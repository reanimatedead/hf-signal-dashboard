#!/usr/bin/env python3
"""pipeline/build_verify.py — 判定の検証層（docs/verify.json）。DATA_CONTRACT §21。

Yahoo の日足だけを使い、次の判定を**同じ方法**で検証する:
  - チャート判定（marketcalc.ind）: buy_strong / buy / buy_long_oversold / sell / sell_strong
  - 既存の composite_score（fetch_signals.compute_signal）: strong_buy / buy / hold / watch / avoid
ラベル・説明はすべてコード（表示文は UI 辞書 docs/assets/i18n）。
方法（marketcalc.events）: 判定が出た日の終値 → 20 営業日後の騰落率。同じ銘柄の連続判定は
20 日に 1 回だけ数える。基準 = 同じ銘柄・同じ期間の全営業日の 20 日後騰落率（全期間平均）。
指標が揃うまでの 288 本は数えない。全期間版と直近 6 か月版を出し、直近版で
「判定後の中央値 < 基準の中央値」になった買い系の判定に weakened=true を付ける。

計算式はここに書かない（marketcalc.events / marketcalc.ind を呼ぶだけ）。通信もしない:
fetch_signals.py が 2y 日足フレームを渡して build() を呼ぶ（取得し直さない）。
オフライン確認用に --fixture DIR（tests/screener/calc/fixtures 形の px_*.json）で動く。

使い方:
    python3 pipeline/build_verify.py --fixture tests/screener/calc/fixtures --out /tmp/verify.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from marketcalc import events, fund_us, ind, score  # noqa: E402

SCHEMA = "verify/1"
RECENT_MONTHS = 6
COMPOSITE_LABELS = ("strong_buy", "buy", "hold", "watch", "avoid")
COMPOSITE_BUY = ("strong_buy", "buy")
# nikkei225=日経225 / us_union=米国（Dow30・Nasdaq100・S&P500 の和集合）
MARKET_LABEL = {"nikkei225": "nikkei225", "us": "us_union", "etf": "etf"}
METHOD = {
    "horizon_days": events.H, "gap_days": events.GAP, "warmup_bars": events.WARMUP,
    "recent_months": RECENT_MONTHS,
    "price_source": "yahoo_daily_2y",                 # Yahoo 日足（2年）
    "base": "same_symbol_all_days_h20_mean",          # 同じ銘柄・同じ期間の全営業日の20営業日後騰落率（全期間平均）
    "weakened_rule": "recent6m_buy_median_below_base",  # 直近6か月で買い系の判定後の中央値 < 基準の中央値（件数5未満は判定しない）
    "note": "past_aggregate_not_promise",             # 過去の値動きの集計であり、将来の値動きや売買を約束するものではない
}


def _since(last_date: str, months: int = RECENT_MONTHS) -> str:
    d = dt.date.fromisoformat(last_date[:10])
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12; y -= 1
    return dt.date(y, m, min(d.day, 28)).isoformat()


def conditions(h, l, c, composite=None):
    """1 銘柄分 → (終値配列, {"chart:<label>"|"composite:<label>": bool配列})。
    h,l,c は Close が有限な行だけ（fetch_signals._finite_hlc）。composite は同じ行の BUY/WATCH… ラベル列。"""
    x = ind.compute(h, l, c)
    conds = {f"chart:{k}": v for k, v in ind.label_conditions(x).items()}
    if composite is not None:
        a = np.asarray(composite, dtype=object)
        if len(a) == len(x["c"]):
            for lab in COMPOSITE_LABELS:
                conds[f"composite:{lab}"] = a == lab
    return x["c"], conds


def _split(acc):
    st = {k: events.stats(v) for k, v in acc.items()}
    out = {"base": st.pop("base", events.stats([])), "chart": {}, "composite": {}}
    for k, v in st.items():
        kind, lab = k.split(":", 1)
        out[kind][lab] = v
    return out


def verify_market(items):
    """items: [(dates, h, l, c, composite_or_None), ...] → {"symbols","full","recent6m","weakened"}。"""
    full, recent = {}, {}
    last = max((d[-1] for d, *_ in items if len(d)), default=None)
    since = _since(last) if last else None
    n = 0
    for dates, h, l, c, comp in items:
        if np.sum(np.isfinite(np.asarray(c, dtype=float))) < ind.MIN_BARS:
            continue
        close, conds = conditions(h, l, c, comp)
        if len(close) != len(dates):
            continue
        n += 1
        events.merge(full, events.event_returns(close, conds))
        events.merge(recent, events.event_returns(close, conds, dates=list(dates), since=since))
    F, R = _split(full), _split(recent)
    weak = {}
    for lab in ind.BUY_LABELS:
        weak[f"chart:{lab}"] = events.weakened(R["chart"].get(lab), R["base"])
    for lab in COMPOSITE_BUY:
        if lab in R["composite"]:
            weak[f"composite:{lab}"] = events.weakened(R["composite"].get(lab), R["base"])
    R["since"] = since
    return {"symbols": n, "last_date": last, "full": F, "recent6m": R, "weakened": weak}


def build(markets, generated_at=None):
    """markets: {"nikkei225": items, "us": items}（items は verify_market 参照）→ verify.json の dict。"""
    out = {"schema": SCHEMA, "generated_at": generated_at or dt.datetime.now(dt.timezone.utc).isoformat(),
           "method": METHOD, "markets": {}}
    weak_items = []
    for key, items in markets.items():
        m = verify_market(items)
        m["label"] = MARKET_LABEL.get(key, key)
        out["markets"][key] = m
        for k, v in m["weakened"].items():
            if v:
                weak_items.append(f"{m['label']}:{k}")   # 例 "nikkei225:chart:buy_long_oversold"
    dates = [m["last_date"] for m in out["markets"].values() if m.get("last_date")]
    out["as_of"] = max(dates) if dates else None
    out["weakened"] = bool(weak_items)
    out["weakened_items"] = weak_items
    return out


# ── 売買スコア（screener.calc.score）の 5 段階の検証・ETF ごとの成績（2026-11 追加。既存の markets は変えない）──
SCORE_MARKET = {"nikkei225": "jp", "us": "us", "etf": "etf"}   # marketcalc.score.CCI200 の市場名
SPIKE_MARKETS = ("nikkei225", "us")                             # 「一斉に割れ」を判定する市場（ETF はしない）


def spike_info(xs):
    """[(sym, x, ds, e)] → (一斉に割れの日の集合, 最新日が一斉に割れか)。式は marketcalc.ind（Mac mini と同じ）。"""
    d = {sym: (x, ds) for sym, x, ds, _e in xs}
    dates, counts, active = ind.daily_event_counts(d)
    if not dates:
        return set(), False
    days = ind.spike_days(dates, counts, active)
    return days, dates[-1] in days


def _xs(entries):
    """entries: [{"sym","dates","h","l","c","v"(出来高 or None)}] → [(sym, x, ds, entry)]（Close が有限な行だけ・300 本以上）。"""
    out = []
    for e in entries:
        c = np.asarray(e["c"], dtype=float)
        if np.sum(np.isfinite(c)) < ind.MIN_BARS:
            continue
        x = ind.compute(e["h"], e["l"], c)
        ds = [d for d, o in zip(e["dates"], x["ok"]) if o]
        out.append((e["sym"], x, ds, e))
    return out


def turnover_series(xs):
    """{銘柄: (日付, 売買代金の20日平均)}（出来高のある銘柄だけ）。"""
    out = {}
    for sym, x, ds, e in xs:
        v = e.get("v")
        if v is None:
            continue
        vv = np.asarray(v, dtype=float)[np.asarray(x["ok"], dtype=bool)]
        out[sym] = (ds, score.rolling_mean(score.turnover_values(x["c"], vv)))
    return out


def us_monthly_inputs(xs, fund):
    """us_fundamentals.json の hist（月初の決算）× その月初の終値 → ({月初: {銘柄: (余地, PBR, PER)}}, {月初: {銘柄: one_off}})。"""
    vin, oo = {}, {}
    for sym, x, ds, _e in xs:
        h = ((fund or {}).get(sym) or {}).get("hist") or {}
        for m, rec in h.items():
            i = int(np.searchsorted(np.array(ds), m, side="right")) - 1
            if i < 0:
                continue
            ni, eq, sh, roe = rec[:4]
            vin.setdefault(m, {})[sym] = fund_us.value_inputs(ni, eq, sh, roe, float(x["c"][i]))
            if len(rec) > 4:
                oo.setdefault(m, {})[sym] = bool(rec[4])
    sics = {t: (v or {}).get("sic") for t, v in (fund or {}).items()}
    vin = {m: fund_us.rerate_month(v, sics) for m, v in vin.items()}  # 余地は月初ごとの業種別 PER の中央値から
    return vin, oo


def score_market(entries, parts, gate, since, fund=None, market="us", spikes=None):
    """1 つの市場の段階別成績（score.verify_tiers）。parts は score.score_rows と同じ。"""
    xs = _xs(entries)
    low = score.low_turnover_by_symbol(turnover_series(xs)) if "penalty" in parts else {}
    vbm, obm = us_monthly_inputs(xs, fund) if ("value" in parts and fund) else ({}, {})
    vpm = score.value_points_by_month(vbm) if vbm else None
    items = []
    for sym, x, ds, _e in xs:
        earn = ((fund or {}).get(sym) or {}).get("filed") or []
        tot = score.total_days(x, ds, sym, gate, parts, vpm, obm or None, earn, low.get(sym), market, spikes)
        items.append((x["c"], tot, ds))
    return score.verify_tiers(items, since, parts)


def build_scores(obj, entries_by_market, fund=None, etf_kinds=None):
    """obj（build の戻り値）に score_gate・score_tiers・etf を足す。最上位の段階が直近で基準を下回れば
    weakened_items に "<市場>:score:tier5" を足す（「根拠が弱まっています」と同じ扱い）。gate を返す。"""
    etf_kinds = etf_kinds or {}
    gates, tiers, cci = {}, {}, {}
    for key, entries in entries_by_market.items():
        if key == "etf":
            entries = [e for e in entries if etf_kinds.get(e["sym"]) not in score.NOT_SCORED_KINDS] or []
            xs = _xs(entries)
            mk = verify_market([(e["dates"], e["h"], e["l"], e["c"], None) for e in entries])
        else:
            xs = _xs(entries)
            mk = obj["markets"].get(key) or verify_market([(e["dates"], e["h"], e["l"], e["c"], None) for e in entries])
        since = (mk.get("recent6m") or {}).get("since")
        spikes, spike_today = spike_info(xs) if key in SPIKE_MARKETS else (set(), False)
        c2 = score.cci200_verify([(x, ds) for _s, x, ds, _e in xs], spikes, since)
        c2.update({"market": SCORE_MARKET[key], "verified": True, "spike_today": spike_today,
                   "spike_rule": key in SPIKE_MARKETS, "points": dict(score.CCI200[SCORE_MARKET[key]])})
        cci[key] = c2
        gate = score.gate_from_verify((mk.get("recent6m") or {}).get("chart"), (mk.get("recent6m") or {}).get("base"), c2)
        gates[key] = gate
        gates.setdefault("_spike_today", {})[key] = spike_today
        parts = score.CHART_ONLY if key == "nikkei225" else (("chart", "penalty") if key == "etf"
                                                              else ("value", "chart", "penalty"))
        t = score_market(entries, parts, gate, since, fund if key == "us" else None, SCORE_MARKET[key], spikes)
        t["gate"] = gate
        if key == "us":   # gate は今の判定を過去にも当てるので、当てない場合の成績も残す（先読みの大きさの確認用）
            ng = score_market(entries, parts, None, since, fund, SCORE_MARKET[key], spikes)
            t["without_gate"] = {"full": ng["full"], "recent6m": ng["recent6m"]}
        tiers[key] = t
        if key == "etf":
            obj["etf"] = {"market": {"full": mk["full"], "recent6m": mk["recent6m"], "symbols": mk["symbols"]},
                          "symbols": {}}
        if t.get("weakened") is True:
            obj.setdefault("weakened_items", []).append(f"{MARKET_LABEL.get(key, key)}:score:{score.TOP_TIER}")
            obj["weakened"] = True
    for e in entries_by_market.get("etf", []):     # ETF ごと（inverse も成績は出す・スコアの対象外と印を付ける）
        xs = _xs([e])
        kind = etf_kinds.get(e["sym"], "unknown")
        rec = {"kind": kind, "scored": kind not in score.NOT_SCORED_KINDS}
        if xs:
            st = score.per_symbol_labels(xs[0][1])
            rec.update({"base": st.pop("base", None), "chart": st, "last_date": xs[0][2][-1]})
        obj.setdefault("etf", {"market": None, "symbols": {}})["symbols"][e["sym"]] = rec
    obj["score_tiers"] = tiers
    obj["cci200"] = cci
    obj["score_rules"] = score.rules()
    return gates


def write(obj, path):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    return path


def items_from_fixture(fixdir):
    """tests/screener/calc/fixtures の px_*.json（架空データ）→ items。composite は無し。"""
    items = []
    for p in sorted(pathlib.Path(fixdir).glob("px_*.json")):
        px = fund_us.parse_yahoo_chart(json.loads(p.read_text()))
        c = np.array([np.nan if v is None else v for v in px["c"]], dtype=float)
        ok = np.isfinite(c)
        h = np.array([np.nan if v is None else v for v in (px["h"] or px["c"])], dtype=float)[ok]
        l = np.array([np.nan if v is None else v for v in (px["l"] or px["c"])], dtype=float)[ok]
        items.append(([d for d, k in zip(px["d"], ok) if k], h, l, c[ok], None))
    return items


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fixture", required=True, help="px_*.json のあるディレクトリ（架空データ）")
    ap.add_argument("--out", default=str(ROOT / "docs" / "verify.json"))
    a = ap.parse_args(argv)
    items = items_from_fixture(a.fixture)
    obj = build({"nikkei225": items, "us": items})
    print(f"verify: {write(obj, a.out)} as_of={obj['as_of']} weakened={obj['weakened']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
