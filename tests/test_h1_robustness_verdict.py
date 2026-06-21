"""Agent 5 — 統合判定 (a)(b)(c)(d) → 2 値最終判定 (SPEC §5)."""
import pytest

hr = pytest.importorskip("backtest.h1_robustness", reason="Agent 1 未実装")


def test_overall_pass_when_all_four_pass():
    flags = {"cost": {"pass": True}, "outlier": {"pass": True},
             "subperiod": {"pass": True}, "fade": {"pass": True}}
    out = hr.combine_verdict(flags)
    assert out["overall"] == "Stage2-conditioners-justified"
    assert all(out["criteria"][k] for k in ("cost", "outlier", "subperiod", "fade"))


@pytest.mark.parametrize("failed", ["cost", "outlier", "subperiod", "fade"])
def test_overall_fail_when_any_single_fail(failed):
    flags = {"cost": {"pass": True}, "outlier": {"pass": True},
             "subperiod": {"pass": True}, "fade": {"pass": True}}
    flags[failed]["pass"] = False
    out = hr.combine_verdict(flags)
    assert out["overall"] == "raw-cross-asset-not-tradeable → Completion-B候補"
    assert out["criteria"][failed] is False


def test_run_robustness_e2e_emits_full_struct():
    # Real-data-shape: 200 trades since 2023 with mean ~0.08% (Phase 1.9 actual)
    trades = []
    for i in range(800):
        # 半分は +0.10, 半分は -0.05 → mean ~+0.025% (cost に弱い)
        ts = f"{2023 + (i // 240)}-0{1+(i%9)}-15T00:00:00"
        net = 0.10 if i % 2 == 0 else -0.05
        trades.append({"ts": ts, "net_pct": net, "predicted_prob": 0.55,
                       "outcome01": 1 if net > 0 else 0,
                       "label_value": net / 100.0, "feature": +1.0})
    res = hr.run_robustness(trades, bootstrap_runs=80, label="open_to_close",
                            segment="since_2023")
    for k in ("label", "segment", "n_trades", "ev_baseline", "cost", "outlier",
              "subperiod", "fade", "verdict", "note"):
        assert k in res
    assert res["verdict"]["overall"] in (
        "Stage2-conditioners-justified",
        "raw-cross-asset-not-tradeable → Completion-B候補",
    )
