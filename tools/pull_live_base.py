#!/usr/bin/env python3
"""tools/pull_live_base.py — rebuild the docs/ deploy base from the LIVE Pages
site for the corr_refresh job, then guard it (fail closed).

Under the Actions-deploy model, docs/data.json and docs/charts/*.json are NOT in
git. The corr_refresh job only recomputes correlations, so it must first
reconstruct the full docs/ payload from the currently-published site, validate
it, and only then let build_corr + deploy run. If the live base is
missing / stale / broken this exits 1, so the previous good deploy stays live
(deploy-pages keeps the last success on failure).

Chart tabs are DERIVED from the fetched data.json (tabs with >=1 ready row), not
hardcoded.

Guard (fail closed):
  - meta.updated_at within 48h
  - markets / summary / money_flow / survival_loop all present
  - every markets row carries chart_status
  - equity 4-tab ready rate >= 90%

Env:
  PAGES_BASE    live site base URL (default: the project's github.io URL)
  HF_DOCS_DIR   output dir (default: docs) — override for local testing

Usage:
  PAGES_BASE=https://user.github.io/repo python3 tools/pull_live_base.py
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

BASE = os.environ.get(
    "PAGES_BASE", "https://reanimatedead.github.io/hf-signal-dashboard").rstrip("/")
DOCS = os.environ.get("HF_DOCS_DIR", "docs")
EQUITY_TABS = ("nikkei225", "dow30", "nasdaq100", "sp500")


def _fetch(url, dest):
    urllib.request.urlretrieve(url, dest)
    return os.path.getsize(dest)


def main():
    os.makedirs(os.path.join(DOCS, "charts"), exist_ok=True)

    # ── 1. pull data.json ───────────────────────────────────────────────────
    try:
        n = _fetch(f"{BASE}/data.json", os.path.join(DOCS, "data.json"))
        print(f"fetched data.json {n} B from {BASE}")
    except Exception as e:
        print(f"BASE PULL FAIL: cannot fetch {BASE}/data.json: {e}")
        return 1
    d = json.load(open(os.path.join(DOCS, "data.json"), encoding="utf-8"))

    # ── pull required charts (derived from data.json, not hardcoded) ─────────
    need = sorted(t for t, rows in d.get("markets", {}).items()
                  if any(r.get("chart_status") == "ready" for r in rows))
    for tab in need:
        try:
            n = _fetch(f"{BASE}/charts/{tab}.json",
                       os.path.join(DOCS, "charts", f"{tab}.json"))
            print(f"fetched charts/{tab}.json {n} B")
        except Exception as e:
            print(f"BASE PULL FAIL: required charts/{tab}.json missing: {e}")
            return 1

    # ── 2. guard (fail closed) ──────────────────────────────────────────────
    errs = []
    age_h = None
    try:
        u = datetime.fromisoformat(str(d["meta"]["updated_at"]))
        if u.tzinfo is None:
            u = u.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - u).total_seconds() / 3600
        if age_h > 48:
            errs.append(f"meta.updated_at stale: {age_h:.1f}h > 48h")
    except Exception as e:
        errs.append(f"meta.updated_at unreadable: {e}")

    for k in ("markets", "summary", "money_flow", "survival_loop"):
        if k not in d:
            errs.append(f"missing top-level key: {k}")

    miss = [(m, r.get("symbol")) for m, rows in d.get("markets", {}).items()
            for r in rows if "chart_status" not in r]
    if miss:
        errs.append(f"{len(miss)} rows missing chart_status (e.g. {miss[:3]})")

    tot = rdy = 0
    for tab in EQUITY_TABS:
        rows = d.get("markets", {}).get(tab, [])
        tot += len(rows)
        rdy += sum(1 for r in rows if r.get("chart_status") == "ready")
    pct = (rdy / tot * 100) if tot else 0.0
    if tot and pct < 90:
        errs.append(f"equity ready {pct:.1f}% < 90%")

    if errs:
        print("BASE GUARD FAIL:")
        for e in errs:
            print("  -", e)
        return 1
    age_str = f"{age_h:.1f}h" if age_h is not None else "n/a"
    print(f"base guard OK: ready {pct:.1f}%, updated {age_str} ago, "
          f"{len(need)} chart tabs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
