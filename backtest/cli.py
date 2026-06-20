"""backtest.cli — `python3 -m backtest.cli` で配線疎通スモーク or 実履歴ラン.

Usage:
    python3 -m backtest.cli --smoke                       # 仮装データで e2e 緑確認
    python3 -m backtest.cli --source=duckdb --symbol=^N225 --mode=anchored \\
                            --train-min=400 --test-window=60 --purge=5 --embargo=5

SPEC_BACKTEST §8 の明日の手順から呼び出される入口.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import random
import sys
from typing import Any, Dict, List, Optional

from . import metrics, simulator, walk_forward as wf

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLIC_RESULT_PATH = ROOT / "docs" / "data" / "backtest_summary_public.json"


# ── 仮装データ (random walk) ─────────────────────────
def _smoke_bars(n: int = 600, seed: int = 42, mu: float = 0.0, sigma: float = 0.01,
                start: float = 100.0) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    px = [start]
    for _ in range(n - 1):
        r = mu + sigma * rng.gauss(0, 1)
        px.append(max(1.0, px[-1] * math.exp(r)))
    return [{"ts": f"t{i}", "open": p, "high": p * 1.005,
             "low": p * 0.995, "close": p} for i, p in enumerate(px)]


# ── 単純な過去 10 本リターン → 方向予測 ────────────
def _predict(watched, t_index):
    if t_index < 10:
        return None
    past = [watched[t_index - k]["close"] for k in range(10, 0, -1)]
    chg = (past[-1] - past[0]) / past[0]
    direction = "long" if chg > 0 else "short"
    return {"direction": direction, "predicted_prob": 0.55,
            "pattern": {"regime": "low_vol", "distortion": "mid"}}


def _execute_signals(bars, split, pattern_table, slip_pct, fee_pct, size_pct):
    """fold 内 OOS と IS の両方でシグナルを集めて trades にする."""
    # OOS
    oos_eval = wf.run_fold(bars, split, _predict,
                           evaluator=lambda preds, sp, all_bars: {"preds": preds})
    test_bars = bars[split.test_start: split.test_end + 1]
    oos_signals = []
    for p in oos_eval["preds"]:
        off = p["t_index"] - split.test_start
        if 0 <= off < len(test_bars):
            oos_signals.append({"bar_index": off, "direction": p["direction"],
                                 "predicted_prob": p["predicted_prob"],
                                 "pattern": p["pattern"]})
    oos_trades = []
    if oos_signals:
        r = simulator.simulate_fold(test_bars, oos_signals, pattern_table,
                                    slip_pct=slip_pct, fee_pct=fee_pct,
                                    size_pct=size_pct)
        oos_trades = r["trades"]

    # IS (train 区間内で予測 → 仮想実行)
    is_signals = []
    train_bars = bars[split.train_start: split.train_end + 1]
    for ti in range(10, len(train_bars)):
        pred = _predict(bars, split.train_start + ti)
        if pred:
            is_signals.append({"bar_index": ti, "direction": pred["direction"],
                                "predicted_prob": pred["predicted_prob"],
                                "pattern": pred["pattern"]})
    is_trades = []
    if is_signals:
        r = simulator.simulate_fold(train_bars, is_signals, pattern_table,
                                    slip_pct=slip_pct, fee_pct=fee_pct,
                                    size_pct=size_pct)
        is_trades = r["trades"]
    return is_trades, oos_trades


def run_smoke(seed: int = 42, n_bars: int = 600,
              train_min: int = 200, test_window: int = 60,
              purge: int = 5, embargo: int = 5,
              slip_pct: float = 0.02, fee_pct: float = 0.01,
              size_pct: float = 0.5) -> Dict[str, Any]:
    bars = _smoke_bars(n=n_bars, seed=seed)
    splits = wf.make_splits(n_bars=len(bars), mode="anchored",
                            train_min=train_min, test_window=test_window,
                            purge=purge, embargo=embargo)
    pattern_table = {"low_vol|mid": {"take_profit_pct": 2.0, "stop_loss_pct": -1.5}}
    is_trades: List[Dict[str, Any]] = []
    oos_trades: List[Dict[str, Any]] = []
    for sp in splits:
        ist, oost = _execute_signals(bars, sp, pattern_table,
                                     slip_pct=slip_pct, fee_pct=fee_pct,
                                     size_pct=size_pct)
        is_trades.extend(ist)
        oos_trades.extend(oost)
    pair = metrics.summarize_pair(is_trades, oos_trades,
                                  bootstrap_runs=300, ci=0.95, n_min=30)
    out = {
        "ok": True,
        "mode": "smoke",
        "splits": len(splits),
        "n_oos_trades": len(oos_trades),
        "n_is_trades": len(is_trades),
        "summary": pair,
        "note": "Macro environment visualization / not investment advice. Phase 1.7 smoke.",
    }
    try:
        PUBLIC_RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        # 公開抜粋: trades 配列は出さない (件数だけ)。
        public = {
            "as_of_utc": None,
            "mode": "smoke",
            "n_oos_trades": out["n_oos_trades"],
            "n_is_trades": out["n_is_trades"],
            "summary": pair,
            "note": out["note"],
        }
        PUBLIC_RESULT_PATH.write_text(
            json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="backtest.cli",
                                description="Walk-forward backtest harness (smoke + real).")
    p.add_argument("--smoke", action="store_true", default=False,
                   help="run smoke wiring test with synthetic random walk")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--n-bars", type=int, default=600)
    p.add_argument("--train-min", type=int, default=200)
    p.add_argument("--test-window", type=int, default=60)
    p.add_argument("--purge", type=int, default=5)
    p.add_argument("--embargo", type=int, default=5)
    p.add_argument("--slip-pct", type=float, default=0.02)
    p.add_argument("--fee-pct", type=float, default=0.01)
    p.add_argument("--size-pct", type=float, default=0.5)
    ns = p.parse_args(argv)
    if ns.smoke or True:
        # Phase 1.7 では実データソース連携はまだ枠だけ。--smoke 既定で OK。
        res = run_smoke(seed=ns.seed, n_bars=ns.n_bars,
                        train_min=ns.train_min, test_window=ns.test_window,
                        purge=ns.purge, embargo=ns.embargo,
                        slip_pct=ns.slip_pct, fee_pct=ns.fee_pct,
                        size_pct=ns.size_pct)
        # 表示は要約のみ
        out = {
            "ok": res["ok"],
            "splits": res["splits"],
            "n_oos_trades": res["n_oos_trades"],
            "n_is_trades": res["n_is_trades"],
            "oos_judge": res["summary"]["out_of_sample"].get("judge"),
            "oos_hit_rate": res["summary"]["out_of_sample"].get("hit_rate"),
            "oos_brier": res["summary"]["out_of_sample"].get("brier"),
            "oos_ev_ci": res["summary"]["out_of_sample"].get("avg_net_pct_ci"),
            "overfit_gap": res["summary"]["overfit_gap"],
            "note": res["note"],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
