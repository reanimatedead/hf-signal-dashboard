"""Agent 1 — cost 控除 + 3 水準感度 (SPEC §1)."""
import pytest

hr = pytest.importorskip(
    "backtest.h1_robustness",
    reason="Agent 1 未実装。backtest/h1_robustness.py を作ると緑になる。",
)


def _trade(net_pct, ts="2024-06-01T00:00:00"):
    return {"ts": ts, "net_pct": float(net_pct), "predicted_prob": 0.55,
            "outcome01": 1 if net_pct > 0 else 0}


def test_apply_cost_subtracts_in_pct():
    trades = [_trade(0.10), _trade(-0.05), _trade(0.20)]
    out = hr.apply_cost(trades, cost_pct=0.10)
    assert [round(t["net_pct"], 6) for t in out] == [0.0, -0.15, 0.10]
    # 元の trade を破壊しない
    assert trades[0]["net_pct"] == 0.10


def test_cost_levels_bps_constant():
    assert hr.COST_LEVELS_BPS == (5, 10, 20)


def test_cost_sensitivity_emits_3_rows():
    trades = [_trade(0.20) for _ in range(60)]
    table = hr.cost_sensitivity(trades, bootstrap_runs=50)
    assert isinstance(table, list) and len(table) == 3
    for row in table:
        for k in ("cost_bps", "cost_pct", "n", "mean_net_pct", "ev_ci"):
            assert k in row
        assert row["cost_bps"] in (5, 10, 20)


def test_cost_sensitivity_lower_ev_when_cost_higher():
    trades = [_trade(0.20) for _ in range(80)]
    table = hr.cost_sensitivity(trades, bootstrap_runs=50)
    means = [r["mean_net_pct"] for r in table]
    # 5 < 10 < 20 → means 厳密に減少
    assert means[0] > means[1] > means[2]


def test_verdict_a_fails_when_any_level_ci_lower_negative():
    """5bps コスト控除で CI 下限が負になれば (a) FAIL.

    Phase 1.9 の since_2023 / open_to_close は EV CI [+0.012, +0.157]. 5bps を引くと
    下限 +0.012 - 0.05 = -0.038 → 負 → (a) FAIL 系のケース.
    """
    trades = [_trade(0.08) for _ in range(60)]   # mean ~ 0.08%
    table = hr.cost_sensitivity(trades, bootstrap_runs=50)
    # 0.05% を引くと mean がほぼ +0.03, さらに 0.10/0.20 で完全負側
    # 判定: cost_verdict_pass=False (任意水準で CI 下限 < 0)
    ok = hr.cost_verdict(table)
    assert ok["pass"] is False
    assert ok["levels"]  # 3 水準ごとの結果が残る
