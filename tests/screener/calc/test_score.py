"""screener.calc.score: 売買スコアの規則と配分（1か所）・次の決算の推定・段階・ETF の種類。"""

import numpy as np

from screener.calc import assets, ind, score


def test_percentiles_ties_none_and_direction():
    assert score.percentiles([3, 1, None, 2, 2]) == [1.0, 0.0, None, 0.5, 0.5]
    assert score.percentiles([3, 1, 2], higher_better=False) == [0.0, 1.0, 0.5]
    assert score.percentiles([5]) == [0.5] and score.percentiles([None]) == [None]


def test_tier_lines_and_array_agree():
    vals = [-30, 0, 4.9, 5, 14.9, 15, 24.9, 25, 39.9, 40, 75]
    want = [score.tier(v) for v in vals]
    assert want == [1, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    assert list(score.tiers_array(np.array(vals, float))) == want
    assert score.tiers_array(np.array([np.nan]))[0] == 0


def test_chart_points_and_gate():
    w = score.W["chart"]
    assert score.chart_points("buy_strong") == w["buy_strong"]
    c2 = score.CCI200
    assert score.chart_points("buy", "buy_cci200", market="us") == w["buy"] + c2["us"]["buy_cci200"]
    assert score.chart_points("neutral") == 0 and score.chart_points("sell") == 0
    # 日本株: buy_cci200 は「一斉に割れ」の日だけ加点・sell_cci200 は減点。米国の sell_cci200 は 0 点
    assert score.chart_points("neutral", "buy_cci200", market="jp") == 0
    assert score.chart_points("neutral", "buy_cci200", market="jp", spike=True) == c2["jp"]["buy_cci200_spike"] > 0
    assert score.chart_points("neutral", "sell_cci200", market="jp") == c2["jp"]["sell_cci200"] < 0
    assert score.chart_points("neutral", "sell_cci200", market="us") == 0
    assert score.chart_points("neutral", "buy_cci200", market="fx") == 0
    gate = {"buy": False, "buy_cci200": False}
    assert score.chart_points("buy", "buy_cci200", gate) == 0
    # 直近6か月で中央値が基準を下回るものだけ 0 点（件数が足りないものは付ける）。売り目安は外れたら 0 点
    base = {"n": 100, "median": 1.0}

    def st(m, n=50):
        return {"n": n, "median": m}

    c200 = {
        "base": {"recent6m": base},
        "buy_cci200": {"recent6m": st(0.5), "spike_recent6m": st(3.0)},
        "sell_cci200": {"recent6m": st(2.0)},
    }
    g = score.gate_from_verify({"buy": st(0.5), "buy_strong": st(2.0), "buy_long_oversold": st(-9, 2)}, base, c200)
    assert g == {
        "buy_strong": True,
        "buy": False,
        "buy_long_oversold": True,
        "buy_cci200": False,
        "buy_cci200_spike": True,
        "sell_cci200": False,
    }


def test_sell_points_are_separate_from_total():
    rows = [{"chart_signal": "sell_strong", "upside_pct": 10, "PBR": 1, "PER": 10}]
    score.score_rows(rows)
    r = rows[0]
    assert r["score_sell"] == score.W["sell"]["sell_strong"] and r["score_chart"] == 0
    assert r["score"] == r["score_value"]  # 売りの点は合計に入らない


def test_score_rows_parts_penalties_and_inverse():
    rows = [
        {
            "chart_signal": "buy",
            "upside_pct": 50,
            "PBR": 0.5,
            "PER": 8,
            "F": 7,
            "f_max": 8,
            "roe_pct": 12,
            "equity_ratio_pct": 60,
            "turnover_20d": 1e9,
            "one_off_flag": True,
            "earnings_soon": True,
        },
        {"chart_signal": "neutral", "upside_pct": -10, "PBR": 3, "PER": 30, "turnover_20d": 1e6},
        {"chart_signal": "neutral", "upside_pct": 0, "PBR": 2, "PER": -5, "turnover_20d": 1e8},
    ] + [{"chart_signal": "neutral", "turnover_20d": 1e8 + i} for i in range(10)]
    score.score_rows(rows)
    a, b = rows[0], rows[1]
    assert a["score_value"] == 35.0 and a["score_chart"] == score.W["chart"]["buy"]
    assert a["score_penalty"] == -20 and a["score_penalties"] == "one_off|earnings_soon"
    assert a["score"] == 35 + 20 - 20 and a["score_tier"] == score.tier(35) and a["score_quality"] is not None
    assert "low_turnover" in b["score_penalties"]  # 売買代金が市場の下位 10%
    assert b["score_value"] == 0.0  # 余地が最下位・PBR が最高・PER が最高
    assert rows[2]["score_value"] == 7.5 + 5.0  # PER が負のものは PER の点なし
    # チャートの点だけ（公開の日本株）: 割安・質・減点は None
    jp = [dict(rows[0])]
    score.score_rows(jp, parts=score.CHART_ONLY)
    assert jp[0]["score_value"] is None and jp[0]["score_quality"] is None and jp[0]["score_penalty"] is None
    assert jp[0]["score"] == score.W["chart"]["buy"]
    inv = [{"chart_signal": "buy", "etf_kind": "inverse"}, {"chart_signal": "buy", "etf_kind": "index"}]
    score.score_rows(inv, parts=("chart", "penalty"))
    assert inv[0]["score"] is None and inv[0]["score_note"] == "not_scored_inverse" and inv[1]["score"] == 20


def test_next_earnings_estimate_and_soon_window():
    past = ["2025-02-05", "2025-05-08", "2025-08-07", "2025-11-06", "2026-02-05", "2026-05-08", "2026-08-07"]
    assert score.next_earnings(past, "2026-11-02") == "2026-11-05"
    assert score.earnings_soon(past, "2026-10-30") and not score.earnings_soon(past, "2026-10-20")
    # 今年の分が既に出ていれば次へ
    assert score.next_earnings([*past, "2026-11-04"], "2026-11-06") == "2027-02-04"
    assert not score.earnings_soon([*past, "2026-11-04"], "2026-11-04")
    days = ["2026-10-28", "2026-10-29", "2026-11-04", "2026-11-05", "2026-11-06"]
    m = score.earnings_soon_days(days, past)
    # 画面（最新日）と検証（日ごと）が同じ関数
    assert [score.earnings_soon(past, d) for d in days] == list(m)
    assert score.next_earnings([], "2026-11-02") is None


def test_total_days_last_day_matches_score_rows():
    rng = np.random.default_rng(3)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 700)))
    h, l = c * 1.01, c * 0.99
    x = ind.compute(h, l, c)
    ds = [str(np.datetime64("2023-01-02") + np.timedelta64(i, "D")) for i in range(len(c))]
    tot = score.total_days(x, ds, "X", None, ("chart",))
    j = ind.judge(x)
    rc = ind.cci200_recent(x)
    row = {"chart_signal": j["label"], "cci200_signal": rc["code"] if rc and rc["bars_ago"] == 0 else None}
    score.score_rows([row], parts=score.CHART_ONLY)
    assert tot[-1] == row["score"]


