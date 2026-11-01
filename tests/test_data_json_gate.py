"""tests/_data_json_gate.py: 生成物が無いとき、通常は skip・REQUIRE_DATA_JSON=1 なら fail。"""
import pytest

from tests import _data_json_gate as g


def test_missing_without_env_skips():
    with pytest.raises(pytest.skip.Exception) as e:
        g.gate(["data.json"], env={})
    assert "docs/data.json がない（生成は deploy.yml の full ジョブで行う。オフラインでは作れない）" in str(e.value)


def test_missing_with_require_env_fails():
    with pytest.raises(pytest.fail.Exception) as e:
        g.gate(["data.json"], env={"REQUIRE_DATA_JSON": "1"})
    assert "docs/data.json" in str(e.value)


def test_present_does_nothing(tmp_path):
    (tmp_path / "data.json").write_text("{}")
    assert g.missing_files(["data.json"], docs=tmp_path) == []
    g.gate([], env={"REQUIRE_DATA_JSON": "1"})


def test_required_files_detects_generated_names():
    def t1():
        _load("data.json")  # noqa: F821

    def t2():
        _load(f"charts/{tab}.json")  # noqa: F821

    def t3():
        _read_index()  # noqa: F821

    assert g.required_files(t1) == ["data.json"]
    assert g.required_files(t2) == ["data.json"]
    assert g.required_files(t3) == []
