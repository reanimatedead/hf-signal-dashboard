"""判定の記録帳（Mac mini のローカルだけ）: <data_dir>/history/YYYY.parquet。git にも Pages にも入れない。

daily の最後に、その日の全銘柄（日本株・米国株・ETF）の判定・段階・スコア・終値を 1 行ずつ追記する
（同じ日・市場・銘柄は新しい方で置き換え）。日本株の終値・スコアは J-Quants 由来を含むので、ここから外へは出さない。
答え合わせは calc.live（その銘柄の日足で 20 営業日後）→ verify_local.json の live。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .calc import live
from .config import Config
from .local_report import _check_outside_repo

# doc の市場 → (銘柄の列, 名前の列)
MARKETS = {"jp": ("code", "company_name"), "us": ("ticker", "name"), "etf": ("code", "name")}
COLUMNS = (*live.RECORD_KEYS, "name")


def hist_dir(cfg: Config) -> Path:
    return cfg.data_dir / "history"


def records(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """doc（signals.run）→ その日の記録（calc.live.RECORD_KEYS + name）。"""
    d = str(doc.get("asof") or "")[:10]
    out = []
    for m, (key, name) in MARKETS.items():
        for r in doc.get(m) or []:
            s = r.get(key)
            if not s or not d:
                continue
            t = r.get("score_tier")
            out.append(
                {
                    "d": d,
                    "m": m,
                    "s": str(s),
                    "sig": r.get("chart_signal"),
                    "c2": r.get("cci200_signal"),
                    "t": int(t) if t is not None else None,
                    "sc": r.get("score"),
                    "px": r.get("price"),
                    "name": r.get(name),
                }
            )
    return out


def append(cfg: Config, doc: dict[str, Any]) -> Path | None:
    """その日の記録を <data_dir>/history/<年>.parquet に追記して、そのパスを返す（記録が無ければ None）。"""
    import pandas as pd

    rs = records(doc)
    if not rs:
        return None
    p = hist_dir(cfg) / f"{rs[0]['d'][:4]}.parquet"
    _check_outside_repo(p, cfg)
    new = pd.DataFrame(rs, columns=list(COLUMNS))
    if p.exists():
        old = pd.read_parquet(p)
        new = pd.concat([old, new], ignore_index=True).drop_duplicates(["d", "m", "s"], keep="last")
    new = new.sort_values(["d", "m", "s"]).reset_index(drop=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    new.to_parquet(tmp, index=False)
    os.replace(tmp, p)
    return p


def load(cfg: Config) -> list[dict[str, Any]]:
    import pandas as pd

    fs = sorted(hist_dir(cfg).glob("*.parquet"))
    if not fs:
        return []
    df = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    df = df.astype(object).where(df.notna(), None)
    return df.to_dict("records")


def live_summary(cfg: Config, xs: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """記録帳 → 実際の運用での成績（calc.live.live_stats）。xs = {市場: {銘柄: (x, 日付)}}（signals.run の日足）。
    答え合わせは日足で行う（daily が止まった日があっても 20 営業日後がずれず、株式分割も調整済み）。
    日足が無くなった銘柄は記録帳の終値で。"""
    rs = load(cfg)
    ledger = live.series_from_records(rs)

    def series(m: str, s: str) -> tuple[Any, Any] | None:
        v = (xs or {}).get(m, {}).get(s)
        return (list(v[1]), v[0]["c"]) if v else ledger.get((m, s))

    return live.live_stats(rs, series)
