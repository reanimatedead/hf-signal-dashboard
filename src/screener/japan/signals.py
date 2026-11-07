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

import datetime as dt
import json
from typing import Any

import numpy as np

from .. import alerts, labels
from ..calc import assets, events, fund_us, ind, score
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
    buy = ind.is_buy_type(chart_label)
    if buy and cheap:
        return "A"
    if buy or cheap:
        return "B"
    return "C"


def tags_in(fin_tag: str | None, candidates: tuple[str, ...]) -> str:
    """財務判定のうち candidates に入るものだけ（'a|b'）。"""
    return labels.SEP.join(t for t in (fin_tag or "").split(labels.SEP) if t in candidates)


def _load(p: str) -> Any:
    with open(p) as fh:
        return json.load(fh)


ETF_PROD = ("014", "023")  # J-Quants の銘柄一覧で「市場：その他」の ETF・ETN（013 = REIT は入れない）
ETF_MARKET = "その他"
LOCAL_GATE_KEYS = {ind.LABELS[2]: "buy3", ind.LABELS[1]: "buy", ind.LONG_OVERSOLD_LABEL: "long_oversold"}


def is_etf(m: dict[str, Any]) -> bool:
    return m.get("MktNm") == ETF_MARKET and str(m.get("ProdCat", "")) in ETF_PROD


def _turnover(va: np.ndarray | None, ok: np.ndarray) -> np.ndarray | None:
    """日足の Va（売買代金）→ Close が有限な日だけの 20 日平均（score.rolling_mean）。"""
    if va is None:
        return None
    return score.rolling_mean(np.asarray(va, dtype=float)[ok])


def _last(v: np.ndarray | None) -> float | None:
    if v is None or not len(v) or not np.isfinite(v[-1]):
        return None
    return round(float(v[-1]))


def build_jp(
    cfg: Config, asof: str | None = None, ctx: dict[str, Any] | None = None
) -> tuple[list[Row], Xs, list[str], tuple[str, ...]]:
    """ctx を渡すと 売買スコア用の材料（turnover: {code: (日付, 20日平均)}・disclosures・etf の行と xs）を入れる。"""
    a = jp_anchor_dates(cfg, asof)
    master = {m["Code"][:4]: m for m in _load(a[4])}
    vas: dict[str, np.ndarray] = {}
    dates, panel = load_panel(cfg, va_out=vas)
    disc = screen.disclosure_dates(cfg)
    today = dates[-1] if dates else a[1]
    turn: dict[str, tuple[list[str], np.ndarray]] = {}
    etf_rows: list[Row] = []
    etf_xs: Xs = {}
    vrows = screen.screen(*a, cfg=cfg)
    val = {r["code"]: r for r in vrows}
    vq = screen.value_quintile(vrows)
    rows: list[Row] = []
    xs: Xs = {}
    for c, (h, low, cl) in panel.items():
        m = master.get(c)
        etf = bool(m) and is_etf(m or {})
        if not m or (not etf and (m.get("S17") == "99" or m.get("MktNm") not in screen.MARKETS)):
            continue
        if np.sum(~np.isnan(cl)) < ind.MIN_BARS or np.isnan(cl[-1]):
            continue
        x = ind.compute(h, low, cl)
        j = ind.judge(x)
        ds_c = [d for d, o in zip(dates, x["ok"], strict=False) if o]
        tv = _turnover(vas.get(c), x["ok"])
        rc = ind.cci200_recent(x)
        c2 = {"cci200_signal": rc["code"] if rc and rc["bars_ago"] == 0 else None, "cci200_recent": rc}
        if etf:
            etf_xs[c] = (x, ds_c)
            if tv is not None:
                turn["etf:" + c] = (ds_c, tv)
            etf_rows.append(
                {
                    "code": c,
                    "name": m["CoName"],
                    "etf_kind": assets.etf_kind(m["CoName"]),
                    "chart_signal": j["label"],
                    "trend": j["trend"],
                    "bb48_z": j["zS"],
                    "bb288_z": j["zL"],
                    "cci48": j["cciS"],
                    "cci288": j["cciL"],
                    **c2,
                    "price": round(float(x["c"][-1]), 1),
                    "turnover_20d": _last(tv),
                }
            )
            continue
        v = val.get(c, {})
        xs[c] = (x, ds_c)
        if tv is not None:
            turn[c] = (ds_c, tv)
        ne = score.next_earnings(disc.get(c, []), today)
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
                # 2026-11 追加（Mac mini のみ・J-Quants 由来）
                "per_fwd": v.get("per_fwd"),
                "per_act": v.get("per_act"),
                "roe_act_pct": v.get("roe_act_pct"),
                "div_yield_fwd_pct": v.get("div_yield_fwd_pct"),
                "equity_ratio_pct": v.get("equity_ratio_pct"),
                "turnover_20d": _last(tv),
                "next_earnings": ne,
                "earnings_soon": score.earnings_soon(disc.get(c, []), today),
                **c2,
            }
        )
    if ctx is not None:
        ctx.update({"turnover": turn, "disclosures": disc, "etf_rows": etf_rows, "etf_xs": etf_xs, "today": today})
    return rows, xs, dates, a