def test_verify_tiers_shape_and_weakened_rule():
    rng = np.random.default_rng(1)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 800)))
    ds = [str(np.datetime64("2023-01-02") + np.timedelta64(i, "D")) for i in range(len(c))]
    tot = np.where(np.arange(len(c)) % 30 == 0, 45.0, 0.0)
    v = score.verify_tiers([(c, tot, ds)], ds[500])
    assert set(v["full"]) == {"base", *score.TIER_KEYS} and v["full"]["tier5"]["n"] > 0
    assert v["top_tier"] == "tier5" and v["weakened"] in (True, False, None)


def test_cci200_days_are_both_cross_events_and_marks():
    rng = np.random.default_rng(11)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, 900)))
    x = ind.compute(c * 1.01, c * 0.99, c)
    d, ev = ind.cci200_days(x), ind.cci_events(x)
    assert (d["buy_cci200"] == ev["both_down"]).all() and (d["sell_cci200"] == ev["both_up"]).all()
    assert d["buy_cci200"].any() or d["sell_cci200"].any()
    marks = ind.chart_series(c * 1.01, c * 0.99, c)["marks"]
    for code in ("buy_cci200", "sell_cci200"):
        assert sorted(m["i"] for m in marks if m["type"] == code) == list(np.flatnonzero(d[code]))
    # 既存の買い・売りの規則は変わらない
    assert set(ind.day_labels(x)) <= {"buy_strong", "buy", "neutral", "sell", "sell_strong", "buy_long_oversold"}
    ds = [str(np.datetime64("2023-01-02") + np.timedelta64(i, "D")) for i in range(len(c))]
    v = score.cci200_verify([(x, ds)], {ds[-300]}, ds[-150])
    for code in ("buy_cci200", "sell_cci200", "base"):
        assert set(v[code]) == {"full", "excluding_spike_days", "spike_days_only", "recent6m", "spike_recent6m"}
    assert (
        v["buy_cci200"]["full"]["n"]
        == v["buy_cci200"]["excluding_spike_days"]["n"] + v["buy_cci200"]["spike_days_only"]["n"]
    )


def test_rules_come_from_W():
    r = score.rules()
    assert r["weights"] == score.W and r["max"]["value"] == sum(score.W["value"].values())
    assert r["tiers"][0] == {"ge": score.TIERS[0][0], "tier": 5} and r["public_japan_parts"] == ["chart"]


