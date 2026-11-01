#!/usr/bin/env python3
"""tools/issue_once.py — GitHub Issue を「タイトル固定で1件だけ」起票する（既存なら comment）。

deploy.yml の "Open issue on failure" と同じやり方（gh issue list → create / comment）を
Python から使えるようにしたもの。contract_check / update_universe / 各 workflow が共用する。

使い方:
    GH_TOKEN=... python3 tools/issue_once.py --title "固定タイトル" --body "本文" [--label monitor]
    GH_TOKEN=... python3 tools/issue_once.py --title "固定タイトル" --body-file body.md
テスト: open_issue_once(..., runner=fake) で gh を呼ばずに確かめられる。
"""
from __future__ import annotations

import argparse
import subprocess
import sys


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def open_issue_once(title, body, label="monitor", runner=None):
    """同じタイトルの open Issue があれば comment、無ければ create。戻り値 ("created"|"commented"|"failed", number|None)。"""
    run = runner or _run
    r = run(["gh", "issue", "list", "--state", "open", "--search", f"{title} in:title",
             "--json", "number,title", "-q", f'[.[] | select(.title == "{title}")][0].number'])
    num = (getattr(r, "stdout", "") or "").strip()
    if getattr(r, "returncode", 1) == 0 and num and num != "null":
        c = run(["gh", "issue", "comment", num, "--body", body])
        return ("commented" if c.returncode == 0 else "failed"), num
    cmd = ["gh", "issue", "create", "--title", title, "--body", body]
    c = run(cmd + (["--label", label] if label else []))
    if c.returncode != 0 and label:
        c = run(cmd)                       # ラベルが無いリポジトリでも起票できるように
    return ("created" if c.returncode == 0 else "failed"), None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--body")
    g.add_argument("--body-file")
    ap.add_argument("--label", default="monitor")
    a = ap.parse_args(argv)
    body = a.body if a.body is not None else open(a.body_file, encoding="utf-8").read()
    status, num = open_issue_once(a.title, body, a.label)
    print(f"issue_once: {status} {num or ''}".strip())
    return 0 if status != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
