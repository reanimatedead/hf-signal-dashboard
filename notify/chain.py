"""notify.chain — append-only ハッシュチェーン台帳 (SPEC_NOTIFY §3).

ファイル: data/local/notifications.jsonl (1 行 1 イベント).
不変条件:
  * Chain.append のみで書く。UPDATE / DELETE API 無し。
  * verify() = 全ハッシュチェーンの整合確認。
  * unmatched_entries() = EXIT_* 未確定の ENTRY を列挙。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple


GENESIS_HASH = "0" * 64
EXIT_KINDS = ("EXIT_TP", "EXIT_SL", "EXIT_TIMEOUT")
NOTICE = "事実記録 / not investment advice"

# Fields excluded from the hash input (they are the chain wrapper, not payload).
_HASH_EXCLUDED = {"prev_hash", "curr_hash"}


def _canonical(payload: Dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k not in _HASH_EXCLUDED}
    return json.dumps(body, ensure_ascii=False, sort_keys=True)


def _compute_hash(prev_hash: str, payload: Dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + _canonical(payload)).encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


class Chain:
    """Append-only ledger backed by a single jsonl file."""

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._rows: List[Dict[str, Any]] = self._load()
        # Mapping event_id -> row (built on read).
        self._by_id: Dict[str, Dict[str, Any]] = {r["event_id"]: r for r in self._rows}
        # Set of ENTRY ids that are still open (no EXIT_* yet).
        self._open_entries: List[str] = []
        for r in self._rows:
            if r["kind"] == "ENTRY":
                self._open_entries.append(r["event_id"])
            elif r["kind"] in EXIT_KINDS:
                ref = r.get("entry_ref")
                if ref in self._open_entries:
                    self._open_entries.remove(ref)

    # ── load ----------------------------------------------------
    def _load(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # leave invalid rows in place but skip in memory (verify() will catch)
                continue
        return out

    # ── public read API ----------------------------------------
    def __len__(self) -> int:
        return len(self._rows)

    def rows(self) -> List[Dict[str, Any]]:
        return list(self._rows)

    def find(self, event_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(event_id)

    def unmatched_entries(self) -> List[Dict[str, Any]]:
        return [self._by_id[eid] for eid in self._open_entries if eid in self._by_id]

    def fingerprint(self) -> str:
        if not self._rows:
            return GENESIS_HASH
        return self._rows[-1]["curr_hash"]

    # ── append (the only mutator) ------------------------------
    def append(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        kind = payload.get("kind")
        if kind not in ("ENTRY",) + EXIT_KINDS:
            raise ValueError(f"unknown kind: {kind!r}")

        # EXIT requires a matching ENTRY ref.
        if kind in EXIT_KINDS:
            ref = payload.get("entry_ref")
            if not ref:
                raise ValueError("EXIT_* requires entry_ref")
            entry = self._by_id.get(ref)
            if not entry or entry["kind"] != "ENTRY":
                raise ValueError(f"entry_ref does not match any prior ENTRY: {ref}")
            if ref not in self._open_entries:
                raise ValueError(f"entry_ref already closed: {ref}")

        row = dict(payload)
        row.setdefault("event_id", uuid.uuid4().hex)
        row.setdefault("ts_utc", _utc_now_iso())
        row.setdefault("notice", NOTICE)
        prev_hash = self._rows[-1]["curr_hash"] if self._rows else GENESIS_HASH
        row["prev_hash"] = prev_hash
        row["curr_hash"] = _compute_hash(prev_hash, row)

        # Persist (append-only).
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

        self._rows.append(row)
        self._by_id[row["event_id"]] = row
        if kind == "ENTRY":
            self._open_entries.append(row["event_id"])
        elif kind in EXIT_KINDS:
            ref = row["entry_ref"]
            if ref in self._open_entries:
                self._open_entries.remove(ref)
        return row

    # ── verify --------------------------------------------------
    def verify(self) -> Tuple[bool, Optional[int], Optional[str]]:
        """Re-scan from disk to defeat in-memory shenanigans."""
        if not self.path.exists():
            return True, None, None
        prev_hash = GENESIS_HASH
        seen_ids: set = set()
        open_ids: set = set()
        for i, line in enumerate(self.path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                return False, i, "json_decode"
            if row.get("prev_hash") != prev_hash:
                return False, i, "prev_hash_mismatch"
            expected = _compute_hash(prev_hash, row)
            if row.get("curr_hash") != expected:
                return False, i, "curr_hash_mismatch"
            ev = row.get("event_id")
            if not ev or ev in seen_ids:
                return False, i, "duplicate_or_missing_event_id"
            seen_ids.add(ev)
            kind = row.get("kind")
            if kind == "ENTRY":
                open_ids.add(ev)
            elif kind in EXIT_KINDS:
                ref = row.get("entry_ref")
                if not ref or ref not in seen_ids:
                    return False, i, "exit_without_entry"
                # entry_ref already-closed is allowed at verify time
                open_ids.discard(ref)
            prev_hash = row["curr_hash"]
        return True, None, None

    # ── export (public-safe abridged) --------------------------
    def export_public(self) -> List[Dict[str, Any]]:
        """Return rows with `price` stripped — for frontend display."""
        out = []
        for r in self._rows:
            safe = {k: v for k, v in r.items() if k != "price"}
            out.append(safe)
        return out
