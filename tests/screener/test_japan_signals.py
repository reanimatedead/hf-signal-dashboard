"""screener.japan.signals: 総合判定 A/B/C・検証（20営業日後 vs 基準）・バックテスト（架空データ）。"""

from screener.calc import events, ind
from screener.japan import backtest_tech, backtest_value, signals


def test_overall_grade_rules():
    assert signals.overall("買い", "長期候補") == "A"
    assert signals.overall(ind.LONG_OVERSOLD_LABEL, "中期候補") == "A"
    assert signals.overall("強い買い", "") == "B"
    assert signals.overall("様子見", "長期候補・割安だが質に注意") == "B"
    assert signals.overall("売り", "割安だが質に注意") == "C"
    assert signals.overall(None, None) == "C"
    assert signals.overall("買い", "割安×質 上位50", signals.US_CANDIDATES) == "A"


def test_run_on_fixture(cfg):
    doc = signals.run(cfg)
    jp = {r["コード"]: r for r in doc["jp"]}
    assert set(jp) == {"1001", "1002", "1003", "1004", "1005"}
    assert jp["1001"]["チャート判定"] in ind.BUY_LABELS
    assert jp["1002"]["チャート判定"] in ("売り", "強い売り")
    assert jp["1004"]["チャート判定"] == ind.LONG_OVERSOLD_LABEL
    assert all(r["総合判定"] in ("A", "B", "C") for r in doc["jp"] + doc["us"])
    for r in doc["jp"]:
        assert r["総合判定"] == signals.overall(r["チャート判定"], r["財務判定"])
    assert jp["1003"]["一時利益の目印"] == "決算短信で確認"
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
