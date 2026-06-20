#!/usr/bin/env python3
"""scripts/notify_receiver.py — Mac mini 常駐 receiver (launchd エントリ).

Usage:
    python3 scripts/notify_receiver.py          # loop forever (60s)
    python3 scripts/notify_receiver.py --once   # one cycle, then exit (debugging)
    python3 scripts/notify_receiver.py --interval=30

launchd plist: scripts/com.hf.notify.plist
"""

from __future__ import annotations

import os
import pathlib
import sys


HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv):
    from notify import receiver

    if "--once" in argv:
        import json
        print(json.dumps(receiver.run_once(), ensure_ascii=False, indent=2))
        return 0

    interval = 60
    for a in argv:
        if a.startswith("--interval="):
            try:
                interval = max(5, int(a.split("=", 1)[1]))
            except ValueError:
                interval = 60
    receiver.loop(interval_sec=interval)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
