"""pipeline.corr_sources — 相関パネル用データ収集 (SPEC_MONEYFLOW.md 相関拡張)。

キーレス・捏造禁止。取得と保存だけを行う。計算(相関係数など)は別モジュールの
責務であり、ここではやらない。

公開関数:
    fetch_yf_closes(tickers, period="2y")   -> {ticker: {date: close}|None}
    fetch_fred_series(series_id)            -> {date: value}|None
    fetch_mof_jgb_yields(tenors=("5","10","30")) -> {"JGB5Y": {...}, ...}|None
    era_to_iso(s)                           -> "YYYY-MM-DD"|None
    persist_raw(name, payload)              -> path|None
    fetch_all()                             -> {label: series|None, ...}

すべての日次終値系列は「date(ISO文字列 YYYY-MM-DD) -> float」の dict、日付昇順。
取得に失敗した系列は None を返し、STDERR に1行警告を出す。値をでっち上げない。
"""

from __future__ import annotations

import csv
import gzip
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

REQUEST_TIMEOUT = 40

# yfinance ticker -> fetch_all() が使う内部ラベル
YF_LABELS = {
    "^N225": "N225",
    "^GSPC": "SPX",
    "^STOXX50E": "STOXX50E",
    "JPY=X": "USDJPY",
    "EURUSD=X": "EURUSD",
    "GC=F": "GOLD",
    "BTC-USD": "BTC",
    "DX-Y.NYB": "DXY",
}

FRED_SERIES = {"US5Y": "DGS5", "US10Y": "DGS10", "US30Y": "DGS30"}

# 公式 MoF JGB CSV (キーレス, Shift-JIS)。履歴 + 当月をマージする。
# 実地検証: 履歴は /data/ サブパス配下 (https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm_all.csv
# は 404)、当月は直下 (fetch_signals.py の MOF_JGB_URL と同じ履歴パスを踏襲)。
MOF_JGB_HIST_URL = "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv"
MOF_JGB_CURRENT_URL = "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"

_MOF_TENOR_COL = {"5": "5年", "10": "10年", "30": "30年"}
_MOF_TENOR_LABEL = {"5": "JGB5Y", "10": "JGB10Y", "30": "JGB30Y"}

_UA = {"User-Agent": "hf-signal-dashboard (correlation panel; market context, keyless)"}


def _warn(msg: str) -> None:
    print(f"  [corr_sources] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# yfinance 日次終値
# ---------------------------------------------------------------------------

def fetch_yf_closes(tickers: List[str], period: str = "2y") -> Dict[str, Optional[Dict[str, float]]]:
    """yfinance で日次終値を取得。ticker毎に失敗を分離(1つ落ちても他は返す)。

    戻り値: {ticker: {date_iso: close}|None}。取得できた日のうち close が
    欠損(NaN)の行はスキップする。
    """
    import yfinance as yf

    out: Dict[str, Optional[Dict[str, float]]] = {}
    for t in tickers:
        try:
            raw = yf.download(t, period=period, auto_adjust=True, progress=False)
            if raw is None or raw.empty:
                _warn(f"yfinance {t}: empty response")
                out[t] = None
                continue
            # 単一ティッカーでも MultiIndex columns で返ってくることがある。
            if hasattr(raw.columns, "nlevels") and raw.columns.nlevels > 1:
                try:
                    close = raw["Close"][t]
                except (KeyError, TypeError):
                    close = raw["Close"].iloc[:, 0]
            else:
                close = raw["Close"]
            series: Dict[str, float] = {}
            for idx, v in close.items():
                if v is None or (isinstance(v, float) and v != v):  # NaN check
                    continue
                date_iso = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
                series[date_iso] = round(float(v), 6)
            if not series:
                _warn(f"yfinance {t}: no valid close values")
                out[t] = None
            else:
                out[t] = dict(sorted(series.items()))
        except Exception as exc:
            _warn(f"yfinance {t} fetch failed ({type(exc).__name__}: {exc})")
            out[t] = None
    return out


# ---------------------------------------------------------------------------
# FRED keyless CSV
# ---------------------------------------------------------------------------

def _parse_fred_csv_text(text: str) -> Dict[str, float]:
    """FRED CSV本文(1行目ヘッダ)をパース。値 "." (欠損マーカー) はスキップ。"""
    rows = list(csv.reader(text.splitlines()))
    series: Dict[str, float] = {}
    if not rows or len(rows) < 2:
        return series
    for r in rows[1:]:
        if len(r) < 2:
            continue
        d, v = r[0].strip(), r[1].strip()
        if not d or v in (".", "", None):
            continue
        try:
            series[d] = float(v)
        except ValueError:
            continue
    return series


def _fetch_fred_csv_via_curl(url: str) -> Optional[str]:
    """requests がTLSハンドシェイクで詰まる環境向けのフォールバック。

    ローカル実行環境の LibreSSL 2.8.3 が FRED の CDN (Akamai) と TLS 相性問題を
    起こし requests.get が延々タイムアウトする一方、同じURLへの curl は数百ms
    で成功することを実地確認済み(GitHub Actions の Ubuntu/OpenSSL 3.x では
    requests が第一手段のまま問題なく動く見込み)。
    追加の実地観測: このフォールバック限定で、curl にカスタム User-Agent
    (空文字 "" や "User-Agent:" ヘッダ除去含む)を明示的に指定すると Akamai
    側が HTTP/2 ストリームをリセットする(exit 92)。curl のデフォルト UA
    ("curl/8.x") をそのまま送る(-A オプションを付けない)場合のみ安定して
    通ることを実地確認済みなので、意図的に UA オプションを渡さない。
    subprocess で curl を呼ぶだけで鍵は一切使わない(キーレス原則は不変)。
    """
    try:
        proc = subprocess.run(
            ["curl", "-s", "-m", str(REQUEST_TIMEOUT), "--fail", url],
            capture_output=True, timeout=REQUEST_TIMEOUT + 5,
        )
        if proc.returncode != 0 or not proc.stdout:
            return None
        return proc.stdout.decode("utf-8", errors="replace")
    except Exception:
        return None


def fetch_fred_series(series_id: str) -> Optional[Dict[str, float]]:
    """FRED keyless CSV (fredgraph.csv) から全期間の日次系列を取得。

    第一手段は requests。requests が例外を投げた場合のみ curl サブプロセスに
    フォールバックする(TLSハンドシェイク相性問題の回避、上記コメント参照)。
    値 "." (欠損マーカー) はスキップ。両方失敗したら None を返し STDERR に警告。
    """
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    text = None
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=_UA)
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:
        _warn(f"FRED {series_id} requests failed ({type(exc).__name__}: {exc}); trying curl fallback")
        text = _fetch_fred_csv_via_curl(url)

    if text is None:
        _warn(f"FRED {series_id} fetch failed (requests and curl both unavailable)")
        return None

    series = _parse_fred_csv_text(text)
    if not series:
        _warn(f"FRED {series_id}: no valid rows")
        return None
    return dict(sorted(series.items()))


