"""loop.runner — 5 仮説 × walk-forward × 4 ゲート (SPEC_LOOP §3).

各仮説を 1 回だけ実行 (auto-tune 禁止). 結果と落ちた条件をハッシュチェーン
ログに記録. 個別株が混入したら ValueError.
"""

from __future__ import annotations

import datetime
import math
import statistics
from typing import Any, Callable, Dict, List, Optional, Sequence

from backtest import h1_robustness as gates
from backtest.walk_forward import WatchedBars

from . import holdout, log as loop_log, overfit, registry


SLIP_PCT_DEFAULT = 0.02
FEE_PCT_DEFAULT = 0.01


# ──────────────────────────────────────────────
# 単一仮説 × 単一シンボル trades 生成
# ──────────────────────────────────────────────
def _close_to_close_realized(bars: Sequence[dict], t: int, direction: str,
                              slip_pct: float, fee_pct: float) -> Optional[float]:
    """t → t+1 の close-to-close return に slip/fee を控除した % リターン."""
    if t + 1 >= len(bars):
        return None
    try:
        c_now = float(bars[t]["close"])
        c_next = float(bars[t + 1]["close"])
    except (TypeError, ValueError, KeyError):
        return None
    if c_now <= 0:
        return None
    raw = (c_next - c_now) / c_now * 100.0
    side = 1 if direction == "long" else -1
    gross = raw * side
    # slip/fee は片道 → 往復で 2 倍
    net = gross - 2.0 * (slip_pct + fee_pct)
    return net


def _run_one_predict(predict_fn: Callable, bars: Sequence[dict],
                     holdout_start: Optional[str] = None,
                     slip_pct: float = SLIP_PCT_DEFAULT,
                     fee_pct: float = FEE_PCT_DEFAULT,
                     symbol: str = "") -> List[Dict[str, Any]]:
    """1 シンボルに対し predict_fn を順に当て、close-to-close で trades を返す.

    bars は事前に holdout でフィルタ済の想定だが、安全のため再フィルタ.
    各 t で WatchedBars(bars[:t+1]) を predict_fn に渡し、 look-ahead をブロック.
    """
    filtered = holdout.filter_pre_holdout(bars, holdout_start)
    trades: List[Dict[str, Any]] = []
    for t in range(len(filtered) - 1):
        watched = WatchedBars(filtered, max_idx=t)
        pred = predict_fn(watched, t)
        if not pred:
            continue
        direction = pred.get("direction")
        if direction not in ("long", "short"):
            continue
        realized = _close_to_close_realized(filtered, t, direction,
                                              slip_pct, fee_pct)
        if realized is None:
            continue
        try:
            c_now = float(filtered[t]["close"])
            c_next = float(filtered[t + 1]["close"])
            label_value = (c_next - c_now) / c_now
        except (TypeError, ValueError, KeyError):
            label_value = 0.0
        trades.append({
            "ts": filtered[t + 1].get("ts"),       # 決済時刻
            "symbol": symbol,
            "direction": direction,
            "net_pct": round(realized, 6),
            "outcome01": 1 if realized > 0 else 0,
            "predicted_prob": float(pred.get("predicted_prob", 0.55)),
            # fade 用
            "label_value": float(label_value),
            "feature": +1.0 if direction == "long" else -1.0,
        })
    return trades


def run_one(hypothesis: Dict[str, Any],
            bars: Sequence[dict], *,
            symbol: str = "",
            holdout_start: Optional[str] = None,
            slip_pct: float = SLIP_PCT_DEFAULT,
            fee_pct: float = FEE_PCT_DEFAULT) -> List[Dict[str, Any]]:
    """1 仮説 × 1 シンボル → trades. 1 仮説 1 回のみ呼ばれる (test 担保)."""
    return _run_one_predict(hypothesis["predict"], bars,
                             holdout_start=holdout_start,
                             slip_pct=slip_pct, fee_pct=fee_pct,
                             symbol=symbol)


# ──────────────────────────────────────────────
# 4 ゲート評価
# ──────────────────────────────────────────────
def _evaluate_4_gates(trades: List[Dict[str, Any]],
                      bootstrap_runs: int) -> Dict[str, Any]:
    cost_table = gates.cost_sensitivity(trades, bootstrap_runs=bootstrap_runs)
    cost_v = gates.cost_verdict(cost_table)
    outlier_table = gates.outlier_sensitivity(trades, bootstrap_runs=bootstrap_runs)
    outlier_v = gates.outlier_verdict(outlier_table)
    sub_table = gates.subperiod_table(trades)
    sub_v = gates.subperiod_verdict(sub_table)
    fade_summary = gates.fade_summary(trades)
    fade_v = gates.fade_verdict(fade_summary)
    all_pass = all([cost_v.get("pass"), outlier_v.get("pass"),
                    sub_v.get("pass"), fade_v.get("pass")])
    return {
        "cost": {"table": cost_table, "verdict": cost_v},
        "outlier": {"table": outlier_table, "verdict": outlier_v},
        "subperiod": {"table": sub_table, "verdict": sub_v},
        "fade": {"summary": fade_summary, "verdict": fade_v},
        "passed_4_gates": bool(all_pass),
    }


