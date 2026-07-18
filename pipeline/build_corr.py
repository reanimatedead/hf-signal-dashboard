#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_corr.py — 相関パネル ビルダ（feat/corr-panel, SPEC_MONEYFLOW.md 相関拡張）

責務: pipeline/corr_sources.py の fetch_all() が返す14系列を計算し、
docs/data.json の correlations（新規トップレベルキー）と
money_flow.<region>.sink_metrics（既存キーへの追記）を
「read-modify-write マージ」で書き込む。取得はしない（A1責務）・描画もしない（A4責務）。

計算ルール（必須・水準相関の禁止）:
  - 水準（価格・利回りの生値）どうしの相関は見せかけの相関（spurious correlation）
    になりやすいため禁止。必ず「日次変化」に変換してから相関を取る。
  - 株価指数・為替: 対数リターン ln(P_t / P_{t-1})。
  - 利回り系列（US5Y/10Y/30Y, JGB5Y/10Y/30Y）: 変化幅bp = (y_t - y_{t-1}) * 100
    （yfinance終値ではなくFRED/MoFの利回り%なので対数リターンではなく差分bp）。
  - 派生系列 US-JP10Yspread = DGS10水準 - JGB10Y水準 を「水準」として先に構築し、
    その日次変化bp（スプレッド自体の日次変化）を相関計算に使う
    （ドル円の最重要ドライバーの一つ）。
  - inner join: 変化系列どうしを、両方に値がある日のみで結合する。前方補完
    （ffill）は一切行わない（休場日のズレをごまかさない）。
  - ローリング窓: long=60営業日, short=20営業日。相関行列は直近window分の
    データ（10系列共通日で inner join した末尾）で計算する。
  - 決定論: 相関値は小数4桁に丸める。同じ入力からは同じ出力（wall-clock
    タイムスタンプを埋め込まない。correlations.as_of は「結合後の最新観測日」）。
    lag_days（実行日と最新観測日の暦日差）だけは実行日依存で変わってよい。

sink_metrics（money_flow.<region>）:
  - 「シェア×総資産」のような額の捏造をしない。各シンク代表系列の週次変化%
    （直近終値 / 「最新日-7暦日以前で最も近い日」の終値 - 1）* 100 のみを出す。
  - フロント側はこれを「週次変化」として表示する想定（流入額と偽らない）。

data-hygiene（未確定バー除外）:
  - yfinance 由来の全系列から「今日(UTC) または 今日(JST)」日付の観測を計算前に
    除外する（correlations と sink_metrics の両方の入力に適用）。
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corr_sources import fetch_all, YF_LABELS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_JSON = ROOT / "docs" / "data.json"

WINDOW_LONG = 60
WINDOW_SHORT = 20
KEY_PAIR_LOOKBACK = 250  # 直近250営業日分のローリング60日相関系列

MATRIX_LABELS = [
    "N225", "SPX", "US5Y", "US10Y", "US30Y",
    "JGB5Y", "JGB10Y", "JGB30Y", "USDJPY", "US-JP10Yspread",
]

# 対数リターンで変化系列化する系列（株価指数・為替）
LOG_RETURN_LABELS = {"N225", "SPX", "USDJPY"}
# bp差分で変化系列化する系列（利回り、% 単位）
BP_CHANGE_LABELS = {"US5Y", "US10Y", "US30Y", "JGB5Y", "JGB10Y", "JGB30Y"}

KEY_PAIRS = [
    ("N225", "USDJPY"),
    ("SPX", "US10Y"),
    ("USDJPY", "US-JP10Yspread"),
]

SOURCES = ["yfinance", "FRED:fredgraph", "MOF:jgbcm"]
METHOD_NOTE = (
    "log-returns (equity/FX) and bp-changes (yields), inner join (no forward fill), "
    "Pearson rolling 60/20 business days"
)
CORR_NOTE = "For data visualization purposes only. Not investment advice."

