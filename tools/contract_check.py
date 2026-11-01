#!/usr/bin/env python3
"""tools/contract_check.py — 外部データの確認（M2）。deploy.yml full で2回使う。

1) 生成の前（引数なし）:
   - 構成銘柄の件数が想定 ±5%（nikkei225=225 / nasdaq100=100 / sp500=500 / dow30=30）。外れたら exit 1（止める）。
   - Yahoo 主要20銘柄×2（contracts.US_PROBE + JP_PROBE）の直近終値: **警告だけ（止めない）**。
     HTTP 429（回数制限）は「取れない」ではなく「確認できない」と数える。
     2026-11-01 の deploy #260 で、この確認だけが 429 を 100% 受けて公開を止めた（本体の取得は動いていた）ため。
2) 生成の後（--post docs/data.json）:
   - 本当の欠損チェック。meta.nan_report で、株式4タブそれぞれ price=None の割合が 10% を超えたら exit 1
     （以降の upload / deploy-pages は走らず、Pages は前日のまま）。

Issue は作らない（失敗の通知は workflow の ntfy ステップだけ）。

オフライン確認: --fixture FILE（JSON）で取得結果を差し替える:
    {"prices": {"AAPL": [190.1, 191.2], "7203.T": null, "MSFT": "rate_limited", ...},
     "counts": {"nikkei225": 225, "nasdaq100": 101, "sp500": 503, "dow30": 30}}
    prices に無い銘柄は「取れなかった」、"rate_limited" は「確認できない（429）」と数える。
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from marketcalc import contracts  # noqa: E402

RATE_LIMITED = "rate_limited"
EQUITY_TABS = ("nikkei225", "dow30", "nasdaq100", "sp500")
NAN_MAX = contracts.MISSING_MAX  # 10%


def _last_close_ok(closes):
    if not isinstance(closes, list) or not closes:
        return False
    v = [c for c in closes if c is not None and isinstance(c, (int, float)) and math.isfinite(c) and c > 0]
    return bool(v)


def _probe_one(symbol, timeout=15):
    """Yahoo chart API を1回ずつ（query1 → query2）。429 は RATE_LIMITED を返す（リトライで叩き続けない）。"""
    import fetch_signals as fs
    enc = urllib.parse.quote(str(symbol), safe="")
    limited = False
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        url = f"https://{host}/v8/finance/chart/{enc}?range=5d&interval=1d"
        req = urllib.request.Request(url, headers={"User-Agent": fs._CHART_API_UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                j = json.loads(r.read())
            return j["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        except urllib.error.HTTPError as e:
            limited = limited or e.code == 429
        except Exception:  # noqa: BLE001
            pass
    return RATE_LIMITED if limited else None


def live_prices(symbols):
    return {s: _probe_one(s) for s in symbols}


def live_counts():
    """構成銘柄の件数（fetch_signals と同じ選び方: universe ファイル優先・無ければ内蔵/取得）。"""
    import fetch_signals as fs
    out = {}
    for name, default in (("nikkei225", fs.NIKKEI225), ("nasdaq100", fs.NASDAQ100), ("dow30", fs.DOW30)):
        d, _ = fs.load_universe(name, default)
        out[name] = len(d)
    d, src = fs.load_universe("sp500", {})
    out["sp500"] = len(d) if src == "file" else len(fs.get_sp500_tickers()[0])
    return out


def yahoo_warnings(prices):
    """Yahoo の事前確認（警告だけ）。戻り値は表示用の行のリスト。"""
    lines = []
    for name, probe in (("Yahoo 米国 主要20", contracts.US_PROBE), ("Yahoo 日本 主要20", contracts.JP_PROBE)):
        limited = sum(1 for s in probe if prices.get(s) == RATE_LIMITED)
        checked = [s for s in probe if prices.get(s) != RATE_LIMITED]
        missing = sum(1 for s in checked if not _last_close_ok(prices.get(s)))
        if not checked:
            lines.append(f"⚠️ {name}: 全 {len(probe)} 件が HTTP 429 → 確認できない（止めない。欠損は生成後の nan_report で見る）")
            continue
        ratio = missing / len(checked)
        mark = "✅" if ratio <= contracts.MISSING_MAX else "⚠️"
        extra = f"・429 で確認できない {limited} 件" if limited else ""
        lines.append(f"{mark} {name}: 確認できた {len(checked)} 件中 取れない {missing} 件（{ratio * 100:.0f}%）{extra}"
                     + ("" if mark == "✅" else " → 警告だけ（止めない）"))
    return lines


def check(prices, counts):
    res = []
    for name in EQUITY_TABS:
        n = counts.get(name)
        res.append(contracts.count_within(name, int(n or 0)) if n is not None else (False, f"{name}: 件数を取得できない"))
    ok, body = contracts.summarize(res)
    return ok, "\n".join(yahoo_warnings(prices) + [body])


def run(fixture=None):
    if fixture:
        fx = json.loads(pathlib.Path(fixture).read_text(encoding="utf-8"))
        prices, counts = fx.get("prices", {}), fx.get("counts", {})
    else:
        prices = live_prices(contracts.US_PROBE + contracts.JP_PROBE)
        counts = live_counts()
    ok, body = check(prices, counts)
    print(body)
    if ok:
        print("\ncontract_check: OK")
        return 0
    print("\ncontract_check: FAIL（構成銘柄の件数）→ 以降の生成・デプロイを止めます（前日のデプロイが残ります）")
    return 1


def post(path):
    """生成後の欠損チェック（meta.nan_report）。"""
    p = pathlib.Path(path)
    if not p.exists():
        print(f"contract_check --post: FAIL — {p} がない")
        return 1
    nan = ((json.loads(p.read_text(encoding="utf-8")).get("meta") or {}).get("nan_report")) or {}
    res = []
    for tab in EQUITY_TABS:
        rec = nan.get(tab)
        if not isinstance(rec, dict) or not rec.get("constituents"):
            res.append((False, f"{tab}: nan_report がない／構成銘柄 0 件"))
            continue
        n, null = int(rec["constituents"]), int(rec.get("price_null") or 0)
        res.append(contracts.missing_ratio_ok(f"{tab} 株価(price=None)", n - null, n, NAN_MAX))
    ok, body = contracts.summarize(res)
    print(body)
    print("\ncontract_check --post: " + ("OK" if ok else "FAIL → upload / deploy-pages は走らず、Pages は前日のまま"))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", help="取得結果を差し替える JSON（オフライン確認用）")
    ap.add_argument("--post", metavar="DATA_JSON", help="生成後の欠損チェック（meta.nan_report）")
    a = ap.parse_args(argv)
    return post(a.post) if a.post else run(a.fixture)


if __name__ == "__main__":
    sys.exit(main())
