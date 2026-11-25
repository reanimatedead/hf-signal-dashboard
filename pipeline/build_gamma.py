#!/usr/bin/env python3
"""pipeline/build_gamma.py — dealer gamma-exposure layer → docs/gamma.json.

Reads the CBOE public SPX option chain (gamma/delta/OI/volume/iv are already in
the feed — no Black-Scholes of our own is required for the walls, though total
GEX / zero-gamma recompute gamma from iv per the spec). Emits AGGREGATES ONLY —
the raw chain is never published. < 400 KB.

Chain source, in order (first that works wins):
  1. local archive (~/taka-data/cboe-chains/SPX-YYYY-MM-DD.json.gz, written by
     ~/taka-automation/bin/snapshot_cboe.sh — NOT reimplemented here), only if the
     newest file is at most ARCHIVE_MAX_AGE_DAYS old (older → ignored, reason logged);
  2. the live CBOE public API (timeout 20s, honest UA, no header spoofing);
  3. yfinance SPY options as a PROXY (2026-11-25: cdn.cboe.com now 307-redirects to
     cdn-api.cboe.com, which Cloudflare blocks with 403 for every client). Gamma is
     computed with our own Black-Scholes; strikes/spot/zero_gamma/walls are scaled
     to the SPX level by ratio = ^GSPC/SPY. Dollar GEX is unchanged by the scaling
     (contracts are converted to SPX-equivalent OI = OI / ratio).
If all three fail an error payload is written and we still exit 0 (deploy must not fail).
We never work around the Cloudflare block (no spoofed headers, cookies, headless browsers or proxies).

Supplementary VIX / VIX3M / SKEW come from CBOE public CSVs, falling back to the
yfinance ^VIX / ^VIX3M / ^SKEW last close; MOVE/VIX uses docs/data.json.

Standalone:
    python3 pipeline/build_gamma.py
"""
import glob
import gzip
import json
import math
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timezone
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "gamma.json"
DATA_JSON = ROOT / "docs" / "data.json"

CHAIN_LIVE = "https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json"
CHAIN_DIR = os.path.expanduser("~/taka-data/cboe-chains")
CSV_BASE = "https://cdn.cboe.com/api/global/us_indices/daily_prices"
_UA = {"User-Agent": "hf-signal-dashboard gamma (CBOE public)"}
CBOE_TIMEOUT = 20
ARCHIVE_MAX_AGE_DAYS = 4
# yfinance SPY proxy
YF_SOURCE = "yfinance:SPY_proxy_scaled_to_SPX"
YF_MAX_DAYS = 60          # expiries within 60 days
YF_MAX_EXPIRIES = 12      # at most 12 expiries (one network call each)
YF_BUDGET_S = 90          # overall time budget for the option chains
DEFAULT_SCALE_RATIO = 10.0
R = 0.038

import re
PAT = re.compile(r'^SPXW?(\d{6})([CP])(\d{8})$')


def _http_bytes(url, timeout=CBOE_TIMEOUT):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _npdf(x):
    """Standard normal pdf (math only — no scipy)."""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bs_gamma(S, K, T, iv, r=R):
    """Black-Scholes gamma (same for calls and puts)."""
    if S <= 0 or K <= 0 or iv <= 0 or T <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + iv * iv / 2) * T) / (iv * math.sqrt(T))
    return _npdf(d1) / (S * iv * math.sqrt(T))


def load_chain_archive(today, chain_dir=None, max_age_days=ARCHIVE_MAX_AGE_DAYS):
    """(chain_dict, source) from the newest local archive, or None.
    Used only when the file date (SPX-YYYY-MM-DD.json.gz) is at most max_age_days old."""
    chain_dir = chain_dir or CHAIN_DIR
    if not os.path.isdir(chain_dir):
        return None
    files = sorted(glob.glob(os.path.join(chain_dir, "SPX-*.json.gz")), reverse=True)
    if not files:
        return None
    name = os.path.basename(files[0])
    try:
        fdate = date.fromisoformat(name[4:14])
    except ValueError:
        print(f"  [chain] archive {name}: no date in file name; ignored")
        return None
    age = (today - fdate).days
    if age > max_age_days:
        print(f"  [chain] archive {name} is {age} days old (> {max_age_days}); ignored")
        return None
    try:
        with gzip.open(files[0]) as f:
            return json.load(f), f"local:{name}"
    except Exception as exc:
        print(f"  [chain] local archive read failed ({exc}); trying the next source")
        return None