# --- sink_metrics 定義: 地域 -> シンク種別 -> (label, ticker) ---
SINK_SPEC = {
    "us": {"stocks": ("^GSPC", "SPX"), "gold": ("GC=F", "GOLD"), "crypto": ("BTC-USD", "BTC"), "cash": ("DX-Y.NYB", "DXY")},
    "eu": {"stocks": ("^STOXX50E", "STOXX50E"), "gold": ("GC=F", "GOLD"), "crypto": ("BTC-USD", "BTC"), "cash": ("EURUSD=X", "EURUSD")},
    "jp": {"stocks": ("^N225", "N225"), "gold": ("GC=F", "GOLD"), "crypto": ("BTC-USD", "BTC"), "cash": ("JPY=X", "USDJPY")},
}
SINK_METRICS_NOTE = "Weekly % change of representative series. Particle arrival % is a visual effect, not measured flow."


# yfinance 由来の内部ラベル (未確定バー除外の対象。FRED/MOF は公表ラグがあり
# 当日データが存在しないため対象外)
YF_SOURCED_LABELS = set(YF_LABELS.values())


def drop_unconfirmed_bars(raw: Dict[str, Optional[Dict[str, float]]]) -> Dict[str, Optional[Dict[str, float]]]:
    """yfinance 系列から「今日(UTC) / 今日(JST)」日付の観測(未確定バー)を除外する。

    根拠: (1) 進行中バーは「終値」ではない(BTC は 24/7 で UTC 日中ずっと更新、
    N225 は 11:00 JST cron 実行時に場中の半日バーが混入する潜在バグ)。
    (2) 未確定バーの混入は無変化ガード(cron 2本目の空コミット防止)を永久に無効化する。
    (3) 除外により同一暦日内の再実行はバイト同一(決定論)になり、新しい確定バーが
    増えた時だけ差分が出る = ガードの本来の挙動。SPEC の「日次終値」定義の忠実化。
    """
    now_utc = datetime.now(timezone.utc)
    today_utc = now_utc.strftime("%Y-%m-%d")
    today_jst = (now_utc + timedelta(hours=9)).strftime("%Y-%m-%d")
    drop_dates = {today_utc, today_jst}

    out: Dict[str, Optional[Dict[str, float]]] = {}
    for label, series in raw.items():
        if label in YF_SOURCED_LABELS and series:
            filtered = {d: v for d, v in series.items() if d not in drop_dates}
            dropped = len(series) - len(filtered)
            if dropped:
                print(f"  [hygiene] {label}: 未確定バー {dropped}件除外 ({sorted(set(series) & drop_dates)})")
            out[label] = filtered or None  # 除外で空になったら None (捏造しない)
        else:
            out[label] = series
    return out


def _to_series(raw: Optional[Dict[str, float]]) -> Optional[pd.Series]:
    """{date_iso: value} dict -> pandas Series (DatetimeIndex, 昇順)。None はそのまま None。"""
    if not raw:
        return None
    s = pd.Series(raw, dtype="float64")
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()
    return s


def _log_return(s: pd.Series) -> pd.Series:
    return np.log(s / s.shift(1)).dropna()


def _bp_change(s: pd.Series) -> pd.Series:
    return ((s - s.shift(1)) * 100.0).dropna()


def build_change_series(raw: Dict[str, Optional[Dict[str, float]]]) -> Dict[str, Optional[pd.Series]]:
    """fetch_all() の生系列(水準)から、相関計算に使う「変化系列」を作る。

    水準相関を禁止するため、株/FXは対数リターン、利回りはbp差分に変換する。
    派生系列 US-JP10Yspread はまず水準スプレッドを作り、それをbp差分化する。
    取得失敗(None)の系列は None のまま伝播する。
    """
    levels: Dict[str, Optional[pd.Series]] = {
        label: _to_series(raw.get(label)) for label in raw
    }

    changes: Dict[str, Optional[pd.Series]] = {}
    for label in LOG_RETURN_LABELS:
        s = levels.get(label)
        changes[label] = _log_return(s) if s is not None and len(s) > 1 else None
    for label in BP_CHANGE_LABELS:
        s = levels.get(label)
        changes[label] = _bp_change(s) if s is not None and len(s) > 1 else None

    # 派生系列: US-JP10Yspread = DGS10水準 - JGB10Y水準 (先に水準スプレッドを作る)
    us10 = levels.get("US10Y")
    jgb10 = levels.get("JGB10Y")
    if us10 is not None and jgb10 is not None:
        spread_level = (us10 - jgb10).dropna()
        changes["US-JP10Yspread"] = _bp_change(spread_level) if len(spread_level) > 1 else None
    else:
        changes["US-JP10Yspread"] = None

    return changes


