"""日本株（全銘柄）と米国株: チャート判定 × 割安度 → 総合判定 A/B/C と、検証（イベントスタディ）。

総合判定（日本株）: backtest_value.with_chart で検証した定義
  A = 割安5分の1（screener.japan.screen.value_quintile = cheap_quintile:
      プライム・スタンダード / 金融を除く / 時価総額300億円以上 の中で 上値余地が上位20%）
      かつ チャートが買い系（買い / 強い買い / 買い（長期の売られすぎ））
  B = どちらか一方だけ
  C = それ以外
  品質の候補（長期候補・中期候補）は総合判定に使わず、別の列 quality_candidate に残す。
総合判定（米国株）: 理論株価の余地が無いので 割安側 = 財務判定の「割安×質 上位50」「中期候補」（従来どおり）。
検証: 判定が出た日から 20 営業日後の騰落を、全期間の平均（基準）と同じ方法で比べる（calc.events）。
  日本株は A の定義そのもの（その月初の割安5分の1 × 買い系）の成績も出す（verify_local.json の jp.grade_A）。
日付は直書きしない（手元の bars_/master_ と今日から決める）。一覧のファイルは書かない（local_report が書く）。
"""

from __future__ import annotations

import bisect
import datetime as dt
import json
import os
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


def overall(chart_label: str | None, cheap: bool) -> str:
    """総合判定 A/B/C。cheap = 日本株は割安5分の1（cheap_quintile）、米国株は US_CANDIDATES のどれか。"""
    buy = (chart_label or "") in BUY_LABELS
    if buy and cheap:
        return "A"
    if buy or cheap:
        return "B"
    return "C"


def tags_in(fin_tag: str | None, candidates: tuple[str, ...]) -> str:
    """財務判定のうち candidates に入るものだけ（'a|b'）。"""
    return labels.SEP.join(t for t in (fin_tag or "").split(labels.SEP) if t in candidates)


QUINTILE_CACHE = "value_quintile_v1"  # 定義を変えたら名前を変える（古い控えを使わない）


def monthly_quintiles(cfg: Config) -> dict[str, dict[str, str]]:
    """months.json の各月初の 割安5分の1（{月初: {code: cheap_quintile/middle/expensive_quintile}}）。
    過去の月初は変わらないので <data_dir>/japan/derived/ に控える（J-Quants 由来・ローカルだけ）。"""
    mp = cfg.jp("months.json")
    if not mp.exists():
        return {}
    out: dict[str, dict[str, str]] = {}
    cdir = cfg.jp("derived", QUINTILE_CACHE)
    for d in _load(str(mp)):
        cp = cdir / f"{d}.json"
        if cp.exists():
            out[d] = _load(str(cp))
            continue
        master = cfg.jp(f"master_{d}.json")
        if not master.exists() or not cfg.jp(f"bars_{d}.json").exists():
            continue
        out[d] = screen.value_quintile(screen.screen(d, d, d, d, str(master), cfg=cfg))
        cdir.mkdir(parents=True, exist_ok=True)
        tmp = cp.with_name(cp.name + ".tmp")
        tmp.write_text(json.dumps(out[d]))
        os.replace(tmp, cp)
    return out


def cheap_days(code: str, ds: list[str], vq: dict[str, dict[str, str]]) -> np.ndarray:
    """各日がその日以前で最も近い月初の評価で 割安5分の1 か（bool 配列。評価の無い日は False）。"""
    vm = sorted(vq)
    out = np.zeros(len(ds), bool)
    for i, d in enumerate(ds):
        k = bisect.bisect_right(vm, d) - 1
        out[i] = k >= 0 and vq[vm[k]].get(code) == "cheap_quintile"
    return out


def _load(p: str) -> Any:
    with open(p) as fh:
        return json.load(fh)


def build_jp(cfg: Config, asof: str | None = None) -> tuple[list[Row], Xs, list[str], tuple[str, ...]]:
    a = jp_anchor_dates(cfg, asof)
    master = {m["Code"][:4]: m for m in _load(a[4])}
    dates, panel = load_panel(cfg)
    vrows = screen.screen(*a, cfg=cfg)
    val = {r["code"]: r for r in vrows}
    vq = screen.value_quintile(vrows)
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
                "grade": overall(j["label"], vq.get(c) == "cheap_quintile"),
                "chart_signal": j["label"],
                "trend": j["trend"],
                "bb48_z": j["zS"],
                "bb288_z": j["zL"],
                "cci48": j["cciS"],
                "cci288": j["cciL"],
                "price": round(float(x["c"][-1]), 1),
                "fair_price": v.get("fair_price"),
                "upside_pct": v.get("upside_pct"),
                "value_quintile": vq.get(c),
                "quality_candidate": tags_in(fin, JP_CANDIDATES),
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
                "grade": overall(j["label"], bool(tags_in(fin, US_CANDIDATES))),
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


def buy_type(x: dict[str, Any]) -> np.ndarray:
    """買い系（judge() の label が BUY_LABELS になる日）の bool 配列。"""
    lc = ind.label_conditions(x)
    return np.asarray(lc[BUY_LABELS[0]] | lc[BUY_LABELS[1]] | lc[BUY_LABELS[2]], bool)


def _grade_a(
    xs: Xs, since: str, vq: dict[str, dict[str, str]], base: dict[str, Any], base6m: dict[str, Any]
) -> dict[str, Any]:
    """A の定義そのもの（その月初の割安5分の1 × 買い系）の 20営業日後。
    比べる相手: 全銘柄の基準（verify の base と同じもの）と、割安5分の1にいた日すべて（cheap_quintile_days）。"""
    full: dict[str, list[float]] = {}
    recent: dict[str, list[float]] = {}
    for code, (x, ds) in xs.items():
        cheap = cheap_days(code, ds, vq)
        if not cheap.any():
            continue
        conds = {"grade_A": cheap & buy_type(x), "cheap_quintile_days": cheap}
        events.merge(full, events.event_returns(x["c"], conds))
        events.merge(recent, events.event_returns(x["c"], conds, dates=ds, since=since))
    keys = ("grade_A", "cheap_quintile_days")
    fs = {k: events.stats(full.get(k, [])) for k in keys} | {"base": base}
    rs = {k: events.stats(recent.get(k, [])) for k in keys} | {"base": base6m}
    return {
        "definition": "cheap_quintile_x_buy_type",
        "valuation_months": len(vq),
        "full": fs,
        "recent6m": rs,
        "median_below_base": {
            "full": events.weakened(fs["grade_A"], base),
            "recent6m": events.weakened(rs["grade_A"], base6m),
        },
    }


def verify(xs: Xs, since: str, vq: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
    """20営業日後の騰落を全期間の平均（基準）と比べる。全期間と直近6か月。
    vq（月初ごとの割安5分の1）を渡すと A の定義そのものの成績（grade_A）も出す。
    「根拠が弱まっています」の判定（weakened）の規則は変えない（buy / long_oversold だけ）。"""
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
    out = {"full": fs, "recent6m": rs, "weakened_by": weak, "weakened": any(v is True for v in weak.values())}
    if vq is not None:
        out["grade_A"] = _grade_a(xs, since, vq, fs.get("base", {}), rs.get("base", {}))
    return out


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
        "jp": verify(jx, since, monthly_quintiles(cfg)),
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
