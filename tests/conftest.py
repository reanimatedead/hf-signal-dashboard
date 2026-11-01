import sys
import pathlib

import pytest

# Allow imports of top-level modules like fetch_signals from tests/
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# src/screener（uv sync 無しの python3 -m pytest でも import できるように）
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tests import _data_json_gate as gate  # noqa: E402


def pytest_collection_modifyitems(config, items):
    """生成物（docs/data.json など）を読むテストに marker needs_data_json を付ける。"""
    for item in items:
        if item.path.name not in gate.MODULES:
            continue
        need = gate.required_files(getattr(item, "function", None))
        if need:
            item.add_marker(pytest.mark.needs_data_json(files=need))


def pytest_runtest_setup(item):
    m = item.get_closest_marker("needs_data_json")
    if m is not None:
        gate.gate(gate.missing_files(list(m.kwargs.get("files") or ["data.json"])))
