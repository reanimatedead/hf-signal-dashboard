"""backtest.walk_forward — anchored/rolling split + purge + embargo + look-ahead 監視.

SPEC_BACKTEST.md §2.
- predict_fn には常に **監視 list** を渡し、t_index 以降を読んだら AssertionError.
- これによりロジック改変なしで "未来を読まない" を構造で保証する.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence


@dataclass
class Split:
    train_start: int
    train_end: int       # inclusive
    test_start: int
    test_end: int        # inclusive


def make_splits(n_bars: int,
                mode: str = "anchored",
                train_min: int = 200,
                test_window: int = 40,
                rolling_train_window: int = 400,
                purge: int = 5,
                embargo: int = 5) -> List[Split]:
    if mode not in ("anchored", "rolling"):
        raise ValueError(f"mode must be anchored|rolling (got {mode!r})")
    if purge <= 0 and embargo <= 0:
        raise ValueError("purge and embargo cannot both be zero (label-leak risk)")
    if train_min <= 0 or test_window <= 0:
        raise ValueError("train_min and test_window must be positive")

    gap = purge + embargo + 1
    out: List[Split] = []
    # In rolling mode, the first anchor must already give us a full window
    # otherwise early folds would have short trains (and "fixed-length" breaks).
    if mode == "rolling":
        anchor = max(train_min, rolling_train_window) - 1
    else:
        anchor = train_min - 1   # last index inclusive of initial train
    while True:
        test_start = anchor + gap
        test_end = test_start + test_window - 1
        if test_end >= n_bars:
            break
        if mode == "anchored":
            tr_start = 0
            tr_end = anchor - purge        # leave purge headroom inside train
        else:  # rolling
            tr_start = max(0, anchor - rolling_train_window + 1)
            tr_end = anchor - purge
        if tr_end - tr_start + 1 < max(10, train_min // 4):
            # 異常に短い train は混乱の元 → スキップして次へ
            anchor += test_window
            continue
        out.append(Split(train_start=tr_start, train_end=tr_end,
                          test_start=test_start, test_end=test_end))
        anchor += test_window
    return out


# ── look-ahead 監視 list ────────────────────────────
class WatchedBars:
    """list ライクなビュー. インデックス > max_idx を読んだら AssertionError."""

    def __init__(self, src: Sequence[Any], max_idx: int):
        self._src = src
        self._max_idx = int(max_idx)

    def _check(self, i: int) -> None:
        if i < 0:
            i = len(self._src) + i
        assert i <= self._max_idx, (
            f"look-ahead leak: read index {i} > max_idx {self._max_idx}"
        )

    def __len__(self) -> int:
        # 「使える最大長」を返す — 本当に list 全長を欲しい呼び出しは別 API へ。
        return self._max_idx + 1

    def __getitem__(self, i):
        if isinstance(i, slice):
            stop = i.stop if i.stop is not None else len(self._src)
            if stop is not None and stop > self._max_idx + 1:
                raise AssertionError(
                    f"look-ahead leak: slice stop {stop} > max_idx+1 {self._max_idx + 1}"
                )
            return self._src[i]
        idx = int(i)
        self._check(idx)
        return self._src[idx]

    def __iter__(self):
        for k in range(self._max_idx + 1):
            yield self._src[k]


def run_fold(bars: Sequence[Dict[str, Any]],
             split: Split,
             predict_fn: Callable[[Any, int], Optional[Dict[str, Any]]],
             evaluator: Callable[[List[Dict[str, Any]], Split, Sequence[Dict[str, Any]]], Dict[str, Any]],
             ) -> Dict[str, Any]:
    """Iterate the test region. For each bar, call `predict_fn(watched_bars, t_index)`.

    `watched_bars` is a WatchedBars limited to indices [0..t_index]. Reading past
    that boundary raises AssertionError (caught by the test suite — see
    tests/test_walk_forward.test_predict_fn_cannot_peek_future).
    """
    preds: List[Dict[str, Any]] = []
    for t in range(split.test_start, split.test_end + 1):
        watched = WatchedBars(bars, max_idx=t)
        pred = predict_fn(watched, t)
        if pred is None:
            continue
        rec = dict(pred)
        rec["t_index"] = t
        preds.append(rec)
    return evaluator(preds, split, bars)
