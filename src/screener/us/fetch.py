"""米国株のデータ取得（保存場所は <data_dir>/us）。

--universe  構成銘柄の一覧を作り直す。リポジトリの data/universe/{sp500,nasdaq100,dow30}.json（週次の
            universe.yml が更新）を優先、無ければ Wikipedia。件数が想定 ±5% から外れたら前回の一覧のまま。
--edgar     EDGAR companyfacts を1社ずつ取り直す（SEC の 10回/秒 を超えないよう間を空ける・並列にしない）
--prices    Yahoo の日足。既定は1か月分を取って手元のファイルに付け足す（毎日）。--full で5年分。
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import config as config_mod
from ..calc.contracts import count_within
from ..config import Config

IDX = {"sp500": "S&P500", "nasdaq100": "NAS100", "dow30": "DOW30"}
DOW_FALLBACK = (
    "MMM GOOGL AMZN AXP AMGN AAPL BA CAT CVX CSCO KO DIS GS HD HON IBM JNJ JPM MCD MRK MSFT NKE NVDA PG "
    "CRM SHW TRV UNH V WMT"
).split()
Raw = Callable[..., bytes]


def raw(u: str, ua: str | None = None, timeout: float = 40) -> bytes:
    req = urllib.request.Request(u, headers={"User-Agent": ua or "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data: bytes = r.read()
        return data


# ---------- 構成銘柄 ----------
def from_repo(udir: Path) -> dict[str, dict[str, str]] | None:
    out: dict[str, dict[str, str]] = {}
    for name in IDX:
        p = udir / f"{name}.json"
        if not p.exists():
            return None
        with open(p, encoding="utf-8") as fh:
            j = json.load(fh)
        mem = j.get("members") if isinstance(j, dict) else j
        if isinstance(mem, list):
            mem = {t: t for t in mem}
        out[name] = dict(mem or {})
    return out


def from_wikipedia() -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    import pandas as pd

    sp = pd.read_html(io.StringIO(raw("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies").decode()))[0]
    nd = pd.read_html(io.StringIO(raw("https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies").decode()))[0]
    sectors: dict[str, str] = {}
    out: dict[str, dict[str, str]] = {"sp500": {}, "nasdaq100": {}, "dow30": {t: t for t in DOW_FALLBACK}}
    for t, n, s in zip(sp["Symbol"], sp["Security"], sp["GICS Sector"], strict=False):
        out["sp500"][t] = n
        sectors[t] = s
    for t, n, s in zip(nd["Ticker"], nd["Company"], nd.iloc[:, 3], strict=False):
        out["nasdaq100"][t] = n
        sectors.setdefault(t, s)
    return out, sectors


def build_universe(
    lists: dict[str, dict[str, str]], prev: dict[str, Any] | None = None, sectors: dict[str, str] | None = None
) -> dict[str, dict[str, Any]]:
    prev = prev or {}
    sectors = sectors or {}
    U: dict[str, dict[str, Any]] = {}
    for name, mem in lists.items():
        for t, n in mem.items():
            e = U.setdefault(
                t,
                {
                    "name": n if n != t else prev.get(t, {}).get("name", t),
                    "sector": sectors.get(t) or prev.get(t, {}).get("sector", ""),
                    "idx": [],
                },
            )
            e["idx"].append(IDX[name])
    return U


def update_universe(
    cfg: Config, lists: dict[str, dict[str, str]] | None = None, sectors: dict[str, str] | None = None
) -> dict[str, Any]:
    p = cfg.us("universe.json")
    prev = json.loads(p.read_text()) if p.exists() else {}
    src = "given"
    if lists is None:
        lists = from_repo(cfg.repo_dir / "data" / "universe")
        src = "repo"
        if lists is None:
            lists, sectors = from_wikipedia()
            src = "wikipedia"
    res = [count_within(name, len(mem)) for name, mem in lists.items()]
    ok = all(r[0] for r in res)
    rec: dict[str, Any] = {"source": src, "ok": ok, "messages": [r[1] for r in res]}
    if ok:
        U = build_universe(lists, prev, sectors)
        rec["added"] = sorted(set(U) - set(prev)) if prev else []
        rec["removed"] = sorted(set(prev) - set(U)) if prev else []
        cfg.us_dir.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(U, ensure_ascii=False))
    return rec


# ---------- EDGAR（1社ずつ） ----------
def fetch_edgar(
    cfg: Config, tickers: list[str], force: bool = True, getter: Raw = raw, sleep: Callable[[float], None] = time.sleep
) -> tuple[int, int]:
    ua = str(cfg.get("edgar.user_agent"))
    cik = {
        v["ticker"]: v["cik_str"]
        for v in json.loads(getter("https://www.sec.gov/files/company_tickers.json", ua)).values()
    }
    cfg.us("facts").mkdir(parents=True, exist_ok=True)
    got = err = 0
    for t in tickers:  # 1社ずつ（並列にしない・メモリに溜めない）
        c = cik.get(t.replace(".", "-")) or cik.get(t)
        p = cfg.us("facts", f"{t}.json")
        if not c or (p.exists() and not force):
            continue
        for i in range(3):
            try:
                b = getter(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c:010d}.json", ua)
                tmp = p.with_suffix(".json.tmp")
                tmp.write_bytes(b)
                os.replace(tmp, p)
                got += 1
                break
            except Exception:
                sleep(2 * (i + 1))
        else:
            err += 1
        sleep(0.15)
    return got, err


# ---------- Yahoo ----------
def merge_chart(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any] | None:
    """Yahoo chart JSON を timestamp で付け足す（同じ日は新しい方）。新しい分割があれば None（5年分を取り直す）。"""
    ro, rn = old["chart"]["result"][0], new["chart"]["result"][0]
    new_splits = set(((rn.get("events") or {}).get("splits") or {}).keys())
    old_splits = set(((ro.get("events") or {}).get("splits") or {}).keys())
    if new_splits - old_splits:
        return None
    rows: dict[str, tuple[Any, ...]] = {}
    for r in (ro, rn):
        q = r["indicators"]["quote"][0]
        a = (r["indicators"].get("adjclose") or [{"adjclose": q["close"]}])[0]["adjclose"]
        for i, ts in enumerate(r["timestamp"]):
            day = dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%d")
            rows[day] = (ts, q["high"][i], q["low"][i], q["close"][i], a[i])
    days = sorted(rows)
    out: dict[str, Any] = json.loads(json.dumps(old))
    r = out["chart"]["result"][0]
    r["timestamp"] = [rows[d][0] for d in days]
    r["indicators"]["quote"][0] = {
        "high": [rows[d][1] for d in days],
        "low": [rows[d][2] for d in days],
        "close": [rows[d][3] for d in days],
    }
    r["indicators"]["adjclose"] = [{"adjclose": [rows[d][4] for d in days]}]
    if rn.get("events"):
        r["events"] = rn["events"]
    return out


def fetch_prices(
    cfg: Config, tickers: list[str], full: bool = False, getter: Raw = raw, sleep: Callable[[float], None] = time.sleep
) -> tuple[int, int]:
    cfg.us("px").mkdir(parents=True, exist_ok=True)
    got = err = 0
    base = "https://query1.finance.yahoo.com/v8/finance/chart/"
    for t in tickers:
        p = cfg.us("px", f"{t}.json")
        y = t.replace(".", "-")
        rng = "5y" if (full or not p.exists()) else "1mo"
        try:
            j = json.loads(getter(f"{base}{y}?range={rng}&interval=1d&events=split,div"))
            if rng != "5y":
                m = merge_chart(json.loads(p.read_text()), j)
                j = m if m is not None else json.loads(getter(f"{base}{y}?range=5y&interval=1d&events=split,div"))
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(j))
            os.replace(tmp, p)
            got += 1
        except Exception:
            err += 1
        sleep(0.2)
    return got, err


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--universe", action="store_true")
    ap.add_argument("--edgar", action="store_true")
    ap.add_argument("--prices", action="store_true")
    ap.add_argument("--full", action="store_true", help="株価を5年分取り直す")
    a = ap.parse_args(argv)
    cfg = config_mod.load()
    rc = 0
    if a.universe:
        rec = update_universe(cfg)
        print("universe", rec["source"], "ok" if rec["ok"] else "外れ（前回のまま）", rec["messages"], flush=True)
        rc |= 0 if rec["ok"] else 1
    p = cfg.us("universe.json")
    U = json.loads(p.read_text()) if p.exists() else {}
    if a.edgar:
        got, err = fetch_edgar(cfg, list(U))
        print("edgar", got, "err", err, flush=True)
        rc |= 1 if err > len(U) * 0.1 else 0
    if a.prices:
        got, err = fetch_prices(cfg, list(U), a.full)
        print("prices", got, "err", err, flush=True)
        rc |= 1 if err > len(U) * 0.1 else 0
    return rc


if __name__ == "__main__":
    sys.exit(main())
