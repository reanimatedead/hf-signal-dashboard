"""e2e: 仮装データ (固定 seed の random walk) で walk_forward → simulator → metrics 配線疎通 (SPEC §1 (I))."""
import math
import random

import pytest

wf = pytest.importorskip("backtest.walk_forward", reason="Agent A 未実装")
sim = pytest.importorskip("backtest.simulator", reason="Agent B 未実装")
mt = pytest.importorskip("backtest.metrics", reason="Agent C 未実装")


def _random_walk(n, seed=0, mu=0.0, sigma=0.01, start=100.0):
    rng = random.Random(seed)
    px = [start]
    for _ in range(n - 1):
        r = mu + sigma * rng.gauss(0, 1)
        px.append(max(1.0, px[-1] * math.exp(r)))
    return [{"ts": f"t{i}", "open": p, "high": p * 1.005,
             "low": p * 0.995, "close": p} for i, p in enumerate(px)]


def _simple_predict(watched, t_index):
    """過去 10 本のリターンが正なら long, 負なら short. 確率は固定 0.55.

    look-ahead を犯さないことを wf.run_fold の監視 list が保証する.
    """
    if t_index < 10:
        return None
    past = [watched[t_index - k]["close"] for k in range(10, 0, -1)]
    chg = (past[-1] - past[0]) / past[0]
    direction = "long" if chg > 0 else "short"
    return {"direction": direction, "predicted_prob": 0.55,
            "pattern": {"regime": "low_vol", "distortion": "mid"}}


def test_e2e_smoke_runs_end_to_end():
    bars = _random_walk(600, seed=42)
    splits = wf.make_splits(n_bars=len(bars), mode="anchored",
                            train_min=200, test_window=60,
                            purge=5, embargo=5)
    assert splits, "need at least one fold"

    pattern_table = {"low_vol|mid": {"take_profit_pct": 2.0, "stop_loss_pct": -1.5}}

    oos_trades = []
    is_trades = []
    for split in splits:
        # ── OOS: test 区間でシグナル生成 + 仮想実行
        def predict_in_test(watched, t_index):
            return _simple_predict(watched, t_index)
        oos_eval = wf.run_fold(bars, split, predict_in_test,
                               evaluator=lambda preds, sp, all_bars: {"preds": preds})
        # シグナル を simulator が消費できる形に
        test_bars = bars[split.test_start: split.test_end + 1]
        # 0-indexed within test_bars
        signals = []
        for p in oos_eval["preds"]:
            offset = p["t_index"] - split.test_start
            if 0 <= offset < len(test_bars):
                signals.append({
                    "bar_index": offset,
                    "direction": p["direction"],
                    "predicted_prob": p["predicted_prob"],
                    "pattern": p["pattern"],
                })
        if signals:
            res = sim.simulate_fold(test_bars, signals, pattern_table,
                                    slip_pct=0.02, fee_pct=0.01, size_pct=0.5)
            oos_trades.extend(res["trades"])

        # ── IS: train 内のサンプルでも同じ判定 (in-sample 比較用)
        is_eval_signals = []
        for ti in range(10, (split.train_end - split.train_start)):
            pred = _simple_predict(bars, split.train_start + ti)
            if pred:
                is_eval_signals.append({
                    "bar_index": ti,
                    "direction": pred["direction"],
                    "predicted_prob": pred["predicted_prob"],
                    "pattern": pred["pattern"],
                })
        train_bars = bars[split.train_start: split.train_end + 1]
        if is_eval_signals:
            res_is = sim.simulate_fold(train_bars, is_eval_signals, pattern_table,
                                       slip_pct=0.02, fee_pct=0.01, size_pct=0.5)
            is_trades.extend(res_is["trades"])

    assert len(oos_trades) > 0, "OOS trades empty — wiring broken"
    pair = mt.summarize_pair(is_trades, oos_trades, bootstrap_runs=100)
    assert "in_sample" in pair and "out_of_sample" in pair and "overfit_gap" in pair
    # 配線疎通: 主要キーが揃う
    for side in ("in_sample", "out_of_sample"):
        m = pair[side]
        for k in ("n", "judge", "hit_rate", "brier", "avg_net_pct",
                  "avg_net_pct_ci", "max_dd_pct"):
            assert k in m, f"{side}.{k} missing"
