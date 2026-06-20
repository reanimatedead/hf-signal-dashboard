"""backtest.local_loader — jsonl/duckdb 読込 + 整列 + min_bars 除外 (SPEC_BACKTEST_LIVE §1)."""
import json
import pathlib
import pytest

ll = pytest.importorskip(
    "backtest.local_loader",
    reason="Agent A 未実装。backtest/local_loader.py を作ると緑になる。",
)


def _write_jsonl(path: pathlib.Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _bar(ts, close=100.0, sym="USDJPY=X", iv="1d"):
    return {"ts": ts, "open": close, "high": close * 1.01,
            "low": close * 0.99, "close": close, "volume": 0.0,
            "symbol": sym, "interval": iv}


@pytest.fixture
def tmp_local(tmp_path, monkeypatch):
    monkeypatch.setattr(ll, "LOCAL_DIR", tmp_path, raising=True)
    monkeypatch.setattr(ll, "DUCKDB_PATH", tmp_path / "history.duckdb", raising=True)
    return tmp_path


# ── basic load ──────────────────────────────────────
def test_load_all_reads_jsonl(tmp_local):
    rows = [_bar(f"2020-01-{d:02d}T00:00:00", close=100 + d) for d in range(1, 20)]
    _write_jsonl(tmp_local / "history_USDJPY_X_1d.jsonl", rows)
    res = ll.load_all(interval="1d", min_bars=10, source="jsonl")
    assert res["source_used"] == "jsonl"
    assert "USDJPY=X" in res["symbols"]
    sym = res["symbols"]["USDJPY=X"]
    assert sym["n"] == 19
    assert sym["first_ts"] <= sym["last_ts"]


def test_min_bars_below_threshold_goes_to_excluded(tmp_local):
    rows = [_bar(f"2020-01-{d:02d}T00:00:00") for d in range(1, 5)]
    _write_jsonl(tmp_local / "history_USDJPY_X_1d.jsonl", rows)
    res = ll.load_all(interval="1d", min_bars=10, source="jsonl")
    assert "USDJPY=X" not in res["symbols"]
    excluded = res["excluded"]
    assert "USDJPY=X" in excluded
    assert excluded["USDJPY=X"]["reason"] == "insufficient_data"
    assert excluded["USDJPY=X"]["n"] == 4


# ── deduplication ───────────────────────────────────
def test_duplicate_ts_keeps_latest(tmp_local):
    # 同一 ts を 2 行: 後勝ち
    rows = [_bar("2020-01-01T00:00:00", close=100.0),
            _bar("2020-01-02T00:00:00", close=101.0),
            _bar("2020-01-01T00:00:00", close=999.0),    # duplicate
            _bar("2020-01-03T00:00:00", close=102.0)]
    _write_jsonl(tmp_local / "history_X_1d.jsonl", rows)
    res = ll.load_all(interval="1d", min_bars=3, source="jsonl")
    assert "X" in res["symbols"]
    bars = res["symbols"]["X"]["bars"]
    assert len(bars) == 3
    first = next(b for b in bars if b["ts"].startswith("2020-01-01"))
    assert first["close"] == 999.0   # 最新値で正規化


# ── sort order ──────────────────────────────────────
def test_bars_are_sorted_ascending(tmp_local):
    rows = [_bar(f"2020-01-{d:02d}T00:00:00") for d in (5, 1, 3, 2, 4)]
    _write_jsonl(tmp_local / "history_X_1d.jsonl", rows)
    res = ll.load_all(interval="1d", min_bars=3, source="jsonl")
    bars = res["symbols"]["X"]["bars"]
    ts = [b["ts"] for b in bars]
    assert ts == sorted(ts), f"bars must be sorted ascending: {ts}"


# ── 非数値 close は弾く ─────────────────────────────
def test_invalid_close_rows_dropped(tmp_local):
    rows = [_bar("2020-01-01T00:00:00", close=100.0)]
    rows.append({"ts": "2020-01-02T00:00:00", "close": None, "symbol": "X", "interval": "1d"})
    rows.append({"ts": "2020-01-03T00:00:00", "close": "NaN", "symbol": "X", "interval": "1d"})
    rows.append(_bar("2020-01-04T00:00:00", close=102.0))
    _write_jsonl(tmp_local / "history_X_1d.jsonl", rows)
    res = ll.load_all(interval="1d", min_bars=2, source="jsonl")
    bars = res["symbols"]["X"]["bars"]
    assert len(bars) == 2, f"invalid close rows must be dropped: {[b['close'] for b in bars]}"


# ── interval filter ────────────────────────────────
def test_interval_filter_skips_other_tf(tmp_local):
    _write_jsonl(tmp_local / "history_X_1d.jsonl",
                  [_bar(f"2020-01-{d:02d}T00:00:00") for d in range(1, 10)])
    _write_jsonl(tmp_local / "history_X_1wk.jsonl",
                  [_bar(f"2020-01-{d:02d}T00:00:00", iv="1wk") for d in range(1, 10)])
    res = ll.load_all(interval="1d", min_bars=3, source="jsonl")
    # 1d だけ収集
    syms = list(res["symbols"].keys())
    assert syms == ["X"]


def test_summary_counts_present(tmp_local):
    _write_jsonl(tmp_local / "history_A_1d.jsonl",
                  [_bar(f"2020-01-{d:02d}T00:00:00", sym="A") for d in range(1, 11)])
    _write_jsonl(tmp_local / "history_B_1d.jsonl",
                  [_bar(f"2020-01-{d:02d}T00:00:00", sym="B") for d in range(1, 3)])
    res = ll.load_all(interval="1d", min_bars=5, source="jsonl")
    assert len(res["symbols"]) == 1     # A だけ
    assert len(res["excluded"]) == 1    # B
    assert res["totals"]["n_symbols"] == 1
    assert res["totals"]["n_excluded"] == 1