def _inner_join_frame(changes: Dict[str, Optional[pd.Series]], labels: List[str]) -> pd.DataFrame:
    """指定 labels の変化系列を、値が揃っている日のみで inner join した DataFrame を返す。
    None の系列は列ごと欠落させる(全NaN列として残す。呼び出し側で扱う)。
    前方補完はしない。
    """
    available = {l: changes[l] for l in labels if changes.get(l) is not None}
    if not available:
        return pd.DataFrame(columns=labels)
    df = pd.concat(available, axis=1, join="inner")
    # 欠けている列は全NaNで追加(行列の該当行・列をnullにするため)
    for l in labels:
        if l not in df.columns:
            df[l] = np.nan
    return df[labels]


def _round4(x) -> Optional[float]:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), 4)


def compute_matrix(df_full: pd.DataFrame, window: int) -> tuple[List[List[Optional[float]]], int]:
    """直近 window 行(共通営業日)の相関行列を計算する。

    df_full は10系列共通日で inner join 済みの DataFrame(全列揃っている行のみ)。
    使えるデータが window 未満なら、ある分だけで計算する(0行なら全null)。
    戻り値: (10x10 行列, 実際に使った行数)
    """
    n = len(df_full)
    if n == 0:
        labels = list(df_full.columns)
        return [[None] * len(labels) for _ in labels], 0

    use_n = min(window, n)
    tail = df_full.tail(use_n)
    corr = tail.corr(method="pearson")

    labels = list(df_full.columns)
    matrix: List[List[Optional[float]]] = []
    for li in labels:
        row: List[Optional[float]] = []
        for lj in labels:
            if li == lj:
                # 対角は定義上1.0(データがあれば)。列が全NaNなら値なしなのでnull。
                col_has_data = tail[li].notna().any()
                row.append(1.0 if col_has_data else None)
            else:
                v = corr.loc[li, lj] if li in corr.index and lj in corr.columns else np.nan
                row.append(_round4(v))
        matrix.append(row)
    return matrix, use_n


def compute_key_pairs(changes: Dict[str, Optional[pd.Series]]) -> List[dict]:
    """3ペアそれぞれについて、直近250営業日分のローリング60日相関の時系列を作る。
    ペア毎に2系列だけで inner join し(10列共通日制約は課さない)、ローリング相関。
    """
    out = []
    for a, b in KEY_PAIRS:
        sa, sb = changes.get(a), changes.get(b)
        series_60d: List[dict] = []
        if sa is not None and sb is not None:
            joined = pd.concat({a: sa, b: sb}, axis=1, join="inner").dropna()
            if len(joined) >= WINDOW_LONG:
                roll = joined[a].rolling(WINDOW_LONG).corr(joined[b]).dropna()
                roll = roll.tail(KEY_PAIR_LOOKBACK)
                for dt, v in roll.items():
                    r = _round4(v)
                    if r is not None:
                        series_60d.append({"date": dt.strftime("%Y-%m-%d"), "r": r})
        out.append({"pair": [a, b], "series_60d": series_60d})
    return out


def business_days_lag(latest_obs_date: Optional[date]) -> int:
    if latest_obs_date is None:
        return 9999
    return (date.today() - latest_obs_date).days


def determine_data_status(changes: Dict[str, Optional[pd.Series]], n_obs: int, lag_days: int) -> str:
    """全系列生きていてlag正常なら live。一部Noneまたはlag>5営業日相当ならstale。
    行列が計算不能(共通日<window)ならplaceholder。
    """
    if n_obs < WINDOW_LONG:
        return "placeholder"
    any_missing = any(changes.get(l) is None for l in MATRIX_LABELS)
    # lag>5営業日相当 ≒ 暦日で7日超をおおよその目安にする(週末+休場を吸収)
    if any_missing or lag_days > 7:
        return "stale"
    return "live"


