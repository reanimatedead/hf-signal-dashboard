"""backtest.h1 — 単一仮説 H1: 前日 US 終値リターン → 日本オーバーナイト波及.

SPEC_H1.md と一対. 仮説のみを固定実装し、学習しない (Phase 2 未着工 / not implemented).
他仮説 H2..H10 は本ファイルに持ち込まない (test_h1_only が grep で検知).

公開 API:
    build_us_close_returns(us_bars)        -> {us_date_str: close_to_close_return}
    build_features(jp_bars, us_returns)    -> {jp_date_str: us_prev_return}
    compute_labels(jp_bars)                -> [{overnight, open_to_close, next_week}, ...]
    predict(features, jp_date)             -> {direction, predicted_prob}
    run_h1(jp_bars, us_bars, segments, ...) -> dict (3 labels × N segments + sanity)
"""

from __future__ import annotations

import bisect
import datetime
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import metrics


# ──────────────────────────────────────────────
# 特徴量 (前日 US 終値リターンのみ)
# ──────────────────────────────────────────────
def build_us_close_returns(us_bars: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    """US 終値の close-to-close リターンを {date_str: return} で返す.

    最初のバーは前日が無いため出力に含めない.
    """
    out: Dict[str, float] = {}
    prev_close: Optional[float] = None
    for b in us_bars or []:
        ts = str(b.get("ts") or "")
        close = b.get("close")
        if not ts or close is None:
            continue
        try:
            c = float(close)
        except (TypeError, ValueError):
            continue
        if prev_close is not None and prev_close > 0:
            out[ts[:10]] = (c - prev_close) / prev_close
        prev_close = c
    return out


def build_features(jp_bars: Sequence[Dict[str, Any]],
                   us_returns: Dict[str, float]) -> Dict[str, float]:
    """各 JP date T について 「T より厳密に過去」の最大 US date の return を返す.

    look-ahead 物理保証 (SPEC §1.1):
      - 同日 US (US date == JP date) は使わない (US close は JST 翌朝確定).
      - US 側で T より未来のバーは決して参照しない.
    """
    sorted_us = sorted(us_returns.keys())
    feats: Dict[str, float] = {}
    for b in jp_bars or []:
        ts = str(b.get("ts") or "")
        if not ts:
            continue
        jp_date = ts[:10]
        # bisect_left で「< jp_date」の最大値を取る
        i = bisect.bisect_left(sorted_us, jp_date)
        if i == 0:
            continue
        us_date = sorted_us[i - 1]
        feats[jp_date] = us_returns[us_date]
    return feats


# ──────────────────────────────────────────────
# 予測 (シンプル: 符号 + 固定確率)
# ──────────────────────────────────────────────
_PREDICT_PROB = 0.55


def predict(features: Dict[str, float], jp_date: str) -> Optional[Dict[str, Any]]:
    """features dict のみを参照する (US 生バーには触れない)."""
    f = features.get(jp_date)
    if f is None:
        return None
    return {
        "direction": "long" if f > 0 else "short",
        "predicted_prob": _PREDICT_PROB,
        "feature": f,
    }


# ──────────────────────────────────────────────
# 3 ラベル
# ──────────────────────────────────────────────
def compute_labels(jp_bars: Sequence[Dict[str, Any]]) -> List[Dict[str, Optional[float]]]:
    n = len(jp_bars or [])
    out: List[Dict[str, Optional[float]]] = []
    for i in range(n):
        b = jp_bars[i]
        try:
            open_ = float(b.get("open"))
            close = float(b.get("close"))
        except (TypeError, ValueError):
            out.append({"ts": b.get("ts"), "overnight": None,
                         "open_to_close": None, "next_week": None})
            continue
        overnight: Optional[float] = None
        if i > 0:
            try:
                pc = float(jp_bars[i - 1]["close"])
                if pc > 0:
                    overnight = (open_ - pc) / pc
            except (TypeError, ValueError, KeyError):
                pass
        otc: Optional[float] = None
        if open_ > 0:
            otc = (close - open_) / open_
        nw: Optional[float] = None
        if i + 5 < n:
            try:
                fc = float(jp_bars[i + 5]["close"])
                if close > 0:
                    nw = (fc - close) / close
            except (TypeError, ValueError, KeyError):
                pass
        out.append({"ts": b.get("ts"), "overnight": overnight,
                    "open_to_close": otc, "next_week": nw})
    return out


# ──────────────────────────────────────────────
# サニティチェック (Pearson + t)
# ──────────────────────────────────────────────
def _pearson(xs: Sequence[float], ys: Sequence[float]
             ) -> Tuple[Optional[float], Optional[float], int]:
    pairs = [(x, y) for x, y in zip(xs, ys)
             if x is not None and y is not None
             and math.isfinite(x) and math.isfinite(y)]
    n = len(pairs)
    if n < 3:
        return None, None, n
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    num = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    dx2 = sum((p[0] - mx) ** 2 for p in pairs)
    dy2 = sum((p[1] - my) ** 2 for p in pairs)
    denom = (dx2 * dy2) ** 0.5
    if denom <= 0:
        return None, None, n
    r = num / denom
    if r >= 1.0:
        r = 0.9999
    if r <= -1.0:
        r = -0.9999
    t = r * ((n - 2) / max(1e-12, 1 - r * r)) ** 0.5
    return round(r, 6), round(t, 4), n


def _sanity_for(label_name: str, feats: Sequence[float],
                lbl: Sequence[Optional[float]],
                overnight_r: Optional[float] = None) -> Dict[str, Any]:
    r, t, n = _pearson(feats, lbl)
    out: Dict[str, Any] = {"pearson": r, "t": t, "n": n, "pass": None}
    if r is None or t is None:
        out["pass"] = False
        return out
    if label_name == "overnight":
        out["pass"] = (r > 0) and (abs(t) > 2.0)
    elif label_name == "open_to_close":
        # 実データでは情報吸収のラグで open_to_close にも弱い同符号相関が出るが、
        # overnight より絶対値が小さくなければデータのタイムゾーンが壊れている.
        if overnight_r is None or overnight_r <= 0:
            out["pass"] = (abs(r) < 0.10) and (abs(t) < 2.5)
        else:
            out["pass"] = abs(r) < abs(overnight_r)
    else:                                # next_week — 期待値なし
        out["pass"] = None
    return out


# ──────────────────────────────────────────────
# run_h1 (segment × label の集計)
# ──────────────────────────────────────────────
def _in_segment(date_str: str, lo: Optional[str], hi: Optional[str]) -> bool:
    if lo is not None and date_str < lo:
        return False
    if hi is not None and date_str >= hi:
        return False
    return True


def _judge_from_metric(m: Dict[str, Any]) -> str:
    n = int(m.get("n") or 0)
    ci = m.get("avg_net_pct_ci")
    if n < 30:
        return "insufficient"
    if not isinstance(ci, (list, tuple)) or len(ci) != 2:
        return "inconclusive"
    lo, hi = float(ci[0]), float(ci[1])
    if lo > 0:
        return "edge"
    if hi < 0:
        return "no-edge"
    return "inconclusive"


def _build_trades_for_label(features: Dict[str, float],
                            labels: List[Dict[str, Optional[float]]],
                            label_name: str,
                            seg_lo: Optional[str],
                            seg_hi: Optional[str]
                            ) -> List[Dict[str, Any]]:
    """forecasting trades: realized = label_value * sign(feature). コストは載せない."""
    out: List[Dict[str, Any]] = []
    for lab in labels:
        ts = str(lab.get("ts") or "")
        if not ts:
            continue
        date = ts[:10]
        if not _in_segment(date, seg_lo, seg_hi):
            continue
        f = features.get(date)
        if f is None:
            continue
        value = lab.get(label_name)
        if value is None or not math.isfinite(value):
            continue
        direction = 1 if f > 0 else -1
        realized = float(value) * direction * 100.0     # to %
        out.append({
            "ts": ts,
            "predicted_prob": _PREDICT_PROB,
            "outcome01": 1 if realized > 0 else 0,
            "net_pct": round(realized, 6),
        })
    return out


def run_h1(*, jp_bars: Sequence[Dict[str, Any]],
           us_bars: Sequence[Dict[str, Any]],
           segments: Sequence[Tuple[str, Optional[str], Optional[str]]] = (
               ("pre_2023", None, "2023-01-01"),
               ("since_2023", "2023-01-01", None),
           ),
           bootstrap_runs: int = 300,
           n_min: int = 30,
           jp_symbol: str = "^N225",
           us_symbol: str = "^GSPC") -> Dict[str, Any]:
    us_returns = build_us_close_returns(us_bars)
    features = build_features(jp_bars, us_returns)
    labels = compute_labels(jp_bars)

    segments_out: List[Dict[str, Any]] = []
    for name, lo, hi in segments:
        # サニティ用に segment 内の (feat, label) ペアを構築
        feats_seg: Dict[str, List[float]] = {"overnight": [], "open_to_close": [],
                                              "next_week": []}
        labs_seg: Dict[str, List[float]] = {"overnight": [], "open_to_close": [],
                                             "next_week": []}
        n_jp = 0
        n_with_feat = 0
        for lab in labels:
            ts = str(lab.get("ts") or "")
            date = ts[:10]
            if not _in_segment(date, lo, hi):
                continue
            n_jp += 1
            f = features.get(date)
            if f is None:
                continue
            n_with_feat += 1
            for k in ("overnight", "open_to_close", "next_week"):
                v = lab.get(k)
                if v is not None and math.isfinite(v):
                    feats_seg[k].append(f)
                    labs_seg[k].append(v)
        # overnight を先に計算 → open_to_close の判定で参照
        on_s = _sanity_for("overnight", feats_seg["overnight"], labs_seg["overnight"])
        sanity = {
            "overnight": on_s,
            "open_to_close": _sanity_for("open_to_close",
                                          feats_seg["open_to_close"],
                                          labs_seg["open_to_close"],
                                          overnight_r=on_s.get("pearson")),
            "next_week": _sanity_for("next_week", feats_seg["next_week"],
                                      labs_seg["next_week"]),
        }

        labels_out: Dict[str, Any] = {}
        for k in ("overnight", "open_to_close", "next_week"):
            trades = _build_trades_for_label(features, labels, k, lo, hi)
            m = metrics.summarize(trades, bootstrap_runs=bootstrap_runs,
                                   ci=0.95, n_min=n_min)
            m["judge"] = _judge_from_metric(m)
            labels_out[k] = m

        segments_out.append({
            "name": name, "from": lo, "to": hi,
            "n_jp_bars": n_jp, "n_with_feature": n_with_feat,
            "sanity": sanity, "labels": labels_out,
        })

    return {
        "ok": True,
        "as_of_utc": datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0).isoformat(),
        "hypothesis": "h1",
        "jp_symbol": jp_symbol, "us_symbol": us_symbol,
        "segments": segments_out,
        "note": "Single-hypothesis raw predictive-power measurement. "
                "Not investment advice. Phase 2 (learning) is not implemented.",
    }
