"""pipeline/build_verify.py: 架空データで verify.json の形・直近6か月・weakened の付け方。"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import build_verify as bv  # noqa: E402
from marketcalc import events  # noqa: E402


def test_since_six_months():
    assert bv._since("2026-07-15") == "2026-01-15"
    assert bv._since("2026-03-31") == "2025-09-28"


def test_fixture_cli_and_shape(tmp_path):
    out = tmp_path / "v.json"
    r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "build_verify.py"), "--fixture",
                        str(ROOT / "marketcalc" / "tests" / "fixtures"), "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    v = json.loads(out.read_text())
    assert v["schema"] == bv.SCHEMA and v["method"]["horizon_days"] == events.H == 20
    m = v["markets"]["nikkei225"]
    assert m["recent6m"]["since"] == "2026-01-15"
    assert m["recent6m"]["base"]["n"] <= m["full"]["base"]["n"]
    # weakened は events.weakened と同じ判定（直近版の買い系だけ）
    for k, w in m["weakened"].items():
        lab = k.split(":", 1)[1]
        assert w == events.weakened(m["recent6m"]["chart"][lab], m["recent6m"]["base"])
    assert v["weakened"] == bool(v["weakened_items"])


def test_too_short_series_are_skipped():
    import numpy as np
    c = np.linspace(100, 110, 100)
    import datetime as dt
    d = [(dt.date(2026, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(100)]
    m = bv.verify_market([(d, c, c, c, None)])
    assert m["symbols"] == 0 and m["full"]["base"]["n"] == 0
