"""H1 特徴量 look-ahead 物理保証 (SPEC_H1 §0, §1.1).

最重要テスト: バー T (JST) 時点の特徴量は JP date T より厳密に過去の US 終値のみ.
US バーで ts >= T_jp を全削除 / 改竄しても、生成される features dict が **不変**.
"""
import copy
import pytest

h1 = pytest.importorskip(
    "backtest.h1",
    reason="Agent A/B 未実装。backtest/h1.py を作ると緑になる。",
)


def _us_bar(ts, close):
    return {"ts": ts, "open": close, "high": close * 1.01,
            "low": close * 0.99, "close": close, "volume": 0.0}


def _jp_bar(ts, open_=1000.0, close=1010.0):
    return {"ts": ts, "open": open_, "high": close * 1.01,
            "low": open_ * 0.99, "close": close, "volume": 0.0}


# ── 単純なペアリング ────────────────────────────
def test_jp_monday_uses_us_friday_close():
    us = [
        _us_bar("2024-01-03T00:00:00", 100.0),
        _us_bar("2024-01-04T00:00:00", 101.0),
        _us_bar("2024-01-05T00:00:00", 103.0),     # +1.98%
    ]
    jp = [_jp_bar("2024-01-08T00:00:00")]   # JP Monday
    feats = h1.build_features(jp, h1.build_us_close_returns(us))
    assert "2024-01-08" in feats
    assert abs(feats["2024-01-08"] - (103.0 - 101.0) / 101.0) < 1e-9


def test_jp_uses_strict_less_than_us_date():
    """同日 US (US date == JP date) は使ってはいけない (US close は JST 翌朝確定)."""
    us = [
        _us_bar("2024-01-04T00:00:00", 100.0),
        _us_bar("2024-01-05T00:00:00", 102.0),
        _us_bar("2024-01-08T00:00:00", 110.0),     # 同日 US — 触ってはいけない
    ]
    jp = [_jp_bar("2024-01-08T00:00:00")]
    feats = h1.build_features(jp, h1.build_us_close_returns(us))
    # 期待: 2024-01-05 の return = (102-100)/100 = 0.02
    assert abs(feats["2024-01-08"] - 0.02) < 1e-9, (
        f"must use 2024-01-05 (strict <), got feature={feats.get('2024-01-08')}"
    )


# ── look-ahead 物理保証 ────────────────────────
def test_mutating_future_us_bars_does_not_change_features():
    us_orig = [
        _us_bar("2024-01-03T00:00:00", 100.0),
        _us_bar("2024-01-04T00:00:00", 101.0),
        _us_bar("2024-01-05T00:00:00", 103.0),
        _us_bar("2024-01-08T00:00:00", 110.0),     # JP date と同じ — 未来扱い
        _us_bar("2024-01-09T00:00:00", 115.0),     # JP date より未来
        _us_bar("2024-01-10T00:00:00", 120.0),
    ]
    jp = [_jp_bar("2024-01-08T00:00:00")]
    feats_orig = h1.build_features(jp, h1.build_us_close_returns(us_orig))

    # US の同日以降を改竄 / 削除しても features が変わらない
    us_mutated = copy.deepcopy(us_orig)
    for b in us_mutated:
        if b["ts"] >= "2024-01-08":
            b["close"] = 99999.0
            b["open"] = 99999.0
    feats_mut = h1.build_features(jp, h1.build_us_close_returns(us_mutated))
    assert feats_orig == feats_mut, (
        f"mutating same-day or future US bars must NOT change features:\n"
        f"  orig={feats_orig}\n  mut ={feats_mut}"
    )

    # US の同日以降を全削除しても features が変わらない
    us_truncated = [b for b in us_orig if b["ts"] < "2024-01-08"]
    feats_trunc = h1.build_features(jp, h1.build_us_close_returns(us_truncated))
    assert feats_orig == feats_trunc, "truncating future US bars must not change features"


def test_no_us_data_before_jp_date_yields_no_feature():
    us = [_us_bar("2024-01-10T00:00:00", 100.0)]   # JP より未来しかない
    jp = [_jp_bar("2024-01-08T00:00:00")]
    feats = h1.build_features(jp, h1.build_us_close_returns(us))
    assert "2024-01-08" not in feats


def test_build_us_close_returns_first_day_has_no_return():
    us = [
        _us_bar("2024-01-03T00:00:00", 100.0),
        _us_bar("2024-01-04T00:00:00", 101.0),
        _us_bar("2024-01-05T00:00:00", 103.0),
    ]
    r = h1.build_us_close_returns(us)
    assert "2024-01-03" not in r          # 最初は不可能
    assert "2024-01-04" in r and abs(r["2024-01-04"] - 0.01) < 1e-9
    assert "2024-01-05" in r and abs(r["2024-01-05"] - (103.0 - 101.0) / 101.0) < 1e-9


# ── predictor が US バーを直接触らないことの構造保証 ─
def test_predictor_signature_does_not_accept_us_bars():
    """`predict_h1(features, jp_date)` は features dict のみ受け取る — US 生バー型なし.

    型の二重定義になるが、 H1 では「特徴量は pre-compute」を方針として固める。
    """
    import inspect
    sig = inspect.signature(h1.predict)
    params = list(sig.parameters)
    # 1st arg = features dict, 2nd = jp_date.
    assert "features" in params[0] or params[0] == "features"
    assert "jp_date" in params or params[1].startswith("jp_date") or params[1] == "jp_date"
