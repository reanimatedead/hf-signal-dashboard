"""CCI/BB の売買判定を検証: シグナル後 10日・20日の値動き と 全期間の平均 を比べる（日本株・ローカルだけ）。

対象: 手元の最新 bars_/master_ で 時価総額300億以上・プライム/スタンダード・金融除く。
出力: <data_dir>/out/verify/YYYY-MM/backtest_tech.json（リポジトリには書かない）
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import numpy as np

from .. import config as config_mod
from ..calc import ind
from ..config import Config
from ..dates import files_dates, on_or_before
from ..local_report import dump_json, verify_dir
from .panel import load_panel
from .screen import FIN

NAMES = {
    "base": "全期間の平均（比べる基準）",
    "buy": "買い（長期上向き・-2σ・CCI48<-100）",
    "buy3": "強い買い（-3σ）",
    "sell": "売り（長期下向き・+2σ・CCI48>+100）",
    "sell3": "強い売り（+3σ）",
    "brk_up": "比較：順張り買い（上向き・+2σ超え）",
    "brk_dn": "比較：順張り売り（下向き・-2σ割れ）",
}
GAP = 20  # 同じ銘柄の連続シグナルは20日に1回だけ数える


def universe(cfg: Config, min_mcap: float = 300e8, markets: tuple[str, ...] = ("プライム", "スタンダード")) -> set[str]:
    bd = files_dates(cfg.jp("bars_*.json"))[-1]
    mds = files_dates(cfg.jp("master_*.json"))
    md = on_or_before(mds, bd) or mds[-1]
    with open(cfg.jp(f"bars_{bd}.json")) as fh:
        bars = json.load(fh)
    with open(cfg.jp(f"master_{md}.json")) as fh:
        master = {m["Code"][:4]: m for m in json.load(fh)}

    def ok(b: dict[str, Any]) -> bool:
        m = master.get(b["Code"][:4], {})
        return bool(
            (b.get("MktCap") or 0) * 1e6 >= min_mcap
            and m.get("MktNm") in markets
            and m.get("S33") not in FIN
            and m.get("S17") != "99"
        )

    return {b["Code"][:4] for b in bars if ok(b)}


def st(v: list[float]) -> dict[str, Any] | None:
    a = np.array(v)
    if not len(a):
        return None
    return {
        "n": int(len(a)),
        "平均%": round(float(a.mean()), 2),
        "中央値%": round(float(np.median(a)), 2),
        "上昇の割合%": round(float((a > 0).mean() * 100), 1),
    }


def run(cfg: Config, min_bars: int = 420, min_mcap: float = 300e8) -> dict[str, Any]:
    uni = universe(cfg, min_mcap)
    dates, panel = load_panel(cfg, uni)
    H = (10, 20)
    res: dict[str, dict[int, list[float]]] = {k: {h: [] for h in H} for k in NAMES}
    for h, low, cl in panel.values():
        if np.sum(~np.isnan(cl)) < min_bars:
            continue
        x = ind.compute(h, low, cl)
        s = ind.signals(x)
        C = x["c"]
        up = (x["cciL"] > 0) & (C >= x["mS"] + 2 * x["sS"])
        dn = (x["cciL"] < 0) & (C <= x["mS"] - 2 * x["sS"])
        last = {k: -999 for k in res}
        for i in range(int(ind.P["bb_long"]), len(C) - max(H)):
            fw = {hh: (C[i + hh] / C[i] - 1) * 100 for hh in H}
            for hh in H:
                res["base"][hh].append(fw[hh])
            tags = [
                t
                for t, c in (
                    ("buy", s[i] >= 1),
                    ("buy3", s[i] == 2),
                    ("sell", s[i] <= -1),
                    ("sell3", s[i] == -2),
                    ("brk_up", up[i]),
                    ("brk_dn", dn[i]),
                )
                if c
            ]
            for t in tags:
                if i - last[t] < GAP:
                    continue
                last[t] = i
                for hh in H:
                    res[t][hh].append(fw[hh])
    out = {k: {h: st(v) for h, v in d.items()} for k, d in res.items()}
    period = [dates[min(int(ind.P["bb_long"]), len(dates) - 1)], dates[-1]] if dates else None
    return {"names": NAMES, "res": out, "period": period, "stocks": len(panel)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--min-bars", type=int, default=420)
    ap.add_argument("--min-mcap", type=float, default=300e8)
    a = ap.parse_args(argv)
    cfg = config_mod.load()
    r = run(cfg, a.min_bars, a.min_mcap)
    p = verify_dir(cfg) / "backtest_tech.json"
    dump_json(p, r)
    print("銘柄", r["stocks"], "期間", r["period"], "→", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
