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
SPLIT_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=10y&interval=1mo&events=split"
SEC_PAUSE = 0.12
MIN_COVERAGE = 0.5


def http_json(url):
    import urllib.request
    host = "sec.gov" in url
    ua = os.environ.get("SEC_USER_AGENT") or "hf-signal-dashboard https://github.com/reanimatedead/hf-signal-dashboard"
    headers = {"User-Agent": ua if host else "Mozilla/5.0", "Accept": "application/json"}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return json.load(r)


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


def one(get_json, sym, cik, asof):
    F = get_json(FACTS_URL.format(cik=cik))["facts"]
    fd = fund_us.fundamentals(F, asof, splits_of(get_json, sym))
    del F                                              # 1社分ずつ捨てる（全部をメモリに載せない）
    if not fd:
        return None
    try:
        sic = get_json(SUBMIT_URL.format(cik=cik)).get("sic")
    except Exception:  # noqa: BLE001
        sic = None
    row = {k: fd[k] for k in ("fy", "ni", "eq", "ebit", "sh", "debt", "cash", "cap", "f_score", "f_max")}
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


def build(tickers, get_json=http_json, asof=None, pause=SEC_PAUSE, check_contract=True):
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
            r = one(get_json, t, cik, asof)
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
