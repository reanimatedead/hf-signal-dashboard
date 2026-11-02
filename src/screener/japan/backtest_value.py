"""財務判定（理論株価の余地）の検証（日本株・ローカルだけ）。

  yearly:     財務判定（長期候補・中期候補など）と余地の5分位を 1年後の騰落で比べる（期間は手元の bars_ から1年刻み）
  with_chart: 割安度（余地の5分の1）× チャート判定 の組み合わせを 20営業日後で比べる（months.json の各月初で評価）。
              割安5分の1 と チャート判定の規則は画面と同じ関数（screen.monthly_valuation / ind.day_labels）を呼ぶ
出力: <data_dir>/out/verify/YYYY-MM/backtest_value.json（リポジトリには書かない）
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from typing import Any

import numpy as np

from .. import config as config_mod
from ..calc import ind
from ..config import Config
from ..dates import files_dates, on_or_before, yearly_windows
from ..local_report import dump_json, verify_dir
from . import screen
from .backtest_tech import universe
from .panel import load_panel


def _px(cfg: Config, d: str) -> dict[str, Any]:
    with open(cfg.jp(f"bars_{d}.json")) as fh:
        return {b["Code"][:4]: b.get("AdjC") for b in json.load(fh)}


def _master_for(cfg: Config, d: str) -> str | None:
    m = on_or_before(files_dates(cfg.jp("master_*.json")), d)
    return str(cfg.jp(f"master_{m}.json")) if m else None


def _g(sel: list[screen.Row], base: float | None = None) -> dict[str, Any]:
    v = [r["fwd"] for r in sel if r["fwd"] is not None]
    out: dict[str, Any] = {
        "n": len(v),
        "gone": sum(r["fwd"] is None for r in sel),
        "mean_pct": round(statistics.mean(v), 1) if v else None,
        "median_pct": round(statistics.median(v), 1) if v else None,
    }
    if v and base is not None:
        out["win_rate_vs_base_pct"] = round(100 * sum(x > base for x in v) / len(v))
    return out


def yearly(cfg: Config, n: int = 3) -> dict[str, Any]:
    res: dict[str, Any] = {}
    for t0, p1y, p1m, t1 in yearly_windows(files_dates(cfg.jp("bars_*.json")), n):
        mp = _master_for(cfg, t0)
        if not mp:
            continue
        rows = screen.screen(t0, t0, p1y, p1m, mp, cfg=cfg)
        a, b = _px(cfg, t0), _px(cfg, t1)
        for r in rows:
            c = r["code"]
            r["fwd"] = (b[c] / a[c] - 1) * 100 if a.get(c) and b.get(c) else None
        U = [r for r in rows if not r["financial"] and (r["mcap_oku_jpy"] or 0) >= 300]
        base = _g(U)["mean_pct"]
        out = {"all_300oku_ex_fin": _g(U, base)}
        for t in ("long_candidate", "mid_candidate", "cheap_low_quality"):
            out[t] = _g([r for r in rows if t in r["fin_tag"]], base)
        q = sorted([r for r in U if r["upside_pct"] is not None], key=lambda r: r["upside_pct"])
        nq = len(q)
        for i in range(5):
            out[f"upside_q{i + 1}"] = _g(  # 余地の5分位（1=低→5=高）
                q[i * nq // 5 : (i + 1) * nq // 5], base
            )
        res[t0] = {"t1": t1, **out}
    return res


def _st(v: list[float]) -> dict[str, Any] | None:
    a = np.array(v)
    if not len(a):
        return None
    return {
        "n": int(len(a)),
        "mean_pct": round(float(a.mean()), 2),
        "median_pct": round(float(np.median(a)), 2),
        "up_ratio_pct": round(float((a > 0).mean() * 100), 1),
    }


def with_chart(cfg: Config, min_bars: int = 420, min_mcap: float = 300e8) -> dict[str, Any]:
    """割安度（月初の 割安5分の1）× チャート判定 を 20営業日後で比べる。
    割安度は screen.monthly_valuation（画面の A と同じ母集団・同じ線）、チャート判定は ind.day_labels（画面と同じ規則:
    長期の売られすぎが売りと同じ日は売り）。ここに規則は書かない。min_mcap はチャートを読む銘柄の範囲だけに使う。"""
    mv = screen.monthly_valuation(cfg)
    vm = sorted(mv)
    lt_sets = {d: set(v["long_candidate"]) for d, v in mv.items()}
    dates, panel = load_panel(cfg, universe(cfg, min_mcap))
    R: dict[tuple[str, str], list[float]] = collections.defaultdict(list)
    for c, (h, low, cl) in panel.items():
        if np.sum(~np.isnan(cl)) < min_bars:
            continue
        di = [d for d, o in zip(dates, ~np.isnan(cl), strict=False) if o]
        x = ind.compute(h, low, cl)
        lc = ind.label_conditions(x)
        buy = lc[ind.LABELS[2]] | lc[ind.LABELS[1]]
        lo_ = lc[ind.LONG_OVERSOLD_LABEL]
        either = ind.buy_type_days(x)
        C = x["c"]
        last: dict[tuple[str, str], int] = collections.defaultdict(lambda: -99)
        for i in range(int(ind.P["bb_long"]), len(C) - 20):
            m = screen.month_at(vm, di[i])
            if m is None:
                continue
            grp = mv[m]["quintile"].get(c)
            if not grp:
                continue
            fw = (C[i + 20] / C[i] - 1) * 100
            lt = c in lt_sets[m]
            R[("base", grp)].append(fw)
            for name, cond in (("buy", buy[i]), ("long_oversold", lo_[i]), ("either", either[i])):
                if not cond:
                    continue
                for g in (grp, "all") + (("long_candidate",) if lt else ()):
                    key = (name, g)
                    if i - last[key] < 20:
                        continue
                    last[key] = i
                    R[key].append(fw)
    period = [dates[min(int(ind.P["bb_long"]), len(dates) - 1)], dates[-1]] if dates else None
    return {"res": {f"{a}|{b}": _st(v) for (a, b), v in R.items()}, "period": period, "valuation_months": len(mv)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--min-bars", type=int, default=420)
    a = ap.parse_args(argv)
    cfg = config_mod.load()
    r = {"yearly": yearly(cfg), "with_chart": with_chart(cfg, a.min_bars)}
    p = verify_dir(cfg) / "backtest_value.json"
    dump_json(p, r)
    print("→", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
