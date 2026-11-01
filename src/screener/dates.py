"""日付の決め方（直書きの日付を使わず、手元のファイルと今日から決める）。"""

from __future__ import annotations

import bisect
import calendar
import datetime as dt
import glob
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config

DateLike = str | dt.date


def iso(d: DateLike) -> str:
    return d if isinstance(d, str) else d.isoformat()


def files_dates(pattern: str | Path) -> list[str]:
    """'.../bars_*.json' や '.../daily/*.json' → ['YYYY-MM-DD', ...]（昇順）。"""
    out = []
    for f in glob.glob(str(pattern)):
        b = os.path.basename(f)
        s = b[b.index("_") + 1 : b.index("_") + 11] if "_" in b else b[:10]
        try:
            dt.date.fromisoformat(s)
        except ValueError:
            continue
        out.append(s)
    return sorted(set(out))


def on_or_before(dates: list[str], target: DateLike) -> str | None:
    """dates（昇順）のうち target 以前で最も新しいもの。無ければ None。"""
    i = bisect.bisect_right(dates, iso(target)) - 1
    return dates[i] if i >= 0 else None


def minus(d: DateLike, years: int = 0, months: int = 0, days: int = 0) -> dt.date:
    x = dt.date.fromisoformat(iso(d))
    y, m = x.year - years, x.month - months
    while m < 1:
        m += 12
        y -= 1
    day = min(x.day, calendar.monthrange(y, m)[1])
    return dt.date(y, m, day) - dt.timedelta(days=days)


def weekdays(start: DateLike, end: DateLike) -> list[str]:
    d, e = dt.date.fromisoformat(iso(start)), dt.date.fromisoformat(iso(end))
    out = []
    while d <= e:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def jp_anchor_dates(cfg: Config, asof: DateLike | None = None) -> tuple[str, str, str, str, str]:
    """screen() に渡す (ASOF, PX, P1Y, P1M, MASTER のパス) を手元の bars_/master_ から決める。"""
    bars = files_dates(cfg.jp("bars_*.json"))
    masters = files_dates(cfg.jp("master_*.json"))
    if not bars or not masters:
        raise FileNotFoundError(
            f"{cfg.jp_dir} に bars_*.json / master_*.json がありません（python -m screener.japan.fetch）"
        )
    a = iso(asof) if asof else (dt.date.fromisoformat(bars[-1]) + dt.timedelta(days=1)).isoformat()
    px = on_or_before(bars, (dt.date.fromisoformat(a) - dt.timedelta(days=1)).isoformat()) or bars[-1]
    p1y = on_or_before(bars, minus(px, years=1)) or bars[0]
    p1m = on_or_before(bars, minus(px, months=1)) or bars[0]
    m = on_or_before(masters, px) or masters[-1]
    return a, px, p1y, p1m, str(cfg.jp(f"master_{m}.json"))


def yearly_windows(dates: list[str], n: int = 3) -> list[tuple[str, str, str, str]]:
    """検証の期間（t0, 1年前, 1か月前, t1=t0の1年後）を手元の日付から n 個作る（古い順）。"""
    out: list[tuple[str, str, str, str]] = []
    if not dates:
        return out
    t1 = dates[-1]
    for _ in range(n):
        t0 = on_or_before(dates, minus(t1, years=1))
        if not t0 or t0 == t1:
            break
        p1y = on_or_before(dates, minus(t0, years=1)) or t0
        p1m = on_or_before(dates, minus(t0, months=1)) or t0
        out.append((t0, p1y, p1m, t1))
        t1 = t0
    return out[::-1]
