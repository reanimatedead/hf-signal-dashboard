"""通知の secret がリポに混入しない (SPEC_NOTIFY §0, §10.2).

- 実 ntfy topic 値 / API key / Bearer Token / Gmail OAuth 文字列 が git 管理下に無い。
- config.local 実体ファイルが追跡されていない (.gitignore で除外)。
- SPEC は example token を "hf-XXX" placeholder で書く方針。
"""
import os
import pathlib
import re
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _tracked_files():
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT).decode("utf-8")
    return [ROOT / line for line in out.splitlines() if line]


def test_config_local_is_not_tracked():
    files = _tracked_files()
    bad = [p for p in files if p.name == "config.local" or p.name.startswith("config.local.")
           and not p.name.endswith(".example")]
    assert not bad, f"config.local* file is tracked (must be .gitignore'd): {bad}"


SECRET_PATTERNS = [
    r"AIza[0-9A-Za-z_\-]{20,}",                   # Google API key
    r"AKIA[0-9A-Z]{16}",                          # AWS access key id
    r"ghp_[A-Za-z0-9]{20,}",                      # GitHub PAT
    r"xox[baprs]-[A-Za-z0-9-]{10,}",              # Slack
    r"sk-[A-Za-z0-9]{20,}",                       # OpenAI / similar
    r"Bearer\s+[A-Za-z0-9\-_=]{20,}",
    r"ya29\.[A-Za-z0-9\-_]{20,}",                 # Google OAuth
]


def test_no_obvious_secret_in_tracked_files():
    files = _tracked_files()
    hits = []
    for p in files:
        if not p.is_file():
            continue
        if p.suffix in (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".pdf",
                        ".duckdb", ".parquet"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for pat in SECRET_PATTERNS:
            for m in re.finditer(pat, text):
                hits.append((str(p.relative_to(ROOT)), pat, m.group(0)[:30]))
    assert not hits, f"possible secret-like tokens in tracked files: {hits[:5]}"


def test_no_hardcoded_ntfy_topic():
    """ntfy_topic は config.local のみ。リポに `ntfy.sh/hf-<具体的な>` がコミットされていない。"""
    files = _tracked_files()
    bad = []
    for p in files:
        if not p.is_file():
            continue
        if p.suffix in (".png", ".jpg", ".jpeg", ".svg"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in re.finditer(r"ntfy\.sh/(hf-[A-Za-z0-9_\-]{8,})", text):
            tok = m.group(1).lower()
            # placeholders are allowed
            if tok in ("hf-xxx", "hf-secret-topic", "hf-test", "hf-x", "hf-<random-string-32-chars>"):
                continue
            bad.append((str(p.relative_to(ROOT)), tok))
    assert not bad, f"hardcoded ntfy topic in repo: {bad}"


def test_config_example_documents_notify_keys():
    ex = ROOT / "config.local.json.example"
    assert ex.exists(), "config.local.json.example must exist as docs"
    body = ex.read_text(encoding="utf-8")
    for k in ("notify_enabled", "ntfy_topic"):
        assert k in body, f"config.local.json.example must document key: {k}"
