"""tools/contract_check.py: 壊れたサンプルで「失敗→exit≠0、Issue 作成コマンドが1回だけ、前日ファイルが残る」。
gh はモック（実際の GitHub には繋がない）。"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import contract_check as cc  # noqa: E402
from issue_once import open_issue_once  # noqa: E402
from marketcalc import contracts  # noqa: E402

GOOD_COUNTS = {"nikkei225": 225, "nasdaq100": 101, "sp500": 503, "dow30": 30}


def _fixture(tmp_path, missing=0, counts=None):
    syms = contracts.US_PROBE + contracts.JP_PROBE
    prices = {s: ([100.0, None] if i >= missing else None) for i, s in enumerate(syms)}
    p = tmp_path / "fx.json"
    p.write_text(json.dumps({"prices": prices, "counts": counts or GOOD_COUNTS}))
    return p


class FakeGh:
    def __init__(self, existing=""):
        self.calls, self.existing = [], existing

    def __call__(self, cmd):
        self.calls.append(cmd)
        out = self.existing if cmd[:3] == ["gh", "issue", "list"] else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    def count(self, verb):
        return sum(1 for c in self.calls if c[:3] == ["gh", "issue", verb])


def test_ok_passes_without_issue(tmp_path):
    gh = FakeGh()
    assert cc.run(_fixture(tmp_path), issue=True, runner=gh) == 0
    assert gh.calls == []


def test_broken_prices_fail_and_issue_created_once_and_previous_kept(tmp_path):
    docs = tmp_path / "docs"; docs.mkdir()
    prev = docs / "data.json"; prev.write_text('{"meta":{"updated_at":"yesterday"}}')
    before = prev.read_text()
    gh = FakeGh()
    # 米国 20 中 3 取れない = 15% > 10% → 止める
    assert cc.run(_fixture(tmp_path, missing=3), issue=True, runner=gh) != 0
    assert gh.count("create") == 1 and gh.count("comment") == 0
    create = next(c for c in gh.calls if c[:3] == ["gh", "issue", "create"])
    assert create[create.index("--title") + 1] == cc.ISSUE_TITLE
    assert prev.read_text() == before          # 前日のファイルはそのまま（contract_check は触らない）


def test_second_failure_comments_instead_of_new_issue(tmp_path):
    gh = FakeGh(existing="42")
    assert cc.run(_fixture(tmp_path, missing=5), issue=True, runner=gh) == 1
    assert gh.count("create") == 0 and gh.count("comment") == 1


def test_count_out_of_range_fails(tmp_path):
    bad = dict(GOOD_COUNTS, sp500=102)          # S&P500 が 102 件 fallback → ±5% 外れ
    assert cc.run(_fixture(tmp_path, counts=bad)) == 1


def test_small_missing_ratio_is_tolerated(tmp_path):
    assert cc.run(_fixture(tmp_path, missing=2)) == 0       # 2/20 = 10% はちょうど上限内


def test_cli_exit_code(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "contract_check.py"), "--fixture",
                        str(_fixture(tmp_path, missing=20))], capture_output=True, text=True)
    assert r.returncode == 1 and "FAIL" in r.stdout


def test_issue_once_label_fallback():
    class G(FakeGh):
        def __call__(self, cmd):
            self.calls.append(cmd)
            rc = 1 if "--label" in cmd else 0
            return subprocess.CompletedProcess(cmd, rc, stdout="", stderr="")
    g = G()
    assert open_issue_once("t", "b", runner=g) == ("created", None)
    assert g.count("create") == 2               # ラベル付きが失敗 → ラベル無しで1件
