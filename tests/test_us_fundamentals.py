"""tools/build_us_fundamentals.py をオフラインで（架空 EDGAR 形 facts_*.json・通信は差し替え）。"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import build_us_fundamentals as bu  # noqa: E402
from marketcalc import contracts, fund_us  # noqa: E402
from tests._fake_market import TICKERS, facts, px_json  # noqa: E402

PROBE = contracts.US_PROBE


def fake_sec(broken_probe=0, sic=None):
    """US_PROBE 20社 + 架空5社。US_PROBE には架空 AAA の facts を返す（本物ではない）。"""
    universe = list(PROBE) + TICKERS
    ciks = {t: i + 1 for i, t in enumerate(universe)}

    def get_json(url):
        if url == bu.TICKERS_URL:
            return {str(i): {"ticker": t, "cik_str": c} for i, (t, c) in enumerate(ciks.items())}
        for t, c in ciks.items():
            if url == bu.FACTS_URL.format(cik=c):
                if t in PROBE[:broken_probe]:
                    return {"facts": {"us-gaap": {}}}
                return facts(t if t in TICKERS else "AAA")
            if url == bu.SUBMIT_URL.format(cik=c):
                return {"sic": (sic or {}).get(t, "3571")}
        if "finance.yahoo.com" in url:
            sym = url.split("/chart/")[1].split("?")[0]
            if sym in TICKERS:
                return px_json(sym)
            raise OSError("no")
        raise OSError(url)
    return get_json


def test_build_rows_match_marketcalc():
    code, obj, log = bu.build(TICKERS, get_json=fake_sec(sic={"EEE": "6021"}), asof="2025-12-31", pause=0)
    assert code == 0, log
    assert obj["count"] == 5 and set(obj["rows"]) == set(TICKERS)
    ddd = obj["rows"]["DDD"]
    want = fund_us.fundamentals(facts("DDD")["facts"], "2025-12-31",
                                fund_us.parse_yahoo_chart(px_json("DDD"))["splits"])
    assert ddd["sh"] == want["sh"] and ddd["f_score"] == want["f_score"]   # 分割調整も同じ式
    assert obj["rows"]["EEE"]["fin"] is True and obj["rows"]["AAA"]["fin"] is False
    # 毎日の側（fetch_signals）は metrics をそのまま呼べる形
    assert fund_us.metrics(obj["rows"]["AAA"], 100.0)["PER"] is not None


def test_edgar_contract_failure_stops_before_writing():
    code, obj, log = bu.build(TICKERS, get_json=fake_sec(broken_probe=3), asof="2025-12-31", pause=0)
    assert code == 2 and obj is None
    assert any("EDGAR" in x and "止める" in x for x in log)


def test_low_coverage_stops():
    code, obj, _ = bu.build(TICKERS + [f"ZZ{i}" for i in range(10)], get_json=fake_sec(), asof="2025-12-31", pause=0)
    assert code == 3 and obj is None


def test_sic_is_fin():
    assert bu.sic_is_fin("6021") and bu.sic_is_fin(4911) and bu.sic_is_fin("6798")
    assert not bu.sic_is_fin("3571") and not bu.sic_is_fin(None)
