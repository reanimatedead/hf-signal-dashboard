"""notify.bus — osascript + ntfy.sh 通知経路 (SPEC_NOTIFY §5).

両経路を試行し、両方失敗時は data/local/notify_queue.jsonl に積み、次サイクルで flush().
event_id 単位の dedup (24 h) を保持する。
"""

from __future__ import annotations

import datetime
import json
import pathlib
import subprocess
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


# ── パス (テストで monkeypatch されるためモジュール変数で公開) ──
ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCAL_DIR = ROOT / "data" / "local"
QUEUE_PATH = LOCAL_DIR / "notify_queue.jsonl"
SEEN_PATH = LOCAL_DIR / "notify_seen.jsonl"
DEDUP_WINDOW_SEC = 24 * 60 * 60

_NTFY_URL = "https://ntfy.sh/"
_TIMEOUT = 5
_PRIORITY = {"ENTRY": "urgent", "EXIT_TP": "high", "EXIT_SL": "high", "EXIT_TIMEOUT": "default"}
_NOTICE = "事実記録 / not investment advice"

# Module-level sound (receiver overrides per config). Test contract keeps
# send_both/send_osascript signature simple — see tests/test_notify_bus.py.
SOUND = "Glass"


# ── helpers ─────────────────────────────────────────────────
def _now_ts() -> float:
    return datetime.datetime.now(datetime.timezone.utc).timestamp()


def _ensure_local():
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)


def _seen_recent() -> Dict[str, float]:
    out: Dict[str, float] = {}
    if not SEEN_PATH.exists():
        return out
    cutoff = _now_ts() - DEDUP_WINDOW_SEC
    for line in SEEN_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = float(rec.get("ts", 0))
        if ts < cutoff:
            continue
        eid = rec.get("event_id")
        if eid:
            out[eid] = ts
    return out


def _mark_seen(event_id: str):
    _ensure_local()
    with SEEN_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"event_id": event_id, "ts": _now_ts()},
                           ensure_ascii=False) + "\n")


def _enqueue(row: Dict[str, Any], topic: Optional[str]):
    _ensure_local()
    rec = {"row": row, "topic": topic, "ts": _now_ts()}
    with QUEUE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _format_body(row: Dict[str, Any]) -> str:
    sym = row.get("symbol", "—")
    side = row.get("side", "—")
    price = row.get("price")
    edge = row.get("edge_score")
    kind = row.get("kind", "?")
    head = f"{kind} {sym} {side}"
    if price is not None:
        try:
            head += f" @ {float(price):.4f}"
        except (TypeError, ValueError):
            head += f" @ {price}"
    if edge is not None:
        head += f" edge={edge}"
    pat = row.get("pattern") or {}
    if pat:
        head += f" [{pat.get('regime','?')}/{pat.get('distortion','?')}]"
    return f"{head} | {_NOTICE}"


# ── osascript 経路 ──────────────────────────────────────────
def send_osascript(row: Dict[str, Any], sound: Optional[str] = None) -> bool:
    sound = sound or SOUND
    title = f"hf {row.get('kind','?')} {row.get('symbol','')}"
    body = _format_body(row)
    # escape double quotes
    body_q = body.replace("\\", "\\\\").replace('"', '\\"')
    title_q = title.replace("\\", "\\\\").replace('"', '\\"')
    snippet = (
        f'display notification "{body_q}" with title "{title_q}" '
        f'sound name "{sound}"'
    )
    try:
        r = subprocess.run(["osascript", "-e", snippet],
                           capture_output=True, text=True, timeout=_TIMEOUT)
        return r.returncode == 0
    except Exception:
        return False


# ── ntfy 経路 ───────────────────────────────────────────────
def send_ntfy(row: Dict[str, Any], topic: Optional[str]) -> bool:
    if not topic:
        return False
    if not isinstance(topic, str) or not topic.strip():
        return False
    url = _NTFY_URL + topic.strip()
    body = _format_body(row).encode("utf-8")
    title = f"hf {row.get('kind','?')} {row.get('symbol','')}"
    priority = _PRIORITY.get(row.get("kind", ""), "default")
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": "hf-signal-dashboard",
        "Content-Type": "text/plain; charset=utf-8",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            status = getattr(r, "status", 200)
            return 200 <= int(status) < 300
    except Exception:
        return False


# ── 送信 facade ─────────────────────────────────────────────
def send_both(row: Dict[str, Any], topic: Optional[str] = None) -> Dict[str, Any]:
    """Send via both routes. Dedup by event_id within DEDUP_WINDOW_SEC.

    Returns {"sent": bool, "dedup": bool, "osascript": bool, "ntfy": bool}.
    Never raises. Failures are queued for the next flush().
    """
    eid = row.get("event_id") or ""
    if eid:
        seen = _seen_recent()
        if eid in seen:
            return {"sent": False, "dedup": True, "osascript": False, "ntfy": False}

    osa = False
    nt = False
    try:
        osa = bool(send_osascript(row))
    except Exception:
        osa = False
    try:
        nt = bool(send_ntfy(row, topic=topic))
    except Exception:
        nt = False
    sent = osa or nt
    if not sent:
        _enqueue(row, topic)
    if eid:
        _mark_seen(eid)
    return {"sent": sent, "dedup": False, "osascript": osa, "ntfy": nt}


def flush(topic: Optional[str] = None) -> Dict[str, int]:
    """Re-send queued rows. Removes successes from the queue."""
    if not QUEUE_PATH.exists():
        return {"resent": 0, "remaining": 0}
    keep = []
    resent = 0
    for line in QUEUE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        row = rec.get("row") or {}
        t = rec.get("topic") or topic
        ok_a = False
        ok_n = False
        try:
            ok_a = bool(send_osascript(row))
        except Exception:
            ok_a = False
        try:
            ok_n = bool(send_ntfy(row, topic=t))
        except Exception:
            ok_n = False
        if ok_a or ok_n:
            resent += 1
        else:
            keep.append(line)
    if keep:
        QUEUE_PATH.write_text("\n".join(keep) + "\n", encoding="utf-8")
    else:
        QUEUE_PATH.write_text("", encoding="utf-8")
    return {"resent": resent, "remaining": len(keep)}


# ── smoke helpers (Mac mini 上で手動確認用) ────────────────
def smoke_local(text: str = "hello from hf") -> bool:
    return send_osascript({"kind": "INFO", "symbol": "smoke",
                           "side": "—", "price": None,
                           "edge_score": None})


def smoke_ntfy(text: str = "hello via ntfy", topic_override: str = "") -> bool:
    return send_ntfy({"kind": "INFO", "symbol": "smoke", "side": "—",
                      "price": None, "edge_score": None}, topic=topic_override)
