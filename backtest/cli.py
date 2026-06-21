"""backtest.cli — `python3 -m backtest.cli` で配線疎通 + 実レート walk-forward.

Usage:
    python3 -m backtest.cli --smoke
    python3 -m backtest.cli --source=local                          # 実レート全銘柄
    python3 -m backtest.cli --source=local --interval=1d \\
                            --mode=anchored --train-min=400 --test-window=80
    python3 -m backtest.cli --source=local --symbols=USDJPY=X,EURUSD=X

Phase 1.8: --source=local で data/local/history_*.jsonl (or duckdb) から
銘柄別 walk-forward を回し judge 分類 (edge / no-edge / inconclusive / insufficient).

★Phase 2 (学習) は実装しない. test_no_learning_code が backtest/+collector/ を
grep して禁止語混入を検知する.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import pathlib
import random
import sys
import uuid
from typing import Any, Dict, List, Optional

from . import local_loader, metrics, simulator, walk_forward as wf
from . import h1 as h1_mod   # Phase 1.9 — single-hypothesis evaluation

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLIC_RESULT_PATH = ROOT / "docs" / "data" / "backtest_summary_public.json"
LIVE_RESULT_DIR = ROOT / "data" / "local" / "backtest"
H1_PUBLIC_PATH = ROOT / "docs" / "data" / "h1_summary_public.json"
H1_RESULT_DIR = ROOT / "data" / "local" / "h1"


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


def _execute_signals(bars, split, pattern_table, slip_pct, fee_pct, size_pct,
                     backtest_root=False):
    """fold 内 OOS と IS の両方でシグナルを集めて trades にする.

    backtest_root=False で simulator の jsonl 出力を抑制 (live ランの inode 爆発回避)。
    smoke で詳細な per-trade ログを残したい時だけ既存挙動に戻せるよう引数化している.
    """
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
                                    size_pct=size_pct,
                                    backtest_root=backtest_root)
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
                                    size_pct=size_pct,
                                    backtest_root=backtest_root)
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


# ──────────────────────────────────────────────
# Phase 1.8 — judge 分類とライブ実行
# ──────────────────────────────────────────────
def _classify_judge(metric: Dict[str, Any]) -> Dict[str, Any]:
    """metric (= metrics.summarize の戻り) を judge 4 カテゴリに正規化."""
    n = int(metric.get("n") or 0)
    ci = metric.get("avg_net_pct_ci")
    if n < 30:
        return {"judge": "insufficient", "n": n, "ci": ci}
    if not isinstance(ci, (list, tuple)) or len(ci) != 2:
        return {"judge": "inconclusive", "n": n, "ci": ci}
    lo, hi = float(ci[0]), float(ci[1])
    if lo > 0:
        return {"judge": "edge", "n": n, "ci": [lo, hi]}
    if hi < 0:
        return {"judge": "no-edge", "n": n, "ci": [lo, hi]}
    return {"judge": "inconclusive", "n": n, "ci": [lo, hi]}


def _run_one_symbol(bars: List[Dict[str, Any]], *,
                    mode: str = "anchored",
                    train_min: int, test_window: int,
                    purge: int, embargo: int,
                    slip_pct: float, fee_pct: float,
                    size_pct: float,
                    bootstrap_runs: int = 500) -> Dict[str, Any]:
    """Run walk-forward + simulate + summarize. Returns metrics PLUS the trade tapes
    so the caller can reuse them for the overall summary (1-pass, not 2)."""
    pattern_table = {"low_vol|mid": {"take_profit_pct": 2.0, "stop_loss_pct": -1.5}}
    splits = wf.make_splits(n_bars=len(bars), mode=mode,
                            train_min=train_min, test_window=test_window,
                            purge=purge, embargo=embargo)
    is_trades: List[Dict[str, Any]] = []
    oos_trades: List[Dict[str, Any]] = []
    for sp in splits:
        ist, oost = _execute_signals(bars, sp, pattern_table,
                                     slip_pct=slip_pct, fee_pct=fee_pct,
                                     size_pct=size_pct)
        is_trades.extend(ist)
        oos_trades.extend(oost)
    pair = metrics.summarize_pair(is_trades, oos_trades,
                                  bootstrap_runs=bootstrap_runs, ci=0.95,
                                  n_min=30)
    classify = _classify_judge(pair["out_of_sample"])
    return {
        "folds": len(splits),
        "n_oos_trades": len(oos_trades),
        "n_is_trades": len(is_trades),
        "in_sample": pair["in_sample"],
        "out_of_sample": pair["out_of_sample"],
        "overfit_gap": pair["overfit_gap"],
        "judge": classify["judge"],
        "calibration": pair["out_of_sample"].get("calibration"),
        # trade テープを返す → run_local の overall 集計で再利用 (再ループ防止)
        "_is_trades": is_trades,
        "_oos_trades": oos_trades,
    }


def run_local(*, interval: str = "1d",
              symbols: Optional[List[str]] = None,
              mode: str = "anchored",
              train_min: int = 400,
              test_window: int = 80,
              purge: int = 5, embargo: int = 5,
              slip_pct: float = 0.02, fee_pct: float = 0.01,
              size_pct: float = 0.5,
              bootstrap_runs: int = 500,
              source: str = "auto") -> Dict[str, Any]:
    loaded = local_loader.load_all(interval=interval,
                                    min_bars=max(train_min + 2 * test_window + 20, 200),
                                    source=source)
    sym_filter = set(symbols) if symbols else None
    per_symbol: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []

    # All OOS trades concatenated for the overall summary.
    all_oos: List[Dict[str, Any]] = []
    all_is: List[Dict[str, Any]] = []

    for sym, info in sorted(loaded["symbols"].items()):
        if sym_filter and sym not in sym_filter:
            continue
        bars = info["bars"]
        res = _run_one_symbol(
            bars,
            mode=mode,
            train_min=train_min, test_window=test_window,
            purge=purge, embargo=embargo,
            slip_pct=slip_pct, fee_pct=fee_pct,
            size_pct=size_pct,
            bootstrap_runs=bootstrap_runs,
        )
        # 全体集計用に trade テープを引き継ぐ (再ループしない)
        all_is.extend(res.pop("_is_trades", []))
        all_oos.extend(res.pop("_oos_trades", []))
        per_symbol.append({
            "symbol": sym,
            "n_bars": info["n"],
            "first_ts": info["first_ts"],
            "last_ts": info["last_ts"],
            **res,
        })

    overall_pair = metrics.summarize_pair(all_is, all_oos,
                                           bootstrap_runs=bootstrap_runs, ci=0.95,
                                           n_min=30)
    overall_judge = _classify_judge(overall_pair["out_of_sample"])

    for sym, info in sorted(loaded["excluded"].items()):
        excluded.append({
            "symbol": sym, "n_bars": info["n"],
            "min_required": info["min_required"],
            "reason": info["reason"],
        })

    out = {
        "ok": True,
        "as_of_utc": datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0).isoformat(),
        "source_used": loaded["source_used"],
        "interval": interval,
        "fold_config": {"mode": mode, "train_min": train_min,
                        "test_window": test_window,
                        "purge": purge, "embargo": embargo},
        "exec_config": {"slip_pct": slip_pct, "fee_pct": fee_pct,
                        "size_pct": size_pct},
        "per_symbol": per_symbol,
        "excluded": excluded,
        "overall": {
            "n_symbols": len(per_symbol),
            "n_excluded": len(excluded),
            "n_oos_trades": len(all_oos),
            "n_is_trades": len(all_is),
            "in_sample": overall_pair["in_sample"],
            "out_of_sample": overall_pair["out_of_sample"],
            "overfit_gap": overall_pair["overfit_gap"],
            "judge": overall_judge["judge"],
            "calibration": overall_pair["out_of_sample"].get("calibration"),
        },
        "note": "想定精度のみ / This is the system's estimated accuracy, "
                "not real trading P&L. Macro environment visualization, "
                "not investment advice. Phase 2 (model training) is not implemented.",
    }

    # 詳細結果は data/local に保存 (リポ外)
    try:
        LIVE_RESULT_DIR.mkdir(parents=True, exist_ok=True)
        rid = uuid.uuid4().hex[:10]
        out_path = LIVE_RESULT_DIR / f"{out['as_of_utc'].replace(':','')}_{rid}_live.json"
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        out["persisted"] = str(out_path)
    except OSError:
        pass

    # 公開抜粋
    try:
        PUBLIC_RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        # 公開: per_symbol は要約のみ (calibration 含む)、trades 配列は外す
        per_sym_public = [
            {k: v for k, v in s.items() if k != "calibration"}
            for s in per_symbol
        ]
        public = {
            "as_of_utc": out["as_of_utc"],
            "mode": "live",
            "source_used": out["source_used"],
            "interval": interval,
            "fold_config": out["fold_config"],
            "exec_config": out["exec_config"],
            "per_symbol": per_sym_public,
            "excluded": excluded,
            "overall": out["overall"],
            "note": out["note"],
        }
        PUBLIC_RESULT_PATH.write_text(
            json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass

    return out


# ──────────────────────────────────────────────
# Phase 1.9 — H1 単一仮説 (US→日本オーバーナイト波及)
# ──────────────────────────────────────────────
def run_h1_local(*, jp_symbol: str = "^N225",
                 us_symbol: str = "^GSPC",
                 bootstrap_runs: int = 300,
                 n_min: int = 30,
                 source: str = "auto") -> Dict[str, Any]:
    loaded = local_loader.load_all(interval="1d", min_bars=200, source=source)
    if jp_symbol not in loaded["symbols"]:
        return {"ok": False, "error": f"jp_symbol {jp_symbol!r} not in store"}
    if us_symbol not in loaded["symbols"]:
        return {"ok": False, "error": f"us_symbol {us_symbol!r} not in store"}
    jp = loaded["symbols"][jp_symbol]["bars"]
    us = loaded["symbols"][us_symbol]["bars"]
    res = h1_mod.run_h1(jp_bars=jp, us_bars=us,
                        bootstrap_runs=bootstrap_runs, n_min=n_min,
                        jp_symbol=jp_symbol, us_symbol=us_symbol)
    res["source_used"] = loaded["source_used"]

    # 詳細結果は data/local/h1/ (リポ外)
    try:
        H1_RESULT_DIR.mkdir(parents=True, exist_ok=True)
        rid = uuid.uuid4().hex[:10]
        out_path = H1_RESULT_DIR / f"{res['as_of_utc'].replace(':','')}_{rid}.json"
        out_path.write_text(json.dumps(res, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        res["persisted"] = str(out_path)
    except OSError:
        pass

    # 公開抜粋: 詳細を含むが reproducible
    try:
        H1_PUBLIC_PATH.parent.mkdir(parents=True, exist_ok=True)
        H1_PUBLIC_PATH.write_text(json.dumps(res, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    except OSError:
        pass
    return res


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="backtest.cli",
                                description="Walk-forward backtest harness (smoke + real).")
    p.add_argument("--smoke", action="store_true", default=False,
                   help="run smoke wiring test with synthetic random walk")
    p.add_argument("--source", choices=("smoke", "local"), default=None,
                   help="data source: 'smoke' (random walk) or 'local' "
                        "(data/local/history_*.jsonl + duckdb)")
    p.add_argument("--interval", default="1d")
    p.add_argument("--symbols", default=None,
                   help="comma-separated symbol filter (default: all loaded)")
    p.add_argument("--mode", choices=("anchored", "rolling"), default="anchored")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--n-bars", type=int, default=600)
    p.add_argument("--train-min", type=int, default=200)
    p.add_argument("--test-window", type=int, default=60)
    p.add_argument("--purge", type=int, default=5)
    p.add_argument("--embargo", type=int, default=5)
    p.add_argument("--slip-pct", type=float, default=0.02)
    p.add_argument("--fee-pct", type=float, default=0.01)
    p.add_argument("--size-pct", type=float, default=0.5)
    p.add_argument("--bootstrap-runs", type=int, default=500)
    p.add_argument("--hypothesis", choices=("h1",), default=None,
                   help="Phase 1.9: 単一仮説評価. 'h1' のみ実装.")
    p.add_argument("--jp-symbol", default="^N225")
    p.add_argument("--us-symbol", default="^GSPC")
    p.add_argument("--n-min", type=int, default=30)
    ns = p.parse_args(argv)

    # ── Phase 1.9 hypothesis branch ──────────────────
    if ns.hypothesis == "h1":
        res = run_h1_local(jp_symbol=ns.jp_symbol, us_symbol=ns.us_symbol,
                            bootstrap_runs=ns.bootstrap_runs, n_min=ns.n_min,
                            source=(ns.source or "auto"))
        # 表示は要約のみ
        out = {
            "ok": res["ok"],
            "hypothesis": res.get("hypothesis"),
            "jp_symbol": res.get("jp_symbol"),
            "us_symbol": res.get("us_symbol"),
            "source_used": res.get("source_used"),
            "segments": [
                {"name": s["name"], "from": s["from"], "to": s["to"],
                 "n_jp_bars": s["n_jp_bars"], "n_with_feature": s["n_with_feature"],
                 "sanity": {k: {"r": v.get("pearson"), "t": v.get("t"),
                                  "n": v.get("n"), "pass": v.get("pass")}
                            for k, v in s["sanity"].items()},
                 "labels": {k: {"n": m.get("n"), "hit_rate": m.get("hit_rate"),
                                 "brier": m.get("brier"),
                                 "avg_net_pct_ci": m.get("avg_net_pct_ci"),
                                 "judge": m.get("judge")}
                             for k, m in s["labels"].items()}}
                for s in res.get("segments", [])
            ],
            "note": res.get("note"),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    # source 解決: --source 明示 > --smoke > 既定 (smoke).
    chosen = ns.source or ("smoke" if ns.smoke else "smoke")

    if chosen == "local":
        sym_filter = [s.strip() for s in ns.symbols.split(",")] if ns.symbols else None
        # local 既定: train_min=400, test_window=80 にしておく (CLI 既定上書き).
        train_min = ns.train_min if ns.train_min != 200 else 400
        test_window = ns.test_window if ns.test_window != 60 else 80
        res = run_local(interval=ns.interval, symbols=sym_filter,
                        mode=ns.mode,
                        train_min=train_min, test_window=test_window,
                        purge=ns.purge, embargo=ns.embargo,
                        slip_pct=ns.slip_pct, fee_pct=ns.fee_pct,
                        size_pct=ns.size_pct,
                        bootstrap_runs=ns.bootstrap_runs)
        # 表示は要約のみ
        ov = res["overall"]
        oos = ov["out_of_sample"]
        out = {
            "ok": res["ok"],
            "source_used": res["source_used"],
            "interval": res["interval"],
            "n_symbols": ov["n_symbols"],
            "n_excluded": ov["n_excluded"],
            "n_oos_trades": ov["n_oos_trades"],
            "n_is_trades": ov["n_is_trades"],
            "overall_judge": ov["judge"],
            "overall_oos_hit_rate": oos.get("hit_rate"),
            "overall_oos_brier": oos.get("brier"),
            "overall_oos_ev_ci": oos.get("avg_net_pct_ci"),
            "overfit_gap": ov["overfit_gap"],
            "per_symbol_summary": [
                {"symbol": s["symbol"], "n_bars": s["n_bars"],
                 "folds": s["folds"], "n_oos": s["n_oos_trades"],
                 "judge": s["judge"],
                 "oos_hit": s["out_of_sample"].get("hit_rate"),
                 "oos_brier": s["out_of_sample"].get("brier"),
                 "oos_ci": s["out_of_sample"].get("avg_net_pct_ci")}
                for s in res["per_symbol"]
            ],
            "excluded": res["excluded"],
            "note": res["note"],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    # smoke 既定
    res = run_smoke(seed=ns.seed, n_bars=ns.n_bars,
                    train_min=ns.train_min, test_window=ns.test_window,
                    purge=ns.purge, embargo=ns.embargo,
                    slip_pct=ns.slip_pct, fee_pct=ns.fee_pct,
                    size_pct=ns.size_pct)
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
