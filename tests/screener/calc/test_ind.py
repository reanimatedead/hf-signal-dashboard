"""ind: CCI・BB が手計算と一致し、判定が条件どおりに出る。"""

import math

import numpy as np

from screener.calc import ind


def hand_cci(h, l, c, n, i):
    tp = [(h[k] + l[k] + c[k]) / 3 for k in range(i - n + 1, i + 1)]
    m = sum(tp) / n
    md = sum(abs(t - m) for t in tp) / n
    return (tp[-1] - m) / (0.015 * md)


def hand_bb(c, n, i):
    w = c[i - n + 1 : i + 1]
    m = sum(w) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in w) / n)  # 母標準偏差
    return m, sd


def test_cci_matches_hand_calc():
    rng = np.random.default_rng(1)
    c = list(100 + np.cumsum(rng.normal(0, 1, 60)))
    h = [v + 1 for v in c]
    l = [v - 1.5 for v in c]
    got = ind.cci(h, l, c, 20)
    for i in (19, 30, 59):
        assert abs(got[i] - hand_cci(h, l, c, 20, i)) < 1e-9
    assert np.isnan(got[18])


def test_cci_tiny_known_value():
    # tp = 1,2,3 → 平均2, 平均偏差 2/3 → (3-2)/(0.015*2/3) = 100
    assert abs(ind.cci([1, 2, 3], [1, 2, 3], [1, 2, 3], 3)[-1] - 100.0) < 1e-9


def test_bb_matches_hand_calc():
    c = [float(v) for v in [10, 11, 12, 13, 12, 11, 10, 9, 10, 12]]
    m, s = ind.bb(c, 5)
    for i in (4, 7, 9):
        hm, hs = hand_bb(c, 5, i)
        assert abs(m[i] - hm) < 1e-12 and abs(s[i] - hs) < 1e-9


def _x(c, cL, cS, mS, sS, mL=None, sL=None):
    def a(v):
        return np.array(v, dtype=float)

    n = len(c)
    return {
        "c": a(c),
        "cciL": a(cL),
        "cciS": a(cS),
        "mS": a(mS),
        "sS": a(sS),
        "mL": a(mL if mL else [100] * n),
        "sL": a(sL if sL else [10] * n),
    }


def test_signal_conditions_exact():
    # 0:買い(-2σちょうど) 1:強い買い(-3σ) 2:長期下向きなので買いにならない 3:CCI48が-100ちょうど→買いにならない
    # 4:売り(+2σ) 5:強い売り(+3σ) 6:長期上向きなので売りにならない 7:何もなし
    c = [96, 94, 94, 96, 104, 106, 106, 100]
    cL = [10, 10, -10, 10, -10, -10, 10, 0]
    cS = [-150, -150, -150, -100, 150, 150, 150, 0]
    x = _x(c, cL, cS, [100] * 8, [2] * 8)
    assert ind.signals(x).tolist() == [1, 2, 0, 0, -1, -2, 0, 0]


def test_long_oversold_and_labels():
    x = _x([79, 81, 94], [-5, -5, 10], [0, 0, -150], [100] * 3, [10] * 3, mL=[100] * 3, sL=[10] * 3)
    assert ind.long_oversold(x).tolist() == [True, False, False]
    j0 = ind.judge(x, i=0)
    j2 = ind.judge(x, i=2)
    assert j0["label"] == "buy_long_oversold" and j0["long_oversold"]
    assert ind.judge(x, i=1)["label"] == "neutral"
    # 2: c=94 は mS-2σ(80) を下回らないので買いにならない
    assert j2["label"] == "neutral"


def test_labels_on_fixtures(fx):
    want = {"AAA": "buy_strong", "BBB": "sell_strong", "CCC": "neutral", "EEE": "buy_long_oversold"}
    for t, lab in want.items():
        p = fx["px"][t]
        assert ind.summary(p["h"], p["l"], p["c"])["chart_signal"] == lab, t


def test_summary_needs_enough_bars(fx):
    p = fx["px"]["AAA"]
    assert ind.summary(p["h"][:200], p["l"][:200], p["c"][:200]) is None


def test_chart_series_shapes(fx):
    p = fx["px"]["AAA"]
    s = ind.chart_series(p["h"], p["l"], p["c"], tail=120)
    assert len(s["close"]) == 120 and len(s["bb288"]["p3"]) == 120 and len(s["cci48"]) == 120
    assert any(m["type"] == "buy" for m in s["marks"])


def test_label_conditions_match_judge(fx):
    for t, p in fx["px"].items():
        x = ind.compute(p["h"], p["l"], p["c"])
        conds = ind.label_conditions(x)
        for i in range(ind.MIN_BARS, len(x["c"])):
            j = ind.judge(x, i=i)["label"]
            hit = [k for k, v in conds.items() if v[i]]
            assert hit == ([] if j == ind.LABELS[0] else [j]), (t, i, j, hit)


def test_chart_series_nd_rounds_prices(fx):
    p = fx["px"]["AAA"]
    s = ind.chart_series(p["h"], p["l"], p["c"], tail=50, nd=1)
    v = [x for x in s["close"] + s["bb48"]["p2"] if x is not None]
    assert v and all(round(x, 1) == x for x in v)


def test_long_oversold_on_a_sell_day_counts_as_sell(monkeypatch):
    """長期の売られすぎ と 売り が同じ日は「売り」（画面・検証とも ind.day_labels の1か所の規則）。"""
    import numpy as np

    sig = np.array([0, -1, 1, 0, -2])
    lo = np.array([True, True, True, False, True])
    monkeypatch.setattr(ind, "signals", lambda x, p=ind.P: sig)
    monkeypatch.setattr(ind, "long_oversold", lambda x, p=ind.P: lo)
    lab = list(ind.day_labels({}))
    assert lab == ["buy_long_oversold", "sell", "buy", "neutral", "sell_strong"]
    assert ind.buy_type_days({}).tolist() == [True, False, True, False, False]
    assert ind.is_buy_type("buy_long_oversold") and not ind.is_buy_type("sell") and not ind.is_buy_type(None)
