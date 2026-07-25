#!/usr/bin/env python3
"""pipeline/build_macro_v2.py — v2 macro layer → docs/macro_v2.json.

NOTE ON NAMING: this is docs/macro_v2.json, distinct from the legacy
docs/data/macro.json (produced by pipeline/build_macro.py). See DATA_CONTRACT.md
§11/§12: the legacy tracked copy is frozen; this v2 layer is generated fresh by
deploy.yml full and is NOT committed to git.

Fetches 16 daily FRED series (keyless CSV), attaches a percentile/z context to
every series, embeds the Fisher identity and the term-premium decomposition of
the 10Y, and reworks net_liquidity to make WRESBAL (bank reserves) the primary
gauge with the SNS-style WALCL-TGA-RRP formula kept only as a reference.

Standalone:
    python3 pipeline/build_macro_v2.py
"""
import csv
import io
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "macro_v2.json"

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"
_UA = {"User-Agent": "hf-signal-dashboard macro_v2 (FRED keyless)"}

# 16 daily series: id -> (label, category)
FRED_SERIES = {
    # decomposition (Fisher / term-premium identity)
    "DGS10":        ("US 10Y nominal",        "rates_decomp"),
    "DFII10":       ("US 10Y real (TIPS)",    "rates_decomp"),
    "T10YIE":       ("10Y breakeven",         "rates_decomp"),
    "THREEFYTP10":  ("10Y term premium",      "rates_decomp"),
    # credit
    "BAMLH0A0HYM2": ("US HY OAS",             "credit"),
    "BAMLC0A0CM":   ("US IG OAS",             "credit"),
    # funding
    "SOFR":         ("SOFR",                  "funding"),
    "IORB":         ("IORB",                  "funding"),
    "SOFR99":       ("SOFR 99th pct",         "funding"),
    "WRESBAL":      ("Bank reserves",         "funding"),
    # conditions / regime
    "NFCI":         ("Chicago Fed NFCI",      "conditions"),
    "ANFCI":        ("Adjusted NFCI",         "conditions"),
    "STLFSI4":      ("StL Fed Fin Stress",    "conditions"),
    "DTWEXBGS":     ("Broad Dollar Index",    "conditions"),
    # recession
    "T10Y3M":       ("10Y-3M spread",         "recession"),
    "SAHMREALTIME": ("Sahm rule",             "recession"),
}

# extra series only for the reference net_liquidity formula (WALCL-TGA-RRP)
NL_EXTRA = {
    "WALCL":     "Fed total assets",           # millions of USD
    "WTREGEN":   "Treasury General Account",   # billions of USD
    "RRPONTSYD": "Overnight RRP",              # billions of USD
}


def _fred_csv_text(series_id, timeout=30):
    """Fetch FRED CSV text. curl (default UA) is primary: LibreSSL 2.8.3 on the
    mac hangs the requests/urllib TLS handshake to FRED's Akamai CDN, while curl
    succeeds in ~100ms; CI ubuntu (OpenSSL 3) also has curl. A custom UA makes
    Akamai reset the stream, so we pass NO -A. urllib is a last-ditch fallback."""
    url = FRED_CSV.format(id=series_id)
    try:
        proc = subprocess.run(["curl", "-s", "-m", str(timeout), "--fail", url],
                              capture_output=True, timeout=timeout + 5)
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", errors="replace")
    except Exception:
        pass
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def fetch_fred(series_id, retries=3):
    """FRED keyless CSV → [{date, value}] (full history). '.' rows skipped.
    Retries a few times. [] on final failure (never raises)."""
    for attempt in range(1, retries + 1):
        body = _fred_csv_text(series_id)
        if body:
            out = []
            for row in csv.DictReader(io.StringIO(body)):
                keys = list(row.keys())
                d = row[keys[0]]
                v = row.get(series_id) if series_id in row else row.get(keys[1])
                if v in (".", "", None):
                    continue
                try:
                    out.append({"date": d, "value": float(v)})
                except ValueError:
                    continue
            if out:
                return out
        if attempt < retries:
            time.sleep(1.0 * attempt)
    print(f"  [FRED] {series_id} fetch failed after {retries} tries")
    return []


def _to_series(points):
    if not points:
        return None
    s = pd.Series({p["date"]: p["value"] for p in points}, dtype="float64")
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def contextualize(series, value, lookback=1250):
    """Position `value` inside the series' own recent history: percentile rank,
    z-score, 20-observation change and its z. Rounds defensively; None on
    insufficient data."""
    s = series.dropna().tail(lookback)
    if len(s) < 20 or s.std() == 0:
        return {"value": value, "pct_rank": None, "z": None,
                "d20_change": None, "d20_z": None, "n_obs": int(len(s))}
    d20 = series.diff(20)
    d20_tail = d20.tail(lookback).dropna()
    d20_last = d20.iloc[-1] if len(d20) and pd.notna(d20.iloc[-1]) else None
    d20_z = None
    if d20_last is not None and len(d20_tail) >= 2 and d20_tail.std() != 0:
        d20_z = round((d20_last - d20_tail.mean()) / d20_tail.std(), 2)
    return {
        "value": value,
        "pct_rank": round(float((s < value).mean() * 100)),
        "z": round(float((value - s.mean()) / s.std()), 2),
        "d20_change": round(float(d20_last), 4) if d20_last is not None else None,
        "d20_z": d20_z,
        "n_obs": int(len(s)),
    }