def test_etf_kind_from_name():
    assert assets.etf_kind("ＮＥＸＴ　ＦＵＮＤＳ　日経平均レバレッジ・インデックス連動型上場投信") == "leveraged"
    assert assets.etf_kind("日経平均ダブルインバース・インデックス連動型上場投信") == "inverse"
    assert assets.etf_kind("TOPIXベア2倍上場投信") == "inverse"
    assert assets.etf_kind("iFreeETF TOPIXインバース(−1倍)指数") == "inverse"
    assert assets.etf_kind("日経平均ブル2倍上場投信") == "leveraged"
    assert assets.etf_kind("NEXT FUNDS FTSEブルサ・マレーシアKLCI連動型上場投信") == "index"
    assert assets.etf_kind("NEXT FUNDS TOPIX連動型上場投信") == "index"
    assert assets.etf_kind("SPDRゴールド・シェア") == "unknown"
    # 公開の ETF 一覧の種類は名前の規則と一致（1か所の定義どうしがずれない）
    assert {s: k for s, (_n, k) in assets.ETFS.items()} == {s: assets.etf_kind(n) for s, (n, _k) in assets.ETFS.items()}
    assert {"1306.T", "1321.T", "1570.T", "1360.T", "1357.T", "1458.T", "1459.T"} <= set(assets.ETFS)


# ── gate を各日付の時点で決める（score.gate_days）: 未来の結果を見ない ──


def _series(n=1000, seed=3):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.02, n)))
    h, lo = c * 1.01, c * 0.99
    ds = [str(d) for d in np.datetime64("2022-01-03") + np.arange(n)]
    return ind.compute(h, lo, c), ds


def test_gate_days_ignores_the_future():
    """ある日の gate は、その日より後の値動きを変えても変わらない。"""
    xs = [_series(seed=s) for s in range(6)]
    cut = 800
    day = xs[0][1][cut]
    a = score.gate_days(xs)
    chopped = []
    for x, ds in xs:
        y = {k: (v[: cut + 1] if isinstance(v, np.ndarray) and len(v) == len(ds) else v) for k, v in x.items()}
        chopped.append((y, ds[: cut + 1]))
    b = score.gate_days(chopped)
    assert a[day] == b[day]


def test_gate_days_only_uses_results_known_by_that_day(monkeypatch):
    """シグナルの 20 営業日後の結果が確定するまでは gate に効かない。"""
    n = 600
    x, ds = _series(n)
    i = 400
    buys = np.zeros(n, dtype=bool)
    buys[i::30] = True
    monkeypatch.setattr(ind, "label_conditions", lambda _x: {"buy": buys})
    monkeypatch.setattr(ind, "cci200_days", lambda _x: {})
    c = np.full(n, 100.0)
    c[i + 20 :: 30] = 50.0  # どの buy も 20 営業日後に半値（それ以外の日は動かない）
    g = score.gate_days([({**x, "c": c}, ds)])
    assert g[ds[i + 19]]["buy"] is True  # まだ1件も確定していない
    assert g[ds[i + 30 * 3 + 20]]["buy"] is True  # 確定は 4 件だけ（5 件未満は判定しない）
    assert g[ds[i + 30 * 4 + 19]]["buy"] is True  # 5 件目の結果は翌日に確定する
    assert g[ds[i + 30 * 4 + 20]]["buy"] is False  # 確定した日に初めて 0 点


def test_total_days_uses_each_days_gate():
    x, ds = _series(600)
    on = {d: {} for d in ds}
    off = {d: {k: False for k in score.W["chart"]} for d in ds}
    a = score.total_days(x, ds, "X", None, ("chart",), gate_by_day=on)
    b = score.total_days(x, ds, "X", None, ("chart",), gate_by_day=off)
    assert np.array_equal(a, score.total_days(x, ds, "X", None, ("chart",)))
    assert (b <= a).all()


def _tiers(t5, base, n=10):
    return {"tier5": {"n": n, "median": t5}, "base": {"n": 100, "median": base}}


def test_evidence_weak_when_top_tier_never_beats_market():
    assert score.evidence_weak(_tiers(0.3, 0.5), _tiers(0.5, 0.5)) is True
    assert score.evidence_weak(_tiers(0.6, 0.5), _tiers(0.1, 0.5)) is False  # 片方でも上回れば出さない
    assert score.evidence_weak(_tiers(0.1, 0.5), _tiers(0.6, 0.5)) is False
    assert score.evidence_weak(_tiers(9.0, 0.5, n=2), _tiers(9.0, 0.5, n=4)) is True  # 件数が少なすぎる
    assert score.evidence_weak(_tiers(None, 0.5, n=0), _tiers(None, 0.5, n=0)) is True  # 段階5 が無い
