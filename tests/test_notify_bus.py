"""notify.bus — osascript / ntfy 経路 + queue + retry (SPEC_NOTIFY §5, §10.1)."""
import json
import pathlib
import pytest

bus = pytest.importorskip(
    "notify.bus",
    reason="Agent B 未実装。notify/bus.py を作ると緑になる。",
)


def _row(symbol="AAPL", kind="ENTRY", price=100.0):
    return {
        "event_id": "uuid-fake-1",
        "ts_utc": "2026-06-20T00:00:00Z",
        "kind": kind,
        "symbol": symbol,
        "side": "long",
        "price": price,
        "edge_score": 80,
        "pattern": {"regime": "high_vol", "distortion": "high"},
        "exit_targets": {"take_profit_pct": 3.0, "stop_loss_pct": -2.0},
        "notice": "事実記録 / not investment advice",
        "prev_hash": "0" * 64,
        "curr_hash": "a" * 64,
    }


# ── osascript ────────────────────────────────────────
def test_send_osascript_invokes_subprocess(monkeypatch):
    calls = {"args": None}
    def fake_run(args, **kw):
        calls["args"] = args
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()
    monkeypatch.setattr(bus.subprocess, "run", fake_run)
    ok = bus.send_osascript(_row())
    assert ok is True
    assert calls["args"][0] == "osascript"
    # 通知本文に GRC 文言が必ず含まれる
    joined = " ".join(calls["args"])
    assert "事実記録" in joined or "not investment advice" in joined


def test_send_osascript_returns_false_on_failure(monkeypatch):
    def boom(args, **kw):
        raise RuntimeError("no osascript")
    monkeypatch.setattr(bus.subprocess, "run", boom)
    assert bus.send_osascript(_row()) is False


# ── ntfy ─────────────────────────────────────────────
def test_send_ntfy_posts_to_topic_url(monkeypatch):
    captured = {}
    class FakeResp:
        status = 200
        def read(self): return b"ok"
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = req.data
        return FakeResp()
    monkeypatch.setattr(bus.urllib.request, "urlopen", fake_urlopen)
    ok = bus.send_ntfy(_row(), topic="hf-secret-topic")
    assert ok is True
    assert "ntfy.sh/hf-secret-topic" in captured["url"]
    # priority は ENTRY=5 (urgent) (SPEC §5.1)
    norm = {k.lower(): v for k, v in captured["headers"].items()}
    assert norm.get("priority") in ("urgent", "5")
    body = captured["body"].decode("utf-8") if captured["body"] else ""
    assert "事実記録" in body or "not investment advice" in body


def test_send_ntfy_no_topic_returns_false():
    assert bus.send_ntfy(_row(), topic=None) is False
    assert bus.send_ntfy(_row(), topic="") is False


def test_send_ntfy_handles_http_error(monkeypatch):
    def fail(req, timeout):
        raise RuntimeError("HTTP 503")
    monkeypatch.setattr(bus.urllib.request, "urlopen", fail)
    assert bus.send_ntfy(_row(), topic="hf-x") is False


# ── send_both: queue + dedup ───────────────────────
def test_send_both_dedup_within_24h(monkeypatch, tmp_path):
    monkeypatch.setattr(bus, "QUEUE_PATH", tmp_path / "queue.jsonl")
    monkeypatch.setattr(bus, "SEEN_PATH", tmp_path / "seen.jsonl")
    monkeypatch.setattr(bus, "send_osascript", lambda r: True)
    monkeypatch.setattr(bus, "send_ntfy", lambda r, topic=None: True)
    r = _row()
    res1 = bus.send_both(r, topic="hf-x")
    res2 = bus.send_both(r, topic="hf-x")
    assert res1["sent"] is True
    assert res2["sent"] is False, "second send with same event_id must dedup"
    assert res2["dedup"] is True


def test_send_both_queues_on_total_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(bus, "QUEUE_PATH", tmp_path / "queue.jsonl")
    monkeypatch.setattr(bus, "SEEN_PATH", tmp_path / "seen.jsonl")
    monkeypatch.setattr(bus, "send_osascript", lambda r: False)
    monkeypatch.setattr(bus, "send_ntfy", lambda r, topic=None: False)
    bus.send_both(_row(), topic="hf-x")
    assert (tmp_path / "queue.jsonl").exists()
    lines = (tmp_path / "queue.jsonl").read_text().splitlines()
    assert len(lines) == 1


def test_flush_resends_queued_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(bus, "QUEUE_PATH", tmp_path / "queue.jsonl")
    monkeypatch.setattr(bus, "SEEN_PATH", tmp_path / "seen.jsonl")
    # 1) 失敗を 2 件 queue に積む
    monkeypatch.setattr(bus, "send_osascript", lambda r: False)
    monkeypatch.setattr(bus, "send_ntfy", lambda r, topic=None: False)
    bus.send_both(_row(symbol="AAPL"), topic="hf-x")
    r2 = _row(symbol="MSFT")
    r2["event_id"] = "uuid-fake-2"
    bus.send_both(r2, topic="hf-x")
    # 2) 復活、flush 成功 → queue が空に
    monkeypatch.setattr(bus, "send_osascript", lambda r: True)
    monkeypatch.setattr(bus, "send_ntfy", lambda r, topic=None: True)
    bus.flush(topic="hf-x")
    body = (tmp_path / "queue.jsonl").read_text().strip()
    assert body == "", f"flush should drain queue; remaining: {body!r}"


# ── config 不在で no-op (落とさない) ────────────────
def test_send_both_noop_when_topic_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(bus, "QUEUE_PATH", tmp_path / "queue.jsonl")
    monkeypatch.setattr(bus, "SEEN_PATH", tmp_path / "seen.jsonl")
    monkeypatch.setattr(bus, "send_osascript", lambda r: True)
    res = bus.send_both(_row(), topic=None)
    # osascript だけ通っても OK。落ちなければ全体テスト緑。
    assert res["sent"] in (True, False)
    assert res.get("crashed") is not True
