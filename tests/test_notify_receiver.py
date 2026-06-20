"""notify.receiver — 1 サイクル e2e (data.json → triggers → chain → bus, 全モック)
SPEC_NOTIFY §1, §10.1.
"""
import json
import pathlib
import pytest

rc = pytest.importorskip(
    "notify.receiver",
    reason="Agent B 未実装。notify/receiver.py を作ると緑になる。",
)


def _fake_data():
    return {
        "meta": {"updated_at": "2026-06-20T00:00:00+09:00"},
        "markets": {
            "fx": [
                {"symbol": "USDJPY=X", "name": "USDJPY", "rsi": 28, "bb_pct": 0.05,
                 "atr": 1.0, "price": 150.0, "cci_daily": -220, "data_status": "live"},
            ],
        },
        "money_flow": {"us": {"cb_assets": {"wow_change": 0.01}}},
        "survival_loop": {
            "auto_risk": {"per_trade_pct": 0.14, "max_concurrent": 3,
                          "dd_shrink_pct": -10.0, "dd_stop_pct": -15.0},
            "pattern_table": {
                "high_vol|high": {"take_profit_pct": 3.5, "stop_loss_pct": -1.8}
            },
            "candidates": [
                {"symbol": "USDJPY=X", "edge_score": 90, "direction_hint": "long",
                 "vol_context_pct": 1.0, "stretch": 0.9, "data_status": "live"}
            ],
            "mode_a_positions": [
                {"symbol": "USDJPY=X", "direction": "long", "entry_edge_score": 90,
                 "pattern": {"regime": "high_vol", "distortion": "high"},
                 "exit": {"take_profit_pct": 3.5, "stop_loss_pct": -1.8},
                 "size_pct": 0.14, "entry_date": "2026-06-20"}
            ]
        }
    }


def test_run_once_sends_entry_for_new_mode_a(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(rc.bus, "send_both",
                        lambda row, topic=None: sent.append(row) or
                        {"sent": True, "dedup": False})
    monkeypatch.setattr(rc.config, "load",
                        lambda: {"notify_enabled": True, "ntfy_topic": "hf-test"})
    monkeypatch.setattr(rc, "DATA_JSON_PATH", tmp_path / "data.json")
    (tmp_path / "data.json").write_text(json.dumps(_fake_data()))
    chain_path = tmp_path / "notifications.jsonl"
    monkeypatch.setattr(rc, "CHAIN_PATH", chain_path)
    res = rc.run_once()
    assert res["ok"] is True
    assert len(sent) >= 1
    assert any(r["kind"] == "ENTRY" for r in sent)
    # chain にも 1 行以上書き込まれている
    assert chain_path.exists() and chain_path.read_text().strip()


def test_run_once_idempotent_for_same_position(monkeypatch, tmp_path):
    """同じ mode_a position に対して 2 回 run しても dedup で 1 イベントしか出さない."""
    sent_count = {"n": 0}
    seen = set()
    def fake_send(row, topic=None):
        if row["event_id"] in seen:
            return {"sent": False, "dedup": True}
        seen.add(row["event_id"])
        sent_count["n"] += 1
        return {"sent": True, "dedup": False}
    monkeypatch.setattr(rc.bus, "send_both", fake_send)
    monkeypatch.setattr(rc.config, "load",
                        lambda: {"notify_enabled": True, "ntfy_topic": "hf-test"})
    monkeypatch.setattr(rc, "DATA_JSON_PATH", tmp_path / "data.json")
    (tmp_path / "data.json").write_text(json.dumps(_fake_data()))
    monkeypatch.setattr(rc, "CHAIN_PATH", tmp_path / "notifications.jsonl")
    rc.run_once()
    n1 = sent_count["n"]
    rc.run_once()
    assert sent_count["n"] == n1, "second run must not re-send the same ENTRY"


def test_run_once_quiet_when_no_config(monkeypatch, tmp_path):
    monkeypatch.setattr(rc.config, "load", lambda: None)
    monkeypatch.setattr(rc, "DATA_JSON_PATH", tmp_path / "data.json")
    (tmp_path / "data.json").write_text(json.dumps(_fake_data()))
    monkeypatch.setattr(rc, "CHAIN_PATH", tmp_path / "notifications.jsonl")
    res = rc.run_once()
    assert res["ok"] is True
    assert res["notified"] == 0, "no config => no notifications"
    assert res.get("reason") == "no_config"


def test_run_once_quiet_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(rc.config, "load",
                        lambda: {"notify_enabled": False, "ntfy_topic": "hf-test"})
    monkeypatch.setattr(rc, "DATA_JSON_PATH", tmp_path / "data.json")
    (tmp_path / "data.json").write_text(json.dumps(_fake_data()))
    monkeypatch.setattr(rc, "CHAIN_PATH", tmp_path / "notifications.jsonl")
    res = rc.run_once()
    assert res["notified"] == 0
