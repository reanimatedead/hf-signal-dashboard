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


def fake_get(daily_rows=3600, drop_col=None):
    fins = json.loads(json.dumps(_fin_row()))
    if drop_col:
        del fins[drop_col]

    def get(path, **q):
        if path == "equities/bars/daily":
            return [{"Code": f"{i:05d}"} for i in range(daily_rows)]
        if path == "fins/summary":
            return [fins]
        return []

    return get


def _fin_row():
    from screener.calc.contracts import JQ_FIN_COLUMNS

    r = {c: "1" for c in JQ_FIN_COLUMNS}
    r["DocType"] = "FYFinancialStatements_Consolidated_JP"
    return r


def test_failure_sends_fail_and_exit_1(cfg):
    sent = []

    def run(c, d):
        raise RuntimeError("boom")

    rc = daily.main([], cfg=cfg, today=TUE, run=run, poster=lambda u, b: sent.append(b.decode()))
    assert rc == 1 and sent == ["screener 2026-11-03 失敗"]


def test_success_sends_nothing_except_monday(cfg):
    sent = []
    post = lambda u, b: sent.append(b.decode())  # noqa: E731
    assert daily.main([], cfg=cfg, today=TUE, run=lambda c, d: None, poster=post) == 0
    assert sent == []
    assert daily.main([], cfg=cfg, today=MON, run=lambda c, d: None, poster=post) == 0
    assert sent == ["screener 2026-11-02 週次 OK"]


def test_pipeline_end_to_end_on_fixture(cfg):
    """架空データの最終日（既にファイルがある日）で全段を通す。git・J-Quants・Yahoo は差し替え。"""
    git = Git()
    last = dt.date(2026, 10, 30)
    c = daily.pipeline(cfg, last, get=fake_get(), runner=git, us_prices=lambda c: None)
    assert git.calls == [["git", "-C", str(cfg.repo_dir), "pull", "--ff-only"]]
    assert c["japan_rows"] == 5 and (cfg.out_dir / "japan_list.html").exists()


def test_git_pull_failure_stops(cfg):
    with pytest.raises(RuntimeError, match="ff-only"):
        daily.pipeline(cfg, TUE, get=fake_get(), runner=Git(rc=1), us_prices=lambda c: None)


@pytest.mark.parametrize("kw", [{"daily_rows": 1200}, {"drop_col": "NxFEPS"}])
def test_contract_failure_stops_before_fetch(cfg, kw):
    with pytest.raises(contract.ContractError):
        daily.pipeline(cfg, TUE, get=fake_get(**kw), runner=Git(), us_prices=lambda c: None)
    assert not cfg.jp("daily", f"{TUE}.json").exists()


def test_contract_fixtures_ok_and_broken(fixture_src):
    ok = json.loads((fixture_src / "contract_ok.json").read_text())
    bad = json.loads((fixture_src / "contract_broken.json").read_text())
    assert contract.evaluate(ok)[0] is True
    good, text = contract.evaluate(bad)
    assert good is False and "1200" in text and "NxFEPS" in text
