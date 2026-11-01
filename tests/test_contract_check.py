"""tools/contract_check.py（オフライン。Yahoo には繋がない）。

- 事前の確認は構成銘柄の件数 ±5% だけ。Yahoo には問い合わせない（2026-11-01 deploy #260 の再発防止:
  事前の40回が本体の取得と同じ IP の回数制限枠を使い 429 を受けた）。
- 生成後の欠損チェック（--post）: meta.nan_report で price=None が 10% 超なら止める。
- Issue は作らない（gh を呼ばない）。
"""
import pytest
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import contract_check as cc  # noqa: E402

GOOD_COUNTS = {"nikkei225": 225, "nasdaq100": 101, "sp500": 503, "dow30": 30}


def _fixture(tmp_path, counts=None):
    p = tmp_path / "fx.json"
    p.write_text(json.dumps({"counts": counts or GOOD_COUNTS}))
    return p


def test_ok(tmp_path):
    assert cc.run(_fixture(tmp_path)) == 0


def test_count_out_of_range_still_stops(tmp_path):
    bad = dict(GOOD_COUNTS, sp500=102)          # S&P500 が 102 件 fallback → ±5% 外れ
    assert cc.run(_fixture(tmp_path, counts=bad)) == 1


def test_precheck_never_contacts_yahoo(monkeypatch):
    """事前の確認は Yahoo に1回も問い合わせない（件数だけ）。"""
    import fetch_signals as fs
    import urllib.request

    def boom(*a, **k):
        raise AssertionError("network call in pre-check")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(fs, "_chart_api_json", boom, raising=False)
    monkeypatch.setattr(fs, "fetch_chart_api", boom, raising=False)
    monkeypatch.setattr(fs, "fetch_batch", boom, raising=False)
    monkeypatch.setattr(cc, "live_counts", lambda: dict(GOOD_COUNTS))
    assert cc.run() == 0
    src = (ROOT / "tools" / "contract_check.py").read_text(encoding="utf-8")
    for name in ("chart_api", "urlopen", "live_prices", "yahoo_warnings", "_probe_one", "US_PROBE", "JP_PROBE"):
        assert name not in src, name


@pytest.mark.ci_only   # workflow ファイルを読む: 通常の CI だけ
def test_ntfy_missing_topic_warns_in_every_workflow():
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = wf.read_text(encoding="utf-8")
        if "NTFY_TOPIC" not in text:
            continue
        n_steps = text.count('curl -fsS -m 20 -d "hf-signal-dashboard')
        assert text.count("::warning::NTFY_TOPIC が未設定") == n_steps > 0, wf.name
        assert "通知なし\"; exit 0" not in text, wf.name


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


@pytest.mark.ci_only   # workflow ファイルを読む: 通常の CI だけ
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
