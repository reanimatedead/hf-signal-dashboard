"""screener.alerts: CCI ±200 の一覧・Mac mini の通知（ntfy には送らない）・検証（日本株/米国株/FX/仮想通貨）。"""

import datetime as dt
import json
from pathlib import Path

import numpy as np

from screener import alerts, daily, fxcrypto, local_report
from screener.calc import assets
from screener.japan import signals

DAYS = [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(140)]


def _xs(series, days=DAYS):
    """{code: (S, L)} → Xs。全銘柄同じ日付。"""
    return {
        c: ({"cciS": np.array(s, float), "cciL": np.array(lo, float), "c": np.ones(len(s))}, days)
        for c, (s, lo) in series.items()
    }


def _hist(today_s, today_l):
    """139日は平穏（−100）、最終日だけ指定の値。"""
    return [-100.0] * 139 + [today_s], [-100.0] * 139 + [today_l]


def _rows(xs, cci=(-250, -230)):
    return {c: {"name": f"名{c}", "cci48": cci[0], "cci288": cci[1]} for c in xs}


def _calm(n, prefix):
    return {f"{prefix}{i:04d}": _hist(-100, -100) for i in range(n)}


def test_build_all_markets_with_watchlist_and_no_up_notify():
    # 銘柄数が少なすぎると 1.5% の線が 1 件未満になるので、平穏な銘柄で埋める（日本株 200・米国株 100）
    jx = _xs({"1001": _hist(-250, -230), "1002": _hist(-250, -100), "1003": _hist(250, 220), **_calm(197, "9")})
    ux = _xs({"AAA": _hist(-210, -100), "BBB": _hist(-250, -250), **_calm(98, "Z")})
    fx = _xs({"USDJPY=X": _hist(-260, -240)})
    cr = _xs({"BTC-USD": _hist(-100, -100)})
    a = alerts.build(
        {"jp": (jx, _rows(jx)), "us": (ux, _rows(ux)), "fx": (fx, _rows(fx)), "crypto": (cr, _rows(cr))},
        ["1002", "aaa"],
    )
    m = a["markets"]
    assert [r["code"] for r in m["jp"]["both_down"]] == ["1001"] and m["jp"]["universe"] == 200
    assert a["spike"] is False  # 日本株 1 件 < 3 件（200 の 1.5%）・米国株 1 件 < 1.5 件
    assert [r["code"] for r in m["us"]["both_down"]] == ["BBB"]
    assert [r["code"] for r in m["fx"]["both_down"]] == ["USDJPY=X"] and m["fx"]["verified"] is False
    assert m["fx"]["spike_line"] is None and m["crypto"]["both_down_count"] == 0  # FX・仮想通貨は一斉に割れを出さない
    assert sorted(r["code"] for r in a["watch_hits"]) == ["1002", "AAA"]
    assert {r["code"] for r in a["items"]} == {"1001", "1002", "1003", "AAA", "BBB", "USDJPY=X"}  # +200 は一覧に残る
    title, body = alerts.message(a)
    assert title.startswith("CCI −200 割れ")
    # 2026-11: +200 は「売り目安（CCI +200）」として両方割れの文の後ろに足す（両方割れの文には入らない）
    down, _, sell = body.partition("売り目安（CCI +200）")
    assert "1003" not in down and "1003" in sell and "空売りの根拠ではない" in body
    assert "日本株 両方割れ 1 件: 1001 名1001" in body and "米国株 両方割れ 1 件: BBB" in body
    assert "FX（未検証）1 件: USDJPY=X 名USDJPY=X" in body and "ウォッチ 2 件" in body
    assert "生き残りの偏り" in m["us"]["note"]


