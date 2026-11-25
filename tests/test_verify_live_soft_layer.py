"""tools/verify_live.py: gamma.json は補助層（soft layer）— 2026-11-25〜。

CBOE が公開エンドポイントを封鎖（Cloudflare 403）し、gamma.json が古いまま
data_status="stale" で再掲されるようになった。監視が毎回 exit 1 にならないよう、
補助層の鮮度切れ / data_status 劣化は WARN のみ。ただし 404 等の消失は exit 2 のまま。
ネットワークは使わない（verify_live._fetch を差し替える）。
"""
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import verify_live as vl  # noqa: E402

BASE = "https://example.invalid/hf"


def _iso(hours_ago, tz=timezone.utc):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).astimezone(tz).isoformat()


def _data_json(hours_ago=1):
    rows = [{"ticker": f"T{i}", "chart_status": "ready"} for i in range(5)]
    return {
        "meta": {"updated_at": _iso(hours_ago, timezone(timedelta(hours=9)))},
        "markets": {tab: list(rows) for tab in vl.EQUITY_TABS},
        "summary": {},
        "money_flow": {},
        "survival_loop": {},
    }


def _bodies(data_age=1, gamma_age=1, gamma_status="ok"):
    return {
        "": (200, b"<!doctype html><title>x</title>"),
        "data.json": (200, json.dumps(_data_json(data_age)).encode()),
        "relations.json": (200, json.dumps({"as_of": _iso(1)}).encode()),
        "macro_v2.json": (200, json.dumps({"as_of": _iso(1)}).encode()),
        "gamma.json": (200, json.dumps({"as_of": _iso(gamma_age),
                                        "data_status": gamma_status}).encode()),
    }


def _run(monkeypatch, capsys, bodies):
    def fake_fetch(base, path):
        st, body = bodies[path]
        if st == 200:
            return st, body, None, 1
        return st, None, f"HTTP {st}", 1

    monkeypatch.setattr(vl, "_fetch", fake_fetch)
    monkeypatch.setattr(vl.time, "sleep", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["verify_live.py", BASE])
    rc = vl.main()
    return rc, capsys.readouterr().out


@pytest.fixture(autouse=True)
def _default_soft(monkeypatch):
    monkeypatch.delenv("VERIFY_SOFT_LAYERS", raising=False)


def test_only_gamma_old_is_warn_not_fail(monkeypatch, capsys):
    rc, out = _run(monkeypatch, capsys, _bodies(gamma_age=100))
    assert rc == 0, out
    assert "WARN gamma.json stale: 100h (soft layer)" in out
    assert "::warning::gamma.json stale: 100h (soft layer)" in out
    assert "verify_live: OK" in out


def test_gamma_data_status_stale_with_fresh_as_of_is_warn(monkeypatch, capsys):
    rc, out = _run(monkeypatch, capsys, _bodies(gamma_status="stale"))
    assert rc == 0, out
    assert "WARN gamma.json data_status=stale (soft layer)" in out
    assert "::warning::gamma.json data_status=stale (soft layer)" in out


def test_gamma_missing_as_of_is_warn(monkeypatch, capsys):
    b = _bodies()
    b["gamma.json"] = (200, json.dumps({"data_status": "error"}).encode())
    rc, out = _run(monkeypatch, capsys, b)
    assert rc == 0, out
    assert "WARN gamma.json freshness key as_of missing (soft layer)" in out
    assert "WARN gamma.json data_status=error (soft layer)" in out


def test_data_json_old_still_fails(monkeypatch, capsys):
    rc, out = _run(monkeypatch, capsys, _bodies(data_age=100))
    assert rc == 1, out
    assert "data.json stale" in out


def test_gamma_404_is_hard_fail(monkeypatch, capsys):
    b = _bodies()
    b["gamma.json"] = (404, None)
    rc, out = _run(monkeypatch, capsys, b)
    assert rc == 2, out
    assert "gamma.json HTTP=404" in out


def test_empty_soft_layers_env_restores_hard_freshness(monkeypatch, capsys):
    monkeypatch.setenv("VERIFY_SOFT_LAYERS", "")
    rc, out = _run(monkeypatch, capsys, _bodies(gamma_age=100))
    assert rc == 1, out
    assert "gamma.json stale" in out
    assert "WARN gamma.json" not in out
