"""collector.log — data/collect_log.jsonl 追記 (SPEC_AUTOCOLLECT §3).

1 実行 = 1 行 jsonl。append-only。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict


REQUIRED = {
    "run_at_utc", "run_at_jst_date", "workflow", "duration_sec",
    "sources", "history_written", "history_size_kb", "git_changed", "errors",
}


def write_entry(entry: Dict[str, Any], root) -> str:
    """Append one collect log entry (jsonl) under `root/collect_log.jsonl`.

    Missing keys are filled with safe defaults so callers don't crash; tests in
    test_collector_schema verify the contract is honored.
    """
    missing = REQUIRED - set(entry.keys())
    for k in missing:
        entry[k] = (
            False if k == "git_changed" else
            [] if k in ("errors",) else
            {} if k in ("sources",) else
            ""
        )
    p_root = pathlib.Path(root)
    p_root.mkdir(parents=True, exist_ok=True)
    f = p_root / "collect_log.jsonl"
    line = json.dumps(entry, ensure_ascii=False)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return str(f)
