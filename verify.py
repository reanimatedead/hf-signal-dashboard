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
    "SPEC_H1.md",                           # v4.7 Phase 1.9 contract
    "backtest/h1.py",
    "docs/assets/survival/h1_panel.js",
    "tests/test_h1_feature_lookahead.py",
    "tests/test_h1_labels.py",
    "tests/test_h1_e2e.py",
    "tests/test_h1_only.py",
    "SPEC_H1_ROBUSTNESS.md",                # v4.7.1 Phase 1.9.1 contract
    "backtest/h1_robustness.py",
    "tests/test_h1_robustness_costs.py",
    "tests/test_h1_robustness_outliers.py",
    "tests/test_h1_robustness_subperiods.py",
    "tests/test_h1_robustness_fade_skew.py",
    "tests/test_h1_robustness_verdict.py",
    "SPEC_LOOP.md",                         # v4.7.2 Phase 1.9.2 contract
    "loop/__init__.py",
    "loop/registry.py",
    "loop/holdout.py",
    "loop/runner.py",
    "loop/overfit.py",
    "loop/log.py",
    "tests/test_loop_spec.py",
    "tests/test_loop_holdout_block.py",
    "tests/test_loop_dsr_pbo.py",
    "tests/test_loop_no_autotuning.py",
    "tests/test_loop_e2e.py",
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


# =============================================================================
# 相関パネル (feat/corr-panel) ゲート群 — docs/data.json の
# correlations / money_flow.<region>.sink_metrics を検証する。
# macro.json (上の Gate-2〜10) とは独立に docs/data.json を直接読む。
# =============================================================================

CORR_LABELS_EXPECTED = [
    "N225", "SPX", "US5Y", "US10Y", "US30Y",
    "JGB5Y", "JGB10Y", "JGB30Y", "USDJPY", "US-JP10Yspread",
]
CORR_REQUIRED_KEYS = [
    "as_of", "window", "n_obs", "matrix_60d", "matrix_20d",
    "labels", "key_pairs", "data_status", "lag_days", "sources",
]
CORR_KEY_PAIRS_EXPECTED = [
    ["N225", "USDJPY"], ["SPX", "US10Y"], ["USDJPY", "US-JP10Yspread"],
]
YIELD_LABELS = ["US5Y", "US10Y", "US30Y", "JGB5Y", "JGB10Y", "JGB30Y"]
US_YIELD_LABELS = ["US5Y", "US10Y", "US30Y"]
JP_YIELD_LABELS = ["JGB5Y", "JGB10Y", "JGB30Y"]

SINK_SYMBOLS_EXPECTED = {
    "us": {"stocks": "^GSPC", "cash": "DX-Y.NYB"},
    "eu": {"stocks": "^STOXX50E", "cash": "EURUSD=X"},
    "jp": {"stocks": "^N225", "cash": "JPY=X"},
}

corr_existing = (existing or {}).get("correlations") if existing else None
mf_existing = (existing or {}).get("money_flow") if existing else None


def _corr_cell_decimals_ok(v):
    """小数4桁以下(丸め漏れ検出)。整数・None は無条件OK。"""
    if v is None:
        return True
    s = repr(float(v))
    if "e" in s or "E" in s:
        return False
    if "." not in s:
        return True
    return len(s.split(".")[1]) <= 4


