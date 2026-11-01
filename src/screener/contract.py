"""J-Quants の契約テスト（毎日の取得の前に、データの「形」が変わっていないか確かめる）。判定式は calc.contracts。

API が V2 / 直近営業日の日足件数 ≥ 3500 / 決算短信に必要な列がある
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from .calc import contracts as C
from .jquants import API_BASE, API_VERSION, Getter


def observe(today: dt.date, get: Getter, lookback: int = 10) -> dict[str, Any]:
    """直近の営業日（最大 lookback 日さかのぼる）の日足件数と、決算短信の1行（列名を見る）。"""
    obs: dict[str, Any] = {"api_version": API_VERSION, "api_base": API_BASE}
    n, row = 0, None
    for back in range(lookback):
        x = today - dt.timedelta(days=back)
        if x.weekday() >= 5:
            continue
        if not n:
            r = get("equities/bars/daily", date=x.isoformat())
            n = len(r) if isinstance(r, list) else 0
            if n:
                obs["jq_daily_date"] = x.isoformat()
        if row is None:
            r = get("fins/summary", date=x.isoformat())
            if isinstance(r, list) and r:
                row = next((v for v in r if str(v.get("DocType", "")).startswith("FY")), r[0])
        if n and row is not None:
            break
    obs["jq_daily_count"] = n
    obs["jq_fins_row"] = row
    return obs


def evaluate(obs: dict[str, Any]) -> tuple[bool, str]:
    v = obs.get("api_version")
    ok_v = v == C.JQ_API_VERSION and API_VERSION == C.JQ_API_VERSION and API_BASE.endswith("/" + C.JQ_API_VERSION)
    res = [
        (ok_v, f"J-Quants API: {v}（想定 {C.JQ_API_VERSION}）"),
        C.min_count("J-Quants 日足", int(obs.get("jq_daily_count") or 0), C.JQ_DAILY_MIN),
        C.has_columns("J-Quants 決算短信", obs.get("jq_fins_row"), C.JQ_FIN_COLUMNS),
    ]
    ok, text = C.summarize(res)
    return bool(ok), str(text)


class ContractError(RuntimeError):
    pass


def check(today: dt.date, get: Getter) -> str:
    """不合格なら ContractError（メッセージは件数と列名だけ。値は出さない）。"""
    ok, text = evaluate(observe(today, get))
    if not ok:
        raise ContractError("J-Quants 契約テスト不合格\n" + text)
    return text
