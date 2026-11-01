"""米国株の最新の指標と判定を <data_dir>/us/us_value.json / .csv に出す（screen.py を使用）。"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys

from .. import config as config_mod
from ..config import Config
from . import screen as S

KEYS = [
    "ticker", "name", "idx", "sector", "fin_tag", "fy", "price", "mcap_bn", "PER", "PBR", "roe_pct",
    "earnings_yield_pct", "roc_pct", "magic_rank", "F", "f_max", "ret_1y_pct", "ri_upside_pct",
]  # fmt: skip


def tag(r: S.Row) -> str:
    q = r["f_max"] >= 5 and r["F"] >= r["f_max"] - 2
    mf = r.get("magic_rank")
    t = []
    if not r["fin"] and mf and mf <= 50 and q:
        t.append("value_quality_top50")
    if not r["fin"] and mf and mf <= 100 and q and (r.get("ret_1y_pct") or -1) > 0:
        t.append("mid_candidate")
    return "|".join(t)


def build(cfg: Config, today: dt.date) -> list[S.Row]:
    rows = S.screen(str(today), str(today - dt.timedelta(days=365)), str(today - dt.timedelta(days=30)), cfg=cfg)
    for r in rows:
        r["fin_tag"] = tag(r)
    rows.sort(key=lambda r: r.get("magic_rank") or 9999)
    return [{k: r.get(k) for k in KEYS} | {"fin": r.get("fin")} for r in rows]


def write(cfg: Config, rows: list[S.Row]) -> None:
    cfg.us_dir.mkdir(parents=True, exist_ok=True)
    with open(cfg.us("us_value.json"), "w") as fh:
        json.dump(rows, fh, ensure_ascii=False)
    with open(cfg.us("us_value.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=KEYS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", help="基準日（既定: 今日 JST）")
    a = ap.parse_args(argv)
    cfg = config_mod.load()
    today = dt.date.fromisoformat(a.today) if a.today else config_mod.today_jst()
    rows = build(cfg, today)
    write(cfg, rows)
    print(len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
