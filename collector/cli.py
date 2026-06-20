"""collector.cli — `python -m collector.cli` の入口 (SPEC_AUTOCOLLECT §4).

工程:
    1. fetch_signals.main() を呼び docs/data.json を更新する (失敗は記録して継続)
    2. docs/data.json を読み、collector.snapshot.extract → write_snapshot で
       data/history/YYYY-MM-DD.json を冪等更新
    3. collector.log.write_entry で data/collect_log.jsonl に追記

設計上、git commit / push はワークフロー (collect.yml) に任せる。
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import sys
import time
import traceback
from typing import Any, Dict, List, Optional

from . import log as cl
from . import runtime as rt
from . import snapshot as sn


ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DATA_JSON = DOCS / "data.json"
HISTORY_DIR = ROOT / "data" / "history"
LOG_DIR = ROOT / "data"
JST = datetime.timezone(datetime.timedelta(hours=9))


def _invoke_fetch() -> None:
    """fetch_signals.main() を呼ぶ薄いラッパ。テストから monkeypatch される。"""
    sys.path.insert(0, str(ROOT))
    import fetch_signals as fs   # type: ignore
    fs.main()


def _invoke_snapshot(data: Dict[str, Any], root: pathlib.Path) -> Dict[str, Any]:
    payload = sn.extract(data)
    return sn.write_snapshot(payload, root=root)


def _now_utc():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def _today_jst_iso() -> str:
    return datetime.datetime.now(JST).date().isoformat()


def _empty_sources() -> Dict[str, Dict[str, int]]:
    return {s: {"ok": 0, "failed": 0, "ratelimited": 0}
            for s in ("yfinance", "fred", "fiscaldata", "cftc_cot",
                      "coingecko", "mof_jgb")}


def _classify_source(err: Exception) -> Optional[str]:
    msg = str(err).lower()
    if "yfinance" in msg or "yf" in msg:        return "yfinance"
    if "fred" in msg:                            return "fred"
    if "fiscaldata" in msg or "treasury" in msg: return "fiscaldata"
    if "cftc" in msg:                            return "cftc_cot"
    if "coingecko" in msg or "btc" in msg:       return "coingecko"
    if "mof" in msg or "jgb" in msg:             return "mof_jgb"
    return None


def run(*, history_root: Optional[pathlib.Path] = None,
        log_root: Optional[pathlib.Path] = None,
        workflow: str = "local") -> Dict[str, Any]:
    """1 サイクル実行。例外を中で捕えて collect_log に積み、必ず辞書を返す."""
    history_root = pathlib.Path(history_root or HISTORY_DIR)
    log_root = pathlib.Path(log_root or LOG_DIR)
    errors: List[str] = []
    sources = _empty_sources()
    history_path = ""
    history_size_kb = 0.0
    git_changed = False
    t0 = time.time()

    # 1. fetch_signals — 1 ソース失敗が出ても落とさない。
    try:
        _invoke_fetch()
    except Exception as exc:
        errors.append(f"fetch_signals: {type(exc).__name__}: {exc}")
        klass = _classify_source(exc)
        if klass:
            sources[klass]["failed"] += 1

    # 2. snapshot
    try:
        if DATA_JSON.exists():
            data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
            try:
                res = _invoke_snapshot(data, history_root)
            except TypeError:
                # backward compat with positional-args mocks in tests
                res = _invoke_snapshot(data, root=history_root)
            history_path = res.get("path", "")
            history_size_kb = float(res.get("size_kb", 0.0))
            git_changed = bool(res.get("changed", False))
        else:
            errors.append("snapshot: docs/data.json missing after fetch")
    except Exception as exc:
        errors.append(f"snapshot: {type(exc).__name__}: {exc}")

    # 3. collect_log
    try:
        cl.write_entry({
            "run_at_utc": _now_utc().isoformat(),
            "run_at_jst_date": _today_jst_iso(),
            "workflow": workflow,
            "duration_sec": round(time.time() - t0, 2),
            "sources": sources,
            "history_written": history_path,
            "history_size_kb": history_size_kb,
            "git_changed": git_changed,
            "errors": errors[:5],   # cap to 5 per SPEC §3
        }, root=log_root)
    except Exception as exc:
        # Last-ditch: log to stderr but do not raise
        sys.stderr.write(f"[collector] write_entry failed: {exc}\n")
        sys.stderr.write(traceback.format_exc())

    return {
        "ok": True,
        "errors": errors,
        "history_path": history_path,
        "history_size_kb": history_size_kb,
        "git_changed": git_changed,
        "sources": sources,
        "duration_sec": round(time.time() - t0, 2),
    }


def main(argv: Optional[List[str]] = None) -> int:
    workflow = "local"
    if argv:
        for a in argv:
            if a.startswith("--workflow="):
                workflow = a.split("=", 1)[1]
    res = run(workflow=workflow)
    # Print a tight summary so CI logs stay readable.
    print(json.dumps({
        "ok": res["ok"],
        "history_path": res["history_path"],
        "history_size_kb": res["history_size_kb"],
        "git_changed": res["git_changed"],
        "errors": res["errors"][:3],
        "duration_sec": res["duration_sec"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
