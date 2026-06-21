"""H1 e2e: 仮想 JP/US データで run_h1() が 2 segment × 3 labels + sanity を返す (SPEC_H1 §3)."""
import datetime
import math
import random
import pytest

h1 = pytest.importorskip("backtest.h1", reason="Agent A/B 未実装")


def _gen_us(n=500, seed=0):
    """US は対数ランダムウォーク (close のみ)."""
    rng = random.Random(seed)
    px = [100.0]
    for _ in range(n - 1):
        px.append(max(1.0, px[-1] * math.exp(0.0008 * rng.gauss(0, 1))))
    bars = []
    start = datetime.date(2018, 1, 2)
    for i, p in enumerate(px):
        d = start + datetime.timedelta(days=i)
        # skip weekends roughly: keep all (simpler test)
        bars.append({"ts": d.isoformat() + "T00:00:00",
                     "open": p, "high": p * 1.005, "low": p * 0.995,
                     "close": p, "volume": 0.0})
    return bars


def _gen_jp_aligned_with_us(us_bars, seed=1, spillover=0.5):
    """JP open = prev_close * (1 + spillover * us_prev_return) + noise.
       JP close = JP open + intraday noise (ほぼ無相関)."""
    rng = random.Random(seed)
    # Build US prev_return map by date.
    us_close_prev = None
    us_returns_by_date = {}
    for b in us_bars:
        if us_close_prev is not None:
            us_returns_by_date[b["ts"][:10]] = (b["close"] - us_close_prev) / us_close_prev
        us_close_prev = b["close"]
    # JP bars are dated +1 day relative to US (US date T-1 affects JP date T)
    jp_bars = []
    prev_close = 1000.0
    sorted_us_dates = sorted(us_returns_by_date.keys())
    for i in range(1, len(us_bars)):
        # JP date = US date + 1 (deliberate ordering for the test)
        us_date = us_bars[i - 1]["ts"][:10]
        jp_date = (datetime.date.fromisoformat(us_date) + datetime.timedelta(days=1)).isoformat()
        us_r = us_returns_by_date.get(us_date, 0.0)
        gap = us_r * spillover + 0.002 * rng.gauss(0, 1)
        open_ = prev_close * (1 + gap)
        intraday = 0.005 * rng.gauss(0, 1)
        close = open_ * (1 + intraday)
        jp_bars.append({"ts": jp_date + "T00:00:00",
                        "open": open_, "high": max(open_, close) * 1.005,
                        "low": min(open_, close) * 0.995, "close": close, "volume": 0.0})
        prev_close = close
    return jp_bars


def test_run_h1_returns_segments_and_labels():
    us = _gen_us(n=800, seed=0)
    jp = _gen_jp_aligned_with_us(us, seed=1, spillover=0.5)
    res = h1.run_h1(jp_bars=jp, us_bars=us,
                    segments=(("pre_split", None, jp[400]["ts"][:10]),
                              ("post_split", jp[400]["ts"][:10], None)),
                    bootstrap_runs=100, n_min=30)
    assert res["hypothesis"] == "h1"
    seg_names = [s["name"] for s in res["segments"]]
    assert seg_names == ["pre_split", "post_split"]
    for seg in res["segments"]:
        assert "labels" in seg and "sanity" in seg
        for lab in ("overnight", "open_to_close", "next_week"):
            assert lab in seg["labels"]
            m = seg["labels"][lab]
            assert "n" in m and "judge" in m
            assert m["judge"] in ("edge", "no-edge", "inconclusive", "insufficient")


def test_sanity_overnight_spillover_recovered():
    """spillover=0.7 で生成 → overnight サニティは PASS (正・有意), open_to_close は ほぼ無相関."""
    us = _gen_us(n=1500, seed=42)
    jp = _gen_jp_aligned_with_us(us, seed=43, spillover=0.7)
    res = h1.run_h1(jp_bars=jp, us_bars=us,
                    segments=(("all", None, None),),
                    bootstrap_runs=50, n_min=30)
    sanity = res["segments"][0]["sanity"]
    on = sanity["overnight"]
    assert on["pearson"] is not None and on["pearson"] > 0, (
        f"overnight pearson must be positive when spillover>0: {on}"
    )
    assert on["pass"] is True, f"overnight sanity must PASS for spillover=0.7: {on}"
    otc = sanity["open_to_close"]
    # intraday は意図的に無相関にしてあるので |r| < 0.2 程度
    assert abs(otc["pearson"]) < 0.20, f"open_to_close must be near zero: {otc}"


def test_sanity_fails_when_data_misaligned():
    """わざと US と JP を 同日揃え (= 同時刻を使うバグ) にしたデータでは
    overnight サニティが FAIL する (時系列が壊れていれば信号は出ない)."""
    us = _gen_us(n=800, seed=7)
    # 「同日揃え」: us[i].ts == jp[i].ts として spillover=0 にする (相関は 0 になる)
    jp = []
    prev_close = 1000.0
    rng = random.Random(8)
    for b in us:
        gap = 0.005 * rng.gauss(0, 1)
        open_ = prev_close * (1 + gap)
        intraday = 0.005 * rng.gauss(0, 1)
        close = open_ * (1 + intraday)
        jp.append({"ts": b["ts"], "open": open_, "high": max(open_, close) * 1.005,
                    "low": min(open_, close) * 0.995, "close": close, "volume": 0.0})
        prev_close = close
    res = h1.run_h1(jp_bars=jp, us_bars=us, segments=(("all", None, None),),
                    bootstrap_runs=50, n_min=30)
    on = res["segments"][0]["sanity"]["overnight"]
    # 相関が 0 付近 → pass は False (t が小さい)
    assert on["pass"] is False, f"misaligned data must FAIL overnight sanity: {on}"


def test_run_h1_uses_strict_less_than_us_date():
    """run_h1 がそのまま build_features を呼んでいる: 同日 US は触らない (look-ahead 防止)."""
    us = _gen_us(n=200, seed=11)
    jp = _gen_jp_aligned_with_us(us, seed=12, spillover=0.5)
    # JP date と同じ US バーを「破壊」して走らせる → 結果が変わらないこと
    us_broken = [dict(b) for b in us]
    jp_dates = {b["ts"][:10] for b in jp}
    for b in us_broken:
        if b["ts"][:10] in jp_dates:
            b["close"] = 1e9
    res_a = h1.run_h1(jp_bars=jp, us_bars=us,
                      segments=(("all", None, None),), bootstrap_runs=30, n_min=30)
    res_b = h1.run_h1(jp_bars=jp, us_bars=us_broken,
                      segments=(("all", None, None),), bootstrap_runs=30, n_min=30)
    for lab in ("overnight", "open_to_close", "next_week"):
        a = res_a["segments"][0]["labels"][lab]
        b = res_b["segments"][0]["labels"][lab]
        assert a["n"] == b["n"], (
            f"mutating same-day US must not change H1 results: "
            f"{lab}: orig n={a['n']}, mut n={b['n']}"
        )
