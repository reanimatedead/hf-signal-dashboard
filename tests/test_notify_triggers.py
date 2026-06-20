"""notify.triggers — look-ahead 厳禁 / ENTRY/EXIT 判定 (SPEC_NOTIFY §4, §10.5)."""
import math
import pytest

tr = pytest.importorskip(
    "notify.triggers",
    reason="Agent A 未実装。notify/triggers.py を作ると緑になる。",
)


def _bar(close, ts="2026-06-20T00:00:00Z"):
    return {"close": float(close), "ts": ts, "tf": "1d"}


def _series(prices):
    return [_bar(p, ts=f"2026-06-{20+i:02d}T00:00:00Z") for i, p in enumerate(prices)]


# ── ENTRY 閾値 ─────────────────────────────────────────
def test_no_entry_below_threshold():
    bars = _series([100, 101, 102])
    out = tr.evaluate(bars, t_index=2, state={}, edge_score_at_t=60,
                      pattern={"regime": "low_vol", "distortion": "mid"},
                      symbol="AAPL", side="long",
                      pattern_table=tr.DEFAULT_TABLE)
    assert out == [], "edge < 70 must not ENTRY"


def test_entry_at_threshold():
    bars = _series([100, 101, 102])
    out = tr.evaluate(bars, t_index=2, state={}, edge_score_at_t=72,
                      pattern={"regime": "high_vol", "distortion": "high"},
                      symbol="AAPL", side="long",
                      pattern_table=tr.DEFAULT_TABLE)
    assert len(out) == 1
    assert out[0]["kind"] == "ENTRY"
    assert out[0]["price"] == 102.0
    assert out[0]["edge_score"] == 72


def test_no_double_entry_when_position_open():
    bars = _series([100, 101, 102])
    out = tr.evaluate(bars, t_index=2,
                      state={"AAPL": {"event_id": "x", "side": "long",
                                       "entry_price": 100,
                                       "entry_bar": 0,
                                       "exit_targets": {"take_profit_pct": 5.0,
                                                         "stop_loss_pct": -3.0}}},
                      edge_score_at_t=85,
                      pattern={"regime": "high_vol", "distortion": "high"},
                      symbol="AAPL", side="long",
                      pattern_table=tr.DEFAULT_TABLE)
    # 既ポジ AAPL に対する ENTRY は出ない。EXIT 条件にも到達してないので空。
    assert out == []


# ── EXIT TP / SL / TIMEOUT ────────────────────────────
def test_exit_tp_long_when_price_reaches_target():
    bars = _series([100, 101, 105])     # +5% (TP=3%)
    state = {"AAPL": {"event_id": "e1", "side": "long",
                       "entry_price": 100.0, "entry_bar": 0,
                       "exit_targets": {"take_profit_pct": 3.0,
                                         "stop_loss_pct": -2.0}}}
    out = tr.evaluate(bars, t_index=2, state=state, edge_score_at_t=10,
                      pattern={}, symbol="AAPL", side="long",
                      pattern_table=tr.DEFAULT_TABLE)
    assert len(out) == 1 and out[0]["kind"] == "EXIT_TP"
    assert out[0]["entry_ref"] == "e1"
    assert math.isclose(out[0]["realized_pct"], 5.0, abs_tol=0.0001)


def test_exit_sl_short_when_price_jumps_up():
    bars = _series([100, 101, 110])
    state = {"AAPL": {"event_id": "e2", "side": "short",
                       "entry_price": 100.0, "entry_bar": 0,
                       "exit_targets": {"take_profit_pct": 3.0,
                                         "stop_loss_pct": -2.0}}}
    out = tr.evaluate(bars, t_index=2, state=state, edge_score_at_t=10,
                      pattern={}, symbol="AAPL", side="short",
                      pattern_table=tr.DEFAULT_TABLE)
    assert len(out) == 1 and out[0]["kind"] == "EXIT_SL"


def test_exit_timeout_after_max_hold_bars():
    bars = _series([100.0 + i * 0.01 for i in range(60)])
    state = {"AAPL": {"event_id": "e3", "side": "long",
                       "entry_price": 100.0, "entry_bar": 0,
                       "exit_targets": {"take_profit_pct": 10.0,
                                         "stop_loss_pct": -10.0}}}
    out = tr.evaluate(bars, t_index=tr.MAX_HOLD_BARS + 1,
                      state=state, edge_score_at_t=10,
                      pattern={}, symbol="AAPL", side="long",
                      pattern_table=tr.DEFAULT_TABLE)
    assert len(out) == 1 and out[0]["kind"] == "EXIT_TIMEOUT"


# ── look-ahead 厳禁: bars[t+1:] を改竄しても結果が変わらない ──
def test_evaluate_ignores_future_bars():
    bars = _series([100, 101, 102, 999_999, math.nan])
    out1 = tr.evaluate(bars, t_index=2, state={}, edge_score_at_t=85,
                       pattern={"regime": "high_vol", "distortion": "high"},
                       symbol="AAPL", side="long",
                       pattern_table=tr.DEFAULT_TABLE)
    # 未来を 0 に置き換えても結果同じ
    bars2 = _series([100, 101, 102, 0.0, 0.0])
    out2 = tr.evaluate(bars2, t_index=2, state={}, edge_score_at_t=85,
                       pattern={"regime": "high_vol", "distortion": "high"},
                       symbol="AAPL", side="long",
                       pattern_table=tr.DEFAULT_TABLE)
    assert out1 == out2, "future bars must not change t-index judgement"


def test_evaluate_does_not_index_future_bars():
    """関数中で bars[t_index+1:] を読まないことを「アクセス監視 list」で担保。"""
    class Watch(list):
        def __init__(self, src, max_idx):
            super().__init__(src)
            self.max_idx = max_idx
            self.violated = False

        def __getitem__(self, i):
            if isinstance(i, slice):
                # 末尾アクセス. stop が max_idx 以下なら OK.
                stop = i.stop if i.stop is not None else len(self)
                if stop > self.max_idx + 1:
                    self.violated = True
            elif isinstance(i, int):
                idx = i if i >= 0 else len(self) + i
                if idx > self.max_idx:
                    self.violated = True
            return super().__getitem__(i)

    src = _series([100, 101, 102, 200, 50])
    w = Watch(src, max_idx=2)
    tr.evaluate(w, t_index=2, state={}, edge_score_at_t=85,
                pattern={"regime": "high_vol", "distortion": "high"},
                symbol="AAPL", side="long",
                pattern_table=tr.DEFAULT_TABLE)
    assert w.violated is False, "evaluate read a bar with index > t_index (look-ahead leak)"
