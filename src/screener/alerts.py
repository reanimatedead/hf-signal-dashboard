"""CCI ±200 の抜け: その日の一覧（HTML）・Mac mini の通知・検証。規則は screener.calc.ind（cci_events / spike_*）だけ。

市場（MARKETS）: 日本株・米国株（Dow・Nasdaq100・S&P500 の和集合）・FX（18）・仮想通貨（4）。全部の市場で同じ規則。
- 両方割れ = CCI48 と CCI288 の両方が −200 以下にそろった日（前の日はそろっていない）。
- 「一斉に割れ（暴落の可能性）」: 日本株・米国株だけ。その日の両方割れの件数が、過去1年（その日を含まない）の
  日々の件数の上位1% と その市場の銘柄数の 1.5% の大きい方を超えた日。FX・仮想通貨は銘柄が少ないので出さない。
- FX・仮想通貨は 1つずつ通知する。検証していないので、通知と一覧に「未検証」と出す。
- ウォッチリスト（config の [alerts] watchlist）は、どの市場の銘柄でもよく、CCI48 / CCI288 の −200 割れを通知する。
- +200 を上に抜けたものは通知しない（一覧の列には残す）。
- 通知は Mac mini の中だけ。既定は osascript の display notification（本文は市場ごとの件数＋上位銘柄、最後に一覧の
  ファイルの場所）。terminal-notifier は config の [alerts] notifier = "terminal-notifier" のときだけ試し、
  使えなければ osascript。ntfy には送らない。銘柄名を出してよいのは Mac mini の外に出ないため（ADR-002）。
- 通知の音は大事さで分ける（sound_for）: 一斉に割れ = sound_spike（既定 Sosumi）、CCI ±200 の買い・売り目安 =
  sound_signal（既定 Glass）、それ以外（ウォッチリストの片方だけの割れなど）は鳴らさない。設定は config の [alerts]。
  sound_enabled = false なら鳴らさない。名前が /System/Library/Sounds に無ければ音なしで通知する。
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

from . import labels
from .calc import events, ind

Row = dict[str, Any]
Xs = dict[str, tuple[dict[str, Any], list[str]]]
TOP_N = 5
SELL_NOTE_TEXT = "売り目安は利益確定・新しく買わない目安（空売りの根拠ではない）"
ALERT_COLS = ["market", "watch", "code", "name", "cci48", "cci288", *ind.CCI_EVENTS]

# 市場ごとの扱い（規則そのものは ind。ここは「一斉に割れ」を出すか・検証済みか・注記だけ）
MARKETS: dict[str, dict[str, Any]] = {
    "jp": {"label": "日本株", "spike": True, "verified": True, "note": ""},
    "us": {
        "label": "米国株",
        "spike": True,
        "verified": True,
        "note": "今の構成銘柄だけで検証（生き残りの偏りあり：途中で外れた・上場廃止の銘柄は入っていない）",
    },
    "fx": {"label": "FX", "spike": False, "verified": False, "note": "未検証"},
    "crypto": {"label": "仮想通貨", "spike": False, "verified": False, "note": "未検証"},
}


def daily_counts(xs: Xs, key: str = "both_down") -> tuple[list[str], list[int], list[int]]:
    """(日付, その抜けの件数, その日に日足がある銘柄の数)。0 件の日も含む（式は ind.daily_event_counts）。"""
    dates, counts, active = ind.daily_event_counts(xs, key)
    return list(dates), list(counts), list(active)


def _today_rows(market: str, xs: Xs, rows: dict[str, Row], asof: str) -> list[Row]:
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
                "market": market,
                "code": code,
                "name": r.get("name") or code,
                "cci48": r.get("cci48"),
                "cci288": r.get("cci288"),
                **ev,
            }
        )
    return out


def _order(items: list[Row]) -> list[Row]:
    """深く割れている順（CCI288 → CCI48 が低い順）。"""
    return sorted(items, key=lambda r: (r["cci288"] if r["cci288"] is not None else 0, r["cci48"] or 0))


def build(markets: dict[str, tuple[Xs, dict[str, Row]]], watchlist: list[str] | None = None) -> dict[str, Any]:
    """markets = {市場: (xs, {コード: {name, cci48, cci288}})}。その日の CCI ±200 の抜けをまとめる。"""
    watch = {str(w).strip().upper() for w in (watchlist or []) if str(w).strip()}
    per: dict[str, Any] = {}
    items: list[Row] = []
    for m, (xs, rows) in markets.items():
        spec = MARKETS[m]
        dates, counts, active = daily_counts(xs)
        asof = dates[-1] if dates else None
        n = counts[-1] if counts else 0
        line = ind.spike_line(counts[-1 - ind.SPIKE_LOOKBACK : -1], active[-1]) if (counts and spec["spike"]) else None
        mi = _order(_today_rows(m, xs, rows, asof)) if asof else []
        for r in mi:
            r["watch"] = r["code"].upper() in watch
        items += mi
        per[m] = {
            "label": spec["label"],
            "asof": asof,
            "universe": active[-1] if active else 0,
            "both_down_count": n,
            "spike_line": line,
            "spike": bool(spec["spike"] and ind.is_spike(n, line)),
            "verified": spec["verified"],
            "note": spec["note"],
            "both_down": [r for r in mi if r["both_down"]],
            # 売り目安（CCI +200）= ind.cci200_days の sell_cci200（both_up と同じ日）。利益確定・新しく買わない目安
            ind.CCI200_SELL: [r for r in mi if r["both_up"]],
        }
    watched = [r for r in items if r["watch"] and any(r[k] for k in ind.NOTIFY_EVENTS)]
    asof = (per.get("jp") or {}).get("asof") or max((v["asof"] or "" for v in per.values()), default="") or None
    return {
        "asof": asof,
        "markets": per,
        "spike": any(v["spike"] for v in per.values()),
        "watch_hits": watched,
        "watchlist": sorted(watch),
        "items": items,
    }


# ── 検証（verify_local.json の cci_both_down.<市場>）──────────────────────────────


def _stats_by_year(pairs: list[tuple[str, float]]) -> dict[str, Any]:
    by: dict[str, list[float]] = collections.defaultdict(list)
    for d, f in pairs:
        by[d[:4]].append(f)
    return {y: events.stats(v) for y, v in sorted(by.items())}


def verify(xs: Xs, market: str) -> dict[str, Any]:
    """両方割れの日の 20営業日後（中央値など。件数 n も必ず出す）。全体・「一斉に割れ」の日を除く・年ごと。
    比べる相手は同じ銘柄・同じ期間の全営業日（base）。FX・仮想通貨は「一斉に割れ」を出さないので除く日は無い。"""
    spec = MARKETS[market]
    dates, counts, active = daily_counts(xs)
    spikes = ind.spike_days(dates, counts, active) if spec["spike"] else set()
    acc: dict[str, list[tuple[str, float]]] = {}
    for x, ds in xs.values():
        ev = ind.cci_events(x)
        events.merge(
            acc, events.event_returns_dated(x["c"], {"both_down": ev["both_down"], "both_up": ev["both_up"]}, ds)
        )
    bd, base = acc.get("both_down", []), acc.get("base", [])
    return {
        "market": spec["label"],
        "verified": spec["verified"],
        "note": spec["note"],
        "definition": "cci48_and_cci288_both_cross_below_minus200",
        "symbols": len(xs),
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
        "spike_rule": (
            {"quantile": ind.SPIKE_Q, "lookback_days": ind.SPIKE_LOOKBACK, "min_frac_of_universe": ind.SPIKE_MIN_FRAC}
            if spec["spike"]
            else None
        ),
        "by_year": {"both_down": _stats_by_year(bd), "base": _stats_by_year(base)},
    }


# ── 一覧（HTML）と Mac mini の通知 ─────────────────────────────────────────────


def _cell(v: Any) -> str:
    if v is True:
        return "●"
    if v is False or v is None:
        return ""
    return str(v)


def render_html(a: dict[str, Any]) -> str:
    head = "".join(f"<th>{html.escape(labels.col(c))}</th>" for c in ALERT_COLS)
    body = []
    for r in a["items"]:
        r = r | {"market": MARKETS[r["market"]]["label"]}
        tds = "".join(f"<td>{html.escape(_cell(r.get(c)))}</td>" for c in ALERT_COLS)
        cls = "bd" if r.get("both_down") else ("w" if r.get("watch") else "")
        body.append(f'<tr class="{cls}">{tds}</tr>')
    summary = []
    for m in a["markets"].values():
        line = f"{m['spike_line']:.0f} 件" if m["spike_line"] is not None else "—"
        flag = "一斉に割れ（暴落の可能性）" if m["spike"] else ""
        summary.append(
            "<tr>"
            + "".join(
                f"<td>{html.escape(str(v))}</td>"
                for v in (m["label"], m["asof"], m["universe"], m["both_down_count"], line, flag, m["note"])
            )
            + "</tr>"
        )
    banner = "".join(
        f'<p class="spike">一斉に割れ（暴落の可能性）: {html.escape(m["label"])} 両方 −200 割れ '
        f"{m['both_down_count']} 件（線 {m['spike_line']:.0f} 件を超えた）</p>"
        for m in a["markets"].values()
        if m["spike"]
    )
    return (
        '<!DOCTYPE html>\n<html lang="ja"><head><meta charset="utf-8">'
        f"<title>CCI ±200 {html.escape(str(a['asof']))}</title>"
        "<style>body{font-family:sans-serif;font-size:13px}table{border-collapse:collapse;margin:8px 0}"
        "th,td{border:1px solid #ccc;padding:2px 6px}th{background:#eee;position:sticky;top:0}"
        ".bd{background:#ffe6e6}.w{background:#e6f0ff}.spike{color:#b00;font-weight:bold;font-size:16px}</style>"
        f"</head><body><h1>CCI ±200 の抜け（{html.escape(str(a['asof']))}）</h1>{banner}"
        "<table><thead><tr><th>市場</th><th>日付</th><th>銘柄数</th><th>両方 −200 割れ</th>"
        "<th>「一斉に割れ」の線</th><th></th><th>注記</th></tr></thead>"
        f"<tbody>{''.join(summary)}</tbody></table>"
        f"<p>ウォッチリストで −200 を抜けた銘柄: {len(a['watch_hits'])} 件。"
        "+200 を上に抜けたものは通知しません（列だけ）。過去の集計は verify_local.json の cci_both_down。"
        "このファイルは Mac mini のローカルにだけあります。</p>"
        f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></body></html>\n"
    )


def _names(rs: list[Row], n: int = TOP_N) -> str:
    s = "、".join(f"{r['code']} {r['name']}" for r in rs[:n])
    return s + (f" ほか{len(rs) - n}" if len(rs) > n else "")


def message(a: dict[str, Any]) -> tuple[str, str] | None:
    """(タイトル, 本文)。本文は市場ごとの件数＋上位銘柄（FX・仮想通貨は1つずつ全部・「未検証」）。無ければ None。"""
    parts = []
    for m in a["markets"].values():
        bd = m["both_down"]
        if not bd:
            continue
        if m["spike"]:
            parts.append(f"⚠{m['label']} 一斉に割れ {len(bd)} 件（線 {m['spike_line']:.0f} 件超え）: {_names(bd)}")
        elif m["verified"]:
            parts.append(f"{m['label']} 両方割れ {len(bd)} 件: {_names(bd)}")
        else:
            parts.append(f"{m['label']}（未検証）{len(bd)} 件: {_names(bd, n=len(bd))}")
    if a["watch_hits"]:
        parts.append(f"ウォッチ {len(a['watch_hits'])} 件: {_names(a['watch_hits'])}")
    sells = []  # 2026-11 追加: 売り目安（CCI +200）。既存の両方割れの文はそのまま、その後ろに足す
    for m in a["markets"].values():
        su = m.get(ind.CCI200_SELL) or []
        if su:
            tag = "" if m["verified"] else "（未検証）"
            names = _names(su, n=TOP_N if m["verified"] else len(su))
            sells.append(f"{m['label']}{tag} 売り目安（CCI +200）{len(su)} 件: {names}")
    if sells:
        parts += sells + [SELL_NOTE_TEXT]
    if not parts:
        return None
    spiked = [m["label"] for m in a["markets"].values() if m["spike"]]
    if spiked:
        title = f"⚠ 一斉に割れ（暴落の可能性）: {'・'.join(spiked)}"
    elif any(m["both_down"] for m in a["markets"].values()) or a["watch_hits"]:
        title = f"CCI −200 割れ {a['asof']}"
    else:
        title = f"売り目安（CCI +200） {a['asof']}"
    return title, " ／ ".join(parts)


def shown_path(p: Path, home: Path | None = None) -> str:
    """通知に書く一覧の場所（ホームの下なら ~/ から）。"""
    home = home or Path.home()
    try:
        return "~/" + str(p.resolve().relative_to(home.resolve()))
    except ValueError:
        return str(p)


def _ok(r: Any) -> None:
    rc = getattr(r, "returncode", 0)
    if rc not in (0, None):
        raise RuntimeError(f"終了コード {rc}")


Runner = Callable[..., Any]
SOUND_DIR = Path("/System/Library/Sounds")


def sound_settings(cfg: Any) -> dict[str, Any]:
    """config の [alerts] の音の設定。"""
    return {
        "enabled": bool(cfg.get("alerts.sound_enabled", True)),
        "spike": str(cfg.get("alerts.sound_spike", "Sosumi")),
        "signal": str(cfg.get("alerts.sound_signal", "Glass")),
    }


def sound_for(a: dict[str, Any], sounds: dict[str, Any] | None, sound_dir: Path = SOUND_DIR) -> str | None:
    """この通知で鳴らす音の名前。鳴らさないときは None。名前は sound_dir の実在のファイルと完全に一致したものだけ使う
    （誤った名前は音なし。osascript の文字列に入るので、ここを通らない値は渡さない）。"""
    if not sounds or not sounds.get("enabled"):
        return None
    ms = a["markets"].values()
    if any(m["spike"] for m in ms):
        name = sounds.get("spike")
    elif any(m["both_down"] or m.get(ind.CCI200_SELL) for m in ms):
        name = sounds.get("signal")
    else:
        return None
    if name in {p.stem for p in sound_dir.glob("*")}:
        return str(name)
    print(f"mac通知: 音の名前が {sound_dir} に無いので音なし（{name}）", flush=True)
    return None


def notify(
    a: dict[str, Any],
    html_path: Path,
    runner: Runner = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    platform: str = sys.platform,
    prefer: str = "osascript",
    home: Path | None = None,
    sounds: dict[str, Any] | None = None,
    sound_dir: Path = SOUND_DIR,
) -> str:
    """Mac mini の通知を1回出す。戻り値は使った方法（osascript / terminal-notifier / none / not_mac / error）。
    既定は osascript の display notification（macOS 26 では terminal-notifier が通知の許可の一覧に出ず使えなかった）。
    prefer="terminal-notifier" のときだけ試し、実行時にエラーなら osascript に切り替える。
    本文の最後に一覧のファイルの場所を書く。通知の失敗で本処理を失敗にしない。"""
    m = message(a)
    if m is None:
        print("mac通知: 該当なし", flush=True)
        return "none"
    title, body = m
    body = f"{body} ／ 一覧: {shown_path(html_path, home)}"
    if platform != "darwin":
        print(f"mac通知: Mac ではないので出さない（{title}）", flush=True)
        return "not_mac"
    sound = sound_for(a, sounds, sound_dir)
    tn = which("terminal-notifier") if prefer == "terminal-notifier" else None
    if tn:
        try:
            _ok(
                runner(
                    [
                        *[tn, "-title", title, "-message", body, "-open", html_path.as_uri()],
                        *["-group", "screener-cci"],
                        *(["-sound", sound] if sound else []),
                    ],
                    timeout=30,
                )
            )
            print(f"mac通知: terminal-notifier（{title}）→ {html_path}", flush=True)
            return "terminal-notifier"
        except Exception as e:
            print(f"mac通知: terminal-notifier が使えない（{type(e).__name__}）→ osascript に切り替え", flush=True)
    try:
        esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
        tail = f' sound name "{sound}"' if sound else ""
        script = f'display notification "{esc(body)}" with title "{esc(title)}"{tail}'
        _ok(runner(["osascript", "-e", script], timeout=30))
    except Exception as e:
        print(f"mac通知: 出せませんでした（{type(e).__name__}）", flush=True)
        return "error"
    print(f"mac通知: osascript（{title}・音 {sound or 'なし'}）→ {html_path}", flush=True)
    return "osascript"
