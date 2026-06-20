"""notify.triggers — look-ahead 厳禁 ENTRY/EXIT 判定 (SPEC_NOTIFY §4).

evaluate(bars, t_index, state, ...) は **bars[:t_index+1]** のみ参照。
bars[t_index+1:] を一切読まないことを tests/test_notify_triggers.py が監視する。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# Default pattern table for fallback (mirrors survival.pattern_table defaults).
DEFAULT_TABLE: Dict[str, Dict[str, float]] = {
    "high_vol|high": {"take_profit_pct": 3.5, "stop_loss_pct": -1.8},
    "high_vol|mid":  {"take_profit_pct": 2.5, "stop_loss_pct": -1.5},
    "high_vol|low":  {"take_profit_pct": 1.5, "stop_loss_pct": -1.2},
    "low_vol|high":  {"take_profit_pct": 2.0, "stop_loss_pct": -1.0},
    "low_vol|mid":   {"take_profit_pct": 1.5, "stop_loss_pct": -0.8},
    "low_vol|low":   {"take_profit_pct": 1.0, "stop_loss_pct": -0.6},
}

ENTRY_EDGE_THRESHOLD = 70.0
MAX_HOLD_BARS = 40


def _pattern_key(pat: Dict[str, str]) -> str:
    return f"{pat.get('regime','low_vol')}|{pat.get('distortion','mid')}"


def _lookup_exit(pattern_table: Dict[str, Dict[str, float]],
                 pat: Dict[str, str]) -> Dict[str, float]:
    key = _pattern_key(pat)
    return dict(pattern_table.get(key) or DEFAULT_TABLE.get(key)
                or DEFAULT_TABLE["low_vol|mid"])


def evaluate(bars: Sequence[Dict[str, Any]],
             t_index: int,
             state: Dict[str, Dict[str, Any]],
             edge_score_at_t: Optional[float],
             pattern: Dict[str, str],
             symbol: str,
             side: str,
             pattern_table: Optional[Dict[str, Dict[str, float]]] = None,
             ) -> List[Dict[str, Any]]:
    """Return ENTRY/EXIT event payloads for `symbol` at bar `t_index`.

    Look-ahead policy: this function never inspects `bars` beyond index
    `t_index`. Tests (test_notify_triggers.test_evaluate_does_not_index_future_bars)
    wrap `bars` in a watcher list and fail the test if any read crosses the
    boundary.
    """
    pattern_table = pattern_table or DEFAULT_TABLE
    if t_index < 0:
        return []
    # Bound the upper index — accessing past slices only.
    if t_index >= len(bars):
        return []
    cur_bar = bars[t_index]                # OK: t_index is the "now" bar
    cur_price = float(cur_bar["close"])
    out: List[Dict[str, Any]] = []
    pos = state.get(symbol)

    # EXIT first (existing position) — no entry-twice problem.
    if pos:
        entry_price = float(pos["entry_price"])
        side_open = pos.get("side", "long")
        tgts = pos.get("exit_targets") or {}
        tp_pct = float(tgts.get("take_profit_pct", 0.0))
        sl_pct = float(tgts.get("stop_loss_pct", 0.0))
        held = t_index - int(pos.get("entry_bar", t_index))
        # realized_pct sign convention: long = (now-entry)/entry, short = (entry-now)/entry
        if side_open == "long":
            realized = (cur_price - entry_price) / entry_price * 100.0
        else:
            realized = (entry_price - cur_price) / entry_price * 100.0
        kind: Optional[str] = None
        if realized >= tp_pct:
            kind = "EXIT_TP"
        elif realized <= sl_pct:
            kind = "EXIT_SL"
        elif held >= MAX_HOLD_BARS:
            kind = "EXIT_TIMEOUT"
        if kind:
            out.append({
                "kind": kind,
                "symbol": symbol,
                "side": side_open,
                "bar_tf": cur_bar.get("tf", "1d"),
                "bar_ts": cur_bar.get("ts", ""),
                "price": cur_price,
                "edge_score": None,
                "entry_ref": pos.get("event_id"),
                "pattern": pos.get("pattern", pattern),
                "size_pct": pos.get("size_pct", 0.0),
                "exit_targets": dict(pos.get("exit_targets") or {}),
                "realized_pct": round(realized, 6),
            })
            return out   # do not also ENTRY in the same bar — closed first.

    # ENTRY (no open position for this symbol).
    if not pos and edge_score_at_t is not None and edge_score_at_t >= ENTRY_EDGE_THRESHOLD:
        tgts = _lookup_exit(pattern_table, pattern)
        out.append({
            "kind": "ENTRY",
            "symbol": symbol,
            "side": side,
            "bar_tf": cur_bar.get("tf", "1d"),
            "bar_ts": cur_bar.get("ts", ""),
            "price": cur_price,
            "edge_score": float(edge_score_at_t),
            "entry_ref": None,
            "pattern": dict(pattern or {}),
            "size_pct": 0.0,                # supplied by caller from auto_risk
            "exit_targets": tgts,
            "realized_pct": None,
        })
    return out
