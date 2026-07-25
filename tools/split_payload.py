#!/usr/bin/env python3
"""One-shot: split an already-generated docs/data.json into the v6.0 layout
(slim docs/data.json + docs/charts/{tab}.json) WITHOUT re-fetching from the net.

Shares its splitting logic with the pipeline (fetch_signals.split_chart_payload),
so a manual split here and a fresh pipeline run produce byte-identical layouts.
Idempotent: re-running on an already-split data.json leaves it unchanged.

    PYTHONPATH=. python3 tools/split_payload.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fetch_signals import split_chart_payload, OUTPUT_FILE, OUTPUT_DIR, _json_safe  # noqa: E402

payload = json.load(open(OUTPUT_FILE, encoding="utf-8"))
written = split_chart_payload(payload, OUTPUT_DIR)
payload = _json_safe(payload)
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

# No capacity budget any more — sizes are reported for visibility only. Capacity
# is bounded solely by Cloudflare Pages limits (25 MiB/file, 1 GB/site, 20k
# files); see DATA_CONTRACT.md §10.
size = OUTPUT_FILE.stat().st_size
print(f"data.json: {size:,} B")
total = sum(written.values())
for tab, b in sorted(written.items()):
    print(f"  charts/{tab}.json: {b:,} B")
print(f"charts total: {total:,} B  (Pages limit: 25 MiB/file)")
