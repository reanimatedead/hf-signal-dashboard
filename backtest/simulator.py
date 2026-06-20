"""backtest.simulator — 1 fold の仮想取引 (SPEC_BACKTEST §3).

ルール:
  * entry/exit に slip_pct を**価格に上乗せ**し、fee_pct を realized から控除.
  * size_pct は HARD_CAPS["PER_TRADE_PCT_MAX"]=0.5% に強制.
  * 同時保有は HARD_CAPS["MAX_CONCURRENT"]=3 で打ち切り.
  * MAX_HOLD_BARS=40 で EXIT_TIMEOUT.
  * 結果行は data/local/backtest/<run_id>.jsonl に追記 (引数で root 指定可).
"""

from __future__ import annotations

import json
import math
import os
import pathlib
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence

from survival import risk_engine as _re

MAX_HOLD_BARS = 40
DEFAULT_BACKTEST_DIR = pathlib.Path(__file__).resolve().parents[1] / "data" / "local" / "backtest"


def _pattern_key(pat: Dict[str, Any]) -> str:
    return f"{(pat or {}).get('regime','low_vol')}|{(pat or {}).get('distortion','mid')}"


def _lookup(table: Dict[str, Dict[str, float]], pat: Dict[str, Any]) -> Dict[str, float]:
    key = _pattern_key(pat)
    return dict(table.get(key) or table.get("low_vol|mid")
                or {"take_profit_pct": 1.5, "stop_loss_pct": -1.0})


def _bar_close(b: Dict[str, Any]) -> float:
    return float(b.get("close") or b.get("price") or 0.0)


def _bar_high(b: Dict[str, Any]) -> float:
    v = b.get("high")
    return float(v) if v is not None else _bar_close(b)


def _bar_low(b: Dict[str, Any]) -> float:
    v = b.get("low")
    return float(v) if v is not None else _bar_close(b)


