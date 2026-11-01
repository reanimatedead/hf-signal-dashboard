"""screener.japan.signals: 総合判定 A/B/C・検証（20営業日後 vs 基準）・バックテスト（架空データ）。"""

from screener.calc import events, ind
from screener.japan import backtest_tech, backtest_value, signals


def test_overall_grade_rules():
    assert signals.overall("buy", "long_candidate") == "A"
    assert signals.overall(ind.LONG_OVERSOLD_LABEL, "mid_candidate") == "A"
    assert signals.overall("buy_strong", "") == "B"
    assert signals.overall("neutral", "long_candidate|cheap_low_quality") == "B"
    assert signals.overall("sell", "cheap_low_quality") == "C"
    assert signals.overall(None, None) == "C"
    assert signals.overall("buy", "value_quality_top50", signals.US_CANDIDATES) == "A"


def test_run_on_fixture(cfg):
    doc = signals.run(cfg)
    jp = {r["code"]: r for r in doc["jp"]}
    assert set(jp) == {"1001", "1002", "1003", "1004", "1005"}
    assert jp["1001"]["chart_signal"] in ind.BUY_LABELS
    assert jp["1002"]["chart_signal"] in ("sell", "sell_strong")
    assert jp["1004"]["chart_signal"] == ind.LONG_OVERSOLD_LABEL
    assert all(r["grade"] in ("A", "B", "C") for r in doc["jp"] + doc["us"])
    for r in doc["jp"]:
        assert r["grade"] == signals.overall(r["chart_signal"], r["fin_tag"])
    assert jp["1003"]["one_off_note"] == "check_earnings_release"
    assert {r["ticker"] for r in doc["us"]} == {"AAA", "BBB", "CCC"}
    v = doc["verify"]
    assert v["horizon_days"] == events.H == 20 and v["gap_days"] == events.GAP == 20
    assert v["jp"]["full"]["base"]["n"] > 0


def test_backtests_run_on_fixture(cfg):
    r = backtest_tech.run(cfg, min_bars=300, min_mcap=0)
    assert r["stocks"] == 4 and r["res"]["base"][20]["n"] > 0  # 金融（1005）は除く
    y = backtest_value.yearly(cfg, n=1)
    assert isinstance(y, dict)
    w = backtest_value.with_chart(cfg, min_bars=300, min_mcap=0)
    assert w["valuation_months"] >= 1
