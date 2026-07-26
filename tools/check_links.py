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


def _collect_urls(d):
    """(category, symbol, url) を markets 全行の link.url について列挙（重複 url は 1 回）。"""
    seen = set()
    out = []
    for cat, rows in (d.get("markets") or {}).items():
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                continue
            url = ((r.get("link") or {}).get("url")) or ""
            if not url or not url.startswith(("http://", "https://")):
                continue
            if url in seen:
                continue
            seen.add(url)
            out.append((cat, r.get("symbol", "?"), url))
    return out


def _head(url):
    """HEAD リクエスト。(status_code:int|None, note:str) を返す。"""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status, "ok"
    except urllib.error.HTTPError as e:
        # 一部サーバは HEAD を 405 で返す → GET で再確認（軽量に）。
        if e.code in (403, 405):
            try:
                greq = urllib.request.Request(
                    url, method="GET", headers={"User-Agent": UA})
                with urllib.request.urlopen(greq, timeout=TIMEOUT_S) as resp:
                    return resp.status, "ok_via_get"
            except urllib.error.HTTPError as e2:
                return e2.code, "http_error"
            except Exception as e2:  # noqa: BLE001
                return None, f"error:{type(e2).__name__}"
        return e.code, "http_error"
    except Exception as e:  # noqa: BLE001
        return None, f"error:{type(e).__name__}"


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

    urls = _collect_urls(d)
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
        "ok": ok,
        "warn": warn,
        "policy": "CI warns only; rate-limit(429)/network errors never fail the job",
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
