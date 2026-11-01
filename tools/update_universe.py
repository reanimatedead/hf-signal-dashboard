#!/usr/bin/env python3
"""tools/update_universe.py — 構成銘柄の週次更新（.github/workflows/universe.yml・月曜 2:00 JST）。

  1. 取得: S&P500 = Wikipedia（→ datahub CSV）、Nasdaq-100 / Dow30 = Wikipedia。
     日経225 は DATA_CONTRACT §19（指数提供元の権利により機械取得しない・確定済み）に従い
     既定では取得しない（内蔵の一覧を件数検査するだけ）。--nikkei-dynamic を付けたとき
     （universe.yml ではリポジトリ変数 NIKKEI_DYNAMIC=true のとき）だけ Wikipedia から取る。
  2. 件数検査: marketcalc.contracts.count_within（想定 ±5%）。
  3. 外れた / 取れなかった → 前週の一覧（data/universe/{name}.json、無ければ内蔵 dict）のまま。
     GITHUB_OUTPUT に bad=... を書き、workflow が Issue を1件だけ起票する（tools/issue_once.py）。
  4. 通った → data/universe/{name}.json を更新し、前週との差分を data/universe/changes.json に追記。
     コミットは workflow が行う。

通信は fetch(url) -> str を差し替えられる（テストは tests/test_update_universe.py でオフライン）。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from marketcalc.contracts import count_within  # noqa: E402

UDIR = ROOT / "data" / "universe"
CHANGES_KEEP = 200
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
URLS = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "sp500_csv": "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
    "nasdaq100": "https://en.wikipedia.org/wiki/Nasdaq-100",
    "dow30": "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average",
    "nikkei225": "https://en.wikipedia.org/wiki/Nikkei_225",
}
NAMES = ("nikkei225", "nasdaq100", "sp500", "dow30")


def http_get(url):
    import requests
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text


def _tables(html):
    import pandas as pd
    return pd.read_html(io.StringIO(html))


def parse_table(html, sym_cols=("Symbol", "Ticker"), name_cols=("Security", "Company", "Company name")):
    """sym_cols のどれかを列に持つ最初の表 → {ticker: name}（"." は Yahoo 形の "-" にそろえる）。"""
    for df in _tables(html):
        cols = [str(c).strip() for c in df.columns]
        sc = next((c for c in sym_cols if c in cols), None)
        if not sc:
            continue
        nc = next((c for c in name_cols if c in cols), None)
        out = {}
        for _, row in df.iterrows():
            t = str(row[df.columns[cols.index(sc)]]).strip().replace(".", "-")
            if not re.fullmatch(r"[A-Z][A-Z0-9\-]{0,6}", t):
                continue
            out[t] = str(row[df.columns[cols.index(nc)]]).strip() if nc else t
        if out:
            return out
    return {}


def parse_sp500_csv(text):
    rows = list(csv.DictReader(io.StringIO(text)))
    return {r["Symbol"].replace(".", "-"): r.get("Security", r["Symbol"]) for r in rows if r.get("Symbol")}


def parse_nikkei(html):
    """Wikipedia の構成銘柄一覧（4桁コード）→ {"NNNN.T": name}。表の列名に依らずコード列を探す。"""
    out = {}
    for df in _tables(html):
        for c in df.columns:
            vals = df[c].astype(str).str.extract(r"^\s*(\d{4}|\d{3}[A-Z])\s*$")[0]
            if vals.notna().sum() >= 20:
                namec = next((k for k in df.columns if k != c and df[k].dtype == object), None)
                for i, code in vals.items():
                    if isinstance(code, str):
                        out[f"{code}.T"] = str(df.at[i, namec]) if namec is not None else code
                break
    return out


def fetch_one(name, fetch, nikkei_dynamic=False):
    """→ ({ticker: name} | None, 理由)。None は「取れなかった / 取らない」。"""
    try:
        if name == "sp500":
            try:
                d = parse_table(fetch(URLS["sp500"]))
            except Exception:  # noqa: BLE001
                d = {}
            if len(d) < 400:
                d = parse_sp500_csv(fetch(URLS["sp500_csv"]))
            return d, "wikipedia/datahub"
        if name == "nasdaq100":
            return parse_table(fetch(URLS["nasdaq100"])), "wikipedia"
        if name == "dow30":
            return parse_table(fetch(URLS["dow30"]), sym_cols=("Symbol",), name_cols=("Company",)), "wikipedia"
        if name == "nikkei225":
            if not nikkei_dynamic:
                return None, "DATA_CONTRACT §19: 機械取得しない（内蔵一覧を件数検査のみ）"
            return parse_nikkei(fetch(URLS["nikkei225"])), "wikipedia"
    except Exception as exc:  # noqa: BLE001
        return None, f"取得失敗 {type(exc).__name__}: {str(exc)[:80]}"
    return None, "unknown"


def previous(name, udir, builtin):
    p = pathlib.Path(udir) / f"{name}.json"
    if p.exists():
        try:
            return dict(json.loads(p.read_text(encoding="utf-8")).get("members") or {}), "file"
        except Exception:  # noqa: BLE001
            pass
    return dict(builtin.get(name) or {}), "builtin"


def builtin_lists():
    import fetch_signals as fs
    return {"nikkei225": fs.NIKKEI225, "nasdaq100": fs.NASDAQ100, "dow30": fs.DOW30, "sp500": {}}


def update(fetch=None, udir=None, builtin=None, today=None, nikkei_dynamic=False, names=NAMES):
    """戻り値 {"results": {name: {...}}, "bad": [name,...], "changed": [name,...]}。ファイルを書く。"""
    fetch = fetch or http_get
    udir = pathlib.Path(udir or UDIR); udir.mkdir(parents=True, exist_ok=True)
    builtin = builtin if builtin is not None else builtin_lists()
    today = today or dt.date.today().isoformat()
    results, bad, changed, entries = {}, [], [], []
    for name in names:
        prev, prev_src = previous(name, udir, builtin)
        got, src = fetch_one(name, fetch, nikkei_dynamic)
        if got is None:
            ok, msg = count_within(name, len(prev)) if prev else (False, f"{name}: 前回の一覧も無い")
            results[name] = {"status": "kept", "count": len(prev), "source": prev_src, "reason": src, "check": msg}
            if not ok or not src.startswith("DATA_CONTRACT"):
                bad.append(name)
            continue
        ok, msg = count_within(name, len(got))
        if not ok:
            results[name] = {"status": "kept", "count": len(prev), "source": prev_src,
                             "fetched": len(got), "reason": msg, "check": msg}
            bad.append(name)
            continue
        added, removed = sorted(set(got) - set(prev)), sorted(set(prev) - set(got))
        (udir / f"{name}.json").write_text(json.dumps(
            {"as_of": today, "source": src, "count": len(got), "members": dict(sorted(got.items()))},
            ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        results[name] = {"status": "updated", "count": len(got), "source": src, "check": msg,
                         "added": added, "removed": removed}
        if added or removed or prev_src != "file":
            changed.append(name)
            entries.append({"date": today, "name": name, "count": len(got), "added": added, "removed": removed})
    cp = udir / "changes.json"
    hist = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {"entries": []}
    hist["entries"] = (hist.get("entries", []) + entries)[-CHANGES_KEEP:]
    hist["last_run"] = {"date": today, "results": {k: {kk: vv for kk, vv in v.items() if kk not in ("added", "removed")}
                                                   for k, v in results.items()}, "bad": bad}
    cp.write_text(json.dumps(hist, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"results": results, "bad": bad, "changed": changed}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--nikkei-dynamic", action="store_true",
                    help="日経225 も Wikipedia から取る（DATA_CONTRACT §19 の判断を変えるときだけ）")
    ap.add_argument("--issue-body", default="", help="外れたときの Issue 本文の書き出し先")
    a = ap.parse_args(argv)
    r = update(nikkei_dynamic=a.nikkei_dynamic or os.environ.get("NIKKEI_DYNAMIC") == "true")
    for k, v in r["results"].items():
        print(f"{k:10s} {v['status']:8s} count={v['count']} source={v['source']} — {v.get('check') or v.get('reason')}")
    if r["bad"]:
        body = ("構成銘柄の週次更新で件数が想定 ±5% から外れた / 取れなかったため、前週の一覧のままにしました。\n\n"
                + "\n".join(f"- {k}: {r['results'][k]}" for k in r["bad"]))
        if a.issue_body:
            pathlib.Path(a.issue_body).write_text(body, encoding="utf-8")
        print("\n" + body)
    go = os.environ.get("GITHUB_OUTPUT")
    if go:
        with open(go, "a", encoding="utf-8") as f:
            f.write(f"bad={','.join(r['bad'])}\nchanged={','.join(r['changed'])}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
