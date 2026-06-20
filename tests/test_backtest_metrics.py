"""backtest.metrics — Brier 分解 / bootstrap CI / N<30 保留 / IS-OOS 並列 (SPEC_BACKTEST §4)."""
import random
import pytest

mt = pytest.importorskip(
    "backtest.metrics",
    reason="Agent C 未実装。backtest/metrics.py を作ると緑になる。",
)


def _fake_trades(n=50, hit_rate=0.55, seed=0):
    rng = random.Random(seed)
    trades = []
    for i in range(n):
        outcome = 1 if rng.random() < hit_rate else 0
        # 単純に勝ち=+1%, 負け=-1%
        net = 1.0 if outcome else -1.0
        trades.append({
            "predicted_prob": 0.55,
            "outcome01": outcome,
            "net_pct": net,
        })
    return trades


# ── Brier 分解の恒等式 ────────────────────────────
def test_brier_decomposition_identity():
    trades = _fake_trades(n=300, hit_rate=0.55, seed=42)
    m = mt.summarize(trades, bootstrap_runs=50)
    d = m["brier_decomposition"]
    # Murphy: Brier = Reliability - Resolution + Uncertainty (許容 1e-6)
    lhs = m["brier"]
    rhs = d["reliability"] - d["resolution"] + d["uncertainty"]
    assert abs(lhs - rhs) < 1e-6, f"Brier identity violated: {lhs} vs {rhs}"


def test_calibration_table_has_bins():
    trades = _fake_trades(n=200, seed=1)
    m = mt.summarize(trades, bootstrap_runs=50)
    cal = m["calibration"]
    assert isinstance(cal, list) and cal
    for row in cal:
        for k in ("bin", "n", "pred_mean", "obs_rate"):
            assert k in row


# ── N<30 で undetermined ─────────────────────────
def test_small_sample_returns_undetermined():
    trades = _fake_trades(n=10, seed=2)
    m = mt.summarize(trades, bootstrap_runs=50, n_min=30)
    assert m["judge"] == "undetermined"
    assert m["n"] == 10


# ── bootstrap CI が 0 を跨ぐ → ev_ambiguous + undetermined ─
def test_zero_edge_yields_ambiguous_ev():
    random.seed(0)
    trades = _fake_trades(n=120, hit_rate=0.50, seed=0)
    m = mt.summarize(trades, bootstrap_runs=300, n_min=30, ci=0.95)
    lo, hi = m["avg_net_pct_ci"]
    assert lo <= 0 <= hi or m["ev_ambiguous"] is True, (
        f"50-50 edge should produce CI straddling 0; got [{lo}, {hi}]"
    )
    if m["ev_ambiguous"]:
        assert m["judge"] == "undetermined"


def test_positive_edge_with_enough_sample_passes():
    trades = _fake_trades(n=200, hit_rate=0.70, seed=5)
    m = mt.summarize(trades, bootstrap_runs=500, n_min=30, ci=0.95)
    # 強い edge なら CI が正側に出やすい
    lo, hi = m["avg_net_pct_ci"]
    assert lo > 0 or m["judge"] == "undetermined"


# ── IS / OOS 並列 + overfit_gap ───────────────────
def test_summarize_pair_returns_overfit_gap():
    is_trades = _fake_trades(n=300, hit_rate=0.80, seed=7)
    oos_trades = _fake_trades(n=300, hit_rate=0.52, seed=8)
    pair = mt.summarize_pair(is_trades, oos_trades, bootstrap_runs=200)
    assert set(pair.keys()) == {"in_sample", "out_of_sample", "overfit_gap"}
    g = pair["overfit_gap"]
    for k in ("hit_rate", "brier", "avg_net"):
        assert k in g
    # IS が明確に高いケース → hit_rate gap が正に出る
    assert g["hit_rate"] > 0


# ── max_dd ──────────────────────────────────────
def test_max_dd_present_and_non_positive():
    trades = _fake_trades(n=100, seed=3)
    # equity 系列を付与
    eq = [1.0]
    for t in trades:
        eq.append(eq[-1] * (1 + t["net_pct"] / 100))
    m = mt.summarize(trades, bootstrap_runs=50, equity_curve=eq)
    assert "max_dd_pct" in m
    assert m["max_dd_pct"] <= 0.0
