"""loop.log — append-only ハッシュチェーン ログ (SPEC_LOOP §5).

notify.chain の思想を流用. data/local/loop_trials.jsonl に試行を 1 行ずつ書き込み、
prev_hash + canonical_json → sha256 → curr_hash で連鎖.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import uuid
from typing import Any, Dict, List, Optional, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
TRIALS_LOG_PATH = ROOT / "data" / "local" / "loop_trials.jsonl"
GENESIS_HASH = "0" * 64
_HASH_EXCLUDED = {"prev_hash", "curr_hash"}


def _canonical(payload: Dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k not in _HASH_EXCLUDED}
    return json.dumps(body, ensure_ascii=False, sort_keys=True)


def _compute_hash(prev_hash: str, payload: Dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + _canonical(payload)).encode("utf-8")).hexdigest()


def _last_curr_hash(path: pathlib.Path) -> str:
    if not path.exists():
        return GENESIS_HASH
    last = GENESIS_HASH
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        ch = row.get("curr_hash")
        if isinstance(ch, str):
            last = ch
    return last


def append_trial(payload: Dict[str, Any],
                 path: Optional[pathlib.Path] = None) -> Dict[str, Any]:
    """append-only で試行行を書き込む. 既存行は変更しない."""
    p = pathlib.Path(path or TRIALS_LOG_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = dict(payload)
    row.setdefault("event_id", uuid.uuid4().hex)
    row.setdefault("ts_utc", datetime.datetime.now(datetime.timezone.utc)
                              .replace(microsecond=0).isoformat())
    row.setdefault("kind", "LOOP_TRIAL")
    prev = _last_curr_hash(p)
    row["prev_hash"] = prev
    row["curr_hash"] = _compute_hash(prev, row)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def verify(path: Optional[pathlib.Path] = None) -> Tuple[bool, Optional[int], Optional[str]]:
    p = pathlib.Path(path or TRIALS_LOG_PATH)
    if not p.exists():
        return True, None, None
    prev = GENESIS_HASH
    seen = set()
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            return False, i, "json_decode"
        if row.get("prev_hash") != prev:
            return False, i, "prev_hash_mismatch"
        expected = _compute_hash(prev, row)
        if row.get("curr_hash") != expected:
            return False, i, "curr_hash_mismatch"
        ev = row.get("event_id")
        if not ev or ev in seen:
            return False, i, "duplicate_or_missing_event_id"
        seen.add(ev)
        prev = row["curr_hash"]
    return True, None, None


def rows(path: Optional[pathlib.Path] = None) -> List[Dict[str, Any]]:
    p = pathlib.Path(path or TRIALS_LOG_PATH)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
