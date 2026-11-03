#!/usr/bin/env python3
"""tools/build_about.py — docs/about.json（仕組み（About）タブと AI 向けの1ファイル要約）を作る。

中身は src/screener/about.py が コード（ind.P・判定の規則・総合スコアの表・deploy.yml の cron）と
生成物（docs/data.json の meta・docs/verify.json）から組み立てる。git にはコミットしない（.gitignore）。
deploy.yml の full / corr_refresh の公開の作業で毎回作り直す。

使い方: python3 tools/build_about.py [--docs DOCS_DIR]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screener import about  # noqa: E402


def _load(p: pathlib.Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"  [about] {p.name}: {type(e).__name__}（その部分は available=false）")
        return None


def write(docs: pathlib.Path) -> pathlib.Path:
    data = _load(docs / "data.json")
    verify = _load(docs / "verify.json")
    a = about.build((data or {}).get("meta"), verify)
    out = docs / "about.json"
    out.write_text(json.dumps(a, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"✓ about.json → {out} ({out.stat().st_size:,} B) commit={a['commit']['sha']} "
          f"meta={a['meta'].get('available')} verify={a['verify'].get('available')} next={a['schedule']['next']}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default=str(ROOT / "docs"))
    write(pathlib.Path(ap.parse_args().docs))