# Gate-corr-schema: 必須キー・labels順序・data_status・key_pairs
try:
    if not isinstance(corr_existing, dict):
        fail("gate_corr_schema", "data.json.correlations missing or not dict")
    else:
        problems = []
        missing_keys = [k for k in CORR_REQUIRED_KEYS if k not in corr_existing]
        if missing_keys:
            problems.append(f"missing keys: {missing_keys}")
        if corr_existing.get("labels") != CORR_LABELS_EXPECTED:
            problems.append(f"labels mismatch: {corr_existing.get('labels')}")
        if corr_existing.get("data_status") not in ("live", "stale", "placeholder"):
            problems.append(f"data_status invalid: {corr_existing.get('data_status')}")
        kp = corr_existing.get("key_pairs")
        if not isinstance(kp, list) or len(kp) != 3:
            problems.append(f"key_pairs must have 3 entries: {kp}")
        else:
            kp_pairs = [item.get("pair") for item in kp if isinstance(item, dict)]
            if kp_pairs != CORR_KEY_PAIRS_EXPECTED:
                problems.append(f"key_pairs order/content mismatch: {kp_pairs}")
        if problems:
            fail("gate_corr_schema", "; ".join(problems))
        else:
            ok("gate_corr_schema")
except Exception as e:
    fail("gate_corr_schema", str(e))


# Gate-corr-matrix: 60d/20d 両方 10x10・対称性・対角・値域
def _check_matrix(name, labels, matrix):
    problems = []
    n = len(labels)
    if not isinstance(matrix, list) or len(matrix) != n or any(
        not isinstance(row, list) or len(row) != n for row in matrix
    ):
        return [f"{name}: not {n}x{n}"]
    for i in range(n):
        for j in range(n):
            a, b = matrix[i][j], matrix[j][i]
            if a is None and b is None:
                continue
            if a is None or b is None:
                problems.append(f"{name}[{i}][{j}] asymmetric null mismatch: {a} vs {b}")
                continue
            if abs(a - b) > 1e-9:
                problems.append(f"{name}[{i}][{j}]={a} != {name}[{j}][{i}]={b}")
    for i in range(n):
        diag = matrix[i][i]
        col_has_data = any(matrix[i][j] is not None for j in range(n) if j != i) or diag is not None
        if diag is not None and diag != 1.0:
            problems.append(f"{name} diag[{i}]={diag} != 1.0")
        # データがある列(対角含め非null値が存在)は1.0のはず。全null列のみnull許容。
        row_all_null = all(v is None for v in matrix[i])
        col_all_null = all(matrix[k][i] is None for k in range(n))
        if diag is None and not (row_all_null and col_all_null):
            problems.append(f"{name} diag[{i}] is null but row/col has data")
    for i in range(n):
        for j in range(n):
            v = matrix[i][j]
            if v is not None and not (-1.0 <= v <= 1.0):
                problems.append(f"{name}[{i}][{j}]={v} out of [-1,1]")
    return problems


try:
    if not isinstance(corr_existing, dict):
        fail("gate_corr_matrix", "correlations missing")
    else:
        labels = corr_existing.get("labels") or []
        problems = []
        problems += _check_matrix("matrix_60d", labels, corr_existing.get("matrix_60d"))
        problems += _check_matrix("matrix_20d", labels, corr_existing.get("matrix_20d"))
        if problems:
            fail("gate_corr_matrix", "; ".join(problems))
        else:
            ok("gate_corr_matrix")
except Exception as e:
    fail("gate_corr_matrix", str(e))


# Gate-corr-level-misuse: 水準相関の誤実装検出（bp変化なら起こらない特徴）
def detect_level_correlation_misuse(labels, matrix60):
    """クロスカントリー利回りペアの|r|>0.95、または利回り15ペア中|r|>0.98が4本以上なら
    水準相関の疑いとして問題リストを返す(空なら健全)。labels/matrix60 は10x10想定。
    """
    problems = []
    idx = {l: i for i, l in enumerate(labels)}

    def cell(a, b):
        if a not in idx or b not in idx:
            return None
        return matrix60[idx[a]][idx[b]]

    for a in US_YIELD_LABELS:
        for b in JP_YIELD_LABELS:
            v = cell(a, b)
            if v is not None and abs(v) > 0.95:
                problems.append(f"cross-country {a}-{b} |r|={abs(v)} > 0.95 (level-correlation suspected)")

    high_count = 0
    for i2, a in enumerate(YIELD_LABELS):
        for b in YIELD_LABELS[i2 + 1:]:
            v = cell(a, b)
            if v is not None and abs(v) > 0.98:
                high_count += 1
    if high_count >= 4:
        problems.append(f"{high_count}/15 yield pairs have |r|>0.98 (level-correlation suspected)")

    return problems


