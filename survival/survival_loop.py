"""survival.survival_loop — data.json.survival_loop ブロック生成.

fetch_signals.main() から呼ばれる。SPEC_SURVIVAL §4 の構造を出力。
全ての副作用は無く、`build(data)` 1 関数で完結 (テスト容易).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from . import bankruptcy as bk
from . import edge_score as es
from . import pattern_table as pt
from . import risk_engine as re

SURVIVAL_VERSION = "1"

# Phase 1 で履歴不在: 不可知的な既定値で動かす (テスト済み)
_PHASE1_WIN_PROB = 0.50
_PHASE1_WLR = 1.0


def _safe_num(x) -> Optional[float]:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _build_risk_gate(data: dict) -> dict:
    """money_flow + VIX + yield_curve から 1 単語の risk-on/off/neutral."""
    score = 0
    reasons: List[str] = []

    mf = data.get("money_flow") or {}
    us_cb = (mf.get("us") or {}).get("cb_assets") or {}
    wow = _safe_num(us_cb.get("wow_change"))
    if wow is not None:
        if wow > 0:
            score += 1; reasons.append("Fed assets expanding")
        elif wow < 0:
            score -= 1; reasons.append("Fed assets contracting")

    vix_row = next(
        (r for r in (data.get("markets") or {}).get("volatility", [])
         if r.get("symbol") == "VIX"),
        None,
    )
    vix = _safe_num(vix_row.get("price")) if vix_row else None
    if vix is not None:
        if vix >= 30:
            score -= 2; reasons.append(f"VIX {vix:.1f} high")
        elif vix >= 20:
            score -= 1; reasons.append(f"VIX {vix:.1f} elevated")
        elif vix < 15:
            score += 1; reasons.append(f"VIX {vix:.1f} calm")

    yc = (data.get("meta") or {}).get("yield_curve") or {}
    state = ((yc.get("us_10y_2y_spread") or {}).get("state") or "")
    if state == "inverted":
        score -= 1; reasons.append("US curve inverted")
    elif state == "normal_or_steepening":
        score += 0  # neutral fact

    if score >= 1:
        label, color = "risk-on", "green"
    elif score <= -1:
        label, color = "risk-off", "red"
    else:
        label, color = "neutral", "yellow"

    return {
        "label": label,
        "color": color,
        "score": int(score),
        "reasons": reasons,
        "inputs": {
            "money_flow_wow": wow,
            "vix": vix,
            "yield_curve_state": state or None,
        },
        "note": "Macro environment indicator. Not investment advice.",
    }


def _classify_pattern(stretch: Optional[float], vol_pct: Optional[float]):
    """(regime, distortion)."""
    if vol_pct is not None and vol_pct >= 2.0:
        regime = "high_vol"
    else:
        regime = "low_vol"
    if stretch is None:
        distortion = "mid"
    elif stretch >= 0.6:
        distortion = "high"
    elif stretch >= 0.3:
        distortion = "mid"
    else:
        distortion = "low"
    return regime, distortion


def _collect_candidates(data: dict, as_of: str) -> List[dict]:
    out: List[dict] = []
    markets = data.get("markets") or {}
    imm_rows = markets.get("imm") or []
    for mkt in ("nikkei225", "dow30", "nasdaq100", "sp500", "fx"):
        for row in markets.get(mkt) or []:
            if row.get("error"):
                continue
            cand = es.build_candidate(row, imm_rows, mkt, as_of)
            out.append(cand)
    out.sort(key=lambda c: (c.get("edge_score") or 0), reverse=True)
    return out


def _realized_vol_estimate(candidates: List[dict]) -> float:
    """全候補の vol_context_pct 平均。手元に値が無ければ 1.0% の保守的既定."""
    vals = [c["vol_context_pct"] for c in candidates if c.get("vol_context_pct")]
    if not vals:
        return 1.0
    return sum(vals) / len(vals)


def _build_mode_a(candidates: List[dict], table, per_trade_pct: float,
                  as_of_date: str) -> List[dict]:
    """edge_score>=70 上位 max_concurrent 件を仮想エントリ."""
    cap = re.HARD_CAPS["MAX_CONCURRENT"]
    positions: List[dict] = []
    for c in candidates:
        if len(positions) >= cap:
            break
        es_val = c.get("edge_score")
        if es_val is None or es_val < 70:
            continue
        regime, dist = _classify_pattern(c.get("stretch"), c.get("vol_context_pct"))
        exit_cell = pt.lookup(table, regime, dist)
        positions.append({
            "symbol": c.get("symbol"),
            "name": c.get("name"),
            "market": c.get("market"),
            "direction": c.get("direction_hint") if c.get("direction_hint") in ("long", "short") else "long",
            "entry_date": as_of_date,
            "entry_edge_score": es_val,
            "pattern": {"regime": regime, "distortion": dist},
            "exit": {
                "take_profit_pct": exit_cell["take_profit_pct"],
                "stop_loss_pct": exit_cell["stop_loss_pct"],
            },
            "size_pct": re.clamp_risk(per_trade_pct),
            "data_status": c.get("data_status"),
            "note": "Mode A virtual entry (machine). Macro environment context only — not investment advice.",
        })
    return positions


def build(data: dict) -> dict:
    """data (markets/meta/money_flow を読み込み済) から survival_loop を返す."""
    as_of_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    as_of_date = as_of_iso[:10]

    risk_gate = _build_risk_gate(data)
    candidates = _collect_candidates(data, as_of_iso)

    realized = _realized_vol_estimate(candidates)
    risk = re.design_daily_risk(
        realized_vol_pct=realized,
        win_prob=_PHASE1_WIN_PROB,
        win_loss_ratio=_PHASE1_WLR,
    )

    table = pt.DEFAULT_PATTERN_TABLE      # Phase 1 はデフォルトから出す
    serialized_table = pt.serialize_for_json(table)

    mode_a = _build_mode_a(candidates, table, risk["per_trade_pct"], as_of_date)

    hm = bk.heatmap(
        win_prob=_PHASE1_WIN_PROB,
        win_loss_ratio=_PHASE1_WLR,
        balances_pct_basis=[300, 400, 500],
        risk_options=[0.1, 0.25, 0.5],
        trades=200, runs=300,
        dd_stop_pct=abs(re.HARD_CAPS["DD_STOP_PCT"]),
    )

    return {
        "as_of": as_of_iso,
        "version": SURVIVAL_VERSION,
        "risk_gate": risk_gate,
        "auto_risk": risk,
        "pattern_table": serialized_table,
        # 候補は edge_score>=55 上位 20 件 (Phase 1 spec §4.1 のチューニング点)
        "candidates": [c for c in candidates if (c.get("edge_score") or 0) >= 55][:20],
        "mode_a_positions": mode_a,
        "mode_b_note": "Mode B = discretionary. Recorded client-side (localStorage).",
        "mode_c_note": "Mode C = A/B comparison ledger. Verdict in Phase 3.",
        "bankruptcy_simulation": hm,
        "notes": [
            "Hard caps in survival.risk_engine.HARD_CAPS (no learning).",
            "Stop loss / margin call / DD ceilings are fixed. Not adjusted by daily_update.",
            "Phase 1: no model learning, no regime auto-switch.",
            "Market environment visualization only. Not investment advice.",
        ],
    }
