"""日本株（全銘柄）と米国株: チャート判定 × 財務判定 → 総合判定 A/B/C と、検証（イベントスタディ）。

総合判定:
  A = チャートが買い系（買い / 強い買い / 買い（長期の売られすぎ））かつ 財務判定に「長期候補」か「中期候補」
  B = チャートが買い系だけ、または 財務判定の候補だけ
  C = それ以外
  米国は財務判定の候補 = 「割安×質 上位50」「中期候補」で同じ規則。
検証: 判定が出た日から 20 営業日後の騰落を、全期間の平均（基準）と同じ方法で比べる（calc.events）。
日付は直書きしない（手元の bars_/master_ と今日から決める）。ファイルは書かない（local_report が書く）。
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import numpy as np

from .. import labels
from ..calc import events, fund_us, ind
from ..config import Config
from ..dates import jp_anchor_dates, minus
from ..us import make_value
from ..us import screen as us_screen
from . import screen
from .panel import load_panel

BUY_LABELS = ind.BUY_LABELS
JP_CANDIDATES = ("long_candidate", "mid_candidate")
US_CANDIDATES = ("value_quality_top50", "mid_candidate")
Row = dict[str, Any]
Xs = dict[str, tuple[dict[str, Any], list[str]]]


def overall(chart_label: str | None, fin_tag: str | None, candidates: tuple[str, ...] = JP_CANDIDATES) -> str:
    """総合判定 A/B/C。"""
    buy = (chart_label or "") in BUY_LABELS
    cand = any(c in (fin_tag or "").split(labels.SEP) for c in candidates)
    if buy and cand:
        return "A"
    if buy or cand:
        return "B"
    return "C"


def _load(p: str) -> Any:
    with open(p) as fh:
        return json.load(fh)


def build_jp(cfg: Config, asof: str | None = None) -> tuple[list[Row], Xs, list[str], tuple[str, ...]]:
    a = jp_anchor_dates(cfg, asof)
    master = {m["Code"][:4]: m for m in _load(a[4])}
    dates, panel = load_panel(cfg)
    val = {r["code"]: r for r in screen.screen(*a, cfg=cfg)}
    rows: list[Row] = []
    xs: Xs = {}
    for c, (h, low, cl) in panel.items():
        m = master.get(c)
        if not m or m.get("S17") == "99" or m.get("MktNm") not in screen.MARKETS:
            continue
        if np.sum(~np.isnan(cl)) < ind.MIN_BARS or np.isnan(cl[-1]):
            continue
        x = ind.compute(h, low, cl)
        j = ind.judge(x)
        v = val.get(c, {})
        xs[c] = (x, [d for d, o in zip(dates, x["ok"], strict=False) if o])
        fin = v.get("fin_tag", "")
        rows.append(
            {
                "code": c,
                "company_name": m["CoName"],
                "market": m["MktNm"],
                "sector": m["S33Nm"],
                "grade": overall(j["label"], fin, JP_CANDIDATES),
                "chart_signal": j["label"],
                "trend": j["trend"],
                "bb48_z": j["zS"],
                "bb288_z": j["zL"],
                "cci48": j["cciS"],
                "cci288": j["cciL"],
                "price": round(float(x["c"][-1]), 1),
                "fair_price": v.get("fair_price"),
                "upside_pct": v.get("upside_pct"),
                "PBR": v.get("PBR"),
                "F": v.get("F"),
                "f_max": v.get("f_max"),
                "magic_rank": v.get("magic_rank"),
                "fin_tag": fin,
                "mcap_oku_jpy": v.get("mcap_oku_jpy"),
                "one_off_flag": bool(v.get("one_off_flag")),
                "one_off_note": v.get("one_off_note", ""),
                "one_off_reasons": v.get("one_off_reasons", ""),
            }
        )
    return rows, xs, dates, a


def _arr(v: list[Any]) -> np.ndarray:
    return np.array([np.nan if t is None else t for t in v], float)


def build_us(cfg: Config, today: dt.date) -> tuple[list[Row], Xs]:
    usv = {r["ticker"]: r for r in make_value.build(cfg, today)}
    rows: list[Row] = []
    xs: Xs = {}
    for t, info in us_screen.universe(cfg).items():
        px = us_screen.load_px(t, cfg)
        if not px:
            continue
        C = _arr(px["c"])
        H = _arr(px["h"] or px["c"])
        L = _arr(px["l"] or px["c"])
        if np.sum(~np.isnan(C)) < ind.MIN_BARS:
            continue
        x = ind.compute(H, L, C)
        j = ind.judge(x)
        v = usv.get(t, {})
        xs[t] = (x, [d for d, o in zip(px["d"], x["ok"], strict=False) if o])
        fin = v.get("fin_tag", "")
        rows.append(
            {
                "ticker": t,
                "name": info.get("name", t),
                "idx": "/".join(info.get("idx", [])),
                "sector": info.get("sector", ""),
                "grade": overall(j["label"], fin, US_CANDIDATES),
                "chart_signal": j["label"],
                "trend": j["trend"],
                "bb48_z": j["zS"],
                "bb288_z": j["zL"],
                "cci48": j["cciS"],
                "cci288": j["cciL"],
                "price": round(float(x["c"][-1]), 2),
                "fin_tag": fin,
                "magic_rank": v.get("magic_rank"),
                "F": v.get("F"),
                "f_max": v.get("f_max"),
                "fin": fund_us.is_fin(info.get("sector")),
            }
        )
    return rows, xs


def verify(xs: Xs, since: str) -> dict[str, Any]:
    """20営業日後の騰落を全期間の平均（基準）と比べる。全期間と直近6か月。"""
    full: dict[str, list[float]] = {}
    recent: dict[str, list[float]] = {}
    for x, ds in xs.values():
        s = ind.signals(x)
        lo = ind.long_oversold(x)
        conds = {"buy": s >= 1, "buy3": s == 2, "long_oversold": lo, "sell": s <= -1}
        events.merge(full, events.event_returns(x["c"], conds))
        events.merge(recent, events.event_returns(x["c"], conds, dates=ds, since=since))
    fs = {k: events.stats(v) for k, v in full.items()}
    rs = {k: events.stats(v) for k, v in recent.items()}
    weak = {k: events.weakened(rs.get(k), rs.get("base", {})) for k in ("buy", "long_oversold")} if rs else {}
    return {"full": fs, "recent6m": rs, "weakened_by": weak, "weakened": any(v is True for v in weak.values())}


def run(cfg: Config, asof: str | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.UTC)
    jp, jx, dates, anchors = build_jp(cfg, asof)
    today = dates[-1] if dates else anchors[1]
    us, ux = build_us(cfg, dt.date.fromisoformat(today) + dt.timedelta(days=1))
    since = minus(today, months=6).isoformat()
    v: dict[str, Any] = {
        "computed_at": now.isoformat(timespec="seconds"),
        "horizon_days": events.H,
        "gap_days": events.GAP,
        "recent_since": since,
        "period": [dates[min(events.WARMUP, len(dates) - 1)] if dates else None, today],
        "jp": verify(jx, since),
        "us": verify(ux, since),
    }
    v["weakened"] = bool(v["jp"]["weakened"] or v["us"]["weakened"])
    return {
        "asof": today,
        "generated_at": now.isoformat(timespec="seconds"),
        "anchors": {"asof": anchors[0], "px": anchors[1], "p1y": anchors[2], "p1m": anchors[3]},
        "jp": jp,
        "us": us,
        "verify": v,
    }
