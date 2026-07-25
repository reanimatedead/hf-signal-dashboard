#!/usr/bin/env python3
"""tools/health_gate.py — deploy health gate.

Reads a data.json, evaluates FAIL/WARN checks, writes <dir>/health.json, prints a
summary, and exits 1 on any FAIL (0 on PASS/WARN). Used by .github/workflows/
deploy.yml between generation and upload so a broken/stale payload never
overwrites the live site (deploy-pages keeps the previous good deploy on failure).

Runnable standalone:
    PYTHONPATH=. python3 tools/health_gate.py [path/to/data.json]

Checks (A-Ⅰ-2):
  FAIL (exit 1 if any):
    - us_rates lag  > 3d
    - jgb lag       > 5d
    - fred_daily lag> 4d
    - equity 4-tab ready rate < 90%
    - data.json missing any of markets / summary / money_flow / survival_loop
  WARN (exit 0, logged):
    - boj_assets lag > 45d
    - imm lag        > 12d

Freshness reference — honest-limitation note: the current data.json schema stores
NO per-observation date on the US-rate / JGB / FRED-daily rows (they are live /
auto series refetched every pipeline run). us_rates/jgb/fred_daily lag is therefore
measured against meta.updated_at (the pipeline run date), i.e. it catches a stale
DEPLOY, not a stale individual observation. boj_assets and imm DO carry real dates
and are measured directly. Once the macro layer (macro_v2.json / relations.json)
lands with dated series, tighten these to true per-observation dates.
"""
import json
import os
import sys
from datetime import datetime, timezone

DATA = sys.argv[1] if len(sys.argv) > 1 else "docs/data.json"
OUT = os.path.join(os.path.dirname(DATA) or ".", "health.json")

FAIL_LAG = {"us_rates": 3, "jgb": 5, "fred_daily": 4}
WARN_LAG = {"boj_assets": 45, "imm": 12}
READY_MIN_PCT = 90.0
REQUIRED_TOP = ("markets", "summary", "money_flow", "survival_loop")
EQUITY_TABS = ("nikkei225", "dow30", "nasdaq100", "sp500")


def _today():
    return datetime.now(timezone.utc).date()


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except Exception:
        return None


def _lag(dt):
    return None if dt is None else max(0, (_today() - dt).days)


def evaluate(d):
    checks = []
    fails = []
    warns = []

    def add(name, level, status, detail):
        checks.append({"name": name, "level": level, "status": status, "detail": detail})
        if status == "fail":
            fails.append(name)
        elif status in ("warn", "unknown"):
            warns.append(name)

    # 1) structural completeness (FAIL)
    missing = [k for k in REQUIRED_TOP if k not in d]
    if missing:
        add("structure", "FAIL", "fail", f"missing top-level keys: {missing}")
    else:
        add("structure", "FAIL", "pass",
            "markets/summary/money_flow/survival_loop present")

    # 2) equity chart coverage (FAIL if < 90%)
    tot = rdy = 0
    per = {}
    for tab in EQUITY_TABS:
        rows = (d.get("markets") or {}).get(tab, [])
        r = sum(1 for x in rows if x.get("chart_status") == "ready")
        per[tab] = f"{r}/{len(rows)}"
        tot += len(rows)
        rdy += r
    pct = (rdy / tot * 100) if tot else 0.0
    if tot and pct < READY_MIN_PCT:
        add("equity_ready", "FAIL", "fail", f"{pct:.1f}% < {READY_MIN_PCT}% {per}")
    else:
        add("equity_ready", "FAIL", "pass", f"{pct:.1f}% >= {READY_MIN_PCT}% {per}")

    # freshness reference for live/auto-refetched series = pipeline run date.
    run_dt = _parse_date((d.get("meta") or {}).get("updated_at"))
    run_lag = _lag(run_dt)

    # 3) us_rates / jgb / fred_daily lag (FAIL) — proxied by pipeline run date.
    for name, thr in FAIL_LAG.items():
        if run_lag is None:
            add(name, "FAIL", "unknown", "meta.updated_at missing/unparseable")
        elif run_lag > thr:
            add(name, "FAIL", "fail",
                f"pipeline lag {run_lag}d > {thr}d (ref: meta.updated_at)")
        else:
            add(name, "FAIL", "pass",
                f"pipeline lag {run_lag}d <= {thr}d (ref: meta.updated_at)")

    # 4) boj_assets lag (WARN) — real per-series date/lag.
    boj = ((d.get("money_flow") or {}).get("jp") or {}).get("cb_assets") or {}
    boj_lag = boj.get("lag_days")
    if boj_lag is None:
        boj_lag = _lag(_parse_date(boj.get("as_of")))
    if boj_lag is None:
        add("boj_assets", "WARN", "unknown", "no cb_assets date")
    elif boj_lag > WARN_LAG["boj_assets"]:
        add("boj_assets", "WARN", "warn", f"lag {boj_lag}d > {WARN_LAG['boj_assets']}d")
    else:
        add("boj_assets", "WARN", "pass", f"lag {boj_lag}d <= {WARN_LAG['boj_assets']}d")

    # 5) imm lag (WARN) — CFTC COT weekly; real per-row date.
    imm_dates = [x for x in
                 (_parse_date(r.get("date")) for r in (d.get("markets") or {}).get("imm", []))
                 if x]
    imm_lag = _lag(max(imm_dates)) if imm_dates else None
    if imm_lag is None:
        add("imm", "WARN", "unknown", "no imm date")
    elif imm_lag > WARN_LAG["imm"]:
        add("imm", "WARN", "warn", f"lag {imm_lag}d > {WARN_LAG['imm']}d")
    else:
        add("imm", "WARN", "pass", f"lag {imm_lag}d <= {WARN_LAG['imm']}d")

    # fails/warns may repeat names via add(); de-dup while keeping only real fails.
    real_fails = [c["name"] for c in checks if c["status"] == "fail"]
    real_warns = [c["name"] for c in checks if c["status"] in ("warn", "unknown")]
    status = "FAIL" if real_fails else ("WARN" if real_warns else "PASS")
    return {
        "status": status,
        "generated_from": DATA,
        "as_of_utc": _today().isoformat(),
        "fails": real_fails,
        "warns": real_warns,
        "checks": checks,
        "notes": [
            "us_rates/jgb/fred_daily lag is proxied by meta.updated_at (pipeline "
            "run date): the schema has no per-observation date on those rows. This "
            "catches a stale deploy, not a stale single observation.",
            "boj_assets and imm use real per-series dates.",
        ],
    }


def main():
    try:
        d = json.load(open(DATA, encoding="utf-8"))
    except Exception as e:
        rep = {"status": "FAIL", "error": f"cannot read {DATA}: {e}",
               "fails": ["read"], "warns": [], "checks": []}
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        print(json.dumps(rep, ensure_ascii=False))
        return 1
    rep = evaluate(d)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    print(f"\nhealth_gate: {rep['status']}  fails={rep['fails']}  "
          f"warns={rep['warns']}  → {OUT}")
    return 1 if rep["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
