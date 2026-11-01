"""公開 JSON に表示文（日本語・英語の文）を入れない（2026-11 A-2）。

data.json / charts/*.json / verify.json / health.json / docs/data/*.json の文字列値はコード（snake_case）か、
数値・日付・記号・固有名・識別子だけ。言葉は UI の辞書（docs/assets/i18n/dict.js）が持つ。

- 架空データの公開ペイロードを tools/build_preview.build で作り（通信なし）、全 JSON を歩く。
- プレビューが通らない経路（金利・IMM・バリュエーション・USDJPY の edge_context・リンク・money_flow・
  survival_loop・health.json・relations の regime）は、同じ関数を架空入力で呼んで同じ検査をかける。
- 追跡下の docs/data/*.json(l)（バックテスト等の公開結果）も検査する。

判定: 文字列値に 日本語文字（[぀-ヿ㐀-鿿]）がある、または英字の単語が空白区切りで 3 つ以上続く → 失敗。
例外は ALLOW_KEYS（固有名・識別子を持つキー）だけ。最小限に保つこと。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JP = re.compile(r"[぀-ヿ㐀-鿿]")
EN_PHRASE = re.compile(r"[A-Za-z][A-Za-z'\-]*\s+[A-Za-z][A-Za-z'\-]*\s+[A-Za-z][A-Za-z'\-]*")

# 値が固有名・識別子のキー（翻訳しない）。ここに表示文用のキーを足さないこと。
ALLOW_KEYS = {
    "name",           # 銘柄・指数・系列の固有名（"Toyota Motor" / "US 10Y Treasury Yield"）
    "symbol", "ticker", "source_ticker",
    "source", "equity_source", "sources", "universe_source",   # データ提供元の識別子（"FRED (fredgraph.csv): DGS10"）
    "url", "file", "path", "generated_from",
}


def offenders(obj, where: str = "", key: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += offenders(v, f"{where}.{k}", str(k))
    elif isinstance(obj, list):
        for v in obj:
            out += offenders(v, f"{where}[]", key)
    elif isinstance(obj, str) and key not in ALLOW_KEYS:
        if JP.search(obj) or EN_PHRASE.search(obj):
            out.append(f"{where} = {obj[:80]!r}")
    return out


def assert_clean(obj, where):
    bad = sorted(set(offenders(obj, where)))
    assert not bad, "表示文がデータに入っている（コードにすること・codes.json 参照）:\n" + "\n".join(bad[:40])


def test_detector_itself():
    assert offenders({"note": "Not investment advice."})
    assert offenders({"label": "強い買い"})
    assert offenders({"x": ["Market context only here"]})
    assert not offenders({"note": "disclaimer_not_advice", "state": "normal_or_steepening", "signal": "buy_strong"})
    assert not offenders({"name": "Toyota Motor Corp", "source": "FRED (fredgraph.csv): DGS10", "v": 1.5, "d": "2026-11-01"})


@pytest.fixture(scope="module")
def preview(tmp_path_factory):
    from tools import build_preview

    out = tmp_path_factory.mktemp("preview") / "site"
    build_preview.build(out)
    return out


def test_preview_payload_files_have_no_display_text(preview):
    files = [preview / "data.json", preview / "verify.json", *sorted((preview / "charts").glob("*.json"))]
    assert len(files) >= 4
    for p in files:
        assert_clean(json.loads(p.read_text(encoding="utf-8")), p.name)


def test_preview_signal_values_are_codes(preview):
    d = json.loads((preview / "data.json").read_text(encoding="utf-8"))
    rows = [r for t in ("nikkei225", "dow30", "nasdaq100", "sp500") for r in d["markets"][t]]
    code = re.compile(r"^[a-z0-9_]+$")
    for r in rows:
        for k in ("signal", "chart_signal", "trend", "chart_signal_note"):
            v = r.get(k)
            assert v is None or code.match(v), (r["symbol"], k, v)
    for counts in d["summary"].values():
        assert all(code.match(k) for k in counts), counts


def test_survival_loop_and_health_from_preview(preview):
    import fetch_signals as fs
    from survival.survival_loop import build as build_sl
    from tools import health_gate

    d = json.loads((preview / "data.json").read_text(encoding="utf-8"))
    cb = {**fs._mf_placeholder_cb("fed_total_assets", "USD_TN", "FRED:WALCL"), "wow_change": 0.1}
    d["money_flow"] = {"as_of": "2026-11-01", "us": {"cb_assets": cb}}
    d["markets"]["volatility"] = [{"symbol": "VIX", "price": 31.0}]
    d["meta"]["yield_curve"] = {"us_10y_2y_spread": {"state": "inverted"}}
    sl = build_sl(d)
    assert sl["risk_gate"]["reasons"], sl["risk_gate"]
    assert "disclaimer_not_advice" in sl["notes"]
    assert_clean(sl, "survival_loop")
    d["survival_loop"] = sl
    assert_clean(health_gate.evaluate(d), "health.json")


def test_non_preview_builders_emit_codes():
    import fetch_signals as fs

    rates = [{"symbol": "US2Y", "yield": 4.5}, {"symbol": "US10Y", "yield": 4.2}, {"symbol": "JP10Y", "yield": 1.0},
             {"symbol": "JP2Y", "yield": 0.5}, {"symbol": "EU2Y", "yield": 2.0}, {"symbol": "EU10Y", "yield": 2.6}]
    yc = fs.build_yield_curve_state(rates)
    assert yc["us_10y_2y_spread"]["comment"] == "us_curve_context"
    objs = {
        "yield_curve": yc,
        "empty_charts": {tf: fs.build_empty_chart(tf) for tf in ("4h", "1d", "1w")},
        "equity_empty": fs._equity_empty_charts(),
        "jp_rate_chart": fs.build_jp_rate_chart_1d([], "2026-11-01"),
        "valuation_chart": fs.build_valuation_chart_1d([], "2026-11-01"),
        "valuation_side": fs._valuation_side_charts(),
        "edge_placeholder": fs.build_empty_edge_context(),
        "mf": [fs._mf_placeholder_cb("ecb_total_assets", "EUR_TN", "FRED:ECBASSETSW"),
               fs._mf_placeholder_debt("eu_gov_debt", "EUR_TN", "eurostat_not_wired")],
    }
    # USDJPY edge_context（全分岐の factors）
    import numpy as np
    import pandas as pd

    idx = pd.date_range("2024-01-01", periods=400, freq="B")
    c = pd.Series(150 + np.cumsum(np.sin(np.arange(400) / 7.0)), index=idx)
    df = pd.DataFrame({"Open": c, "High": c + 0.5, "Low": c - 0.5, "Close": c})
    row = {"symbol": "USDJPY=X", "change_pct": 0.3}
    fs.attach_charts_to_symbol(row, df, 3, "2026-11-01")
    for vix_risk in ("high", "low"):
        ec = fs.build_usdjpy_edge_context(
            row, [{"symbol": "XAUUSD", "change_pct": 0.5}], rates, [{"risk": vix_risk, "price": 20}], yc,
            [{"symbol": "JPY_IMM", "data_status": "auto_cftc", "positioning_state": "short_crowded", "crowding_risk": "high"}])
        assert ec and all(re.match(r"^[a-z0-9_]+$", f) for f in ec["supporting_factors"] + ec["conflicting_factors"])
        objs[f"edge_{vix_risk}"] = ec
    objs["charts_1d"] = row["charts"]
    objs["links"] = [fs.build_link({"symbol": s, "source_ticker": st}, m) for s, st, m in (
        ("7203.T", None, "nikkei225"), ("AAPL", None, "sp500"), ("US10Y", "^TNX", "rates"), ("JPY_IMM", None, "imm"),
        ("VIX", None, "volatility"), ("JP10Y", None, "rates"), ("EU10Y", None, "rates"), ("US2Y", None, "rates"),
        ("US_BUFFETT_INDICATOR", None, "valuation"))]
    assert {x["label"] for x in objs["links"]} <= {"yahoo_finance", "yahoo_finance_jp", "cftc_cot", "mof_jgb", "ecb_data_portal", "fred"}
    for k, v in objs.items():
        assert_clean(v, k)


def test_pipeline_codes():
    sys.path.insert(0, str(ROOT / "pipeline"))
    import build_relations as br
    import build_verify as bv

    for r in (None, -0.5, 0.0, 0.5):
        assert all(re.match(r"^[a-z_]+$", x) for x in br.regime_of(r))
    assert_clean(bv.METHOD, "verify.method")
    assert_clean(bv.MARKET_LABEL, "verify.label")


@pytest.mark.parametrize("p", sorted((ROOT / "docs" / "data").glob("*.json*")), ids=lambda p: p.name)
def test_tracked_public_data_files(p):
    text = p.read_text(encoding="utf-8")
    docs = [json.loads(line) for line in text.splitlines() if line.strip()] if p.suffix == ".jsonl" else [json.loads(text)]
    for i, d in enumerate(docs):
        assert_clean(d, f"{p.name}#{i}")