# ---------------------------------------------------------------------------
# 和暦 -> 西暦 ISO 変換 (公開・独立関数)
# ---------------------------------------------------------------------------

def era_to_iso(s: str) -> Optional[str]:
    """和暦日付文字列 ('R8.7.1' / 'H31.4.30' / 'S49.9.24') を ISO 'YYYY-MM-DD' に
    変換する。S=昭和(base 1925) / H=平成(base 1988) / R=令和(base 2018)。
    不正入力(元号不明・整数変換不能・月日範囲外)は None。

    fetch_signals.py の _jp_era_to_iso (line 910付近) を参考にした独立実装。
    """
    s = (s or "").strip()
    if len(s) < 2 or s[0] not in "SHR":
        return None
    try:
        parts = s[1:].split(".")
        if len(parts) != 3:
            return None
        yy, mm, dd = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError):
        return None
    base = {"S": 1925, "H": 1988, "R": 2018}[s[0]]
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return None
    if yy < 1:
        return None
    return f"{base + yy:04d}-{mm:02d}-{dd:02d}"


# ---------------------------------------------------------------------------
# MoF JGB 円金利 (キーレス, Shift-JIS, 和暦, 履歴+当月マージ)
# ---------------------------------------------------------------------------

def _mof_http_get_bytes(url: str) -> Optional[bytes]:
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=_UA)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:
        _warn(f"MoF JGB fetch failed for {url} ({type(exc).__name__}: {exc})")
        return None


def _parse_mof_jgb_csv(raw_bytes: bytes, tenors) -> Dict[str, Dict[str, float]]:
    """MoF JGB CSV (Shift-JIS, ヘッダ2行, 和暦日付, 欠損='-', 末尾注記行) を
    パースする。行毎に try し、パース不能な行はスキップして続行する(堅牢優先)。

    戻り値: {"JGB5Y": {date_iso: yield}, "JGB10Y": {...}, "JGB30Y": {...}}
    (要求テナーのみ、該当列が存在するもの)。
    """
    try:
        text = raw_bytes.decode("shift_jis", errors="replace")
    except Exception as exc:
        _warn(f"MoF JGB decode failed ({type(exc).__name__}: {exc})")
        return {}

    rows = list(csv.reader(text.splitlines()))
    # ヘッダは「基準日」を含む行を探す(先頭行がタイトル等でズレることがあるため)。
    hdr_idx = next((i for i, r in enumerate(rows) if r and "基準日" in r[0]), None)
    if hdr_idx is None:
        _warn("MoF JGB: header row ('基準日') not found")
        return {}
    hdr = rows[hdr_idx]

    col_for_tenor: Dict[str, int] = {}
    for tenor in tenors:
        col_label = _MOF_TENOR_COL.get(tenor)
        if col_label is None:
            continue
        try:
            col_for_tenor[tenor] = hdr.index(col_label)
        except ValueError:
            _warn(f"MoF JGB: column '{col_label}' not found in header")
            continue

    if not col_for_tenor:
        return {}

    series: Dict[str, Dict[str, float]] = {_MOF_TENOR_LABEL[t]: {} for t in col_for_tenor}

    for r in rows[hdr_idx + 1:]:
        if not r or not r[0].strip():
            continue
        try:
            iso = era_to_iso(r[0])
            if not iso:
                continue
            for tenor, col in col_for_tenor.items():
                if col >= len(r):
                    continue
                raw_v = r[col].strip()
                if raw_v in ("-", "", "*"):
                    continue
                try:
                    v = float(raw_v)
                except ValueError:
                    continue
                # 妥当性ゲート: -2 <= y < 25 (2016-2024年の実在マイナス金利を許容)
                if -2 <= v < 25:
                    series[_MOF_TENOR_LABEL[tenor]][iso] = round(v, 4)
        except Exception:
            # 個別行の異常はスキップして続行(注記行・書式崩れ対策)。
            continue

    return {k: v for k, v in series.items() if v}


