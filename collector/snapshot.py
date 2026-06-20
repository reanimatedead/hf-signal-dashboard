"""collector.snapshot — 日次スナップショット書き出し (SPEC_AUTOCOLLECT §2).

- extract(data_json_dict) -> snapshot_payload (abridged)
- write_snapshot(payload, root) -> {"path": str, "changed": bool, "size_kb": float}
- index.jsonl は同日エントリを 1 行に正規化 (冪等)

TODO(phase-3): mode_b_intents をクライアント側から POST してもらう経路を追加する。
TODO(phase-3): mode_a_positions の翌日以降の勝敗判定 (cross-day P&L) を集約。
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
from typing import Any, Dict, List, Optional


JST = datetime.timezone(datetime.timedelta(hours=9))


def _today_jst_iso() -> str:
    return datetime.datetime.now(JST).date().isoformat()


def _now_utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _count_data_status(markets: Dict[str, list]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for rows in (markets or {}).values():
        for r in rows or []:
            s = r.get("data_status") or ("placeholder" if r.get("error") else "unknown")
            counts[s] = counts.get(s, 0) + 1
    return counts


def _abridged_cb(cb: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("label", "value_usd_tn", "unit", "as_of", "lag_days", "data_status",
            "source", "wow_change")
    return {k: cb.get(k) for k in keys if k in cb}


def _abridged_debt(d: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("label", "value_local_tn", "unit", "as_of", "lag_days", "data_status",
            "source", "change_prev_day")
    return {k: d.get(k) for k in keys if k in d}


def _abridged_region(region_block: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not region_block:
        return {}
    return {
        "cb_assets": _abridged_cb(region_block.get("cb_assets") or {}),
        "debt": _abridged_debt(region_block.get("debt") or {}),
        "freshness_badge": region_block.get("freshness_badge", "stale"),
    }


def _abridged_candidate(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "symbol": c.get("symbol"),
        "name": c.get("name"),
        "edge_score": c.get("edge_score"),
        "direction_hint": c.get("direction_hint"),
        "data_status": c.get("data_status"),
    }


def _date_from_meta(data: Dict[str, Any]) -> str:
    """Prefer JST-anchored date from meta.updated_at; fall back to today JST."""
    meta = data.get("meta") or {}
    upd = meta.get("updated_at") or ""
    if isinstance(upd, str) and len(upd) >= 10:
        # meta.updated_at is JST ISO from fetch_signals
        return upd[:10]
    return _today_jst_iso()


def extract(data_json_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Build an abridged snapshot from a complete data.json dict.

    Markets arrays are NOT included verbatim — only counts and the survival_loop
    candidates_top (<=5). This keeps snapshots small (<200 KB).
    """
    if not isinstance(data_json_dict, dict):
        raise TypeError("extract requires a dict (data.json contents)")
    sl = data_json_dict.get("survival_loop") or {}
    mf = data_json_dict.get("money_flow") or {}
    candidates = sl.get("candidates") or []
    top = [_abridged_candidate(c) for c in candidates[:5]]
    return {
        "date": _date_from_meta(data_json_dict),
        "as_of_utc": _now_utc_iso(),
        "data_status_counts": _count_data_status(data_json_dict.get("markets") or {}),
        "money_flow_snapshot": {
            "us": _abridged_region(mf.get("us")),
            "eu": _abridged_region(mf.get("eu")),
            "jp": _abridged_region(mf.get("jp")),
        },
        "survival_loop": {
            "risk_gate": sl.get("risk_gate") or {},
            "auto_risk": sl.get("auto_risk") or {},
            "mode_a_positions": sl.get("mode_a_positions") or [],
            "candidates_top": top,
        },
        "mode_b_intents": [],   # TODO(phase-3): wire client-side discretionary intents
    }


def _ensure_root(root) -> pathlib.Path:
    p = pathlib.Path(root)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read_index(root: pathlib.Path) -> List[Dict[str, Any]]:
    idx = root / "index.jsonl"
    if not idx.exists():
        return []
    out = []
    for line in idx.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _write_index(root: pathlib.Path, rows: List[Dict[str, Any]]) -> None:
    idx = root / "index.jsonl"
    rows.sort(key=lambda r: r.get("date", ""))
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    idx.write_text(body, encoding="utf-8")


def _substantive_json(payload: Dict[str, Any]) -> str:
    """Stable string used for change detection. Excludes the always-fresh
    `as_of_utc` timestamp so a same-day re-run with identical data reports
    `changed=False` (and the workflow says "No changes to commit").
    """
    body = dict(payload)
    body.pop("as_of_utc", None)
    return json.dumps(body, ensure_ascii=False, sort_keys=True)


def write_snapshot(payload: Dict[str, Any], root, *, indent: Optional[int] = 2
                   ) -> Dict[str, Any]:
    """Idempotently write one daily snapshot under `root`.

    - Re-writes the same date's file. `changed` is True only when the
      substantive content (everything except `as_of_utc`) differs from disk.
    - Normalizes `index.jsonl` to exactly one row per date.
    """
    if not isinstance(payload, dict) or "date" not in payload:
        raise ValueError("payload must be a dict with a 'date' field")
    p_root = _ensure_root(root)
    date = payload["date"]
    target = p_root / f"{date}.json"

    new_body = json.dumps(payload, ensure_ascii=False, indent=indent, sort_keys=True)
    new_sub = _substantive_json(payload)
    changed = True
    if target.exists():
        try:
            old = json.loads(target.read_text(encoding="utf-8"))
            old_sub = _substantive_json(old)
            changed = old_sub != new_sub
        except (OSError, json.JSONDecodeError):
            changed = True
    # Always write the freshest body (so as_of_utc on disk is current),
    # but only report changed=True when substance differs.
    target.write_text(new_body, encoding="utf-8")

    # Idempotent index: drop any prior row for this date, then append fresh.
    rows = [r for r in _read_index(p_root) if r.get("date") != date]
    rows.append({
        "date": date,
        "as_of_utc": payload.get("as_of_utc"),
        "size_kb": round(target.stat().st_size / 1024, 2) if target.exists() else 0.0,
        "risk_gate": ((payload.get("survival_loop") or {}).get("risk_gate") or {}).get("label"),
    })
    _write_index(p_root, rows)

    size_kb = round(target.stat().st_size / 1024, 2) if target.exists() else 0.0
    return {"path": str(target), "changed": bool(changed), "size_kb": size_kb}
