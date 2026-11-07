"""判定の記録帳の答え合わせ（実際の運用での成績・live）。データ・通信は持たない。

記録 1 件 = その日の 1 銘柄の判定:
  {"d": 日付, "m": 市場 jp|us|etf, "s": 銘柄, "sig": チャート判定, "c2": CCI ±200 の判定,
   "t": 段階, "sc": スコア, "px": 終値}
答え合わせ = その銘柄の日足で、その日の終値から HORIZON 本あと（営業日）の終値までの値動き（%）。
Mac mini（~/screener-data/history/YYYY.parquet）だけが使う。公開側には出さない。
バックテスト（verify の full・recent6m）と違い、その日に実際に出した判定だけを数える。
同じ銘柄が続けて同じ判定なら毎日 1 件と数える（検証の「20 日に 1 回」とは件数の意味が違う）。
"""

from __future__ import annotations

import bisect
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

import numpy as np

HORIZON = 20  # 20 営業日後
RECORD_KEYS = ("d", "m", "s", "sig", "c2", "t", "sc", "px")
MARKETS = ("jp", "us", "etf")
TIER_KEYS = ("tier5", "tier4", "tier3", "tier2", "tier1")


def stats(xs: Sequence[float]) -> dict[str, Any]:
    """値動き（%）の列 → {n, median, mean, up_pct}（件数 0 なら n だけ）。"""
    a = np.asarray([x for x in xs if x is not None and np.isfinite(x)], dtype=float)
    if not len(a):
        return {"n": 0}
    return {
        "n": int(len(a)),
        "median": round(float(np.median(a)), 2),
        "mean": round(float(a.mean()), 2),
        "up_pct": round(float((a > 0).mean() * 100), 1),
    }


def forward_return(dates: Sequence[str], closes: Sequence[Any], d: str, horizon: int = HORIZON) -> float | None:
    """d の終値（d 以前で最も近い日）→ horizon 本あとの終値の値動き%。まだ来ていなければ None。"""
    i = bisect.bisect_right(list(dates), d) - 1
    j = i + horizon
    if i < 0 or j >= len(dates):
        return None
    a, b = closes[i], closes[j]
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if not (np.isfinite(a) and np.isfinite(b)) or a <= 0:
        return None
    return (b / a - 1) * 100


def live_stats(
    records: Iterable[Mapping[str, Any]],
    series: Callable[[str, str], tuple[Sequence[str], Sequence[Any]] | None],
    horizon: int = HORIZON,
) -> dict[str, Any]:
    """記録 → 実際の運用での成績。series(市場, 銘柄) は (日付の列, 終値の列)（昇順）。
    市場ごとに 基準（その市場の記録すべて）・段階別・チャート判定別・CCI ±200 別の 20 営業日後の成績。"""
    recs = [r for r in records if r.get("d") and r.get("m") and r.get("s")]
    out: dict[str, Any] = {
        "horizon": horizon,
        "start": min((r["d"] for r in recs), default=None),
        "asof": max((r["d"] for r in recs), default=None),
        "records": len(recs),
        "matured": 0,
        "markets": {},
    }
    cache: dict[tuple[str, str], Any] = {}
    groups: dict[str, dict[str, dict[str, list[float]]]] = {}
    for r in recs:
        k = (str(r["m"]), str(r["s"]))
        if k not in cache:
            cache[k] = series(*k)
        sr = cache[k]
        fr = forward_return(sr[0], sr[1], str(r["d"]), horizon) if sr else None
        g = groups.setdefault(k[0], {"base": {}, "tiers": {}, "signals": {}, "cci200": {}})
        g["base"].setdefault("all", [])
        if fr is None:
            continue
        out["matured"] += 1
        g["base"]["all"].append(fr)
        if r.get("t") is not None:
            g["tiers"].setdefault(f"tier{int(r['t'])}", []).append(fr)
        if r.get("sig"):
            g["signals"].setdefault(str(r["sig"]), []).append(fr)
        if r.get("c2"):
            g["cci200"].setdefault(str(r["c2"]), []).append(fr)
    for m, g in groups.items():
        out["markets"][m] = {
            "records": sum(1 for r in recs if r["m"] == m),
            "base": stats(g["base"]["all"]),
            "tiers": {k: stats(g["tiers"].get(k, [])) for k in TIER_KEYS},
            "signals": {k: stats(v) for k, v in sorted(g["signals"].items())},
            "cci200": {k: stats(v) for k, v in sorted(g["cci200"].items())},
        }
    return out


def series_from_records(records: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], tuple[list[str], list[Any]]]:
    """記録そのものの終値から (市場, 銘柄) → (日付, 終値)。日足が無くなった銘柄の代わりに使う
    （記録の無い日があると 20 本あとがずれ、株式分割も調整されない）。"""
    by: dict[tuple[str, str], dict[str, Any]] = {}
    for r in records:
        if r.get("d") and r.get("px") is not None:
            by.setdefault((str(r["m"]), str(r["s"])), {})[str(r["d"])] = r["px"]
    return {k: (sorted(v), [v[d] for d in sorted(v)]) for k, v in by.items()}