def fetch_mof_jgb_yields(tenors=("5", "10", "30")) -> Optional[Dict[str, Dict[str, float]]]:
    """日本国債金利 (5Y/10Y/30Y) を MoF 公式 CSV から取得。

    履歴 CSV (jgbcm_all.csv) + 当月 CSV (jgbcm.csv) をマージする。同一日付は
    当月側の値で上書き(より新しい取得元を優先)。全滅時は None。
    """
    hist_bytes = _mof_http_get_bytes(MOF_JGB_HIST_URL)
    hist = _parse_mof_jgb_csv(hist_bytes, tenors) if hist_bytes is not None else {}

    cur_bytes = _mof_http_get_bytes(MOF_JGB_CURRENT_URL)
    cur = _parse_mof_jgb_csv(cur_bytes, tenors) if cur_bytes is not None else {}

    if not hist and not cur:
        _warn("MoF JGB: both historical and current CSV failed/empty")
        return None

    merged: Dict[str, Dict[str, float]] = {}
    labels = {_MOF_TENOR_LABEL[t] for t in tenors if t in _MOF_TENOR_LABEL}
    for label in labels:
        base = dict(hist.get(label, {}))
        base.update(cur.get(label, {}))  # 当月側で上書き
        if base:
            merged[label] = dict(sorted(base.items()))

    if not merged:
        _warn("MoF JGB: no tenor produced usable data")
        return None
    return merged


# ---------------------------------------------------------------------------
# raw ペイロード保存 (append-only, ~/hf-data-store/)
# ---------------------------------------------------------------------------

def persist_raw(name: str, payload) -> Optional[str]:
    """生データを ~/hf-data-store/raw/YYYY-MM-DD/corr_<name>.json.gz に保存。

    append-only: 既存ファイルがあれば上書きせずスキップ(None ではなく既存パス
    を返す)。ディレクトリ作成不可・書込不可(CI環境でストア無し等)なら
    None を返して静かに続行する。
    """
    try:
        today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
        root = Path.home() / "hf-data-store" / "raw" / today
        root.mkdir(parents=True, exist_ok=True)
        out_path = root / f"corr_{name}.json.gz"
        if out_path.exists():
            return str(out_path)  # append-only: 既存を上書きしない
        with gzip.open(out_path, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        return str(out_path)
    except Exception as exc:
        _warn(f"persist_raw({name}) skipped, store unavailable ({type(exc).__name__}: {exc})")
        return None


# ---------------------------------------------------------------------------
# 全系列一括取得
# ---------------------------------------------------------------------------

def fetch_all() -> Dict[str, Optional[Dict[str, float]]]:
    """相関パネル向け全14系列を取得し、ラベル付きで返す。失敗系列は None。

    各系列取得後に persist_raw を呼んでストアへ生データを退避する
    (ストア不在の環境では静かにスキップされる)。
    """
    out: Dict[str, Optional[Dict[str, float]]] = {}

    # --- yfinance 8ティッカー ---
    yf_tickers = list(YF_LABELS.keys())
    yf_results = fetch_yf_closes(yf_tickers)
    for ticker, label in YF_LABELS.items():
        series = yf_results.get(ticker)
        out[label] = series
        persist_raw(label, series)

    # --- FRED 3系列 (US5Y/US10Y/US30Y) ---
    for label, series_id in FRED_SERIES.items():
        series = fetch_fred_series(series_id)
        out[label] = series
        persist_raw(label, series)

    # --- MoF JGB 3テナー (JGB5Y/JGB10Y/JGB30Y) ---
    jgb = fetch_mof_jgb_yields()
    for label in ("JGB5Y", "JGB10Y", "JGB30Y"):
        series = (jgb or {}).get(label)
        out[label] = series
        persist_raw(label, series)

    return out


if __name__ == "__main__":
    result = fetch_all()
    summary = {k: (len(v) if v else None) for k, v in result.items()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
