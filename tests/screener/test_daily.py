"""screener.daily: git pull --ff-only → 契約テスト → 差分 → 一覧 → local_report。
失敗時だけ「失敗」、月曜は「週次 OK」。"""

import datetime as dt
import json

import pytest

from screener import contract, daily

MON, TUE = dt.date(2026, 11, 2), dt.date(2026, 11, 3)


class Git:
    def __init__(self, rc=0):
        self.rc, self.calls = rc, []

    def __call__(self, args, **kw):
        self.calls.append(args)

        class R:
            returncode = self.rc
            stdout = ""
            stderr = "fatal: Not possible to fast-forward"

        return R()


def fake_get(daily_rows=3600, drop_col=None, cfg=None):
    """cfg を渡すと、手元にある日の日足はその中身（+ 件数合わせの空行）を返す（取り直しても値が変わらない）。"""
    fins = json.loads(json.dumps(_fin_row()))
    if drop_col:
        del fins[drop_col]

    def get(path, **q):
        if path == "equities/bars/daily":
            rows = []
            p = cfg.jp("daily", f"{q.get('date')}.json") if cfg else None
            if p is not None and p.exists():
                rows = [
                    {"Code": c + "0", "AdjH": h, "AdjL": lo, "AdjC": cl, "Va": va}
                    for c, h, lo, cl, va in json.loads(p.read_text())
                ]
            return rows + [{"Code": f"9{i:04d}"} for i in range(max(0, daily_rows - len(rows)))]
        if path == "fins/summary":
            p = cfg.jp("fins", f"{q.get('date')}.json") if cfg else None
            if p is not None and p.exists():
                return json.loads(p.read_text())
            return [fins]
        return []

    return get


def _fin_row():
    from screener.calc.contracts import JQ_FIN_COLUMNS

    r = {c: "1" for c in JQ_FIN_COLUMNS}
    r["DocType"] = "FYFinancialStatements_Consolidated_JP"
    r.update(Code="99990", DiscDate="2000-01-04", CurFYEn="2000-03-31")  # 架空データに無い銘柄（一覧に影響しない）
    return r


def test_failure_sends_fail_and_exit_1(cfg):
    sent = []

    def run(c, d):
        raise RuntimeError("boom")

    rc = daily.main(["--pulled"], cfg=cfg, today=TUE, run=run, poster=lambda u, b: sent.append(b.decode()))
    assert rc == 1 and sent == ["screener 2026-11-03 失敗"]


def test_daily_logs_ntfy_result_line(cfg, capsys):
    assert daily.main(["--pulled"], cfg=cfg, today=MON, run=lambda c, d: None, poster=lambda u, b: 200) == 0
    assert "ntfy: 週次 OK 送信 HTTP 200" in capsys.readouterr().out
    assert daily.main(["--pulled"], cfg=cfg, today=TUE, run=lambda c, d: None, poster=lambda u, b: 200) == 0
    assert "ntfy: 送信なし HTTP -" in capsys.readouterr().out


def test_success_sends_nothing_except_monday(cfg):
    sent = []
    post = lambda u, b: sent.append(b.decode())  # noqa: E731
    assert daily.main(["--pulled"], cfg=cfg, today=TUE, run=lambda c, d: None, poster=post) == 0
    assert sent == []
    assert daily.main(["--pulled"], cfg=cfg, today=MON, run=lambda c, d: None, poster=post) == 0
    assert sent == ["screener 2026-11-02 週次 OK"]


def test_pipeline_end_to_end_on_fixture(cfg):
    """架空データの最終日で全段を通す。J-Quants・Yahoo は差し替え（直近3営業日は手元の日足をそのまま返す）。"""
    last = dt.date(2026, 10, 30)
    c = daily.pipeline(cfg, last, get=fake_get(cfg=cfg), us_update=lambda c, d: None)
    assert c["japan_rows"] == 5 and (cfg.out_dir / "japan_list.html").exists()


class Exec:
    def __init__(self):
        self.calls = []

    def __call__(self, prog, argv):
        self.calls.append((prog, argv))


