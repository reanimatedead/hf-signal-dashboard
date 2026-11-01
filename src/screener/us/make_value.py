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
    "ticker", "name", "idx", "sector", "判定", "fy", "price", "mcap_bn", "PER", "PBR", "ROE%", "益回り%",
    "資本利益率%", "魔法の公式順位", "F", "F満点", "1年騰落%", "RI余地%",
]  # fmt: skip


def tag(r: S.Row) -> str:
    q = r["F満点"] >= 5 and r["F"] >= r["F満点"] - 2
    mf = r.get("魔法の公式順位")
    t = []
    if not r["fin"] and mf and mf <= 50 and q:
        t.append("割安×質 上位50")
    if not r["fin"] and mf and mf <= 100 and q and (r.get("1年騰落%") or -1) > 0:
        t.append("中期候補")
    return "・".join(t)


def build(cfg: Config, today: dt.date) -> list[S.Row]:
    rows = S.screen(str(today), str(today - dt.timedelta(days=365)), str(today - dt.timedelta(days=30)), cfg=cfg)
    for r in rows:
        r["判定"] = tag(r)
    rows.sort(key=lambda r: r.get("魔法の公式順位") or 9999)
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
