"""screener.alerts: CCI ±200 の一覧・Mac mini の通知（ntfy には送らない）・検証。"""

import json
from pathlib import Path

import numpy as np

from screener import alerts, daily, local_report
from screener.japan import signals


def _xs(series, days):
    """{code: (S, L)} → Xs。全銘柄同じ日付。"""
    return {
        c: ({"cciS": np.array(s, float), "cciL": np.array(l, float), "c": np.ones(len(s))}, days)
        for c, (s, l) in series.items()
    }


DAYS = [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(140)]


def _hist(today_s, today_l):
    """139日は平穏（−100）、最終日だけ指定の値。"""
    return [-100.0] * 139 + [today_s], [-100.0] * 139 + [today_l]


def test_build_lists_jp_both_down_and_watchlist_but_not_notify_up():
    jx = _xs(
        {
            "1001": _hist(-250, -230),  # 両方割れ
            "1002": _hist(-250, -100),  # CCI48 だけ割れ（ウォッチに入っている）
            "1003": _hist(250, 220),  # +200 超え（一覧の列だけ）
            "1004": _hist(-100, -100),
        },
        DAYS,
    )
    ux = _xs({"AAA": _hist(-210, -100)}, DAYS)
    jp_rows = [{"code": c, "company_name": f"会社{c}", "market": "プライム", "cci48": -1, "cci288": -1} for c in jx]
    us_rows = [{"ticker": "AAA", "name": "Alpha", "cci48": -210, "cci288": -100}]
    a = alerts.build(jp_rows, jx, us_rows, ux, ["1002", "aaa"])
    # 過去1年がずっと 0 件だと線は 0 件。それでも 1 件では「一斉に割れ」にしない（5 件以上）
    assert a["asof"] == DAYS[-1] and a["both_down_count"] == 1 and a["spike_threshold"] == 0.0 and a["spike"] is False
    assert [r["code"] for r in a["both_down"]] == ["1001"]
    assert sorted(r["code"] for r in a["watch_hits"]) == ["1002", "AAA"]
    assert {r["code"] for r in a["items"]} == {"1001", "1002", "1003", "AAA"}  # +200 は一覧には残る
    title, body = alerts.message(a)
    assert "1001 会社1001" in body and "ウォッチ 2 件" in body and "1003" not in body


def test_spike_day_is_emphasized():
    series = {f"{1000 + i}": ([-100.0] * 139 + [-250.0], [-100.0] * 139 + [-250.0]) for i in range(10)}
    jx = _xs(series, DAYS)
    rows = [{"code": c, "company_name": c, "market": "プライム", "cci48": -250, "cci288": -250} for c in jx]
    a = alerts.build(rows, jx, [], {}, [])
    assert a["both_down_count"] == 10 and a["spike_threshold"] == 0.0 and a["spike"] is True
    title, body = alerts.message(a)
    assert title.startswith("⚠ 一斉に割れ") and "10 件" in body and "ほか5" in body


def test_nothing_to_notify():
    jx = _xs({"1004": _hist(-100, -100)}, DAYS)
    a = alerts.build([], jx, [], {}, [])
    assert alerts.message(a) is None
    assert alerts.notify(a, __import__("pathlib").Path("/tmp/x.html"), runner=None, platform="darwin") == "none"
    assert alerts.shown_path(Path("/opt/x.html"), Path("/home/u")) == "/opt/x.html"


class R:
    def __init__(self, rc=0):
        self.returncode = rc


def test_notify_defaults_to_osascript_and_ends_with_list_path(tmp_path):
    jx = _xs({"1001": _hist(-250, -230)}, DAYS)
    a = alerts.build([{"code": "1001", "company_name": '会社"A"', "cci48": -250, "cci288": -230}], jx, [], {}, [])
    page = tmp_path / "screener-data" / "out" / f"cci_alerts_{a['asof']}.html"
    calls = []

    def run(args, **kw):
        calls.append(args)
        return R()

    # terminal-notifier が入っていても、既定では使わない
    how = alerts.notify(a, page, runner=run, which=lambda n: "/opt/tn", platform="darwin", home=tmp_path)
    assert how == "osascript" and calls[-1][0] == "osascript"
    script = calls[-1][2]
    assert '\\"A\\"' in script  # 引用符は逃がす
    assert script.split(" with title ")[0].endswith(f'一覧: ~/screener-data/out/cci_alerts_{a["asof"]}.html"')
    assert alerts.notify(a, page, runner=run, which=lambda n: None, platform="linux") == "not_mac"


def test_terminal_notifier_only_when_chosen_and_falls_back_on_error(tmp_path):
    jx = _xs({"1001": _hist(-250, -230)}, DAYS)
    a = alerts.build([{"code": "1001", "company_name": "会社A", "cci48": -250, "cci288": -230}], jx, [], {}, [])
    page = tmp_path / "cci.html"
    calls = []

    def ok(args, **kw):
        calls.append(args)
        return R()

    kw = {"which": lambda n: "/opt/tn", "platform": "darwin", "prefer": "terminal-notifier"}
    assert alerts.notify(a, page, runner=ok, **kw) == "terminal-notifier"
    assert calls[-1][calls[-1].index("-open") + 1] == page.as_uri()

    def tn_fails(args, **kw):  # macOS 26: 実行時のエラー（終了コード ≠ 0 / 例外）→ osascript に切り替え
        calls.append(args)
        if args[0] == "/opt/tn":
            return R(1)
        return R()

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


def test_daily_run_writes_list_verify_and_notifies_once(cfg, monkeypatch):
    sent = []
    monkeypatch.setattr(daily, "mac_notify", lambda a, p, **kw: sent.append((a["asof"], p, kw)))
    doc = signals.run(cfg)
    a = doc["cci_alerts"]
    assert set(a) >= {"asof", "both_down_count", "spike_threshold", "spike", "both_down", "watch_hits", "items"}
    v = doc["verify"]["jp"]["cci_both_down"]
    assert set(v["full"]) == {"both_down", "both_up", "base"} and v["full"]["base"]["n"] > 0
    assert set(v["excluding_spike_days"]) == {"both_down", "base"} and isinstance(v["spike_days"], list)
    assert v["by_year"]["base"] and v["spike_rule"] == {"quantile": 0.99, "lookback_days": 245, "min_count": 5}
    local_report.write(cfg, doc)
    p = local_report.alerts_html(cfg, doc)
    assert p.exists() and (cfg.out_dir / "cci_alerts.html").exists() and "<script" not in p.read_text()
    vj = json.loads((cfg.out_dir / "verify_local.json").read_text())
    assert "cci_both_down" in vj["jp"]
    import datetime as dt

    from .test_daily import fake_get

    daily.pipeline(cfg, dt.date(2026, 10, 30), get=fake_get(cfg=cfg), us_update=lambda c, d: None)
    assert len(sent) == 1 and sent[0][1].name.startswith("cci_alerts_") and sent[0][2] == {"prefer": "osascript"}