# ──────────────────────────────────────────────
# ループ本体
# ──────────────────────────────────────────────
def run_loop(*, bars_by_symbol: Dict[str, Sequence[dict]],
             holdout_start: Optional[str] = None,
             slip_pct: float = SLIP_PCT_DEFAULT,
             fee_pct: float = FEE_PCT_DEFAULT,
             bootstrap_runs: int = 300,
             persist_log: bool = True) -> Dict[str, Any]:
    """5 仮説をユニバース横断で 1 回ずつ評価し、判定 + フロンティアを返す."""
    # 個別株検査 — ユニバース外をブロック
    for s in bars_by_symbol:
        if s not in registry.ALLOWED_SYMBOLS:
            raise ValueError(f"symbol {s!r} not in ALLOWED_SYMBOLS (indices/FX only)")
    holdout_cut = (holdout_start or holdout.HOLDOUT_START)[:10]

    trials: List[Dict[str, Any]] = []
    n_hypotheses = len(registry.REGISTRY)
    dsr_threshold = overfit.dsr_pass_threshold(n_hypotheses)
    pbo_needed = overfit.pbo_required(n_hypotheses)

    for h in registry.REGISTRY:
        all_trades: List[Dict[str, Any]] = []
        per_symbol_counts: Dict[str, int] = {}
        for sym, bars in bars_by_symbol.items():
            tr = run_one(h, bars, symbol=sym, holdout_start=holdout_cut,
                          slip_pct=slip_pct, fee_pct=fee_pct)
            per_symbol_counts[sym] = len(tr)
            all_trades.extend(tr)
        # 4 ゲート
        gates_res = _evaluate_4_gates(all_trades, bootstrap_runs=bootstrap_runs)
        # SR / DSR / PBO
        nets = [float(t["net_pct"]) for t in all_trades]
        sr = overfit.sharpe_annualized(nets, period=252)
        dsr = overfit.deflated_sharpe(sr, n_trials=n_hypotheses)
        pbo = overfit.pbo_split_sign_consistent(nets)
        # 最終 hypothesis 判定
        passed_4g = gates_res["passed_4_gates"]
        passed_dsr = (dsr is not None) and (dsr > dsr_threshold)
        passed_pbo = (not pbo_needed) or (pbo.get("consistent") is True)
        survives = bool(passed_4g and passed_dsr and passed_pbo)
        trial = {
            "name": h["name"],
            "params": dict(h.get("params") or {}),
            "rationale": h.get("rationale"),
            "n_trades": len(all_trades),
            "hit_rate": gates_res["fade"]["summary"].get("hit_rate"),  # fade は逆だが
            # hit_rate は元 trades 由来で再計算 (直値)
            "_per_symbol_counts": per_symbol_counts,
            "cost": gates_res["cost"],
            "outlier": gates_res["outlier"],
            "subperiod": gates_res["subperiod"],
            "fade": gates_res["fade"],
            "passed_4_gates": passed_4g,
            "sr_raw": sr,
            "dsr": dsr,
            "dsr_threshold": dsr_threshold,
            "pbo_sign_consistent": pbo.get("consistent"),
            "pbo_details": pbo,
            "verdict": (
                "survives" if survives
                else "fails (" + ",".join(
                    [k for k, v in (("4_gates", passed_4g),
                                      ("dsr", passed_dsr),
                                      ("pbo", passed_pbo)) if not v]) + ")"
            ),
            "_trades": all_trades,
        }
        # 仮説直値の hit_rate を上書き (gates.fade_summary は fade 側だった)
        if all_trades:
            wins = sum(1 for t in all_trades if t["outcome01"] == 1)
            trial["hit_rate"] = round(wins / len(all_trades), 6)
        else:
            trial["hit_rate"] = None
        trials.append(trial)

        # ハッシュチェーン記録 (詳細を圧縮)
        if persist_log:
            try:
                loop_log.append_trial({
                    "name": h["name"],
                    "params": dict(h.get("params") or {}),
                    "n_trades": len(all_trades),
                    "hit_rate": trial["hit_rate"],
                    "sr_raw": sr,
                    "dsr": dsr,
                    "passed_4_gates": passed_4g,
                    "pbo_sign_consistent": pbo.get("consistent"),
                    "verdict": trial["verdict"],
                    "cost_verdict_pass": gates_res["cost"]["verdict"].get("pass"),
                    "outlier_verdict_pass": gates_res["outlier"]["verdict"].get("pass"),
                    "subperiod_verdict_pass": gates_res["subperiod"]["verdict"].get("pass"),
                    "fade_verdict_pass": gates_res["fade"]["verdict"].get("pass"),
                    "fade_skew": gates_res["fade"]["summary"].get("skew"),
                    "fade_worst_day": gates_res["fade"]["summary"].get("worst_day_loss_pct"),
                })
            except Exception:
                pass

    # フロンティア (hit_rate, fade.skew 自身)
    frontier = []
    for tr in trials:
        frontier.append({
            "name": tr["name"],
            "hit_rate": tr["hit_rate"],
            "skew": tr["fade"]["summary"].get("skew"),
            "worst_day_loss_pct": tr["fade"]["summary"].get("worst_day_loss_pct"),
            "sr_raw": tr["sr_raw"],
            "dsr": tr["dsr"],
        })

    survivors = [tr["name"] for tr in trials if tr["verdict"] == "survives"]
    if survivors:
        verdict = f"transfer-candidate-survived: {','.join(survivors)} (要・一発ホールドアウト確認)"
    else:
        verdict = ("empty-set under current gate → 指数転用は防御止まり / "
                    "転用Completion-B")

    return {
        "ok": True,
        "as_of_utc": datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0).isoformat(),
        "holdout_start": holdout_cut,
        "n_hypotheses": n_hypotheses,
        "dsr_threshold": dsr_threshold,
        "pbo_required": pbo_needed,
        "universe_used": sorted(bars_by_symbol.keys()),
        "trials": trials,
        "frontier": frontier,
        "verdict": verdict,
        "note": "Phase 1.9.2 anti-overfit loop. Single-hypothesis raw predictive "
                "power tested. Each hypothesis runs ONCE with fixed params. "
                "Holdout (last 2y) physically blocked. Not investment advice. "
                "Phase 2 (learning) not implemented.",
    }
