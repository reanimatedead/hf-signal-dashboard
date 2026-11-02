"""日本株 全銘柄: 理論株価（残余利益モデル）＋質（F）＋魔法の公式＋一時利益の目印。

式（理論PBR・F の数え方・魔法の公式・一時利益の目印）は screener.calc.value にだけある。
ここはデータの読み込みと列づくり（列名・値はコード。言葉は screener.labels）。
一時利益の目印が立った行は one_off_note = "check_earnings_release"（決算短信で確認）。
"""

from __future__ import annotations

import bisect
import collections
import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from ..calc.value import RI, FScore, magic_rank, one_off_flag, ri_ratio
from ..config import Config

FIN = {"7050", "7100", "7150", "7200"}  # 銀行・証券・保険・その他金融（指標の意味が違う）
MARKETS = ("プライム", "スタンダード", "グロース")
# 割安5分の1（総合判定 A の割安側。backtest_value.with_chart で検証した定義）
QUINTILE_MARKETS = ("プライム", "スタンダード")
QUINTILE_MIN_MCAP_OKU = 300
Row = dict[str, Any]


def f(x: Any) -> float | None:
    try:
        return float(x) if x not in ("", None) else None
    except (TypeError, ValueError):
        return None


def _load(p: str | Path) -> Any:
    with open(p) as fh:
        return json.load(fh)


def load_fy(cfg: Config, asof: str) -> dict[str, dict[str, Row]]:
    """通期決算を銘柄ごとに時系列で集める（連結を優先, asof より前の開示だけ）。"""
    fy: dict[str, dict[str, Row]] = collections.defaultdict(dict)
    for p in sorted(cfg.jp("fins").glob("*.json")):
        if p.name[:10] >= asof:  # ファイル名=開示日。asof 以降は読まない
            continue
        for r in _load(p):
            if r["DiscDate"] >= asof or not r["DocType"].startswith("FY"):
                continue
            key = r["CurFYEn"]
            cons = "NonConsolidated" not in r["DocType"]
            prev = fy[r["Code"]].get(key)
            if (
                prev is None
                or (cons and "NonConsolidated" in prev["DocType"])
                or (cons == ("NonConsolidated" not in prev["DocType"]) and r["DiscDate"] >= prev["DiscDate"])
            ):
                fy[r["Code"]][key] = r
    return fy


def _fscore(cur: Row, pre: Row | None) -> FScore:
    """F-score（決算短信で取れる8項目）。判定できない項目は数えない。"""
    np_, ta, cfo, sales, op = (f(cur.get(k)) for k in ("NP", "TA", "CFO", "Sales", "OP"))
    sh, eqar = f(cur.get("ShOutFY")), f(cur.get("EqAR"))
    fs = FScore()
    fs.chk(np_ > 0 if np_ is not None else None)
    fs.chk(cfo > 0 if cfo is not None else None)
    fs.chk(cfo > np_ if cfo is not None and np_ is not None else None)
    if pre:
        p_np, p_ta, p_sales, p_op, p_eqar, p_sh = (
            f(pre.get(k)) for k in ("NP", "TA", "Sales", "OP", "EqAR", "ShOutFY")
        )
        fs.chk(np_ / ta > p_np / p_ta if np_ is not None and ta and p_np is not None and p_ta else None)  # ROA改善
        fs.chk(eqar > p_eqar if eqar and p_eqar else None)  # 借金に頼らない度合い改善
        fs.chk(sh <= p_sh * 1.005 if sh and p_sh else None)  # 株を増やしていない
        fs.chk(
            op / sales > p_op / p_sales if op is not None and sales and p_op is not None and p_sales else None
        )  # 利益率改善
        fs.chk(sales / ta > p_sales / p_ta if sales and ta and p_sales and p_ta else None)  # 資産の回転改善
    return fs


def _r(x: float | None, nd: int) -> float | None:
    return round(x, nd) if x is not None else None