def load_chain_cboe(fetch=None):
    """(chain_dict, source) from the live CBOE public API. Raises on failure."""
    fetch = fetch or _http_bytes
    data = json.loads(fetch(CHAIN_LIVE).decode("utf-8", errors="replace"))
    return data, "live:cboe-api"


def load_chain():
    """Backward-compatible: (chain_dict, source) from archive (fresh) or live CBOE."""
    a = load_chain_archive(datetime.now(timezone.utc).date())
    return a if a else load_chain_cboe()


def _yf_module(yf_mod=None):
    if yf_mod is not None:
        return yf_mod
    import yfinance  # already a dependency (pyproject / uv.lock)
    return yfinance


def _last_close(ticker):
    """Last non-NaN daily close of a yfinance Ticker, or None."""
    try:
        h = ticker.history(period="5d")
        c = h["Close"].dropna()
        return float(c.iloc[-1]) if len(c) else None
    except Exception as exc:
        print(f"  [yf] history failed ({type(exc).__name__}: {exc})")
        return None


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def load_chain_yf(yf_mod=None, today=None, clock=time.monotonic, budget_s=YF_BUDGET_S, now=None):
    """SPY options from yfinance as an SPX proxy. Returns a chain dict (see _chain_from_cboe).

    recs are converted to the SPX scale so the existing gex_at / zero_gamma / gamma_walls
    work unchanged: K*ratio, gamma/ratio, OI/ratio, volume/ratio. Dollar GEX
    (gamma * OI * 100 * S^2 * 0.01) is identical to the SPY-unit value.
    Raises if SPY spot or every option row is unavailable."""
    yf = _yf_module(yf_mod)
    now = now or datetime.now(timezone.utc)
    today = today or now.astimezone(ZoneInfo("America/New_York")).date()
    t0 = clock()
    spy_t = yf.Ticker("SPY")
    spy = _last_close(spy_t)
    if not spy:
        raise RuntimeError("SPY close unavailable")
    spx = _last_close(yf.Ticker("^GSPC"))
    if spx:
        ratio = spx / spy
    else:
        ratio = DEFAULT_SCALE_RATIO
        print(f"  [yf] scale_ratio_note: ^GSPC close unavailable; using default ratio {ratio}")
    exps = []
    for e in list(spy_t.options or []):
        try:
            ed = date.fromisoformat(str(e))
        except ValueError:
            continue
        if 0 <= (ed - today).days <= YF_MAX_DAYS:
            exps.append(ed)
    exps = sorted(exps)[:YF_MAX_EXPIRIES]
    recs = []
    for ed in exps:
        if clock() - t0 > budget_s:
            print(f"  [yf] time budget {budget_s}s reached; stopping at {len(recs)} contracts")
            break
        try:
            ch = spy_t.option_chain(ed.isoformat())  # one network call per expiry
        except Exception as exc:
            print(f"  [yf] option_chain({ed}) failed ({type(exc).__name__}: {exc})")
            continue
        T = max((ed - today).days / 365.0, 1 / 365)
        for cp, df in (("C", ch.calls), ("P", ch.puts)):
            for K, oi, iv, vol in zip(df["strike"], df["openInterest"], df["impliedVolatility"], df["volume"]):
                K, oi, iv, vol = _num(K), _num(oi), _num(iv), _num(vol)
                if oi <= 0 or iv <= 0 or K <= 0:
                    continue
                g = bs_gamma(spy, K, T, iv)
                recs.append((cp, K * ratio, T, iv, g / ratio, oi / ratio, vol / ratio, ed))
    if not recs:
        raise RuntimeError("no usable SPY option rows (OI>0 and IV>0)")
    return {"spot": spy * ratio, "recs": recs, "source": YF_SOURCE, "timestamp": now.isoformat(),
            "date": today, "proxy": "SPY", "scale_ratio": round(ratio, 4)}


