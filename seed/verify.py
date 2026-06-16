#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HF Signal Dashboard 自己点検ハーネス (verify.py) — BUILD_SPEC §6.1
10ゲートを順に通し、結果JSONを標準出力 + verify_report.json に書く。
1つでもFAILなら以降中断。完了報告にはこの実出力を貼ること(反虚偽報告)。
SEED_MODE: ストアは ./data-store を見る(本番は ~/hf-data-store)。
"""
import json, os, math, pathlib, datetime, sys

ROOT = pathlib.Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
SEED_MODE = True
STORE = (ROOT / "data-store") if SEED_MODE else pathlib.Path(os.path.expanduser("~/hf-data-store"))

REQUIRED_FILES = ["public/data.json", "public/index.html", "public/app.js",
                  "public/flow.js", "verify.py", "verify_render.mjs"]
EXPECTED_LAG = {"walcl": 7, "rrp": 7, "real_yield": 7, "hy_spread": 7, "vix": 7,
                "net_liquidity": 7, "cot_jpy": 10, "foreign_jp_flow": 14}
REGIME_SENSITIVE = ["real_yield", "btc_onchain"]   # ok/staleなら崩れ注記必須
FORBIDDEN = ["cesi", "economic_surprise", "bloomberg_fci", "gs_fci", "move_intraday", "65month", "cycle65"]

gates = {}
failed = []

def fail(gate, msg):
    gates[gate] = "FAIL"; failed.append(f"{gate}: {msg}")

def ok(gate):
    gates[gate] = "PASS"

def days_since(d):
    try: return (datetime.date.today() - datetime.date.fromisoformat(str(d)[:10])).days
    except Exception: return None

# Gate-0 ファイル存在
missing_files = [f for f in REQUIRED_FILES if not (ROOT / f).exists()]
if missing_files: fail("gate0_files", f"missing {missing_files}")
else: ok("gate0_files")

# data.json 読み込み(これが無いと以降不能)
data = None
if (PUBLIC / "data.json").exists():
    try: data = json.loads((PUBLIC / "data.json").read_text(encoding="utf-8"))
    except Exception as e: fail("gate0_files", f"data.json parse error {e}")

def finish():
    result = "PASS" if not failed else "FAIL"
    out = {"harness": "verify.py", "result": result,
           "store_used_gb": (data or {}).get("meta", {}).get("store", {}).get("used_gb"),
           "gates": gates, "failed": failed,
           "generated_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()}
    (ROOT / "verify_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if result == "PASS" else 1)

if data is None:
    finish()

tiles = data.get("tiles", {})
flow = data.get("flow", {})

# Gate2 ストア健全性/容量
try:
    if not STORE.exists(): fail("gate2_store", f"store not found: {STORE}")
    elif not os.access(STORE, os.W_OK): fail("gate2_store", "store not writable")
    else:
        used = data.get("meta", {}).get("store", {}).get("used_gb", 0) or 0
        if used >= 250: fail("gate2_store", f"store over 250GB: {used}")
        else: ok("gate2_store")
except Exception as e:
    fail("gate2_store", str(e))

# Gate3 schema
try:
    assert "meta" in data and "flow" in data and "tiles" in data
    bt = flow.get("basin_tilt", {})
    s = sum(bt.values()) if bt else 0
    assert abs(s - 1.0) < 0.02, f"basin_tilt sum={s}"
    for k in ("net_liquidity", "clock_phase", "policy_rate_friction", "currents"):
        assert k in flow, f"flow.{k} missing"
    ok("gate3_schema")
except Exception as e:
    fail("gate3_schema", str(e))

# Gate4 単位健全性
try:
    nl = flow.get("net_liquidity", {}).get("value_usd_tn")
    assert nl is not None and 0 <= nl <= 20, f"net_liquidity={nl} (兆ドル想定)"
    ok("gate4_units")
except Exception as e:
    fail("gate4_units", str(e))

# Gate5 鮮度(ok/staleのみ。okは期待ラグ内、超過はstaleであるべき)
try:
    bad = []
    for tid, t in tiles.items():
        st = t.get("status")
        if st == "ok":
            lag = t.get("lag_days"); exp = EXPECTED_LAG.get(tid)
            if exp is not None and lag is not None and lag > exp:
                bad.append(f"{tid} ok but lag {lag}>{exp} (should be stale)")
    if bad: fail("gate5_freshness", "; ".join(bad))
    else: ok("gate5_freshness")
except Exception as e:
    fail("gate5_freshness", str(e))

# Gate6 欠損の正直さ(missingはvalue=null)
try:
    bad = [tid for tid, t in tiles.items() if t.get("status") == "missing" and t.get("value") not in (None,)]
    if bad: fail("gate6_honesty", f"missing tiles with fabricated value: {bad}")
    else: ok("gate6_honesty")
except Exception as e:
    fail("gate6_honesty", str(e))

# Gate7 z健全性(ok/staleのzが有限・|z|<=6)
try:
    bad = []
    for tid, t in tiles.items():
        if t.get("status") in ("ok", "stale"):
            z = t.get("z")
            if z is None or not math.isfinite(z) or abs(z) > 6: bad.append(f"{tid}:z={z}")
    if bad: fail("gate7_zhealth", "; ".join(bad))
    else: ok("gate7_zhealth")
except Exception as e:
    fail("gate7_zhealth", str(e))

# Gate8 説明・注意の存在(全タイル)
try:
    bad = [tid for tid, t in tiles.items() if not t.get("explain") or not t.get("caveat")]
    if bad: fail("gate8_docs", f"empty explain/caveat: {bad}")
    else: ok("gate8_docs")
except Exception as e:
    fail("gate8_docs", str(e))

# Gate9 レジーム注記(ok/staleのregime-sensitiveタイルは崩れ注記)
try:
    bad = []
    for tid in REGIME_SENSITIVE:
        t = tiles.get(tid)
        if t and t.get("status") in ("ok", "stale"):
            cav = t.get("caveat", "")
            if ("崩れ" not in cav) and ("regime" not in cav.lower()) and ("decoupl" not in cav.lower()):
                bad.append(tid)
    if bad: fail("gate9_regime", f"missing regime note: {bad}")
    else: ok("gate9_regime")  # 対象がmissingなら免除でPASS
except Exception as e:
    fail("gate9_regime", str(e))

# Gate10 除外厳守
try:
    blob = json.dumps(data, ensure_ascii=False).lower()
    hit = [w for w in FORBIDDEN if w in blob]
    if hit: fail("gate10_exclusions", f"forbidden keys: {hit}")
    else: ok("gate10_exclusions")
except Exception as e:
    fail("gate10_exclusions", str(e))

finish()