def screen(asof: str, px_d: str, p1y_d: str, p1m_d: str, master_path: str, cfg: Config) -> list[Row]:
    master = {m["Code"]: m for m in _load(master_path)}
    bars = {
        k: {b["Code"]: b for b in _load(cfg.jp(f"bars_{d}.json"))}
        for k, d in (("px", px_d), ("m1", p1m_d), ("y1", p1y_d))
    }
    fy = load_fy(cfg, asof)
    rows: list[Row] = []
    for code, m in master.items():
        if m.get("S17") == "99" or m.get("MktNm") not in MARKETS:
            continue
        hist = fy.get(code)
        b = bars["px"].get(code)
        if not hist or not b or not b.get("AdjC"):
            continue
        ks = sorted(hist)
        cur = hist[ks[-1]]
        pre = hist[ks[-2]] if len(ks) > 1 else None
        px = float(b["AdjC"])
        np_, eq, ta, op = (f(cur.get(k)) for k in ("NP", "Eq", "TA", "OP"))
        bps, feps, eps = f(cur.get("BPS")), f(cur.get("NxFEPS")), f(cur.get("EPS"))
        sh, tr = f(cur.get("ShOutFY")), f(cur.get("TrShFY")) or 0.0
        if (not bps) and eq and sh:
            bps = eq / (sh - tr)
        if not bps or bps <= 0:
            continue
        roe_fwd = feps / bps if feps is not None else (eps / bps if eps is not None else None)
        roe_act = f(cur.get("ROE")) or (np_ / eq if np_ and eq else None)
        mcap = float(b["MktCap"]) * 1e6 if b.get("MktCap") else None
        sheq = f(cur.get("ShEq")) or eq
        fnp = f(cur.get("NxFNp"))
        if not mcap or not sheq or sheq <= 0:
            continue
        pbr = mcap / sheq  # 分割の影響を受けないよう 時価総額÷自己資本
        tpbr = ri_ratio(roe_fwd, RI) if roe_fwd is not None else None  # 理論PBR
        fair = px * tpbr / pbr if tpbr else None
        fs = _fscore(cur, pre)
        p1y = bars["y1"].get(code, {}).get("AdjC")
        p1m = bars["m1"].get(code, {}).get("AdjC")
        div = f(cur.get("NxFDivAnn"))
        eqar = f(cur.get("EqAR"))
        oo = one_off_flag(net_income=np_, op_income=op, roe_fwd=roe_fwd, roe_act=roe_act)
        rows.append(
            {
                "code": code[:4],
                "company_name": m["CoName"],
                "market": m["MktNm"],
                "sector": m["S33Nm"],
                "scale": m.get("ScaleCat", ""),
                "financial": m.get("S33") in FIN,
                "fiscal_period": ks[-1],
                "price": px,
                "fair_price": round(fair) if fair else None,
                "upside_pct": round(100 * (fair / px - 1), 1) if fair else None,
                "PBR": round(pbr, 2),
                "fair_pbr": _r(tpbr, 2) if tpbr else None,
                "per_fwd": round(mcap / fnp, 1) if fnp and fnp > 0 else None,
                "roe_act_pct": _r(100 * roe_act, 1) if roe_act is not None else None,
                "roe_fwd_pct": _r(100 * roe_fwd, 1) if roe_fwd is not None else None,
                "earnings_yield_pct": round(100 * op / mcap, 1) if op and mcap else None,
                "roa_op_pct": round(100 * op / ta, 1) if op and ta else None,
                "equity_ratio_pct": round(100 * eqar, 1) if eqar else None,
                "div_yield_fwd_pct": round(100 * div / px, 2) if div else None,
                "F": fs.score,
                "f_max": fs.max,
                "ret_1y_ex1m_pct": round(100 * (p1m / p1y - 1), 1) if p1y and p1m else None,
                "mcap_oku_jpy": round(mcap / 1e8),
                "one_off_flag": oo["flag"],
                "one_off_note": oo["note"],
                "one_off_reasons": "|".join(oo["reasons"]),
            }
        )
    magic_rank(rows, "earnings_yield_pct", "roa_op_pct", skip=lambda r: bool(r["financial"]), out_key="magic_rank")
    for r in rows:
        r["fin_tag"] = tag(r)
    return rows


def quality_ok(r: Row) -> bool:
    return bool(r["f_max"] >= 6 and r["F"] >= r["f_max"] - 2)


