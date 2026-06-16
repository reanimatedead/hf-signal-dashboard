#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_macro.py — Macro / お金の流れ レイヤー ビルダ（feat/macro-environment）

設計（BUILD_SPEC v4 §A2/A3 準拠）:
  - 既存 docs/data.json から JP rates / IMM(CFTC) / VIX / yield_curve を **再利用**（再取得しない）
  - 不足分のみ追加取得:
      * 米財務省 TGA（fiscaldata.treasury.gov, キーレス・日次）
      * CoinGecko BTC + ステーブルコイン ペグ（キーレス）
      * FRED（WALCL/RRPONTSYD/DFII10/BAMLH0A0HYM2/DEXJPUS）→ FRED_API_KEY あれば
  - 取れないものは絶対に捏造しない → status:"missing" を明示
  - flow ブロックは常に契約充足（アニメは止まらない）
  - 出力: ./docs/data/macro.json （Cloudflare の publish root 配下）

実行:
  python3 pipeline/build_macro.py
  FRED_API_KEY=xxxx python3 pipeline/build_macro.py
"""

import json
import os
import sys
import socket
import urllib.request
import urllib.parse
import datetime
import pathlib
import math
import csv

socket.setdefaulttimeout(15)

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
EXISTING_DATA = DOCS / "data.json"
VALUATION_CSV = ROOT / "data" / "valuation_metrics.csv"
OUT_DIR = DOCS / "data"
OUT = OUT_DIR / "macro.json"

NOW = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
FRED_KEY = os.environ.get("FRED_API_KEY")


def http_get(url, headers=None, timeout=15):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0 hf-macro/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def days_since(date_str):
    try:
        d = datetime.date.fromisoformat(str(date_str)[:10])
        return (datetime.date.today() - d).days
    except Exception:
        return None


def fred_latest(series_id):
    if not FRED_KEY:
        return None
    try:
        url = ("https://api.stlouisfed.org/fred/series/observations"
               f"?series_id={series_id}&api_key={FRED_KEY}&file_type=json"
               "&sort_order=desc&limit=1")
        d = json.loads(http_get(url))
        obs = d.get("observations") or []
        if obs and obs[0]["value"] not in (".", "", None):
            return float(obs[0]["value"]), obs[0]["date"]
    except Exception as e:
        print(f"  [FRED:{series_id}] fail {type(e).__name__}: {e}", file=sys.stderr)
    return None


def tile(label, value, unit, z, color, as_of, lag_days, status, source, explain, caveat):
    return {"label": label, "value": value, "unit": unit, "z": float(z) if z is not None else 0.0,
            "color": color, "as_of": as_of, "lag_days": lag_days,
            "status": status, "source": source, "explain": explain, "caveat": caveat}


def clamp_color(z, thr_amber=1.0, thr_red=2.0):
    a = abs(z) if z is not None else 0.0
    return "red" if a >= thr_red else ("amber" if a >= thr_amber else "green")


# ─── Load existing docs/data.json (re-use) ─────────────────────────
existing = {}
if EXISTING_DATA.exists():
    try:
        existing = json.loads(EXISTING_DATA.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[warn] failed to parse {EXISTING_DATA}: {e}", file=sys.stderr)

def get_rates_map():
    out = {}
    for r in (existing.get("markets", {}) or {}).get("rates", []) or []:
        sym = r.get("symbol")
        y = r.get("yield")
        if sym and y is not None:
            out[sym] = {"yield": float(y), "source": r.get("source"), "data_status": r.get("data_status")}
    return out


def get_imm_jpy():
    for r in (existing.get("markets", {}) or {}).get("imm", []) or []:
        if r.get("symbol") == "JPY_IMM":
            return r
    return {}


def get_vix_price():
    rows = (existing.get("markets", {}) or {}).get("volatility", []) or []
    if rows:
        v = rows[0]
        for k in ("price", "level", "value"):
            if v.get(k) is not None:
                return float(v[k])
    return None


def get_yield_curve():
    return ((existing.get("meta") or {}).get("yield_curve") or {})


def get_valuation_us():
    """Buffett Indicator US 最新値（data/valuation_metrics.csv から）"""
    if not VALUATION_CSV.exists():
        return None
    try:
        rows = []
        with open(VALUATION_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                sym = (r.get("symbol") or "").upper()
                reg = (r.get("region") or "").upper()
                met = (r.get("metric") or "").lower()
                if sym == "US_BUFFETT_INDICATOR" or (reg == "US" and "buffett" in met):
                    rows.append(r)
        if not rows:
            return None
        rows.sort(key=lambda r: r.get("date") or "")
        latest = rows[-1]
        return {"value": float(latest["value"]), "date": latest.get("date"),
                "source": latest.get("source") or "data/valuation_metrics.csv"}
    except Exception as e:
        print(f"  [valuation] read fail: {e}", file=sys.stderr)
        return None


sources_as_of = {}

tiles = {}
flags = {"live": [], "missing": [], "stale": []}


def record(tid, t):
    tiles[tid] = t
    flags.setdefault(t["status"], []).append(tid)


# ─── existing-derived: JP rates / US rates ────────────────────────
rates = get_rates_map()
yc = get_yield_curve()

# US-JP 10Y spread (USDJPY carry)
usjp10 = yc.get("us_jp_10y_spread", {})
if isinstance(usjp10, dict) and usjp10.get("value") is not None:
    val = round(float(usjp10["value"]), 3)
    # 直近の docs/data.json は generated_at = meta.updated_at
    as_of = existing.get("meta", {}).get("updated_at")
    lag = days_since(as_of) if as_of else None
    status = "ok" if (lag is not None and lag <= 2) else ("stale" if lag is not None else "ok")
    record("usdjpy_carry", tile(
        "ドル円 金利差（US10Y − JP10Y）", val, "%", 0.0, "neutral",
        as_of, lag, status, "docs/data.json (再利用)",
        "差が縮むと円高→キャリー巻き戻し→世界的リスクオフ。",
        "yieldは日替わり。z は履歴ストア未配線のため0（本番ストアで算定予定）。"))
else:
    record("usdjpy_carry", tile(
        "ドル円 金利差（US10Y − JP10Y）", None, "%", 0.0, "neutral",
        None, None, "missing", "docs/data.json (再利用)",
        "差が縮むと円高→キャリー巻き戻し→世界的リスクオフ。",
        "既存 data.json に meta.yield_curve.us_jp_10y_spread が無いため missing。"))


# ─── existing-derived: COT JPY ────────────────────────────────────
imm_jpy = get_imm_jpy()
if imm_jpy and imm_jpy.get("net_position") is not None:
    npos = int(imm_jpy["net_position"])
    chg = imm_jpy.get("weekly_change")
    crowd = imm_jpy.get("crowding_risk")
    date = imm_jpy.get("date")
    lag = days_since(date) if date else None
    # CFTC COT は週次 → 期待ラグ 10 日
    status = "ok" if (lag is not None and lag <= 10) else ("stale" if lag is not None else "ok")
    color = {"high": "red", "medium": "amber", "low": "green"}.get(crowd, "neutral")
    record("cot_jpy", tile(
        "円 投機ポジション(CFTC COT)", {"net": npos, "wow": chg, "crowd": crowd}, "contracts",
        0.0, color, date, lag, status,
        "docs/data.json (CFTC COT, 再利用)",
        "投機筋の円ネットポジション。極端な円売り(マイナス大)は巻き戻しの燃料。",
        "週次・火曜集計の金曜公表。zは履歴ストア未配線のため0（本番で配線）。"))
else:
    record("cot_jpy", tile(
        "円 投機ポジション(CFTC COT)", None, "contracts", 0.0, "neutral",
        None, None, "missing", "docs/data.json (CFTC COT, 再利用)",
        "投機筋の円ネットポジション。", "既存 markets.imm に JPY_IMM が無いため missing。"))


# ─── existing-derived: VIX ────────────────────────────────────────
vix = get_vix_price()
if vix is not None:
    as_of = existing.get("meta", {}).get("updated_at")
    lag = days_since(as_of) if as_of else 0
    status = "ok" if lag is None or lag <= 3 else "stale"
    color = "red" if vix >= 25 else ("amber" if vix >= 18 else "green")
    record("vix", tile(
        "VIX", round(vix, 2), "pt", 0.0, color, as_of, lag, status, "docs/data.json (yfinance, 再利用)",
        "株の予想変動率=恐怖指数。", "同時的で予測ではない。zは履歴ストア未配線のため0。"))
else:
    record("vix", tile(
        "VIX", None, "pt", 0.0, "neutral", None, None, "missing", "docs/data.json",
        "株の予想変動率=恐怖指数。", "既存 data.json に VIX 価格が無いため missing。"))


# ─── existing-derived: Valuation (Buffett US) ─────────────────────
buf = get_valuation_us()
if buf:
    val = round(buf["value"], 1)
    lag = days_since(buf.get("date"))
    status = "ok" if (lag is not None and lag <= 95) else "stale"
    color = "red" if val >= 200 else ("amber" if val >= 150 else "green")
    record("valuation_us", tile(
        "Buffett Indicator (US)", val, "%", 0.0, color, buf.get("date"), lag, status,
        buf.get("source") or "data/valuation_metrics.csv",
        "米株時価総額 / 米GDP。長期の過熱/割安の温度計。",
        "四半期更新（GDP）。水準より傾きを見る。"))
else:
    record("valuation_us", tile(
        "Buffett Indicator (US)", None, "%", 0.0, "neutral", None, None, "missing",
        "data/valuation_metrics.csv",
        "米株時価総額 / 米GDP。", "valuation_metrics.csv が無い／US 行欠損。"))


# ─── LIVE: TGA (Treasury Operating Cash, 日次・キーレス) ───────────
tga_val_bn = None
tga_date = None
try:
    url = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/"
           "operating_cash_balance?fields=record_date,open_today_bal,account_type"
           "&filter=account_type:eq:Treasury%20General%20Account%20(TGA)%20Opening%20Balance"
           "&sort=-record_date&page[size]=1")
    d = json.loads(http_get(url))
    row = (d.get("data") or [{}])[0]
    if row.get("open_today_bal"):
        # API は $M(百万) で返す（v3 シードと同じ）→ $B(十億) に
        tga_val_bn = float(row["open_today_bal"]) / 1000.0
        tga_date = row.get("record_date")
        sources_as_of["treasury_tga"] = tga_date
except Exception as e:
    print(f"  [TGA] fail {type(e).__name__}: {e}", file=sys.stderr)

if tga_val_bn is not None:
    lag = days_since(tga_date)
    status = "ok" if (lag is not None and lag <= 7) else "stale"
    record("tga", tile(
        "米財務省 TGA 残高", round(tga_val_bn, 1), "USD十億", 0.0, "neutral",
        tga_date, lag, status, "fiscaldata.treasury.gov DTS",
        "TGA(政府預金)。増えると市場から流動性を吸う。WALCL/RRPと並ぶ純流動性の3要素。",
        "代理指標。会計サイクル(税収/国債発行)で揺れる。"))
else:
    record("tga", tile(
        "米財務省 TGA 残高", None, "USD十億", 0.0, "neutral", None, None, "missing",
        "fiscaldata.treasury.gov DTS",
        "TGA(政府預金)。", "取得不可のため missing。"))


# ─── LIVE: CoinGecko (BTC + stablecoin peg, キーレス) ──────────────
btc = usdt = usdc = None
try:
    d = json.loads(http_get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,tether,usd-coin&vs_currencies=usd"))
    btc = d.get("bitcoin", {}).get("usd")
    usdt = d.get("tether", {}).get("usd")
    usdc = d.get("usd-coin", {}).get("usd")
    sources_as_of["coingecko"] = NOW
except Exception as e:
    print(f"  [CoinGecko] fail {type(e).__name__}: {e}", file=sys.stderr)

if btc is not None:
    record("btc_price", tile(
        "BTC価格", round(float(btc), 1), "USD", 0.0, "neutral", NOW, 0, "ok",
        "CoinGecko (キーレス)",
        "ビットコインのドル価格。流動性と暗号資産の温度計。",
        "zは履歴ストア未配線のため0。"))
else:
    record("btc_price", tile(
        "BTC価格", None, "USD", 0.0, "neutral", None, None, "missing",
        "CoinGecko",
        "ビットコインのドル価格。", "取得不可のため missing。"))


def _peg_color(p):
    if p is None:
        return "neutral"
    dev = abs(p - 1.0)
    return "green" if dev <= 0.005 else ("amber" if dev <= 0.01 else "red")


if usdt is not None or usdc is not None:
    devs = [abs((usdt or 1) - 1), abs((usdc or 1) - 1)]
    worst = max(devs)
    z_proxy = round(worst / 0.005, 2)  # 0.5%=1z 相当の近似
    record("stablecoin_peg", tile(
        "ステーブルコイン ペグ", {"USDT": usdt, "USDC": usdc}, "USD", z_proxy,
        _peg_color(usdt or usdc), NOW, 0, "ok",
        "CoinGecko (キーレス)",
        "USDT/USDCの1ドルからの乖離。0.5〜1%は日常、10%超が続けば本物のストレス。",
        "薄商い会場の乖離は技術的なこともある。Tetherは完全監査なし。"))
else:
    record("stablecoin_peg", tile(
        "ステーブルコイン ペグ", None, "USD", 0.0, "neutral", None, None, "missing",
        "CoinGecko", "USDT/USDCの1ドルからの乖離。", "取得不可のため missing。"))


# ─── FRED 依存 ────────────────────────────────────────────────────
def fred_tile(tid, label, series, unit, explain, caveat, color_thr=None):
    r = fred_latest(series)
    if r is None:
        why = "FRED_API_KEY 未設定" if not FRED_KEY else "FRED 取得失敗"
        record(tid, tile(label, None, unit, 0.0, "neutral", None, None, "missing",
                         f"FRED:{series}", explain, f"{caveat} ／ {why} のため missing。"))
        return None
    val, dt = r
    sources_as_of.setdefault("fred", dt)
    lag = days_since(dt)
    status = "ok" if (lag is not None and lag <= 7) else "stale"
    color = "neutral"
    if color_thr:
        amber, red = color_thr
        a = abs(val)
        color = "red" if a >= red else ("amber" if a >= amber else "green")
    record(tid, tile(label, round(val, 4), unit, 0.0, color, dt, lag, status,
                     f"FRED:{series}", explain, caveat))
    return val, dt


walcl = fred_tile("walcl", "FRB総資産(WALCL)", "WALCL", "USD百万",
                  "FRBの総資産。お金の総量の源泉。",
                  "週次・木曜更新。単位は百万。net_liquidity 計算に使用。")

rrp = fred_tile("rrp", "翌日物RRP", "RRPONTSYD", "USD十億",
                "中銀に置かれた余り金。増えると市場から流動性を吸う。",
                "単位は十億(WALCLは百万)→揃える。")

real_yield = fred_tile("real_yield", "10年実質金利(DFII10)", "DFII10", "%",
                       "実質金利が下がると金の魅力が増す。",
                       "2022年以降、金vs実質金利は崩れた(中銀/PBOC買い)→regimeシフト注記必須。")

hy = fred_tile("hy_spread", "HY信用スプレッド", "BAMLH0A0HYM2", "%",
               "低格付け社債と国債の利回り差。広がる=リスクオフ。株安に先行しやすい。",
               "FREDは直近3年窓→本番はストアに自前保存。水準より広がる速さ。",
               color_thr=(5.0, 7.0))


# ─── ネット流動性 (WALCL − TGA − RRP) ──────────────────────────────
net_liq_status = "missing"
net_liq_val_tn = None
if walcl and (tga_val_bn is not None) and rrp:
    walcl_bn = walcl[0] / 1000.0  # 百万→十億
    nl_bn = walcl_bn - tga_val_bn - rrp[0]  # すべて十億
    net_liq_val_tn = round(nl_bn / 1000.0, 3)  # 十億→兆
    lag = max(filter(lambda x: x is not None,
                     [days_since(walcl[1]), days_since(tga_date), days_since(rrp[1])]),
              default=7)
    status = "ok" if lag <= 7 else "stale"
    net_liq_status = status
    record("net_liquidity", tile(
        "米ネット流動性 (WALCL−TGA−RRP)", net_liq_val_tn, "USD兆", 0.0, "neutral",
        sources_as_of.get("fred"), lag, status,
        "FRED + Treasury (合成)",
        "市場で実際に使えるドルの総量。増=追い風、減=逆風。",
        "代理指標。単位整合必須(WALCL百万/RRP/TGA十億)。構成で誤誘導しうる。"))
else:
    record("net_liquidity", tile(
        "米ネット流動性 (WALCL−TGA−RRP)", None, "USD兆", 0.0, "neutral", None, None, "missing",
        "FRED + Treasury",
        "市場で実際に使えるドルの総量。",
        "WALCL/RRPはFREDキー必須。欠損時アニメは中立値(6.0兆)で動作。"))


# ─── Clock phase（ナウキャスト未配線・現状 missing 表示） ─────────
record("clock_phase_tile", tile(
    "景気局面", None, "phase", 0.0, "neutral", None, None, "missing",
    "未配線 (GDPNow/Cleveland 予定)",
    "リフレ/回復/過熱/スタグ。お金がどの器に傾くかを決める。",
    "本番ストアに GDPNow+ナウキャストを配線予定。現状は recovery を既定として flow を構成。"))


# ─── flow ブロック（常に契約充足、アニメは止まらない） ───────────
clock_phase = "recovery"  # ナウキャスト未配線時の既定（タイル側は missing 明示）
basin_map = {
    "reflation":   {"stocks": 0.10, "gold": 0.45, "oil": 0.10, "cash": 0.35},
    "recovery":    {"stocks": 0.55, "gold": 0.20, "oil": 0.15, "cash": 0.10},
    "overheat":    {"stocks": 0.20, "gold": 0.30, "oil": 0.45, "cash": 0.05},
    "stagflation": {"stocks": 0.05, "gold": 0.20, "oil": 0.25, "cash": 0.50},
}
basin_tilt = basin_map[clock_phase]
# 念のため正規化（verify gate3: sum(basin_tilt)≒1）
_s = sum(basin_tilt.values()) or 1.0
basin_tilt = {k: round(v / _s, 4) for k, v in basin_tilt.items()}

nl_value_for_flow = net_liq_val_tn if net_liq_val_tn is not None else 6.0
nl_trend = "expand"  # 履歴未配線時の既定

# risk_off: VIX>=25 or HY>=5 で 0.5、>=30 / >=7 で 1.0
risk_off = 0.0
if vix is not None:
    if vix >= 30:
        risk_off = max(risk_off, 1.0)
    elif vix >= 25:
        risk_off = max(risk_off, 0.5)
if hy:
    hyv = hy[0]
    if hyv >= 7.0:
        risk_off = max(risk_off, 1.0)
    elif hyv >= 5.0:
        risk_off = max(risk_off, 0.5)

# JPY IMM ネット → z プロキシ（履歴未配線のためサイズ比例。± で巻き戻し方向）
cot_jpy_z = 0.0
if imm_jpy and imm_jpy.get("net_position") is not None:
    # ±200k contracts ≒ |z|=2 の素朴近似（ストア無しでも方向性は出す）
    cot_jpy_z = max(-3.0, min(3.0, float(imm_jpy["net_position"]) / 100000.0))

# policy_rate_friction: 実質金利を 0–1 にクランプ（参考値）
prf = 0.33
if real_yield:
    prf = max(0.0, min(1.0, float(real_yield[0]) / 3.0 + 0.33))

flow = {
    "net_liquidity": {
        "value_usd_tn": float(nl_value_for_flow),
        "wow_change_tn": 0.0,
        "z": 0.0,
        "trend": nl_trend,
        "status": net_liq_status,
    },
    "clock_phase": clock_phase,
    "policy_rate_friction": round(prf, 3),
    "basin_tilt": basin_tilt,
    "currents": {
        "foreign_jp_flow_z": 0.0,
        "cot_jpy_z": round(cot_jpy_z, 3),
        "risk_off": round(risk_off, 3),
    },
}


# ─── meta ─────────────────────────────────────────────────────────
store_dir = pathlib.Path(os.path.expanduser("~/hf-data-store"))
used_gb = 0.0
if store_dir.exists():
    try:
        used_gb = round(sum(f.stat().st_size for f in store_dir.rglob("*") if f.is_file()) / 1e9, 6)
    except Exception:
        used_gb = 0.0

data = {
    "meta": {
        "generated_at": NOW,
        "pipeline_version": "macro-0.1",
        "reference_seed": False,
        "branch": "feat/macro-environment",
        "note": "JP rates / IMM(CFTC) / VIX / yield_curve は docs/data.json を再利用。FRED 系は FRED_API_KEY 設定時のみ live、未設定なら missing。捏造はしない。",
        "sources_as_of": sources_as_of,
        "store": {"path": str(store_dir), "used_gb": used_gb, "limit_gb": 250},
        "inputs": {
            "existing_data_json": str(EXISTING_DATA.relative_to(ROOT)) if EXISTING_DATA.exists() else None,
            "valuation_csv": str(VALUATION_CSV.relative_to(ROOT)) if VALUATION_CSV.exists() else None,
            "fred_key_set": bool(FRED_KEY),
        },
    },
    "flow": flow,
    "tiles": tiles,
}

OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# 集計
live = sum(1 for t in tiles.values() if t["status"] == "ok")
stale = sum(1 for t in tiles.values() if t["status"] == "stale")
missing = sum(1 for t in tiles.values() if t["status"] == "missing")
print(json.dumps({
    "build": "ok",
    "out": str(OUT.relative_to(ROOT)),
    "tiles_total": len(tiles),
    "live": live,
    "stale": stale,
    "missing": missing,
    "net_liquidity_status": net_liq_status,
    "fred_key_set": bool(FRED_KEY),
}, ensure_ascii=False))