def test_pull_then_restart_with_new_code(cfg):
    """git pull --ff-only のあと、本処理の前に自分自身を起動し直す（古いコードのまま走らない）。"""
    git, ex, ran = Git(), Exec(), []
    rc = daily.main(["--today", "2026-11-03"], cfg=cfg, run=lambda c, d: ran.append(d), runner=git, execv=ex)
    assert rc == 0 and ran == []  # 古いプロセスでは本処理をしない
    assert git.calls == [["git", "-C", str(cfg.repo_dir), "pull", "--ff-only"]]
    ((prog, argv),) = ex.calls
    assert argv[0] == prog and argv[-5:] == ["-m", "screener.daily", "--pulled", "--today", "2026-11-03"]
    # 起動し直したあと（--pulled）は pull しない・本処理をする
    git2 = Git()
    assert daily.main(argv[argv.index("--pulled") :], cfg=cfg, run=lambda c, d: ran.append(d), runner=git2) == 0
    assert git2.calls == [] and ran == [dt.date(2026, 11, 3)]


def test_reexec_uses_uv_run_when_available(cfg, monkeypatch):
    monkeypatch.setattr(daily.shutil, "which", lambda n: "/opt/uv")
    prog, argv = daily.reexec_argv(cfg, [])
    assert prog == "/opt/uv" and argv[:4] == ["/opt/uv", "run", "--project", str(cfg.repo_dir)]
    monkeypatch.setattr(daily.shutil, "which", lambda n: None)
    prog, argv = daily.reexec_argv(cfg, [])
    assert prog == daily.sys.executable and argv[1:] == ["-m", "screener.daily", "--pulled"]


def test_git_pull_failure_stops_and_sends_fail(cfg):
    sent, ex = [], Exec()
    rc = daily.main([], cfg=cfg, today=TUE, runner=Git(rc=1), execv=ex, poster=lambda u, b: sent.append(b.decode()))
    assert rc == 1 and sent == ["screener 2026-11-03 失敗"] and ex.calls == []


@pytest.mark.parametrize("kw", [{"daily_rows": 1200}, {"drop_col": "NxFEPS"}])
def test_contract_failure_stops_before_fetch(cfg, kw):
    with pytest.raises(contract.ContractError):
        daily.pipeline(cfg, TUE, get=fake_get(**kw), us_update=lambda c, d: None)
    assert not cfg.jp("daily", f"{TUE}.json").exists()


def test_contract_fixtures_ok_and_broken(fixture_src):
    ok = json.loads((fixture_src / "contract_ok.json").read_text())
    bad = json.loads((fixture_src / "contract_broken.json").read_text())
    assert contract.evaluate(ok)[0] is True
    good, text = contract.evaluate(bad)
    assert good is False and "1200" in text and "NxFEPS" in text


def test_broken_config_still_sends_fail(tmp_path, monkeypatch):
    conf = tmp_path / "config.toml"
    conf.write_text('[ntfy]\ntopic = "screener-abc123"\n[paths\nbroken', encoding="utf-8")
    monkeypatch.setenv("SCREENER_CONFIG", str(conf))
    sent = []
    rc = daily.main(["--pulled"], today=TUE, poster=lambda u, b: sent.append((u, b.decode())))
    assert rc == 1 and sent == [("https://ntfy.sh/screener-abc123", "screener 2026-11-03 失敗")]


def test_pipeline_writes_today_html_only_under_out(cfg):
    """daily の最後に <data_dir>/out/today.html（日本株・米国株・ETF の段階5/4・CCI ±200・決算7日以内・段階の検証）。"""
    daily.pipeline(cfg, dt.date(2026, 10, 30), get=fake_get(cfg=cfg), us_update=lambda c, d: None)
    p = cfg.out_dir / "today.html"
    assert p.exists() and not any(cfg.repo_dir.rglob("*"))
    t = p.read_text(encoding="utf-8")
    for s in (
        "日本株",
        "米国株",
        "ETF",
        "段階5 の上位",
        "段階4 の上位",
        "そろって −200 割れ",
        "そろって +200 超え",
        "日以内",
        "段階ごとの検証",
        "空売りの根拠ではありません",
        "公開しない",
    ):
        assert s in t, s
    assert "<script" not in t and "buy_cci200" not in t  # 言葉は描画時に付ける（コードを出さない）
