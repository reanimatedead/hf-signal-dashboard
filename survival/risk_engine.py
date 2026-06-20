"""survival.risk_engine — リスク自動設計 (SPEC_SURVIVAL §1, §2).

固定天井 (HARD_CAPS) は **学習しない**。値は年単位の見直し前提だが、
ここで動的に動くと「死なない土台」が崩れるため、コードで強制する。

公開 API:
    HARD_CAPS                       — 定数辞書
    auto_risk_per_trade(...)        — 1 トレード許容リスク %
    position_size_pct(...)          — 1/4 Kelly × 逆ボラ → % サイズ
    dd_state(peak_to_current_pct)   — "normal" | "shrink" | "stop"
    concurrent_cap(correlation)     — 同時保有上限 (1..3)
    clamp_risk(pct)                 — 受領した提案を天井に強制
    margin_simulator(...)           — 維持率 + レバ感応度
"""

from __future__ import annotations

import math
from typing import List, Sequence

# ──────────────────────────────────────────────
# 固定天井 (学習禁止 / SPEC §1)
# ──────────────────────────────────────────────
HARD_CAPS = {
    "PER_TRADE_PCT_MAX": 0.5,
    "DD_SHRINK_PCT":     -10.0,
    "DD_STOP_PCT":       -15.0,
    "MAX_CONCURRENT":    3,
    "KELLY_FRACTION":    0.25,
    "TARGET_VOL_PCT":    1.0,
}

# 内部 reference (auto_risk_per_trade 基準)
_BASE_PER_TRADE_PCT = 0.5


def _safe_float(x, default=0.0):
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


# ──────────────────────────────────────────────
# §2.1 1 トレード許容リスク (逆ボラスケーリング)
# ──────────────────────────────────────────────
def auto_risk_per_trade(target_vol_pct: float, realized_vol_pct: float) -> float:
    """target_vol / realized_vol で逆スケール。天井 0.5% を絶対に超えない。

    realized_vol が極小 / 0 の場合でも天井に張り付くだけで NaN / inf にしない。
    """
    t = _safe_float(target_vol_pct, default=HARD_CAPS["TARGET_VOL_PCT"])
    r = _safe_float(realized_vol_pct, default=t)
    if r <= 0:
        # ゼロ除算回避 → 天井で打ち止め (緩めない)
        return HARD_CAPS["PER_TRADE_PCT_MAX"]
    raw = (t / r) * _BASE_PER_TRADE_PCT
    return clamp_risk(raw)


# ──────────────────────────────────────────────
# §2.2 ポジションサイズ (Kelly × 逆ボラ)
# ──────────────────────────────────────────────
def kelly_quarter(win_prob: float, win_loss_ratio: float) -> float:
    """1/4 Kelly. 負の edge と b<=0 は 0 を返す."""
    p = _safe_float(win_prob)
    b = _safe_float(win_loss_ratio)
    if b <= 0:
        return 0.0
    q = 1.0 - p
    full = (b * p - q) / b
    if full <= 0:
        return 0.0
    return full * HARD_CAPS["KELLY_FRACTION"]


def position_size_pct(win_prob: float, win_loss_ratio: float,
                      realized_vol_pct: float,
                      target_vol_pct: float = None) -> float:
    """ポジション % サイズ = Kelly(1/4) × 逆ボラ × 100. 天井で必ずクランプ.

    返り値は 0.0..PER_TRADE_PCT_MAX (%) の範囲。
    """
    target_vol_pct = (target_vol_pct
                     if target_vol_pct is not None
                     else HARD_CAPS["TARGET_VOL_PCT"])
    k = kelly_quarter(win_prob, win_loss_ratio)
    if k <= 0:
        return 0.0
    r = _safe_float(realized_vol_pct)
    if r <= 0:
        # ゼロ除算回避: 天井で打ち止め
        return HARD_CAPS["PER_TRADE_PCT_MAX"]
    inv_vol = target_vol_pct / r
    raw = k * inv_vol * 100.0
    return clamp_risk(raw)


