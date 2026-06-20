"""survival.edge_score — stretch / positioning_fuel / vol_context / edge_score.

SPEC_SURVIVAL §4 候補抽出。取得不能な要素は None。捏造しない。
"""

from __future__ import annotations

import math
from typing import Iterable, List, Optional


def _f(x) -> Optional[float]:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


# ──────────────────────────────────────────────
# stretch: RSI / BB%B / CCI の歪み度合い (0..1)
#   - どれか一つでも極端なら高いスコアを出す (max ベース)。
#   - RSI ≤ 35 / ≥ 65、BB%B が両端 0.2 外側、CCI |.| >= 100 を歪み判定に。
# ──────────────────────────────────────────────
def stretch_score(row: dict) -> Optional[float]:
    parts: List[float] = []
    rsi = _f(row.get("rsi"))
    if rsi is not None:
        if rsi <= 35:
            parts.append(min(1.0, (35 - rsi) / 25))
        elif rsi >= 65:
            parts.append(min(1.0, (rsi - 65) / 25))
        else:
            parts.append(0.0)
    bb = _f(row.get("bb_pct"))
    if bb is not None:
        # 0.5 から離れるほど extreme。0.2 外側で 0、0/1 で 1.0
        ext = max(0.0, abs(bb - 0.5) * 2 - 0.4) / 0.6
        parts.append(min(1.0, ext))
    cci = _f(row.get("cci_daily"))
    if cci is None:
        cci = _f(row.get("cci_4h"))
    if cci is not None:
        parts.append(min(1.0, max(0.0, (abs(cci) - 100) / 200)))
    if not parts:
        return None
    # どれか一つでも強く歪んでいれば「妙味」として拾う (max)。
    # ただし複数指標が同時に歪んでいるほど確度が高いので、平均で 0.2 だけ補強。
    mx = max(parts)
    avg = sum(parts) / len(parts)
    return round(mx * 0.8 + avg * 0.2, 4)


# ──────────────────────────────────────────────
# positioning_fuel: IMM/COT 極端さ。FX 以外は None。
# ──────────────────────────────────────────────
_IMM_MAP = {
    "USDJPY=X": "JPY_IMM",
    "EURUSD=X": "EUR_IMM",
    "GBPUSD=X": "GBP_IMM",
    "AUDUSD=X": "AUD_IMM",
    "USDCAD=X": "CAD_IMM",
    "USDCHF=X": "CHF_IMM",
}


def positioning_fuel(symbol: str, imm_rows: Iterable[dict]) -> Optional[float]:
    imm_sym = _IMM_MAP.get(symbol)
    if not imm_sym:
        return None
    rec = next((r for r in (imm_rows or []) if r.get("symbol") == imm_sym), None)
    if not rec:
        return None
    crowd = (rec.get("crowding_risk") or "").lower()
    if crowd == "high":
        return 0.8
    if crowd == "medium":
        return 0.4
    if crowd == "low":
        return 0.1
    return None


# ──────────────────────────────────────────────
# vol_context: 直近ボラ (ATR/price → 日次想定変動 %)
# ──────────────────────────────────────────────
def vol_context_pct(row: dict) -> Optional[float]:
    atr = _f(row.get("atr"))
    price = _f(row.get("price"))
    if atr is None or price is None or price <= 0:
        return None
    return round(atr / price * 100, 3)


# ──────────────────────────────────────────────
# edge_score: 0..100 (None なら edge_score=None で残す)
# ──────────────────────────────────────────────
def edge_score(stretch: Optional[float],
               positioning: Optional[float],
               vol_pct: Optional[float]) -> Optional[float]:
    if stretch is None and positioning is None and vol_pct is None:
        return None
    score = 0.0
    weight = 0.0
    if stretch is not None:
        score += stretch * 60     # 主要因
        weight += 60
    if positioning is not None:
        score += positioning * 25
        weight += 25
    if vol_pct is not None and vol_pct > 0:
        # vol が 0.5%〜4% にあるとボーナス、両端で減衰。広めの sweet spot で
        # equities (vc≈3%) も拾えるようにする。
        v = min(1.0, max(0.0, 1 - abs(vol_pct - 2.0) / 4.0))
        score += v * 15
        weight += 15
    if weight == 0:
        return None
    # 重みを 100 換算
    return round(score / weight * 100, 1)


# ──────────────────────────────────────────────
# 方向 hint: RSI が高ければ short bias, 低ければ long bias (mean-revert)
# ──────────────────────────────────────────────
def direction_hint(row: dict) -> str:
    rsi = _f(row.get("rsi"))
    bb = _f(row.get("bb_pct"))
    if rsi is None and bb is None:
        return "neutral"
    score = 0.0
    if rsi is not None:
        score += (50 - rsi) / 50    # >50 → short, <50 → long
    if bb is not None:
        score += (0.5 - bb) * 2     # >0.5 → short, <0.5 → long
    if score > 0.2:
        return "long"
    if score < -0.2:
        return "short"
    return "neutral"


# ──────────────────────────────────────────────
# 候補抽出
# ──────────────────────────────────────────────
def build_candidate(row: dict, imm_rows: Iterable[dict], market_key: str,
                    as_of: str) -> dict:
    s = stretch_score(row)
    pf = positioning_fuel(row.get("symbol", ""), imm_rows)
    vc = vol_context_pct(row)
    es = edge_score(s, pf, vc)
    status = row.get("data_status") or ("placeholder" if row.get("error") else "live")
    return {
        "symbol": row.get("symbol"),
        "market": market_key,
        "name": row.get("name"),
        "direction_hint": direction_hint(row),
        "stretch": s,
        "positioning_fuel": pf,
        "vol_context_pct": vc,
        "edge_score": es,
        "rsi": _f(row.get("rsi")),
        "bb_pct": _f(row.get("bb_pct")),
        "data_status": status,
        "as_of": as_of,
    }