def _chain_from_cboe(chain, src, now):
    """CBOE-format chain → the common chain dict (spot, recs, source, timestamp, date, proxy, scale_ratio)."""
    ts = chain.get("timestamp", "")
    try:
        snap_date = datetime.fromisoformat(ts[:10]).date()
    except Exception:
        snap_date = now.date()
    spot, recs = parse_chain(chain, snap_date)
    return {"spot": spot, "recs": recs, "source": src, "timestamp": ts, "date": snap_date,
            "proxy": None, "scale_ratio": None}


def get_chain(now, chain_dir=None, cboe=load_chain_cboe, yf_loader=load_chain_yf):
    """Try archive (fresh) → CBOE live → yfinance SPY. Raises RuntimeError if all fail."""
    errors = []
    a = load_chain_archive(now.date(), chain_dir)
    if a:
        return _chain_from_cboe(a[0], a[1], now)
    try:
        chain, src = cboe()
        return _chain_from_cboe(chain, src, now)
    except Exception as exc:
        print(f"  [gamma] CBOE live failed ({type(exc).__name__}: {exc}); trying yfinance SPY")
        errors.append(f"cboe: {type(exc).__name__}")
    try:
        return yf_loader()
    except Exception as exc:
        print(f"  [gamma] yfinance SPY failed ({type(exc).__name__}: {exc})")
        errors.append(f"yfinance: {type(exc).__name__}")
    raise RuntimeError("all chain sources failed: " + "; ".join(errors))


def _spot(d):
    """Spot from the chain payload; the feed carries data.close."""
    dd = d.get("data", {})
    for k in ("close", "current_price", "last"):
        v = dd.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def parse_chain(d, today):
    """(spot, recs) with recs = [(cp, K, T, iv, gamma, oi, vol, exp)]; OI>0 only."""
    S = _spot(d)
    recs = []
    for x in d["data"]["options"]:
        m = PAT.match(x["option"])
        if not m:
            continue
        ymd, cp, k = m.groups()
        exp = date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6]))
        T = max((exp - today).days / 365.0, 1 / 365)
        oi = x.get("open_interest") or 0
        if oi <= 0:
            continue
        recs.append((cp, int(k) / 1000.0, T, x.get("iv") or 0,
                     x.get("gamma") or 0, oi, x.get("volume") or 0, exp))
    return S, recs


def gex_at(recs, spot, r=R):
    """慣習的仮定: ディーラーはコール買い / プット売り。OI ベース、gamma を iv から再計算。"""
    tot = 0.0
    for cp, K, T, iv, g, oi, vol, exp in recs:
        if iv <= 0 or T <= 0:
            continue
        d1 = (math.log(spot / K) + (r + iv * iv / 2) * T) / (iv * math.sqrt(T))
        gam = _npdf(d1) / (spot * iv * math.sqrt(T))
        v = gam * oi * 100 * spot * spot * 0.01
        tot += v if cp == "C" else -v
    return tot


def zero_gamma(recs, S, lo_mult=0.85, hi_mult=1.15):
    lo, hi = S * lo_mult, S * hi_mult
    if gex_at(recs, lo) * gex_at(recs, hi) >= 0:
        return None
    for _ in range(40):
        mid = (lo + hi) / 2
        if gex_at(recs, lo) * gex_at(recs, mid) < 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def gamma_walls(recs, S, bucket=25, top=10):
    """Strike walls using the CBOE-provided per-contract gamma (OI-weighted)."""
    by = defaultdict(float)
    for cp, K, T, iv, g, oi, vol, exp in recs:
        v = g * oi * 100 * S * S * 0.01
        by[round(K / bucket) * bucket] += v if cp == "C" else -v
    return sorted(by.items(), key=lambda x: -abs(x[1]))[:top]


def gex_volume_0dte(recs, spot, today, r=R):
    """0DTE GEX on the *volume* side (OI-based GEX understates the intraday 0DTE
    amplification that evaporates at the close). Kept SEPARATE from gex_oi."""
    tot, n = 0.0, 0
    for cp, K, T, iv, g, oi, vol, exp in recs:
        if exp != today or vol <= 0 or iv <= 0:
            continue
        d1 = (math.log(spot / K) + (r + iv * iv / 2) * T) / (iv * math.sqrt(T))
        gam = _npdf(d1) / (spot * iv * math.sqrt(T))
        v = gam * vol * 100 * spot * spot * 0.01
        tot += v if cp == "C" else -v
        n += 1
    return tot, n


