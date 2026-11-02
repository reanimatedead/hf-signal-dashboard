"""screener.calc.schedule: 画面の「次回」は deploy.yml の full の cron から計算する（固定の文字を書かない）。"""

import datetime as dt
import re

import pytest

from screener.calc import schedule as S

JST = S.JST


def _jst(*a):
    return dt.datetime(*a, tzinfo=JST)


def test_next_after_basic_fields():
    # 30 22 * * * (UTC) = 毎日 07:30 JST
    assert S.next_after("30 22 * * *", _jst(2026, 11, 2, 7, 0)) == _jst(2026, 11, 2, 7, 30)
    assert S.next_after("30 22 * * *", _jst(2026, 11, 2, 7, 30)) == _jst(2026, 11, 3, 7, 30)  # ちょうどは次の日
    assert S.next_after("30 22 * * *", _jst(2026, 11, 2, 23, 59)) == _jst(2026, 11, 3, 7, 30)
    # 曜日: 0 2 * * 1-5 = 月〜金 11:00 JST（2026-11-07 は土曜 → 月曜 11-09）
    assert S.next_after("0 2 * * 1-5", _jst(2026, 11, 7, 12, 0)) == _jst(2026, 11, 9, 11, 0)
    assert S.next_after("17 */2 * * *", _jst(2026, 11, 2, 9, 0)) == _jst(2026, 11, 2, 9, 17)  # 00:17 UTC
    # 7 も日曜（UTC 日曜 17時 = JST 月曜 2時）
    assert S.next_after("0 17 * * 7", _jst(2026, 11, 2, 0, 0)) == _jst(2026, 11, 2, 2, 0)
    with pytest.raises(ValueError):
        S.parse("0 25 * * *")


def test_deploy_yml_full_is_0730_jst_and_next_update_is_computed():
    crons = S.workflow_crons()
    assert crons["full"] == ["30 22 * * *"]
    nxt = S.next_job_run("full", _jst(2026, 11, 2, 8, 0))
    assert nxt == _jst(2026, 11, 3, 7, 30) and nxt.strftime("%H:%M") == "07:30"
    assert S.next_job_run("nope", _jst(2026, 11, 2, 8, 0)) is None


def test_full_and_corr_refresh_never_fire_at_the_same_minute():
    """同じ分に2つ走ると concurrency "pages"（cancel-in-progress）で片方が止まる。2週間ぶん確かめる。"""
    crons = S.workflow_crons()
    t = _jst(2026, 11, 2, 0, 0).astimezone(dt.UTC)
    for _ in range(14 * 24 * 60):
        fired = [job for job, cs in crons.items() for c in cs if S.matches(c, t)]
        assert len(fired) <= 1, (t, fired)
        t += dt.timedelta(minutes=1)


def test_if_conditions_use_the_same_cron_strings():
    """ジョブの if: が見る schedule の文字列は、そのジョブの cron 行と同じ（片方だけ変えない）。"""
    text = S.DEPLOY_YML.read_text(encoding="utf-8")
    crons = S.workflow_crons()
    for job, cs in crons.items():
        block = text.split(f"\n  {job}:\n", 1)[1].split("runs-on:", 1)[0]
        used = re.findall(r"github\.event\.schedule == '([^']+)'", block)
        assert sorted(used) == sorted(cs), job


def test_fetch_signals_does_not_hardcode_next_update():
    src = (S.DEPLOY_YML.parents[2] / "fetch_signals.py").read_text(encoding="utf-8")
    assert 'schedule.next_job_run("full"' in src and "hour=8, minute=0" not in src
