"""screener.us: calc.fund_us を使う・決算は1社ずつ読む・判定（架空データ）。"""

from screener.us import make_value
from screener.us import screen as S
from screener.us.fetch import merge_chart


def test_screen_reads_facts_one_company_at_a_time(cfg, monkeypatch):
    opened = []
    orig = S.load_facts

    def spy(t, c):
        opened.append(t)
        return orig(t, c)

    monkeypatch.setattr(S, "load_facts", spy)
    rows = S.screen("2026-10-31", "2025-10-31", "2026-09-30", cfg=cfg)
    assert opened == list(S.universe(cfg))  # 1社ずつ順番に
    assert {r["ticker"] for r in rows} == {"AAA", "BBB", "CCC"}


def test_make_value_tags(cfg):
    import datetime as dt

    rows = make_value.build(cfg, dt.date(2026, 10, 31))
    by = {r["ticker"]: r for r in rows}
    assert by["CCC"]["fin_tag"] == ""  # 金融は候補にしない
    assert all(set(make_value.KEYS) <= set(r) for r in rows)


def test_merge_chart_appends_and_detects_split():
    def chart(ts, c, splits=None):
        r = {
            "timestamp": ts,
            "indicators": {"quote": [{"high": c, "low": c, "close": c}], "adjclose": [{"adjclose": c}]},
        }
        if splits:
            r["events"] = {"splits": splits}
        return {"chart": {"result": [r]}}

    old = chart([86400 * 1, 86400 * 2], [1.0, 2.0])
    new = chart([86400 * 2, 86400 * 3], [2.5, 3.0])
    m = merge_chart(old, new)
    assert m["chart"]["result"][0]["indicators"]["quote"][0]["close"] == [1.0, 2.5, 3.0]
    assert merge_chart(old, chart([86400 * 3], [3.0], {"259200": {"numerator": 2}})) is None