def build_correlations(raw: Dict[str, Optional[Dict[str, float]]]) -> dict:
    changes = build_change_series(raw)

    print("== 系列別 使用可否 / n_obs ==")
    for label in MATRIX_LABELS:
        s = changes.get(label)
        n = len(s) if s is not None else 0
        status = "OK" if s is not None else "MISSING"
        print(f"  {label:16s} {status:8s} n_obs={n}")

    df_full = _inner_join_frame(changes, MATRIX_LABELS)
    # 全列そろっている行だけ(dropna)にして共通営業日にする
    df_full_common = df_full.dropna(how="any")
    n_obs = len(df_full_common)

    matrix_60d, used_60 = compute_matrix(df_full_common, WINDOW_LONG)
    matrix_20d, used_20 = compute_matrix(df_full_common, WINDOW_SHORT)

    if len(df_full_common) > 0:
        latest_obs = df_full_common.index.max().date()
    else:
        # 共通日が皆無でも、生きている系列の最新日で as_of を出す(全滅時のフォールバック)
        latest_dates = [s.index.max().date() for s in changes.values() if s is not None and len(s) > 0]
        latest_obs = max(latest_dates) if latest_dates else None

    lag_days = business_days_lag(latest_obs)
    data_status = determine_data_status(changes, n_obs, lag_days)
    key_pairs = compute_key_pairs(changes)

    as_of_iso = (
        f"{latest_obs.isoformat()}T00:00:00+00:00" if latest_obs is not None else None
    )

    return {
        "as_of": as_of_iso,
        "window": {"long": WINDOW_LONG, "short": WINDOW_SHORT},
        "n_obs": n_obs,
        "matrix_60d": matrix_60d,
        "matrix_20d": matrix_20d,
        "labels": MATRIX_LABELS,
        "key_pairs": key_pairs,
        "data_status": data_status,
        "lag_days": lag_days,
        "sources": SOURCES,
        "method": METHOD_NOTE,
        "note": CORR_NOTE,
    }


# ---------------------------------------------------------------------------
# sink_metrics: money_flow.<region>.sink_metrics
# ---------------------------------------------------------------------------

def _weekly_change_pct(s: Optional[pd.Series]) -> tuple[Optional[float], Optional[str], str]:
    """週次変化% = (最新終値 / 「最新日-7暦日以前で最も近い日」の終値 - 1) * 100。
    戻り値: (wow_pct(2桁丸め)|None, as_of(最新終値の日付)|None, data_status)
    """
    if s is None or len(s) < 2:
        return None, None, "placeholder"
    latest_dt = s.index.max()
    latest_val = s.loc[latest_dt]
    cutoff = latest_dt - pd.Timedelta(days=7)
    prior_candidates = s.index[s.index <= cutoff]
    if len(prior_candidates) == 0:
        return None, latest_dt.strftime("%Y-%m-%d"), "placeholder"
    prior_dt = prior_candidates.max()
    prior_val = s.loc[prior_dt]
    if prior_val == 0 or pd.isna(prior_val) or pd.isna(latest_val):
        return None, latest_dt.strftime("%Y-%m-%d"), "placeholder"
    pct = (float(latest_val) / float(prior_val) - 1.0) * 100.0
    return round(pct, 2), latest_dt.strftime("%Y-%m-%d"), "live"


def build_sink_metrics(raw: Dict[str, Optional[Dict[str, float]]]) -> Dict[str, dict]:
    """money_flow.us/eu/jp 各地域の sink_metrics ブロックを作る。"""
    levels = {label: _to_series(raw.get(label)) for label in raw}

    out: Dict[str, dict] = {}
    for region, sinks in SINK_SPEC.items():
        block = {"label_type": "weekly_change"}
        as_of_candidates = []
        for sink_name, (ticker, label) in sinks.items():
            s = levels.get(label)
            wow_pct, as_of, status = _weekly_change_pct(s)
            block[sink_name] = {
                "symbol": ticker,
                "wow_pct": wow_pct,
                "as_of": as_of,
                "data_status": status,
            }
            if as_of:
                as_of_candidates.append(as_of)
        block["as_of"] = max(as_of_candidates) if as_of_candidates else None
        block["note"] = SINK_METRICS_NOTE
        out[region] = block
    return out


