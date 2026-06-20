"""walk_forward — anchored/rolling + purge/embargo + look-ahead 厳禁 (SPEC_BACKTEST §2)."""
import pytest

wf = pytest.importorskip(
    "backtest.walk_forward",
    reason="Agent A 未実装。backtest/walk_forward.py を作ると緑になる。",
)


# ── 分割: anchored ──────────────────────────────────
def test_anchored_split_increases_train_size():
    splits = wf.make_splits(n_bars=600, mode="anchored",
                            train_min=200, test_window=40,
                            purge=5, embargo=5)
    assert len(splits) >= 1
    # train が単調増加
    sizes = [(s.train_end - s.train_start) for s in splits]
    assert sizes == sorted(sizes), f"anchored train must grow monotonically: {sizes}"
    # 必ず train < test (時系列順)
    for s in splits:
        assert s.train_end < s.test_start
        assert s.test_start < s.test_end


def test_anchored_respects_purge_and_embargo():
    splits = wf.make_splits(n_bars=400, mode="anchored",
                            train_min=200, test_window=20,
                            purge=3, embargo=2)
    for s in splits:
        gap = s.test_start - s.train_end
        # purge + embargo + 1 以上の隙間が必要
        assert gap >= 3 + 2 + 1, f"gap={gap} violates purge+embargo+1"


# ── 分割: rolling ──────────────────────────────────
def test_rolling_split_window_is_fixed():
    splits = wf.make_splits(n_bars=1000, mode="rolling",
                            train_min=200, test_window=40,
                            rolling_train_window=300,
                            purge=5, embargo=5)
    sizes = [(s.train_end - s.train_start) for s in splits]
    # 固定長 (許容 ±1)
    assert max(sizes) - min(sizes) <= 1, f"rolling train sizes vary too much: {sizes}"


# ── purge と embargo の最低値 ────────────────────
def test_zero_purge_and_zero_embargo_raises():
    with pytest.raises(ValueError):
        wf.make_splits(n_bars=400, mode="anchored",
                       train_min=200, test_window=20,
                       purge=0, embargo=0)


def test_invalid_mode_raises():
    with pytest.raises(ValueError):
        wf.make_splits(n_bars=400, mode="weird",
                       train_min=200, test_window=20,
                       purge=5, embargo=5)


# ── look-ahead 監視 list ─────────────────────────
def test_run_fold_supplies_watch_wrapped_bars():
    """run_fold は predict_fn に bars をラップ済 (上限 = train_end) で渡す.

    predict_fn が train_end を越えるインデックスを読んだら AssertionError.
    """
    bars = [{"close": float(i), "ts": f"t{i}"} for i in range(100)]
    splits = wf.make_splits(n_bars=100, mode="anchored",
                            train_min=40, test_window=10,
                            purge=2, embargo=2)
    assert splits, "test setup: at least one split needed"

    def evil_predict(watched_bars, t_index):
        # わざと未来を覗く
        try:
            _ = watched_bars[t_index + 10]
        except (IndexError, AssertionError):
            raise
        return {"direction": "long", "predicted_prob": 0.6}

    with pytest.raises(AssertionError):
        wf.run_fold(bars, splits[0], evil_predict, evaluator=lambda *a, **k: None)


def test_run_fold_passes_when_predict_stays_within_window():
    bars = [{"close": float(i), "ts": f"t{i}"} for i in range(200)]
    splits = wf.make_splits(n_bars=200, mode="anchored",
                            train_min=80, test_window=20,
                            purge=3, embargo=3)
    captured = {"calls": 0, "max_idx": -1}

    def safe_predict(watched_bars, t_index):
        captured["calls"] += 1
        captured["max_idx"] = max(captured["max_idx"], t_index)
        # 過去のみ参照
        _ = watched_bars[t_index]
        if t_index > 0:
            _ = watched_bars[t_index - 1]
        return {"direction": "long" if t_index % 2 == 0 else "short",
                "predicted_prob": 0.55}

    out = wf.run_fold(bars, splits[0], safe_predict,
                      evaluator=lambda preds, split, all_bars: {"n": len(preds)})
    assert captured["calls"] > 0
    assert out["n"] >= 1