def _arr(v: list[Any]) -> np.ndarray:
    return np.array([np.nan if t is None else t for t in v], float)


def build_us(cfg: Config, today: dt.date, ctx: dict[str, Any] | None = None) -> tuple[list[Row], Xs]:
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
        ds_t = [d for d, o in zip(px["d"], x["ok"], strict=False) if o]
        xs[t] = (x, ds_t)
        tv = None
        if px.get("v"):
            tv = score.rolling_mean(score.turnover_values(x["c"], _arr(px["v"])[x["ok"]]))
            if ctx is not None:
                ctx.setdefault("turnover", {})[t] = (ds_t, tv)
        filed = v.get("filed") or []
        if ctx is not None:
            ctx.setdefault("filed", {})[t] = filed
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
                # 2026-11 追加（SEC の決算 × Yahoo の株価。式は calc.fund_us / calc.score）
                "PER": v.get("PER"),
                "PBR": v.get("PBR"),
                "roe_pct": v.get("roe_pct"),
                "div_yield_pct": v.get("div_yield_pct"),
                "equity_ratio_pct": v.get("equity_ratio_pct"),
                "fair_price": v.get("fair_price"),
                "upside_pct": v.get("ri_upside_pct"),
                "value_check": v.get("value_check"),  # 「要確認」（fund_us.value_check）→ 割安の点 0
                "one_off_flag": bool(v.get("one_off_flag")),
                "turnover_20d": _last(tv),
                "next_earnings": score.next_earnings(filed, ds_t[-1]),
                "earnings_soon": score.earnings_soon(filed, ds_t[-1]),
                "cci200_signal": (lambda rc: rc["code"] if rc and rc["bars_ago"] == 0 else None)(ind.cci200_recent(x)),
                "cci200_recent": ind.cci200_recent(x),
            }
        )
    return rows, xs


