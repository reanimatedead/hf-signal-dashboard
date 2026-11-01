#!/usr/bin/env python3
"""tools/contract_check.py — 外部データの確認（M2）。deploy.yml full で2回使う。

1) 生成の前（引数なし）:
   - 構成銘柄の件数が想定 ±5%（nikkei225=225 / nasdaq100=100 / sp500=500 / dow30=30）。外れたら exit 1（止める）。
   - Yahoo への事前の問い合わせはしない。2026-11-01 の deploy #260 で、事前確認の40回が本体の取得と同じ IP の
     回数制限枠を使い、429 を 100% 受けて公開を止めたため（本体の fetch_signals は動いていた）。
2) 生成の後（--post docs/data.json）:
   - 本当の欠損チェック。meta.nan_report で、株式4タブそれぞれ price=None の割合が 10% を超えたら exit 1
     （以降の upload / deploy-pages は走らず、Pages は前日のまま）。

Issue は作らない（失敗の通知は workflow の ntfy ステップだけ）。

オフライン確認: --fixture FILE（JSON）で件数を差し替える:
    {"counts": {"nikkei225": 225, "nasdaq100": 101, "sp500": 503, "dow30": 30}}
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from marketcalc import contracts  # noqa: E402

EQUITY_TABS = ("nikkei225", "dow30", "nasdaq100", "sp500")
NAN_MAX = contracts.MISSING_MAX  # 10%


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


def check(counts):
    res = []
    for name in EQUITY_TABS:
        n = counts.get(name)
        res.append(contracts.count_within(name, int(n or 0)) if n is not None else (False, f"{name}: 件数を取得できない"))
    return contracts.summarize(res)


def run(fixture=None):
    if fixture:
        fx = json.loads(pathlib.Path(fixture).read_text(encoding="utf-8"))
        counts = fx.get("counts", {})
    else:
        counts = live_counts()
    ok, body = check(counts)
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
    ap.add_argument("--fixture", help="件数を差し替える JSON（オフライン確認用）")
    ap.add_argument("--post", metavar="DATA_JSON", help="生成後の欠損チェック（meta.nan_report）")
    a = ap.parse_args(argv)
    return post(a.post) if a.post else run(a.fixture)


if __name__ == "__main__":
    sys.exit(main())
