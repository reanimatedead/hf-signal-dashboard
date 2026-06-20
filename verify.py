#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify.py — Macro レイヤー自己点検ハーネス（BUILD_SPEC v4 §A5 増築版）

- 既存 docs/data.json を破壊していないこと（回帰ゼロ）
- 新規 docs/data/macro.json が契約（meta/flow/tiles）を満たし、健全であること
- 既存 per-symbol タブ（テーブル）が docs/index.html 内に残っていること（DOM 文字列検査）

PASS なら 0 終了、FAIL なら 1。stdout は verify_report.json と同じ JSON。
"""

import json
import os
import math
import pathlib
import datetime
import sys
import re

ROOT = pathlib.Path(__file__).resolve().parent
DOCS = ROOT / "docs"
MACRO = DOCS / "data" / "macro.json"
EXISTING_DATA = DOCS / "data.json"
INDEX = DOCS / "index.html"
HOME_STORE = pathlib.Path(os.path.expanduser("~/hf-data-store"))

REQUIRED_FILES = [
    "docs/index.html",
    "docs/data.json",
    "docs/data/macro.json",                 # legacy macro layer (still wired)
    "docs/assets/lib/particles.js",         # v4.1 shared particle engine
    "pipeline/build_macro.py",
    "verify.py",
    "verify_render.mjs",
    "MACRO_INTEGRATION_NOTES.md",
    "SPEC_MONEYFLOW.md",                    # v4.1 contract
    "SPEC_SURVIVAL.md",                     # v4.2 Phase 1 contract
    "survival/risk_engine.py",
    "survival/pattern_table.py",
    "survival/bankruptcy.py",
    "survival/survival_loop.py",
    "docs/assets/survival/survival.js",
    "tests/test_money_flow_schema.py",
    "tests/test_index_html_contract.py",
    "tests/test_risk_ceiling.py",
    "tests/test_pattern_table_invariants.py",
    "tests/test_bankruptcy_simulator.py",
    "tests/test_survival_loop_schema.py",
    "SPEC_AUTOCOLLECT.md",                  # v4.3 Phase 1.5 contract
    "collector/runtime.py",
    "collector/snapshot.py",
    "collector/log.py",
    "collector/cli.py",
    ".github/workflows/collect.yml",
    "tests/test_collector_idempotent.py",
    "tests/test_collector_schema.py",
    "tests/test_collector_resilience.py",
    "tests/test_collect_workflow.py",
    "SPEC_NOTIFY.md",                       # v4.4 Phase 1.6 contract
    "notify/__init__.py",
    "notify/chain.py",
    "notify/triggers.py",
    "notify/bus.py",
    "notify/receiver.py",
    "notify/config.py",
    "scripts/notify_receiver.py",
    "scripts/com.hf.notify.plist",
    "docs/assets/survival/notify_panel.js",
    "tests/test_notify_chain.py",
    "tests/test_notify_triggers.py",
    "tests/test_notify_bus.py",
    "tests/test_notify_receiver.py",
    "tests/test_notify_security.py",
    "SPEC_BACKTEST.md",                     # v4.5 Phase 1.7 contract
    "backtest/__init__.py",
    "backtest/walk_forward.py",
    "backtest/simulator.py",
    "backtest/metrics.py",
    "backtest/cli.py",
    "collector/backfill.py",
    "docs/assets/survival/backtest_panel.js",
    "docs/assets/survival/backfill_panel.js",
    "tests/test_walk_forward.py",
    "tests/test_backtest_simulator.py",
    "tests/test_backtest_metrics.py",
    "tests/test_backfill_cli.py",
    "tests/test_backtest_e2e_smoke.py",
    "SPEC_BACKTEST_LIVE.md",                # v4.6 Phase 1.8 contract
    "backtest/local_loader.py",
    "tests/test_local_loader.py",
    "tests/test_backtest_live.py",
    "tests/test_no_learning_code.py",
]

EXPECTED_LAG = {
    "walcl": 7, "rrp": 7, "real_yield": 7, "hy_spread": 7, "vix": 7,
    "net_liquidity": 7, "cot_jpy": 10, "tga": 7,
    "btc_price": 2, "stablecoin_peg": 2,
    "usdjpy_carry": 3,
    "valuation_us": 95,
}
REGIME_SENSITIVE = ["real_yield"]   # ok/stale なら崩れ注記必須
FORBIDDEN = ["cesi", "economic_surprise", "bloomberg_fci", "gs_fci", "move_intraday", "65month", "cycle65"]

gates = {}
failed = []


def fail(gate, msg):
    gates[gate] = "FAIL"
    failed.append(f"{gate}: {msg}")


def ok(gate):
    gates[gate] = "PASS"


def days_since(d):
    try:
        return (datetime.date.today() - datetime.date.fromisoformat(str(d)[:10])).days
    except Exception:
        return None


# Gate-0: ファイル存在
missing_files = [f for f in REQUIRED_FILES if not (ROOT / f).exists()]
if missing_files:
    fail("gate0_files", f"missing {missing_files}")
else:
    ok("gate0_files")

# Gate-1: 既存 docs/data.json が壊れていない（回帰ゼロ）
existing = None
try:
    existing = json.loads(EXISTING_DATA.read_text(encoding="utf-8"))
    must_have = ["markets", "meta"]
    bad = [k for k in must_have if k not in existing]
    if bad:
        fail("gate1_regression_data", f"existing data.json missing keys: {bad}")
    else:
        markets = existing.get("markets", {})
        expected = {"nikkei225", "fx", "rates", "imm", "volatility", "valuation"}
        missing_mkt = expected - set(markets.keys())
        if missing_mkt:
            fail("gate1_regression_data", f"existing markets missing: {missing_mkt}")
        else:
            ok("gate1_regression_data")
except Exception as e:
    fail("gate1_regression_data", f"existing data.json parse fail: {e}")

# Gate-1b: v4.1 タブ統合後の構造が壊れていない (per-symbol タブのうち
# 残るべきもの = nikkei225 / fx 等; rates/imm/valuation は rates_vol/pos_val に統合済み)
try:
    html = INDEX.read_text(encoding="utf-8")
    needles = [
        'data-tab="nikkei225"', 'data-tab="fx"',
        'data-tab="rates_vol"', 'data-tab="pos_val"', 'data-tab="moneyflow"',
        'id="bg-fx"', 'assets/lib/particles.js',
    ]
    miss = [n for n in needles if n not in html]
    if miss:
        fail("gate1_regression_index", f"v4.1 index.html anchors missing: {miss}")
    else:
        ok("gate1_regression_index")
except Exception as e:
    fail("gate1_regression_index", str(e))

# Gate-1c: v4.1 top-level money_flow ブロックが data.json に存在し契約を満たす
try:
    mf = (existing or {}).get("money_flow") if existing else None
    if not isinstance(mf, dict):
        fail("gate1c_money_flow", "data.json.money_flow missing or not dict")
    else:
        problems = []
        for region in ("us", "eu", "jp"):
            blk = mf.get(region)
            if not isinstance(blk, dict):
                problems.append(f"money_flow.{region} missing"); continue
            for k in ("cb_assets", "debt", "freshness_badge"):
                if k not in blk:
                    problems.append(f"money_flow.{region}.{k} missing")
            if blk.get("region") != region:
                problems.append(f"money_flow.{region}.region != {region}")
        for region in ("eu", "jp"):
            blk = mf.get(region, {})
            for k in ("tga", "rrp", "net_liquidity"):
                if blk.get(k) is not None:
                    problems.append(f"money_flow.{region}.{k} must be null (US-only)")
        if problems:
            fail("gate1c_money_flow", "; ".join(problems))
        else:
            ok("gate1c_money_flow")
except Exception as e:
    fail("gate1c_money_flow", str(e))

# Gate-1d: v4.2 Phase 1 — survival_loop の契約 + HARD_CAPS の遵守
try:
    sl = (existing or {}).get("survival_loop") if existing else None
    if not isinstance(sl, dict):
        fail("gate1d_survival_loop", "data.json.survival_loop missing or not dict")
    elif sl.get("data_status") == "placeholder":
        ok("gate1d_survival_loop")
    else:
        problems = []
        for k in ("risk_gate", "auto_risk", "pattern_table",
                  "candidates", "mode_a_positions", "bankruptcy_simulation"):
            if k not in sl:
                problems.append(f"survival_loop.{k} missing")
        ar = sl.get("auto_risk") or {}
        ptp = ar.get("per_trade_pct")
        if ptp is None or ptp > 0.5 or ptp < 0:
            problems.append(f"per_trade_pct {ptp} violates HARD_CAP 0.5")
        if ar.get("dd_shrink_pct") != -10.0:
            problems.append("dd_shrink_pct must be -10.0 (fixed)")
        if ar.get("dd_stop_pct") != -15.0:
            problems.append("dd_stop_pct must be -15.0 (fixed)")
        if (ar.get("max_concurrent") or 0) > 3:
            problems.append("max_concurrent > 3 violates HARD_CAP")
        for p in sl.get("mode_a_positions", []):
            if p.get("size_pct", 0) > 0.5:
                problems.append(f"mode_a {p.get('symbol')} size_pct > 0.5")
        if problems:
            fail("gate1d_survival_loop", "; ".join(problems))
        else:
            ok("gate1d_survival_loop")
except Exception as e:
    fail("gate1d_survival_loop", str(e))


def finish():
    result = "PASS" if not failed else "FAIL"
    out = {
        "harness": "verify.py",
        "result": result,
        "gates": gates,
        "failed": failed,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
    }
    (ROOT / "verify_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if result == "PASS" else 1)


# 続行のためには macro.json が必要
data = None
if not MACRO.exists():
    fail("gate0_files", f"macro.json missing: {MACRO}")
    finish()
try:
    data = json.loads(MACRO.read_text(encoding="utf-8"))
except Exception as e:
    fail("gate0_files", f"macro.json parse error: {e}")
    finish()

tiles = data.get("tiles", {})
flow = data.get("flow", {})

# Gate-2: ストア健全性（任意。~/hf-data-store の容量上限）
try:
    used = (data.get("meta", {}).get("store", {}) or {}).get("used_gb", 0) or 0
    if used >= 250:
        fail("gate2_store", f"store over 250GB: {used}")
    else:
        ok("gate2_store")
except Exception as e:
    fail("gate2_store", str(e))

# Gate-3: schema (meta/flow/tiles、basin_tilt 合計=1、flow キー)
try:
    assert "meta" in data and "flow" in data and "tiles" in data, "top-level missing"
    bt = flow.get("basin_tilt", {})
    s = sum(bt.values()) if bt else 0
    assert abs(s - 1.0) < 0.02, f"basin_tilt sum={s}"
    for k in ("net_liquidity", "clock_phase", "policy_rate_friction", "currents"):
        assert k in flow, f"flow.{k} missing"
    ok("gate3_schema")
except Exception as e:
    fail("gate3_schema", str(e))

# Gate-4: 単位健全性（net_liquidity 兆ドル想定 0-20）
try:
    nl = flow.get("net_liquidity", {}).get("value_usd_tn")
    assert nl is not None and 0 <= nl <= 20, f"net_liquidity={nl} (兆ドル想定)"
    ok("gate4_units")
except Exception as e:
    fail("gate4_units", str(e))

# Gate-5: 鮮度（ok は期待ラグ内、超過なら stale でなければ FAIL）
try:
    bad = []
    for tid, t in tiles.items():
        st = t.get("status")
        if st == "ok":
            lag = t.get("lag_days")
            exp = EXPECTED_LAG.get(tid)
            if exp is not None and lag is not None and lag > exp:
                bad.append(f"{tid} ok but lag {lag}>{exp} (should be stale)")
    if bad:
        fail("gate5_freshness", "; ".join(bad))
    else:
        ok("gate5_freshness")
except Exception as e:
    fail("gate5_freshness", str(e))

# Gate-6: 欠損の正直さ（missing は value=None）
try:
    bad = [tid for tid, t in tiles.items() if t.get("status") == "missing" and t.get("value") not in (None,)]
    if bad:
        fail("gate6_honesty", f"missing tiles with fabricated value: {bad}")
    else:
        ok("gate6_honesty")
except Exception as e:
    fail("gate6_honesty", str(e))

# Gate-7: z 健全性
try:
    bad = []
    for tid, t in tiles.items():
        if t.get("status") in ("ok", "stale"):
            z = t.get("z")
            if z is None or not math.isfinite(z) or abs(z) > 6:
                bad.append(f"{tid}:z={z}")
    if bad:
        fail("gate7_zhealth", "; ".join(bad))
    else:
        ok("gate7_zhealth")
except Exception as e:
    fail("gate7_zhealth", str(e))

# Gate-8: 説明/注意の存在
try:
    bad = [tid for tid, t in tiles.items() if not t.get("explain") or not t.get("caveat")]
    if bad:
        fail("gate8_docs", f"empty explain/caveat: {bad}")
    else:
        ok("gate8_docs")
except Exception as e:
    fail("gate8_docs", str(e))

# Gate-9: レジーム注記（ok/stale の regime-sensitive タイルは崩れ注記）
try:
    bad = []
    for tid in REGIME_SENSITIVE:
        t = tiles.get(tid)
        if t and t.get("status") in ("ok", "stale"):
            cav = t.get("caveat", "")
            if ("崩れ" not in cav) and ("regime" not in cav.lower()) and ("decoupl" not in cav.lower()):
                bad.append(tid)
    if bad:
        fail("gate9_regime", f"missing regime note: {bad}")
    else:
        ok("gate9_regime")
except Exception as e:
    fail("gate9_regime", str(e))

# Gate-10: 除外厳守（HFT/CESI/65か月/Bloomberg/有料系の単語不在）
try:
    blob = json.dumps(data, ensure_ascii=False).lower()
    hit = [w for w in FORBIDDEN if w in blob]
    if hit:
        fail("gate10_exclusions", f"forbidden keys: {hit}")
    else:
        ok("gate10_exclusions")
except Exception as e:
    fail("gate10_exclusions", str(e))

finish()
