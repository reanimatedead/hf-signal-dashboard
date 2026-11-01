"""fetch_signals の §21 配線をオフライン（架空の5銘柄）で確かめる:
株式行の chart_signal 等・charts.1d.series・docs/verify.json・米国行の magic_rank/f_score。
Yahoo / EDGAR には繋がない（_batched_2y_ohlc を差し替える）。"""
import json

import pytest

import fetch_signals as fs
from marketcalc import fund_us, ind
from tests._fake_market import TICKERS, facts, frame


@pytest.fixture
def markets(monkeypatch):
    frames = {t: frame(t) for t in TICKERS}
    frames.update({f"{i}001.T": frame(t) for i, t in enumerate(TICKERS, 1)})
    monkeypatch.setattr(fs, "_batched_2y_ohlc", lambda syms, **k: {s: frames.get(s) for s in syms})

    def rows(syms):
        return [fs.process_ticker(frames[s].tail(126), s, f"Fake {s}") for s in syms]
    return {"nikkei225": rows([f"{i}001.T" for i in range(1, 6)]), "dow30": rows(TICKERS[:2]),
            "nasdaq100": rows(TICKERS), "sp500": rows(TICKERS)}


def test_rows_get_chart_signal_fields_and_series(markets, tmp_path):
    collect = {}
    fs.attach_equity_charts(markets, collect=collect)
    for tab, rows in markets.items():
        for r in rows:
            if r["symbol"].startswith("^"):
                continue
            for k in fs.SIGNAL_FIELDS:
                assert k in r, (tab, r["symbol"], k)
            assert r["chart_signal"] in set(ind.LABELS.values()) | {ind.LONG_OVERSOLD_LABEL}
            s = r["charts"]["1d"]["series"]
            n = len(r["charts"]["1d"]["ohlc"])
            assert len(s["close"]) == n == len(s["cci48"]) == len(s["bb288"]["m3"])
            assert all(0 <= m["i"] < n for m in s["marks"])
            assert "index_map" not in s
    aaa = next(r for r in markets["nasdaq100"] if r["symbol"] == "AAA")
    assert aaa["chart_signal"] in ("強い買い", "買い")          # 架空 AAA は長期上向き→急落
    bbb = next(r for r in markets["nasdaq100"] if r["symbol"] == "BBB")
    assert bbb["chart_signal_code"] < 0                          # 架空 BBB は長期下向き→急騰
    assert set(collect) == {"nikkei225", "dow30", "nasdaq100", "sp500"}
    # 行の値は marketcalc.ind.summary と同じ（式を複製していない）
    _, h, l, c = fs._finite_hlc(frame("AAA"))
    sm = ind.summary(h, l, c)
    assert aaa["cci288"] == sm["cci288"] and aaa["bb48_z"] == sm["bb48_z"]

    # split 後: data.json 側には series を含む charts が残らず、charts/{tab}.json に入る
    payload = {"markets": markets}
    fs.split_chart_payload(payload, tmp_path)
    assert all("charts" not in r for rows in markets.values() for r in rows)
    store = json.loads((tmp_path / "charts" / "nasdaq100.json").read_text())
    assert "series" in store["AAA"]["1d"]

    # verify.json（同じフレームを再利用）
    vp = tmp_path / "verify.json"
    rec = fs.build_and_write_verify(collect, vp)
    assert rec["available"], rec
    v = json.loads(vp.read_text())
    assert set(v["markets"]) == {"nikkei225", "us"}
    assert v["markets"]["us"]["symbols"] == 5                    # Dow/NDX/S&P の重複は1回
    full = v["markets"]["us"]["full"]
    assert set(full["chart"]) == {"強い買い", "買い", "買い（長期の売られすぎ）", "売り", "強い売り"}
    assert {"BUY", "WATCH", "AVOID"} <= set(full["composite"])
    assert full["base"]["n"] > 0 and isinstance(v["weakened"], bool)
    assert v["as_of"] == "2026-07-15"


def test_signal_fields_none_when_too_few_bars():
    r = {"symbol": "X"}
    fs.attach_signal_fields(r, frame("AAA").tail(200), None)
    assert r["chart_signal"] is None and r["cci288"] is None and "chart_signal_note" in r


def test_composite_series_matches_process_ticker_on_last_day():
    df = frame("CCC")
    _, _, _, c = fs._finite_hlc(df)
    labels = fs.composite_label_series(c)
    assert len(labels) == len(c)
    assert set(labels) <= {"STRONG BUY", "BUY", "HOLD", "WATCH", "AVOID"}
    assert labels[-1] == fs.process_ticker(df, "CCC", "c")["signal"]


def test_attach_us_fundamentals_rank_over_union(tmp_path):
    rows = {}
    for t in TICKERS:
        fd = fund_us.fundamentals(facts(t)["facts"], "2025-12-31")
        rows[t] = {**fd, "fin": t == "EEE"}
    p = tmp_path / "us_fundamentals.json"
    p.write_text(json.dumps({"as_of": "2025-12-31", "rows": rows}))
    tab_a = [{"symbol": t, "price": 100.0} for t in TICKERS[:3]] + [{"symbol": "^NDX", "price": 1.0}]
    tab_b = [{"symbol": t, "price": 100.0} for t in TICKERS]
    rec = fs.attach_us_fundamentals((tab_a, tab_b), p)
    assert rec["with_fundamentals"] == 5 and rec["ranked"] == 4          # EEE は金融で除外
    ranks = sorted(r["magic_rank"] for r in tab_b if r["magic_rank"])
    assert ranks == [1, 2, 3, 4]
    assert next(r for r in tab_b if r["symbol"] == "EEE")["magic_rank"] is None
    a_in_a = next(r for r in tab_a if r["symbol"] == "AAA")
    a_in_b = next(r for r in tab_b if r["symbol"] == "AAA")
    assert a_in_a["magic_rank"] == a_in_b["magic_rank"] and a_in_a["f_score"] == rows["AAA"]["f_score"]
    assert "magic_rank" not in tab_a[-1]                                    # 指数行には付けない


def test_attach_us_fundamentals_without_file(tmp_path):
    tab = [{"symbol": "AAA", "price": 1.0}]
    rec = fs.attach_us_fundamentals((tab,), tmp_path / "none.json")
    assert rec["available"] is False and tab[0]["magic_rank"] is None and tab[0]["f_score"] is None
