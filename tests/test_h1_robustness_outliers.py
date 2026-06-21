"""Agent 2 — 外れ値除外 (top 1% / 5% by |realized|) (SPEC §2)."""
import pytest

hr = pytest.importorskip("backtest.h1_robustness", reason="Agent 1 未実装")


def _trade(net_pct):
    return {"ts": "2024-01-01T00:00:00", "net_pct": float(net_pct),
            "predicted_prob": 0.55, "outcome01": 1 if net_pct > 0 else 0}


def test_drop_top_pct_removes_largest_abs():
    # 100 trades, large fat-tail outliers ±10%
    trades = [_trade(0.01)] * 90 + [_trade(10.0)] * 5 + [_trade(-10.0)] * 5
    pruned = hr.drop_top_abs_pct(trades, pct=5.0)
    # top 5% = 5 件除外
    assert len(pruned) == 95
    # 除外で平均が -inf 方向に動く保証はしないが、|10.0| 級は全部消える
    assert max(abs(t["net_pct"]) for t in pruned) < 10.0


def test_drop_top_pct_handles_small_sample():
    trades = [_trade(0.1)] * 10
    pruned = hr.drop_top_abs_pct(trades, pct=5.0)
    # 10 件で 5% は 0.5 件 → 切り上げで 1 件除外
    assert len(pruned) == 9


def test_outlier_sensitivity_emits_two_rows():
    trades = [_trade(0.05 + 0.001 * i) for i in range(200)]
    table = hr.outlier_sensitivity(trades, bootstrap_runs=50)
    pcts = [r["pct_excluded"] for r in table]
    assert sorted(pcts) == [1.0, 5.0]


def test_outlier_verdict_pass_when_both_strict_positive():
    trades = [_trade(0.5) for _ in range(200)]   # 安定 positive
    table = hr.outlier_sensitivity(trades, bootstrap_runs=80)
    v = hr.outlier_verdict(table)
    assert v["pass"] is True


def test_outlier_verdict_fail_when_excluded_ci_crosses_zero():
    # 巨大 +tail 数本だけが EV を支える
    trades = [_trade(-0.01) for _ in range(195)] + [_trade(50.0)] * 5
    table = hr.outlier_sensitivity(trades, bootstrap_runs=80)
    v = hr.outlier_verdict(table)
    assert v["pass"] is False
