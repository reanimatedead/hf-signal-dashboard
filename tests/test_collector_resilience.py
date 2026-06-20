"""1 ソース失敗で全体が落ちない (SPEC_AUTOCOLLECT §0, §7.3).

collector.runtime.retry が attempts 回失敗しても、collector.cli.run() は
それを errors に積んで処理を継続することを担保する。
"""
import pytest

rt = pytest.importorskip("collector.runtime", reason="Agent C 未実装")
cli = pytest.importorskip("collector.cli", reason="Agent A/C 未実装")


def test_retry_returns_value_on_success():
    calls = [0]
    def f():
        calls[0] += 1
        return 42
    v = rt.retry(f, attempts=3, base_backoff=0.0)
    assert v == 42 and calls[0] == 1


def test_retry_eventually_succeeds():
    calls = [0]
    def f():
        calls[0] += 1
        if calls[0] < 3:
            raise RuntimeError("boom")
        return "ok"
    v = rt.retry(f, attempts=3, base_backoff=0.0)
    assert v == "ok" and calls[0] == 3


def test_retry_raises_after_exhausted():
    def f():
        raise RuntimeError("perma")
    with pytest.raises(RuntimeError):
        rt.retry(f, attempts=2, base_backoff=0.0)


def test_collect_run_records_failures_without_dying(tmp_path, monkeypatch):
    """ソース取得 ramp の一部に例外が起きても、cli.run は完了し
    collect_log.errors に失敗ソース名が並ぶ。"""
    # ダミーの収集呼び出し: dict を 1 つだけ返すフェイク
    def fake_fetch():
        # raise inside; should be swallowed and recorded
        raise RuntimeError("yfinance HTTP 503")

    def fake_snapshot(data, root):
        return {"path": str(root / "fake.json"), "changed": False, "size_kb": 0.1}

    monkeypatch.setattr(cli, "_invoke_fetch", fake_fetch, raising=True)
    monkeypatch.setattr(cli, "_invoke_snapshot", fake_snapshot, raising=True)
    res = cli.run(history_root=tmp_path, log_root=tmp_path, workflow="local")
    assert res["ok"] is True, "cli.run should not crash on source failure"
    assert any("yfinance" in e for e in res["errors"]), (
        f"failed source must be recorded; got errors={res['errors']}"
    )
    assert (tmp_path / "collect_log.jsonl").exists()


def test_runtime_user_agent_constant():
    ua = rt.USER_AGENT
    assert "hf-signal-dashboard" in ua
    assert "github.com" in ua, "UA should reference repo URL per SPEC §4"


def test_runtime_rate_limit_minimum_interval():
    assert rt.MIN_REQUEST_INTERVAL_SEC >= 0.2, (
        "rate-limit floor must be at least 0.2s for politeness"
    )
