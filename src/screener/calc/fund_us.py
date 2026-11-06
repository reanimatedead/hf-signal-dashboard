"""米国株: EDGAR companyfacts（dict）と株価（dict）から、その時点で入手できた決算だけで指標を計算する。
ファイルは読まない。呼ぶ側が facts / 株価を1社ずつ渡す（全部を一度にメモリに載せない）。"""

import bisect
import datetime as dt
import math

from .value import RI, FScore, magic_rank, one_off_flag, ri_ratio

TAGS = {
    "ni": ["NetIncomeLoss", "ProfitLoss"],
    "eq": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "ebit": ["OperatingIncomeLoss"],
    "cfo": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "ta": ["Assets"],
    "ca": ["AssetsCurrent"],
    "cl": ["LiabilitiesCurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "ltd": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "std": ["LongTermDebtCurrent", "DebtCurrent"],
    "ppe": ["PropertyPlantAndEquipmentNet"],
    "rev": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
    "gp": ["GrossProfit"],
    "dsh": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "div": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
}
FILED_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A")
FILED_TAGS = ("NetIncomeLoss", "Assets", "StockholdersEquity")
FILED_KEEP = 12  # 次の決算の推定（calc.score.next_earnings）に使う直近の提出日の数
CORE_TAGS = ("NetIncomeLoss", "StockholdersEquity", "Assets")  # 契約テストで「取れること」を確かめるタグ
FIN_SECTORS = ("Financial", "Real Estate", "Utilities")
STALE_DAYS = 550  # 決算が18か月超古いものは除外
# 株数（表紙の dei:EntityCommonStockSharesOutstanding）の確かめ。複数クラス株の会社は表紙の株数が
# 何年も更新されない・1クラス分だけになることがある（MA は 2010 年、FOX は 1 株）。
# そのときは希薄化後の加重平均株数を使う。
SHARES_STALE_DAYS = 400  # 表紙の株数が asof より 400 日超古い
SHARES_MIN = 100_000  # これより少ない株数は誤り（FOX の表紙は 1 株）
SHARES_MAX_RATIO = 1.5  # 表紙の株数と直近の希薄化後株数（分割調整後）が 1.5 倍超ずれる


def annual(F, tags, asof, unit="USD"):
    """10-K の通期値（最新, 前期, 最新期末日）。asof より前に提出されたものだけ使う。"""
    best = {}
    for tg in tags:
        x = F.get("us-gaap", {}).get(tg, {}).get("units", {}).get(unit)
        if not x:
            continue
        out = {}
        for v in x:
            if v.get("form") not in ("10-K", "10-K/A") or v.get("fp") != "FY" or v.get("filed", "9999") >= asof:
                continue
            if "start" in v:
                m = (int(v["end"][:4]) - int(v["start"][:4])) * 12 + int(v["end"][5:7]) - int(v["start"][5:7])
                if not 11 <= m <= 13:
                    continue
            out[v["end"]] = v["val"]
        if out and (not best or max(out) > max(best)):
            best = out
    k = sorted(best)
    return (best[k[-1]] if k else None), (best[k[-2]] if len(k) > 1 else None), (k[-1] if k else None)


def parse_yahoo_chart(j):
    """Yahoo chart API の JSON → {"d","c","a","h","l","splits"}。"""
    r = j["chart"]["result"][0]
    ts = [dt.datetime.fromtimestamp(x, dt.UTC).strftime("%Y-%m-%d") for x in r["timestamp"]]
    q = r["indicators"]["quote"][0]
    a = (r["indicators"].get("adjclose") or [{"adjclose": q["close"]}])[0]["adjclose"]
    sp = sorted(
        (dt.datetime.fromtimestamp(int(k), dt.UTC).strftime("%Y-%m-%d"), v["numerator"] / v["denominator"])
        for k, v in (r.get("events", {}) or {}).get("splits", {}).items()
    )
    return {"d": ts, "c": q["close"], "a": a, "h": q.get("high"), "l": q.get("low"), "v": q.get("volume"), "splits": sp}


def price_at(p, d, adj=False, raw=False):
    i = bisect.bisect_right(p["d"], d) - 1
    while i >= 0 and p["c"][i] is None:
        i -= 1
    if i < 0:
        return None
    if adj:
        return p["a"][i]
    if raw:
        return p["c"][i]
    f = 1.0
    for sd, r in p["splits"]:
        if sd > p["d"][i]:
            f *= r
    return p["c"][i] * f


def shares(F, asof):
    x = F.get("dei", {}).get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
    x = [v for v in x if v.get("filed", "9999") < asof]
    if x:
        last = max(x, key=lambda v: (v["filed"], v["end"]))
        return sum(v["val"] for v in x if v["filed"] == last["filed"]), last["end"]  # 複数クラス株は合計
    return None, None


def latest_dsh(F, asof):
    """直近の希薄化後の加重平均株数（10-K / 10-Q のうち期末が最も新しいもの）→ (株数, 期末日)。"""
    g = F.get("us-gaap", {}).get("WeightedAverageNumberOfDilutedSharesOutstanding", {})
    x = g.get("units", {}).get("shares", [])
    x = [v for v in x if v.get("filed", "9999") < asof and v.get("form") in FILED_FORMS and v.get("val")]
    if not x:
        return None, None
    v = max(x, key=lambda v: (v["end"], v["filed"]))
    return v["val"], v["end"]


def implied_shares(F, asof, splits=()):
    """純利益 ÷ 希薄化後 EPS（直近の通期）→ 株数の目安（今の分割基準）。単位の違う値に左右されない物差し。"""
    ni, _n0, fy = annual(F, TAGS["ni"][:1], asof)
    eps, _e0, efy = annual(F, ["EarningsPerShareDiluted", "EarningsPerShareBasic"], asof, "USD/shares")
    if not ni or not eps or fy is None or efy != fy or abs(eps) < 0.01:
        return None
    v = ni / eps
    return split_adjust(v, fy, splits) if v > 0 else None


def pick_shares(F, asof, splits=()):
    """使う株数（今の分割基準）→ (株数, 出どころ "dei"|"dsh"|None)。
    候補は表紙の株数（dei）と直近の希薄化後の加重平均株数（dsh）。どちらかが単位違い・古い・1クラス分だけのことがある
    （MA は表紙が 2010 年のまま、FOX は表紙が 1 株、MCD・WAT は dsh が百万単位や 1000 倍）。
    1) 純利益 ÷ 希薄化後 EPS（implied_shares）があれば、それに近い方
    2) 無ければ表紙の株数。ただし表紙が 400 日超古い・10 万株未満なら dsh。
       dsh と 100 倍超ずれるなら dsh の単位違いとみなし表紙、1.5 倍超ずれるなら dsh"""
    sh, shd = shares(F, asof)
    dv, dend = latest_dsh(F, asof)
    a = split_adjust(sh, shd, splits) if sh and shd else None
    b = split_adjust(dv, dend, splits) if dv and dend else None
    if not (a and b):
        return (a, "dei") if a else (b, "dsh") if b else (None, None)
    c = implied_shares(F, asof, splits)
    if c:
        return (a, "dei") if abs(math.log(a / c)) <= abs(math.log(b / c)) else (b, "dsh")
    stale = (dt.date.fromisoformat(asof) - dt.date.fromisoformat(shd)).days > SHARES_STALE_DAYS
    if (stale or a < SHARES_MIN) and b >= SHARES_MIN:
        return b, "dsh"
    r = a / b
    if not (1 / 100 <= r <= 100):  # dsh の単位違い（百万単位・1000 倍）
        return a, "dei"
    if not (1 / SHARES_MAX_RATIO <= r <= SHARES_MAX_RATIO):
        return b, "dsh"
    return a, "dei"


def split_adjust(sh, shd, splits):
    """株数を今の分割基準にそろえる（株価は Yahoo の分割調整後なので）。"""
    for sd, rr in splits:
        if sd > shd:
            sh *= rr
    return sh


def filed_dates(F, asof):
    """10-K / 10-Q の提出日（asof より前・新しい順に FILED_KEEP 件・昇順で返す）。次の決算の推定に使う。"""
    ds = set()
    for tg in FILED_TAGS:
        for unit in (F.get("us-gaap", {}).get(tg, {}).get("units", {}) or {}).values():
            for v in unit:
                f = v.get("filed")
                if f and f < asof and v.get("form") in FILED_FORMS:
                    ds.add(f)
    return sorted(ds)[-FILED_KEEP:]


def fundamentals(F, asof, splits=()):
    """価格を使わない部分（週1回計算して保存できる）。足りなければ None。"""
    g = {k: annual(F, v, asof, "shares" if k == "dsh" else "USD") for k, v in TAGS.items()}
    ni, ni0, fy = g["ni"]
    eq, eq0, _ = g["eq"]
    sh, _src = pick_shares(F, asof, splits)
    if not sh and g["dsh"][0] and g["dsh"][2]:
        sh = split_adjust(g["dsh"][0], g["dsh"][2], splits)
    if ni is None or not eq or not sh or fy is None:
        return None
    if (dt.date.fromisoformat(asof) - dt.date.fromisoformat(fy)).days > STALE_DAYS:
        return None
    ta, ta0, _ = g["ta"]
    cfo = g["cfo"][0]
    rev, rev0, _ = g["rev"]
    gp, gp0, _ = g["gp"]
    ltd, ltd0, _ = g["ltd"]
    fs = FScore()
    fs.chk(ni > 0)
    fs.chk(cfo > 0 if cfo is not None else None)
    fs.chk(cfo > ni if cfo is not None else None)
    fs.chk(ni / ta > ni0 / ta0 if all([ta, ta0]) and ni0 is not None else None)
    fs.chk(ltd / ta < ltd0 / ta0 if all([ltd is not None, ltd0, ta, ta0]) else None)
    fs.chk(gp / rev > gp0 / rev0 if all([gp, rev, gp0, rev0]) else None)
    fs.chk(rev / ta > rev0 / ta0 if all([rev, ta, rev0, ta0]) else None)
    roe = ni / ((eq + (eq0 or eq)) / 2) if eq > 0 else None
    debt = (g["ltd"][0] or 0) + (g["std"][0] or 0)
    cap = ((g["ca"][0] or 0) - (g["cl"][0] or 0)) + (g["ppe"][0] or 0)
    return {
        "fy": fy,
        "ni": ni,
        "eq": eq,
        "ebit": g["ebit"][0],
        "sh": sh,
        "debt": debt,
        "cash": g["cash"][0] or 0,
        "cap": cap,
        "roe": roe,
        "f_score": fs.score,
        "f_max": fs.max,
        "ta": ta,
        "div": g["div"][0],
        "one_off": one_off_flag(net_income=ni, op_income=g["ebit"][0])["flag"],
        "filed": filed_dates(F, asof),
    }


def value_inputs(ni, eq, sh, roe, px):
    """(上値余地%, PBR, PER)（丸めなし）。metrics と 売買スコアの検証（月初ごと）の両方がこれを使う。"""
    mcap = px * sh
    pbr = mcap / eq if eq and eq > 0 else None
    tpbr = ri_ratio(roe, RI) if roe is not None else None
    up = 100 * (tpbr / pbr - 1) if tpbr and pbr else None
    per = mcap / ni if ni and ni > 0 else None
    return up, pbr, per


def metrics(fd, px):
    """価格を入れて毎日計算する部分。"""
    mcap = px * fd["sh"]
    ev = mcap + fd["debt"] - fd["cash"]
    ni, eq, ebit, cap, roe = fd["ni"], fd["eq"], fd["ebit"], fd["cap"], fd["roe"]
    tpbr = ri_ratio(roe, RI) if roe is not None else None
    up, pbr, per = value_inputs(ni, eq, fd["sh"], roe, px)
    return {
        "mcap_bn": round(mcap / 1e9, 1),
        "PER": round(per, 1) if per is not None else None,
        "PBR": round(pbr, 2) if pbr else None,
        "roe_pct": round(100 * roe, 1) if roe is not None else None,
        "ri_upside_pct": round(up, 1) if up is not None else None,
        "earnings_yield_pct": round(100 * ebit / ev, 1) if ebit and ev > 0 else None,
        "roc_pct": round(100 * ebit / cap, 1) if ebit and cap > 0 else None,
        # 2026-11 追加（売買スコア・公開の米国株の列）。古い us_fundamentals.json に無い項目は None。
        "equity_ratio_pct": round(100 * eq / fd["ta"], 1) if fd.get("ta") and eq > 0 else None,
        "div_yield_pct": round(100 * abs(fd["div"]) / mcap, 2) if fd.get("div") and mcap > 0 else None,
        "fair_price": round(px * tpbr / pbr, 2) if tpbr and pbr else None,
    }


def is_fin(sector):
    return any(x in (sector or "") for x in FIN_SECTORS)


def screen_one(ticker, info, F, p, asof, p1y=None, p1m=None):
    """1社分の行（screen_us.py と同じ列）。足りなければ None。"""
    if not F or not p:
        return None
    fd = fundamentals(F, asof, p["splits"])
    px = price_at(p, asof, raw=True)
    if not fd or not px:
        return None
    r = {
        "ticker": ticker,
        "name": info.get("name", ticker),
        "sector": info.get("sector", ""),
        "idx": "/".join(info.get("idx", [])),
        "fy": fd["fy"],
        "price": round(px, 2),
        **metrics(fd, px),
        "F": fd["f_score"],
        "f_max": fd["f_max"],
        "fin": is_fin(info.get("sector")),
        "one_off_flag": bool(fd.get("one_off")),
        "filed": fd.get("filed") or [],
    }
    if p1y and p1m:
        a, b = price_at(p, p1y, True), price_at(p, p1m, True)
        r["ret_1y_pct"] = round(100 * (b / a - 1), 1) if a and b else None
    return r


def rank(rows):
    """魔法の公式の順位（金融・不動産・公益は除く）。"""
    return magic_rank(rows, "earnings_yield_pct", "roc_pct", skip=lambda r: r.get("fin"), out_key="magic_rank")
