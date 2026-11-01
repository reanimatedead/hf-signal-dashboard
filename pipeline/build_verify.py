#!/usr/bin/env python3
"""pipeline/build_verify.py — 判定の検証層（docs/verify.json）。DATA_CONTRACT §21。

Yahoo の日足だけを使い、次の判定を**同じ方法**で検証する:
  - チャート判定（marketcalc.ind）: 強い買い / 買い / 買い（長期の売られすぎ）/ 売り / 強い売り
  - 既存の composite_score（fetch_signals.compute_signal）: STRONG BUY / BUY / HOLD / WATCH / AVOID
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

from marketcalc import events, fund_us, ind  # noqa: E402

SCHEMA = "verify/1"
RECENT_MONTHS = 6
COMPOSITE_LABELS = ("STRONG BUY", "BUY", "HOLD", "WATCH", "AVOID")
COMPOSITE_BUY = ("STRONG BUY", "BUY")
MARKET_LABEL = {"nikkei225": "日経225", "us": "米国（Dow30・Nasdaq100・S&P500 の和集合）"}
METHOD = {
    "horizon_days": events.H, "gap_days": events.GAP, "warmup_bars": events.WARMUP,
    "recent_months": RECENT_MONTHS, "price_source": "Yahoo 日足（2年）",
    "base": "同じ銘柄・同じ期間の全営業日の20営業日後騰落率（全期間平均）",
    "weakened_rule": "直近6か月で、買い系の判定後の中央値が基準の中央値を下回る（件数5未満は判定しない）",
    "note": "過去の値動きの集計であり、将来の値動きや売買を約束するものではありません。",
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
                weak_items.append(f"{m['label']}: {k.split(':', 1)[1]}")
    dates = [m["last_date"] for m in out["markets"].values() if m.get("last_date")]
    out["as_of"] = max(dates) if dates else None
    out["weakened"] = bool(weak_items)
    out["weakened_items"] = weak_items
    return out


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
