"""screener.japan.signals: 総合判定 A/B/C・検証（20営業日後 vs 基準）・バックテスト（架空データ）。"""

from screener.calc import events, ind
from screener.japan import backtest_tech, backtest_value, screen, signals


def test_overall_grade_rules():
    """A = 割安5分の1 × 買い系（品質の候補は使わない）。"""
    assert signals.overall("buy", True) == "A"
    assert signals.overall(ind.LONG_OVERSOLD_LABEL, True) == "A"
    assert signals.overall("buy_strong", False) == "B"
    assert signals.overall("neutral", True) == "B"
    assert signals.overall("sell", False) == "C"
    assert signals.overall(None, False) == "C"
    assert signals.tags_in("long_candidate|cheap_low_quality", signals.JP_CANDIDATES) == "long_candidate"
    assert signals.overall("buy", bool(signals.tags_in("value_quality_top50", signals.US_CANDIDATES))) == "A"


def _row(code, upside, market="プライム", fin=False, mcap=500):
    return {"code": code, "upside_pct": upside, "market": market, "financial": fin, "mcap_oku_jpy": mcap}


def test_value_quintile_universe_and_bounds():
    rows = [_row(f"{i:04d}", float(i)) for i in range(10)]  # 余地 0..9 → 80%点 = 8
    rows += [
        _row("G", 99.0, market="グロース"),  # 母集団の外（市場）
        _row("F", 99.0, fin=True),  # 金融
        _row("S", 99.0, mcap=299),  # 300億円未満
        _row("N", None),  # 余地なし
    ]
    assert screen.cheap_bounds(rows) == (2.0, 8.0)
    vq = screen.value_quintile(rows)
    assert {c for c, v in vq.items() if v == "cheap_quintile"} == {"0008", "0009"}
    assert not {"G", "F", "S", "N"} & set(vq)


def test_grade_a_members_have_upside_at_or_above_cheap_bound(cfg):
    """A の銘柄はすべて 上値余地が割安5分の1の境界以上（6101 ツガミの −52.3% が A になった件の再発防止）。"""
    doc = signals.run(cfg)
    a = doc["anchors"]
    vrows = screen.screen(a["asof"], a["px"], a["p1y"], a["p1m"], _master(cfg, a), cfg=cfg)
    _, hi = screen.cheap_bounds(vrows)
    grade_a = [r for r in doc["jp"] if r["grade"] == "A"]
    assert grade_a, "架空データに A が1件はあること（空なら検査にならない）"
    for r in grade_a:
        assert r["upside_pct"] is not None and r["upside_pct"] >= hi, r
        assert r["value_quintile"] == "cheap_quintile" and r["chart_signal"] in ind.BUY_LABELS
        assert r["market"] in screen.QUINTILE_MARKETS
    # 買い × 品質の候補 でも 割安5分の1 でなければ A にしない（品質の候補は別の列に残る）
    jp = {r["code"]: r for r in doc["jp"]}
    assert jp["1001"]["chart_signal"] in ind.BUY_LABELS and jp["1001"]["upside_pct"] < 0
    assert jp["1001"]["quality_candidate"] == "mid_candidate" and jp["1001"]["grade"] == "B"


def _master(cfg, a):
    from screener.dates import jp_anchor_dates

    return jp_anchor_dates(cfg, a["asof"])[4]


def test_run_on_fixture(cfg):
    doc = signals.run(cfg)
    jp = {r["code"]: r for r in doc["jp"]}
    assert set(jp) == {"1001", "1002", "1003", "1004", "1005"}
    assert jp["1001"]["chart_signal"] in ind.BUY_LABELS
    assert jp["1002"]["chart_signal"] in ("sell", "sell_strong")
    assert jp["1004"]["chart_signal"] == ind.LONG_OVERSOLD_LABEL
    assert all(r["grade"] in ("A", "B", "C") for r in doc["jp"] + doc["us"])
    for r in doc["jp"]:
        assert r["grade"] == signals.overall(r["chart_signal"], r["value_quintile"] == "cheap_quintile")
    assert jp["1003"]["one_off_note"] == "check_earnings_release"
    assert {r["ticker"] for r in doc["us"]} == {"AAA", "BBB", "CCC"}
    v = doc["verify"]
    assert v["horizon_days"] == events.H == 20 and v["gap_days"] == events.GAP == 20
    assert v["jp"]["full"]["base"]["n"] > 0
    g = v["jp"]["grade_A"]  # A の定義そのもの（月初の割安5分の1 × 買い系）の成績
    assert g["definition"] == "cheap_quintile_x_buy_type" and g["valuation_months"] >= 1
    assert g["full"]["grade_A"]["n"] > 0 and g["full"]["base"] == v["jp"]["full"]["base"]
    assert set(g["median_below_base"]) == {"full", "recent6m"}
    assert "grade_A" not in v["us"]
    assert any(cfg.jp("derived", screen.VALUATION_CACHE).glob("*.json"))  # 月初の評価は控えから読み直せる
    assert signals.run(cfg)["verify"]["jp"]["grade_A"]["full"] == g["full"]


def test_backtest_uses_same_rules_as_screen(cfg):
    """with_chart の「割安5分の1 × 買い系」と、画面の A の検証（verify_local.json の jp.grade_A）が同じ件数・同じ成績。
    規則（割安5分の1 の線・買い系の日）は screen / ind の1か所だけにある。"""
    g = signals.run(cfg)["verify"]["jp"]["grade_A"]["full"]["grade_A"]
    w = backtest_value.with_chart(cfg, min_bars=300, min_mcap=0)["res"]["either|cheap_quintile"]
    assert g["n"] > 0 and w["n"] == g["n"] and w["median_pct"] == g["median"]
    import inspect

    for mod in (backtest_value, signals):
        src = inspect.getsource(mod)
        assert "4 * n // 5" not in src and "ind.long_oversold(" not in src, mod.__name__


def test_backtests_run_on_fixture(cfg):
    r = backtest_tech.run(cfg, min_bars=300, min_mcap=0)
    assert r["stocks"] == 4 and r["res"]["base"][20]["n"] > 0  # 金融（1005）は除く
    y = backtest_value.yearly(cfg, n=1)
    assert isinstance(y, dict)
    w = backtest_value.with_chart(cfg, min_bars=300, min_mcap=0)
    assert w["valuation_months"] >= 1
