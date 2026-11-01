import json, pathlib, sys
import pytest
ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FIX = pathlib.Path(__file__).parent / "fixtures"
TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE"]


@pytest.fixture
def fx():
    from marketcalc import fund_us
    px = {t: fund_us.parse_yahoo_chart(json.loads((FIX / f"px_{t}.json").read_text())) for t in TICKERS}
    facts = {t: json.loads((FIX / f"facts_{t}.json").read_text())["facts"] for t in TICKERS}
    uni = json.loads((FIX / "universe.json").read_text())
    return {"px": px, "facts": facts, "uni": uni}
