#!/usr/bin/env python3
"""tools/build_preview.py — 架空データでサイトのプレビューを組み立てる（通信なし）。

docs/ の静的ファイル（index.html・assets）をコピーし、tests/screener/calc/fixtures の
**架空 5 銘柄**（AAA〜EEE、本物の銘柄・本物の価格ではない）から、本番と同じ関数
（fetch_signals.process_ticker / attach_equity_charts / split_chart_payload /
build_and_write_verify / attach_us_fundamentals / record_payload_size）で
data.json・charts/*.json・verify.json を作る。日経225 タブも同じ架空系列（コードは FAKE1.T 等）。

使い方:
    python3 tools/build_preview.py OUT_DIR [--hours-ago 50]
    python3 -m http.server -d OUT_DIR 8765   →   node tools/preview_screens.mjs http://127.0.0.1:8765 SHOTS_DIR
--hours-ago: meta.updated_at を何時間前にするか（既定 50 = 48h 警告が出る状態を見せる）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fetch_signals as fs  # noqa: E402
from marketcalc import fund_us  # noqa: E402
from tests._fake_market import TICKERS, facts, frame  # noqa: E402

GENERATED = ("data.json", "charts", "verify.json", "health.json", "macro_v2.json", "relations.json", "gamma.json")


def build(out, hours_ago=50.0):
    out = pathlib.Path(out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} が空ではありません（上書きしない）")
    shutil.copytree(ROOT / "docs", out, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(*GENERATED, "_spec", "_ops_notes"))
    frames = {t: frame(t) for t in TICKERS}
    jp = {f"FAKE{i}.T": t for i, t in enumerate(TICKERS, 1)}
    frames.update({k: frames[t] for k, t in jp.items()})
    # 2026-11 UI 検証: 日経225 の 7735.T（コードだけ本物・価格は架空 BBB×50）と FX 1 本（架空 AAA を 150 円台へ）
    frames["7735.T"] = _scaled(frames["BBB"], 50.0)
    frames["USDJPY=X"] = _scaled(frames["AAA"], 150.0 / float(frames["AAA"]["Close"].iloc[-1]))
    fs._batched_2y_ohlc = lambda syms, **k: {s: frames.get(s) for s in syms}   # 通信しない

    def rows(syms, label):
        return [fs.process_ticker(frames[s].tail(126), s, f"FAKE {s} ({label})") for s in syms]
    markets_eq = {"nikkei225": rows(list(jp) + ["7735.T"], "JP"), "dow30": rows(TICKERS[:2], "US"),
                  "nasdaq100": rows(TICKERS, "US"), "sp500": rows(TICKERS, "US")}
    collect = {}
    fs.attach_equity_charts(markets_eq, collect=collect)
    vrec = fs.build_and_write_verify(collect, out / "verify.json")
    fd = {t: {**fund_us.fundamentals(facts(t)["facts"], "2025-12-31"), "fin": t == "EEE"} for t in TICKERS}
    fpath = out / "_us_fundamentals_fake.json"
    fpath.write_text(json.dumps({"as_of": "2025-12-31", "rows": fd}))
    urec = fs.attach_us_fundamentals((markets_eq["dow30"], markets_eq["nasdaq100"], markets_eq["sp500"]), fpath)
    fpath.unlink()
    now = datetime.now(fs.JST) - timedelta(hours=hours_ago)
    uni = {tab: {"count": len([r for r in rs if not r["symbol"].startswith("^")]), "target": fs.EQUITY_TARGETS[tab],
                 "capture_pct": 0, "defined": len(rs), "source_mode": "curated_subset",
                 "universe_source": "preview", "fetch_failures": []} for tab, rs in markets_eq.items()}
    payload = {
        "meta": {"updated_at": now.isoformat(), "updated_at_str": now.strftime("%Y-%m-%d %H:%M JST"),
                 "next_update_str": "—", "preview": "preview_fake_data",   # 架空データ（本物の銘柄・価格ではない）
                 "counts": {k: len(v) for k, v in markets_eq.items()}, "universe": uni, "fallbacks": [],
                 "stale_hours": fs._stale_hours(), "verify": vrec, "us_fundamentals": urec},
        "summary": {k: fs.build_summary(v) for k, v in markets_eq.items()},
        "markets": {**markets_eq, "fx": [_fake_fx(frames["USDJPY=X"], now.isoformat())],
                    "rates": [], "volatility": [], "imm": [], "crypto": [], "valuation": []},
    }
    payload["summary"]["fx"] = fs.build_summary(payload["markets"]["fx"])
    _write_fake_layers(out, frames["AAA"])
    payload = fs._json_safe(payload)
    fs.split_chart_payload(payload, out)
    ps = fs.record_payload_size(payload, out)
    print(f"preview: {out} initial={ps['initial_bytes']:,}B total={ps['total_bytes']:,}B verify={vrec}")
    return out


def _scaled(df, k):
    out = df.copy()
    for c in ("Open", "High", "Low", "Close"):
        out[c] = out[c] * k
    return out


def _fake_fx(df, now_iso):
    """FX タブ 1 行（架空）。process_ticker の指標 + FX 列 + 本番と同じ attach_charts_to_symbol の 1d チャート。"""
    row = fs.process_ticker(df.tail(126), "USDJPY", "FAKE USD/JPY")
    row.update({"signal": "neutral", "mc_probability": 50.0, "mc_valid": True,
                "cci_daily": row.get("cci48") if row.get("cci48") is not None else 0.0, "cci_4h": 0.0})
    return fs.attach_charts_to_symbol(row, df, 3, now_iso)


def _write_fake_layers(out, df):
    """relations / macro_v2 / gamma の架空版（形だけ本番と同じ・値は架空 AAA 由来）。
    プレビューで 404（= ブラウザのコンソールエラー）にしないため。本物の値ではない。"""
    c = [float(v) for v in df["Close"].tail(260)]
    dates = [d.strftime("%Y-%m-%d") for d in df.index[-260:]]
    ser = [{"date": d, "equity": v, "nominal": 4 + (v - c[0]) / c[0], "real_yield": 1.8 + (v - c[0]) / c[0] / 2}
           for d, v in zip(dates, c)]
    reg = lambda real: {"data_status": "live", "source": "FRED (public)", "equity_source": "FRED:SP500",
                        "series": [dict(p, real_yield=p["real_yield"] if real else None) for p in ser]}
    rel = {"preview": "preview_fake_data", "regions": {"us": reg(True), "eu": reg(False), "jp": reg(False)},
           "balance": {"regime": {"r_120d": -0.31, "label": "growth_shock_dominant", "n_obs": 120,
                                  "history": {"covid_2020_03_2021_06": -0.4, "inflation_2022": 0.35, "last_1y": -0.2}},
                       "beta": {"nasdaq100": -0.42, "dow30": -0.25, "sp500": -0.3, "lookback_days": 250},
                       "rebalance": {"data_status": "live", "pressure": "sell_equity_buy_bond", "eq_ret_pct": 2.1,
                                     "bond_ret_pct": -0.8, "gap_pct": 2.9},
                       "context": {"us_10y_nominal": {"value": 4.21, "pct_rank": 78, "d20_z": 0.6}},
                       "erp": {"reason": "erp_no_free_daily_eps"}}}
    s = lambda cat, v, lab: {"category": cat, "data_status": "live", "value": v, "label": lab,
                              "context": {"pct_rank": 60, "z": 0.4, "d20_z": 0.2}}
    mac = {"preview": "preview_fake_data",
           "series": {"DGS10": s("rates_decomp", 4.21, "us10y_nominal"), "DFII10": s("rates_decomp", 1.9, "us10y_real_tips"),
                      "BAMLH0A0HYM2": s("credit", 3.1, "us_hy_oas"), "SOFR": s("funding", 4.3, "sofr"),
                      "NFCI": s("conditions", -0.5, "chicago_fed_nfci"), "SAHMREALTIME": s("recession", 0.2, "sahm_rule")},
           "identities": {"fisher": {"nominal": 4.21, "real": 1.9, "breakeven": 2.3, "gap": 0.01},
                          "expectations": {"nominal": 4.21, "term_premium": 0.5, "value": 3.71}},
           "net_liquidity": {"primary": {"value_tn": 3.2}, "reference": {"value_tn": 5.8, "components_tn": {"RRP": 0.1}}}}
    gam = {"preview": "preview_fake_data", "data_status": "live", "gex_oi_bn": 1.2, "zero_gamma": 5800.0, "spot": 5900.0,
           "flip_vs_spot": "above_flip_dampening", "n_contracts_oi": 1000, "n_0dte_contracts": 0,
           "snapshot": {"source": "preview"}, "note": "naive_dealer_assumption_note", "assumption": "dealer_long_call_short_put",
           "gex_volume_0dte_status": "unavailable", "gex_volume_0dte_reason": "delayed_snapshot_no_0dte",
           "gamma_walls": [{"strike": 5900 + 25 * i, "gex_bn": 0.3 - 0.1 * i} for i in range(6)],
           "vol_structure": {"vix3m_vix_ratio": 1.12, "term_state": "contango", "skew": 140.0, "move_vix_ratio": 5.5},
           "coverage": {"us": "live", "eu": "unavailable", "jp": "unavailable"}}
    for name, obj in (("relations.json", rel), ("macro_v2.json", mac), ("gamma.json", gam)):
        (out / name).write_text(json.dumps(obj))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--hours-ago", type=float, default=50.0)
    a = ap.parse_args(argv)
    build(a.out, a.hours_ago)
    return 0


if __name__ == "__main__":
    sys.exit(main())
