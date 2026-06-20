"""backtest.local_loader — data/local/ の OHLC を walk-forward に流せる形に整形.

SPEC_BACKTEST_LIVE.md §1. DuckDB 優先・jsonl fallback. 重複除去・昇順整列・
非数値 close 排除. 薄い銘柄は捏造せず excluded に逃がす.

Phase 2 (学習) は本ファイルに持ち込まない. テスト test_no_learning_code が
backtest/ 配下の禁止語混入を検知する.
"""

from __future__ import annotations

import glob
import json
import math
import os
import pathlib
from typing import Any, Dict, List, Optional

# Optional duckdb
try:
    import duckdb as _DUCKDB    # type: ignore
except Exception:
    _DUCKDB = None   # type: ignore


ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCAL_DIR = ROOT / "data" / "local"
DUCKDB_PATH = LOCAL_DIR / "history.duckdb"


def _safe_float(x) -> Optional[float]:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _normalize_bars(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """重複 ts は最新で正規化、非数値 close を弾き、ts 昇順にソート."""
    by_ts: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        ts = r.get("ts")
        if not ts:
            continue
        close = _safe_float(r.get("close"))
        if close is None:
            continue
        by_ts[ts] = {
            "ts": ts,
            "open":  _safe_float(r.get("open"))  or close,
            "high":  _safe_float(r.get("high"))  or close,
            "low":   _safe_float(r.get("low"))   or close,
            "close": close,
            "volume": _safe_float(r.get("volume")) or 0.0,
        }
    return sorted(by_ts.values(), key=lambda r: r["ts"])


def _scan_jsonl(interval: str) -> Dict[str, List[Dict[str, Any]]]:
    """Read every history_*.jsonl in LOCAL_DIR and group by `symbol` (interval filter)."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    pattern = str(LOCAL_DIR / "history_*.jsonl")
    for p in sorted(glob.glob(pattern)):
        try:
            text = pathlib.Path(p).read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if interval and row.get("interval") and row.get("interval") != interval:
                continue
            sym = row.get("symbol")
            if not sym:
                continue
            out.setdefault(sym, []).append(row)
    return out


def _scan_duckdb(interval: str) -> Dict[str, List[Dict[str, Any]]]:
    if _DUCKDB is None or not DUCKDB_PATH.exists():
        return {}
    try:
        con = _DUCKDB.connect(str(DUCKDB_PATH))
    except Exception:
        return {}
    try:
        rows = con.execute(
            "SELECT symbol, ts, open, high, low, close, volume "
            "FROM bars WHERE interval = ? ORDER BY symbol, ts",
            [interval]
        ).fetchall()
    except Exception:
        return {}
    finally:
        con.close()
    out: Dict[str, List[Dict[str, Any]]] = {}
    for sym, ts, o, h, l, c, v in rows:
        out.setdefault(sym, []).append({
            "ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": v,
        })
    return out


def load_all(interval: str = "1d",
             min_bars: int = 400,
             source: str = "auto") -> Dict[str, Any]:
    """Return dict { interval, source_used, symbols, excluded, totals }."""
    src = (source or "auto").lower()
    raw: Dict[str, List[Dict[str, Any]]] = {}
    used = "jsonl"
    if src in ("auto", "duckdb"):
        raw = _scan_duckdb(interval) or {}
        if raw:
            used = "duckdb"
    if not raw:
        raw = _scan_jsonl(interval)
        used = "jsonl"

    symbols: Dict[str, Any] = {}
    excluded: Dict[str, Any] = {}
    for sym, rows in raw.items():
        bars = _normalize_bars(rows)
        n = len(bars)
        if n < int(min_bars):
            excluded[sym] = {
                "reason": "insufficient_data",
                "n": n,
                "min_required": int(min_bars),
            }
            continue
        symbols[sym] = {
            "bars": bars,
            "n": n,
            "first_ts": bars[0]["ts"] if bars else None,
            "last_ts": bars[-1]["ts"] if bars else None,
        }
    return {
        "interval": interval,
        "source_used": used,
        "symbols": symbols,
        "excluded": excluded,
        "totals": {
            "n_symbols": len(symbols),
            "n_excluded": len(excluded),
            "total_bars": sum(s["n"] for s in symbols.values()),
        },
    }
