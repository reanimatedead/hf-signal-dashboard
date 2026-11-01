"""tools/contract_check.py（オフライン。Yahoo には繋がない）。

- Yahoo の事前確認は警告だけ: 429 は「確認できない」で、公開を止めない（2026-11-01 deploy #260 の再発防止）。
- 構成銘柄の件数 ±5% が外れたら止める。
- 生成後の欠損チェック（--post）: meta.nan_report で price=None が 10% 超なら止める。
- Issue は作らない（gh を呼ばない）。
"""
import json
import pathlib
import subprocess
import sys
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import contract_check as cc  # noqa: E402
from marketcalc import contracts  # noqa: E402

GOOD_COUNTS = {"nikkei225": 225, "nasdaq100": 101, "sp500": 503, "dow30": 30}
SYMS = contracts.US_PROBE + contracts.JP_PROBE


def _fixture(tmp_path, missing=0, limited=0, counts=None):
    prices = {}
    for i, s in enumerate(SYMS):
        prices[s] = cc.RATE_LIMITED if i < limited else (None if i < limited + missing else [100.0, None])
    p = tmp_path / "fx.json"
    p.write_text(json.dumps({"prices": prices, "counts": counts or GOOD_COUNTS}))
    return p


def test_ok(tmp_path):
    assert cc.run(_fixture(tmp_path)) == 0


def test_all_429_is_unverifiable_and_does_not_stop(tmp_path, capsys):
    """deploy #260 と同じ状況: 40 件すべて 429 → 止めない（警告だけ）。"""
    assert cc.run(_fixture(tmp_path, limited=len(SYMS))) == 0
    out = capsys.readouterr().out
    assert out.count("確認できない") >= 2 and "contract_check: OK" in out


def test_missing_prices_only_warn(tmp_path, capsys):
    """429 以外で取れなくても事前確認では止めない（本当の欠損は --post で見る）。"""
    assert cc.run(_fixture(tmp_path, missing=15)) == 0
    assert "警告だけ" in capsys.readouterr().out


def test_count_out_of_range_still_stops(tmp_path):
    bad = dict(GOOD_COUNTS, sp500=102)          # S&P500 が 102 件 fallback → ±5% 外れ
    assert cc.run(_fixture(tmp_path, counts=bad)) == 1


def test_probe_maps_429_to_rate_limited(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(cc.urllib.request, "urlopen", fake_urlopen)
    assert cc._probe_one("AAPL") == cc.RATE_LIMITED
    assert len(calls) == 2                       # query1 → query2 の1回ずつ。叩き続けない


def test_probe_other_error_is_missing(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(cc.urllib.request, "urlopen", fake_urlopen)
    assert cc._probe_one("ZZZZ") is None


def _data(tmp_path, null=None):
    null = null or {}
    nan = {t: {"constituents": n, "price_null": null.get(t, 0), "chart_unavailable": 0}
           for t, n in (("nikkei225", 225), ("dow30", 30), ("nasdaq100", 101), ("sp500", 503))}
    p = tmp_path / "data.json"
    p.write_text(json.dumps({"meta": {"nan_report": nan}}))
    return p


def test_post_ok(tmp_path):
    assert cc.post(_data(tmp_path, {"sp500": 50})) == 0        # 50/503 = 9.9%


def test_post_missing_over_10pct_stops(tmp_path):
    assert cc.post(_data(tmp_path, {"nikkei225": 23})) == 1    # 23/225 = 10.2%


def test_post_without_nan_report_stops(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"meta":{}}')
    assert cc.post(p) == 1
    assert cc.post(tmp_path / "nope.json") == 1


def test_no_issue_creation_anywhere():
    src = (ROOT / "tools" / "contract_check.py").read_text(encoding="utf-8")
    assert "gh issue" not in src and "issue_once" not in src
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = wf.read_text(encoding="utf-8")
        assert "gh issue create" not in text and "issues: write" not in text, wf.name


def test_cli(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "contract_check.py"), "--post",
                        str(_data(tmp_path, {"dow30": 30}))], capture_output=True, text=True)
    assert r.returncode == 1 and "FAIL" in r.stdout
