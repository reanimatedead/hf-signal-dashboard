"""米国株: EDGAR companyfacts（dict）と株価（dict）から、その時点で入手できた決算だけで指標を計算する。
ファイルは読まない。呼ぶ側が facts / 株価を1社ずつ渡す（全部を一度にメモリに載せない）。"""

import bisect
import datetime as dt
import math
import re

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
    ni, _n0, fy = annual(F, TAGS["ni"], asof)
    eps, _e0, efy = annual(F, ["EarningsPerShareDiluted", "EarningsPerShareBasic"], asof, "USD/shares")
    if not ni or not eps or fy is None or efy != fy or abs(eps) < 0.01:
        return None
    v = ni / eps
    return split_adjust(v, fy, splits) if v > 0 else None


def pick_shares_end(F, asof, splits=()):
    """使う株数（今の分割基準）→ (株数, 出どころ "dei"|"dsh"|None, その株数の期末日)。
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
        return (a, "dei", shd) if a else (b, "dsh", dend) if b else (None, None, None)
    c = implied_shares(F, asof, splits)
    if c:
        return (a, "dei", shd) if abs(math.log(a / c)) <= abs(math.log(b / c)) else (b, "dsh", dend)
    stale = (dt.date.fromisoformat(asof) - dt.date.fromisoformat(shd)).days > SHARES_STALE_DAYS
    if (stale or a < SHARES_MIN) and b >= SHARES_MIN:
        return b, "dsh", dend
    r = a / b
    if not (1 / 100 <= r <= 100):  # dsh の単位違い（百万単位・1000 倍）
        return a, "dei", shd
    if not (1 / SHARES_MAX_RATIO <= r <= SHARES_MAX_RATIO):
        return b, "dsh", dend
    return a, "dei", shd


def pick_shares(F, asof, splits=()):
    """使う株数（今の分割基準）→ (株数, 出どころ)。pick_shares_end の期末日なし版。"""
    sh, src, _end = pick_shares_end(F, asof, splits)
    return sh, src


def shares_mismatch(sh, implied, limit=None):
    """使う株数が「純利益 ÷ 希薄化後 EPS」と limit（既定 20%）を超えて食い違う。物差しが無ければ False。"""
    limit = VALUE_CHECK["sh_mismatch"] if limit is None else limit
    return bool(sh and implied) and abs(sh / implied - 1) > limit


def share_check(sh, ni, fy, F, asof, splits, sh_fix, needs_fix):
    """株数の照合 → None（合っている）| "shares_mismatch"（20% 超ずれる）| "shares_unverified"（物差しが無い）。"""
    if needs_fix and not sh_fix:
        return "shares_mismatch"
    eps = ((sh_fix[2] if len(sh_fix) > 2 else None) or {}).get(fy) if sh_fix else None
    implied = ni / eps if eps else implied_shares(F, asof, splits)
    if not implied or implied <= 0:
        return "shares_unverified"
    return "shares_mismatch" if shares_mismatch(sh, implied) else None


def split_adjust(sh, shd, splits):
    """株数を今の分割基準にそろえる（株価は Yahoo の分割調整後なので）。"""
    for sd, rr in splits:
        if sd > shd:
            sh *= rr
    return sh


# 株の種類の換算。companyfacts は種類ごとの株数を持たないので、10-Q / 10-K の本文（iXBRL）から読み、
# 上場している種類の株数に換算する（週次の tools/build_us_fundamentals.py）。提出書類で確かめた:
#   BRK-B: A 株 1 株 = B 株 1,500 株（配当・分配の権利が 1/1,500・転換も 1:1,500）。表紙の株数 × 定款の固定比率
#   ERIE:  B 株 1 株 = A 株 2,400 株（転換比率。希薄化後 EPS も同じ換算）。同上
#   HSY:   B 株 1 株 = 普通株 1 株（転換比率）。同上
#   V:     B-1〜B-3・C 株・優先株の転換比率が変わるので、会社が出す A 株換算の合計（as_converted）をそのまま読む
SHARE_CLASSES = {
    "BRK-B": {"us-gaap:CommonClassAMember": 1500, "us-gaap:CommonClassBMember": 1},
    "ERIE": {"us-gaap:CommonClassAMember": 1, "us-gaap:CommonClassBMember": 2400},
    "HSY": {"us-gaap:CommonStockMember": 1, "us-gaap:CommonClassBMember": 1},
    "V": {"as_converted": "v:SharesOutstandingAsConvertedBasis"},
}
# 照合に使う EPS（上場している種類の通期の値。companyfacts に無いので 10-K の本文から読む）。
# BRK は希薄化がなく基本 EPS だけ。
CLASS_EPS = {
    "BRK-B": ("us-gaap:EarningsPerShareBasic", "EquivalentClassBMember"),
    "ERIE": ("us-gaap:EarningsPerShareDiluted", "CommonClassAMember"),
    "HSY": ("us-gaap:EarningsPerShareDiluted", "CommonStockMember"),
    "V": ("us-gaap:EarningsPerShareDiluted", "CommonClassAMember"),
}
_IX_NUM = re.compile(r"<ix:nonFraction\b([^>]*)>(.*?)</ix:nonFraction>", re.S)


def _ix_facts(html, name):
    """iXBRL の数値 → [(値, [member], 日付)]。値が無い（— など）ものは飛ばす。"""
    out = []
    for m in _IX_NUM.finditer(html):
        attrs = m.group(1)
        if f'name="{name}"' not in attrs:
            continue
        ctx_id = re.search(r'contextRef="([^"]+)"', attrs)
        scale = re.search(r'scale="(-?\d+)"', attrs)
        num = re.sub(r"[^0-9.]", "", re.sub(r"<[^>]+>", "", m.group(2)))
        pat = rf'<xbrli:context id="{re.escape(ctx_id.group(1))}">(.*?)</xbrli:context>' if ctx_id else None
        ctx = pat and re.search(pat, html, re.S)
        if not ctx or not re.search(r"\d", num):
            continue
        body = ctx.group(1)
        dates = re.findall(r"<xbrli:(?:instant|endDate)>([^<]+)<", body)
        members = [x.strip() for x in re.findall(r"explicitMember[^>]*>([^<]+)<", body)]
        v = float(num) * 10 ** int(scale.group(1) if scale else 0)
        out.append((int(v) if v.is_integer() else v, members, max(dates, default="")))
    return out


def cover_class_shares(html):
    """10-Q / 10-K の本文（iXBRL）→ {株の種類の member: 表紙の株数}。"""
    return {ms[0]: v for v, ms, _d in _ix_facts(html, "dei:EntityCommonStockSharesOutstanding") if ms}


def class_equiv_shares(ticker, counts):
    """表紙の種類別の株数 → 上場している種類に換算した株数。対象外・種類が欠けていれば None。"""
    ratios = SHARE_CLASSES.get(ticker)
    if not ratios or not all(counts.get(k) for k in ratios):
        return None
    return sum(counts[k] * r for k, r in ratios.items())


def listed_class_shares(ticker, html):
    """本文（iXBRL）→ 上場している種類に換算した株数。読めなければ None。"""
    tag = (SHARE_CLASSES.get(ticker) or {}).get("as_converted")
    if tag:
        total = [(d, v) for v, ms, d in _ix_facts(html, tag) if not ms]  # 種類を指定しない値 = 合計
        return max(total)[1] if total else None
    return class_equiv_shares(ticker, cover_class_shares(html))


def class_eps(ticker, html):
    """10-K の本文（iXBRL）→ {決算期末: 上場している種類の EPS}。"""
    spec = CLASS_EPS.get(ticker)
    if not spec:
        return {}
    return {d: v for v, ms, d in _ix_facts(html, spec[0]) if ms and ms[0].endswith(spec[1]) and v}


def fix_at(sh_fix, m):
    """過去の月 m に使える換算株数。提出が m より後なら None（今の株数を過去に当てると先読みになる）。"""
    return sh_fix if sh_fix and sh_fix[1] < m else None


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


def fundamentals(F, asof, splits=(), sh_fix=None, needs_fix=False):
    """価格を使わない部分（週1回計算して保存できる）。足りなければ None。
    sh_fix = (株数, 日付, {決算期末: EPS}): 株の種類を換算した株数（SHARE_CLASSES）。
    あれば companyfacts の株数の代わりに使う。
    needs_fix: SHARE_CLASSES の銘柄。換算できなかった（sh_fix なし）ら株数を信用しない。"""
    g = {k: annual(F, v, asof, "shares" if k == "dsh" else "USD") for k, v in TAGS.items()}
    ni, ni0, fy = g["ni"]
    eq, eq0, _ = g["eq"]
    sh, _src, sh_end = pick_shares_end(F, asof, splits)
    if not sh and g["dsh"][0] and g["dsh"][2]:
        sh, sh_end = split_adjust(g["dsh"][0], g["dsh"][2], splits), g["dsh"][2]
    if sh_fix:
        sh, sh_end = sh_fix[:2]
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
        "sh_end": sh_end,
        "sh_check": share_check(sh, ni, fy, F, asof, splits, sh_fix, needs_fix),
    }


def value_inputs(ni, eq, sh, roe, px):
    """(残余利益モデルの上値余地%, PBR, PER)（丸めなし）。米国株の上値余地は業種別 PER の中央値で置き換える
    （公開は apply_relative、月初の検証は rerate_month）。残余利益の余地はここでだけ計算し、表示・点数には使わない。"""
    mcap = px * sh
    pbr = mcap / eq if eq and eq > 0 else None
    tpbr = ri_ratio(roe, RI) if roe is not None else None
    up = 100 * (tpbr / pbr - 1) if tpbr and pbr else None
    per = mcap / ni if ni and ni > 0 else None
    return up, pbr, per


# ── 米国株の理論株価（2026-11-06 から）─────────────────────────────────────────────
# 日本株の残余利益モデル（calc.value.ri_ratio: 割引率 8%・ROE 上限 40%・10 年で資本コストへ収束・純資産が起点）を
# そのまま米国株に当てると、自社株買いで純資産が小さく ROE が高い米国の大型株はほぼ全部が大きく割高に出る
# （2026-11-06 の公開データで上値余地の中央値 −66.9%、AAPL 理論株価 20）。
# 米国株は「同じ業種の黒字企業の PER の中央値」を基準にする: 理論株価 = EPS × 基準 PER、上値余地 = 基準 PER ÷ PER − 1。
# 業種は SEC の SIC コード（data/us_fundamentals.json の sic）の上 2 桁。黒字企業が group_min 社未満なら SIC の大分類、
# それも足りなければ全体の中央値。赤字（PER なし）は理論株価なし。
PER_LEVELS = ("sic2", "division", "all")
PER_BENCH = {"group_min": 8, "levels": PER_LEVELS}
SIC_DIVISIONS = (
    (1, 9, "A"), (10, 14, "B"), (15, 17, "C"), (20, 39, "D"), (40, 49, "E"),
    (50, 51, "F"), (52, 59, "G"), (60, 67, "H"), (70, 89, "I"), (90, 99, "J"),
)  # fmt: skip


def sic_keys(sic):
    """SIC コード → {"sic2": 上2桁, "division": 大分類, "all": "all"}。"""
    try:
        two = int(str(sic).strip()[:2])
    except (TypeError, ValueError):
        return {"sic2": None, "division": None, "all": "all"}
    div = next((d for lo, hi, d in SIC_DIVISIONS if lo <= two <= hi), None)
    return {"sic2": f"{two:02d}", "division": div, "all": "all"}


def per_benchmarks(pers, sics, p=PER_BENCH):
    """{銘柄: PER（丸めなし）}・{銘柄: SIC} → {銘柄: (基準 PER, 使った段 "sic2"|"division"|"all")}。
    黒字（PER>0）だけで中央値。"""
    import statistics

    keys = {t: sic_keys(sics.get(t)) for t in pers}
    pools = {}
    for t, v in pers.items():
        if v is None or not v >= VALUE_CHECK["per_min"]:  # 赤字と「要確認」（PER 2 未満）は中央値に入れない
            continue
        for lv in p["levels"]:
            k = keys[t][lv]
            if k is not None:
                pools.setdefault((lv, k), []).append(v)
    med = {k: statistics.median(v) for k, v in pools.items() if len(v) >= p["group_min"] or k[0] == "all"}
    out = {}
    for t in pers:
        for lv in p["levels"]:
            k = keys[t][lv]
            if k is not None and (lv, k) in med:
                out[t] = (med[(lv, k)], lv)
                break
    return out


# 値の確かめ。
# 理論株価・上値余地・PER・PBR を出さない（VALUE_HIDE）:
#   shares_mismatch    使う株数が「純利益 ÷ 希薄化後 EPS」と sh_mismatch（20%）を超えて食い違う
#   shares_unverified  その照合ができない（EPS が無い・決算期が合わない）
#   per_lt_2           PER が per_min 未満
# 値は出す（一時的な利益で PER が低く見えている可能性）:
#   upside_gt_150      上値余地が upside_soft% 超
# どれも売買スコアの割安の点は 0、順位の母集団からも外す。
VALUE_CHECK = {"per_min": 2.0, "upside_soft": 150.0, "sh_mismatch": 0.2}
VALUE_HIDE = ("shares_mismatch", "shares_unverified", "per_lt_2")


def value_check(per, up, p=VALUE_CHECK, sh_check=None):
    """→ None（問題なし）| "shares_mismatch" | "shares_unverified" | "per_lt_2" | "upside_gt_150"。"""
    if sh_check:
        return sh_check
    if per is not None and per < p["per_min"]:  # PER は黒字のときだけある（赤字は None）
        return "per_lt_2"
    if up is not None and up > p["upside_soft"]:
        return "upside_gt_150"
    return None


def per_upside(per, bench):
    """上値余地%（基準 PER ÷ PER − 1）。赤字・PER なしは None。"""
    return 100 * (bench / per - 1) if per and per > 0 and bench else None


def relative_value(per_px, sics, p=PER_BENCH, sh_checks=None):
    """{銘柄: (PER, 株価)} → {銘柄: {"upside_pct", "fair_price", "per_bench", "per_bench_level"}}。
    公開側・Mac mini とも同じ関数。"""
    bm = per_benchmarks({t: (None if (sh_checks or {}).get(t) else v[0]) for t, v in per_px.items()}, sics, p)
    out = {}
    for t, (per, px) in per_px.items():
        b = bm.get(t)
        up = per_upside(per, b[0]) if b else None
        chk = value_check(per, up, sh_check=(sh_checks or {}).get(t))
        if chk in VALUE_HIDE:
            up = None
        out[t] = {
            "upside_pct": round(up, 1) if up is not None else None,
            "fair_price": round(px * b[0] / per, 2) if up is not None else None,
            "per_bench": round(b[0], 1) if b else None,
            "per_bench_level": b[1] if b else None,
            "value_check": chk,
        }
    return out


def rerate_month(vin, sics, p=PER_BENCH):
    """月初の {銘柄: (余地, PBR, PER, ...)} の余地を、その月初の業種別 PER の中央値で置き換える（検証用）。"""
    bm = per_benchmarks({t: v[2] for t, v in vin.items()}, sics, p)
    out = {}
    for t, v in vin.items():
        b = bm.get(t)
        up = per_upside(v[2], b[0]) if b else None
        if value_check(v[2], up):  # 要確認の月は余地・PBR・PER を空に（割安の点 0）
            out[t] = type(v)((None, None, None, *v[3:]))
        else:
            out[t] = type(v)((up, *v[1:]))
    return out


def metrics(fd, px):
    """価格を入れて毎日計算する部分。"""
    mcap = px * fd["sh"]
    ev = mcap + fd["debt"] - fd["cash"]
    ni, eq, ebit, cap, roe = fd["ni"], fd["eq"], fd["ebit"], fd["cap"], fd["roe"]
    _up_ri, pbr, per = value_inputs(ni, eq, fd["sh"], roe, px)
    return {
        "mcap_bn": round(mcap / 1e9, 1),
        "PER": round(per, 1) if per is not None else None,
        "PBR": round(pbr, 2) if pbr else None,
        "roe_pct": round(100 * roe, 1) if roe is not None else None,
        # 上値余地・理論株価は業種別 PER の中央値で apply_relative が入れる（全銘柄がそろってから）
        "ri_upside_pct": None,
        "earnings_yield_pct": round(100 * ebit / ev, 1) if ebit and ev > 0 else None,
        "roc_pct": round(100 * ebit / cap, 1) if ebit and cap > 0 else None,
        # 2026-11 追加（売買スコア・公開の米国株の列）。古い us_fundamentals.json に無い項目は None。
        "equity_ratio_pct": round(100 * eq / fd["ta"], 1) if fd.get("ta") and eq > 0 else None,
        "div_yield_pct": round(100 * abs(fd["div"]) / mcap, 2) if fd.get("div") and mcap > 0 else None,
        "fair_price": None,
        "per_raw": per,
        "sh_check": fd.get("sh_check"),  # 株数の照合の結果 → apply_relative が「要確認」
    }


def apply_relative(rows, sics, key="ticker", p=PER_BENCH):
    """metrics の行（price・per_raw を持つ）に、業種別 PER の中央値からの理論株価・上値余地を入れる。"""
    per_px = {r[key]: (r.get("per_raw"), r.get("price")) for r in rows if r.get(key) and r.get("price")}
    sh_checks = {r[key]: r.get("sh_check") for r in rows if r.get(key)}
    rv = relative_value(per_px, sics, p, sh_checks)
    for r in rows:
        v = rv.get(r.get(key))
        if v:
            r["ri_upside_pct"], r["fair_price"] = v["upside_pct"], v["fair_price"]
            r["per_bench"], r["per_bench_level"] = v["per_bench"], v["per_bench_level"]
            r["value_check"] = v["value_check"]
            if v["value_check"]:
                r["value_check_per"] = r.get("PER")
            if v["value_check"] in VALUE_HIDE:  # 株数・1株利益が疑わしいので PER・PBR も出さない
                r["PER"] = r["PBR"] = None
    return rows


def is_fin(sector):
    return any(x in (sector or "") for x in FIN_SECTORS)


def screen_one(ticker, info, F, p, asof, p1y=None, p1m=None, sh_fix=None):
    """1社分の行（screen_us.py と同じ列）。足りなければ None。"""
    if not F or not p:
        return None
    fd = fundamentals(F, asof, p["splits"], sh_fix, ticker in SHARE_CLASSES)
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
