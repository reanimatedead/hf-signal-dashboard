"""H1 3 ラベル定義の正確性 (SPEC_H1 §2)."""
import math
import pytest

h1 = pytest.importorskip("backtest.h1", reason="Agent A/B 未実装")


def _bar(ts, open_, close):
    return {"ts": ts, "open": open_, "high": max(open_, close) * 1.01,
            "low": min(open_, close) * 0.99, "close": close, "volume": 0.0}


def test_overnight_uses_prev_close_to_open():
    bars = [
        _bar("2024-01-04T00:00:00", open_=1000.0, close=1010.0),
        _bar("2024-01-05T00:00:00", open_=1020.0, close=1015.0),
    ]
    labels = h1.compute_labels(bars)
    # bar[1].overnight = (1020 - 1010) / 1010
    assert labels[1]["overnight"] is not None
    assert abs(labels[1]["overnight"] - (1020.0 - 1010.0) / 1010.0) < 1e-9


def test_open_to_close_is_intraday():
    bars = [
        _bar("2024-01-04T00:00:00", open_=1000.0, close=1010.0),
        _bar("2024-01-05T00:00:00", open_=1020.0, close=1040.0),
    ]
    labels = h1.compute_labels(bars)
    # bar[1].open_to_close = (1040 - 1020) / 1020
    assert abs(labels[1]["open_to_close"] - (1040.0 - 1020.0) / 1020.0) < 1e-9


def test_next_week_is_5_bars_forward():
    bars = [_bar(f"2024-01-{d:02d}T00:00:00", open_=1000.0, close=1000.0 + d)
            for d in range(1, 11)]
    labels = h1.compute_labels(bars)
    # bars[1] is d=2 (close=1002); bars[1+5] = bars[6] is d=7 (close=1007).
    expected = (1007.0 - 1002.0) / 1002.0
    assert abs(labels[1]["next_week"] - expected) < 1e-9


def test_first_bar_has_no_overnight():
    bars = [
        _bar("2024-01-04T00:00:00", open_=1000.0, close=1010.0),
        _bar("2024-01-05T00:00:00", open_=1020.0, close=1015.0),
    ]
    labels = h1.compute_labels(bars)
    assert labels[0]["overnight"] is None


def test_last_5_bars_have_no_next_week():
    bars = [_bar(f"2024-01-{d:02d}T00:00:00", open_=1000.0, close=1000.0 + d)
            for d in range(1, 8)]   # 7 bars
    labels = h1.compute_labels(bars)
    # bars[2] + 5 = bars[7] doesn't exist; same for [3..6]
    for i in range(2, 7):
        assert labels[i]["next_week"] is None, (
            f"label[{i}].next_week should be None (not enough forward bars)"
        )
    # bars[1] + 5 = bars[6] exists
    assert labels[1]["next_week"] is not None


def test_invalid_open_handled():
    bars = [
        _bar("2024-01-04T00:00:00", open_=1000.0, close=1010.0),
        _bar("2024-01-05T00:00:00", open_=0.0, close=1015.0),    # open=0 → invalid
    ]
    labels = h1.compute_labels(bars)
    assert labels[1]["open_to_close"] is None
