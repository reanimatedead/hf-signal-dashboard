"""Agent 3 — since_2023 サブ期間 (年単位) 安定性 (SPEC §3)."""
import pytest

hr = pytest.importorskip("backtest.h1_robustness", reason="Agent 1 未実装")


def _t(ts, net_pct):
    return {"ts": ts, "net_pct": float(net_pct),
            "predicted_prob": 0.55, "outcome01": 1 if net_pct > 0 else 0}


def test_split_by_year_groups_correctly():
    trades = [_t("2023-03-01T00:00:00", 0.10),
              _t("2024-04-01T00:00:00", 0.20),
              _t("2025-05-01T00:00:00", -0.05),
              _t("2026-06-01T00:00:00", 0.30)]
    groups = hr.split_by_year(trades)
    assert sorted(groups.keys()) == ["2023", "2024", "2025", "2026"]
    assert len(groups["2023"]) == 1
    assert len(groups["2024"]) == 1


def test_subperiod_table_emits_per_year_means():
    trades = [_t(f"2023-{(m % 12) + 1:02d}-01T00:00:00", 0.05) for m in range(120)] + \
             [_t(f"2024-{(m % 12) + 1:02d}-01T00:00:00", -0.02) for m in range(80)]
    table = hr.subperiod_table(trades)
    years = {r["year"] for r in table}
    assert {"2023", "2024"}.issubset(years)
    for r in table:
        for k in ("year", "n", "mean_net_pct", "sum_net_pct"):
            assert k in r


def test_subperiod_verdict_pass_when_balanced_and_no_neg_year():
    # 4 期間で似たような mean、負期間なし → PASS
    trades = []
    for y in (2023, 2024, 2025, 2026):
        for _ in range(80):
            trades.append(_t(f"{y}-06-01T00:00:00", 0.10))
    table = hr.subperiod_table(trades)
    v = hr.subperiod_verdict(table)
    assert v["pass"] is True


def test_subperiod_verdict_fail_when_one_year_dominates():
    # 2024 だけが全体 EV の > 50% を占める
    trades = (
        [_t("2023-06-01T00:00:00", 0.0001)] * 50
        + [_t("2024-06-01T00:00:00", 10.0)] * 50
        + [_t("2025-06-01T00:00:00", 0.0001)] * 50
    )
    table = hr.subperiod_table(trades)
    v = hr.subperiod_verdict(table)
    assert v["pass"] is False
    assert v["reason"] and "dominat" in v["reason"].lower()


def test_subperiod_verdict_fail_when_any_year_negative():
    trades = (
        [_t("2023-06-01T00:00:00", 0.10)] * 80
        + [_t("2024-06-01T00:00:00", -0.05)] * 80
        + [_t("2025-06-01T00:00:00", 0.10)] * 80
    )
    table = hr.subperiod_table(trades)
    v = hr.subperiod_verdict(table)
    assert v["pass"] is False
