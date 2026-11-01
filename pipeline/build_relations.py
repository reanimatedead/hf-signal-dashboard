#!/usr/bin/env python3
"""pipeline/build_relations.py — yield×equity "balance" layer → docs/relations.json.

The 60/40 balance between stocks and bonds hinges on the SIGN of the stock-bond
correlation, and that sign is driven by REAL rates, not nominal (nominal = real +
breakeven, and those two push equities in opposite directions — see 3-0). So the
US line is the real yield (DFII10); nominal is a dashed toggle in the UI.

Four parts (3-1):
  1. ERP  — unavailable (no free daily index EPS; Shiller mirror stopped 2024-09)
  2. regime — 120d rolling corr of equity daily log-return × 10Y daily bp-change
  3. beta   — %/10bp sensitivity of Nasdaq100/Dow30/S&P500 (250d OLS slope)
  4. rebalance — quarter-end pension rebalance pressure (duration-8 approx)

Source asymmetry (documented in DATA_CONTRACT §12): US/JP equities come from FRED
(public: SP500 / NIKKEI225); EU equity has NO FRED series (STOXX50E/SX5E absent),
so it comes from yfinance (personal-use ToS). US alone has real yield + term
premium; EU/JP are nominal-only.

Standalone:
    python3 pipeline/build_relations.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
OUT = ROOT / "docs" / "relations.json"
DATA_JSON = ROOT / "docs" / "data.json"

from build_macro_v2 import fetch_fred, contextualize          # noqa: E402  (curl-based FRED + context)
from corr_sources import fetch_yf_closes, fetch_ecb_eu10y, fetch_mof_jgb_yields  # noqa: E402

WIN = 120          # correlation window (business days)
BETA_LOOKBACK = 250
SERIES_TAIL = 260  # points emitted per region for the chart


def _series(points_or_dict):
    """[{date,value}] or {date:value} → sorted pandas Series (DatetimeIndex)."""
    if isinstance(points_or_dict, list):
        d = {p["date"]: p["value"] for p in points_or_dict if p.get("value") is not None}
    else:
        d = dict(points_or_dict or {})
    if not d:
        return None
    s = pd.Series(d, dtype="float64")
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def _rolling_corr_last(equity, y10):
    """Latest 120d rolling corr of equity log-return × 10Y bp-change (inner join)."""
    df = pd.concat({"r": np.log(equity).diff(), "dy": y10.diff() * 100},
                   axis=1, join="inner").dropna()
    if len(df) < WIN:
        return None, 0, None
    roll = df["r"].rolling(WIN).corr(df["dy"]).dropna()
    return (round(float(roll.iloc[-1]), 3) if len(roll) else None), len(df), roll


def _period_avg(roll, index_series, start, end):
    """Average rolling-r over [start,end] (data-driven historical context)."""
    if roll is None:
        return None
    seg = roll[(roll.index >= start) & (roll.index <= end)]
    return round(float(seg.mean()), 3) if len(seg) else None


def regime_of(r):
    """(regime, label)。label もコード（表示文は UI 辞書）:
    unknown=相関を計算できません（データ不足） / growth_shock_dominant=成長ショック主導。債券が株のヘッジになる＝天秤が機能 /
    inflation_policy_shock_dominant=インフレ/政策ショック主導。株と債券が同時に落ちる＝天秤が壊れる / transition=移行期。符号が不安定"""
    if r is None:
        return ("unknown", "unknown")
    if r <= -0.20:
        return ("growth_shock_dominant", "growth_shock_dominant")
    if r >= 0.20:
        return ("inflation_policy_shock_dominant", "inflation_policy_shock_dominant")
    return ("transition", "transition")


def _beta(index_s, y10):
    j = pd.concat({"r": np.log(index_s).diff(), "dy": y10.diff() * 100},
                  axis=1, join="inner").dropna().tail(BETA_LOOKBACK)
    if len(j) < 30 or j["dy"].std() == 0:
        return None
    return round(float(np.polyfit(j["dy"], j["r"], 1)[0]) * 100 * 10, 3)


def _region_series(cols):
    """Inner-join the given {name: Series} on common business days; emit the last
    SERIES_TAIL rows as [{date, <name>...}]. No ffill (inner join)."""
    frame = pd.concat(cols, axis=1, join="inner").dropna(how="any")
    frame = frame.tail(SERIES_TAIL)
    out = []
    for ts, row in frame.iterrows():
        rec = {"date": ts.date().isoformat()}
        for name in cols:
            rec[name] = round(float(row[name]), 4)
        out.append(rec)
    return out


def main():
    now = datetime.now(timezone.utc)

    # ── fetch (US/JP: FRED public; EU equity: yfinance) ─────────────────────
    spx = _series(fetch_fred("SP500"))
    ndx = _series(fetch_fred("NASDAQ100"))
    dji = _series(fetch_fred("DJIA"))
    n225 = _series(fetch_fred("NIKKEI225"))
    dgs10 = _series(fetch_fred("DGS10"))
    dfii10 = _series(fetch_fred("DFII10"))
    tp10 = _series(fetch_fred("THREEFYTP10"))
    sx5e = _series(fetch_yf_closes(["^STOXX50E"]).get("^STOXX50E"))
    eu10 = _series(fetch_ecb_eu10y())
    jgb = fetch_mof_jgb_yields() or {}
    jp10 = _series((jgb.get("JGB10Y")))

    # ── part 2: correlation regime (US: SPX × DGS10) ────────────────────────
    r120, n_corr, roll = _rolling_corr_last(spx, dgs10) if (spx is not None and dgs10 is not None) else (None, 0, None)
    reg_key, reg_label = regime_of(r120)
    history = {}
    if roll is not None:
        history = {
            "covid_2020_03_2021_06": _period_avg(roll, spx, "2020-03-01", "2021-06-30"),
            "inflation_2022": _period_avg(roll, spx, "2022-01-01", "2022-12-31"),
            "last_1y": _period_avg(roll, spx, (now - pd.Timedelta(days=365)).strftime("%Y-%m-%d"),
                                   now.strftime("%Y-%m-%d")),
        }

    # ── part 3: beta (%/10bp) ───────────────────────────────────────────────
    beta = {
        "nasdaq100": _beta(ndx, dgs10) if (ndx is not None and dgs10 is not None) else None,
        "dow30": _beta(dji, dgs10) if (dji is not None and dgs10 is not None) else None,
        "sp500": _beta(spx, dgs10) if (spx is not None and dgs10 is not None) else None,
        "lookback_days": BETA_LOOKBACK,
        "unit": "percent_per_10bp",
        "note": "beta_note",   # 10bp 上昇に対する日次リターン%(直近250日 OLS 傾き)。Nasdaq 最敏感=デュレーション。Dow > SPX は教科書と逆。断定せず観測対象
    }

    # ── part 4: quarter-end rebalance (duration-8 approx) ───────────────────
    rebalance = {"data_status": "unavailable"}
    if spx is not None and dgs10 is not None:
        y = now.year
        q_start_month = ((now.month - 1) // 3) * 3 + 1
        qs = pd.Timestamp(y, q_start_month, 1)
        spx_q = spx[spx.index >= qs]
        y10_q = dgs10[dgs10.index >= qs]
        if len(spx_q) and len(y10_q):
            eq_ret = float(spx.iloc[-1] / spx_q.iloc[0] - 1)
            bond_ret = float(-8.0 * (dgs10.iloc[-1] - y10_q.iloc[0]) / 100)
            gap = eq_ret - bond_ret
            rebalance = {
                "data_status": "live",
                "quarter_start": qs.date().isoformat(),
                "eq_ret_pct": round(eq_ret * 100, 2),
                "bond_ret_pct": round(bond_ret * 100, 2),
                "gap_pct": round(gap * 100, 2),
                "pressure": "sell_equity_buy_bond" if gap > 0 else "buy_equity_sell_bond",
                "note": "rebalance_duration8_note",   # デュレーション8での近似。実際の年金比率と規模は非公開
            }

    # ── percentile context (reuse macro_v2.contextualize) ───────────────────
    ctx = {}
    if dgs10 is not None:
        c = contextualize(dgs10, round(float(dgs10.iloc[-1]), 4))
        c["speed_warning"] = bool(c.get("d20_z") is not None and abs(c["d20_z"]) >= 2.0)
        ctx["us_10y_nominal"] = c
    if dfii10 is not None:
        ctx["us_10y_real"] = contextualize(dfii10, round(float(dfii10.iloc[-1]), 4))

    # ── 3-region series (inner join, no ffill) ──────────────────────────────
    regions = {}
    us_cols = {k: v for k, v in {"equity": spx, "real_yield": dfii10, "nominal": dgs10}.items() if v is not None}
    regions["us"] = {
        "equity": "^GSPC", "equity_source": "FRED:SP500",
        "real_yield": "DFII10", "nominal": "DGS10", "term_premium": "THREEFYTP10",
        "yields": ["US2Y", "US10Y", "US30Y"],
        "asymmetry": "full_real_yield_term_premium",   # full (real yield + term premium available)
        "source": "FRED (public)",
        "data_status": "live" if len(us_cols) == 3 else "error",
        "series": _region_series(us_cols) if len(us_cols) == 3 else [],
    }
    eu_cols = {k: v for k, v in {"equity": sx5e, "nominal": eu10}.items() if v is not None}
    regions["eu"] = {
        "equity": "^STOXX50E", "equity_source": "yfinance",
        "real_yield": None, "nominal": "EU10Y", "term_premium": None,
        "yields": ["EU2Y", "EU10Y", "EU30Y"],
        "asymmetry": "nominal_only_us_asymmetric",   # nominal only — no free daily real yield / term premium
        "source": "yfinance + ECB Data Portal",
        "data_status": "live" if len(eu_cols) == 2 else "error",
        "series": _region_series(eu_cols) if len(eu_cols) == 2 else [],
    }
    jp_cols = {k: v for k, v in {"equity": n225, "nominal": jp10}.items() if v is not None}
    regions["jp"] = {
        "equity": "^N225", "equity_source": "FRED:NIKKEI225",
        "real_yield": None, "nominal": "JP10Y", "term_premium": None,
        "yields": ["JP2Y", "JP10Y", "JP30Y"],
        "asymmetry": "nominal_only_us_asymmetric",
        "source": "FRED + MoF JGB",
        "data_status": "live" if len(jp_cols) == 2 else "error",
        "series": _region_series(jp_cols) if len(jp_cols) == 2 else [],
    }

    payload = {
        "as_of": now.isoformat(),
        "align": "inner_join",
        "align_note": "inner_join_no_ffill_note",   # 共通営業日で inner join（dropna, 前方補完なし）。祝日不一致で共通日は各系列より少ない
        "balance": {
            "erp": {"value": None, "data_status": "unavailable",
                    "reason": "erp_no_free_daily_eps"},   # 指数の日次EPSに無料の信頼ソースがない。Shillerミラーは2024-09で停止
            "regime": {"r_120d": r120, "regime": reg_key, "label": reg_label,
                       "n_obs": n_corr, "history": history,
                       # 株価の日次対数リターン × 利回りの日次変化(bp) の120日ローリング相関。60/40 の前提はこの符号に依存
                       "note": "regime_corr_method_note"},
            "beta": beta,
            "rebalance": rebalance,
            "context": ctx,
        },
        "regions": regions,
        "source_asymmetry": {
            "us": "FRED (public)", "jp": "FRED (public)",
            "eu": "yfinance",   # equity yfinance (personal-use ToS) — FRED に STOXX50E/SX5E が存在しないため
            "note": "source_asymmetry_note",   # 米日株価は FRED、欧州株価は yfinance。実質金利・TP は米国のみ
        },
        "disclaimer": "disclaimer_data_viz_not_advice",   # For data visualization purposes only. Not investment advice.
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n✅ relations.json → {OUT} ({OUT.stat().st_size} B)")
    print(f"   regime r120={r120} ({reg_key})  beta N/D/S="
          f"{beta['nasdaq100']}/{beta['dow30']}/{beta['sp500']}  "
          f"rebalance gap={rebalance.get('gap_pct')} {rebalance.get('pressure')}")
    print(f"   series us/eu/jp = "
          f"{len(regions['us']['series'])}/{len(regions['eu']['series'])}/{len(regions['jp']['series'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