# ---------------------------------------------------------------------------
# read-modify-write マージ
# ---------------------------------------------------------------------------

def merge_into_data_json(correlations: dict, sink_metrics_by_region: Dict[str, dict], dry_run: bool = False) -> dict:
    if not DATA_JSON.exists():
        raise FileNotFoundError(f"{DATA_JSON} が見つかりません")

    with open(DATA_JSON, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    original_top_keys = set(data.keys())
    original_money_flow_region_keys = {
        r: set(data.get("money_flow", {}).get(r, {}).keys())
        for r in ("us", "eu", "jp")
        if r in data.get("money_flow", {})
    }

    # correlations は新規トップレベルキーとして追加/更新(既存キーは触らない)
    data["correlations"] = correlations

    # money_flow.<region>.sink_metrics を追記(既存の他フィールドは無傷)
    if "money_flow" not in data:
        data["money_flow"] = {}
    for region, metrics in sink_metrics_by_region.items():
        if region not in data["money_flow"]:
            data["money_flow"][region] = {}
        data["money_flow"][region]["sink_metrics"] = metrics

    # 検証: 既存トップレベルキーが壊れていないか
    preserved = original_top_keys.issubset(set(data.keys()))
    print(f"== 既存トップレベルキー保全チェック: {'OK' if preserved else 'NG'} ==")
    print(f"  before: {sorted(original_top_keys)}")
    print(f"  after : {sorted(data.keys())}")
    for r, keys in original_money_flow_region_keys.items():
        after_keys = set(data["money_flow"][r].keys())
        ok = keys.issubset(after_keys)
        print(f"  money_flow.{r} 既存キー保全: {'OK' if ok else 'NG'} ({sorted(keys)} ⊆ {sorted(after_keys)})")

    if not dry_run:
        with open(DATA_JSON, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))

    return data


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    print("== fetch_all() 実行中 (FRED は curl フォールバックで最大3分程度) ==")
    raw = fetch_all()

    # data-hygiene: 未確定バー(今日UTC/JST)を除外してから計算する
    # (correlations / sink_metrics 両方の入力に適用。as_of も除外後の系列で決まる)
    raw = drop_unconfirmed_bars(raw)

    correlations = build_correlations(raw)
    sink_metrics_by_region = build_sink_metrics(raw)

    if dry_run:
        print("\n== --dry-run: correlations サマリ (書き込みなし) ==")
        print(f"  n_obs        = {correlations['n_obs']}")
        print(f"  data_status  = {correlations['data_status']}")
        print(f"  as_of        = {correlations['as_of']}")
        print(f"  lag_days     = {correlations['lag_days']}")
        labels = correlations["labels"]
        diag = [correlations["matrix_60d"][i][i] for i in range(len(labels))]
        print(f"  matrix_60d 対角 = {diag}")
        n225_idx = labels.index("N225")
        usdjpy_idx = labels.index("USDJPY")
        rep_val = correlations["matrix_60d"][n225_idx][usdjpy_idx]
        print(f"  代表値 matrix_60d[N225][USDJPY] = {rep_val}")
        for kp in correlations["key_pairs"]:
            print(f"  key_pair {kp['pair']}: series_60d len={len(kp['series_60d'])}")
        print("\n  sink_metrics:")
        for region, block in sink_metrics_by_region.items():
            print(f"    {region}: as_of={block.get('as_of')} "
                  + ", ".join(f"{k}={block[k]['wow_pct']}" for k in ("stocks", "gold", "crypto", "cash")))
        try:
            merge_into_data_json(correlations, sink_metrics_by_region, dry_run=True)
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        return 0

    try:
        merge_into_data_json(correlations, sink_metrics_by_region, dry_run=False)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"\n== 書き込み完了: {DATA_JSON} ==")
    print(f"  correlations.n_obs = {correlations['n_obs']}, data_status = {correlations['data_status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
