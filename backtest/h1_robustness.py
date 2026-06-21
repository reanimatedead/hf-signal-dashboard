"""backtest.h1_robustness — H1 open_to_close 頑健性分析 (Phase 1.9.1).

SPEC_H1_ROBUSTNESS.md と一対. 既存 Phase 1.9 の trades に対する 4 条件
((a) cost, (b) outlier, (c) subperiod, (d) fade skew) を判定し 2 値で最終結論を出す.

★新仮説 (H2-H10) や学習は一切実装しない. 既存 H1 trades の頑健性分析のみ.
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import metrics


COST_LEVELS_BPS = (5, 10, 20)


# ──────────────────────────────────────────────
# 共通ユーティリティ
# ──────────────────────────────────────────────
def _safe_mean(xs: Sequence[float]) -> Optional[float]:
    xs = [float(x) for x in xs if x is not None and math.isfinite(x)]
    return sum(xs) / len(xs) if xs else None


def _ci_bounds(values: Sequence[float], runs: int, ci: float = 0.95,
               seed: int = 0) -> Optional[List[float]]:
    n = len(values)
    if n == 0:
        return None
    rng = random.Random(seed)
    means: List[float] = []
    for _ in range(runs):
        s = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(s) / n)
    means.sort()
    lo_q = (1 - ci) / 2
    hi_q = 1 - lo_q
    lo = means[max(0, int(lo_q * runs) - 1)]
    hi = means[min(runs - 1, int(hi_q * runs))]
    return [round(lo, 6), round(hi, 6)]


# ──────────────────────────────────────────────
# Agent 1 — cost 控除
# ──────────────────────────────────────────────
def apply_cost(trades: Sequence[Dict[str, Any]], cost_pct: float
               ) -> List[Dict[str, Any]]:
    """trades の net_pct から往復コスト (%) を控除した新 list を返す.
    元の trade dict は変更しない (deep-copy も不要 — net_pct を上書き copy する)."""
    out: List[Dict[str, Any]] = []
    for t in trades:
        new_net = float(t.get("net_pct", 0.0)) - float(cost_pct)
        out.append({**t, "net_pct": round(new_net, 6),
                    "outcome01": 1 if new_net > 0 else 0})
    return out


def cost_sensitivity(trades: Sequence[Dict[str, Any]],
                     bootstrap_runs: int = 500) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for bps in COST_LEVELS_BPS:
        cost_pct = bps / 100.0       # 5 bps = 0.05%
        adj = apply_cost(trades, cost_pct=cost_pct)
        vals = [float(t["net_pct"]) for t in adj
                if t.get("net_pct") is not None and math.isfinite(t["net_pct"])]
        ci = _ci_bounds(vals, runs=bootstrap_runs)
        rows.append({
            "cost_bps": bps,
            "cost_pct": round(cost_pct, 6),
            "n": len(adj),
            "mean_net_pct": round(_safe_mean(vals) or 0.0, 6),
            "ev_ci": ci,
        })
    return rows


def cost_verdict(table: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    levels = []
    all_pass = True
    for row in table:
        ci = row.get("ev_ci")
        passes = bool(isinstance(ci, list) and len(ci) == 2 and ci[0] > 0)
        all_pass = all_pass and passes
        levels.append({"cost_bps": row["cost_bps"], "ev_ci": ci, "pass": passes})
    return {"pass": bool(all_pass), "levels": levels}


# ──────────────────────────────────────────────
# Agent 2 — 外れ値除外
# ──────────────────────────────────────────────
def drop_top_abs_pct(trades: Sequence[Dict[str, Any]], pct: float
                     ) -> List[Dict[str, Any]]:
    """|net_pct| 上位 pct% を除外. インデックスベースで除外する (同一参照の
    list でも安全).
    """
    if not trades or pct <= 0:
        return list(trades)
    n = len(trades)
    k = max(1, math.ceil(n * pct / 100.0))
    # (abs_net_pct, original_index) で降順ソート → 上位 k 個の index を除外
    indexed = [(abs(float(t.get("net_pct", 0.0))), i) for i, t in enumerate(trades)]
    indexed.sort(reverse=True)
    drop_indices = {idx for _, idx in indexed[:k]}
    return [t for i, t in enumerate(trades) if i not in drop_indices]


def outlier_sensitivity(trades: Sequence[Dict[str, Any]],
                        bootstrap_runs: int = 500) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for pct in (1.0, 5.0):
        pruned = drop_top_abs_pct(trades, pct=pct)
        vals = [float(t["net_pct"]) for t in pruned
                if t.get("net_pct") is not None and math.isfinite(t["net_pct"])]
        ci = _ci_bounds(vals, runs=bootstrap_runs)
        rows.append({
            "pct_excluded": pct,
            "n_kept": len(pruned),
            "mean_net_pct": round(_safe_mean(vals) or 0.0, 6),
            "ev_ci": ci,
        })
    return rows


def outlier_verdict(table: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    all_pass = True
    rows = []
    for row in table:
        ci = row.get("ev_ci")
        passes = bool(isinstance(ci, list) and len(ci) == 2 and ci[0] > 0)
        all_pass = all_pass and passes
        rows.append({"pct_excluded": row["pct_excluded"],
                      "ev_ci": ci, "pass": passes})
    return {"pass": bool(all_pass), "rows": rows}


# ──────────────────────────────────────────────
# Agent 3 — サブ期間
# ──────────────────────────────────────────────
def split_by_year(trades: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for t in trades:
        ts = str(t.get("ts") or "")
        if len(ts) < 4:
            continue
        year = ts[:4]
        out.setdefault(year, []).append(t)
    return out


def subperiod_table(trades: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_year = split_by_year(trades)
    rows: List[Dict[str, Any]] = []
    for year in sorted(by_year.keys()):
        ts_list = by_year[year]
        vals = [float(t.get("net_pct", 0.0)) for t in ts_list
                if t.get("net_pct") is not None and math.isfinite(t["net_pct"])]
        rows.append({
            "year": year,
            "n": len(vals),
            "mean_net_pct": round(_safe_mean(vals) or 0.0, 6),
            "sum_net_pct": round(sum(vals), 6),
        })
    return rows


def subperiod_verdict(table: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not table:
        return {"pass": False, "reason": "no_subperiods"}
    total = sum(abs(r["sum_net_pct"]) for r in table)
    if total <= 0:
        return {"pass": False, "reason": "zero_total"}
    # 単一期間集中チェック
    biggest = max(table, key=lambda r: abs(r["sum_net_pct"]))
    share = abs(biggest["sum_net_pct"]) / total
    if share > 0.50:
        return {"pass": False,
                "reason": f"single year {biggest['year']} dominates ({share:.0%})",
                "table": list(table)}
    # 負期間チェック
    neg = [r for r in table if r["mean_net_pct"] < 0]
    if neg:
        return {"pass": False,
                "reason": f"negative year(s): {[r['year'] for r in neg]}",
                "table": list(table)}
    return {"pass": True, "reason": None, "table": list(table)}


# ──────────────────────────────────────────────
# Agent 4 — fade + skew/maxDD/worst-day
# ──────────────────────────────────────────────
def build_fade_trades(raw_label_feature: Sequence[Dict[str, Any]]
                       ) -> List[Dict[str, Any]]:
    """raw = [{ts, label_value, feature}, ...] → fade 戦略 trades."""
    out: List[Dict[str, Any]] = []
    for r in raw_label_feature:
        lv = r.get("label_value")
        fv = r.get("feature")
        if lv is None or fv is None:
            continue
        try:
            lv_f = float(lv); fv_f = float(fv)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(lv_f) and math.isfinite(fv_f)):
            continue
        # fade: 元 direction = sign(feature), fade = -sign(feature)
        d = -1 if fv_f > 0 else 1
        realized = lv_f * d * 100.0
        out.append({"ts": r.get("ts"),
                     "net_pct": round(realized, 6),
                     "outcome01": 1 if realized > 0 else 0})
    return out


def compute_skew(values: Sequence[float]) -> Optional[float]:
    xs = [float(x) for x in values if x is not None and math.isfinite(x)]
    n = len(xs)
    if n < 3:
        return None
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / n
    s = v ** 0.5
    if s <= 0:
        return None
    return round(sum(((x - m) / s) ** 3 for x in xs) / n, 6)


def max_dd_from_pct(realized_pct: Sequence[float]) -> Optional[float]:
    if not realized_pct:
        return None
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    for v in realized_pct:
        try:
            eq *= 1.0 + float(v) / 100.0
        except (TypeError, ValueError):
            continue
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (eq - peak) / peak * 100.0
            if dd < mdd:
                mdd = dd
    return round(mdd, 6)


def worst_day_loss(realized_pct: Sequence[float]) -> Optional[float]:
    vals = [float(v) for v in realized_pct
             if v is not None and math.isfinite(v)]
    if not vals:
        return None
    return round(min(vals), 6)


def fade_summary(raw_label_feature: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    fade = build_fade_trades(raw_label_feature)
    realized = [float(t["net_pct"]) for t in fade]
    hits = [int(t["outcome01"]) for t in fade]
    return {
        "n": len(fade),
        "hit_rate": round(sum(hits) / len(hits), 6) if hits else None,
        "mean_net_pct": round(_safe_mean(realized) or 0.0, 6),
        "skew": compute_skew(realized),
        "max_dd_pct": max_dd_from_pct(realized),
        "worst_day_loss_pct": worst_day_loss(realized),
    }


def fade_verdict(summary: Dict[str, Any]) -> Dict[str, Any]:
    skew = summary.get("skew")
    worst = summary.get("worst_day_loss_pct")
    if skew is None or worst is None:
        return {"pass": False, "reason": "insufficient_data",
                "summary": summary}
    ok_skew = skew >= -0.5
    ok_worst = worst >= -5.0
    passed = bool(ok_skew and ok_worst)
    reason = None
    if not passed:
        if not ok_skew and not ok_worst:
            reason = f"neg-skew {skew:.2f} AND worst-day {worst:.2f}%"
        elif not ok_skew:
            reason = f"neg-skew {skew:.2f} (< -0.5)"
        else:
            reason = f"worst-day {worst:.2f}% < -5%"
    return {"pass": passed, "reason": reason, "summary": summary,
            "ok_skew": ok_skew, "ok_worst": ok_worst}


# ──────────────────────────────────────────────
# Agent 5 — 統合判定
# ──────────────────────────────────────────────
def combine_verdict(flags: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    crit = {k: bool((flags.get(k) or {}).get("pass")) for k in
             ("cost", "outlier", "subperiod", "fade")}
    all_pass = all(crit.values())
    overall = ("Stage2-conditioners-justified" if all_pass
               else "raw-cross-asset-not-tradeable → Completion-B候補")
    return {"overall": overall, "criteria": crit}


def run_robustness(trades_with_raw: Sequence[Dict[str, Any]],
                   bootstrap_runs: int = 500,
                   label: str = "open_to_close",
                   segment: str = "since_2023") -> Dict[str, Any]:
    """Phase 1.9.1 の 4 条件を 1 まとめにする entry point.

    `trades_with_raw` は各 trade に net_pct / outcome01 / predicted_prob /
    ts / label_value / feature を含むことを期待 (Agent 4 の fade に label/feature
    が必要なため). Phase 1.9 の trades は label_value/feature を持たないので、
    backtest.cli.run_h1_robustness で h1.build_features / compute_labels と
    結線してから渡す.
    """
    trades = list(trades_with_raw)
    # baseline EV
    raw_vals = [float(t["net_pct"]) for t in trades
                if t.get("net_pct") is not None and math.isfinite(t["net_pct"])]
    baseline = {
        "n": len(trades),
        "mean_net_pct": round(_safe_mean(raw_vals) or 0.0, 6),
        "ev_ci": _ci_bounds(raw_vals, runs=bootstrap_runs),
    }

    cost_table = cost_sensitivity(trades, bootstrap_runs=bootstrap_runs)
    cost_v = cost_verdict(cost_table)

    outlier_table = outlier_sensitivity(trades, bootstrap_runs=bootstrap_runs)
    outlier_v = outlier_verdict(outlier_table)

    sub_table = subperiod_table(trades)
    sub_v = subperiod_verdict(sub_table)

    fade_s = fade_summary(trades)
    fade_v = fade_verdict(fade_s)

    verdict = combine_verdict({"cost": cost_v, "outlier": outlier_v,
                                "subperiod": sub_v, "fade": fade_v})

    return {
        "label": label, "segment": segment,
        "n_trades": len(trades),
        "ev_baseline": baseline,
        "cost": {"table": cost_table, "verdict": cost_v},
        "outlier": {"table": outlier_table, "verdict": outlier_v},
        "subperiod": {"table": sub_table, "verdict": sub_v},
        "fade": {"summary": fade_s, "verdict": fade_v},
        "verdict": verdict,
        "note": "頑健性検証. 想定 + 取引可能性検証 / not investment advice. "
                "Phase 2 (学習) 未実装.",
    }