def _grade_a(
    xs: Xs, since: str, vq: dict[str, dict[str, str]], base: dict[str, Any], base6m: dict[str, Any]
) -> dict[str, Any]:
    """A の定義そのもの（その月初の割安5分の1 × 買い系）の 20営業日後。
    比べる相手: 全銘柄の基準（verify の base と同じもの）と、割安5分の1にいた日すべて（cheap_quintile_days）。"""
    full: dict[str, list[float]] = {}
    recent: dict[str, list[float]] = {}
    for code, (x, ds) in xs.items():
        cheap = screen.cheap_days(code, ds, vq)
        if not cheap.any():
            continue
        conds = {"grade_A": cheap & ind.buy_type_days(x), "cheap_quintile_days": cheap}
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
    「根拠が弱まっています」の判定（weakened）の規則は変えない（buy / long_oversold の中央値が基準を下回る）。
    どの日を buy / long_oversold と数えるかは画面と同じ ind.day_labels。"""
    full: dict[str, list[float]] = {}
    recent: dict[str, list[float]] = {}
    for x, ds in xs.values():
        lc = ind.label_conditions(x)  # 画面と同じ規則（ind.day_labels）。長期の売られすぎ×売りの日は売り
        conds = {
            "buy": lc[ind.LABELS[2]] | lc[ind.LABELS[1]],
            "buy3": lc[ind.LABELS[2]],
            "long_oversold": lc[ind.LONG_OVERSOLD_LABEL],
            "sell": lc[ind.LABELS[-1]] | lc[ind.LABELS[-2]],
        }
        events.merge(full, events.event_returns(x["c"], conds))
        events.merge(recent, events.event_returns(x["c"], conds, dates=ds, since=since))
    fs = {k: events.stats(v) for k, v in full.items()}
    rs = {k: events.stats(v) for k, v in recent.items()}
    weak = {k: events.weakened(rs.get(k), rs.get("base", {})) for k in ("buy", "long_oversold")} if rs else {}
    out = {"full": fs, "recent6m": rs, "weakened_by": weak, "weakened": any(v is True for v in weak.values())}
    if vq is not None:
        out["grade_A"] = _grade_a(xs, since, vq, fs.get("base", {}), rs.get("base", {}))
    return out


def alert_markets(cfg: Config, jp: list[Row], jx: Xs, us: list[Row], ux: Xs) -> dict[str, tuple[Xs, dict[str, Row]]]:
    """CCI ±200 の通知・検証の対象（日本株・米国株・FX・仮想通貨）。行は {コード: {name, cci48, cci288}}。"""
    from .. import fxcrypto

    def pick(rows: list[Row], key: str, name: str) -> dict[str, Row]:
        return {r[key]: {"name": r.get(name), "cci48": r.get("cci48"), "cci288": r.get("cci288")} for r in rows}

    out = {"jp": (jx, pick(jp, "code", "company_name")), "us": (ux, pick(us, "ticker", "name"))}
    for m in ("fx", "crypto"):
        rows, xs = fxcrypto.load(cfg, m)
        out[m] = (xs, rows)
    return out


# ── 売買スコア（規則と配分は calc.score の1か所。ここは材料を集めて同じ関数を呼ぶだけ）──────────────
VALUE_PARTS = ("value", "chart", "penalty")  # 合計に入る部分（質の点は別の列）
ETF_PARTS = ("chart", "penalty")


def gate_local(vm: dict[str, Any], c200: dict[str, Any]) -> dict[str, bool]:
    """verify() の全期間（buy3=強い買い・buy=買い系の買い・long_oversold）
    と CCI 両方割れの全期間 → チャートの点の gate。"""
    rec = vm.get("recent6m") or {}
    chart = {lab: rec.get(k) for lab, k in LOCAL_GATE_KEYS.items()}
    return score.gate_from_verify(chart, rec.get("base"), c200)


def tiers_local(
    xs: Xs,
    gate: dict[str, bool],
    parts: tuple[str, ...],
    since: str,
    vin: dict[str, dict[str, Any]] | None = None,
    earn: dict[str, list[str]] | None = None,
    turn: dict[str, tuple[list[str], np.ndarray]] | None = None,
    market: str = "us",
    spikes: set[str] | None = None,
) -> dict[str, Any]:
    """日ごとの合計点（score.total_days）→ 段階ごとの 20 営業日後（score.verify_tiers）。
    vin = {月初: {銘柄: [上値余地, PBR, PER, 一時利益]}}（その月の市場の中の順位で割安の点にする）。"""
    vpm = (
        score.value_points_by_month({m: {c: tuple(v[:3]) for c, v in d.items()} for m, d in vin.items()})
        if vin
        else None
    )
    obm = {m: {c: bool(v[3]) for c, v in d.items()} for m, d in vin.items()} if vin else None
    low = score.low_turnover_by_symbol(turn) if turn and "penalty" in parts else {}
    items = [
        (
            x["c"],
            score.total_days(x, ds, c, gate, parts, vpm, obm, (earn or {}).get(c, []), low.get(c), market, spikes),
            ds,
        )
        for c, (x, ds) in xs.items()
    ]
    out = score.verify_tiers(items, since, parts)
    out["gate"] = gate
    return out


def add_scores(
    v: dict[str, Any],
    cfg: Config,
    since: str,
    jp: list[Row],
    jx: Xs,
    us: list[Row],
    ux: Xs,
    ctx: dict[str, Any],
    uctx: dict[str, Any],
    amk: dict[str, tuple[Xs, dict[str, Row]]] | None = None,
) -> list[Row]:
    """verify に score_tiers・cci200・etf を足し、行（日本株・米国株・ETF）にスコアの列を付ける。ETF の行を返す。"""
    etf_rows: list[Row] = ctx.get("etf_rows", [])
    kinds = {r["code"]: r["etf_kind"] for r in etf_rows}
    exs: Xs = ctx.get("etf_xs", {})
    scored = {c: xv for c, xv in exs.items() if kinds.get(c) not in score.NOT_SCORED_KINDS}
    # CCI ±200 の判定の検証（市場ごと・一斉に割れの日を除く・直近6か月。式は calc.score.cci200_verify）
    c200: dict[str, Any] = {}
    spk: dict[str, set[str]] = {}
    src = {"jp": jx, "us": ux, "etf": scored, **{m: xs for m, (xs, _r) in (amk or {}).items() if m in ("fx", "crypto")}}
    for m, xs in src.items():
        spec = alerts.MARKETS.get(m, {"spike": False, "verified": True, "note": ""})
        days: set[str] = set()
        if spec["spike"]:
            dts, cnt, act = ind.daily_event_counts(xs)
            days = ind.spike_days(dts, cnt, act)
        spk[m] = days
        last = max((ds[-1] for _x, ds in xs.values() if ds), default=None)
        c200[m] = score.cci200_verify(xs.values(), days, since) | {
            "verified": bool(spec["verified"]),
            "note": spec.get("note", ""),
            "spike_today": bool(last and last in days),
            "points": dict(score.CCI200.get(m, {})),
        }
    v["cci200"] = c200
    gj = gate_local(v["jp"], c200["jp"])
    gu = gate_local(v["us"], c200["us"])
    ve = verify(scored, since)
    ge = gate_local(ve, c200["etf"])
    turn = ctx.get("turnover", {})
    jturn = {c: t for c, t in turn.items() if not c.startswith("etf:")}
    eturn = {c[4:]: t for c, t in turn.items() if c.startswith("etf:") and c[4:] in scored}
    jvin = screen.monthly_score_inputs(cfg)
    uvin = us_screen.monthly_score_inputs(cfg, sorted(jvin)) if ux else {}
    tiers = {
        "jp": tiers_local(jx, gj, VALUE_PARTS, since, jvin, ctx.get("disclosures"), jturn, "jp", spk["jp"]),
        "us": tiers_local(ux, gu, VALUE_PARTS, since, uvin, uctx.get("filed"), uctx.get("turnover"), "us", spk["us"]),
        "etf": tiers_local(scored, ge, ETF_PARTS, since, None, None, eturn, "etf"),
    }
    v["score_tiers"] = tiers
    v["score_rules"] = score.rules()
    v["etf"] = {
        "market": {"full": ve["full"], "recent6m": ve["recent6m"], "symbols": len(scored)},
        "symbols": {
            r["code"]: {
                "name": r["name"],
                "kind": r["etf_kind"],
                "scored": r["etf_kind"] not in score.NOT_SCORED_KINDS,
                **({"chart": score.per_symbol_labels(exs[r["code"]][0])} if r["code"] in exs else {}),
            }
            for r in etf_rows
        },
    }
    items = list(v.get("weakened_items") or [])
    for m, t in tiers.items():
        if t.get("weakened") is True:
            items.append(f"{m}:score:{score.TOP_TIER}")
    v["weakened_items"] = items
    v["weakened"] = bool(v["weakened"] or any(t.get("weakened") is True for t in tiers.values()))
    for m, rows in (("jp", jp), ("us", us), ("etf", etf_rows)):
        for r in rows:
            r["cci200_spike"] = bool(c200[m]["spike_today"]) and r.get("cci200_signal") == ind.CCI200_BUY
    score.score_rows(jp, gj, score.ALL_PARTS, {"per": "per_act", "roe": "roe_act_pct"}, market="jp")
    score.score_rows(us, gu, score.ALL_PARTS, market="us")
    score.score_rows(etf_rows, ge, ETF_PARTS, market="etf")
    return etf_rows


def run(cfg: Config, asof: str | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.UTC)
    ctx: dict[str, Any] = {}
    uctx: dict[str, Any] = {}
    jp, jx, dates, anchors = build_jp(cfg, asof, ctx)
    today = dates[-1] if dates else anchors[1]
    us, ux = build_us(cfg, dt.date.fromisoformat(today) + dt.timedelta(days=1), uctx)
    since = minus(today, months=6).isoformat()
    v: dict[str, Any] = {
        "computed_at": now.isoformat(timespec="seconds"),
        "horizon_days": events.H,
        "gap_days": events.GAP,
        "recent_since": since,
        "period": [dates[min(events.WARMUP, len(dates) - 1)] if dates else None, today],
        "jp": verify(jx, since, screen.monthly_quintiles(cfg)),
        "us": verify(ux, since),
    }
    v["weakened"] = bool(v["jp"]["weakened"] or v["us"]["weakened"])
    markets = alert_markets(cfg, jp, jx, us, ux)
    v["cci_both_down"] = {m: alerts.verify(xs, m) for m, (xs, _) in markets.items()}
    for k in ("buy", "long_oversold"):  # 既存の「根拠が弱まっています」（買い系）を項目でも残す
        for m in ("jp", "us"):
            if v[m]["weakened_by"].get(k) is True:
                v.setdefault("weakened_items", []).append(f"{m}:chart:{k}")
    etf = add_scores(v, cfg, since, jp, jx, us, ux, ctx, uctx, markets)
    return {
        "asof": today,
        "generated_at": now.isoformat(timespec="seconds"),
        "anchors": {"asof": anchors[0], "px": anchors[1], "p1y": anchors[2], "p1m": anchors[3]},
        "jp": jp,
        "us": us,
        "etf": etf,
        "verify": v,
        "cci_alerts": alerts.build(markets, list(cfg.get("alerts.watchlist", []) or [])),
    }
