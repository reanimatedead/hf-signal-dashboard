#!/usr/bin/env python3
"""pipeline/build_gamma.py — dealer gamma-exposure layer → docs/gamma.json.

Reads the CBOE public SPX option chain (gamma/delta/OI/volume/iv are already in
the feed — no Black-Scholes of our own is required for the walls, though total
GEX / zero-gamma recompute gamma from iv per the spec). Emits AGGREGATES ONLY —
the raw chain is never published. < 400 KB.

Chain source: local archive (~/taka-data/cboe-chains/SPX-YYYY-MM-DD.json.gz,
written by ~/taka-automation/bin/snapshot_cboe.sh — NOT reimplemented here) is
preferred; if absent (e.g. CI has no ~/taka-data) it falls back to the live CBOE
API. Supplementary VIX / VIX3M / SKEW come from CBOE public CSVs; MOVE/VIX uses
docs/data.json.

Standalone:
    python3 pipeline/build_gamma.py
"""
import glob
import gzip
import json
import math
import os
import sys
import urllib.request
from datetime import date, datetime, timezone
from collections import defaultdict
from pathlib import Path

from scipy.stats import norm

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "gamma.json"
DATA_JSON = ROOT / "docs" / "data.json"

CHAIN_LIVE = "https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json"
CHAIN_DIR = os.path.expanduser("~/taka-data/cboe-chains")
CSV_BASE = "https://cdn.cboe.com/api/global/us_indices/daily_prices"
_UA = {"User-Agent": "hf-signal-dashboard gamma (CBOE public)"}

import re
PAT = re.compile(r'^SPXW?(\d{6})([CP])(\d{8})$')


def _http_bytes(url, timeout=60):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def load_chain():
    """Return (chain_dict, source_str). Prefer the newest local archive; else live."""
    if os.path.isdir(CHAIN_DIR):
        files = sorted(glob.glob(os.path.join(CHAIN_DIR, "SPX-*.json.gz")), reverse=True)
        if files:
            try:
                with gzip.open(files[0]) as f:
                    return json.load(f), f"local:{os.path.basename(files[0])}"
            except Exception as exc:
                print(f"  [chain] local archive read failed ({exc}); falling back to live")
    data = json.loads(_http_bytes(CHAIN_LIVE).decode("utf-8", errors="replace"))
    return data, "live:cboe-api"


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


def gex_at(recs, spot, r=0.038):
    """慣習的仮定: ディーラーはコール買い / プット売り。OI ベース、gamma を iv から再計算。"""
    tot = 0.0
    for cp, K, T, iv, g, oi, vol, exp in recs:
        if iv <= 0 or T <= 0:
            continue
        d1 = (math.log(spot / K) + (r + iv * iv / 2) * T) / (iv * math.sqrt(T))
        gam = norm.pdf(d1) / (spot * iv * math.sqrt(T))
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


def gex_volume_0dte(recs, spot, today, r=0.038):
    """0DTE GEX on the *volume* side (OI-based GEX understates the intraday 0DTE
    amplification that evaporates at the close). Kept SEPARATE from gex_oi."""
    tot, n = 0.0, 0
    for cp, K, T, iv, g, oi, vol, exp in recs:
        if exp != today or vol <= 0 or iv <= 0:
            continue
        d1 = (math.log(spot / K) + (r + iv * iv / 2) * T) / (iv * math.sqrt(T))
        gam = norm.pdf(d1) / (spot * iv * math.sqrt(T))
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