def check_fisher(nominal, real, breakeven, tol=0.05):
    """名目 = 実質 + 期待インフレ。ズレたらデータ不整合を疑う。"""
    if None in (nominal, real, breakeven):
        return {"ok": None, "gap": None, "reason": "missing input"}
    gap = abs(nominal - (real + breakeven))
    return {"ok": bool(gap <= tol), "gap": round(gap, 4),
            "nominal": nominal, "real": real, "breakeven": breakeven}


def main():
    now = datetime.now(timezone.utc)
    series_out, latest = {}, {}
    for sid, (label, cat) in FRED_SERIES.items():
        pts = fetch_fred(sid)
        s = _to_series(pts)
        if s is None or len(s) < 2:
            series_out[sid] = {"label": label, "category": cat, "value": None,
                               "as_of": None, "data_status": "error",
                               "context": None}
            latest[sid] = None
            continue
        val = round(float(s.iloc[-1]), 4)
        latest[sid] = val
        series_out[sid] = {
            "label": label, "category": cat, "value": val,
            "as_of": s.index[-1].date().isoformat(), "data_status": "live",
            "context": contextualize(s, val),
        }
        print(f"  {sid:13} {val:>12}  ({series_out[sid]['as_of']})")

    # ── identities ──────────────────────────────────────────────────────────
    fisher = check_fisher(latest.get("DGS10"), latest.get("DFII10"), latest.get("T10YIE"))
    tp = latest.get("THREEFYTP10")
    nom = latest.get("DGS10")
    expectations = (round(nom - tp, 4) if (nom is not None and tp is not None) else None)
    identities = {
        "fisher": fisher,
        "expectations": {
            "value": expectations, "nominal": nom, "term_premium": tp,
            "note": ("名目 = 利上げ予想(expectations) + ターム・プレミアム(risk premium)。"
                     "同じ名目でも内訳で株への効き方が違うため両方を出す。"),
        },
    }

    # ── net_liquidity: WRESBAL primary, WALCL-TGA-RRP reference ──────────────
    nl_extra = {k: _to_series(fetch_fred(k)) for k in NL_EXTRA}
    def _last_tn(s, div):
        return round(float(s.iloc[-1]) / div, 4) if (s is not None and len(s)) else None
    wresbal_tn = _last_tn(_to_series(fetch_fred("WRESBAL")), 1e6)  # WRESBAL: millions → tn
    walcl_tn = _last_tn(nl_extra["WALCL"], 1e6)                     # WALCL: millions → tn
    tga_tn = _last_tn(nl_extra["WTREGEN"], 1e6)                     # WTREGEN(TGA): millions → tn
    rrp_tn = _last_tn(nl_extra["RRPONTSYD"], 1e3)                   # RRPONTSYD: billions → tn
    simple = (round(walcl_tn - tga_tn - rrp_tn, 4)
              if None not in (walcl_tn, tga_tn, rrp_tn) else None)
    wresbal_s = _to_series(fetch_fred("WRESBAL"))
    net_liquidity = {
        "primary_metric": "WRESBAL",
        "primary": {
            "metric": "WRESBAL", "label": "Bank reserves (trillions USD)",
            "value_tn": wresbal_tn,
            "context": (contextualize(wresbal_s / 1e6, wresbal_tn) if wresbal_s is not None else None),
            "note": "準備預金残高。RRP がほぼ枯渇した現在の第一指標。",
        },
        "reference": {
            "metric": "WALCL - TGA - RRP", "value_tn": simple,
            "components_tn": {"WALCL": walcl_tn, "TGA": tga_tn, "RRP": rrp_tn},
            "note": ("SNS 由来の簡易式。参考値。RRP は約 {} 兆ドルでほぼ枯渇し情報量が乏しい。"
                     .format(rrp_tn if rrp_tn is not None else "n/a")),
        },
        "which_is_primary": "WRESBAL",
    }

    payload = {
        "as_of": now.isoformat(),
        "as_of_date": now.date().isoformat(),
        "source": "FRED (keyless CSV)",
        "series": series_out,
        "identities": identities,
        "net_liquidity": net_liquidity,
        "coverage": {"note": "US-only macro layer (FRED). EU yields live in markets.rates via ECB."},
        "disclaimer": "For data visualization purposes only. Not investment advice.",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    n_live = sum(1 for v in series_out.values() if v["data_status"] == "live")
    print(f"\n✅ macro_v2.json → {OUT} ({OUT.stat().st_size} B)  "
          f"series live={n_live}/{len(FRED_SERIES)}  fisher={fisher.get('ok')} gap={fisher.get('gap')}  "
          f"expectations={expectations}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
