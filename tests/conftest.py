import sys
import pathlib

# Allow imports of top-level modules like fetch_signals from tests/
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# src/screener（uv sync 無しの python3 -m pytest でも import できるように）
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
