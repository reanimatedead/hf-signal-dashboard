"""Agent 4 — fade 戦略 + skew / maxDD / worst-day (SPEC §4)."""
import pytest

hr = pytest.importorskip("backtest.h1_robustness", reason="Agent 1 未実装")


def _t(label_value, feature=1.0, ts="2024-01-01T00:00:00"):
    """label_value = decimal return; feature = US prev return sign."""
    return {"ts": ts, "label_value": float(label_value), "feature": float(feature)}


def test_fade_inverts_direction():
    long_trades = [{"ts": "x", "net_pct": 0.10, "predicted_prob": 0.55,
                    "outcome01": 1}]
    # fade 元データは label/feature を保持しないと作れない → build_fade_trades は
    # label/feature リストを期待する.
    raw = [{"ts": "x", "label_value": 0.001, "feature": +1.0}]
    fade = hr.build_fade_trades(raw)
    # 元 net_pct = +0.10 (long), fade = +0.001 * -1 * 100 = -0.10
    assert len(fade) == 1
    assert abs(fade[0]["net_pct"] - (-0.10)) < 1e-9


def test_skew_negative_for_small_gains_rare_big_loss():
    # 95 件の +0.01 と 5 件の -2.0 → 強い負スキュー
    values = [0.01] * 95 + [-2.0] * 5
    s = hr.compute_skew(values)
    assert s is not None and s < -1.0, f"strong negative skew expected, got {s}"


def test_skew_near_zero_for_symmetric():
    values = [-1.0, 0.0, 1.0, -0.5, 0.5] * 40
    s = hr.compute_skew(values)
    assert abs(s) < 0.3, f"symmetric data → near-zero skew, got {s}"


def test_max_dd_from_realized():
    realized = [+0.10, +0.10, -0.50, +0.05]
    mdd = hr.max_dd_from_pct(realized)
    # eq: 1, 1.001, 1.002, 0.997..., 0.997.. -> peak 1.002, trough 0.997, dd ~ -0.5%
    assert mdd is not None and mdd <= -0.4 and mdd >= -0.6


def test_worst_day_loss_returns_min_realized():
    realized = [+0.10, -3.5, +0.20, -0.05]
    assert hr.worst_day_loss(realized) == -3.5


def test_fade_summary_struct():
    raw = [{"ts": f"2024-01-{d:02d}", "label_value": (0.005 if d % 3 else -0.03),
            "feature": 1.0} for d in range(1, 20)]
    s = hr.fade_summary(raw)
    for k in ("n", "hit_rate", "mean_net_pct", "skew",
              "max_dd_pct", "worst_day_loss_pct"):
        assert k in s


def test_fade_verdict_pass_when_skew_ok_and_worst_day_modest():
    # 対称的な分布 → skew ~ 0, worst-day -0.5%
    raw = [{"ts": f"x{i}", "label_value": (-1)**i * 0.005, "feature": 1.0}
           for i in range(100)]
    summary = hr.fade_summary(raw)
    v = hr.fade_verdict(summary)
    assert v["pass"] is True


def test_fade_verdict_fail_when_strong_negative_skew():
    # fade = label * -1 * 100. 小さい正 label が多くて稀に大きい正 label が来ると
    # fade では「小さい負が多く稀に大きい負」になり強い負スキュー.
    raw = [{"ts": "x", "label_value": 0.001, "feature": 1.0}] * 95 + \
          [{"ts": "x", "label_value": 0.05, "feature": 1.0}] * 5    # label が稀に +5%
    summary = hr.fade_summary(raw)
    v = hr.fade_verdict(summary)
    assert v["pass"] is False