# ──────────────────────────────────────────────
# §2.3 DD 状態判定 (固定絶対線)
# ──────────────────────────────────────────────
def dd_state(peak_to_current_pct: float) -> str:
    """current/peak の DD% (負値) を受け取り 3 状態を返す。"""
    v = _safe_float(peak_to_current_pct, default=0.0)
    if v <= HARD_CAPS["DD_STOP_PCT"]:
        return "stop"
    if v <= HARD_CAPS["DD_SHRINK_PCT"]:
        return "shrink"
    return "normal"


# ──────────────────────────────────────────────
# §2.4 同時保有上限 (相関調整 / 固定天井 3)
# ──────────────────────────────────────────────
def concurrent_cap(correlation_matrix: Sequence[Sequence[float]]) -> int:
    if not correlation_matrix:
        return 1
    n = len(correlation_matrix)
    if n == 1:
        return 1
    s = 0.0
    cnt = 0
    for i in range(n):
        row = correlation_matrix[i] or []
        for j in range(i + 1, n):
            if j >= len(row):
                continue
            s += abs(_safe_float(row[j]))
            cnt += 1
    if cnt == 0:
        return 1
    avg = s / cnt
    raw = HARD_CAPS["MAX_CONCURRENT"] * max(0.0, 1.0 - avg)
    slots = int(round(raw))
    return max(1, min(HARD_CAPS["MAX_CONCURRENT"], slots))


# ──────────────────────────────────────────────
# clamp utility (天井の最終防衛線)
# ──────────────────────────────────────────────
def clamp_risk(pct: float) -> float:
    v = _safe_float(pct, default=0.0)
    if v <= 0:
        return 0.0
    return min(v, HARD_CAPS["PER_TRADE_PCT_MAX"])


def clamp_risk_list(pct_list: Sequence[float]) -> List[float]:
    return [clamp_risk(x) for x in (pct_list or [])]


# ──────────────────────────────────────────────
# §2.5 証拠金シミュレータ
# ──────────────────────────────────────────────
def margin_simulator(notional_pct: float, equity_pct: float = 100.0,
                     leverage_x: float = 0.0) -> dict:
    """口座 API なし前提の現物 / 簡易レバ感応度.

    leverage_x = 0 → 現物相当 (notional = equity に対する % で計算).
    """
    n = max(0.0, _safe_float(notional_pct))
    eq = max(1e-6, _safe_float(equity_pct, default=100.0))
    if leverage_x and leverage_x > 0:
        used = n / leverage_x
    else:
        used = n
    maint = used / eq
    warning = maint >= 0.8
    sens = {f"x{int(lx)}": round(min(1.0, n / max(lx, 1e-6) / eq), 4)
            for lx in (1, 2, 3)}
    return {
        "notional_pct": round(n, 4),
        "equity_pct": round(eq, 4),
        "maint_ratio": round(maint, 4),
        "warning": warning,
        "leverage_sensitivity": sens,
        "note": "情報提供のみ。買い/売り推奨ではない。",
    }


# ──────────────────────────────────────────────
# 上位 facade: 1 日 1 回の自動リスク決定 (data.json 用)
# ──────────────────────────────────────────────
def design_daily_risk(realized_vol_pct: float,
                      win_prob: float = 0.50,
                      win_loss_ratio: float = 1.0,
                      target_vol_pct: float = None) -> dict:
    """Phase 1 用. 履歴が無くても安全な既定値で値を返す."""
    target = target_vol_pct or HARD_CAPS["TARGET_VOL_PCT"]
    per_trade = auto_risk_per_trade(target, realized_vol_pct)
    size = position_size_pct(win_prob, win_loss_ratio, realized_vol_pct, target)
    return {
        "per_trade_pct": per_trade,
        "position_size_pct": size,
        "kelly_fraction": HARD_CAPS["KELLY_FRACTION"],
        "target_vol_pct": target,
        "realized_vol_pct": round(_safe_float(realized_vol_pct), 4),
        "max_concurrent": HARD_CAPS["MAX_CONCURRENT"],
        "dd_shrink_pct": HARD_CAPS["DD_SHRINK_PCT"],
        "dd_stop_pct": HARD_CAPS["DD_STOP_PCT"],
        "source": "inverse_vol_scaling, kelly_quarter (Phase 1)",
    }
