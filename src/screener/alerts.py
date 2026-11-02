"""CCI ±200 の抜け: その日の一覧（HTML）・Mac mini の通知・検証。規則は screener.calc.ind（cci_events / spike_*）だけ。

- 対象: 「両方が −200 を下に抜けた」は日本株（検証した範囲）。ウォッチリスト（config の [alerts] watchlist）は
  日本株のコード・米国株のティッカーのどちらでもよく、CCI48 / CCI288 の −200 割れを通知する。
- 「一斉に割れ」: その日の日本株の both_down 件数が、過去1年（その日を含まない）の日々の件数の上位1%を超えた日
  （ただし 5 件以上。平穏な年は線が 0 件になり、1 銘柄でも「一斉に」になってしまうため）。
- +200 を上に抜けたものは通知しない（一覧の列には残す）。
- 通知は Mac mini の中だけ（terminal-notifier、無ければ osascript）。ntfy には送らない。銘柄名を出してよいのは
  通知と一覧が Mac mini の外に出ないため（ADR-002）。
"""

from __future__ import annotations

import collections
import html
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from . import labels
from .calc import events, ind

Row = dict[str, Any]
Xs = dict[str, tuple[dict[str, Any], list[str]]]
TOP_N = 5
ALERT_COLS = ["watch", "code", "name", "market", "cci48", "cci288", *ind.CCI_EVENTS]


def daily_counts(xs: Xs, key: str = "both_down") -> tuple[list[str], list[int]]:
    """全営業日（どれかの銘柄に日足がある日）の、その抜けの件数（0 の日も含む）。"""
    cnt: collections.Counter[str] = collections.Counter()
    days: set[str] = set()
    for x, ds in xs.values():
        days.update(ds)
        ev = ind.cci_events(x)[key]
        for i in np.flatnonzero(ev):
            cnt[ds[i]] += 1
    dates = sorted(days)
    return dates, [cnt.get(d, 0) for d in dates]


def _today_rows(xs: Xs, rows: dict[str, Row], asof: str, name_key: str, market: str) -> list[Row]:
    out = []
    for code, (x, ds) in xs.items():
        if not ds or ds[-1] != asof:
            continue  # その日の日足が無い銘柄（止まっている・古い）は数えない
        ev = {k: bool(v[-1]) for k, v in ind.cci_events(x).items()}
        if not any(ev.values()):
            continue
        r = rows.get(code, {})
        out.append(
            {
                "code": code,
                "name": r.get(name_key) or code,
                "market": r.get("market") or market,
                "cci48": r.get("cci48"),
                "cci288": r.get("cci288"),
                **ev,
            }
        )
    return out


def _order(items: list[Row]) -> list[Row]:
    """深く割れている順（CCI288 → CCI48 が低い順）。"""
    return sorted(items, key=lambda r: (r["cci288"] if r["cci288"] is not None else 0, r["cci48"] or 0))


def build(jp_rows: list[Row], jx: Xs, us_rows: list[Row], ux: Xs, watchlist: list[str] | None = None) -> dict[str, Any]:
    """その日の CCI ±200 の抜けをまとめる（通知と一覧の元）。"""
    watch = {str(w).strip().upper() for w in (watchlist or []) if str(w).strip()}
    dates, counts = daily_counts(jx)
    asof = dates[-1] if dates else None
    n = counts[-1] if counts else 0
    thr = ind.spike_threshold(counts[-1 - ind.SPIKE_LOOKBACK : -1]) if counts else None
    us_asof = max((ds[-1] for _, ds in ux.values() if ds), default=None)
    items = _today_rows(jx, {r["code"]: r for r in jp_rows}, asof, "company_name", "JP") if asof else []
    if us_asof:
        items += _today_rows(ux, {r["ticker"]: r for r in us_rows}, us_asof, "name", "US")
    for r in items:
        r["watch"] = r["code"].upper() in watch
    items = _order(items)
    both = [r for r in items if r["market"] != "US" and r["both_down"]]
    watched = [r for r in items if r["watch"] and any(r[k] for k in ind.NOTIFY_EVENTS)]
    return {
        "asof": asof,
        "us_asof": us_asof,
        "both_down_count": n,
        "spike_threshold": thr,
        "spike": ind.is_spike(n, thr),
        "both_down": both,
        "watch_hits": watched,
        "watchlist": sorted(watch),
        "items": items,
    }


# ── 検証（verify_local.json の jp.cci_both_down）────────────────────────────────


def _stats_by_year(pairs: list[tuple[str, float]]) -> dict[str, Any]:
    by: dict[str, list[float]] = collections.defaultdict(list)
    for d, f in pairs:
        by[d[:4]].append(f)
    return {y: events.stats(v) for y, v in sorted(by.items())}


def verify(jx: Xs) -> dict[str, Any]:
    """「CCI48 と CCI288 の両方が −200 を下に抜けた」日の 20営業日後（中央値など）。
    全体・「一斉に割れ」の日（暴落の日）を除く・年ごと。比べる相手は同じ銘柄・同じ期間の全営業日（base）。"""
    dates, counts = daily_counts(jx)
    spikes = ind.spike_days(dates, counts)
    acc: dict[str, list[tuple[str, float]]] = {}
    for x, ds in jx.values():
        ev = ind.cci_events(x)
        part = events.event_returns_dated(x["c"], {"both_down": ev["both_down"], "both_up": ev["both_up"]}, ds)
        events.merge(acc, part)
    bd = acc.get("both_down", [])
    base = acc.get("base", [])
    return {
        "definition": "cci48_and_cci288_both_cross_below_minus200",
        "horizon_days": events.H,
        "gap_days": events.GAP,
        "full": {
            "both_down": events.stats([f for _, f in bd]),
            "both_up": events.stats([f for _, f in acc.get("both_up", [])]),
            "base": events.stats([f for _, f in base]),
        },
        "excluding_spike_days": {
            "both_down": events.stats([f for d, f in bd if d not in spikes]),
            "base": events.stats([f for d, f in base if d not in spikes]),
        },
        "spike_days": sorted(spikes),
        "spike_rule": {"quantile": ind.SPIKE_Q, "lookback_days": ind.SPIKE_LOOKBACK, "min_count": ind.SPIKE_MIN_COUNT},
        "by_year": {"both_down": _stats_by_year(bd), "base": _stats_by_year(base)},
    }


