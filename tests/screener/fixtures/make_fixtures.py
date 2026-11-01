#!/usr/bin/env python3
"""架空のサンプルデータを作る（決まった乱数で毎回同じ。本物のデータは使わない）。

tests/screener 用（テストの最初に一時ディレクトリへ作る。リポジトリには生成物を置かない）。

日本株: 架空5銘柄 × 400営業日（J-Quants の列形）・通期決算2期＋四半期1件
  daily/YYYY-MM-DD.json   [[Code4, AdjH, AdjL, AdjC, Va], ...]
  fins/YYYY-MM-DD.json    [{Code, DocType, CurFYEn, DiscDate, NP, Eq, TA, CFO, Sales, OP, BPS, EPS, NxFEPS,
                            ShOutFY, TrShFY, EqAR, ShEq, NxFNp, NxFDivAnn, ROE}, ...]
  master_YYYY-MM-DD.json  [{Code, CoName, MktNm, S17, S33, S33Nm, ScaleCat}, ...]
  bars_YYYY-MM-DD.json    [{Code, Date, AdjC, MktCap(百万円)}, ...]（各月の最初の営業日と最終日）
  months.json
米国株: 架空3銘柄（Yahoo chart 形 px/、EDGAR companyfacts 形 facts/、universe.json）
契約テスト: contract_ok.json / contract_broken.json（screener.contract の「観測値」形）

使い方: uv run python tests/screener/fixtures/make_fixtures.py OUT_DIR  → OUT_DIR/{japan,us,contract_*.json}
"""

import datetime as dt
import json
import pathlib
import sys

import numpy as np

from screener.calc import contracts, ind
from screener.calc.fund_us import CORE_TAGS

N = 400
END = dt.date(2026, 10, 30)  # サンプルの最終営業日（架空データの日付。コード側はこの日付を知らない）
SPLIT_AT = 200  # 10030 は 200日目に 1:2 の株式分割

JP = [  # code, name, S33, S33Nm, shares(期末), kind
    ("10010", "架空A工業", "3650", "電気機器", 100e6, "buy"),
    ("10020", "架空B商事", "6050", "卸売業", 80e6, "sell"),
    ("10030", "架空C電機", "3650", "電気機器", 100e6, "split"),
    ("10040", "架空D化学", "3200", "化学", 60e6, "long_oversold"),
    ("10050", "架空E銀行", "7050", "銀行業", 200e6, "flat"),
]
US = [
    ("AAA", "Alpha Fake Inc", "Information Technology", ["S&P500", "NAS100"], "buy"),
    ("BBB", "Beta Fake Corp", "Industrials", ["S&P500", "DOW30"], "flat"),
    ("CCC", "Gamma Fake Bank", "Financials", ["S&P500"], "sell"),
]


def bdays(n, end=END):
    d, out = end, []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= dt.timedelta(days=1)
    return out[::-1]


def path(kind, rng, drop):
    t = np.arange(N, dtype=float)
    if kind == "buy":  # 長期上向き → 最後に急落
        c = 1000 * np.exp(0.002 * t)
        c[-6:] *= np.linspace(1 - drop / 6, 1 - drop, 6)
    elif kind == "sell":  # 長期下向き → 最後に急騰
        c = 3000 * np.exp(-0.002 * t)
        c[-6:] *= np.linspace(1 + drop / 6, 1 + drop, 6)
    elif kind == "long_oversold":  # 横ばい → 最後の60日で大きく下落
        c = 2000 + 40 * np.sin(t / 20)
        c[-60:] *= np.linspace(1.0, 1 - 2 * drop, 60)
    elif kind == "split":  # ゆるい上昇（分割は調整後終値なので連続）
        c = 1500 * np.exp(0.0005 * t + 0.03 * np.sin(t / 30))
    else:
        c = 800 + 10 * np.sin(t / 25)
    c = c * (1 + rng.normal(0, 0.002, N))
    h = c * (1 + np.abs(rng.normal(0, 0.004, N)))
    l = c * (1 - np.abs(rng.normal(0, 0.004, N)))
    return h, l, c


def tuned(kind, seed):
    """最終日に狙った判定が出るまで下げ幅を上げる（決まった手順なので毎回同じ）。"""
    want = {
        "buy": lambda j: j["signal"] >= 1,
        "sell": lambda j: j["signal"] <= -1,
        "long_oversold": lambda j: j["long_oversold"] and j["signal"] == 0,
    }.get(kind)
    for drop in np.arange(0.05, 0.6, 0.01):
        rng = np.random.RandomState(seed)
        h, l, c = path(kind, rng, drop)
        if want is None:
            return h, l, c
        j = ind.judge(ind.compute(h, l, c))
        if want(j):
            return h, l, c
    raise SystemExit(f"fixture tuning failed for {kind}")


