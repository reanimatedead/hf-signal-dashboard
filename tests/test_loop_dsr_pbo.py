"""Agent 3 — DSR / PBO 簡略実装の数学的健全性 (SPEC_LOOP §4)."""
import math
import random
import pytest

of = pytest.importorskip("loop.overfit", reason="Agent 3 未実装")


def test_expected_max_sr_grows_with_n():
    a = of.expected_max_sr(2)
    b = of.expected_max_sr(5)
    c = of.expected_max_sr(20)
    assert a < b < c, f"E[SR_max] must grow with N: {a}, {b}, {c}"


def test_expected_max_sr_value_for_n5():
    # √(2 ln 5) ≈ 1.794
    e = of.expected_max_sr(5)
    assert abs(e - math.sqrt(2 * math.log(5))) < 1e-9


def test_sr_annualized_uses_252():
    rng = random.Random(0)
    returns = [0.001 * rng.gauss(0, 1) for _ in range(252)]   # daily, 1 year
    sr = of.sharpe_annualized(returns, period=252)
    # mean 0, std ~ 0.001 → SR ~ 0 ± noise
    assert sr is not None and -1 < sr < 1


def test_dsr_subtracts_expected_max():
    rng = random.Random(1)
    returns = [0.01 + 0.005 * rng.gauss(0, 1) for _ in range(252)]
    sr = of.sharpe_annualized(returns, period=252)
    dsr = of.deflated_sharpe(sr, n_trials=5)
    assert dsr is not None
    # round(6) 切捨ての許容
    assert abs(dsr - (sr - of.expected_max_sr(5))) < 1e-5


def test_pbo_sign_consistency_pass_when_both_halves_positive():
    pos = [0.01] * 100
    res = of.pbo_split_sign_consistent(pos)
    assert res["consistent"] is True


def test_pbo_sign_consistency_fail_when_halves_disagree():
    series = [0.01] * 50 + [-0.01] * 50    # 前半正 / 後半負
    res = of.pbo_split_sign_consistent(series)
    assert res["consistent"] is False
    assert res["first_half_mean"] > 0 and res["second_half_mean"] < 0


def test_pbo_handles_small_sample():
    res = of.pbo_split_sign_consistent([0.01, -0.01])
    # 2 件しかない場合は consistent=None (undetermined)
    assert res["consistent"] in (None, True, False)
    assert "first_half_mean" in res and "second_half_mean" in res


def test_pass_threshold_raises_with_trial_count():
    # 試行数で threshold が引き上がる
    th_1 = of.dsr_pass_threshold(n_trials=1)
    th_5 = of.dsr_pass_threshold(n_trials=5)
    th_20 = of.dsr_pass_threshold(n_trials=20)
    assert th_1 <= th_5 <= th_20