# ── 一覧（HTML）と Mac mini の通知 ─────────────────────────────────────────────


def render_html(a: dict[str, Any]) -> str:
    head = "".join(f"<th>{html.escape(labels.col(c))}</th>" for c in ALERT_COLS)
    body = []
    for r in a["items"]:
        tds = "".join(f"<td>{html.escape(_cell(r.get(c)))}</td>" for c in ALERT_COLS)
        cls = "bd" if r.get("both_down") else ("w" if r.get("watch") else "")
        body.append(f'<tr class="{cls}">{tds}</tr>')
    thr = a["spike_threshold"]
    banner = (
        '<p class="spike">一斉に割れ（暴落の可能性）: 両方が −200 を下に抜けた銘柄が '
        f"{a['both_down_count']} 件。過去1年の上位1%の線（{thr:.0f} 件）を超えました。</p>"
        if a["spike"]
        else ""
    )
    thr_txt = f"{thr:.0f} 件" if thr is not None else "履歴が短く未判定"
    return (
        '<!DOCTYPE html>\n<html lang="ja"><head><meta charset="utf-8">'
        f"<title>CCI ±200 {html.escape(str(a['asof']))}</title>"
        "<style>body{font-family:sans-serif;font-size:13px}table{border-collapse:collapse}"
        "th,td{border:1px solid #ccc;padding:2px 6px}th{background:#eee;position:sticky;top:0}"
        ".bd{background:#ffe6e6}.w{background:#e6f0ff}.spike{color:#b00;font-weight:bold;font-size:16px}</style>"
        "</head><body>"
        f"<h1>CCI ±200 の抜け（日本株 {html.escape(str(a['asof']))}・米国株 {html.escape(str(a['us_asof']))}）</h1>"
        f"{banner}<p>両方が −200 を下に抜けた日本株: {a['both_down_count']} 件（「一斉に割れ」の線: {thr_txt}）。"
        f"ウォッチリストで −200 を抜けた銘柄: {len(a['watch_hits'])} 件。"
        "+200 を上に抜けたものは通知しません（列だけ）。"
        "過去の集計は verify_local.json の jp.cci_both_down。このファイルは Mac mini のローカルにだけあります。</p>"
        f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></body></html>\n"
    )


def _cell(v: Any) -> str:
    if v is True:
        return "●"
    if v is False or v is None:
        return ""
    return str(v)


def _names(rs: list[Row]) -> str:
    s = "、".join(f"{r['code']} {r['name']}" for r in rs[:TOP_N])
    return s + (f" ほか{len(rs) - TOP_N}" if len(rs) > TOP_N else "")


def message(a: dict[str, Any]) -> tuple[str, str] | None:
    """(タイトル, 本文)。通知することが無ければ None。"""
    if a["spike"]:
        return (
            "⚠ 一斉に割れ（暴落の可能性）",
            f"{a['asof']} 日本株で CCI48・288 の両方が −200 割れ {a['both_down_count']} 件"
            f"（過去1年の上位1%の線 {a['spike_threshold']:.0f} 件を超えた）。{_names(a['both_down'])}",
        )
    parts = []
    if a["both_down"]:
        parts.append(f"両方 −200 割れ {len(a['both_down'])} 件: {_names(a['both_down'])}")
    if a["watch_hits"]:
        parts.append(f"ウォッチ {len(a['watch_hits'])} 件: {_names(a['watch_hits'])}")
    if not parts:
        return None
    return f"CCI −200 割れ {a['asof']}", " ／ ".join(parts)


Runner = Callable[..., Any]


def notify(
    a: dict[str, Any],
    html_path: Path,
    runner: Runner = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    platform: str = sys.platform,
) -> str:
    """Mac mini の通知を1回出す。戻り値は使った方法（terminal-notifier / osascript / none / not_mac / error）。
    通知の失敗で本処理を失敗にしない。"""
    m = message(a)
    if m is None:
        print("mac通知: 該当なし", flush=True)
        return "none"
    title, body = m
    if platform != "darwin":
        print(f"mac通知: Mac ではないので出さない（{title}）", flush=True)
        return "not_mac"
    try:
        tn = which("terminal-notifier")
        if tn:
            runner(
                [tn, "-title", title, "-message", body, "-open", html_path.as_uri(), "-group", "screener-cci"],
                timeout=30,
            )
            how = "terminal-notifier"
        else:  # osascript の通知は押しても一覧は開かない（brew install terminal-notifier で開くようになる）
            esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
            runner(["osascript", "-e", f'display notification "{esc(body)}" with title "{esc(title)}"'], timeout=30)
            how = "osascript"
    except Exception as e:
        print(f"mac通知: 出せませんでした（{type(e).__name__}）", flush=True)
        return "error"
    print(f"mac通知: {how}（{title}）→ {html_path}", flush=True)
    return how