def fin_rows(code, shares, kind):
    """通期2期分。架空A は F が 8/8 になる形、架空C は一時利益（純利益>営業利益×1.3）。"""
    k = int(code[:4]) % 100
    scale = 1e9 * (1 + k / 10)
    rows = []
    for yi, (fye, disc) in enumerate((("2025-03-31", "2025-05-14"), ("2026-03-31", "2026-05-14"))):
        g = 1.0 + 0.1 * yi
        sh = shares if not (kind == "split" and yi == 0) else shares / 2  # 分割前は半分
        np_, op = 10 * scale * g, 12 * scale * g
        if kind == "split" and yi == 1:
            np_ = 20 * scale  # 特別利益で純利益が膨らむ
        if kind == "sell":
            np_, op = 3 * scale * g, 5 * scale * g
        eq = 80 * scale * (1 + 0.05 * yi)
        ta = (
            150 * scale * (1 + 0.02 * yi) * (0.8 + 0.1 * k)
        )  # 銘柄ごとに総資産利益率を変える（順位が同点にならないよう）
        sales = 100 * scale * (1 + 0.03 * yi)
        bps = eq / sh
        eps = np_ / sh
        rows.append(
            {
                "Code": code,
                "DocType": "FYFinancialStatements_Consolidated_JP",
                "CurFYEn": fye,
                "DiscDate": disc,
                "NP": str(np_),
                "Eq": str(eq),
                "TA": str(ta),
                "CFO": str(np_ * 1.4),
                "Sales": str(sales),
                "OP": str(op * (1 + 0.05 * yi)),
                "BPS": str(round(bps, 2)),
                "EPS": str(round(eps, 2)),
                "NxFEPS": str(round(eps * 1.15 if kind != "split" else eps * 0.6, 2)),
                "ShOutFY": str(sh),
                "TrShFY": "0",
                "EqAR": str(round(0.50 + 0.03 * yi, 3)),
                "ShEq": str(eq),
                "NxFNp": str(np_ * 1.15),
                "NxFDivAnn": str(round(eps * 0.3, 1)),
                "ROE": str(round(np_ / eq, 4)),
            }
        )
    # 四半期（通期の集計では使われないことの確認用）
    q = dict(rows[-1])
    q.update(
        {
            "DocType": "1QFinancialStatements_Consolidated_JP",
            "DiscDate": "2026-08-07",
            "CurFYEn": "2027-03-31",
            "NP": str(1.0),
        }
    )
    rows.append(q)
    if kind == "flat":  # 金融は空欄が多い
        for r in rows:
            r["OP"] = ""
            r["Sales"] = ""
    return rows


def yahoo_chart(days, h, l, c, splits=None):
    ts = [int(dt.datetime(d.year, d.month, d.day, 14, 30, tzinfo=dt.UTC).timestamp()) for d in days]
    r = {
        "timestamp": ts,
        "indicators": {
            "quote": [{"high": h.round(4).tolist(), "low": l.round(4).tolist(), "close": c.round(4).tolist()}],
            "adjclose": [{"adjclose": c.round(4).tolist()}],
        },
    }
    if splits:
        r["events"] = {"splits": splits}
    return {"chart": {"result": [r]}}


def us_facts(k, kind):
    base = 1e9 * (k + 1)

    def fy(tag, v0, v1, unit="USD"):
        return {
            tag: {
                "units": {
                    unit: [
                        {
                            "start": "2024-01-01",
                            "end": "2024-12-31",
                            "val": v0,
                            "form": "10-K",
                            "fp": "FY",
                            "filed": "2025-02-15",
                        },
                        {
                            "start": "2025-01-01",
                            "end": "2025-12-31",
                            "val": v1,
                            "form": "10-K",
                            "fp": "FY",
                            "filed": "2026-02-15",
                        },
                    ]
                }
            }
        }

    def inst(tag, v0, v1):
        return {
            tag: {
                "units": {
                    "USD": [
                        {"end": "2024-12-31", "val": v0, "form": "10-K", "fp": "FY", "filed": "2025-02-15"},
                        {"end": "2025-12-31", "val": v1, "form": "10-K", "fp": "FY", "filed": "2026-02-15"},
                    ]
                }
            }
        }

    g = {}
    g.update(fy("NetIncomeLoss", 0.10 * base, 0.12 * base))
    g.update(fy("OperatingIncomeLoss", 0.15 * base, 0.19 * base))
    g.update(fy("NetCashProvidedByUsedInOperatingActivities", 0.14 * base, 0.16 * base))
    g.update(fy("Revenues", 1.0 * base, 1.1 * base))
    g.update(fy("GrossProfit", 0.4 * base, 0.46 * base))
    g.update(inst("StockholdersEquity", 0.9 * base, 1.0 * base))
    g.update(inst("Assets", 2.0 * base, 2.1 * base))
    g.update(inst("AssetsCurrent", 0.8 * base, 0.85 * base))
    g.update(inst("LiabilitiesCurrent", 0.5 * base, 0.5 * base))
    g.update(inst("PropertyPlantAndEquipmentNet", 0.6 * base, 0.62 * base))
    g.update(inst("LongTermDebtNoncurrent", 0.5 * base, 0.45 * base))
    g.update(inst("CashAndCashEquivalentsAtCarryingValue", 0.2 * base, 0.25 * base))
    g.update(fy("WeightedAverageNumberOfDilutedSharesOutstanding", 1e8 * (k + 1), 1e8 * (k + 1), "shares"))
    dei = {
        "EntityCommonStockSharesOutstanding": {
            "units": {"shares": [{"end": "2026-01-31", "val": 1e8 * (k + 1), "form": "10-K", "filed": "2026-02-15"}]}
        }
    }
    return {"facts": {"us-gaap": g, "dei": dei}}


