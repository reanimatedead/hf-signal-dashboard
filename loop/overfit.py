"""loop.overfit — Deflated Sharpe + PBO 簡略実装 (SPEC_LOOP §4)."""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Sequence


def expected_max_sr(n_trials: int) -> float:
    """N 個の N(0,1) Sharpe を引いたときの最大値の期待値の近似.

    sqrt(2 ln N) は標準正規最大値の漸近近似 (Bailey-Lopez de Prado 2014).
    """
    n = max(1, int(n_trials))
    if n == 1:
        return 0.0
    return math.sqrt(2.0 * math.log(n))


def sharpe_annualized(returns: Sequence[float], period: int = 252) -> Optional[float]:
    xs = [float(r) for r in (returns or [])
          if r is not None and math.isfinite(r)]
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    sd = var ** 0.5
    if sd <= 0:
        return None
    return m / sd * math.sqrt(period)


def deflated_sharpe(sr_raw: Optional[float], n_trials: int) -> Optional[float]:
    """DSR = SR_raw - expected_max_SR(N_trials). 簡略版."""
    if sr_raw is None:
        return None
    return round(sr_raw - expected_max_sr(n_trials), 6)


def pbo_split_sign_consistent(returns: Sequence[float]) -> Dict[str, Any]:
    """簡略 PBO: 時系列を半々分割し前後半の mean 符号が一致するか."""
    xs = [float(r) for r in (returns or [])
          if r is not None and math.isfinite(r)]
    n = len(xs)
    if n < 2:
        return {"consistent": None, "first_half_mean": None,
                "second_half_mean": None, "n": n}
    half = n // 2
    a = xs[:half]
    b = xs[half:]
    if not a or not b:
        return {"consistent": None, "first_half_mean": None,
                "second_half_mean": None, "n": n}
    ma = sum(a) / len(a)
    mb = sum(b) / len(b)
    same_sign = (ma > 0 and mb > 0) or (ma < 0 and mb < 0)
    return {"consistent": bool(same_sign),
            "first_half_mean": round(ma, 6),
            "second_half_mean": round(mb, 6),
            "n": n}


def dsr_pass_threshold(n_trials: int) -> float:
    """試行数で吊り上がる DSR 合格閾値 (SPEC §4.3)."""
    n = max(1, int(n_trials))
    if n <= 1:
        return 0.0
    if n <= 5:
        return 0.0
    return 0.5


def pbo_required(n_trials: int) -> bool:
    """N>=2 で PBO 符号一致を必須化."""
    return n_trials >= 2
