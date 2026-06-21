"""Agent 5 — e2e: 仮想 bars で 5 仮説 × 4 ゲート + DSR/PBO + 判定 + 改竄ログ (SPEC_LOOP §3-§7)."""
import math
import random
import pytest

pytest.importorskip("loop.runner", reason="Agent 2 未実装")

from loop import runner


def _walk(n=500, seed=0, start_y=2020):
    rng = random.Random(seed)
    px = [100.0]
    for _ in range(n - 1):
        px.append(max(1.0, px[-1] * math.exp(0.0005 * rng.gauss(0, 1))))
    # Daily bars Mon-Fri-ish; just sequential calendar
    import datetime
    bars = []
    d = datetime.date(start_y, 1, 1)
    for i, p in enumerate(px):
        bars.append({"ts": (d + datetime.timedelta(days=i)).isoformat() + "T00:00:00",
                     "open": p, "high": p * 1.005, "low": p * 0.995,
                     "close": p, "volume": 0.0})
    return bars


def test_run_loop_emits_full_report_structure():
    bars = _walk(n=800, seed=7)
    res = runner.run_loop(bars_by_symbol={"^N225": bars, "^GSPC": bars},
                          holdout_start="2024-06-21",
                          bootstrap_runs=30)
    for k in ("trials", "frontier", "verdict", "n_hypotheses", "note", "as_of_utc"):
        assert k in res, f"missing {k}"
    assert res["n_hypotheses"] == 5
    assert len(res["trials"]) == 5
    for t in res["trials"]:
        for f in ("name", "n_trades", "hit_rate", "cost", "outlier",
                  "subperiod", "fade", "sr_raw", "dsr",
                  "pbo_sign_consistent", "passed_4_gates", "verdict"):
            assert f in t, f"{t['name']}: missing {f}"


def test_run_loop_writes_immutable_chain_log(tmp_path, monkeypatch):
    from loop import log as loop_log
    monkeypatch.setattr(loop_log, "TRIALS_LOG_PATH",
                         tmp_path / "loop_trials.jsonl", raising=True)
    bars = _walk(n=400, seed=1)
    runner.run_loop(bars_by_symbol={"^N225": bars},
                    holdout_start="2024-06-21",
                    bootstrap_runs=20)
    p = tmp_path / "loop_trials.jsonl"
    assert p.exists()
    lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 5, f"5 trials expected, got {len(lines)}"
    # ハッシュチェーン verify
    ok, broken_at, reason = loop_log.verify(p)
    assert ok, f"chain broken at {broken_at}: {reason}"


def test_verdict_string_one_of_two_values():
    bars = _walk(n=600, seed=3)
    res = runner.run_loop(bars_by_symbol={"^N225": bars},
                          holdout_start="2024-06-21",
                          bootstrap_runs=20)
    v = res["verdict"]
    assert isinstance(v, str)
    assert (v.startswith("transfer-candidate-survived")
            or v == "empty-set under current gate → 指数転用は防御止まり / 転用Completion-B")


def test_frontier_has_hit_skew_pairs():
    bars = _walk(n=800, seed=11)
    res = runner.run_loop(bars_by_symbol={"^N225": bars},
                          holdout_start="2024-06-21",
                          bootstrap_runs=20)
    f = res["frontier"]
    assert isinstance(f, list) and len(f) == 5
    for row in f:
        for k in ("name", "hit_rate", "skew"):
            assert k in row


def test_universe_check_rejects_individual_stock_input():
    """ALLOWED_SYMBOLS に無い銘柄を bars_by_symbol で渡すと拒否される."""
    bars = _walk(n=200, seed=2)
    with pytest.raises(ValueError):
        runner.run_loop(bars_by_symbol={"AAPL": bars},
                        holdout_start="2024-06-21",
                        bootstrap_runs=10)
