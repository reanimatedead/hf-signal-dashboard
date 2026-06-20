"""Pattern-table invariants (SPEC_SURVIVAL §3, §8.4)

下振れ (stop_loss / DD ceiling / margin_call) は decay_update で **絶対に動かない**。
上振れ (take_profit) のみ [MIN_TP, MAX_TP] の範囲で EWMA pull される。
"""
import copy
import pytest

pt = pytest.importorskip(
    "survival.pattern_table",
    reason="Agent D 未実装。survival/pattern_table.py を作ると緑になる。",
)


def test_default_table_has_expected_cells():
    keys = {
        ("high_vol", "high"), ("high_vol", "mid"), ("high_vol", "low"),
        ("low_vol", "high"),  ("low_vol", "mid"),  ("low_vol", "low"),
    }
    assert keys.issubset(set(pt.DEFAULT_PATTERN_TABLE.keys()))


def test_default_stop_loss_is_negative():
    for cell in pt.DEFAULT_PATTERN_TABLE.values():
        assert cell["stop_loss_pct"] < 0, f"stop loss must be negative: {cell}"
        assert cell["take_profit_pct"] > 0


def test_daily_update_never_touches_stop_loss():
    before = copy.deepcopy(pt.DEFAULT_PATTERN_TABLE)
    # 滅茶苦茶な realized 結果でも下振れは絶対動かない
    results = {
        ("high_vol", "high"): [{"pct": 9.0}, {"pct": -50.0}, {"pct": 100.0}],
        ("low_vol", "low"):   [{"pct": -10.0}, {"pct": -8.0}],
    }
    after = pt.daily_update(before, results)
    for k, cell in after.items():
        assert cell["stop_loss_pct"] == before[k]["stop_loss_pct"], (
            f"stop_loss_pct changed for {k}: {before[k]['stop_loss_pct']} → {cell['stop_loss_pct']}"
        )


def test_daily_update_take_profit_within_bounds():
    before = copy.deepcopy(pt.DEFAULT_PATTERN_TABLE)
    extreme = {k: [{"pct": 1000.0}] for k in before}
    after = pt.daily_update(before, extreme)
    for k, cell in after.items():
        assert pt.MIN_TP_PCT <= cell["take_profit_pct"] <= pt.MAX_TP_PCT, (
            f"take_profit out of bounds: {cell['take_profit_pct']}"
        )


def test_daily_update_take_profit_does_pull_toward_realized():
    before = copy.deepcopy(pt.DEFAULT_PATTERN_TABLE)
    key = ("high_vol", "mid")
    cur = before[key]["take_profit_pct"]
    # 安定して大きな利確が出るシミュレーション
    results = {key: [{"pct": 5.0}] * 5}
    after = pt.daily_update(before, results)
    # 上方向に動いてはいるが MAX_TP を超えない
    assert after[key]["take_profit_pct"] > cur
    assert after[key]["take_profit_pct"] <= pt.MAX_TP_PCT


def test_daily_update_is_idempotent_with_empty_results():
    before = copy.deepcopy(pt.DEFAULT_PATTERN_TABLE)
    after = pt.daily_update(before, {})
    assert after == before


def test_daily_update_returns_new_dict_not_mutation():
    before = copy.deepcopy(pt.DEFAULT_PATTERN_TABLE)
    snap = copy.deepcopy(before)
    pt.daily_update(before, {("high_vol", "high"): [{"pct": 3.0}]})
    assert before == snap, "daily_update must not mutate input"


def test_serialize_uses_pipe_keys():
    # SPEC §4: "regime|distortion" 文字列キー
    out = pt.serialize_for_json(pt.DEFAULT_PATTERN_TABLE)
    assert "high_vol|high" in out
    assert "low_vol|low" in out
    for v in out.values():
        assert "take_profit_pct" in v and "stop_loss_pct" in v
