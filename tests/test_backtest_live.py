"""backtest.cli --source=local — 実レート結線 e2e (SPEC_BACKTEST_LIVE §2)."""
import json
import math
import pathlib
import random

import pytest

cli = pytest.importorskip("backtest.cli", reason="Agent A/B 未実装")
ll = pytest.importorskip("backtest.local_loader", reason="Agent A 未実装")


def _write_walk(path: pathlib.Path, n=800, seed=7, sym="USDJPY=X"):
    rng = random.Random(seed)
    px = [100.0]
    for _ in range(n - 1):
        px.append(max(1.0, px[-1] * math.exp(0.0 + 0.01 * rng.gauss(0, 1))))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for i, p in enumerate(px):
            f.write(json.dumps({
                "ts": f"2020-01-01T{i:04d}",
                "open": p, "high": p * 1.005, "low": p * 0.995,
                "close": p, "volume": 0.0,
                "symbol": sym, "interval": "1d",
            }, ensure_ascii=False) + "\n")


@pytest.fixture
def tmp_local(tmp_path, monkeypatch):
    monkeypatch.setattr(ll, "LOCAL_DIR", tmp_path, raising=True)
    monkeypatch.setattr(ll, "DUCKDB_PATH", tmp_path / "history.duckdb", raising=True)
    # 公開抜粋もテスト用 tmp に逃がす
    public = tmp_path / "backtest_summary_public.json"
    monkeypatch.setattr(cli, "PUBLIC_RESULT_PATH", public, raising=True)
    return tmp_path


def test_run_local_emits_per_symbol_and_overall(tmp_local):
    _write_walk(tmp_local / "history_USDJPY_X_1d.jsonl", n=800, seed=1, sym="USDJPY=X")
    _write_walk(tmp_local / "history_EURUSD_X_1d.jsonl", n=800, seed=2, sym="EURUSD=X")
    res = cli.run_local(interval="1d", train_min=200, test_window=60,
                        purge=5, embargo=5, slip_pct=0.02, fee_pct=0.01,
                        size_pct=0.5)
    assert res["ok"] is True
    assert res["source_used"] in ("jsonl", "duckdb")
    assert "per_symbol" in res
    syms = [r["symbol"] for r in res["per_symbol"]]
    assert "USDJPY=X" in syms and "EURUSD=X" in syms
    for s in res["per_symbol"]:
        assert s["judge"] in ("edge", "no-edge", "inconclusive", "insufficient")
        assert "in_sample" in s and "out_of_sample" in s
        assert "overfit_gap" in s
    assert "overall" in res
    overall = res["overall"]
    assert overall["judge"] in ("edge", "no-edge", "inconclusive", "insufficient")
    assert "out_of_sample" in overall and "in_sample" in overall


def test_run_local_excludes_thin_symbols(tmp_local):
    # 太い銘柄
    _write_walk(tmp_local / "history_USDJPY_X_1d.jsonl", n=600, seed=1)
    # 薄い銘柄 (min_bars に届かない)
    _write_walk(tmp_local / "history_BAR_1d.jsonl", n=50, seed=2, sym="BAR")
    res = cli.run_local(interval="1d", train_min=300, test_window=60,
                        purge=5, embargo=5)
    syms = [r["symbol"] for r in res["per_symbol"]]
    assert "BAR" not in syms
    excluded_syms = [e["symbol"] for e in res["excluded"]]
    assert "BAR" in excluded_syms


def test_run_local_public_summary_written(tmp_local):
    _write_walk(tmp_local / "history_USDJPY_X_1d.jsonl", n=600, seed=11)
    cli.run_local(interval="1d", train_min=200, test_window=60,
                  purge=5, embargo=5)
    public = tmp_local / "backtest_summary_public.json"
    assert public.exists()
    body = json.loads(public.read_text(encoding="utf-8"))
    for k in ("per_symbol", "overall", "note", "as_of_utc", "source_used"):
        assert k in body
    assert "想定精度" in body["note"] or "not investment advice" in body["note"]


def test_judge_categories_well_defined():
    # 4 値だけ受け入れる
    for j in ("edge", "no-edge", "inconclusive", "insufficient"):
        assert cli._classify_judge(_make_metric(judge_input=j))["judge"] == j


def _make_metric(judge_input):
    if judge_input == "edge":
        return {"n": 100, "avg_net_pct_ci": [0.05, 0.5], "ev_ambiguous": False}
    if judge_input == "no-edge":
        return {"n": 100, "avg_net_pct_ci": [-0.5, -0.05], "ev_ambiguous": False}
    if judge_input == "inconclusive":
        return {"n": 100, "avg_net_pct_ci": [-0.1, 0.1], "ev_ambiguous": True}
    return {"n": 10, "avg_net_pct_ci": [-0.1, 0.1], "ev_ambiguous": True}
