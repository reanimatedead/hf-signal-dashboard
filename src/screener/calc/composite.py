"""総合スコア（composite_score 0〜100 と STRONG BUY〜AVOID）の表。規則はここ1か所。

fetch_signals.compute_signal（公開画面のスコア・検証）と 仕組み（About）の表示の両方がこの表を使う。
入力は計算済みの指標（RSI・MACD ヒストグラム・EMA・BB%）だけ（データは持たない）。
"""

from __future__ import annotations

import math
from typing import Any

# 指標の期間（fetch_signals の calc_rsi / calc_macd / calc_bollinger / calc_atr と EMA がこの値を使う）
PERIODS: dict[str, Any] = {
    "rsi": 14,
    "macd": (12, 26, 9),
    "bb": 20,
    "bb_k": 2.0,
    "ema": (20, 50, 200),
    "ema200_min_bars": 40,  # これより短い履歴では EMA200 を使わない（EMA50 で代わりにする）
    "atr": 14,
}

# RSI: 値が「以下」なら点（上から順に最初に当てはまったもの）。どれにも当てはまらなければ 0 点。
RSI_TIERS: tuple[tuple[float, int], ...] = ((25, 25), (35, 21), (45, 16), (55, 12), (65, 7), (75, 3))
# MACD ヒストグラム: 正なら pos 点。0 以下は max(0, int(scale × (1 + h / (|h| + 1e-6)) × factor))（0〜scale×factor 点）
MACD: dict[str, float] = {"pos": 20, "scale": 25, "factor": 0.4}
# EMA の並び: (条件コード, 点)。上から順に最初に当てはまったもの。EMA200 がある時と無い時で表が違う。
EMA_WITH_200: tuple[tuple[str, int], ...] = (
    ("p_e20_e50_e200", 25),  # 終値 > EMA20 > EMA50 > EMA200
    ("p_e20_e50", 20),  # 終値 > EMA20 > EMA50
    ("p_e50_and_e200", 15),  # 終値 > EMA50 かつ 終値 > EMA200
    ("p_e200", 8),  # 終値 > EMA200
)
EMA_WITH_200_ELSE = 0
EMA_NO_200: tuple[tuple[str, int], ...] = (("p_e20_e50", 20), ("p_e50", 13))
EMA_NO_200_ELSE = 3
# BB%（BB20 の帯の中の位置 0〜1）: 値が「以下」なら点。どれにも当てはまらなければ 0 点。
BB_TIERS: tuple[tuple[float, int], ...] = ((0.05, 25), (0.20, 21), (0.35, 16), (0.55, 10), (0.75, 5), (0.90, 2))
# 合計（0〜100 に切る）が「以上」ならラベル。どれにも当てはまらなければ LABEL_ELSE。
LABEL_CUTS: tuple[tuple[int, str], ...] = ((78, "strong_buy"), (63, "buy"), (43, "hold"), (28, "watch"))
LABEL_ELSE = "avoid"


def _ema_ok(code: str, p: float, e20: float, e50: float, e200: float) -> bool:
    return {
        "p_e20_e50_e200": p > e20 > e50 > e200,
        "p_e20_e50": p > e20 > e50,
        "p_e50_and_e200": p > e50 and p > e200,
        "p_e200": p > e200,
        "p_e50": p > e50,
    }[code]


def _tier(v: float, tiers: tuple[tuple[float, int], ...]) -> int:
    for th, pts in tiers:
        if v <= th:
            return pts
    return 0


def score(rsi: float, macd_hist: float, ema20: float, ema50: float, ema200: float, bb_pct: float, price: float) -> int:
    s = _tier(rsi, RSI_TIERS)
    if macd_hist > 0:
        s += int(MACD["pos"])
    else:
        s += max(0, int(MACD["scale"] * (1 + macd_hist / (abs(macd_hist) + 1e-6)) * MACD["factor"]))
    if not math.isnan(ema200):
        s += next((p for c, p in EMA_WITH_200 if _ema_ok(c, price, ema20, ema50, ema200)), EMA_WITH_200_ELSE)
    else:
        s += next((p for c, p in EMA_NO_200 if _ema_ok(c, price, ema20, ema50, ema200)), EMA_NO_200_ELSE)
    s += _tier(bb_pct, BB_TIERS)
    return min(100, max(0, s))


def label(s: float) -> str:
    return next((lab for th, lab in LABEL_CUTS if s >= th), LABEL_ELSE)


def compute(
    rsi: float, macd_hist: float, ema20: float, ema50: float, ema200: float, bb_pct: float, price: float
) -> tuple[int, str]:
    """(スコア, ラベルのコード)。ラベルはコード（表示文は UI 辞書）。"""
    s = score(rsi, macd_hist, ema20, ema50, ema200, bb_pct, price)
    return s, label(s)


def rules() -> dict[str, Any]:
    """表をそのまま機械が読める形で（仕組み（About）の表示と docs/about.json 用）。"""
    return {
        "periods": {k: list(v) if isinstance(v, tuple) else v for k, v in PERIODS.items()},
        "rsi_tiers": [{"le": th, "pts": p} for th, p in RSI_TIERS],
        "macd": dict(MACD),
        "ema_with_200": [{"cond": c, "pts": p} for c, p in EMA_WITH_200],
        "ema_with_200_else": EMA_WITH_200_ELSE,
        "ema_no_200": [{"cond": c, "pts": p} for c, p in EMA_NO_200],
        "ema_no_200_else": EMA_NO_200_ELSE,
        "bb_tiers": [{"le": th, "pts": p} for th, p in BB_TIERS],
        "label_cuts": [{"ge": th, "label": lab} for th, lab in LABEL_CUTS],
        "label_else": LABEL_ELSE,
        "max": 100,
    }
