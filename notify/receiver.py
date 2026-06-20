"""notify.receiver — 60 秒ループ + 1 サイクル (SPEC_NOTIFY §1).

責務:
  * docs/data.json を読む
  * survival_loop.mode_a_positions に対応する ENTRY 通知を発火 (重複は seen で抑止)
  * data/local/notifications.jsonl にハッシュチェーン追記
  * config.local の `notify_enabled` / `ntfy_topic` を読み、未設定なら no-op

Phase 2 (学習) / Phase 3 (勝敗判定) は本ファイルには持ち込まない。
EXIT イベントの自動発火 (TP/SL/TIMEOUT 判定) は notify.triggers.evaluate に集約。
本 receiver は本フェーズでは ENTRY を中心に動かし、EXIT 判定は将来の bar 連続供給
を待つ (Phase 3).
"""

from __future__ import annotations

import datetime
import json
import pathlib
import time
from typing import Any, Dict, List, Optional

from . import bus, chain, config

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_JSON_PATH = ROOT / "docs" / "data.json"
LOCAL_DIR = ROOT / "data" / "local"
CHAIN_PATH = LOCAL_DIR / "notifications.jsonl"


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _entry_payload(p: Dict[str, Any]) -> Dict[str, Any]:
    """Translate one mode_a_positions row into an ENTRY chain payload."""
    pat = p.get("pattern") or {}
    exit_ = p.get("exit") or {}
    return {
        "kind": "ENTRY",
        "symbol": p.get("symbol"),
        "side": p.get("direction", "long"),
        "bar_tf": "1d",
        "bar_ts": str(p.get("entry_date") or ""),
        "price": None,                       # price isn't exposed in mode_a_positions
        "edge_score": p.get("entry_edge_score"),
        "entry_ref": None,
        "pattern": {"regime": pat.get("regime", "low_vol"),
                    "distortion": pat.get("distortion", "mid")},
        "size_pct": float(p.get("size_pct", 0.0)),
        "exit_targets": {
            "take_profit_pct": float(exit_.get("take_profit_pct", 0.0)),
            "stop_loss_pct": float(exit_.get("stop_loss_pct", 0.0)),
        },
        "realized_pct": None,
    }


def _stable_position_id(pos: Dict[str, Any]) -> str:
    """Stable identifier so daily re-runs do not re-send the same ENTRY."""
    sym = pos.get("symbol") or ""
    d = pos.get("entry_date") or ""
    side = pos.get("direction") or ""
    return f"mode-a/{d}/{side}/{sym}"


def run_once() -> Dict[str, Any]:
    """One pass over the freshest data.json."""
    cfg = config.load()
    enabled = config.is_notify_enabled(cfg)
    topic = config.ntfy_topic(cfg) if enabled else None
    bus.SOUND = config.mac_notify_sound(cfg) if enabled else "Glass"

    if not DATA_JSON_PATH.exists():
        return {"ok": True, "notified": 0, "reason": "no_data_json"}

    try:
        data = json.loads(DATA_JSON_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "notified": 0, "reason": "parse_error",
                "error": str(exc)[:120]}

    if not enabled:
        # SPEC §5.3: config 不在 / 無効でも落とさない
        return {"ok": True, "notified": 0, "reason": "no_config"}

    sl = data.get("survival_loop") or {}
    positions = sl.get("mode_a_positions") or []

    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    c = chain.Chain(CHAIN_PATH)
    already_known_event_ids = {r["event_id"] for r in c.rows()}
    sent_count = 0

    # First flush any earlier failures so they get re-sent on this pass.
    try:
        bus.flush(topic=topic)
    except Exception:
        pass

    for pos in positions:
        stable_id = _stable_position_id(pos)
        if stable_id in already_known_event_ids:
            continue
        payload = _entry_payload(pos)
        payload["event_id"] = stable_id
        try:
            row = c.append(payload)
        except Exception:
            # Chain failure should not crash the loop; surface via flush queue.
            continue
        try:
            res = bus.send_both(row, topic=topic)
            if res.get("sent") or res.get("dedup"):
                sent_count += 1
        except Exception:
            pass

    return {"ok": True, "notified": sent_count}


def loop(interval_sec: int = 60) -> None:
    """Long-running launchd entry. Sleeps between sweeps; runs forever.

    launchd KeepAlive will restart the process if it dies (SPEC §8).
    """
    while True:
        try:
            run_once()
        except Exception:
            # never let an exception escape the loop
            pass
        time.sleep(max(5, int(interval_sec)))


if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        print(json.dumps(run_once(), ensure_ascii=False, indent=2))
    else:
        loop()