def main():
    now = datetime.now(timezone.utc)
    try:
        chain, chain_src = load_chain()
    except Exception as exc:
        print(f"  [gamma] chain load failed ({type(exc).__name__}: {exc})")
        payload = {"as_of": now.isoformat(), "data_status": "error",
                   "error": str(exc)[:160],
                   "assumption": "naive_dealer_convention",
                   "note": "chain unavailable; layer degraded.",
                   "coverage": {"us": "unavailable", "eu": "unavailable", "jp": "unavailable"},
                   "disclaimer": "For data visualization purposes only. Not investment advice."}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        return 0

    # snapshot date = chain timestamp date (fallback: today UTC)
    ts = chain.get("timestamp", "")
    try:
        snap_date = datetime.fromisoformat(ts[:10]).date()
    except Exception:
        snap_date = now.date()

    spot, recs = parse_chain(chain, snap_date)
    total_gex = gex_at(recs, spot) if (spot and recs) else None
    zg = zero_gamma(recs, spot) if (spot and recs) else None
    walls = gamma_walls(recs, spot) if (spot and recs) else []
    gex0, n0 = gex_volume_0dte(recs, spot, snap_date) if (spot and recs) else (None, 0)
    # How many contracts in the feed actually expire on the snapshot date. The
    # public delayed _SPX feed carries standard (monthly) expiries; sub-monthly
    # SPXW dailies/weeklies are often absent, so 0DTE can legitimately be 0.
    n_0dte_contracts = sum(1 for r in recs if r[7] == snap_date)

    # volatility structure
    vix = _csv_latest_close("VIX_History.csv")
    vix3m = _csv_latest_close("VIX3M_History.csv")
    skew = _csv_latest_close("SKEW_History.csv")
    move, vix_dj = _move_vix_from_data_json()
    vix_for_move = vix or vix_dj
    term = (round(vix3m / vix, 4) if (vix and vix3m and vix) else None)
    move_vix = (round(move / vix_for_move, 4) if (move and vix_for_move) else None)

    payload = {
        "as_of": now.isoformat(),
        "snapshot": {"source": chain_src, "timestamp": ts, "date": snap_date.isoformat()},
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
        # 0DTE volume-based GEX, kept SEPARATE (not summed with gex_oi).
        "gex_volume_0dte": round(gex0) if gex0 is not None else None,
        "gex_volume_0dte_bn": round(gex0 / 1e9, 2) if gex0 is not None else None,
        "n_0dte_volume": n0,
        "n_0dte_contracts": n_0dte_contracts,
        "vol_structure": {
            "vix": vix, "vix3m": vix3m, "skew": skew, "move": move,
            "vix3m_vix_ratio": term,
            "term_state": ("contango" if (term and term > 1) else
                           "backwardation" if (term and term <= 1) else "unknown"),
            "move_vix_ratio": move_vix,
            "note": "VIX3M/VIX>1=contango(平常)/<1=backwardation(ストレス)。MOVE/VIX=金利ボラ対株ボラ。",
        },
        "assumption": "naive_dealer_convention",
        "note": ("ディーラーがコール買い/プット売りという慣習的仮定に基づく。"
                 "CBOEは売買主体を公開していない。仮定が外れると符号が反転する。"),
        "reading": ("現値がフリップ(zero_gamma)より下＝負ガンマ＝増幅ゾーン（下落で売り上昇で買い）。"
                    "上＝正ガンマ＝値が貼り付く。"),
        "zero_dte_note": ("建玉(OI)ベースGEXは寄り引けで消える0DTEを過小評価する。日中の増幅は"
                          "出来高側(gex_volume_0dte)に出る。gex_oiと合算しない。"),
        "coverage": {"us": "full", "eu": "unavailable", "jp": "unavailable"},
        "coverage_note": "この層は米国のみ。JPX/Eurex はギリシャ文字を公開していない。",
        "disclaimer": "For data visualization purposes only. Not investment advice.",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n✅ gamma.json → {OUT} ({OUT.stat().st_size} B)")
    print(f"   src={chain_src} spot={payload['spot']} n_oi={len(recs)} "
          f"GEX={payload['gex_oi_bn']}bn zero_gamma={payload['zero_gamma']} "
          f"0dte_vol={payload['gex_volume_0dte_bn']}bn (n={n0})")
    if walls:
        print(f"   top wall: {walls[0][0]} ({round(walls[0][1]/1e9,2)}bn)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
