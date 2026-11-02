"""tools/pull_live_base.py（corr_refresh の土台）: 画面が読む JSON は full だけが作るものも全部持ち越す。

corr_refresh は Pages を丸ごと置き換えるので、持ち越さなかったファイルは公開サイトから消える
（2026-11-02: verify.json が抜けていて 11:00 の corr_refresh が消していた）。
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import pull_live_base as plb  # noqa: E402


def _page_json_files():
    src = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    for js in (ROOT / "docs" / "assets").rglob("*.js"):
        src += js.read_text(encoding="utf-8")
    return set(re.findall(r'fetch\(\s*["\']([A-Za-z0-9_]+\.json)', src))


def test_every_root_json_the_page_reads_is_carried_forward():
    files = _page_json_files()
    assert "verify.json" in files and "data.json" in files
    missing = files - {"data.json"} - set(plb.LAYER_FILES)  # data.json は別に必ず取る
    assert not missing, f"corr_refresh が公開サイトから消してしまう: {sorted(missing)}"
