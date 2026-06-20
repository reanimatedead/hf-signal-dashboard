"""backtest.simulator — slip / fee 控除 / 天井クランプ (SPEC_BACKTEST §3)."""
import pytest

sim = pytest.importorskip(
    "backtest.simulator",
    reason="Agent B 未実装。backtest/simulator.py を作ると緑になる。",
)
from survival import risk_engine as re   # 既存 Phase 1


def _bars(prices):
    return [{"ts": f"t{i}", "open": p, "high": p * 1.005, "low": p * 0.995, "close": p}
            for i, p in enumerate(prices)]


# ── スリッページ + 手数料が必ず控除 ──────────────
def test_slippage_and_fee_reduce_gross_to_net():
    bars = _bars([100.0] * 50)
    # 価格不変 → gross 0% だが slip+fee で必ず負
    signals = [{"bar_index": 0, "direction": "long",
                "predicted_prob": 0.55,
                "pattern": {"regime": "low_vol", "distortion": "mid"}}]
    res = sim.simulate_fold(bars, signals,
                            pattern_table={"low_vol|mid": {"take_profit_pct": 1.0,
                                                            "stop_loss_pct": -1.0}},
                            slip_pct=0.05, fee_pct=0.02, size_pct=0.5)
    assert res["n_trades"] >= 1
    t = res["trades"][0]
    # slip と fee 控除で net < gross (gross が 0 でも net は負)
    assert t["net_pct"] < t["gross_pct"], (
        f"net ({t['net_pct']}) must be smaller than gross ({t['gross_pct']})"
    )


# ── HARD_CAPS の強制 ─────────────────────────────
def test_size_pct_clamped_to_hard_cap():
    bars = _bars([100.0] * 20)
    signals = [{"bar_index": 0, "direction": "long",
                "predicted_prob": 0.6, "pattern": {}}]
    res = sim.simulate_fold(bars, signals,
                            pattern_table={"low_vol|mid": {"take_profit_pct": 1.0,
                                                            "stop_loss_pct": -1.0}},
                            slip_pct=0.0, fee_pct=0.0,
                            size_pct=99.0)   # わざと天井超え
    assert res["effective_size_pct"] <= re.HARD_CAPS["PER_TRADE_PCT_MAX"], (
        "size must be clamped to HARD_CAPS"
    )


# ── TP / SL / TIMEOUT 発火 ────────────────────────
def test_take_profit_long_fires_on_rally():
    # entry @ 100, target +5%, バー 5 で 110
    bars = _bars([100, 101, 102, 105, 108, 110, 109])
    signals = [{"bar_index": 0, "direction": "long",
                "predicted_prob": 0.7, "pattern": {}}]
    res = sim.simulate_fold(bars, signals,
                            pattern_table={"low_vol|mid": {"take_profit_pct": 5.0,
                                                            "stop_loss_pct": -3.0}},
                            slip_pct=0.0, fee_pct=0.0)
    t = res["trades"][0]
    assert t["kind"] == "EXIT_TP"
    assert t["outcome01"] == 1


def test_stop_loss_long_fires_on_decline():
    bars = _bars([100, 99, 98, 95, 92, 90])
    signals = [{"bar_index": 0, "direction": "long",
                "predicted_prob": 0.6, "pattern": {}}]
    res = sim.simulate_fold(bars, signals,
                            pattern_table={"low_vol|mid": {"take_profit_pct": 10.0,
                                                            "stop_loss_pct": -5.0}},
                            slip_pct=0.0, fee_pct=0.0)
    t = res["trades"][0]
    assert t["kind"] == "EXIT_SL"
    assert t["outcome01"] == 0


def test_timeout_forces_exit():
    bars = _bars([100.0 + 0.001 * i for i in range(200)])
    signals = [{"bar_index": 0, "direction": "long",
                "predicted_prob": 0.55, "pattern": {}}]
    res = sim.simulate_fold(bars, signals,
                            pattern_table={"low_vol|mid": {"take_profit_pct": 10.0,
                                                            "stop_loss_pct": -10.0}},
                            slip_pct=0.0, fee_pct=0.0)
    t = res["trades"][0]
    assert t["kind"] == "EXIT_TIMEOUT"


# ── 同時保有上限 ──────────────────────────────────
def test_concurrent_positions_capped():
    bars = _bars([100.0] * 60)
    # 4 件同時シグナル (天井=3)
    signals = [
        {"bar_index": 0, "direction": "long", "predicted_prob": 0.55, "pattern": {}, "symbol": "A"},
        {"bar_index": 0, "direction": "long", "predicted_prob": 0.55, "pattern": {}, "symbol": "B"},
        {"bar_index": 0, "direction": "long", "predicted_prob": 0.55, "pattern": {}, "symbol": "C"},
        {"bar_index": 0, "direction": "long", "predicted_prob": 0.55, "pattern": {}, "symbol": "D"},
    ]
    res = sim.simulate_fold(bars, signals,
                            pattern_table={"low_vol|mid": {"take_profit_pct": 5.0,
                                                            "stop_loss_pct": -3.0}},
                            slip_pct=0.0, fee_pct=0.0)
    assert res["n_trades"] <= re.HARD_CAPS["MAX_CONCURRENT"], (
        f"concurrent trades must be capped: n={res['n_trades']}"
    )


# ── equity curve と maxDD ─────────────────────────
def test_equity_curve_and_max_dd_computed():
    bars = _bars([100, 105, 110, 90, 88, 95])
    signals = [{"bar_index": 0, "direction": "long",
                "predicted_prob": 0.55, "pattern": {}}]
    res = sim.simulate_fold(bars, signals,
                            pattern_table={"low_vol|mid": {"take_profit_pct": 8.0,
                                                            "stop_loss_pct": -5.0}},
                            slip_pct=0.0, fee_pct=0.0)
    assert "equity_curve" in res and len(res["equity_curve"]) >= 2
    assert "max_dd_pct" in res
    assert res["max_dd_pct"] <= 0.0