def write(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False))


def make(out):
    out = pathlib.Path(out)
    days = bdays(N)
    ds = [str(d) for d in days]
    jp, us = out / "japan", out / "us"
    series = {}
    for i, (code, name, s33, s33nm, sh, kind) in enumerate(JP):
        series[code] = tuned(kind, 100 + i)
    # 日足（日付別ファイル）
    for t, d in enumerate(ds):
        rows = []
        for code, *_ in JP:
            h, l, c = series[code]
            rows.append([code[:4], round(float(h[t]), 2), round(float(l[t]), 2), round(float(c[t]), 2), 1_000_000])
        write(jp / "daily" / f"{d}.json", rows)
    # 月初と最終日の bars（時価総額つき）
    month_first, seen = [], set()
    for d in ds:
        if d[:7] not in seen:
            seen.add(d[:7])
            month_first.append(d)
    for d in sorted(set(month_first + [ds[-1]])):
        t = ds.index(d)
        rows = []
        for code, name, s33, s33nm, sh, kind in JP:
            c = float(series[code][2][t])
            shares = sh / 2 if (kind == "split" and t < SPLIT_AT) else sh
            adj = c  # 調整後終値（分割後基準）
            raw = c * 2 if (kind == "split" and t < SPLIT_AT) else c  # 分割前の実際の株価
            rows.append(
                {
                    "Code": code,
                    "Date": d,
                    "AdjC": round(adj, 2),
                    "C": round(raw, 2),
                    "MktCap": round(raw * shares / 1e6, 1),
                }
            )
        write(jp / f"bars_{d}.json", rows)
    master = [
        {
            "Code": code,
            "CoName": name,
            "MktNm": "プライム",
            "S17": "5",
            "S33": s33,
            "S33Nm": s33nm,
            "ScaleCat": "TOPIX Mid400",
        }
        for code, name, s33, s33nm, sh, kind in JP
    ]
    for d in month_first:
        write(jp / f"master_{d}.json", master)
    write(jp / "months.json", month_first)
    byday = {}
    for code, name, s33, s33nm, sh, kind in JP:
        for r in fin_rows(code, sh, kind):
            byday.setdefault(r["DiscDate"], []).append(r)
    for d, rows in byday.items():
        write(jp / "fins" / f"{d}.json", rows)
    write(jp / "fins" / f"{ds[-1]}.json", [])  # 開示の無い日（空のファイル）

    # 米国
    uni = {}
    for k, (t, name, sector, idx, kind) in enumerate(US):
        h, l, c = tuned(kind, 200 + k)
        c = c / 10
        h = h / 10
        l = l / 10
        write(us / "px" / f"{t}.json", yahoo_chart(days, h, l, c))
        write(us / "facts" / f"{t}.json", us_facts(k, kind))
        uni[t] = {"name": name, "sector": sector, "idx": idx}
    write(us / "universe.json", uni)

    # 契約テストの観測値（正常・壊れた）
    ok = {
        "api_version": "v2",
        "jq_daily_count": 3812,
        "jq_fins_row": fin_rows("10010", 1e8, "buy")[0],
        "edgar": {t: list(contracts_tags()) for t in contracts.US_PROBE},
        "yahoo": {t: 250 for t in contracts.US_PROBE},
        "universe": {"sp500": 503, "nasdaq100": 101, "dow30": 30, "nikkei225": 225},
    }
    write(out / "contract_ok.json", ok)
    bad = json.loads(json.dumps(ok))
    bad["jq_daily_count"] = 1200  # 日足が足りない
    del bad["jq_fins_row"]["NxFEPS"]  # 列名が変わった
    for t in contracts.US_PROBE[:5]:
        bad["yahoo"][t] = None  # 5/20 = 25% 取れない
    bad["universe"]["nasdaq100"] = 80
    write(out / "contract_broken.json", bad)
    return out


def contracts_tags():
    return CORE_TAGS


if __name__ == "__main__":
    print(make(sys.argv[1]))
