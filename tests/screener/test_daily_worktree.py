"""毎日の実行は専用の作業ツリーで動く: 開発用のクローンの状態で止まらず、そちらに触らない（本物の git で確かめる）。

2026-11-06・07 に止まった形: 開発用のクローンが追跡先のないブランチのまま → git pull が失敗。
"""

import os
import subprocess
from pathlib import Path

import pytest

from screener import daily
from screener.config import Config

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=ENV)
    assert not check or r.returncode == 0, r.stderr
    return r


def commit(repo: Path, name: str, text: str) -> str:
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-qm", name)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def repos(tmp_path):
    """origin（bare）・開発用のクローン dev・別の人の clone up・専用の作業ツリー run。"""
    origin, dev, up, run = (tmp_path / n for n in ("origin.git", "dev", "up", "run"))
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True, env=ENV)
    subprocess.run(["git", "clone", "-q", str(origin), str(dev)], check=True, env=ENV, capture_output=True)
    git(dev, "checkout", "-q", "-b", "main")
    commit(dev, "a.txt", "1\n")
    git(dev, "push", "-q", "origin", "main")
    subprocess.run(["git", "clone", "-q", str(origin), str(up)], check=True, env=ENV)
    git(dev, "worktree", "add", "-q", "--detach", str(run), "origin/main")
    return dev, up, run


def on_branch_without_upstream(dev: Path) -> None:
    """11/6・11/7 に止まった形（追跡先なし＋作業途中の変更）。"""
    git(dev, "checkout", "-q", "-b", "fix/wip")
    (dev / "a.txt").write_text("wip\n")
    (dev / "new.txt").write_text("untracked\n")
    assert git(dev, "pull", "--ff-only", check=False).returncode != 0  # 古いやり方なら止まる


def on_main(dev: Path) -> None:
    pass


def on_detached_head(dev: Path) -> None:
    git(dev, "checkout", "-q", "--detach")


def in_merge_conflict(dev: Path) -> None:
    git(dev, "checkout", "-q", "-b", "side")
    commit(dev, "a.txt", "side\n")
    git(dev, "checkout", "-q", "-b", "other", "HEAD~1")
    commit(dev, "a.txt", "other\n")
    assert git(dev, "merge", "side", check=False).returncode != 0


def state(dev: Path) -> tuple[str, str, str]:
    return (
        git(dev, "rev-parse", "HEAD").stdout,
        git(dev, "symbolic-ref", "-q", "HEAD", check=False).stdout,
        git(dev, "status", "--porcelain").stdout,
    )


def run_daily(run: Path, tmp_path: Path, sent: list[bytes]) -> tuple[int, list[str]]:
    cfg = Config(data_dir=tmp_path / "data", repo_dir=run, raw={"ntfy": {"topic": "t"}})
    argv: list[str] = []
    rc = daily.main(
        [],
        cfg=cfg,
        run=lambda c, d: pytest.fail("起動し直す前に本処理をした"),
        execv=lambda prog, a: argv.extend(a),
        poster=lambda u, b: sent.append(b),
        runner=lambda cmd, **kw: subprocess.run(cmd, env=ENV, **kw),
    )
    return rc, argv


@pytest.mark.parametrize("prepare", [on_branch_without_upstream, on_main, on_detached_head, in_merge_conflict])
def test_daily_ignores_dev_clone_state(repos, tmp_path, prepare):
    dev, up, run = repos
    prepare(dev)
    before = state(dev)
    new = commit(up, "b.txt", "new\n")
    git(up, "push", "-q", "origin", "main")

    sent: list[bytes] = []
    rc, argv = run_daily(run, tmp_path, sent)

    assert rc == 0 and sent == [] and "--pulled" in argv  # 新しいコードで起動し直す
    assert git(run, "rev-parse", "HEAD").stdout.strip() == new and (run / "b.txt").exists()
    assert state(dev) == before  # 開発用のクローンは動かない


def test_daily_runs_twice_while_dev_clone_sits_on_main(repos, tmp_path):
    """開発用のクローンが main を開いていても（同じブランチは2か所で開けない）毎日動く。"""
    dev, up, run = repos
    assert git(dev, "branch", "--show-current").stdout.strip() == "main"
    for name in ("b.txt", "c.txt"):
        new = commit(up, name, "x\n")
        git(up, "push", "-q", "origin", "main")
        rc, _ = run_daily(run, tmp_path, [])
        assert rc == 0 and git(run, "rev-parse", "HEAD").stdout.strip() == new


def test_daily_refuses_a_normal_clone(repos, tmp_path):
    """config が開発用のクローンを指したままなら、動かさずに失敗を知らせる。"""
    dev, up, _run = repos
    on_branch_without_upstream(dev)
    before = state(dev)
    sent: list[bytes] = []
    rc, argv = run_daily(dev, tmp_path, sent)
    assert rc == 1 and argv == [] and len(sent) == 1 and state(dev) == before
