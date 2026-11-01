"""tests/screener 共通: 架空データ（fixtures/make_fixtures.py）を一時ディレクトリに作り、そこを指す config.toml を使う。
通信・キー・キーチェーン・ntfy・git は使わない（すべて差し替える）。"""

import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE / "fixtures") not in sys.path:
    sys.path.insert(0, str(HERE / "fixtures"))

from screener import config  # noqa: E402

CONFIG_TOML = """
[paths]
data_dir = "{data}"
repo_dir = "{repo}"
[jquants]
keychain_service = "screener-test"
rate_per_min = 50
history_years = 1
[ntfy]
server = "https://ntfy.example.invalid"
topic = "screener-testtopic"
"""


@pytest.fixture(scope="session")
def fixture_src(tmp_path_factory):
    import make_fixtures

    return make_fixtures.make(tmp_path_factory.mktemp("fixtures"))


@pytest.fixture
def cfg(fixture_src, tmp_path, monkeypatch):
    """架空データの作業コピー（<tmp>/data）+ config.toml。戻り値は Config。"""
    data = tmp_path / "data"
    shutil.copytree(fixture_src, data)
    repo = tmp_path / "repo"
    repo.mkdir()
    p = tmp_path / "config.toml"
    p.write_text(CONFIG_TOML.format(data=data, repo=repo))
    monkeypatch.setenv("SCREENER_CONFIG", str(p))
    monkeypatch.delenv("JQ", raising=False)
    from screener.us import screen as us_screen

    us_screen.clear_cache()
    return config.load(p)
