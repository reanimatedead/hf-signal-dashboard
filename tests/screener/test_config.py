"""screener.config: 既定のデータ置き場は ~/screener-data（リポジトリの外）。
config.toml で変えられる。リポジトリの中は拒否。"""

from pathlib import Path

import pytest

from screener import config


def test_default_data_dir_is_home_not_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SCREENER_CONFIG", raising=False)
    c = config.load()
    assert c.data_dir == tmp_path / "screener-data"
    assert c.repo_dir == tmp_path / "hf-signal-dashboard"
    assert c.out_dir == tmp_path / "screener-data" / "out"
    assert not str(c.data_dir).startswith(str(config.PACKAGE_REPO))
    assert config.default_config_path() == tmp_path / ".config" / "screener" / "config.toml"


def test_override_by_config_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    p = tmp_path / ".config" / "screener" / "config.toml"
    p.parent.mkdir(parents=True)
    p.write_text('[paths]\ndata_dir = "~/elsewhere"\n[ntfy]\ntopic = "screener-abc"\n')
    monkeypatch.delenv("SCREENER_CONFIG", raising=False)
    c = config.load()
    assert c.data_dir == tmp_path / "elsewhere"
    assert c.ntfy_topic == "screener-abc" and c.ntfy_server == "https://ntfy.sh"
    assert c.get("jquants.rate_per_min") == 50


def test_data_dir_inside_repo_is_refused(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(f'[paths]\ndata_dir = "{Path(config.PACKAGE_REPO) / "screener-data"}"\n')
    with pytest.raises(ValueError):
        config.load(p)
    repo = tmp_path / "repo"
    p.write_text(f'[paths]\ndata_dir = "{repo / "d"}"\nrepo_dir = "{repo}"\n')
    with pytest.raises(ValueError):
        config.load(p)
