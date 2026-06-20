"""collector.backfill CLI — 冪等 / 部分失敗許容 / DuckDB optional (SPEC_BACKTEST §5)."""
import json
import pathlib
import subprocess
import sys

import pytest

bf = pytest.importorskip(
    "collector.backfill",
    reason="Agent D 未実装。collector/backfill.py を作ると緑になる。",
)


@pytest.fixture
def tmp_local(tmp_path, monkeypatch):
    monkeypatch.setattr(bf, "LOCAL_DIR", tmp_path, raising=True)
    monkeypatch.setattr(bf, "PROGRESS_PATH", tmp_path / "backfill_progress.json", raising=True)
    # 公開抜粋もテスト用 tmp に逃がして、実リポを汚さない
    monkeypatch.setattr(bf, "PUBLIC_PROGRESS_PATH", tmp_path / "backfill_progress_public.json", raising=True)
    monkeypatch.setattr(bf, "DUCKDB_PATH", tmp_path / "history.duckdb", raising=True)
    return tmp_path


# ── CLI 起動可能 ─────────────────────────────────
def test_module_main_help_runs():
    res = subprocess.run([sys.executable, "-m", "collector.backfill", "--help"],
                         capture_output=True, text=True, timeout=20)
    assert res.returncode == 0
    assert "backfill" in res.stdout.lower() or "usage" in res.stdout.lower()


# ── dry-run はネットワークを叩かない ───────────
def test_dry_run_emits_plan_without_fetch(tmp_local, monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("dry-run must not call fetch_history")
    monkeypatch.setattr(bf, "_fetch_history_one", boom, raising=True)
    res = bf.run(symbols=["^N225", "USDJPY=X"], period="1mo",
                 intervals=["1d"], dry_run=True)
    assert res["dry_run"] is True
    assert "plan" in res and len(res["plan"]) == 2


# ── 冪等: 2 回実行で行が増えない ──────────────
def test_backfill_is_idempotent(tmp_local, monkeypatch):
    calls = {"n": 0}
    def fake_fetch(symbol, period, interval):
        calls["n"] += 1
        return [
            {"ts": "2026-01-01T00:00:00", "open": 100.0, "high": 101.0,
             "low": 99.0, "close": 100.5, "volume": 1000},
            {"ts": "2026-01-02T00:00:00", "open": 100.5, "high": 102.0,
             "low": 100.0, "close": 101.5, "volume": 1100},
        ]
    monkeypatch.setattr(bf, "_fetch_history_one", fake_fetch, raising=True)
    r1 = bf.run(symbols=["TEST"], period="1mo", intervals=["1d"])
    r2 = bf.run(symbols=["TEST"], period="1mo", intervals=["1d"])
    # store には 2 行のみ (重複しない)
    rows = bf.read_all(symbol="TEST", interval="1d")
    assert len(rows) == 2, f"expected 2 unique rows, got {len(rows)}"
    assert r2["written_total"] == 0 or r2.get("duplicates_skipped", 0) >= 1


# ── 部分失敗で例外を投げない ────────────────────
def test_partial_failure_does_not_abort(tmp_local, monkeypatch):
    def fake_fetch(symbol, period, interval):
        if symbol == "BROKEN":
            raise RuntimeError("yfinance HTTP 503")
        return [{"ts": "2026-01-01T00:00:00", "open": 1.0, "high": 1.0,
                 "low": 1.0, "close": 1.0, "volume": 0}]
    monkeypatch.setattr(bf, "_fetch_history_one", fake_fetch, raising=True)
    res = bf.run(symbols=["A", "BROKEN", "B"], period="1mo", intervals=["1d"])
    assert res["ok"] is True
    assert any("BROKEN" in e for e in res["errors"])
    # 失敗銘柄以外は書き込まれている
    assert bf.read_all(symbol="A", interval="1d")
    assert bf.read_all(symbol="B", interval="1d")


# ── DuckDB が無くても落ちない ──────────────────
def test_works_without_duckdb(tmp_local, monkeypatch):
    monkeypatch.setattr(bf, "_DUCKDB", None, raising=False)
    def fake_fetch(symbol, period, interval):
        return [{"ts": "2026-01-01T00:00:00", "open": 1.0, "high": 1.0,
                 "low": 1.0, "close": 1.0, "volume": 0}]
    monkeypatch.setattr(bf, "_fetch_history_one", fake_fetch, raising=True)
    res = bf.run(symbols=["X"], period="1mo", intervals=["1d"])
    assert res["ok"] is True
    # fallback jsonl が書かれている
    files = list(tmp_local.glob("history_*.jsonl"))
    assert files, "jsonl fallback must produce a file when DuckDB unavailable"


# ── 進捗 json が出力される ──────────────────────
def test_progress_json_emitted(tmp_local, monkeypatch):
    monkeypatch.setattr(bf, "_fetch_history_one",
        lambda s, p, i: [{"ts": "2026-01-01T00:00:00", "open": 1.0,
                          "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0}],
        raising=True)
    bf.run(symbols=["X"], period="1mo", intervals=["1d"])
    p = bf.PROGRESS_PATH
    assert p.exists()
    body = json.loads(p.read_text())
    assert "symbols" in body
