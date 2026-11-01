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
    fs._batched_2y_ohlc = lambda syms, **k: {s: frames.get(s) for s in syms}   # 通信しない

    def rows(syms, label):
        return [fs.process_ticker(frames[s].tail(126), s, f"架空銘柄 {s}（{label}・fake）") for s in syms]
    markets_eq = {"nikkei225": rows(list(jp), "日本"), "dow30": rows(TICKERS[:2], "米国"),
                  "nasdaq100": rows(TICKERS, "米国"), "sp500": rows(TICKERS, "米国")}
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
                 "next_update_str": "—", "preview": "架空データ（tools/build_preview.py）。本物の銘柄・価格ではありません。",
                 "counts": {k: len(v) for k, v in markets_eq.items()}, "universe": uni, "fallbacks": [],
                 "stale_hours": fs._stale_hours(), "verify": vrec, "us_fundamentals": urec},
        "summary": {k: fs.build_summary(v) for k, v in markets_eq.items()},
        "markets": {**markets_eq, "fx": [], "rates": [], "volatility": [], "imm": [], "crypto": [], "valuation": []},
    }
    payload = fs._json_safe(payload)
    fs.split_chart_payload(payload, out)
    ps = fs.record_payload_size(payload, out)
    print(f"preview: {out} initial={ps['initial_bytes']:,}B total={ps['total_bytes']:,}B verify={vrec}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--hours-ago", type=float, default=50.0)
    a = ap.parse_args(argv)
    build(a.out, a.hours_ago)
    return 0


if __name__ == "__main__":
    sys.exit(main())
