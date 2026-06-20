"""collector スキーマ契約 (SPEC_AUTOCOLLECT §2.2, §3, §7.5).

snapshot と collect_log.jsonl の必須キーを実装側に強制する。
"""
import json
import pathlib

import pytest

sn = pytest.importorskip("collector.snapshot", reason="Agent B 未実装")
lg = pytest.importorskip("collector.log", reason="Agent E 未実装")


REQUIRED_SNAPSHOT_KEYS = {
    "date", "as_of_utc",
    "data_status_counts", "money_flow_snapshot",
    "survival_loop", "mode_b_intents",
}
REQUIRED_SURVIVAL_SUB = {"risk_gate", "auto_risk", "mode_a_positions", "candidates_top"}
REQUIRED_LOG_KEYS = {
    "run_at_utc", "run_at_jst_date", "workflow", "duration_sec",
    "sources", "history_written", "history_size_kb", "git_changed", "errors",
}
SOURCE_NAMES = {"yfinance", "fred", "fiscaldata", "cftc_cot", "coingecko", "mof_jgb"}


def _full_payload():
    return {
        "date": "2026-06-21",
        "as_of_utc": "2026-06-21T00:00:00+00:00",
        "data_status_counts": {"live": 100, "placeholder": 2},
        "money_flow_snapshot": {"us": {"cb_assets": {}, "debt": {}, "freshness_badge": "weekly"},
                                "eu": {"cb_assets": {}, "debt": {}, "freshness_badge": "weekly"},
                                "jp": {"cb_assets": {}, "debt": {}, "freshness_badge": "stale"}},
        "survival_loop": {
            "risk_gate": {"label": "neutral", "color": "yellow", "score": 0},
            "auto_risk": {"per_trade_pct": 0.14, "max_concurrent": 3,
                          "dd_shrink_pct": -10.0, "dd_stop_pct": -15.0},
            "mode_a_positions": [],
            "candidates_top": [],
        },
        "mode_b_intents": [],
    }


def test_snapshot_payload_contract(tmp_path):
    sn.write_snapshot(_full_payload(), root=tmp_path)
    body = json.loads((tmp_path / "2026-06-21.json").read_text())
    missing = REQUIRED_SNAPSHOT_KEYS - set(body.keys())
    assert not missing, f"snapshot missing keys: {missing}"
    sub_missing = REQUIRED_SURVIVAL_SUB - set(body["survival_loop"].keys())
    assert not sub_missing, f"survival_loop subkeys missing: {sub_missing}"


def test_snapshot_extract_from_payload_keys():
    """collector.snapshot.extract(data_json_dict) returns a contracts-compliant payload."""
    fake_data = {
        "meta": {"updated_at": "2026-06-21T00:00:00+09:00",
                 "updated_at_str": "2026-06-21 00:00 JST"},
        "markets": {"nikkei225": [{"data_status": "live"}],
                    "fx": [{"data_status": "live"}, {"data_status": "placeholder"}]},
        "money_flow": {"us": {"cb_assets": {}, "debt": {}, "freshness_badge": "weekly"},
                       "eu": {"cb_assets": {}, "debt": {}, "freshness_badge": "weekly"},
                       "jp": {"cb_assets": {}, "debt": {}, "freshness_badge": "stale"}},
        "survival_loop": {
            "risk_gate": {"label": "risk-on", "color": "green", "score": 1, "reasons": []},
            "auto_risk": {"per_trade_pct": 0.14, "max_concurrent": 3,
                          "dd_shrink_pct": -10.0, "dd_stop_pct": -15.0},
            "mode_a_positions": [{"symbol": "AAPL", "size_pct": 0.14}],
            "candidates": [{"symbol": "AAPL", "edge_score": 75, "direction_hint": "long",
                            "data_status": "live"}],
        },
    }
    p = sn.extract(fake_data)
    missing = REQUIRED_SNAPSHOT_KEYS - set(p.keys())
    assert not missing, f"extract output missing keys: {missing}"
    assert p["date"] == "2026-06-21"
    assert p["survival_loop"]["mode_a_positions"][0]["symbol"] == "AAPL"
    # candidates_top is truncated to <= 5
    assert len(p["survival_loop"]["candidates_top"]) <= 5
    # data_status_counts collated
    assert p["data_status_counts"]["live"] == 2
    assert p["data_status_counts"]["placeholder"] == 1


def test_collect_log_contract(tmp_path):
    lg.write_entry({
        "run_at_utc": "2026-06-21T00:00:00Z",
        "run_at_jst_date": "2026-06-21",
        "workflow": "collect",
        "duration_sec": 12.3,
        "sources": {s: {"ok": 1, "failed": 0} for s in SOURCE_NAMES},
        "history_written": "data/history/2026-06-21.json",
        "history_size_kb": 4.2,
        "git_changed": True,
        "errors": [],
    }, root=tmp_path)
    f = tmp_path / "collect_log.jsonl"
    assert f.exists()
    body = json.loads(f.read_text().strip())
    missing = REQUIRED_LOG_KEYS - set(body.keys())
    assert not missing, f"collect_log missing keys: {missing}"


def test_collect_log_jsonl_is_appended(tmp_path):
    for i in range(3):
        lg.write_entry({
            "run_at_utc": f"2026-06-2{i+1}T00:00:00Z",
            "run_at_jst_date": f"2026-06-2{i+1}",
            "workflow": "collect",
            "duration_sec": 1.0,
            "sources": {},
            "history_written": "",
            "history_size_kb": 0.0,
            "git_changed": False,
            "errors": [],
        }, root=tmp_path)
    lines = [l for l in (tmp_path / "collect_log.jsonl").read_text().splitlines() if l.strip()]
    assert len(lines) == 3
