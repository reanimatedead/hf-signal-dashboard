"""collector の冪等性 (SPEC_AUTOCOLLECT §2.3, §7.2)

同日中に 2 回 snapshot を書いても:
  - data/history/YYYY-MM-DD.json は最新版で正規化されている (重複行なし)
  - data/history/index.jsonl は同日エントリが 1 行に正規化される
  - 二度目の write は同一データなら git_changed=False を返す
"""
import json
import pathlib
import shutil
import tempfile

import pytest

sn = pytest.importorskip(
    "collector.snapshot",
    reason="Agent B 未実装。collector/snapshot.py を作ると緑になる。",
)


@pytest.fixture
def tmp_history(tmp_path):
    """tmp_path/history/ をルートにして snapshot module を呼ぶ."""
    root = tmp_path / "history"
    root.mkdir()
    yield root


def _payload(day):
    return {
        "date": day,
        "as_of_utc": day + "T00:00:00+00:00",
        "data_status_counts": {"live": 100},
        "money_flow_snapshot": {"us": {}, "eu": {}, "jp": {}},
        "survival_loop": {
            "risk_gate": {"label": "neutral", "color": "yellow", "score": 0},
            "auto_risk": {"per_trade_pct": 0.2, "max_concurrent": 3},
            "mode_a_positions": [],
            "candidates_top": [],
        },
        "mode_b_intents": [],
    }


def test_snapshot_creates_dated_file(tmp_history):
    res = sn.write_snapshot(_payload("2026-06-20"), root=tmp_history)
    f = tmp_history / "2026-06-20.json"
    assert f.exists(), f"{f} should exist"
    assert res["path"].endswith("2026-06-20.json")


def test_snapshot_second_write_same_day_is_idempotent(tmp_history):
    sn.write_snapshot(_payload("2026-06-20"), root=tmp_history)
    res2 = sn.write_snapshot(_payload("2026-06-20"), root=tmp_history)
    files = sorted(p.name for p in tmp_history.glob("*.json"))
    assert files == ["2026-06-20.json"], (
        f"second write must overwrite, not duplicate: got {files}"
    )
    assert res2["changed"] is False, "identical payload must yield changed=False"


def test_index_jsonl_has_one_line_per_day(tmp_history):
    sn.write_snapshot(_payload("2026-06-20"), root=tmp_history)
    sn.write_snapshot(_payload("2026-06-20"), root=tmp_history)
    sn.write_snapshot(_payload("2026-06-21"), root=tmp_history)
    sn.write_snapshot(_payload("2026-06-21"), root=tmp_history)
    idx = tmp_history / "index.jsonl"
    assert idx.exists()
    lines = [l for l in idx.read_text().splitlines() if l.strip()]
    dates = [json.loads(l)["date"] for l in lines]
    assert sorted(dates) == ["2026-06-20", "2026-06-21"], dates


def test_snapshot_changed_when_payload_differs(tmp_history):
    sn.write_snapshot(_payload("2026-06-20"), root=tmp_history)
    p2 = _payload("2026-06-20")
    p2["data_status_counts"]["live"] = 99
    res = sn.write_snapshot(p2, root=tmp_history)
    assert res["changed"] is True


def test_snapshot_size_capped(tmp_history):
    """snapshot は abridged で 200KB を大幅に超えてはいけない (回帰防止)."""
    p = _payload("2026-06-20")
    sn.write_snapshot(p, root=tmp_history)
    f = tmp_history / "2026-06-20.json"
    assert f.stat().st_size < 200 * 1024, f"snapshot too large: {f.stat().st_size} bytes"