def _csv_latest_close(name):
    """Latest CLOSE from a CBOE daily-price CSV (DATE,OPEN,HIGH,LOW,CLOSE)."""
    try:
        body = _http_bytes(f"{CSV_BASE}/{name}").decode("utf-8", errors="replace")
        rows = [ln.split(",") for ln in body.splitlines() if ln.strip()]
        for r in reversed(rows[1:]):
            try:
                return round(float(r[-1]), 4)
            except (ValueError, IndexError):
                continue
    except Exception as exc:
        print(f"  [csv] {name} failed ({type(exc).__name__}: {exc})")
    return None


def _move_vix_from_data_json():
    """(MOVE, VIX) latest prices from docs/data.json markets.volatility, or (None,None)."""
    try:
        d = json.load(open(DATA_JSON, encoding="utf-8"))
        px = {r.get("symbol"): r.get("price") for r in d["markets"].get("volatility", [])}
        return px.get("MOVE"), px.get("VIX")
    except Exception:
        return None, None


def _yf_index_close(sym, yf_mod=None):
    """Last close of an index via yfinance (^VIX / ^VIX3M / ^SKEW), or None."""
    try:
        v = _last_close(_yf_module(yf_mod).Ticker(sym))
        return round(v, 4) if v else None
    except Exception as exc:
        print(f"  [yf] {sym} failed ({type(exc).__name__}: {exc})")
        return None


VOL_SOURCES = (("vix", "VIX_History.csv", "^VIX"), ("vix3m", "VIX3M_History.csv", "^VIX3M"),
               ("skew", "SKEW_History.csv", "^SKEW"))


def vol_inputs(csv=None, yf_close=None):
    """{vix, vix3m, skew}: CBOE CSV first, then the yfinance last close, else None."""
    csv = csv or _csv_latest_close
    yf_close = yf_close or _yf_index_close
    out = {}
    for key, name, sym in VOL_SOURCES:
        v = csv(name)
        if v is None:
            v = yf_close(sym)
        out[key] = v
    return out


