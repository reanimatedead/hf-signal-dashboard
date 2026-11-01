"""日本株 全銘柄: 理論株価（残余利益モデル）＋質（F）＋魔法の公式＋一時利益の目印。

式（理論PBR・F の数え方・魔法の公式・一時利益の目印）は screener.calc.value にだけある。
ここはデータの読み込みと列づくり。一時利益の目印が立った行は「決算短信で確認」と書く。
"""

from __future__ import annotations

import collections
import json
from pathlib import Path
from typing import Any

from ..calc.value import RI, FScore, magic_rank, one_off_flag, ri_ratio
from ..config import Config

FIN = {"7050", "7100", "7150", "7200"}  # 銀行・証券・保険・その他金融（指標の意味が違う）
MARKETS = ("プライム", "スタンダード", "グロース")
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
                "コード": code[:4],
                "会社名": m["CoName"],
                "市場": m["MktNm"],
                "業種": m["S33Nm"],
                "規模": m.get("ScaleCat", ""),
                "金融": "○" if m.get("S33") in FIN else "",
                "決算期": ks[-1],
                "株価": px,
                "理論株価": round(fair) if fair else None,
                "上値余地%": round(100 * (fair / px - 1), 1) if fair else None,
                "PBR": round(pbr, 2),
                "理論PBR": _r(tpbr, 2) if tpbr else None,
                "予想PER": round(mcap / fnp, 1) if fnp and fnp > 0 else None,
                "実績ROE%": _r(100 * roe_act, 1) if roe_act is not None else None,
                "予想ROE%": _r(100 * roe_fwd, 1) if roe_fwd is not None else None,
                "益回り%(営業利益/時価)": round(100 * op / mcap, 1) if op and mcap else None,
                "総資産利益率%(営業)": round(100 * op / ta, 1) if op and ta else None,
                "自己資本比率%": round(100 * eqar, 1) if eqar else None,
                "予想配当利回り%": round(100 * div / px, 2) if div else None,
                "F": fs.score,
                "F満点": fs.max,
                "1年騰落%(直近1か月除く)": round(100 * (p1m / p1y - 1), 1) if p1y and p1m else None,
                "時価総額(億円)": round(mcap / 1e8),
                "one_off_flag": oo["flag"],
                "一時利益の目印": oo["note"],
                "一時利益の理由": "・".join(oo["reasons"]),
            }
        )
    magic_rank(
        rows, "益回り%(営業利益/時価)", "総資産利益率%(営業)", skip=lambda r: bool(r["金融"]), out_key="魔法の公式順位"
    )
    for r in rows:
        r["判定"] = tag(r)
    return rows


def quality_ok(r: Row) -> bool:
    return bool(r["F満点"] >= 6 and r["F"] >= r["F満点"] - 2)


def tag(r: Row) -> str:
    t = []
    ok_q = quality_ok(r)
    big = (r["時価総額(億円)"] or 0) >= 300
    if (
        ok_q
        and (r["予想ROE%"] or 0) >= 8
        and (r["上値余地%"] or -99) >= 20
        and (r["自己資本比率%"] or 0) >= 40
        and big
        and not r["金融"]
    ):
        t.append("長期候補")
    if (r.get("魔法の公式順位") or 9999) <= 300 and (r["1年騰落%(直近1か月除く)"] or -99) > 0 and ok_q and big:
        t.append("中期候補")
    if (r["上値余地%"] or 0) >= 50 and (r["F"] <= 3 or (r["予想ROE%"] or 0) < 3):
        t.append("割安だが質に注意")
    return "・".join(t)
