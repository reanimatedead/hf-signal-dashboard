"""collect.yml workflow の cron / 整合性検査 (SPEC_AUTOCOLLECT §1, §6, §7.1).

- 木〜土 UTC 15:00 (= 金〜日 0:00 JST) と 日 UTC 18:00 (= 月 3:00 JST) を必ず含む。
- update_signals.yml と同じ時刻で衝突しない (15:00 UTC は両方に存在するが、
  collect.yml は週末だけ、update_signals.yml は毎日 → 重複は許容、ただし
  collect.yml が "weekend-only" 切替で再実行を制限している事を簡易に検査)。
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
COLLECT_YML = ROOT / ".github" / "workflows" / "collect.yml"
UPDATE_YML  = ROOT / ".github" / "workflows" / "update_signals.yml"


def test_collect_workflow_exists():
    assert COLLECT_YML.exists(), "collect.yml workflow must exist (Agent A)"


def test_collect_cron_contains_weekend_zero_jst():
    text = COLLECT_YML.read_text(encoding="utf-8")
    # accept any whitespace around 4,5,6
    assert re.search(r'cron:\s*"0\s+15\s+\*\s+\*\s+4\s*,\s*5\s*,\s*6"', text), (
        "weekend midnight JST cron (0 15 * * 4,5,6) missing"
    )


def test_collect_cron_contains_monday_three_am_jst():
    text = COLLECT_YML.read_text(encoding="utf-8")
    assert re.search(r'cron:\s*"0\s+18\s+\*\s+\*\s+0"', text), (
        "monday 03:00 JST cron (0 18 * * 0) missing"
    )


def test_collect_does_not_redefine_existing_workflow_name():
    text = COLLECT_YML.read_text(encoding="utf-8")
    upd_text = UPDATE_YML.read_text(encoding="utf-8") if UPDATE_YML.exists() else ""
    # Different "name:" so GitHub Actions UI shows them separately.
    name_a = re.search(r'^name:\s*(.+)$', text, re.M)
    name_b = re.search(r'^name:\s*(.+)$', upd_text, re.M)
    assert name_a and name_b, "both workflows must have name:"
    assert name_a.group(1).strip() != name_b.group(1).strip(), (
        "collect.yml and update_signals.yml must have distinct names"
    )


def test_collect_uses_collector_cli_module():
    text = COLLECT_YML.read_text(encoding="utf-8")
    assert "python -m collector.cli" in text, (
        "collect.yml must invoke collector.cli (Agent A wiring)"
    )


def test_collect_pytest_gate_present():
    text = COLLECT_YML.read_text(encoding="utf-8")
    # SPEC §6: pytest 回帰防止ゲート
    assert "pytest" in text, "collect.yml must run pytest gate before commit"
