"""米国株（S&P500・NASDAQ100・DOW30）: その時点で入手できた決算だけで指標を計算する。

式は screener.calc.fund_us（F・魔法の公式・残余利益）。ここはファイルの読み込みだけ。
決算（<data_dir>/us/facts/<ticker>.json）は1社ずつ読み、使い終わったら捨てる
（全社の companyfacts を同時にメモリに載せない）。
"""

from __future__ import annotations

import json
from typing import Any

from ..calc import fund_us
from ..config import Config

Row = dict[str, Any]
_px_cache: dict[tuple[str, str], Any] = {}


def universe(cfg: Config) -> dict[str, dict[str, Any]]:
    p = cfg.us("universe.json")
    if not p.exists():
        return {}
    with open(p) as fh:
        out: dict[str, dict[str, Any]] = json.load(fh)
        return out


def load_facts(t: str, cfg: Config) -> dict[str, Any] | None:
    try:
        with open(cfg.us("facts", f"{t}.json")) as fh:
            facts: dict[str, Any] = json.load(fh)["facts"]
            return facts
    except (OSError, ValueError, KeyError):
        return None


def load_px(t: str, cfg: Config) -> Any:
    key = (str(cfg.us_dir), t)
    if key not in _px_cache:
        try:
            with open(cfg.us("px", f"{t}.json")) as fh:
                _px_cache[key] = fund_us.parse_yahoo_chart(json.load(fh))
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            _px_cache[key] = None
    return _px_cache[key]


def clear_cache() -> None:
    _px_cache.clear()


def screen(
    asof: str, p1y: str | None, p1m: str | None, cfg: Config, uni: dict[str, dict[str, Any]] | None = None
) -> list[Row]:
    uni = uni if uni is not None else universe(cfg)
    rows: list[Row] = []
    for t, info in uni.items():
        facts = load_facts(t, cfg)  # 1社ずつ
        r = fund_us.screen_one(t, info, facts, load_px(t, cfg), asof, p1y, p1m)
        del facts
        if r:
            rows.append(r)
    fund_us.rank(rows)
    return rows


def fwd(t: str, a: str, b: str, cfg: Config) -> float | None:
    p = load_px(t, cfg)
    if not p:
        return None
    x, y = fund_us.price_at(p, a, True), fund_us.price_at(p, b, True)
    return (y / x - 1) * 100 if x and y else None
