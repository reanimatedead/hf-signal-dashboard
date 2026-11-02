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


def test_spike_threshold_is_strictly_above_top_1pct_of_past_year():
    assert ind.spike_threshold([0] * 50) is None  # 履歴が短いと判定しない
    past = [0] * 240 + [10, 20, 30, 40, 50]
    thr = ind.spike_threshold(past)
    assert thr == float(np.quantile(past, 0.99))
    assert ind.is_spike(int(thr) + 1, thr) and not ind.is_spike(thr, thr) and not ind.is_spike(0, -1.0)
    assert not ind.is_spike(4, 0.0) and ind.is_spike(5, 0.0)  # 線が 0 件でも 5 件未満は「一斉に」としない


def test_spike_days_use_only_the_days_before():
    dates = [f"d{i:03d}" for i in range(200)]
    counts = [1] * 200
    counts[150] = 50
    counts[151] = 50  # 前の日が入っても、上位1%の線はまだ低い → 続けて「一斉に割れ」
    assert ind.spike_days(dates, counts) == {"d150", "d151"}
