"""互換の薄い再エクスポート。式は src/screener/calc/ にだけある（ここに書かない）。

既存の `from marketcalc import ind` / `from marketcalc.contracts import ...`
（fetch_signals.py・pipeline/・tools/）を壊さないため、src/ を sys.path に入れて
screener.calc のモジュールをそのまま marketcalc.* として見せる。
"""
import pathlib
import sys

_SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from screener.calc import contracts, events, fund_us, ind, value  # noqa: E402

for _m in (contracts, events, fund_us, ind, value):
    sys.modules[f"{__name__}.{_m.__name__.rsplit('.', 1)[-1]}"] = _m

__all__ = ["contracts", "events", "fund_us", "ind", "value"]
