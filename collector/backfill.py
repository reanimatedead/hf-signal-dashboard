"""collector.backfill — 最大履歴ダウンロード CLI (SPEC_BACKTEST §5).

Usage:
    python3 -m collector.backfill                       # defaults: 全主要シンボル, 1d, 最長
    python3 -m collector.backfill --symbols=^N225,USDJPY=X
    python3 -m collector.backfill --period=10y --interval=1d
    python3 -m collector.backfill --intervals=1d,1wk
    python3 -m collector.backfill --dry-run

Notes:
    * keyless (yfinance のみ).
    * DuckDB が import できれば data/local/history.duckdb に書く.
      失敗時は data/local/history_<sym>.jsonl の jsonl fallback.
    * 冪等: (symbol, interval, ts) を一意キーに重複行を弾く.
    * 部分失敗で全体落とさない. 失敗は errors リストに積み collect_log にも行追加.
    * 空き容量 < 20GB で WARN を stderr に.
    * 進捗を data/local/backfill_progress.json に書く.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import sys
import time
from typing import Any, Dict, List, Optional


# Optional DuckDB
try:
    import duckdb as _DUCKDB    # type: ignore
except Exception:
    _DUCKDB = None  # type: ignore


ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCAL_DIR = ROOT / "data" / "local"
PROGRESS_PATH = LOCAL_DIR / "backfill_progress.json"
DUCKDB_PATH = LOCAL_DIR / "history.duckdb"
PUBLIC_PROGRESS_PATH = ROOT / "docs" / "data" / "backfill_progress_public.json"
LOW_DISK_WARN_GB = 20.0

DEFAULT_SYMBOLS = [
    "^N225", "^DJI", "^NDX", "^GSPC",
    "USDJPY=X", "EURUSD=X", "EURJPY=X", "GBPUSD=X", "AUDUSD=X",
    "XAUUSD=X", "XAGUSD=X",
    "^TNX", "^TYX", "^VIX", "^MOVE",
    "BTC-USD", "ETH-USD",
]
DEFAULT_INTERVALS = ["1d"]
DEFAULT_PERIOD = "max"


# ── helpers ────────────────────────────────────────────
def _sanitize(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", symbol or "x")


def _free_gb(path: pathlib.Path) -> float:
    try:
        usage = shutil.disk_usage(str(path.parent if path.is_file() else path))
        return usage.free / (1024 ** 3)
    except Exception:
        return float("nan")


def _warn_low_disk():
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    free = _free_gb(LOCAL_DIR)
    if free != free:    # NaN
        return
    if free < LOW_DISK_WARN_GB:
        sys.stderr.write(
            f"[backfill] WARN free disk {free:.1f} GB < {LOW_DISK_WARN_GB} GB\n"
        )


def _fetch_history_one(symbol: str, period: str, interval: str) -> List[Dict[str, Any]]:
    """yfinance 経由で 1 銘柄分の OHLCV を取得.

    テストでは monkeypatch される. 失敗は呼び出し元で握りつぶす.
    """
    try:
        import yfinance as yf   # type: ignore
    except Exception as exc:
        raise RuntimeError(f"yfinance unavailable: {exc}")
    df = yf.download(symbol, period=period, interval=interval,
                     progress=False, auto_adjust=False, threads=False)
    if df is None or getattr(df, "empty", False):
        return []
    out = []
    for ts, row in df.iterrows():
        try:
            ts_iso = ts.isoformat()
        except Exception:
            ts_iso = str(ts)
        out.append({
            "ts": ts_iso,
            "open": float(row.get("Open")) if row.get("Open") is not None else None,
            "high": float(row.get("High")) if row.get("High") is not None else None,
            "low":  float(row.get("Low"))  if row.get("Low")  is not None else None,
            "close": float(row.get("Close")) if row.get("Close") is not None else None,
            "volume": float(row.get("Volume")) if row.get("Volume") is not None else None,
        })
    return out


# ── jsonl fallback I/O ─────────────────────────────────
def _jsonl_path(symbol: str, interval: str) -> pathlib.Path:
    return LOCAL_DIR / f"history_{_sanitize(symbol)}_{interval}.jsonl"


def _read_jsonl(path: pathlib.Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _write_jsonl_rows(symbol: str, interval: str,
                      rows: List[Dict[str, Any]]) -> Dict[str, int]:
    path = _jsonl_path(symbol, interval)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_jsonl(path)
    seen_ts = {r.get("ts") for r in existing}
    new_rows = [r for r in rows if r.get("ts") and r.get("ts") not in seen_ts]
    if new_rows:
        with path.open("a", encoding="utf-8") as f:
            for r in new_rows:
                r2 = dict(r); r2["symbol"] = symbol; r2["interval"] = interval
                f.write(json.dumps(r2, ensure_ascii=False) + "\n")
    return {"written": len(new_rows), "duplicates_skipped": len(rows) - len(new_rows),
            "total_in_store": len(existing) + len(new_rows)}


# ── DuckDB I/O (optional) ─────────────────────────────
def _ensure_duckdb_schema(con) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS bars (
              symbol VARCHAR,
              interval VARCHAR,
              ts VARCHAR,
              open DOUBLE,
              high DOUBLE,
              low  DOUBLE,
              close DOUBLE,
              volume DOUBLE,
              PRIMARY KEY (symbol, interval, ts)
           );""")


