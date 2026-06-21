"""loop.holdout — 直近 2 年ホールドアウトの物理ブロック (SPEC_LOOP §1).

開発フェーズではホールドアウト bars を 1 度も読まないよう、load 入口で削る.
"""

from __future__ import annotations

import datetime
from typing import Any, List, Optional, Sequence


def _two_years_ago_iso(today: Optional[datetime.date] = None) -> str:
    d = today or datetime.date.today()
    try:
        return d.replace(year=d.year - 2).isoformat()
    except ValueError:
        # うるう年 (2/29) の場合は 1 日ずらす
        return (d.replace(year=d.year - 2, day=d.day - 1)).isoformat()


HOLDOUT_START: str = _two_years_ago_iso()


def filter_pre_holdout(bars: Sequence[dict],
                       holdout_start: Optional[str] = None) -> List[dict]:
    """holdout_start 以降の bar を全て削除する.

    holdout_start は ISO 日付 ("YYYY-MM-DD").
    """
    cutoff = (holdout_start or HOLDOUT_START)[:10]
    return [b for b in (bars or []) if str(b.get("ts") or "")[:10] < cutoff]
