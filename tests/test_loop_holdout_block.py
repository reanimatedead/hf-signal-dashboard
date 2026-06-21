"""Agent 3 — 直近 2 年ホールドアウト物理ブロック (SPEC_LOOP §1)."""
import datetime
import pytest

pytest.importorskip("loop.holdout", reason="Agent 3 未実装")
pytest.importorskip("loop.registry", reason="Agent 1 未実装")
pytest.importorskip("loop.runner", reason="Agent 2 未実装")

from loop import holdout, registry, runner


def _bar(ts, close=100.0):
    return {"ts": ts, "open": close, "high": close * 1.01,
            "low": close * 0.99, "close": close, "volume": 0.0}


def test_filter_pre_holdout_drops_holdout_dates():
    holdout_start = "2024-06-21"
    bars = [_bar(f"2023-0{m}-15T00:00:00") for m in range(1, 10)] + \
           [_bar(f"2024-08-15T00:00:00"), _bar(f"2025-01-15T00:00:00")]
    filtered = holdout.filter_pre_holdout(bars, holdout_start)
    assert all(b["ts"][:10] < holdout_start for b in filtered), (
        f"holdout dates leaked: {[b['ts'] for b in filtered]}"
    )
    assert len(filtered) == 9


def test_run_trial_never_reads_holdout_bars():
    """predict 関数に WatchedBars を渡し、holdout 以降を読んだら AssertionError."""
    # 仕掛け: predict をモックして、bars[-1].ts >= HOLDOUT_START の場合 fail
    holdout_start = "2024-06-21"
    bars = ([_bar(f"2023-0{m:02d}-15T00:00:00", 100 + m) for m in range(1, 10)]
            + [_bar(f"2024-08-15T00:00:00", 200), _bar(f"2025-01-15T00:00:00", 250)])
    seen_max_ts = {"x": ""}
    def sensor_predict(watched, t):
        # WatchedBars が holdout を物理ブロックしているなら、t を超えるアクセスも
        # holdout を含むアクセスも起きない.
        cur_ts = watched[t]["ts"][:10]
        if cur_ts > seen_max_ts["x"]:
            seen_max_ts["x"] = cur_ts
        return None
    runner._run_one_predict(sensor_predict, bars, holdout_start=holdout_start)
    assert seen_max_ts["x"] < holdout_start, (
        f"holdout leaked: max ts read = {seen_max_ts['x']}"
    )


def test_run_loop_filters_bars_for_all_hypotheses():
    """run_loop の中で全 hypothesis が holdout < bars のみ参照していること."""
    holdout_start = "2024-06-21"
    bars = ([_bar(f"2023-0{m:02d}-15T00:00:00", 100 + m) for m in range(1, 10)]
            + [_bar(f"2024-08-15T00:00:00", 200), _bar(f"2025-01-15T00:00:00", 250)])
    # 5 仮説に共通する filter 動作の証明: trades の ts はホールドアウト前
    res = runner.run_loop(bars_by_symbol={"^N225": bars},
                          holdout_start=holdout_start,
                          bootstrap_runs=30)
    for trial in res["trials"]:
        for trade in trial.get("_trades", []):
            assert trade["ts"][:10] < holdout_start, (
                f"holdout trade leaked in {trial['name']}: {trade['ts']}"
            )
