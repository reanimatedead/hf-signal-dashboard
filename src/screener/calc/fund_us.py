"""米国株: EDGAR companyfacts（dict）と株価（dict）から、その時点で入手できた決算だけで指標を計算する。
ファイルは読まない。呼ぶ側が facts / 株価を1社ずつ渡す（全部を一度にメモリに載せない）。"""
import bisect
import datetime as dt

from .value import FScore, RI, magic_rank, ri_ratio

TAGS = {
    "ni": ["NetIncomeLoss", "ProfitLoss"],
    "eq": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "ebit": ["OperatingIncomeLoss"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "ta": ["Assets"], "ca": ["AssetsCurrent"], "cl": ["LiabilitiesCurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "ltd": ["LongTermDebtNoncurrent", "LongTermDebt"], "std": ["LongTermDebtCurrent", "DebtCurrent"],
    "ppe": ["PropertyPlantAndEquipmentNet"],
    "rev": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "gp": ["GrossProfit"],
    "dsh": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}
CORE_TAGS = ("NetIncomeLoss", "StockholdersEquity", "Assets")  # 契約テストで「取れること」を確かめるタグ
FIN_SECTORS = ("Financial", "Real Estate", "Utilities")
STALE_DAYS = 550  # 決算が18か月超古いものは除外


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
    ts = [dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime("%Y-%m-%d") for x in r["timestamp"]]
    q = r["indicators"]["quote"][0]
    a = (r["indicators"].get("adjclose") or [{"adjclose": q["close"]}])[0]["adjclose"]
    sp = sorted((dt.datetime.fromtimestamp(int(k), dt.timezone.utc).strftime("%Y-%m-%d"), v["numerator"] / v["denominator"])
                for k, v in (r.get("events", {}) or {}).get("splits", {}).items())
    return {"d": ts, "c": q["close"], "a": a, "h": q.get("high"), "l": q.get("low"), "splits": sp}


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


def split_adjust(sh, shd, splits):
    """株数を今の分割基準にそろえる（株価は Yahoo の分割調整後なので）。"""
    for sd, rr in splits:
        if sd > shd:
            sh *= rr
    return sh


def fundamentals(F, asof, splits=()):
    """価格を使わない部分（週1回計算して保存できる）。足りなければ None。"""
    g = {k: annual(F, v, asof, "shares" if k == "dsh" else "USD") for k, v in TAGS.items()}
    ni, ni0, fy = g["ni"]; eq, eq0, _ = g["eq"]
    sh, shd = shares(F, asof)
    if not sh:
        sh, shd = g["dsh"][0], g["dsh"][2]
    if sh and shd:
        sh = split_adjust(sh, shd, splits)
    if ni is None or not eq or not sh or fy is None:
        return None
    if (dt.date.fromisoformat(asof) - dt.date.fromisoformat(fy)).days > STALE_DAYS:
        return None
    ta, ta0, _ = g["ta"]; cfo = g["cfo"][0]; rev, rev0, _ = g["rev"]; gp, gp0, _ = g["gp"]; ltd, ltd0, _ = g["ltd"]
    fs = FScore()
    fs.chk(ni > 0); fs.chk(cfo > 0 if cfo is not None else None); fs.chk(cfo > ni if cfo is not None else None)
    fs.chk(ni / ta > ni0 / ta0 if all([ta, ta0]) and ni0 is not None else None)
    fs.chk(ltd / ta < ltd0 / ta0 if all([ltd is not None, ltd0, ta, ta0]) else None)
    fs.chk(gp / rev > gp0 / rev0 if all([gp, rev, gp0, rev0]) else None)
    fs.chk(rev / ta > rev0 / ta0 if all([rev, ta, rev0, ta0]) else None)
    roe = ni / ((eq + (eq0 or eq)) / 2) if eq > 0 else None
    debt = (g["ltd"][0] or 0) + (g["std"][0] or 0)
    cap = ((g["ca"][0] or 0) - (g["cl"][0] or 0)) + (g["ppe"][0] or 0)
    return {"fy": fy, "ni": ni, "eq": eq, "ebit": g["ebit"][0], "sh": sh, "debt": debt,
            "cash": g["cash"][0] or 0, "cap": cap, "roe": roe, "f_score": fs.score, "f_max": fs.max}


def metrics(fd, px):
    """価格を入れて毎日計算する部分。"""
    mcap = px * fd["sh"]
    ev = mcap + fd["debt"] - fd["cash"]
    ni, eq, ebit, cap, roe = fd["ni"], fd["eq"], fd["ebit"], fd["cap"], fd["roe"]
    tpbr = ri_ratio(roe, RI) if roe is not None else None
    pbr = mcap / eq if eq > 0 else None
    return {"mcap_bn": round(mcap / 1e9, 1),
            "PER": round(mcap / ni, 1) if ni > 0 else None, "PBR": round(pbr, 2) if pbr else None,
            "ROE%": round(100 * roe, 1) if roe is not None else None,
            "RI余地%": round(100 * (tpbr / pbr - 1), 1) if tpbr and pbr else None,
            "益回り%": round(100 * ebit / ev, 1) if ebit and ev > 0 else None,
            "資本利益率%": round(100 * ebit / cap, 1) if ebit and cap > 0 else None}


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
    r = {"ticker": ticker, "name": info.get("name", ticker), "sector": info.get("sector", ""),
         "idx": "/".join(info.get("idx", [])), "fy": fd["fy"], "price": round(px, 2),
         **metrics(fd, px), "F": fd["f_score"], "F満点": fd["f_max"], "fin": is_fin(info.get("sector"))}
    if p1y and p1m:
        a, b = price_at(p, p1y, True), price_at(p, p1m, True)
        r["1年騰落%"] = round(100 * (b / a - 1), 1) if a and b else None
    return r


def rank(rows):
    """魔法の公式の順位（金融・不動産・公益は除く）。"""
    return magic_rank(rows, "益回り%", "資本利益率%", skip=lambda r: r.get("fin"), out_key="魔法の公式順位")
