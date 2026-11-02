"""screener.notify: 本文は「screener 日付 OK/失敗/週次 OK」だけ（株のデータを送らない）。"""

import datetime as dt
import re

import pytest

from screener import notify

STRICT = re.compile(r"^screener \d{4}-\d{2}-\d{2} (OK|失敗|週次 OK)$")


def test_body_matches_strict_regex():
    d = dt.date(2026, 11, 2)
    assert notify.body("OK", d) == "screener 2026-11-02 OK"
    assert notify.body("失敗", d) == "screener 2026-11-02 失敗"
    assert notify.body("週次 OK", d) == "screener 2026-11-02 週次 OK"
    for s in notify.STATUSES:
        assert STRICT.fullmatch(notify.body(s, d))
    with pytest.raises(ValueError):
        notify.body("OK 7203 買い", d)


def test_send_posts_only_status_and_date(cfg):
    sent = []
    ok = notify.send(cfg, "失敗", dt.date(2026, 11, 2), poster=lambda url, data: sent.append((url, data)))
    assert ok
    ((url, data),) = sent
    assert url == "https://ntfy.example.invalid/screener-testtopic"
    assert STRICT.fullmatch(data.decode("utf-8"))


def test_send_without_topic_or_on_error_returns_false(cfg):
    def boom(url, data):
        raise OSError("down")

    assert notify.send(cfg, "OK", dt.date(2026, 11, 2), poster=boom) is False
    cfg.raw["ntfy"]["topic"] = ""
    assert notify.send(cfg, "OK", dt.date(2026, 11, 2), poster=lambda u, d: None) is False


def test_send_logs_one_line_with_http_code(cfg, capsys):
    import io
    import urllib.error

    d = dt.date(2026, 11, 2)
    assert notify.send(cfg, "OK", d, poster=lambda u, b: 200)
    assert capsys.readouterr().out.strip().splitlines() == ["ntfy: OK 送信 HTTP 200"]

    def http_err(u, b):
        raise urllib.error.HTTPError(u, 429, "Too Many Requests", {}, io.BytesIO())

    assert notify.send(cfg, "失敗", d, poster=http_err) is False
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["ntfy: 失敗 送信失敗 HTTP 429"] and "screener-testtopic" not in out[0]