try:
    if not isinstance(corr_existing, dict):
        fail("gate_corr_level_misuse", "correlations missing")
    else:
        problems = detect_level_correlation_misuse(
            corr_existing.get("labels") or [], corr_existing.get("matrix_60d") or []
        )
        if problems:
            fail("gate_corr_level_misuse", "; ".join(problems))
        else:
            ok("gate_corr_level_misuse")
except Exception as e:
    fail("gate_corr_level_misuse", str(e))


# Gate-corr-era: pipeline.corr_sources.era_to_iso の単体テスト（和暦変換）
try:
    sys.path.insert(0, str(ROOT / "pipeline"))
    from corr_sources import era_to_iso  # noqa: E402

    cases = [
        (("R8.7.1",), "2026-07-01"),
        (("H31.4.30",), "2019-04-30"),
        (("S49.9.24",), "1974-09-24"),
        (("garbage",), None),
        (("R8.13.1",), None),
    ]
    problems = []
    for args, expected in cases:
        got = era_to_iso(*args)
        if got != expected:
            problems.append(f"era_to_iso{args} = {got!r}, expected {expected!r}")
    if problems:
        fail("gate_corr_era", "; ".join(problems))
    else:
        ok("gate_corr_era")
except Exception as e:
    fail("gate_corr_era", str(e))


# Gate-corr-nobs: n_obs >= window.long。未達なら data_status=="placeholder" を要求
try:
    if not isinstance(corr_existing, dict):
        fail("gate_corr_nobs", "correlations missing")
    else:
        n_obs = corr_existing.get("n_obs")
        window_long = (corr_existing.get("window") or {}).get("long")
        status = corr_existing.get("data_status")
        if n_obs is None or window_long is None:
            fail("gate_corr_nobs", f"n_obs={n_obs} window.long={window_long} missing")
        elif n_obs < window_long and status != "placeholder":
            fail("gate_corr_nobs", f"n_obs={n_obs} < window.long={window_long} but data_status={status!r} != placeholder")
        else:
            ok("gate_corr_nobs")
except Exception as e:
    fail("gate_corr_nobs", str(e))


# Gate-corr-determinism: as_of が wall-clock 由来でない（過去営業日のはず）+ 丸め4桁
try:
    if not isinstance(corr_existing, dict):
        fail("gate_corr_determinism", "correlations missing")
    else:
        problems = []
        as_of = corr_existing.get("as_of")
        if as_of:
            try:
                as_of_date = datetime.date.fromisoformat(str(as_of)[:10])
                if as_of_date >= datetime.date.today():
                    problems.append(f"as_of={as_of} is today or future (wall-clock suspected)")
            except Exception as exc:
                problems.append(f"as_of={as_of!r} unparsable: {exc}")
        else:
            problems.append("as_of missing")

        m60 = corr_existing.get("matrix_60d") or []
        bad_cells = [
            (i, j, m60[i][j])
            for i in range(len(m60))
            for j in range(len(m60[i]) if isinstance(m60[i], list) else 0)
            if not _corr_cell_decimals_ok(m60[i][j])
        ]
        if bad_cells:
            problems.append(f"matrix_60d cells with >4 decimals: {bad_cells}")

        if problems:
            fail("gate_corr_determinism", "; ".join(problems))
        else:
            ok("gate_corr_determinism")
except Exception as e:
    fail("gate_corr_determinism", str(e))