def tag(r: Row) -> str:
    t = []
    ok_q = quality_ok(r)
    big = (r["mcap_oku_jpy"] or 0) >= 300
    if (
        ok_q
        and (r["roe_fwd_pct"] or 0) >= 8
        and (r["upside_pct"] or -99) >= 20
        and (r["equity_ratio_pct"] or 0) >= 40
        and big
        and not r["financial"]
    ):
        t.append("long_candidate")
    if (r.get("magic_rank") or 9999) <= 300 and (r["ret_1y_ex1m_pct"] or -99) > 0 and ok_q and big:
        t.append("mid_candidate")
    if (r["upside_pct"] or 0) >= 50 and (r["F"] <= 3 or (r["roe_fwd_pct"] or 0) < 3):
        t.append("cheap_low_quality")
    return "|".join(t)


def quintile_universe(rows: list[Row]) -> list[Row]:
    """割安5分の1を決める母集団: プライム・スタンダード / 金融を除く / 時価総額300億円以上 / 上値余地あり。"""
    return [
        r
        for r in rows
        if r.get("market") in QUINTILE_MARKETS
        and not r["financial"]
        and (r["mcap_oku_jpy"] or 0) >= QUINTILE_MIN_MCAP_OKU
        and r["upside_pct"] is not None
    ]


def cheap_bounds(rows: list[Row]) -> tuple[float, float] | None:
    """(割高5分の1の上限, 割安5分の1の下限)。上値余地を小さい順に並べた 20% 点と 80% 点（with_chart と同じ取り方）。"""
    q = sorted(r["upside_pct"] for r in quintile_universe(rows))
    n = len(q)
    return (q[n // 5], q[4 * n // 5]) if n else None


def value_quintile(rows: list[Row]) -> dict[str, str]:
    """{code: cheap_quintile / middle / expensive_quintile}。母集団の外の銘柄は入らない。"""
    b = cheap_bounds(rows)
    if b is None:
        return {}
    lo, hi = b
    return {
        r["code"]: "cheap_quintile"
        if r["upside_pct"] >= hi
        else "expensive_quintile"
        if r["upside_pct"] <= lo
        else "middle"
        for r in quintile_universe(rows)
    }


VALUATION_CACHE = "valuation_v2"  # 定義を変えたら名前を変える（古い控えを使わない）


def monthly_valuation(cfg: Config) -> dict[str, dict[str, Any]]:
    """months.json の各月初の評価 {月初: {"quintile": {code: cheap_quintile/middle/expensive_quintile},
    "long_candidate": [code, ...]}}。画面の A の検証（signals）と backtest_value.with_chart の両方がこれを使う。
    過去の月初は変わらないので <data_dir>/japan/derived/ に控える（J-Quants 由来・ローカルだけ）。"""
    mp = cfg.jp("months.json")
    if not mp.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    cdir = cfg.jp("derived", VALUATION_CACHE)
    for d in _load(mp):
        cp = cdir / f"{d}.json"
        if cp.exists():
            out[d] = _load(cp)
            continue
        master = cfg.jp(f"master_{d}.json")
        if not master.exists() or not cfg.jp(f"bars_{d}.json").exists():
            continue
        rows = screen(d, d, d, d, str(master), cfg=cfg)
        vq = value_quintile(rows)
        out[d] = {"quintile": vq, "long_candidate": sorted(r["code"] for r in rows if "long_candidate" in r["fin_tag"])}
        cdir.mkdir(parents=True, exist_ok=True)
        tmp = cp.with_name(cp.name + ".tmp")
        tmp.write_text(json.dumps(out[d]))
        os.replace(tmp, cp)
    return out


def monthly_quintiles(cfg: Config) -> dict[str, dict[str, str]]:
    """{月初: {code: 割安度}}（monthly_valuation の quintile だけ）。"""
    return {d: v["quintile"] for d, v in monthly_valuation(cfg).items()}


def month_at(months: list[str], day: str) -> str | None:
    """その日以前で最も近い月初（months は昇順）。無ければ None。"""
    k = bisect.bisect_right(months, day) - 1
    return months[k] if k >= 0 else None


def cheap_days(code: str, ds: list[str], vq: dict[str, dict[str, str]]) -> np.ndarray:
    """各日がその日以前で最も近い月初の評価で 割安5分の1 か（bool 配列。評価の無い日は False）。"""
    vm = sorted(vq)
    out = np.zeros(len(ds), bool)
    for i, d in enumerate(ds):
        m = month_at(vm, d)
        out[i] = m is not None and vq[m].get(code) == "cheap_quintile"
    return out
