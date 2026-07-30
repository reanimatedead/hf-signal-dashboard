#!/usr/bin/env python3
"""tools/check_links.py — link 死活チェック（Task 5-4）。

data.json の全 markets 行の link.url に HEAD を投げ、到達性を記録する。

方針:
  - Yahoo (finance.yahoo.com) には各リクエスト前に 2 秒以上の待機を必ず挟む。
    実測で HTTP 429（レート制限）を踏んでいるため。
  - CI では「警告のみ」。レート制限(429)やタイムアウトによる誤検知で job を
    fail させない。exit code は常に 0（診断出力が目的）。
  - 結果は docs/link_check.json に出力。

実行:
    python3 tools/check_links.py [path/to/data.json]

環境: system /usr/bin/python3 (3.9.6) と CI 3.11 の両方で動くよう標準ライブラリのみ。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

DATA = sys.argv[1] if len(sys.argv) > 1 else "docs/data.json"
DOCS_DIR = os.path.dirname(DATA) or "."
OUT = os.path.join(DOCS_DIR, "link_check.json")

YAHOO_HOST = "finance.yahoo.com"
YAHOO_WAIT_S = 2.5          # >= 2s（429 回避）
TIMEOUT_S = 12
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _now():
    return datetime.now(timezone.utc).isoformat()


_EQUITY_TABS = ("nikkei225", "dow30", "nasdaq100", "sp500")
_EQUITY_SAMPLE = 5   # equity 構成銘柄リンクは同型(finance.yahoo.com/quote/*)。全数は数百件で
                     # Yahoo の 2.5s 待機と GET 再確認で CI を超過する。タブごとにサンプル。


def _collect_urls(d):
    """(category, symbol, url) を列挙（重複 url は 1 回）。equity 構成銘柄の Yahoo quote は
    同型なのでタブごとに先頭 _EQUITY_SAMPLE 件だけ検査し、残数は main() でログする
    （サイレント truncation はしない）。index proxy(^) と非 equity は全数検査。"""
    seen = set()
    out = []
    skipped = 0
    per_tab = {}
    for cat, rows in (d.get("markets") or {}).items():
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                continue
            sym = r.get("symbol", "?")
            url = ((r.get("link") or {}).get("url")) or ""
            if not url or not url.startswith(("http://", "https://")):
                continue
            # equity 構成銘柄(非^)はサンプルのみ。index proxy と非 equity は常に検査。
            if cat in _EQUITY_TABS and not str(sym).startswith("^"):
                per_tab[cat] = per_tab.get(cat, 0) + 1
                if per_tab[cat] > _EQUITY_SAMPLE:
                    skipped += 1
                    continue
            if url in seen:
                continue
            seen.add(url)
            out.append((cat, sym, url))
    return out, skipped


def _get_status(url):
    """GET で到達確認（本文は読まない）。(status_code:int|None, note)。"""
    greq = urllib.request.Request(url, method="GET", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(greq, timeout=TIMEOUT_S) as resp:
            return resp.status, "ok_via_get"
    except urllib.error.HTTPError as e:
        return e.code, "http_error"
    except Exception as e:  # noqa: BLE001
        return None, f"error:{type(e).__name__}"


def _head(url):
    """到達確認。(status_code:int|None, note:str) を返す。

    横断監査(2026-07-30): HEAD 依存は生きたリンクを dead 誤判定する（support.google.com
    が HEAD に 404 を返す等・pixel-reference と同 class）。HEAD が 2xx/3xx でなければ
    **必ず GET で再確認**する（403/405 に限定しない）。GET が通れば生存扱い。
    """
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            if 200 <= resp.status < 400:
                return resp.status, "ok"
            return _get_status(url)                       # 非2xx/3xx は GET で再確認
    except urllib.error.HTTPError:
        return _get_status(url)                           # HEAD が HTTP エラー → GET 再確認
    except Exception:                                     # noqa: BLE001
        return _get_status(url)                           # HEAD がネットワーク不能 → GET 再確認


def main():
    try:
        with open(DATA, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:  # noqa: BLE001
        rep = {"as_of_utc": _now(), "error": f"cannot read {DATA}: {e}",
               "checked": 0, "results": []}
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        print(f"check_links: cannot read {DATA}: {e}")
        return 0  # 警告のみ。CI を落とさない。

    urls, skipped = _collect_urls(d)
    if skipped:
        print(f"check_links: {skipped} 件の equity 構成銘柄リンク(同型 finance.yahoo.com/quote/*)"
              f"はサンプル検査のため未検査（サイレント truncation ではなく明示）", flush=True)
    results = []
    ok = warn = 0
    for cat, sym, url in urls:
        if YAHOO_HOST in url:
            time.sleep(YAHOO_WAIT_S)   # 429 回避の必須待機
        code, note = _head(url)
        # 2xx/3xx は到達。429 とネットワークエラーは「警告」（誤検知しうる）。
        reachable = code is not None and 200 <= code < 400
        rate_limited = code == 429
        if reachable:
            ok += 1
            level = "ok"
        elif rate_limited:
            warn += 1
            level = "warn_rate_limited"
        else:
            warn += 1
            level = "warn"
        results.append({
            "category": cat, "symbol": sym, "url": url,
            "status_code": code, "note": note, "level": level,
        })

    rep = {
        "as_of_utc": _now(),
        "checked": len(urls),
        "equity_constituent_links_skipped": skipped,
        "ok": ok,
        "warn": warn,
        "policy": "CI warns only; rate-limit(429)/network errors never fail the job. "
                  "equity constituent Yahoo quote links are sampled (homogeneous), not silent.",
        "results": results,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(f"check_links: checked={len(urls)} ok={ok} warn={warn} → {OUT}")
    for r in results:
        if r["level"] != "ok":
            print(f"  [{r['level']}] {r['category']}/{r['symbol']} "
                  f"{r['status_code']} {r['url']}")
    return 0  # 常に 0（警告のみ）


if __name__ == "__main__":
    sys.exit(main())
