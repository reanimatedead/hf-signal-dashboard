"""テスト用: tests/screener/calc/fixtures の架空 5 銘柄（AAA〜EEE・400 営業日）を
fetch_signals と同じ形（Open/High/Low/Close/Volume の DataFrame）に変換する。本物のデータは使わない。"""
import json
import pathlib

import pandas as pd

FIX = pathlib.Path(__file__).resolve().parent / "screener" / "calc" / "fixtures"
TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE"]


def frame(t):
    from marketcalc import fund_us
    p = fund_us.parse_yahoo_chart(json.loads((FIX / f"px_{t}.json").read_text()))
    return pd.DataFrame({"Open": p["c"], "High": p["h"], "Low": p["l"], "Close": p["c"],
                         "Volume": [1000] * len(p["c"])}, index=pd.to_datetime(p["d"]))


def facts(t):
    return json.loads((FIX / f"facts_{t}.json").read_text())


def px_json(t):
    return json.loads((FIX / f"px_{t}.json").read_text())
