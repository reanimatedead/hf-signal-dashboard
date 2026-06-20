"""backtest.metrics — hit_rate / Brier 分解 / 較正 / bootstrap CI / IS-OOS 並列.

SPEC_BACKTEST §4. 過学習を構造で炙る:
  * N<n_min は judge="undetermined"
  * bootstrap CI が 0 を跨ぐ → ev_ambiguous + judge="undetermined"
  * IS と OOS を summarize_pair で並列表示し overfit_gap を返す
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Sequence


N_BINS = 10


def _safe_mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def _bin_for(p: float) -> int:
    if p <= 0.0:
        return 0
    if p >= 1.0:
        return N_BINS - 1
    return min(N_BINS - 1, int(p * N_BINS))


def brier_decomposition(predicted_probs: Sequence[float],
                        outcomes01: Sequence[int]) -> Dict[str, float]:
    """Murphy decomposition: Brier = Reliability - Resolution + Uncertainty."""
    n = len(predicted_probs)
    if n == 0:
        return {"reliability": 0.0, "resolution": 0.0, "uncertainty": 0.0}
    base = _safe_mean(outcomes01)
    uncertainty = base * (1 - base)
    # Bin by predicted probability.
    bins: Dict[int, Dict[str, float]] = {}
    for p, o in zip(predicted_probs, outcomes01):
        b = _bin_for(float(p))
        d = bins.setdefault(b, {"sum_p": 0.0, "sum_o": 0.0, "n": 0})
        d["sum_p"] += float(p)
        d["sum_o"] += int(o)
        d["n"] += 1
    rel = 0.0
    res = 0.0
    for d in bins.values():
        nk = d["n"]
        pk = d["sum_p"] / nk
        ok = d["sum_o"] / nk
        rel += nk * (pk - ok) ** 2
        res += nk * (ok - base) ** 2
    rel /= n
    res /= n
    return {"reliability": rel, "resolution": res, "uncertainty": uncertainty}


def calibration_table(predicted_probs: Sequence[float],
                      outcomes01: Sequence[int]) -> List[Dict[str, Any]]:
    bins: Dict[int, Dict[str, float]] = {}
    for p, o in zip(predicted_probs, outcomes01):
        b = _bin_for(float(p))
        d = bins.setdefault(b, {"sum_p": 0.0, "sum_o": 0.0, "n": 0})
        d["sum_p"] += float(p)
        d["sum_o"] += int(o)
        d["n"] += 1
    out = []
    for b in range(N_BINS):
        lo = b / N_BINS
        hi = (b + 1) / N_BINS
        d = bins.get(b)
        if not d:
            out.append({"bin": [round(lo, 3), round(hi, 3)],
                         "n": 0, "pred_mean": None, "obs_rate": None})
            continue
        out.append({"bin": [round(lo, 3), round(hi, 3)],
                     "n": d["n"],
                     "pred_mean": round(d["sum_p"] / d["n"], 4),
                     "obs_rate": round(d["sum_o"] / d["n"], 4)})
    return out


def _max_dd_from_equity(eq: Sequence[float]) -> float:
    if not eq:
        return 0.0
    peak = eq[0]
    mdd = 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            dd = (v - peak) / peak * 100.0
            if dd < mdd:
                mdd = dd
    return round(mdd, 6)


def _bootstrap_mean_ci(values: Sequence[float], runs: int, ci: float,
                       seed: int = 0) -> Optional[List[float]]:
    n = len(values)
    if n == 0:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(runs):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo_q = (1 - ci) / 2
    hi_q = 1 - lo_q
    lo = means[max(0, int(lo_q * runs) - 1)]
    hi = means[min(runs - 1, int(hi_q * runs))]
    return [round(lo, 6), round(hi, 6)]


def summarize(trades: Sequence[Dict[str, Any]],
              bootstrap_runs: int = 1000,
              ci: float = 0.95,
              n_min: int = 30,
              seed: int = 0,
              equity_curve: Optional[Sequence[float]] = None,
              ) -> Dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"n": 0, "judge": "undetermined", "hit_rate": None, "brier": None,
                "brier_decomposition": {"reliability": 0, "resolution": 0, "uncertainty": 0},
                "calibration": [], "avg_net_pct": None,
                "avg_net_pct_ci": None, "ev_ambiguous": True,
                "max_dd_pct": 0.0, "reason": "no_trades"}
    preds = [float(t.get("predicted_prob", 0.5)) for t in trades]
    outs = [int(t.get("outcome01", 0)) for t in trades]
    nets = [float(t.get("net_pct", 0.0)) for t in trades]

    hit_rate = _safe_mean(outs)
    brier = _safe_mean([(p - o) ** 2 for p, o in zip(preds, outs)])
    decomp = brier_decomposition(preds, outs)
    calib = calibration_table(preds, outs)
    ci_bounds = _bootstrap_mean_ci(nets, runs=bootstrap_runs, ci=ci, seed=seed)
    ev_ambiguous = ci_bounds is None or (ci_bounds[0] <= 0 <= ci_bounds[1])
    judge = "ok"
    if n < n_min:
        judge = "undetermined"
    elif ev_ambiguous:
        judge = "undetermined"

    # equity curve fallback: cumulative product from net_pct
    if equity_curve is None:
        eq = [1.0]
        for v in nets:
            eq.append(eq[-1] * (1 + v / 100))
        equity_curve = eq
    max_dd = _max_dd_from_equity(equity_curve)

    return {
        "n": n,
        "judge": judge,
        "hit_rate": round(hit_rate, 6),
        "brier": round(brier, 6),
        "brier_decomposition": {k: round(v, 6) for k, v in decomp.items()},
        "calibration": calib,
        "avg_net_pct": round(_safe_mean(nets), 6),
        "avg_net_pct_ci": ci_bounds,
        "ev_ambiguous": bool(ev_ambiguous),
        "max_dd_pct": max_dd,
    }


def summarize_pair(is_trades: Sequence[Dict[str, Any]],
                   oos_trades: Sequence[Dict[str, Any]],
                   bootstrap_runs: int = 500,
                   ci: float = 0.95,
                   n_min: int = 30,
                   seed: int = 0) -> Dict[str, Any]:
    is_m = summarize(is_trades, bootstrap_runs=bootstrap_runs, ci=ci, n_min=n_min, seed=seed)
    oos_m = summarize(oos_trades, bootstrap_runs=bootstrap_runs, ci=ci, n_min=n_min, seed=seed + 1)

    def _diff(a, b):
        if a is None or b is None:
            return None
        return round(a - b, 6)

    gap = {
        "hit_rate": _diff(is_m["hit_rate"], oos_m["hit_rate"]),
        "brier": _diff(oos_m["brier"], is_m["brier"]),   # OOS が悪化する向きを + で表現
        "avg_net": _diff(is_m["avg_net_pct"], oos_m["avg_net_pct"]),
    }
    return {"in_sample": is_m, "out_of_sample": oos_m, "overfit_gap": gap}
