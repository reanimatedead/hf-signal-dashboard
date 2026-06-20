"""survival.bankruptcy — Risk of Ruin (SPEC_SURVIVAL §2.5, §4).

% 空間で計算。残高は絶対額表示にしか影響しないため、ヒートマップは複数残高で
**同じ RoR を出す**。これは仕様 (人間に初期残高を聞かない設計)。
"""

from __future__ import annotations

import math
import random
from typing import List

from .risk_engine import HARD_CAPS, clamp_risk

DEFAULT_TRADES = 200
DEFAULT_RUNS = 500


def monte_carlo_ror(win_prob: float, win_loss_ratio: float, risk_pct: float,
                    trades: int = DEFAULT_TRADES, runs: int = DEFAULT_RUNS,
                    dd_stop_pct: float = 15.0) -> float:
    """順序依存の破産確率。balance が peak から dd_stop_pct 以上下がったら ruin.

    risk_pct は SPEC の HARD_CAPS で clamp される (天井超え提案は弾く)。
    """
    p = max(0.0, min(1.0, float(win_prob)))
    b = float(win_loss_ratio)
    r_pct = clamp_risk(risk_pct)
    if b <= 0 or r_pct <= 0 or trades <= 0 or runs <= 0:
        return 1.0 if (b <= 0 or r_pct <= 0) else 0.0
    r = r_pct / 100.0
    threshold = -abs(dd_stop_pct) / 100.0
    ruin_count = 0
    for _ in range(runs):
        balance = 1.0
        peak = 1.0
        ruined = False
        for _ in range(trades):
            if random.random() < p:
                balance *= (1.0 + r * b)
            else:
                balance *= (1.0 - r)
            if balance > peak:
                peak = balance
            dd = (balance - peak) / peak
            if dd <= threshold:
                ruined = True
                break
        if ruined:
            ruin_count += 1
    return ruin_count / runs


def kaufman_ror(win_prob: float, win_loss_ratio: float, risk_pct: float,
                target_units: int = 30) -> float:
    """Kaufman/Vince 閉形式の RoR. edge<=0 は 1.0。

    SPEC では参考値として併記。MC が主。target_units = 1 トレード単位での
    リスク量に対する破産までの距離 (DD 15% / risk 0.5% ≒ 30 単位 など)。
    """
    p = max(0.0, min(1.0, float(win_prob)))
    b = float(win_loss_ratio)
    r_pct = clamp_risk(risk_pct)
    if b <= 0 or r_pct <= 0:
        return 1.0
    q = 1.0 - p
    edge = p * b - q
    if edge <= 0:
        return 1.0
    # Vince 近似: RoR ≈ ((1 - edge/(b + 1)) / (1 + edge/(b + 1))) ** target_units
    a = edge / (b + 1.0)
    if a >= 1.0:
        return 0.0
    base = (1.0 - a) / (1.0 + a)
    return max(0.0, min(1.0, base ** target_units))


def heatmap(win_prob: float, win_loss_ratio: float,
            balances_pct_basis: List[int] = None,
            risk_options: List[float] = None,
            trades: int = DEFAULT_TRADES, runs: int = DEFAULT_RUNS,
            dd_stop_pct: float = 15.0) -> dict:
    """複数残高シナリオ × リスク水準で RoR を提示。

    balances は % 空間では RoR 値に影響しないため、絶対額表示の参考でしかない。
    risk_options は HARD_CAPS で clamp される。
    """
    balances = balances_pct_basis or [300, 400, 500]
    risks = risk_options or [0.1, 0.25, 0.5]
    grid = []
    for r in risks:
        rc = clamp_risk(r)
        ror_mc = monte_carlo_ror(win_prob, win_loss_ratio, rc, trades, runs, dd_stop_pct)
        ror_kf = kaufman_ror(win_prob, win_loss_ratio, rc)
        grid.append({
            "risk_pct": round(rc, 4),
            "ror_mc": round(ror_mc, 4),
            "ror_kaufman": round(ror_kf, 4),
        })
    return {
        "trades": trades, "runs": runs,
        "win_prob_used": round(win_prob, 4),
        "win_loss_ratio_used": round(win_loss_ratio, 4),
        "balances_pct_basis": balances,
        "risk_grid": grid,
        "dd_stop_pct": dd_stop_pct,
        "note": "% 空間で計算。残高違いは絶対額表示のみに影響。",
    }
