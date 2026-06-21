"""Agent 2 — 同一仮説の自動パラメータ探索禁止 (SPEC_LOOP §0, §3)."""
import pytest

pytest.importorskip("loop.runner", reason="Agent 2 未実装")
pytest.importorskip("loop.registry", reason="Agent 1 未実装")

from loop import runner, registry


def _bar(ts, close=100.0):
    return {"ts": ts, "open": close, "high": close * 1.01,
            "low": close * 0.99, "close": close, "volume": 0.0}


def test_each_hypothesis_runs_exactly_once_per_loop():
    """call_counts: 1 仮説あたり run_one が 1 回だけ呼ばれる."""
    bars = [_bar(f"2020-{m:02d}-15T00:00:00", 100 + m) for m in range(1, 13)]
    bars += [_bar(f"2021-{m:02d}-15T00:00:00", 110 + m) for m in range(1, 13)]
    bars += [_bar(f"2022-{m:02d}-15T00:00:00", 120 + m) for m in range(1, 13)]
    bars += [_bar(f"2023-{m:02d}-15T00:00:00", 130 + m) for m in range(1, 13)]
    counts = {h["name"]: 0 for h in registry.REGISTRY}
    original = runner.run_one
    def counting_run_one(hypothesis, bars, symbol=None, **kw):
        counts[hypothesis["name"]] += 1
        return original(hypothesis, bars, symbol=symbol, **kw)
    runner.run_one = counting_run_one
    try:
        runner.run_loop(bars_by_symbol={"^N225": bars},
                        holdout_start="2024-06-21",
                        bootstrap_runs=20)
    finally:
        runner.run_one = original
    # 1 銘柄 × 5 仮説 → 各仮説 1 回
    for name, n in counts.items():
        assert n == 1, f"{name} called {n} times — autotuning suspected"


def test_registry_params_are_immutable_during_loop():
    """ループ中に registry の params が変わらない (auto-tune の痕跡無し)."""
    snapshot = {h["name"]: dict(h.get("params", {})) for h in registry.REGISTRY}
    bars = [_bar(f"2020-01-{d:02d}T00:00:00", 100 + d) for d in range(1, 28)] * 3
    runner.run_loop(bars_by_symbol={"^N225": bars[:300]},
                    holdout_start="2024-06-21",
                    bootstrap_runs=10)
    after = {h["name"]: dict(h.get("params", {})) for h in registry.REGISTRY}
    assert snapshot == after, f"params mutated:\n  before={snapshot}\n  after ={after}"


def test_loop_does_not_pick_best_params_internally():
    """run_one 自体に「複数パラメータを試して best を返す」ロジックが無い.

    実装的には 1 hypothesis = 1 predict callable で、複数 callable から選ばない.
    """
    for h in registry.REGISTRY:
        assert callable(h.get("predict"))
        # predict は 1 つだけ. 'candidates' / 'grid' などのキーがあったら NG
        for forbidden in ("candidates", "grid", "search", "alternatives"):
            assert forbidden not in h, (
                f"{h['name']}: forbidden key '{forbidden}' suggests autotuning"
            )
