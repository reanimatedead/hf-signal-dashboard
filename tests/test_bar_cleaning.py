"""未確定の足と最後の足の単位の誤り（calc.contracts の規則・fetch_signals.clean_bars・us.screen.trim_last）。"""

import datetime as dt

import fetch_signals as fs
import numpy as np
import pandas as pd

from screener.calc import contracts
from screener.us import screen as us_screen


def _at(y, m, d, hh, mm, tz):
    from zoneinfo import ZoneInfo

    return dt.datetime(y, m, d, hh, mm, tzinfo=ZoneInfo(tz))


def test_session_today_tse_and_us():
    fri = dt.date(2026, 11, 6)
    assert contracts.session_today("jp", _at(2026, 11, 6, 9, 54, "Asia/Tokyo")) == fri
    assert contracts.session_today("jp", _at(2026, 11, 6, 12, 0, "Asia/Tokyo")) == fri  # 昼休みも未確定
    assert contracts.session_today("jp", _at(2026, 11, 6, 15, 30, "Asia/Tokyo")) is None
    assert contracts.session_today("jp", _at(2026, 11, 6, 7, 30, "Asia/Tokyo")) is None
    assert contracts.session_today("jp", _at(2026, 11, 7, 10, 0, "Asia/Tokyo")) is None  # 土曜
    assert contracts.session_today("us", _at(2026, 11, 6, 10, 0, "America/New_York")) == fri
    assert contracts.session_today("us", _at(2026, 11, 6, 16, 0, "America/New_York")) is None
    # 07:30 JST（定時の full）は米国も時間外
    assert contracts.session_today("us", _at(2026, 11, 6, 7, 30, "Asia/Tokyo")) is None
    assert contracts.session_today(None, _at(2026, 11, 6, 10, 0, "Asia/Tokyo")) is None


def test_market_of():
    assert contracts.market_of("1306.T") == "jp" and contracts.market_of("^N225") == "jp"
    assert contracts.market_of("AAPL") == "us" and contracts.market_of("^GSPC") == "us"
    assert contracts.market_of("USDJPY=X") is None and contracts.market_of("BTC-USD") is None


def test_last_bar_glitch():
    base = [400.0 + i for i in range(20)]
    assert not contracts.last_bar_glitch(base + [392.0])  # 5% 安は本当の値動き
    assert contracts.last_bar_glitch(base + [39.0])  # 1/10
    assert contracts.last_bar_glitch(base + [4100.0])  # 10 倍
    assert not contracts.last_bar_glitch(base + [85.0])  # 中央値 409.5 の 0.2 倍（81.9）より上
    assert not contracts.last_bar_glitch([400.0, 40.0])  # 本数が足りないときは判定しない


def _df(days, closes):
    idx = pd.to_datetime(days)
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": 1.0}, index=idx)


def test_clean_bars_drops_unfinished_only_in_session():
    days = pd.bdate_range(end="2026-11-06", periods=30)
    df = _df(days, [415.0] * 29 + [392.0])
    fs._UNFINISHED.clear()
    a = fs.clean_bars(df, "1306.T", now=_at(2026, 11, 6, 9, 54, "Asia/Tokyo"))
    assert a.index[-1].date() == dt.date(2026, 11, 5) and fs._UNFINISHED == {"1306.T": "2026-11-06"}
    fs._UNFINISHED.clear()
    b = fs.clean_bars(df, "1306.T", now=_at(2026, 11, 6, 16, 0, "Asia/Tokyo"))
    assert len(b) == 30 and fs._UNFINISHED == {}
    # 米国株は東証の時間には外さない
    c = fs.clean_bars(df, "AAPL", now=_at(2026, 11, 6, 9, 54, "Asia/Tokyo"))
    assert len(c) == 30


def test_clean_bars_drops_last_glitch_for_stocks_and_records():
    days = pd.bdate_range(end="2026-11-05", periods=30)
    df = _df(days, [3000.0] * 29 + [300.0])
    fs._GLITCHES.clear()
    out = fs.clean_bars(df, "7203.T", now=_at(2026, 11, 6, 7, 30, "Asia/Tokyo"))
    assert len(out) == 29 and fs._GLITCHES == {"7203.T": {"2026-11-05"}}
    fs.clean_bars(df, "7203.T", now=_at(2026, 11, 6, 7, 30, "Asia/Tokyo"))  # 2回通っても本数は重ねない
    assert len(fs._GLITCHES["7203.T"]) == 1
    fs._GLITCHES.clear()


def test_us_trim_last():
    p = {
        "d": ["2026-11-04", "2026-11-05", "2026-11-06"],
        "c": [10.0, 11.0, 12.0],
        "a": [10.0, 11.0, 12.0],
        "h": None,
        "l": [1, 2, 3],
        "v": [1, 2, 3],
        "splits": [("2020-01-01", 4.0)],
    }
    q = us_screen.trim_last(p, "AAPL", now=_at(2026, 11, 6, 11, 0, "America/New_York"))
    assert q["d"] == ["2026-11-04", "2026-11-05"] and q["c"] == [10.0, 11.0] and q["splits"] == p["splits"]
    assert us_screen.trim_last(p, "AAPL", now=_at(2026, 11, 6, 17, 0, "America/New_York")) == p


def test_clean_bars_drops_trailing_nan_close():  # 取引前の当日の空の行（株価が NaN → null で出ていた）
    days = pd.bdate_range(end="2026-11-06", periods=30)
    df = _df(days, [344.0] * 29 + [float("nan")])
    out = fs.clean_bars(df, "AAPL", now=_at(2026, 11, 6, 11, 0, "Asia/Tokyo"))
    assert len(out) == 29 and float(out["Close"].iloc[-1]) == 344.0
    r = fs.process_ticker(out, "AAPL", "Apple")
    assert r.get("price") == 344.0
