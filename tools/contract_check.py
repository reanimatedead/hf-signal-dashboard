#!/usr/bin/env python3
"""tools/contract_check.py — 外部データの契約テスト（M2）。deploy.yml full の最初に走る。

確かめること（判定関数は marketcalc.contracts）:
  1. Yahoo 主要20銘柄×2（contracts.US_PROBE + JP_PROBE）の直近終値が取れる。
     取れない割合が 10% を超えたら止める。
  2. 構成銘柄の件数が想定 ±5%（nikkei225=225 / nasdaq100=100 / sp500=500 / dow30=30）。

失敗したら exit 1 → deploy.yml の以降のステップは走らず、Pages には前日のデプロイが残る。
--issue を付けると Issue を**タイトル固定で1件だけ**起票（既存なら comment。tools/issue_once.py）。

オフライン確認: --fixture FILE（JSON）で取得結果を差し替える:
    {"prices": {"AAPL": [190.1, 191.2], "7203.T": null, ...},
     "counts": {"nikkei225": 225, "nasdaq100": 101, "sp500": 503, "dow30": 30}}
    prices に無い銘柄は「取れなかった」と数える。
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from marketcalc import contracts  # noqa: E402

ISSUE_TITLE = "🔴 契約テスト（contract_check）が失敗: デプロイを止めました"


def _last_close_ok(closes):
    if not closes:
        return False
    v = [c for c in closes if c is not None and isinstance(c, (int, float)) and math.isfinite(c) and c > 0]
    return bool(v)


def live_prices(symbols):
    """Yahoo chart API（fetch_signals と同じ取得経路）で直近5日の終値を取る。"""
    import fetch_signals as fs
    out = {}
    for s in symbols:
        j = fs._chart_api_json(s, "5d", "1d", 20)
        try:
            out[s] = j["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        except Exception:  # noqa: BLE001
            out[s] = None
    return out


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


def check(prices, counts):
    res = []
    for name, probe in (("Yahoo 米国 主要20", contracts.US_PROBE), ("Yahoo 日本 主要20", contracts.JP_PROBE)):
        got = sum(1 for s in probe if _last_close_ok(prices.get(s)))
        res.append(contracts.missing_ratio_ok(name, got, len(probe)))
    for name in ("nikkei225", "nasdaq100", "sp500", "dow30"):
        n = counts.get(name)
        res.append(contracts.count_within(name, int(n or 0)) if n is not None else (False, f"{name}: 件数を取得できない"))
    return contracts.summarize(res)


def run(fixture=None, issue=False, runner=None, run_url=""):
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
    print("\ncontract_check: FAIL → 以降の生成・デプロイを止めます（前日のデプロイが残ります）")
    if issue:
        from issue_once import open_issue_once
        text = ("外部データの契約テストが失敗したため、この日のデプロイを止めました（Pages は前日のまま）。\n\n"
                + body + (f"\n\nrun: {run_url}" if run_url else ""))
        status, num = open_issue_once(ISSUE_TITLE, text, runner=runner)
        print(f"issue: {status} {num or ''}")
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", help="取得結果を差し替える JSON（オフライン確認用）")
    ap.add_argument("--issue", action="store_true", help="失敗時に Issue を1件だけ起票（gh が必要）")
    ap.add_argument("--run-url", default="")
    a = ap.parse_args(argv)
    return run(a.fixture, a.issue, run_url=a.run_url)


if __name__ == "__main__":
    sys.exit(main())
