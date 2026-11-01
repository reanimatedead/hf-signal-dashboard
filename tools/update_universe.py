#!/usr/bin/env python3
"""tools/update_universe.py — 構成銘柄の週次更新（.github/workflows/universe.yml・月曜 2:00 JST）。

  1. 取得: S&P500 = Wikipedia（→ datahub CSV）、Nasdaq-100 / Dow30 = Wikipedia。
     日経225 は DATA_CONTRACT §19（指数提供元の権利により機械取得しない・確定済み）に従い
     既定では取得しない（内蔵の一覧を件数検査するだけ）。--nikkei-dynamic を付けたとき
     （universe.yml ではリポジトリ変数 NIKKEI_DYNAMIC=true のとき）だけ Wikipedia から取る。
  2. 件数検査: marketcalc.contracts.count_within（想定 ±5%）。
  3. 外れた / 取れなかった → 前週の一覧（data/universe/{name}.json、無ければ内蔵 dict）のまま。
     GITHUB_OUTPUT に bad=... を書く（前週の一覧のまま続ける。Issue は作らない・通知は ntfy だけ）。
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
    # 2026-11: Wikipedia の Nasdaq-100 / DJIA のページから構成銘柄の表そのものが消えたため、公式の出典へ。
    "nasdaq100": "https://api.nasdaq.com/api/quote/list-type/nasdaq100",   # Nasdaq 公式（JSON）
    "dow30": ("https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/"
              "holdings-daily-us-en-dia.xlsx"),                            # SPDR DIA（DJIA 連動 ETF）の保有銘柄
    "nikkei225": "https://en.wikipedia.org/wiki/Nikkei_225",
}
NAMES = ("nikkei225", "nasdaq100", "sp500", "dow30")


def http_get(url):
    """本文を返す（.xlsx は bytes、それ以外は str）。Nasdaq の API はブラウザの UA と Accept: application/json が要る。"""
    import requests
    headers = {"User-Agent": UA}
    if "api.nasdaq.com" in url:
        headers["Accept"] = "application/json"
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.content if url.endswith(".xlsx") else r.text


def _tables(html):
    import pandas as pd
    return pd.read_html(io.StringIO(html))


def _norm_col(c):
    """列名をそろえる: MultiIndex は最後の段、脚注 [1] を除き、前後の空白を取る。"""
    if isinstance(c, tuple):
        c = c[-1]
    return re.sub(r"\[[^\]]*\]", "", str(c)).strip()


_TICKER = re.compile(r"(?:^|[\s:])([A-Z][A-Z0-9.\-]{0,6})$")


def _ticker(cell):
    """セル → ティッカー。"NYSE: MMM" / "MMM[1]" / "BRK.B" の形も受ける（"." は Yahoo 形の "-" に）。"""
    t = re.sub(r"\[[^\]]*\]", "", str(cell)).strip()
    m = _TICKER.search(t)
    return m.group(1).replace(".", "-") if m else None


def parse_table(html, sym_cols=("Symbol", "Ticker"), name_cols=("Security", "Company", "Company name")):
    """sym_cols のどれかを列に持つ最初の表 → {ticker: name}。
    2026-11: Wikipedia の Nasdaq-100 / Dow 30 で 0 件になったため、列名の脚注・MultiIndex・大文字小文字、
    セルの取引所の前置き（"NYSE: MMM"）を許すようにした。"""
    want_s = [c.lower() for c in sym_cols]
    want_n = [c.lower() for c in name_cols]
    for df in _tables(html):
        cols = [_norm_col(c) for c in df.columns]
        low = [c.lower() for c in cols]
        si = next((low.index(c) for c in want_s if c in low), None)
        if si is None:
            continue
        ni = next((low.index(c) for c in want_n if c in low), None)
        out = {}
        for _, row in df.iterrows():
            t = _ticker(row.iloc[si])
            if not t:
                continue
            out[t] = str(row.iloc[ni]).strip() if ni is not None else t
        if out:
            return out
    return {}


_TICKER_RE = re.compile(r"[A-Z][A-Z0-9.\-]{0,6}")


def parse_nasdaq_api(text):
    """Nasdaq 公式 API（list-type/nasdaq100）→ {ticker: name}。data.data.rows[].symbol / companyName。"""
    rows = (((json.loads(text).get("data") or {}).get("data") or {}).get("rows")) or []
    out = {}
    for r in rows:
        t = str(r.get("symbol") or "").strip()
        if _TICKER_RE.fullmatch(t):
            out[t.replace(".", "-")] = str(r.get("companyName") or t).strip()
    return out


def parse_dia_xlsx(data):
    """SPDR DIA の保有銘柄 xlsx（先頭 4 行は説明、5 行目が見出し）→ {ticker: name}。
    現金・先物などティッカーの形でない行と、末尾の注記は落とす。"""
    import pandas as pd
    df = pd.read_excel(io.BytesIO(data), skiprows=4)
    cols = {str(c).strip().lower(): c for c in df.columns}
    tc, nc = cols.get("ticker"), cols.get("name")
    if tc is None:
        return {}
    out = {}
    for _, row in df.iterrows():
        t = str(row[tc]).strip()
        if not _TICKER_RE.fullmatch(t) or t.upper().startswith("CASH"):
            continue
        out[t.replace(".", "-")] = str(row[nc]).strip() if nc is not None else t
    return out


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
            return parse_nasdaq_api(fetch(URLS["nasdaq100"])), "nasdaq_api"
        if name == "dow30":
            return parse_dia_xlsx(fetch(URLS["dow30"])), "ssga_dia_holdings"
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
