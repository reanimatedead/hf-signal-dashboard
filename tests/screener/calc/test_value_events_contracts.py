import numpy as np

from screener.calc import contracts, events, value


def test_one_off_flag():
    assert value.one_off_flag(131, 100)["flag"] and value.one_off_flag(131, 100)["note"] == "check_earnings_release"
    assert not value.one_off_flag(130, 100)["flag"]  # ちょうど1.3倍は対象外（「超える」）
    assert value.one_off_flag(None, None, roe_fwd=0.21, roe_act=0.10)["flag"]
    assert not value.one_off_flag(None, None, roe_fwd=0.20, roe_act=0.10)["flag"]
    assert not value.one_off_flag(50, -10)["flag"]  # 営業赤字は比率に意味がない
    assert len(value.one_off_flag(200, 100, 0.5, 0.1)["reasons"]) == 2


def test_event_returns_and_gap():
    c = np.linspace(100, 200, 400)
    cond = np.zeros(400, bool)
    cond[300] = cond[305] = cond[330] = True
    r = events.event_returns(c, {"sig": cond}, h=20, gap=20, start=288)
    assert len(r["sig"]) == 2  # 305 は 300 から20日未満なので数えない
    assert len(r["base"]) == 400 - 20 - 288
    s = events.stats(r["sig"])
    assert s["n"] == 2 and s["up_pct"] == 100.0


def test_weakened():
    assert events.weakened({"n": 10, "median": 0.5}, {"median": 1.0}) is True
    assert events.weakened({"n": 10, "median": 1.5}, {"median": 1.0}) is False
    assert events.weakened({"n": 2, "median": -9}, {"median": 1.0}) is None


def test_contracts():
    assert contracts.count_within("nikkei225", 225)[0]
    assert contracts.count_within("nikkei225", 214)[0] and not contracts.count_within("nikkei225", 213)[0]
    assert contracts.missing_ratio_ok("yahoo", 18, 20)[0] and not contracts.missing_ratio_ok("yahoo", 17, 20)[0]
    assert not contracts.has_columns("fins", {"NP": 1}, ("NP", "Eq"))[0]
    ok, body = contracts.summarize([(True, "a"), (False, "b")])
    assert not ok and "❌ b" in body
    assert len(contracts.US_PROBE) == 20 and len(contracts.JP_PROBE) == 20
