import json
import pathlib

import pytest

FIX = pathlib.Path(__file__).parent / "fixtures"
TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE"]


@pytest.fixture
def fx():
    from screener.calc import fund_us

    px = {t: fund_us.parse_yahoo_chart(json.loads((FIX / f"px_{t}.json").read_text())) for t in TICKERS}
    facts = {t: json.loads((FIX / f"facts_{t}.json").read_text())["facts"] for t in TICKERS}
    uni = json.loads((FIX / "universe.json").read_text())
    return {"px": px, "facts": facts, "uni": uni}