def test_spike_needs_1_5pct_of_the_market():
    # 日本株 3,600 銘柄で 54 件までは「一斉に割れ」にしない。55 件で強調
    def jp(k):
        s = {f"{i:04d}": _hist(-250, -250) for i in range(k)}
        s.update({f"9{i:04d}": _hist(-100, -100) for i in range(3600 - k)})
        return _xs(s)

    jx54, jx55 = jp(54), jp(55)
    a54 = alerts.build({"jp": (jx54, _rows(jx54))})
    a55 = alerts.build({"jp": (jx55, _rows(jx55))})
    assert a54["markets"]["jp"]["spike_line"] == 54.0 and a54["spike"] is False
    assert a55["spike"] is True
    title, body = alerts.message(a55)
    assert (
        title == "⚠ 一斉に割れ（暴落の可能性）: 日本株"
        and "一斉に割れ 55 件（線 54 件超え）" in body
        and "ほか50" in body
    )
    # 米国株 520 銘柄 → 線は 7.8 件。8 件で強調
    us = {f"U{i:03d}": _hist(-250, -250) for i in range(8)} | {f"V{i:03d}": _hist(-100, -100) for i in range(512)}
    ux = _xs(us)
    assert alerts.build({"us": (ux, _rows(ux))})["markets"]["us"]["spike"] is True


def test_nothing_to_notify():
    jx = _xs(_calm(3, "1"))
    a = alerts.build({"jp": (jx, _rows(jx))})
    assert alerts.message(a) is None
    assert alerts.notify(a, Path("/tmp/x.html"), runner=None, platform="darwin") == "none"
    assert alerts.shown_path(Path("/opt/x.html"), Path("/home/u")) == "/opt/x.html"


class R:
    def __init__(self, rc=0):
        self.returncode = rc


def _one():
    jx = _xs({"1001": _hist(-250, -230)})
    return alerts.build({"jp": (jx, {"1001": {"name": '会社"A"', "cci48": -250, "cci288": -230}})})


def test_notify_defaults_to_osascript_and_ends_with_list_path(tmp_path):
    a = _one()
    page = tmp_path / "screener-data" / "out" / f"cci_alerts_{a['asof']}.html"
    calls = []

    def run(args, **kw):
        calls.append(args)
        return R()

    how = alerts.notify(a, page, runner=run, which=lambda n: "/opt/tn", platform="darwin", home=tmp_path)
    assert how == "osascript" and calls[-1][0] == "osascript"  # terminal-notifier があっても既定では使わない
    script = calls[-1][2]
    assert '\\"A\\"' in script  # 引用符は逃がす
    assert script.split(" with title ")[0].endswith(f'一覧: ~/screener-data/out/cci_alerts_{a["asof"]}.html"')
    assert alerts.notify(a, page, runner=run, which=lambda n: None, platform="linux") == "not_mac"


def test_terminal_notifier_only_when_chosen_and_falls_back_on_error(tmp_path):
    a = _one()
    page = tmp_path / "cci.html"
    calls = []

    def ok(args, **kw):
        calls.append(args)
        return R()

    kw = {"which": lambda n: "/opt/tn", "platform": "darwin", "prefer": "terminal-notifier"}
    assert alerts.notify(a, page, runner=ok, **kw) == "terminal-notifier"

    def tn_fails(args, **kw):  # macOS 26: 実行時のエラー（終了コード ≠ 0 / 例外）→ osascript に切り替え
        calls.append(args)
        return R(1) if args[0] == "/opt/tn" else R()

    calls.clear()
    assert alerts.notify(a, page, runner=tn_fails, **kw) == "osascript"
    assert [c[0] for c in calls] == ["/opt/tn", "osascript"]

    def tn_raises(args, **kw):
        if args[0] == "/opt/tn":
            raise OSError("not permitted")
        return R()

    assert alerts.notify(a, page, runner=tn_raises, **kw) == "osascript"

    def all_fail(*a, **k):
        raise OSError("x")

    assert alerts.notify(a, page, runner=all_fail, **kw) == "error"  # 本処理は止めない


