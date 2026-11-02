"""screener.calc.ind: CCI ±200 の「抜け」と「一斉に割れ」の規則（通知・検証の両方がこれだけを使う）。"""

import numpy as np

from screener.calc import ind


def _x(s, l):
    return {"cciS": np.array(s, float), "cciL": np.array(l, float)}


def test_both_down_only_on_the_day_both_line_up_below_minus200():
    x = _x([-150, -210, -230, -250, -190, -220], [-180, -190, -205, -220, -230, -240])
    ev = ind.cci_events(x)
    assert ev["cci48_down"].tolist() == [False, True, False, False, False, True]  # 戻ってまた割れたら再び数える
    assert ev["cci288_down"].tolist() == [False, False, True, False, False, False]
    assert ev["both_down"].tolist() == [False, False, True, False, False, True]  # そろった日だけ・続く日は数えない
    assert not any(ev[k].any() for k in ("both_up", "cci48_up", "cci288_up"))


def test_up_events_and_first_day_and_nan():
    x = _x([np.nan, 250, 260, 150, 210], [np.nan, 150, 210, 220, 230])
    ev = ind.cci_events(x)
    assert ev["cci48_up"].tolist() == [False, True, False, False, True]
    assert ev["both_up"].tolist() == [False, False, True, False, True]
    first = ind.cci_events(_x([-300], [-300]))  # 最初の日は「前の日」が無いので抜けとしない
    assert not first["both_down"].any()
    assert set(ind.NOTIFY_EVENTS) == {"both_down", "cci48_down", "cci288_down"}  # +200 は通知しない


def test_spike_line_is_max_of_top_1pct_and_1_5pct_of_universe():
    assert ind.spike_line([0] * 50, 3600) is None  # 履歴が短いと判定しない
    calm = [0] * 245
    assert (
        ind.spike_line(calm, 3600) == 54.0 and ind.spike_line(calm, 520) == 0.015 * 520
    )  # 日本株 54 件・米国株 7.8 件
    past = [0] * 240 + [100, 200, 300, 400, 500]
    q = float(np.quantile(past, 0.99))
    assert ind.spike_line(past, 3600) == max(q, 54.0) == q
    line = ind.spike_line(calm, 3600)
    assert not ind.is_spike(54, line) and ind.is_spike(55, line)  # 線を「超えた」日だけ
    us = ind.spike_line(calm, 520)  # 米国株 520 銘柄 → 7.8 件
    assert not ind.is_spike(7, us) and ind.is_spike(8, us)
    assert not ind.is_spike(3, None)


def test_spike_days_use_only_the_days_before_and_daily_universe():
    dates = [f"d{i:03d}" for i in range(200)]
    counts = [1] * 200
    counts[150] = 60
    counts[151] = 60  # 前の日が入っても、上位1%の線はまだ低い → 続けて「一斉に割れ」
    counts[160] = 40  # 平常日より多いが、銘柄数の 1.5%（54 件）に届かない
    assert ind.spike_days(dates, counts, [3600] * 200) == {"d150", "d151"}
    assert ind.spike_days(dates, counts, [6000] * 200) == set()  # 銘柄数が多ければ線は 90 件