def _write_duckdb_rows(symbol: str, interval: str,
                       rows: List[Dict[str, Any]]) -> Dict[str, int]:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    con = _DUCKDB.connect(str(DUCKDB_PATH))
    try:
        _ensure_duckdb_schema(con)
        # Idempotent insert
        written = 0
        duplicates = 0
        for r in rows:
            try:
                con.execute(
                    "INSERT INTO bars(symbol,interval,ts,open,high,low,close,volume) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    [symbol, interval, r.get("ts"),
                     r.get("open"), r.get("high"), r.get("low"),
                     r.get("close"), r.get("volume")])
                written += 1
            except Exception:
                duplicates += 1
        total = con.execute(
            "SELECT COUNT(*) FROM bars WHERE symbol=? AND interval=?",
            [symbol, interval]).fetchone()[0]
        return {"written": written, "duplicates_skipped": duplicates,
                "total_in_store": int(total)}
    finally:
        con.close()


def _persist(symbol: str, interval: str, rows: List[Dict[str, Any]]) -> Dict[str, int]:
    if _DUCKDB is not None:
        try:
            return _write_duckdb_rows(symbol, interval, rows)
        except Exception as exc:
            sys.stderr.write(
                f"[backfill] DuckDB write failed for {symbol}: "
                f"{type(exc).__name__}; falling back to jsonl\n")
    return _write_jsonl_rows(symbol, interval, rows)


def read_all(symbol: str, interval: str) -> List[Dict[str, Any]]:
    """Read every stored bar for a (symbol, interval) — used by tests."""
    if _DUCKDB is not None and DUCKDB_PATH.exists():
        try:
            con = _DUCKDB.connect(str(DUCKDB_PATH))
            try:
                rows = con.execute(
                    "SELECT ts,open,high,low,close,volume FROM bars "
                    "WHERE symbol=? AND interval=? ORDER BY ts",
                    [symbol, interval]).fetchall()
                return [{"ts": r[0], "open": r[1], "high": r[2], "low": r[3],
                          "close": r[4], "volume": r[5]} for r in rows]
            finally:
                con.close()
        except Exception:
            pass
    return _read_jsonl(_jsonl_path(symbol, interval))


