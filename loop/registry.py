"""loop.registry — 5 仮説 (HA-HE) 登録簿 (SPEC_LOOP §2).

★パラメータはスカラー固定. ループ中に書き換えない. 別パラメータを試したい場合は
SPEC を改訂して新仮説として登録 (= 試行数 +1).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# 指数 / 主要 FX 限定. 個別株は対象外 (test_loop_universe_indices_only で検査).
ALLOWED_SYMBOLS = frozenset({
    "^N225", "^GSPC", "^DJI", "^NDX",
    "^VIX", "^MOVE", "^TNX", "^TYX",
    "USDJPY=X", "EURUSD=X", "GBPUSD=X", "AUDUSD=X", "EURJPY=X",
})

MA_WINDOW = 288
SLOPE_BARS = 5
BAND_K_SIGMA = 2.0
TSMOM_LOOKBACK = 60


# ──────────────────────────────────────────────
# predict 関数群 — 全て watched[:t+1] のみ参照 (look-ahead 厳禁)
# ──────────────────────────────────────────────
def _closes_window(watched, t: int, n: int) -> Optional[list]:
    """watched[t-n+1 .. t] の close 値を返す. 不足なら None."""
    if t < n - 1:
        return None
    out = []
    for k in range(n - 1, -1, -1):
        b = watched[t - k]
        c = b.get("close") if isinstance(b, dict) else None
        if c is None:
            return None
        out.append(float(c))
    return out


def predict_288_cross(watched, t: int) -> Optional[Dict[str, Any]]:
    """HA: close が 288MA を上抜けで long, 下抜けで short."""
    closes = _closes_window(watched, t, MA_WINDOW + 1)
    if closes is None:
        return None
    ma_now = sum(closes[1:]) / MA_WINDOW          # 直近 288 本
    ma_prev = sum(closes[:-1]) / MA_WINDOW        # 1 本前の 288 本
    px_now = closes[-1]
    px_prev = closes[-2]
    if px_prev <= ma_prev and px_now > ma_now:
        return {"direction": "long", "predicted_prob": 0.55}
    if px_prev >= ma_prev and px_now < ma_now:
        return {"direction": "short", "predicted_prob": 0.55}
    return None


def predict_288_slope(watched, t: int) -> Optional[Dict[str, Any]]:
    """HB: 288MA の傾き (SLOPE_BARS 本前と比較) が正なら long."""
    closes = _closes_window(watched, t, MA_WINDOW + SLOPE_BARS)
    if closes is None:
        return None
    ma_now = sum(closes[-MA_WINDOW:]) / MA_WINDOW
    ma_old = sum(closes[-(MA_WINDOW + SLOPE_BARS):-SLOPE_BARS]) / MA_WINDOW
    if ma_now > ma_old:
        return {"direction": "long", "predicted_prob": 0.55}
    if ma_now < ma_old:
        return {"direction": "short", "predicted_prob": 0.55}
    return None


def predict_288_band(watched, t: int) -> Optional[Dict[str, Any]]:
    """HC: close が 288MA ± kσ を超えたら平均回帰 (上抜けで short)."""
    closes = _closes_window(watched, t, MA_WINDOW)
    if closes is None:
        return None
    mean = sum(closes) / MA_WINDOW
    var = sum((c - mean) ** 2 for c in closes) / MA_WINDOW
    sigma = var ** 0.5
    if sigma <= 0:
        return None
    px = closes[-1]
    if px > mean + BAND_K_SIGMA * sigma:
        return {"direction": "short", "predicted_prob": 0.55}
    if px < mean - BAND_K_SIGMA * sigma:
        return {"direction": "long", "predicted_prob": 0.55}
    return None


def predict_index_tsmom(watched, t: int) -> Optional[Dict[str, Any]]:
    """HD: 過去 LOOKBACK 日リターンの符号で direction."""
    if t < TSMOM_LOOKBACK:
        return None
    past = watched[t - TSMOM_LOOKBACK].get("close")
    now = watched[t].get("close")
    if past is None or now is None or past <= 0:
        return None
    ret = (float(now) - float(past)) / float(past)
    if ret > 0:
        return {"direction": "long", "predicted_prob": 0.55}
    if ret < 0:
        return {"direction": "short", "predicted_prob": 0.55}
    return None


def predict_regime_tsmom(watched, t: int) -> Optional[Dict[str, Any]]:
    """HE: HD を「close > 288MA」のときだけ採用 (リスクオフでは何もしない)."""
    closes = _closes_window(watched, t, MA_WINDOW)
    if closes is None:
        return None
    ma = sum(closes) / MA_WINDOW
    if closes[-1] <= ma:
        return None
    return predict_index_tsmom(watched, t)


# ──────────────────────────────────────────────
# 登録簿
# ──────────────────────────────────────────────
REGISTRY: List[Dict[str, Any]] = [
    {
        "name": "288_cross",
        "predict": predict_288_cross,
        "params": {"ma_window": MA_WINDOW},
        "rationale": "288日 ≈ 1年。長期 MA クロスは大型機関のリバランス節目"
                      " (Fama-French momentum literature が示す trend persistence の最低単位).",
    },
    {
        "name": "288_slope",
        "predict": predict_288_slope,
        "params": {"ma_window": MA_WINDOW, "slope_bars": SLOPE_BARS},
        "rationale": "MA の傾きは trend persistence の最も単純な指標"
                      " (Hong-Stein 2007 underreaction-driven momentum 仮説).",
    },
    {
        "name": "288_band",
        "predict": predict_288_band,
        "params": {"ma_window": MA_WINDOW, "k_sigma": BAND_K_SIGMA},
        "rationale": "Bollinger Band on 1Y window. 長期 σ から逸脱は mean reversion 候補"
                      " (Lehmann 1990 mean-reversion literature).",
    },
    {
        "name": "index_tsmom",
        "predict": predict_index_tsmom,
        "params": {"lookback": TSMOM_LOOKBACK},
        "rationale": "Time-series momentum, Moskowitz-Ooi-Pedersen 2012"
                      " (12 ヶ月 TSMOM、ここでは 60 日へ短縮、指数限定で確認).",
    },
    {
        "name": "regime_tsmom",
        "predict": predict_regime_tsmom,
        "params": {"lookback": TSMOM_LOOKBACK, "ma_window": MA_WINDOW},
        "rationale": "Regime filter は trend in trend を捕える"
                      " (Faber 2007 Tactical Asset Allocation の核アイデア).",
    },
]
