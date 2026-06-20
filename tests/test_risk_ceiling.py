"""Hard ceiling tests for survival.risk_engine (SPEC_SURVIVAL §1, §2, §8.3)

実装より先にコミット。値や挙動を変えるなら SPEC を先に直すこと。
"""
import importlib
import math
import pytest

re = pytest.importorskip(
    "survival.risk_engine",
    reason="Agent C 未実装。survival/risk_engine.py を作るとここが緑になる。",
)


# ── §1. 固定天井定数 ──────────────────────────────────────
def test_hard_caps_defined_and_immutable():
    caps = re.HARD_CAPS
    assert caps["PER_TRADE_PCT_MAX"] == 0.5
    assert caps["DD_SHRINK_PCT"] == -10.0
    assert caps["DD_STOP_PCT"] == -15.0
    assert caps["MAX_CONCURRENT"] == 3
    assert caps["KELLY_FRACTION"] == 0.25
    assert caps["TARGET_VOL_PCT"] == 1.0


# ── §2.1 1 トレード許容: どんな入力でも 0.5% を超えない ──
@pytest.mark.parametrize(
    "target,realized",
    [(1.0, 1.0), (1.0, 0.1), (1.0, 0.01), (1.0, 0.0001), (5.0, 0.5), (10.0, 0.01)],
)
def test_auto_risk_per_trade_caps_at_half_percent(target, realized):
    v = re.auto_risk_per_trade(target_vol_pct=target, realized_vol_pct=realized)
    assert 0.0 <= v <= re.HARD_CAPS["PER_TRADE_PCT_MAX"], (
        f"per-trade risk must not exceed 0.5%, got {v} for target={target}/realized={realized}"
    )


def test_auto_risk_per_trade_handles_zero_realized_vol_gracefully():
    # ゼロ除算で天井破ってはいけない
    v = re.auto_risk_per_trade(target_vol_pct=1.0, realized_vol_pct=0.0)
    assert v <= re.HARD_CAPS["PER_TRADE_PCT_MAX"]


# ── §2.2 ポジションサイズ Kelly × 逆ボラ → 同じく 0.5% 上限 ──
@pytest.mark.parametrize(
    "p,b,realized",
    [(0.9, 5.0, 0.01), (0.99, 100.0, 0.001), (0.55, 10.0, 0.5), (0.50, 2.0, 1.0)],
)
def test_position_size_caps_at_half_percent(p, b, realized):
    v = re.position_size_pct(win_prob=p, win_loss_ratio=b, realized_vol_pct=realized)
    assert 0.0 <= v <= re.HARD_CAPS["PER_TRADE_PCT_MAX"], (
        f"size must not exceed 0.5%, got {v} for p={p}, b={b}, rv={realized}"
    )


def test_position_size_returns_zero_when_no_edge():
    # p*b - q <= 0 で size 0
    v = re.position_size_pct(win_prob=0.4, win_loss_ratio=1.0, realized_vol_pct=1.0)
    assert v == 0.0


def test_position_size_zero_when_b_nonpositive():
    v = re.position_size_pct(win_prob=0.6, win_loss_ratio=0.0, realized_vol_pct=1.0)
    assert v == 0.0
    v = re.position_size_pct(win_prob=0.6, win_loss_ratio=-1.0, realized_vol_pct=1.0)
    assert v == 0.0


# ── §2.3 DD 状態 ───────────────────────────────────────
@pytest.mark.parametrize(
    "dd,expected",
    [(0.0, "normal"), (-9.99, "normal"), (-10.0, "shrink"), (-12.0, "shrink"),
     (-15.0, "stop"), (-20.0, "stop"), (-100.0, "stop")],
)
def test_dd_state_thresholds(dd, expected):
    assert re.dd_state(peak_to_current_pct=dd) == expected


def test_dd_stop_is_absolute_floor_never_normal():
    # 任意の入力で -15% 以下では normal が返らない
    for dd in (-15.0, -50.0, -1000.0):
        assert re.dd_state(dd) != "normal"


# ── §2.4 同時保有上限 ────────────────────────────────────
def test_concurrent_cap_never_exceeds_three():
    # 強い相関 → 1〜2 スロット
    high_corr = [[1.0, 0.9, 0.9], [0.9, 1.0, 0.9], [0.9, 0.9, 1.0]]
    n = re.concurrent_cap(high_corr)
    assert 1 <= n <= re.HARD_CAPS["MAX_CONCURRENT"]
    # 弱い相関 → 3 まで許容
    low_corr = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    n2 = re.concurrent_cap(low_corr)
    assert n2 == re.HARD_CAPS["MAX_CONCURRENT"]


def test_concurrent_cap_is_at_least_one():
    extreme = [[1.0, 1.0], [1.0, 1.0]]
    assert re.concurrent_cap(extreme) >= 1
    # 単一銘柄でも 1 を返す
    assert re.concurrent_cap([[1.0]]) >= 1


# ── §8 受け入れ: 「天井超え提案は弾かれる」 ────────────
def test_clamp_risk_rejects_ceiling_violations():
    # auto_risk_per_trade を一切経由しなくても、最終的に clamp_risk が天井を強制する
    v = re.clamp_risk(99.0)
    assert v <= re.HARD_CAPS["PER_TRADE_PCT_MAX"]
    v = re.clamp_risk(-5.0)
    assert v == 0.0