def simulate_fold(test_bars: Sequence[Dict[str, Any]],
                  signals: Sequence[Dict[str, Any]],
                  pattern_table: Dict[str, Dict[str, float]],
                  slip_pct: float = 0.05,
                  fee_pct: float = 0.02,
                  size_pct: float = 0.5,
                  max_hold_bars: int = MAX_HOLD_BARS,
                  backtest_root: Optional[pathlib.Path] = None,
                  run_id: Optional[str] = None,
                  ) -> Dict[str, Any]:
    """Execute virtual trades, returning a result dict (also persisted to jsonl)."""
    size_pct = _re.clamp_risk(size_pct)            # HARD_CAPS 強制
    max_concurrent = _re.HARD_CAPS["MAX_CONCURRENT"]
    n = len(test_bars)

    # Sort signals deterministically by bar_index, then preserve order.
    sigs = sorted(list(signals), key=lambda s: (int(s.get("bar_index", 0)), 0))

    trades: List[Dict[str, Any]] = []
    open_positions: List[Dict[str, Any]] = []
    # equity curve indexed by bar (long-term cumulative pct).
    cum_pct = 0.0
    equity_curve: List[float] = [1.0]
    peak_eq = 1.0
    max_dd_pct = 0.0

    def open_position(sig: Dict[str, Any], bar_i: int) -> None:
        if len(open_positions) >= max_concurrent:
            return
        pat = sig.get("pattern") or {}
        tgt = _lookup(pattern_table, pat)
        side = sig.get("direction", "long")
        raw_close = _bar_close(test_bars[bar_i])
        slip = slip_pct / 100.0
        if side == "long":
            entry = raw_close * (1.0 + slip)
        else:
            entry = raw_close * (1.0 - slip)
        open_positions.append({
            "entry_bar": bar_i,
            "entry_price": entry,
            "side": side,
            "predicted_prob": float(sig.get("predicted_prob", 0.5)),
            "pattern": pat,
            "take_profit_pct": float(tgt["take_profit_pct"]),
            "stop_loss_pct": float(tgt["stop_loss_pct"]),
            "symbol": sig.get("symbol"),
        })

    def close_position(pos: Dict[str, Any], exit_bar: int, kind: str) -> Dict[str, Any]:
        raw_close = _bar_close(test_bars[exit_bar])
        slip = slip_pct / 100.0
        if pos["side"] == "long":
            exit_price = raw_close * (1.0 - slip)
            gross = (exit_price - pos["entry_price"]) / pos["entry_price"] * 100.0
        else:
            exit_price = raw_close * (1.0 + slip)
            gross = (pos["entry_price"] - exit_price) / pos["entry_price"] * 100.0
        net = gross - 2.0 * fee_pct
        outcome01 = 1 if net > 0 else 0
        return {
            "entry_bar": pos["entry_bar"],
            "exit_bar": exit_bar,
            "side": pos["side"],
            "entry_price": round(pos["entry_price"], 6),
            "exit_price": round(exit_price, 6),
            "gross_pct": round(gross, 6),
            "net_pct": round(net, 6),
            "predicted_prob": pos["predicted_prob"],
            "outcome01": outcome01,
            "kind": kind,
            "symbol": pos.get("symbol"),
        }

    sig_iter = iter(sigs)
    next_sig = next(sig_iter, None)

    for i in range(n):
        # 1. open new positions at this bar
        while next_sig is not None and int(next_sig.get("bar_index", 0)) <= i:
            open_position(next_sig, i)
            next_sig = next(sig_iter, None)

        # 2. check exits for open positions
        still_open: List[Dict[str, Any]] = []
        for pos in open_positions:
            tp = pos["take_profit_pct"]
            sl = pos["stop_loss_pct"]
            held = i - pos["entry_bar"]
            # use high/low to check intrabar reach, then close to settle.
            if pos["side"] == "long":
                hi_pct = (_bar_high(test_bars[i]) - pos["entry_price"]) / pos["entry_price"] * 100.0
                lo_pct = (_bar_low(test_bars[i]) - pos["entry_price"]) / pos["entry_price"] * 100.0
            else:
                hi_pct = (pos["entry_price"] - _bar_low(test_bars[i])) / pos["entry_price"] * 100.0
                lo_pct = (pos["entry_price"] - _bar_high(test_bars[i])) / pos["entry_price"] * 100.0
            kind: Optional[str] = None
            if hi_pct >= tp:
                kind = "EXIT_TP"
            elif lo_pct <= sl:
                kind = "EXIT_SL"
            elif held >= max_hold_bars:
                kind = "EXIT_TIMEOUT"
            if kind:
                tr = close_position(pos, i, kind)
                trades.append(tr)
                cum_pct += tr["net_pct"] * (size_pct / 100.0)
                eq = 1.0 + cum_pct / 100.0
                equity_curve.append(eq)
                peak_eq = max(peak_eq, eq)
                if peak_eq > 0:
                    dd = (eq - peak_eq) / peak_eq * 100.0
                    if dd < max_dd_pct:
                        max_dd_pct = dd
            else:
                still_open.append(pos)
        open_positions = still_open

    # close all still-open positions at the last bar (forced TIMEOUT).
    for pos in open_positions:
        tr = close_position(pos, n - 1, "EXIT_TIMEOUT")
        trades.append(tr)

    result = {
        "trades": trades,
        "n_trades": len(trades),
        "effective_size_pct": size_pct,
        "slip_pct": slip_pct,
        "fee_pct": fee_pct,
        "equity_curve": equity_curve,
        "max_dd_pct": round(max_dd_pct, 6),
    }

    # Persist (data/local/ — NOT committed).
    # backtest_root=False に明示すると一切書かない (live ラン時の inode 爆発を回避).
    if backtest_root is not False:
        root = pathlib.Path(backtest_root or DEFAULT_BACKTEST_DIR)
        try:
            root.mkdir(parents=True, exist_ok=True)
            rid = run_id or uuid.uuid4().hex
            out_path = root / f"{rid}.jsonl"
            with out_path.open("a", encoding="utf-8") as f:
                for tr in trades:
                    f.write(json.dumps(tr, ensure_ascii=False) + "\n")
            result["persisted"] = str(out_path)
        except OSError:
            pass

    return result
