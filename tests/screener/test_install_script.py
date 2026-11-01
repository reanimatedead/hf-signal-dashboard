"""scripts/install_macmini.sh: キーをファイル・ログ・画面に出す行が無い・
リポジトリは ~/hf-signal-dashboard（main）・bash -n・shellcheck。"""

import re
import shutil
import subprocess
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
    assert "read -rs KEY" in text
    assert 'security add-generic-password -U -s "$SERVICE" -a "$USER" -w "$KEY"' in text
    assert re.search(r"security add-generic-password[^\n]*\n\s*unset KEY", text)
    assert "set -x" not in text


def test_no_tee_anywhere():
    assert not any(re.search(r"\btee\b", ln) for ln in _lines())


def test_repo_dir_is_home_hf_signal_dashboard_on_main():
    text = SCRIPT.read_text()
    assert 'REPO_DIR="$HOME/hf-signal-dashboard"' in text
    assert "<key>WorkingDirectory</key><string>$REPO_DIR</string>" in text
    assert "<string>$REPO_DIR</string>" in text and "screener.daily" in text
    assert '[ "$branch" = "main" ]' in text and 'git -C "$REPO_DIR" status --porcelain' in text


def test_no_obsidian_path_in_scripts_or_plist():
    for p in (ROOT / "scripts").rglob("*"):
        if p.is_file():
            assert "Obsidian" not in p.read_text(errors="replace"), p


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
