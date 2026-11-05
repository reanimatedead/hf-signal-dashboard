"""日付別の日足ファイル（<data_dir>/japan/daily/YYYY-MM-DD.json）を銘柄別の配列にまとめる。式は持たない。"""

from __future__ import annotations

import json
from collections.abc import Collection

import numpy as np

from ..config import Config
from ..dates import files_dates

Panel = dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]


def load_panel(
    cfg: Config,
    codes: Collection[str] | None = None,
    since: str | None = None,
    va_out: dict[str, np.ndarray] | None = None,
) -> tuple[list[str], Panel]:
    """戻り値: (dates, {code4: (H, L, C)})。行の形は [Code4, AdjH, AdjL, AdjC, Va]。
    va_out を渡すと {code4: 売買代金 Va（dates と同じ長さ・無い日は NaN）} を入れる（売買スコアの減点用）。"""
    dates: list[str] = []
    data: dict[str, list[tuple[int, float, float, float]]] = {}
    vas: dict[str, list[tuple[int, float]]] = {}
    for d in files_dates(cfg.jp("daily", "*.json")):
        if since and d < since:
            continue
        with open(cfg.jp("daily", f"{d}.json")) as fh:
            rows = json.load(fh)
        if not rows:
            continue
        dates.append(d)
        i = len(dates) - 1
        for c, h, low, cl, va in rows:
            if codes is not None and c not in codes:
                continue
            if cl is None:
                continue
            data.setdefault(c, []).append((i, h or cl, low or cl, cl))
            if va_out is not None and va is not None:
                vas.setdefault(c, []).append((i, va))
    n = len(dates)
    out: Panel = {}
    for c, v in data.items():
        H = np.full(n, np.nan)
        L = np.full(n, np.nan)
        C = np.full(n, np.nan)
        for i, h, low, cl in v:
            H[i], L[i], C[i] = h, low, cl
        out[c] = (H, L, C)
    if va_out is not None:
        for c, vv in vas.items():
            V = np.full(n, np.nan)
            for i, va in vv:
                V[i] = va
            va_out[c] = V
    return dates, out
