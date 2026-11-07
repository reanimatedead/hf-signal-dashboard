"""scripts/install_macmini.sh: キーをファイル・ログ・画面に出す行が無い・
毎日の実行は専用の作業ツリー ~/hf-signal-dashboard-run・bash -n・shellcheck。"""

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install_macmini.sh"


def _lines():
    return [ln for ln in SCRIPT.read_text().splitlines() if not ln.lstrip().startswith("#")]


def test_key_never_written_to_file_or_log():
    bad = []
    for ln in _lines():
        if "KEY" not in ln:
            continue
        if re.search(r"(echo|printf)[^\n]*\$\{?KEY", ln):  # 画面・ログへ
            bad.append(ln)
        if re.search(r"\$\{?KEY\}?[^\n]*(>|>>)", ln) or re.search(r"(>|>>)[^\n]*\$\{?KEY", ln):  # ファイルへ
            bad.append(ln)
        if re.search(r"\btee\b", ln) or re.search(r"<<<", ln):
            bad.append(ln)
    assert not bad, bad
    text = "\n".join(_lines())
    # キーは security 自身に対話入力させる（-w を値なしで最後に置く）。引数（ps で見える）に載せない
    assert re.search(r'security add-generic-password -U -s "\$SERVICE" -a "\$USER" -w( |$)', text, re.M)
    assert "$KEY" not in text and "read -rs" not in text
    assert "set -x" not in text


def test_no_tee_anywhere():
    assert not any(re.search(r"\btee\b", ln) for ln in _lines())


def test_daily_runs_in_dedicated_worktree():
    text = SCRIPT.read_text()
    assert 'REPO_DIR="$HOME/hf-signal-dashboard"' in text and 'RUN_DIR="$HOME/hf-signal-dashboard-run"' in text
    assert 'worktree add --detach "$RUN_DIR" origin/main' in text
    assert "<key>WorkingDirectory</key><string>$RUN_DIR</string>" in text
    assert "<string>--project</string>\n    <string>$RUN_DIR</string>" in text and "screener.daily" in text
    assert '--repo-dir "$RUN_DIR"' in text
    assert "<string>$REPO_DIR</string>" not in text  # launchd は開発用のクローンを見ない
    assert '[ "$branch" = "main" ]' not in text  # 開発用のクローンのブランチでは止めない


def test_schedule_and_wake():
    text = SCRIPT.read_text()
    assert "<key>Hour</key><integer>19</integer>" in text and "<key>Minute</key><integer>0</integer>" in text
    assert "sudo pmset repeat wakeorpoweron MTWRFSU 18:55:00" in text
    assert 'TOPIC="screener-$(openssl rand -hex 16)"' in text
    assert "launchctl bootstrap" in text and "$DATA_DIR/logs/" in text


def test_bash_syntax():
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck が無い（pip install shellcheck-py）")
def test_shellcheck():
    r = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def _run_script(home: Path) -> subprocess.CompletedProcess[str]:
    """本物のスクリプトを、外に触るコマンドだけ差し替えて最後まで動かす（uv は本物の設定コードを呼ぶ）。"""
    (home / "hf-signal-dashboard" / ".git").mkdir(parents=True, exist_ok=True)
    (home / "hf-signal-dashboard-run").mkdir(exist_ok=True)
    (home / "hf-signal-dashboard-run" / ".git").write_text("gitdir: x\n")
    b = home / "bin"
    b.mkdir(exist_ok=True)
    stubs = {
        "git": "exit 0",
        "security": "exit 0",
        "plutil": "exit 0",
        "launchctl": "exit 0",
        "sudo": "exit 0",
        "pmset": "exit 0",
        "openssl": "echo 0123456789abcdef0123456789abcdef",
        "uv": f"""[ "$1" = sync ] && exit 0
shift; [ "$1" = python ] && shift
[ "$2" = screener.notify ] && exit 0
PYTHONPATH="{ROOT / "src"}" exec "{sys.executable}" "$@\"""",
    }
    for name, body in stubs.items():
        (b / name).write_text(f"#!/usr/bin/env bash\n{body}\n")
        (b / name).chmod(0o755)
    env = {"HOME": str(home), "PATH": f"{b}:/usr/bin:/bin", "USER": "t"}
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, cwd=home)


def test_rerun_keeps_existing_config_and_adds_only_missing(tmp_path):
    conf = tmp_path / ".config" / "screener" / "config.toml"
    conf.parent.mkdir(parents=True)
    conf.write_text(
        """# 自分のメモ
[paths]
data_dir = "/my/data"
repo_dir = "/my/run"

[ntfy]
topic = "screener-abc123"

[edgar]
user_agent = "me example@example.com"

[alerts]
sound_enabled = false
sound_spike = "Hero"
watchlist = ["7203"]
"""
    )
    conf.chmod(0o600)
    r = _run_script(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    text = conf.read_text()
    c = tomllib.loads(text)
    assert text.startswith("# 自分のメモ")
    assert c["paths"] == {"data_dir": "/my/data", "repo_dir": "/my/run"}
    assert c["ntfy"]["topic"] == "screener-abc123" and c["ntfy"]["server"] == "https://ntfy.sh"
    assert c["edgar"]["user_agent"] == "me example@example.com"
    assert c["alerts"]["sound_enabled"] is False and c["alerts"]["sound_spike"] == "Hero"
    assert c["alerts"]["watchlist"] == ["7203"] and c["alerts"]["sound_signal"] == "Glass"  # 足りない項目だけ足す
    assert c["jquants"]["keychain_service"] == "screener-jquants"
    assert (conf.stat().st_mode & 0o777) == 0o600
    assert "repo_dir は既存の値のまま" in r.stderr
    before = conf.read_text()
    assert _run_script(tmp_path).returncode == 0 and conf.read_text() == before  # 何度実行しても同じ


def test_first_install_creates_config(tmp_path):
    r = _run_script(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    conf = tmp_path / ".config" / "screener" / "config.toml"
    c = tomllib.loads(conf.read_text())
    assert c["paths"]["repo_dir"] == str(tmp_path / "hf-signal-dashboard-run")
    assert c["ntfy"]["topic"] == "screener-0123456789abcdef0123456789abcdef"
    assert c["alerts"]["sound_spike"] == "Sosumi" and (conf.stat().st_mode & 0o777) == 0o600


def test_broken_config_is_not_overwritten(tmp_path):
    conf = tmp_path / ".config" / "screener" / "config.toml"
    conf.parent.mkdir(parents=True)
    conf.write_text("[alerts\nbroken")
    r = _run_script(tmp_path)
    assert r.returncode != 0 and conf.read_text() == "[alerts\nbroken"