def _chart(n=420, last=-1.0):
    """Yahoo chart の形（n 日・最終日に急落して CCI が割れる）。"""
    base = dt.datetime(2025, 1, 1, tzinfo=dt.UTC).timestamp()
    c = [100 + np.sin(i / 9) for i in range(n - 1)] + [100 + last * 30]
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [int(base + 86400 * i) for i in range(n)],
                    "indicators": {"quote": [{"high": c, "low": c, "close": c}], "adjclose": [{"adjclose": c}]},
                }
            ]
        }
    }


def test_fxcrypto_uses_the_public_list_and_keeps_previous_file_on_error(cfg):
    src = Path(__file__).resolve().parents[2] / "fetch_signals.py"
    text = src.read_text(encoding="utf-8")
    assert "FX_PAIRS = dict(assets.FX_PAIRS)" in text and "CRYPTO = list(assets.CRYPTO)" in text  # 一覧は1か所
    assert len(assets.FX_PAIRS) == 18 and len(assets.CRYPTO) == 4
    d = fxcrypto.px_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    (d / "USDJPY=X.json").write_text(json.dumps(_chart()))
    urls = []

    def getter(u, *a, **k):
        urls.append(u)
        raise OSError("down")

    res = fxcrypto.fetch(cfg, getter=getter, sleep=lambda s: None)
    assert res == {"fx": (0, 18), "crypto": (0, 4)}  # 例外にしない
    assert json.loads((d / "USDJPY=X.json").read_text()) == _chart()  # 前回のまま
    assert any("USDJPY%3DX" in u or "USDJPY=X" in u for u in urls)
    rows, xs = fxcrypto.load(cfg, "fx")
    assert set(rows) == {"USDJPY=X"} and rows["USDJPY=X"]["name"] == "USD/JPY" and len(xs["USDJPY=X"][1]) == 420


def test_daily_run_writes_list_verify_per_market_and_notifies_once(cfg, monkeypatch):
    d = fxcrypto.px_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    (d / "USDJPY=X.json").write_text(json.dumps(_chart()))
    (d / "BTC-USD.json").write_text(json.dumps(_chart()))
    sent = []
    monkeypatch.setattr(daily, "mac_notify", lambda a, p, **kw: sent.append((a["asof"], p, kw)))
    doc = signals.run(cfg)
    a = doc["cci_alerts"]
    assert set(a["markets"]) == {"jp", "us", "fx", "crypto"} and a["markets"]["fx"]["universe"] == 1
    v = doc["verify"]["cci_both_down"]
    assert set(v) == {"jp", "us", "fx", "crypto"}
    for m in v.values():
        assert set(m["full"]) == {"both_down", "both_up", "base"} and "n" in m["full"]["both_down"]  # 件数は必ず出す
        assert set(m["excluding_spike_days"]) == {"both_down", "base"} and "both_down" in m["by_year"]
    assert v["jp"]["spike_rule"] == {"quantile": 0.99, "lookback_days": 245, "min_frac_of_universe": 0.015}
    assert v["fx"]["spike_rule"] is None and v["fx"]["verified"] is False and v["crypto"]["note"] == "未検証"
    assert "生き残りの偏り" in v["us"]["note"]
    local_report.write(cfg, doc)
    p = local_report.alerts_html(cfg, doc)
    page = p.read_text()
    assert p.exists() and (cfg.out_dir / "cci_alerts.html").exists() and "<script" not in page
    assert "仮想通貨" in page and "未検証" in page
    assert "cci_both_down" in json.loads((cfg.out_dir / "verify_local.json").read_text())
    from .test_daily import fake_get

    daily.pipeline(cfg, dt.date(2026, 10, 30), get=fake_get(cfg=cfg), us_update=lambda c, d: None)
    assert len(sent) == 1 and sent[0][1].name.startswith("cci_alerts_") and sent[0][2] == {"prefer": "osascript"}