# ── progress JSON ─────────────────────────────────────
def _write_progress(progress: Dict[str, Any]) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(json.dumps(progress, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    # Public abridged copy (no symbol names — only counts).
    try:
        PUBLIC_PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
        public = {
            "as_of_utc": progress.get("as_of_utc"),
            "symbol_count": len(progress.get("symbols") or {}),
            "total_bars": sum((v.get("bars", 0) or 0)
                              for v in (progress.get("symbols") or {}).values()),
            "coverage": progress.get("coverage", {}),
            "free_gb": progress.get("free_gb"),
            "store_backend": progress.get("store_backend"),
            "note": "Macro environment visualization / not investment advice.",
        }
        PUBLIC_PROGRESS_PATH.write_text(json.dumps(public, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    except OSError:
        pass


# ── runner ─────────────────────────────────────────────
def run(symbols: Optional[List[str]] = None,
        period: str = DEFAULT_PERIOD,
        intervals: Optional[List[str]] = None,
        dry_run: bool = False) -> Dict[str, Any]:
    symbols = list(symbols) if symbols else list(DEFAULT_SYMBOLS)
    intervals = list(intervals) if intervals else list(DEFAULT_INTERVALS)
    _warn_low_disk()

    plan = [{"symbol": s, "period": period, "interval": i}
            for s in symbols for i in intervals]
    if dry_run:
        return {"ok": True, "dry_run": True, "plan": plan}

    errors: List[str] = []
    summary: Dict[str, Any] = {}
    written_total = 0
    duplicates_total = 0
    coverage_first = None
    coverage_last = None

    for s in symbols:
        s_summary = summary.setdefault(s, {"bars": 0, "first_ts": None,
                                            "last_ts": None, "intervals": {}})
        for itv in intervals:
            try:
                rows = _fetch_history_one(s, period, itv)
            except Exception as exc:
                errors.append(f"{s}/{itv}: {type(exc).__name__}: {exc}")
                s_summary["intervals"][itv] = {"status": "failed",
                                                "error": str(exc)[:120]}
                continue
            res = _persist(s, itv, rows)
            written_total += res.get("written", 0)
            duplicates_total += res.get("duplicates_skipped", 0)
            s_summary["intervals"][itv] = {
                "status": "ok",
                "written": res["written"],
                "duplicates_skipped": res["duplicates_skipped"],
                "total_in_store": res["total_in_store"],
            }
            if rows:
                first = rows[0].get("ts")
                last = rows[-1].get("ts")
                if first and (s_summary["first_ts"] is None or first < s_summary["first_ts"]):
                    s_summary["first_ts"] = first
                if last and (s_summary["last_ts"] is None or last > s_summary["last_ts"]):
                    s_summary["last_ts"] = last
                if first and (coverage_first is None or first < coverage_first):
                    coverage_first = first
                if last and (coverage_last is None or last > coverage_last):
                    coverage_last = last
            s_summary["bars"] += res["total_in_store"]

    import datetime
    out = {
        "ok": True,
        "as_of_utc": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        "store_backend": "duckdb" if _DUCKDB is not None else "jsonl",
        "free_gb": round(_free_gb(LOCAL_DIR), 2),
        "symbols": summary,
        "coverage": {"first_ts": coverage_first, "last_ts": coverage_last},
        "written_total": written_total,
        "duplicates_skipped": duplicates_total,
        "errors": errors,
    }
    _write_progress(out)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="collector.backfill",
                                description="Backfill maximum-history bars into local store.")
    p.add_argument("--symbols", help="comma-separated symbol list", default=None)
    p.add_argument("--period", default=DEFAULT_PERIOD,
                   help='yfinance period (max|10y|5y|2y|1y|6mo|...)')
    p.add_argument("--interval", default=None,
                   help="single interval shortcut (1d|1wk|1h|4h ...)")
    p.add_argument("--intervals", default=None,
                   help="comma-separated intervals (overrides --interval)")
    p.add_argument("--dry-run", action="store_true", default=False)
    ns = p.parse_args(argv)

    symbols = ns.symbols.split(",") if ns.symbols else None
    intervals = None
    if ns.intervals:
        intervals = ns.intervals.split(",")
    elif ns.interval:
        intervals = [ns.interval]
    res = run(symbols=symbols, period=ns.period,
              intervals=intervals, dry_run=ns.dry_run)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
