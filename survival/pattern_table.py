"""survival.pattern_table — パターン別利確テーブル (SPEC_SURVIVAL §3).

下振れ (stop_loss) は **触らない**。上振れ (take_profit) のみ EWMA で小さく更新。
- 取り逃しは構わない、緩めれば死ぬ、という非対称性を構造で固定。
"""

from __future__ import annotations

import copy
from typing import Dict, List, Tuple

# ───────────────────────────────────
# 初期値 (ボラ比例の既定)
# ───────────────────────────────────
# key = (regime, distortion)
DEFAULT_PATTERN_TABLE: Dict[Tuple[str, str], Dict[str, float]] = {
    ("high_vol", "high"): {"take_profit_pct": 3.5, "stop_loss_pct": -1.8},
    ("high_vol", "mid"):  {"take_profit_pct": 2.5, "stop_loss_pct": -1.5},
    ("high_vol", "low"):  {"take_profit_pct": 1.5, "stop_loss_pct": -1.2},
    ("low_vol", "high"):  {"take_profit_pct": 2.0, "stop_loss_pct": -1.0},
    ("low_vol", "mid"):   {"take_profit_pct": 1.5, "stop_loss_pct": -0.8},
    ("low_vol", "low"):   {"take_profit_pct": 1.0, "stop_loss_pct": -0.6},
}

MIN_TP_PCT = 0.5
MAX_TP_PCT = 6.0
EWMA_ALPHA = 0.10   # 1 日に動くのは 10% (小さく)


def daily_update(table: Dict[Tuple[str, str], Dict[str, float]],
                 recent_results: Dict[Tuple[str, str], List[Dict[str, float]]]
                 ) -> Dict[Tuple[str, str], Dict[str, float]]:
    """直近の realized 結果から take_profit のみ EWMA で更新。

    - 入力 table を **変更しない** (deepcopy を返す)。
    - recent_results が空 / 該当セル無しなら元と等しい dict を返す。
    - stop_loss_pct は触らない (テストで保証)。
    - take_profit_pct は [MIN_TP_PCT, MAX_TP_PCT] にクランプ。
    """
    out = copy.deepcopy(table)
    for cell_key, results in (recent_results or {}).items():
        if cell_key not in out or not results:
            continue
        # take_profit の中央値ではなく平均 (Phase 1 はシンプルに)
        pcts = []
        for r in results:
            try:
                p = float(r.get("pct"))
                pcts.append(p)
            except (TypeError, ValueError):
                continue
        if not pcts:
            continue
        avg = sum(pcts) / len(pcts)
        cur = out[cell_key]["take_profit_pct"]
        new_tp = cur * (1 - EWMA_ALPHA) + avg * EWMA_ALPHA
        new_tp = max(MIN_TP_PCT, min(MAX_TP_PCT, new_tp))
        out[cell_key]["take_profit_pct"] = round(new_tp, 4)
        # stop_loss_pct: 何があっても触らない (非対称性)
    return out


def serialize_for_json(table: Dict[Tuple[str, str], Dict[str, float]]
                       ) -> Dict[str, Dict[str, float]]:
    """data.json で扱えるよう (regime, distortion) → "regime|distortion" 文字列キー."""
    return {f"{r}|{d}": {"take_profit_pct": round(c["take_profit_pct"], 4),
                          "stop_loss_pct": round(c["stop_loss_pct"], 4)}
            for (r, d), c in table.items()}


def deserialize_from_json(serialized: Dict[str, Dict[str, float]]
                          ) -> Dict[Tuple[str, str], Dict[str, float]]:
    out = {}
    for k, v in (serialized or {}).items():
        regime, _, dist = k.partition("|")
        if regime and dist:
            out[(regime, dist)] = dict(v)
    return out


def lookup(table: Dict[Tuple[str, str], Dict[str, float]],
           regime: str, distortion: str) -> Dict[str, float]:
    return dict(table.get((regime, distortion))
                or table.get((regime, "mid"))
                or table.get(("low_vol", "mid"))
                or {"take_profit_pct": 1.5, "stop_loss_pct": -1.0})
