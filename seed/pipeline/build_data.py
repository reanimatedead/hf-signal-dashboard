#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HF Signal Dashboard — 参照シード パイプライン (build_data.py)
- キーレスで取れる実データ: 米財務省 TGA(日次), CoinGecko(BTC価格, USDT/USDCペグ)
- FRED系(WALCL/RRP/DFII10/HY/VIX等)は FRED_API_KEY 環境変数があればライブ、無ければ status:"missing"(正直)
- 取得できないものは絶対に捏造しない。status を missing/stale で明示。
- flow ブロックは常に契約充足(アニメが動く)。
出力: ../public/data.json  (このスクリプトから見て)
本番(MacBook)では A1→A2 がこの役割を担い、~/hf-data-store/ の長期履歴で z を算定する。
"""
import json, os, sys, time, socket, urllib.request, datetime, pathlib

socket.setdefaulttimeout(10)
ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
PUBLIC.mkdir(exist_ok=True)
NOW = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
FRED_KEY = os.environ.get("FRED_API_KEY")  # 無ければ FRED系は missing

def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r:
        return r.read().decode()

def fred_latest(series_id):
    """FREDの最新値。キー無し or 失敗なら None。"""
    if not FRED_KEY:
        return None
    try:
        url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}"
               f"&api_key={FRED_KEY}&file_type=json&sort_order=desc&limit=1")
        d = json.loads(http_get(url))
        obs = d.get("observations", [])
        if obs and obs[0]["value"] not in (".", ""):
            return float(obs[0]["value"]), obs[0]["date"]
    except Exception:
        return None
    return None

def days_since(date_str):
    try:
        d = datetime.date.fromisoformat(date_str[:10])
        return (datetime.date.today() - d).days
    except Exception:
        return None

def tile(label, value, unit, z, color, as_of, lag_days, status, source, explain, caveat):
    return {"label": label, "value": value, "unit": unit, "z": z, "color": color,
            "as_of": as_of, "lag_days": lag_days, "status": status, "source": source,
            "explain": explain, "caveat": caveat}

tiles = {}
sources_as_of = {}

# ---- LIVE: 米財務省 TGA (日次・キーレス) ----
tga_val = tga_date = None
try:
    url = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/"
           "operating_cash_balance?fields=record_date,open_today_bal,account_type"
           "&filter=account_type:eq:Treasury%20General%20Account%20(TGA)%20Opening%20Balance"
           "&sort=-record_date&page[size]=1")
    d = json.loads(http_get(url))
    row = (d.get("data") or [{}])[0]
    tga_date = row.get("record_date")
    tga_val = float(row.get("open_today_bal")) / 1000.0 if row.get("open_today_bal") else None  # $M→$B
    sources_as_of["treasury"] = tga_date
except Exception:
    pass

# ---- LIVE: CoinGecko BTC + ステーブルコイン ペグ (キーレス) ----
btc = usdt = usdc = None
try:
    d = json.loads(http_get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,tether,usd-coin&vs_currencies=usd"))
    btc = d.get("bitcoin", {}).get("usd")
    usdt = d.get("tether", {}).get("usd")
    usdc = d.get("usd-coin", {}).get("usd")
    sources_as_of["crypto"] = NOW
except Exception:
    pass

def peg_color(p):
    if p is None: return "neutral"
    dev = abs(p - 1.0)
    return "green" if dev <= 0.005 else ("amber" if dev <= 0.01 else "red")

# BTC価格タイル
if btc is not None:
    tiles["btc_price"] = tile("BTC価格", round(btc, 1), "USD", 0.0, "neutral", NOW, 0, "ok", "live",
        "ビットコインのドル価格。希薄化トレードと暗号資産の温度計。",
        "シードは履歴なしのためz=0。本番はストア履歴でz算定。")
else:
    tiles["btc_price"] = tile("BTC価格", None, "USD", 0.0, "neutral", None, None, "missing", "live",
        "ビットコインのドル価格。", "取得不可のため missing。")

# ステーブルコインペグ
if usdt is not None or usdc is not None:
    worst = max([abs((usdt or 1)-1), abs((usdc or 1)-1)])
    tiles["stablecoin_peg"] = tile("ステーブルコイン ペグ", {"USDT": usdt, "USDC": usdc}, "USD",
        round(worst/0.005, 2), peg_color((usdt or usdc)), NOW, 0, "ok", "live",
        "USDT/USDCの1ドルからの乖離。0.5〜1%は日常、10%超が続けば本物のストレス。",
        "薄商い会場の乖離は技術的なこともある。Tetherは完全監査なし(アテステーションのみ)。")
else:
    tiles["stablecoin_peg"] = tile("ステーブルコイン ペグ", None, "USD", 0.0, "neutral", None, None, "missing", "live",
        "USDT/USDCの1ドルからの乖離。", "取得不可のため missing。")

# ---- FRED依存(キーがあればライブ・無ければ missing) ----
def fred_tile(tid, label, series, unit, explain, caveat):
    r = fred_latest(series)
    if r is None:
        tiles[tid] = tile(label, None, unit, 0.0, "neutral", None, None, "missing", "live",
            explain, (caveat + " ／ FRED_API_KEY未設定のため missing。"))
        return None
    val, dt = r
    sources_as_of["fred"] = dt
    lag = days_since(dt)
    status = "ok" if (lag is not None and lag <= 7) else "stale"
    tiles[tid] = tile(label, round(val, 4), unit, 0.0, "neutral", dt, lag, status, "live", explain, caveat)
    return val, dt

walcl = fred_tile("walcl", "FRB総資産(WALCL)", "WALCL", "USD(百万)",
    "FRBの総資産。お金の総量の源泉。", "週次・木曜更新。単位は百万。")
rrp = fred_tile("rrp", "翌日物RRP", "RRPONTSYD", "USD(十億)",
    "中銀に置かれた余り金。増えると市場から流動性を吸う。", "単位は十億(WALCLは百万)→揃える。")
fred_tile("real_yield", "10年実質金利(DFII10)", "DFII10", "%",
    "実質金利が下がると金の魅力が増す。", "2022年以降、金vs実質金利は崩れた(中銀/PBOC買い)→注記必須。")
fred_tile("hy_spread", "HY信用スプレッド", "BAMLH0A0HYM2", "%",
    "低格付け社債と国債の利回り差。広がる=リスクオフ。株安に先行しやすい。",
    "FREDは直近3年窓→本番はストアに自前保存。水準より広がる速さ。")
fred_tile("vix", "VIX", "VIXCLS", "pt",
    "株の予想変動率=恐怖指数。", "同時的で予測ではない。")

# ---- ネット流動性 (WALCL − TGA − RRP) ----
# WALCL[百万], TGA[十億→百万に揃える], RRP[十億→百万]
net_liq_status = "missing"; net_liq_val = None; net_liq_src = "live"
if walcl and (tga_val is not None) and rrp:
    walcl_bn = walcl[0] / 1000.0          # 百万→十億
    nl_bn = walcl_bn - tga_val - rrp[0]    # すべて十億
    net_liq_val = round(nl_bn / 1000.0, 3) # 十億→兆
    net_liq_status = "ok"
    tiles["net_liquidity"] = tile("米ネット流動性", net_liq_val, "USD兆", 0.0, "neutral",
        sources_as_of.get("fred"), 1, "ok", "live",
        "市場で実際に使えるドルの総量(WALCL−TGA−RRP)。増=追い風、減=逆風。",
        "代理指標。単位整合必須(WALCL百万/RRP十億)。構成で誤誘導しうる。")
else:
    tiles["net_liquidity"] = tile("米ネット流動性", None, "USD兆", 0.0, "neutral", None, None, "missing", "live",
        "市場で実際に使えるドルの総量(WALCL−TGA−RRP)。",
        "WALCL/RRPはFREDキー必須。シードでは欠損→アニメは中立値で動作。")

# ---- まだ配線していないタイル(本番A1で追加予定)→ 正直に missing ----
for tid, label, explain, caveat in [
    ("usdjpy_carry", "ドル円+日米金利差", "差が縮むと円高→キャリー巻き戻し→世界的リスクオフ。", "本番でFRED DEXJPUS+政策金利を配線。"),
    ("cot_jpy", "円 投機ポジション(COT)", "投機筋の円売り/買い越し。極端な円売りは巻き戻しの燃料。", "本番でCFTC COTのJPY契約を配線。"),
    ("foreign_jp_flow", "海外投資家フロー(JPX)", "日本株を動かす主役。売り越し転換は日本株安(ショート追い風)。", "本番でJPX投資部門別(週間)を配線。"),
    ("clock_phase_tile", "景気局面", "リフレ/回復/過熱/スタグ。お金がどの器に傾くかを決める。", "本番でGDPNow+ナウキャストを配線。"),
]:
    tiles[tid] = tile(label, None, "-", 0.0, "neutral", None, None, "missing", "live", explain, caveat)

# ---- flow ブロック(アニメ駆動・常に契約充足) ----
# 局面→basin_tilt(器ウェイト)。シードは "recovery" を既定(局面タイルがmissingのため illustrative)。
clock_phase = "recovery"
basin_map = {
    "reflation":   {"stocks":0.10,"gold":0.45,"oil":0.10,"cash":0.35},
    "recovery":    {"stocks":0.55,"gold":0.20,"oil":0.15,"cash":0.10},
    "overheat":    {"stocks":0.20,"gold":0.30,"oil":0.45,"cash":0.05},
    "stagflation": {"stocks":0.05,"gold":0.20,"oil":0.25,"cash":0.50},
}
basin_tilt = basin_map[clock_phase]

# net_liquidity 数値(欠損時はアニメ用に中立値6.0兆=単位健全域。reference_seedで明示)
nl_value_for_flow = net_liq_val if net_liq_val is not None else 6.0
nl_trend = "expand"  # シード既定(履歴なし)。本番は4週変化で判定
risk_off = 0.0       # 本番はHY+VIX合成

flow = {
    "net_liquidity": {"value_usd_tn": nl_value_for_flow, "wow_change_tn": 0.0, "z": 0.0,
                      "trend": nl_trend, "status": net_liq_status},
    "clock_phase": clock_phase,
    "policy_rate_friction": 0.33,   # 本番は実質政策金利由来
    "basin_tilt": basin_tilt,
    "currents": {"foreign_jp_flow_z": 0.0, "cot_jpy_z": 0.0, "risk_off": risk_off}
}

# ---- ストア使用量(シードは local data-store) ----
store_dir = ROOT / "data-store"
used_gb = 0.0
if store_dir.exists():
    used_gb = round(sum(f.stat().st_size for f in store_dir.rglob("*") if f.is_file()) / 1e9, 6)

data = {
    "meta": {
        "generated_at": NOW,
        "pipeline_version": "seed-0.1",
        "reference_seed": True,
        "note": "参照シード。キーレス分はライブ、FRED系はキー無しでmissing。本番はA1〜A5が拡張。",
        "sources_as_of": sources_as_of,
        "store": {"path": str(store_dir), "used_gb": used_gb, "limit_gb": 250}
    },
    "flow": flow,
    "tiles": tiles
}

out = PUBLIC / "data.json"
out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
live = sum(1 for t in tiles.values() if t["status"] == "ok")
missing = sum(1 for t in tiles.values() if t["status"] == "missing")
print(json.dumps({"build": "ok", "tiles_total": len(tiles), "live": live, "missing": missing,
                  "net_liquidity_status": net_liq_status, "out": str(out)}, ensure_ascii=False))
