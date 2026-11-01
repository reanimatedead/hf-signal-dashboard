"""J-Quants から日本株のデータを取ってデータ置き場に保存する（すべて 50回/60秒 の回数制限を通る）。

  daily/YYYY-MM-DD.json   日足（全銘柄）[[Code4, AdjH, AdjL, AdjC, Va], ...]
  fins/YYYY-MM-DD.json    決算短信（開示日別, fins/summary の生の行）
  bars_YYYY-MM-DD.json    日足の生データ（時価総額 MktCap つき）: 各月の最初の日と、取得範囲の最後の日
  master_YYYY-MM-DD.json  銘柄一覧（equities/master）: 各月の最初の日
  months.json             各月の最初の日の一覧

既定は今日（JST）の分だけ（毎日の差分）。--full で history_years 年分（初回の一括取得）。
既にあるファイルは取り直さない（--force で上書き。削除はしない）。

    python -m screener.japan.fetch            # 今日の差分
    python -m screener.japan.fetch --full     # 5年分（初回）
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import sys
from typing import Any

from .. import config as config_mod
from ..config import Config
from ..dates import files_dates, minus, weekdays
from ..jquants import Getter, default_client


def compact(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [[b["Code"][:4], b.get("AdjH"), b.get("AdjL"), b.get("AdjC"), b.get("Va")] for b in rows]


def _dump(path: os.PathLike[str] | str, obj: Any) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    os.replace(tmp, path)


def fetch_daily(
    dates: list[str], cfg: Config, get: Getter, keep_raw: bool = True, force: bool = False, threads: int = 3
) -> dict[str, int]:
    """日足。スレッドで並べても回数制限は1つ（Client の RateLimiter はスレッド安全）。"""
    cfg.jp("daily").mkdir(parents=True, exist_ok=True)
    todo = [d for d in dates if force or not cfg.jp("daily", f"{d}.json").exists()]
    last = dates[-1] if dates else None

    def one(x: str) -> int:
        r = get("equities/bars/daily", date=x)
        if isinstance(r, list):
            _dump(cfg.jp("daily", f"{x}.json"), compact(r))
            if keep_raw and x == last and r:
                _dump(cfg.jp(f"bars_{x}.json"), r)
            return len(r)
        return -1

    with cf.ThreadPoolExecutor(threads) as ex:
        res = list(ex.map(one, todo))
    return {"fetched": len(todo), "empty": sum(1 for x in res if x == 0), "err": sum(1 for x in res if x < 0)}


def fetch_fins(dates: list[str], cfg: Config, get: Getter, force: bool = False) -> int:
    """決算短信（開示日別）と、その月の銘柄一覧（まだ無ければ）。戻り値はエラーの数。"""
    cfg.jp("fins").mkdir(parents=True, exist_ok=True)
    err = 0
    for d in dates:
        p = cfg.jp("fins", f"{d}.json")
        if force or not p.exists():
            r = get("fins/summary", date=d)
            if isinstance(r, list):
                _dump(p, r)
            else:
                err += 1
    if dates:
        d = dates[-1]
        have = [m for m in files_dates(cfg.jp("master_*.json")) if m[:7] == d[:7]]
        if force or not have:
            r = get("equities/master", date=d)
            if isinstance(r, list) and r:
                _dump(cfg.jp(f"master_{d}.json"), r)
            elif not isinstance(r, list):
                err += 1
    return err


def month_firsts(days: list[str], since: str | None = None) -> list[str]:
    months, seen = [], set()
    for d in days:
        if since and d < since:
            continue
        if d[:7] not in seen:
            seen.add(d[:7])
            months.append(d)
    return months


def fetch_month(cfg: Config, get: Getter) -> tuple[list[str], int]:
    """各月の最初の営業日の bars_ と master_（無い月だけ通信する）と months.json。"""
    days = [d for d in files_dates(cfg.jp("daily", "*.json")) if os.path.getsize(cfg.jp("daily", f"{d}.json")) > 10]
    months = month_firsts(days)
    calls = 0
    for d in months:
        if not cfg.jp(f"bars_{d}.json").exists():
            x = get("equities/bars/daily", date=d)
            calls += 1
            if isinstance(x, list):
                _dump(cfg.jp(f"bars_{d}.json"), x)
        if not cfg.jp(f"master_{d}.json").exists():
            x = get("equities/master", date=d)
            calls += 1
            if isinstance(x, list):
                _dump(cfg.jp(f"master_{d}.json"), x)
    _dump(cfg.jp("months.json"), months)
    return months, calls


def date_range(cfg: Config, today: dt.date, full: bool = False) -> list[str]:
    if full:
        return weekdays(minus(today, years=int(cfg.get("jquants.history_years", 5))), today)
    return weekdays(today, today)


def run(
    cfg: Config, today: dt.date, full: bool = False, get: Getter | None = None, force: bool = False
) -> dict[str, Any]:
    """毎日の差分（既定）または一括取得（full）。エラーがあれば RuntimeError（何件かだけ。中身は出さない）。"""
    if get is None:
        get = default_client(int(cfg.get("jquants.rate_per_min", 50)), str(cfg.get("jquants.keychain_service"))).get
    dates = date_range(cfg, today, full)
    d = fetch_daily(dates, cfg, get, keep_raw=True, force=force)
    e = fetch_fins(dates, cfg, get, force=force)
    months, calls = fetch_month(cfg, get)
    res = {"dates": len(dates), **d, "fins_err": e, "months": len(months), "month_calls": calls}
    if d["err"] or e:
        raise RuntimeError(f"J-Quants 取得のエラー: 日足 {d['err']} 件・決算/銘柄一覧 {e} 件")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--full", action="store_true", help="history_years 年分（初回の一括取得）")
    ap.add_argument("--today", help="基準日（既定: 今日 JST）")
    ap.add_argument("--force", action="store_true", help="既にあるファイルも取り直す（上書き）")
    a = ap.parse_args(argv)
    cfg = config_mod.load()
    cfg.ensure_dirs()
    today = dt.date.fromisoformat(a.today) if a.today else config_mod.today_jst()
    r = run(cfg, today, a.full, force=a.force)
    print({k: v for k, v in r.items()}, flush=True)  # 件数だけ（株のデータは出さない）
    return 0


if __name__ == "__main__":
    sys.exit(main())