def main(chain_dir=None, cboe=load_chain_cboe, yf_loader=load_chain_yf, csv=None, yf_close=None):
    now = datetime.now(timezone.utc)
    try:
        c = get_chain(now, chain_dir=chain_dir, cboe=cboe, yf_loader=yf_loader)
    except Exception as exc:
        print(f"  [gamma] chain load failed ({type(exc).__name__}: {exc})")
        payload = {"as_of": now.isoformat(), "data_status": "error",
                   "error": "exception",
                   "assumption": "naive_dealer_convention",
                   "note": "chain_unavailable_degraded",   # chain unavailable; layer degraded.
                   "coverage": {"us": "unavailable", "eu": "unavailable", "jp": "unavailable"},
                   "disclaimer": "disclaimer_data_viz_not_advice"}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        return 0

    chain_src, ts, snap_date = c["source"], c["timestamp"], c["date"]
    spot, recs = c["spot"], c["recs"]
    total_gex = gex_at(recs, spot) if (spot and recs) else None
    zg = zero_gamma(recs, spot) if (spot and recs) else None
    walls = gamma_walls(recs, spot) if (spot and recs) else []
    gex0, n0 = gex_volume_0dte(recs, spot, snap_date) if (spot and recs) else (None, 0)
    # How many contracts in the feed actually expire on the snapshot date. The
    # public _SPX feed is a DELAYED snapshot taken at the prior session's close,
    # so same-day (0DTE) contracts have already expired and are absent — this
    # source structurally cannot capture 0DTE. When 0, we report gex_volume_0dte
    # as null + status "unavailable" (not 0) to avoid the "no 0DTE exists" misread.
    n_0dte_contracts = sum(1 for r in recs if r[7] == snap_date)
    _0dte_captured = n_0dte_contracts > 0
    # この CBOE 遅延フィードは前営業日引け時点のスナップショットのため当日満期(0DTE)は既に消えており捕捉できない。
    # gex_volume_0dte は 0DTE の実態を表さない。gex_oi も 0DTE を過小評価。リアルタイムフィードは無料では入手できない。
    _0dte_reason = "delayed_snapshot_no_0dte"

    # volatility structure (CBOE CSV → yfinance last close → None)
    vi = vol_inputs(csv=csv, yf_close=yf_close)
    vix, vix3m, skew = vi["vix"], vi["vix3m"], vi["skew"]
    move, vix_dj = _move_vix_from_data_json()
    vix_for_move = vix or vix_dj
    term = (round(vix3m / vix, 4) if (vix and vix3m and vix) else None)
    move_vix = (round(move / vix_for_move, 4) if (move and vix_for_move) else None)

    payload = {
        "as_of": now.isoformat(),
        "snapshot": {"source": chain_src, "timestamp": ts, "date": snap_date.isoformat()},
        # SPY proxy (yfinance) when CBOE is unavailable: strikes/spot/zero_gamma/walls are on the SPX scale
        "proxy": c["proxy"],
        "scale_ratio": c["scale_ratio"],
        "data_status": "live" if (spot and recs) else "error",
        "spot": round(spot, 2) if spot else None,
        "n_contracts_oi": len(recs),
        # OI-based dealer gamma exposure ($ per 1% move). USD.
        "gex_oi": round(total_gex) if total_gex is not None else None,
        "gex_oi_bn": round(total_gex / 1e9, 2) if total_gex is not None else None,
        "zero_gamma": round(zg, 1) if zg is not None else None,
        "flip_vs_spot": ("below_flip_amplifying" if (spot and zg and spot < zg)
                         else "above_flip_dampening" if (spot and zg and spot >= zg)
                         else "unknown"),
        "gamma_walls": [{"strike": k, "gex": round(v), "gex_bn": round(v / 1e9, 2)} for k, v in walls],
        # 0DTE volume-based GEX, kept SEPARATE (not summed with gex_oi). This
        # DELAYED feed cannot capture 0DTE (prior-close snapshot), so when no 0DTE
        # contracts are present we emit null + status "unavailable" + reason rather
        # than a misleading 0.
        "gex_volume_0dte": (round(gex0) if (_0dte_captured and gex0 is not None) else None),
        "gex_volume_0dte_bn": (round(gex0 / 1e9, 2) if (_0dte_captured and gex0 is not None) else None),
        "gex_volume_0dte_status": ("live" if _0dte_captured else "unavailable"),
        "gex_volume_0dte_reason": (None if _0dte_captured else _0dte_reason),
        "n_0dte_volume": n0,
        "n_0dte_contracts": n_0dte_contracts,
        "vol_structure": {
            "vix": vix, "vix3m": vix3m, "skew": skew, "move": move,
            "vix3m_vix_ratio": term,
            "term_state": ("contango" if (term and term > 1) else
                           "backwardation" if (term and term <= 1) else "unknown"),
            "move_vix_ratio": move_vix,
            "note": "vol_structure_note",   # VIX3M/VIX>1=contango(平常)/<1=backwardation(ストレス)。MOVE/VIX=金利ボラ対株ボラ
        },
        "assumption": "naive_dealer_convention",
        # ディーラーがコール買い/プット売りという慣習的仮定に基づく。CBOEは売買主体を公開していない。仮定が外れると符号が反転する。
        "note": "naive_dealer_assumption_note",
        # 現値がフリップ(zero_gamma)より下＝負ガンマ＝増幅ゾーン（下落で売り上昇で買い）。上＝正ガンマ＝値が貼り付く。
        "reading": "gamma_flip_reading",
        # OI ベース GEX は 0DTE を過小評価。本フィードは遅延のため 0DTE を捕捉できず gex_volume_0dte は unavailable。gex_oi と合算しない。
        "zero_dte_note": "zero_dte_note",
        "coverage": {"us": "full", "eu": "unavailable", "jp": "unavailable"},
        "coverage_note": "us_only_no_greeks_jpx_eurex",   # この層は米国のみ。JPX/Eurex はギリシャ文字を公開していない
        "disclaimer": "disclaimer_data_viz_not_advice",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n✅ gamma.json → {OUT} ({OUT.stat().st_size} B)")
    print(f"   src={chain_src} proxy={c['proxy']} ratio={c['scale_ratio']} spot={payload['spot']} n_oi={len(recs)} "
          f"GEX={payload['gex_oi_bn']}bn zero_gamma={payload['zero_gamma']} "
          f"0dte_vol={payload['gex_volume_0dte_bn']}bn (n={n0})")
    if walls:
        print(f"   top wall: {walls[0][0]} ({round(walls[0][1]/1e9,2)}bn)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
