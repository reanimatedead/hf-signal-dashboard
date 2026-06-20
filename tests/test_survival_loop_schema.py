"""data.json.survival_loop の契約テスト (SPEC_SURVIVAL §4, §8.2)."""
import json
import pathlib
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_JSON = ROOT / "docs" / "data.json"

ALLOWED_RISK_LABEL = {"risk-on", "neutral", "risk-off"}
ALLOWED_COLOR = {"green", "yellow", "red"}
ALLOWED_REGIME = {"high_vol", "low_vol"}
ALLOWED_DISTORTION = {"high", "mid", "low"}
ALLOWED_DATA_STATUS = {
    "live", "weekly", "monthly", "quarterly", "stale",
    "placeholder", "auto_mof", "auto_cftc", "manual_csv", "unknown",
}


@pytest.fixture(scope="module")
def sl():
    if not DATA_JSON.exists():
        pytest.skip("data.json not generated; run fetch_signals.py")
    data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    if "survival_loop" not in data:
        pytest.skip("survival_loop missing; build pending (Agent B)")
    return data["survival_loop"]


def test_top_level_keys(sl):
    for k in ("as_of", "version", "risk_gate", "auto_risk", "pattern_table",
              "candidates", "mode_a_positions", "bankruptcy_simulation", "notes"):
        assert k in sl, f"survival_loop.{k} missing"


def test_risk_gate(sl):
    g = sl["risk_gate"]
    assert g["label"] in ALLOWED_RISK_LABEL
    assert g["color"] in ALLOWED_COLOR
    assert isinstance(g["reasons"], list)


def test_auto_risk_within_hard_caps(sl):
    ar = sl["auto_risk"]
    assert 0.0 <= ar["per_trade_pct"] <= 0.5, (
        f"per_trade_pct {ar['per_trade_pct']} violates HARD_CAPS"
    )
    assert ar["max_concurrent"] <= 3
    assert ar["dd_shrink_pct"] == -10.0
    assert ar["dd_stop_pct"] == -15.0
    assert "source" in ar


def test_pattern_table_structure(sl):
    pt = sl["pattern_table"]
    assert isinstance(pt, dict) and pt
    for key, cell in pt.items():
        regime, _, distortion = key.partition("|")
        assert regime in ALLOWED_REGIME, key
        assert distortion in ALLOWED_DISTORTION, key
        assert cell["stop_loss_pct"] < 0
        assert cell["take_profit_pct"] > 0


def test_candidates_have_required_fields(sl):
    for c in sl["candidates"][:5]:
        for k in ("symbol", "market", "edge_score", "data_status", "as_of"):
            assert k in c, f"candidate missing {k}: {c}"
        assert c["data_status"] in ALLOWED_DATA_STATUS, c
        if c["edge_score"] is not None:
            assert 0 <= c["edge_score"] <= 100


def test_mode_a_positions_respect_caps(sl):
    pos = sl["mode_a_positions"]
    assert len(pos) <= 3
    for p in pos:
        assert p["size_pct"] <= 0.5
        assert p["direction"] in {"long", "short"}
        assert p["pattern"]["regime"] in ALLOWED_REGIME
        assert p["pattern"]["distortion"] in ALLOWED_DISTORTION
        assert p["exit"]["stop_loss_pct"] < 0
        assert p["exit"]["take_profit_pct"] > 0


def test_bankruptcy_simulation_grid(sl):
    bs = sl["bankruptcy_simulation"]
    assert isinstance(bs["risk_grid"], list) and bs["risk_grid"]
    for cell in bs["risk_grid"]:
        assert 0.0 <= cell["risk_pct"] <= 0.5
        assert 0.0 <= cell["ror_mc"] <= 1.0


def test_no_execution_advice_text(sl):
    blob = json.dumps(sl, ensure_ascii=False).lower()
    forbidden = ["buy now", "sell now", "long now", "short now",
                 "entry recommended", "take profit at", "stop loss at"]
    for f in forbidden:
        assert f not in blob, f"forbidden execution advice text: {f}"
