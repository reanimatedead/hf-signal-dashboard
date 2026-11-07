"""判定の記録帳（calc.live・history）。Mac mini のローカルだけ。テストは本物のフォルダに書かない。"""

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from screener import daily, history
from screener.calc import live


def _days(n, end="2026-11-05"):
    return [d.date().isoformat() for d in pd.bdate_range(end=end, periods=n)]


def test_forward_return_and_live_stats():
    ds = _days(25)
    closes = [100.0 + i for i in range(25)]
    assert live.forward_return(ds, closes, ds[0]) == (120.0 / 100.0 - 1) * 100
    assert live.forward_return(ds, closes, ds[10]) is None  # まだ 20 本たっていない
    recs = [
        {"d": ds[0], "m": "jp", "s": "A", "sig": "buy", "c2": "buy_cci200", "t": 5},
        {"d": ds[1], "m": "jp", "s": "A", "sig": "neutral", "c2": None, "t": 1},
        {"d": ds[20], "m": "jp", "s": "A", "sig": "neutral", "c2": None, "t": 1},
    ]
    out = live.live_stats(recs, lambda m, s: (ds, closes))
    assert out["records"] == 3 and out["matured"] == 2 and out["start"] == ds[0]
    g = out["markets"]["jp"]
    assert g["tiers"]["tier5"]["n"] == 1 and g["tiers"]["tier5"]["median"] == 20.0
    assert g["signals"]["buy"]["n"] == 1 and g["cci200"]["buy_cci200"]["n"] == 1 and g["base"]["n"] == 2
    assert g["tiers"]["tier3"] == {"n": 0}


def _doc(asof, px=100.0):
    jp = {
        "code": "7203",
        "company_name": "架空自動車",
        "chart_signal": "buy",
        "cci200_signal": "buy_cci200",
        "score": 44.0,
        "score_tier": 5,
        "price": px,
        "next_earnings": asof,
    }
    us = {
        "ticker": "ZZZZ",
        "name": "Fake Corp",
        "chart_signal": "neutral",
        "score": 26.0,
        "score_tier": 4,
        "price": px * 2,
    }
    return {"asof": asof, "jp": [jp], "us": [us], "etf": [], "verify": {}}


def test_history_append_dedupes_and_live(cfg):
    ds = _days(22)
    for i, d in enumerate(ds):
        history.append(cfg, _doc(d, 100.0 + i))
    p = history.append(cfg, _doc(ds[-1], 200.0))  # 同じ日をもう一度 → 置き換え
    df = pd.read_parquet(p)
    assert len(df) == 2 * len(ds) and set(df.columns) == set(history.COLUMNS)
    assert float(df[(df.d == ds[-1]) & (df.m == "jp")].px.iloc[0]) == 200.0
    assert str(p).startswith(str(cfg.data_dir)) and not any(cfg.repo_dir.rglob("*.parquet"))
    lv = history.live_summary(cfg)
    assert lv["matured"] == 4 and lv["markets"]["jp"]["tiers"]["tier5"]["n"] == 2


def test_live_uses_daily_bars_not_ledger_gaps(cfg):
    """記録の無い日があっても 20 営業日後がずれない（11/6・7 のように daily が止まった日があっても）。"""
    ds = _days(40)
    closes = np.array([100.0 + i for i in range(40)])
    for d in ds[::2]:  # 1 日おきにしか記録がない
        history.append(cfg, _doc(d, 1.0))
    lv = history.live_summary(cfg, {"jp": {"7203": ({"c": closes}, ds)}, "us": {}, "etf": {}})
    # 記録 20 件のうち、日足で 20 本あとがあるのは最初の 10 件。値は日足の終値（記録帳の px = 1.0 ではない）
    t5 = lv["markets"]["jp"]["tiers"]["tier5"]
    assert t5["n"] == 10 and t5["median"] > 0
    assert lv["start"] == ds[0] and lv["markets"]["us"]["tiers"]["tier4"]["n"] == 0  # 記録帳だけでは 20 本たっていない


def test_split_in_ledger_does_not_show_as_a_crash(cfg):
    ds = _days(25)
    for i, d in enumerate(ds):
        history.append(cfg, _doc(d, 1000.0 if i < 10 else 500.0))  # 記録帳の終値は分割で半分
    adj = {"c": np.full(25, 500.0)}
    lv = history.live_summary(cfg, {"jp": {"7203": (adj, ds)}})
    assert lv["markets"]["jp"]["tiers"]["tier5"]["median"] == 0.0


def test_first_day_has_start_and_no_matured(cfg):
    history.append(cfg, _doc("2026-11-06"))
    lv = history.live_summary(cfg)
    assert lv["start"] == "2026-11-06" and lv["records"] == 2 and lv["matured"] == 0


def test_daily_pipeline_writes_history_and_live(cfg):
    from tests.screener.test_daily import fake_get

    daily.pipeline(cfg, dt.date(2026, 10, 30), get=fake_get(cfg=cfg), us_update=lambda c, d: None)
    assert list((cfg.data_dir / "history").glob("*.parquet"))
    v = json.loads((cfg.out_dir / "verify_local.json").read_text(encoding="utf-8"))
    assert v["live"]["records"] > 0 and v["live"]["start"]
    assert not any(cfg.repo_dir.rglob("*"))


def test_history_failure_does_not_stop_daily(cfg, monkeypatch, capsys):
    from tests.screener.test_daily import fake_get

    def boom(*a):
        raise OSError("disk full")

    monkeypatch.setattr(history, "append", boom)
    daily.pipeline(cfg, dt.date(2026, 10, 30), get=fake_get(cfg=cfg), us_update=lambda c, d: None)
    assert "history: 失敗 OSError" in capsys.readouterr().out and (cfg.out_dir / "today.html").exists()


def test_tests_cannot_touch_the_real_history_folder():
    """どのテストも本物の ~/screener-data/history に書かない（conftest の見張り）。"""
    from screener.config import Config

    real = Config(data_dir=Path.home() / "screener-data", repo_dir=Path("/x"))
    with pytest.raises(AssertionError, match="本物"):
        history.hist_dir(real)
