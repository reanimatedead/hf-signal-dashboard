"""Monte Carlo bankruptcy simulator (SPEC_SURVIVAL §2.5, §4, §8.5).

% 空間で計算。残高はヒートマップ表示にしか効かない。
"""
import random
import pytest

bk = pytest.importorskip(
    "survival.bankruptcy",
    reason="Agent E 未実装。survival/bankruptcy.py を作ると緑になる。",
)


def test_monte_carlo_ror_zero_edge_collapses():
    # 期待値 0 (p*b - q = 0) + リスク 0.5% の連続賭けでは
    # DD 上限 -15% に触れるシナリオが現実的に観測される
    random.seed(0)
    ror = bk.monte_carlo_ror(
        win_prob=0.5, win_loss_ratio=1.0, risk_pct=0.5,
        trades=2000, runs=200, dd_stop_pct=15.0,
    )
    assert 0.0 <= ror <= 1.0
    # 完全運要素では RoR が 0 のはずがない (確率的に必ず触れる)
    assert ror > 0.0


def test_monte_carlo_ror_positive_edge_decreases():
    random.seed(1)
    ror_no_edge = bk.monte_carlo_ror(
        win_prob=0.50, win_loss_ratio=1.0, risk_pct=0.5, trades=500, runs=300, dd_stop_pct=15.0,
    )
    random.seed(1)
    ror_edge = bk.monte_carlo_ror(
        win_prob=0.55, win_loss_ratio=1.5, risk_pct=0.5, trades=500, runs=300, dd_stop_pct=15.0,
    )
    assert ror_edge < ror_no_edge, (
        f"positive edge must reduce RoR (edge={ror_edge} >= no_edge={ror_no_edge})"
    )


def test_kaufman_ror_returns_one_when_no_edge():
    # 負の edge (p*b - q <= 0) は閉形式で RoR=1.0
    r = bk.kaufman_ror(win_prob=0.4, win_loss_ratio=1.0, risk_pct=1.0)
    assert r == 1.0


def test_kaufman_ror_in_range():
    r = bk.kaufman_ror(win_prob=0.55, win_loss_ratio=1.5, risk_pct=1.0)
    assert 0.0 <= r <= 1.0


def test_heatmap_returns_grid_with_risk_options():
    random.seed(2)
    hm = bk.heatmap(
        win_prob=0.52, win_loss_ratio=1.5,
        balances_pct_basis=[300, 400, 500],
        risk_options=[0.1, 0.25, 0.5],
        trades=200, runs=100, dd_stop_pct=15.0,
    )
    assert hm["balances_pct_basis"] == [300, 400, 500]
    assert len(hm["risk_grid"]) == 3
    for cell in hm["risk_grid"]:
        assert "risk_pct" in cell and "ror_mc" in cell
        assert 0.0 <= cell["ror_mc"] <= 1.0


def test_heatmap_respects_hard_caps_in_risk_options():
    # 0.5% を超える risk_options が混じっていてもクランプされる
    hm = bk.heatmap(
        win_prob=0.55, win_loss_ratio=1.5,
        balances_pct_basis=[300, 400, 500],
        risk_options=[0.1, 0.5, 1.0, 5.0],
        trades=100, runs=50, dd_stop_pct=15.0,
    )
    for cell in hm["risk_grid"]:
        assert cell["risk_pct"] <= 0.5, (
            f"heatmap must clamp risk to HARD_CAPS, got {cell['risk_pct']}"
        )
