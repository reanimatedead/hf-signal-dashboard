"""FX（公開サイトと同じ18通貨ペア）と仮想通貨（同じ4つ）の日足を Mac mini に持つ（CCI ±200 の通知用）。

保存場所: <data_dir>/fx/px/<シンボル>.json（Yahoo chart の JSON。us/fetch と同じ書き方・付け足し）。
取れなかった日（銘柄）は前回のファイルのまま（通知を止めない）。一覧は screener.calc.assets の1か所。

    python -m screener.fxcrypto            # 1か月分を付け足す（毎日）
    python -m screener.fxcrypto --full     # 5年分（初回）
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import numpy as np

from . import config as config_mod
from .calc import assets, fund_us, ind
from .config import Config
from .us import fetch as us_fetch

MARKETS: dict[str, dict[str, str]] = {
    "fx": dict(assets.FX_PAIRS),
    "crypto": dict(assets.CRYPTO),
}


def px_dir(cfg: Config) -> Any:
    return cfg.data_dir / "fx" / "px"


def fetch(cfg: Config, full: bool = False, **kw: Any) -> dict[str, tuple[int, int]]:
    """{市場: (取れた数, 取れなかった数)}。失敗しても例外にしない（前回のまま）。"""
    return {m: us_fetch.fetch_prices(cfg, list(syms), full, dest=px_dir(cfg), **kw) for m, syms in MARKETS.items()}


def _arr(v: list[Any]) -> np.ndarray:
    return np.array([np.nan if t is None else t for t in v], float)


def load(cfg: Config, market: str) -> tuple[dict[str, dict[str, Any]], dict[str, tuple[dict[str, Any], list[str]]]]:
    """(rows, xs)。rows = {シンボル: {name, cci48, cci288}}、xs = {シンボル: (ind.compute の結果, 日付)}。"""
    rows: dict[str, dict[str, Any]] = {}
    xs: dict[str, tuple[dict[str, Any], list[str]]] = {}
    for sym, name in MARKETS[market].items():
        try:
            px = fund_us.parse_yahoo_chart(json.loads((px_dir(cfg) / f"{sym}.json").read_text()))
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            continue
        if not px:
            continue
        C = _arr(px["c"])
        if np.sum(~np.isnan(C)) < ind.MIN_BARS:
            continue
        x = ind.compute(_arr(px["h"] or px["c"]), _arr(px["l"] or px["c"]), C)
        j = ind.judge(x)
        xs[sym] = (x, [d for d, o in zip(px["d"], x["ok"], strict=False) if o])
        rows[sym] = {"name": name, "cci48": j["cciS"], "cci288": j["cciL"]}
    return rows, xs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--full", action="store_true", help="5年分を取り直す")
    a = ap.parse_args(argv)
    print("fx/crypto", fetch(config_mod.load(), a.full), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