# Gate-corr-selftest: 水準相関検出ロジック自体の自己テスト（合成データ・シード固定・オフライン）
try:
    import numpy as _np

    def _build_synthetic_matrix(series_a, series_b):
        """labels=[A,B] の2x2相関行列を作る(gate_corr_matrix互換の形)。"""
        r = float(_np.corrcoef(series_a, series_b)[0, 1])
        r = round(r, 4)
        return ["US5Y", "JGB5Y"], [[1.0, r], [r, 1.0]]

    rng = _np.random.default_rng(42)
    n = 300

    # (1) 水準トレンド系列2本 → 高相関(>0.95)になるはず → 検出器は疑いありと判定すべき
    level_a = _np.linspace(0, 10, n) + rng.normal(0, 0.05, n)
    level_b = _np.linspace(0, 10, n) + rng.normal(0, 0.05, n)
    labels_lvl, matrix_lvl = _build_synthetic_matrix(level_a, level_b)
    problems_lvl = detect_level_correlation_misuse(labels_lvl, matrix_lvl)

    # (2) ランダムウォークの差分系列2本(定常・独立) → 相関≈0 → 検出器は素通りさせるべき
    diff_a = rng.normal(0, 1, n)
    diff_b = rng.normal(0, 1, n)
    labels_diff, matrix_diff = _build_synthetic_matrix(diff_a, diff_b)
    problems_diff = detect_level_correlation_misuse(labels_diff, matrix_diff)

    selftest_problems = []
    if not problems_lvl:
        selftest_problems.append(
            f"detector failed to flag synthetic level-trend series (r={matrix_lvl[0][1]})"
        )
    if problems_diff:
        selftest_problems.append(
            f"detector false-positived on synthetic differenced random-walk series "
            f"(r={matrix_diff[0][1]}): {problems_diff}"
        )

    if selftest_problems:
        fail("gate_corr_selftest", "; ".join(selftest_problems))
    else:
        ok("gate_corr_selftest")
except Exception as e:
    fail("gate_corr_selftest", str(e))


# Gate-sink-metrics: money_flow.<region>.sink_metrics の契約
try:
    if not isinstance(mf_existing, dict):
        fail("gate_sink_metrics", "data.json.money_flow missing")
    else:
        problems = []
        for region in ("us", "eu", "jp"):
            blk = (mf_existing.get(region) or {}).get("sink_metrics")
            if not isinstance(blk, dict):
                problems.append(f"money_flow.{region}.sink_metrics missing")
                continue
            if blk.get("label_type") != "weekly_change":
                problems.append(f"{region}.sink_metrics.label_type != weekly_change")
            note = blk.get("note", "")
            if "visual effect" not in note:
                problems.append(f"{region}.sink_metrics.note missing 'visual effect'")
            for sink in ("stocks", "gold", "crypto", "cash"):
                s = blk.get(sink)
                if not isinstance(s, dict):
                    problems.append(f"{region}.sink_metrics.{sink} missing")
                    continue
                if not s.get("symbol"):
                    problems.append(f"{region}.sink_metrics.{sink}.symbol empty")
                wow = s.get("wow_pct")
                if wow is not None and not isinstance(wow, (int, float)):
                    problems.append(f"{region}.sink_metrics.{sink}.wow_pct not number|null: {wow!r}")
                st = s.get("data_status")
                if st not in ("live", "placeholder"):
                    problems.append(f"{region}.sink_metrics.{sink}.data_status invalid: {st!r}")
                if wow is None and st != "placeholder":
                    problems.append(f"{region}.sink_metrics.{sink} wow_pct=null but data_status={st!r} != placeholder")
            expected_syms = SINK_SYMBOLS_EXPECTED.get(region, {})
            for sink, expected_sym in expected_syms.items():
                actual_sym = (blk.get(sink) or {}).get("symbol")
                if actual_sym != expected_sym:
                    problems.append(f"{region}.sink_metrics.{sink}.symbol={actual_sym!r} != expected {expected_sym!r}")
        if problems:
            fail("gate_sink_metrics", "; ".join(problems))
        else:
            ok("gate_sink_metrics")
except Exception as e:
    fail("gate_sink_metrics", str(e))

finish()
