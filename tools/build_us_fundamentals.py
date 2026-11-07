#!/usr/bin/env python3
"""tools/build_us_fundamentals.py — 米国株の決算部分（週次・universe.yml）→ data/us_fundamentals.json。

EDGAR companyfacts を**1社ずつ**読み、marketcalc.fund_us.fundamentals（価格を使わない部分:
純利益・自己資本・EBIT・株数・負債・現金・投下資本・ROE・F スコア）を計算して小さな JSON に保存する。
毎日の fetch_signals.py は今日の株価でここから fund_us.metrics → fund_us.rank（魔法の公式）を出す。

  0. 最初に契約テスト: 主要20社（marketcalc.contracts.US_PROBE）の companyfacts に
     fund_us.CORE_TAGS が揃っているか。欠けが 10% を超えたら exit 2（前回のファイルのまま）。
  1. 対象: data/universe/{sp500,nasdaq100,dow30}.json の和集合（無ければ fetch_signals の内蔵 / 取得）。
  2. 1社ずつ: companyfacts（決算）＋ submissions（SIC → 金融・不動産・公益の除外判定）＋
     Yahoo の分割履歴（株数を今の分割基準にそろえる）。SEC の 10 リクエスト/秒を守る。
  3. 取れた社が対象の 50% 未満なら exit 3（前回のファイルのまま）。

SEC は User-Agent に連絡先を求める: 環境変数 SEC_USER_AGENT（Actions の vars）で渡す。
通信は get_json(url) を差し替えられる（tests/test_us_fundamentals.py はオフライン）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from marketcalc import contracts, fund_us  # noqa: E402

OUT = ROOT / "data" / "us_fundamentals.json"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMIT_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
SPLIT_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=10y&interval=1mo&events=split"
SEC_PAUSE = 0.12
MIN_COVERAGE = 0.5
HIST_MONTHS = 24     # 売買スコアの検証用: 過去 24 か月の各月初で「その時点で入手できた決算」（hist）


def http_json(url):
    import urllib.request
    host = "sec.gov" in url
    ua = os.environ.get("SEC_USER_AGENT") or "hf-signal-dashboard https://github.com/reanimatedead/hf-signal-dashboard"
    headers = {"User-Agent": ua if host else "Mozilla/5.0", "Accept": "application/json"}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return json.load(r)


def http_text(url):
    import urllib.request
    ua = os.environ.get("SEC_USER_AGENT") or "hf-signal-dashboard https://github.com/reanimatedead/hf-signal-dashboard"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": ua}), timeout=60) as r:
        return r.read().decode("utf-8", "ignore")


def sic_is_fin(sic):
    """SIC 6000-6799（金融・保険・不動産）/ 4900-4999（電気・ガス・水道）→ 魔法の公式から除く。"""
    try:
        s = int(sic)
    except (TypeError, ValueError):
        return False
    return 6000 <= s <= 6799 or 4900 <= s <= 4999


def cik_map(get_json):
    j = get_json(TICKERS_URL)
    out = {}
    for v in (j.values() if isinstance(j, dict) else j):
        t = str(v["ticker"]).upper()
        out[t] = int(v["cik_str"])
        out.setdefault(t.replace(".", "-"), int(v["cik_str"]))
    return out


def edgar_contract(get_json, ciks, probe=contracts.US_PROBE, pause=SEC_PAUSE):
    got = 0
    for t in probe:
        try:
            F = get_json(FACTS_URL.format(cik=ciks[t]))["facts"]
            if all(tag in F.get("us-gaap", {}) for tag in fund_us.CORE_TAGS):
                got += 1
        except Exception:  # noqa: BLE001
            pass
        time.sleep(pause)
    return contracts.missing_ratio_ok("EDGAR 主要20社 タグ", got, len(probe))


def splits_of(get_json, sym):
    try:
        return fund_us.parse_yahoo_chart(get_json(SPLIT_URL.format(sym=sym)))["splits"]
    except Exception:  # noqa: BLE001
        return []


def month_firsts(asof, n=HIST_MONTHS):
    d = dt.date.fromisoformat(asof[:10])
    y, m = d.year, d.month
    out = []
    for _ in range(n):
        out.append(dt.date(y, m, 1).isoformat())
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return sorted(out)


def class_shares(sym, cik, sub, get_text):
    """株の種類を換算した株数（fund_us.SHARE_CLASSES の銘柄だけ）→ (株数, 提出日) | None。
    直近の 10-Q / 10-K の本文から読む。取れなければ None（株数を信用できないので「要確認」になる）。"""
    if sym not in fund_us.SHARE_CLASSES:
        return None
    try:
        r = sub["filings"]["recent"]
        i = next(k for k, f in enumerate(r["form"]) if f in ("10-Q", "10-K"))
        acc = r["accessionNumber"][i].replace("-", "")
        sh = fund_us.listed_class_shares(sym, get_text(DOC_URL.format(cik=cik, acc=acc, doc=r["primaryDocument"][i])))
        return (sh, r["filingDate"][i]) if sh else None
    except Exception:  # noqa: BLE001
        return None


def history(F, asof, splits, sh_fix=None, needs_fix=False):
    """{月初: [純利益, 自己資本, 株数, ROE, 一時利益の目印 0/1]}（その月初より前に提出された決算だけ。fund_us.fundamentals と同じ式）。
    株数が食い違う月（要確認）は入れない。sh_fix は今の換算株数を過去の月にも使う（BRK-B・ERIE・V は株数の変化が小さい）。"""
    out = {}
    for m in month_firsts(asof):
        fd = fund_us.fundamentals(F, m, splits, sh_fix, needs_fix)
        if fd and not fd.get("sh_mismatch"):
            out[m] = [fd["ni"], fd["eq"], fd["sh"], round(fd["roe"], 5) if fd.get("roe") is not None else None,
                      int(bool(fd.get("one_off")))]
    return out


def one(get_json, sym, cik, asof, get_text=http_text):
    F = get_json(FACTS_URL.format(cik=cik))["facts"]
    sp = splits_of(get_json, sym)
    try:
        sub = get_json(SUBMIT_URL.format(cik=cik))
    except Exception:  # noqa: BLE001
        sub = {}
    fix = class_shares(sym, cik, sub, get_text)
    needs = sym in fund_us.SHARE_CLASSES
    fd = fund_us.fundamentals(F, asof, sp, fix, needs)
    hist = history(F, asof, sp, fix, needs) if fd else {}
    del F                                              # 1社分ずつ捨てる（全部をメモリに載せない）
    if not fd:
        return None
    sic = sub.get("sic")
    row = {k: fd[k] for k in ("fy", "ni", "eq", "ebit", "sh", "debt", "cash", "cap", "f_score", "f_max",
                              "ta", "div", "one_off", "filed", "sh_end", "sh_mismatch")}
    if fix:
        row["sh_src"] = "cover"                        # 株の種類を換算した株数（Mac mini 版もこの値を使う）
    row["hist"] = hist
    row["roe"] = round(fd["roe"], 5) if fd.get("roe") is not None else None
    row["sic"] = sic
    row["fin"] = sic_is_fin(sic)
    return row


def us_universe():
    import fetch_signals as fs
    syms = {}
    for name, default in (("dow30", fs.DOW30), ("nasdaq100", fs.NASDAQ100)):
        syms.update(fs.load_universe(name, default)[0])
    sp, src = fs.load_universe("sp500", {})
    syms.update(sp if src == "file" else {t: t for t in fs.get_sp500_tickers()[0]})
    return sorted(syms)


def build(tickers, get_json=http_json, asof=None, pause=SEC_PAUSE, check_contract=True, get_text=http_text):
    """→ (exit_code, obj|None, log_lines)。"""
    asof = asof or dt.date.today().isoformat()
    log = []
    ciks = cik_map(get_json)
    if check_contract:
        ok, msg = edgar_contract(get_json, ciks, pause=pause)
        log.append(("✅ " if ok else "❌ ") + msg)
        if not ok:
            return 2, None, log
    rows, miss = {}, []
    for t in tickers:
        cik = ciks.get(t) or ciks.get(t.replace("-", "."))
        if not cik:
            miss.append(t); continue
        try:
            r = one(get_json, t, cik, asof, get_text)
        except Exception:  # noqa: BLE001
            r = None
        if r:
            rows[t] = r
        else:
            miss.append(t)
        time.sleep(pause)
    cov = len(rows) / len(tickers) if tickers else 0
    log.append(f"取れた {len(rows)}/{len(tickers)}（{cov * 100:.0f}%）")
    if cov < MIN_COVERAGE:
        return 3, None, log
    obj = {"as_of": asof, "source": "SEC EDGAR companyfacts (10-K)", "count": len(rows),
           "missing": miss, "rows": rows}
    return 0, obj, log


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--tickers", help="カンマ区切り（既定は S&P500+NDX+Dow の和集合）")
    a = ap.parse_args(argv)
    tickers = a.tickers.split(",") if a.tickers else us_universe()
    code, obj, log = build(tickers)
    print("\n".join(log))
    if code:
        print(f"build_us_fundamentals: 止めました（exit {code}）。前回の {a.out} のままです。")
        return code
    pathlib.Path(a.out).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"build_us_fundamentals: {a.out} {obj['count']} 社")
    return 0


if __name__ == "__main__":
    sys.exit(main())
