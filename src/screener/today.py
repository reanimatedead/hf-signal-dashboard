"""今日の要点を 1 枚にまとめる: <data_dir>/out/today.html（Mac mini のローカルだけ。リポジトリ・Pages には出さない）。

daily.py の最後（一覧と通知のあと）に作る。中身は日本株・米国株・ETF それぞれの
  - 売買スコアの段階5・段階4 の上位（スコアの高い順）
  - 本日の CCI ±200 の判定: 買い（CCI48・CCI288 がそろって −200 割れ）／売り目安（そろって +200 超え）
  - 決算が 7 日以内の注意（次の決算の推定日 calc.score.next_earnings）
  - 段階ごとの検証（20 営業日後の中央値・全期間と直近6か月・件数。verify_local.json の score_tiers）
J-Quants 由来の数値（日本株の PER・PBR・理論株価など）を含むので、Mac mini の中だけに置く（ADR-002）。
規則は持たない（行の値・検証の値は signals.run が calc.score / calc.ind で作ったものをそのまま使う）。
"""

from __future__ import annotations

import datetime as dt
import html
import os
from pathlib import Path
from typing import Any

from . import labels
from .calc import ind, score
from .config import Config
from .local_report import _check_outside_repo

TOP_N = 15
EARNINGS_DAYS = 7  # 決算が「7 日以内」（暦日）
MARKETS = (("jp", "日本株", "code", "company_name"), ("us", "米国株", "ticker", "name"), ("etf", "ETF", "code", "name"))
_HEAD = ["score", "score_tier", "score_value", "score_chart", "score_penalties", "chart_signal", "price"]
COLS = {
    "jp": [*_HEAD, "upside_pct", "PBR", "per_act", "next_earnings"],
    "us": [*_HEAD, "upside_pct", "PER", "PBR", "next_earnings"],
    "etf": [
        "score",
        "score_tier",
        "score_chart",
        "score_penalties",
        "etf_kind",
        "chart_signal",
        "price",
        "turnover_20d",
    ],
}


def _e(v: Any) -> str:
    return html.escape(labels.value(v))


def _table(rows: list[dict[str, Any]], key: str, name: str, cols: list[str]) -> str:
    if not rows:
        return "<p class=none>該当なし</p>"
    head = "".join(f"<th>{html.escape(labels.col(c))}</th>" for c in [key, name, *cols])
    body = "".join("<tr>" + "".join(f"<td>{_e(r.get(c))}</td>" for c in [key, name, *cols]) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _days(asof: str, d: str | None) -> int | None:
    if not d:
        return None
    try:
        return (dt.date.fromisoformat(d[:10]) - dt.date.fromisoformat(asof[:10])).days
    except ValueError:
        return None


def _tiers(t: dict[str, Any] | None) -> str:
    if not t:
        return "<p class=none>検証なし</p>"
    f = lambda s: "—" if not s or not s.get("n") else f"{s['median']:+.2f}%（{s['n']:,}件）"  # noqa: E731
    rows = "".join(
        f"<tr><td>{'基準（全営業日）' if k == 'base' else '段階' + k[4:]}</td>"
        f"<td>{f((t.get('full') or {}).get(k))}</td><td>{f((t.get('recent6m') or {}).get(k))}</td></tr>"
        for k in ("base", *score.TIER_KEYS)
    )
    warn = (
        "<p class=warn>⚠ 根拠が弱まっています（段階5 の直近6か月の中央値が基準を下回りました）</p>"
        if t.get("weakened")
        else ""
    )
    return (
        f"{warn}<table><thead><tr><th>段階</th><th>全期間 中央値（件数）</th>"
        f"<th>直近6か月（{html.escape(str(t.get('since') or ''))} 以降）</th></tr></thead><tbody>{rows}</tbody></table>"
    )


def render(doc: dict[str, Any]) -> str:
    asof = str(doc.get("asof") or "")
    v = doc.get("verify") or {}
    parts = []
    for m, title, key, name in MARKETS:
        rows = [r for r in doc.get(m) or [] if r.get("score_note") != "not_scored_inverse"]
        ranked = sorted((r for r in rows if r.get("score") is not None), key=lambda r: -float(r["score"]))
        t5 = [r for r in ranked if r.get("score_tier") == 5][:TOP_N]
        t4 = [r for r in ranked if r.get("score_tier") == 4][:TOP_N]
        buy = [r for r in rows if r.get("cci200_signal") == ind.CCI200_BUY]
        sell = [r for r in doc.get(m) or [] if r.get("cci200_signal") == ind.CCI200_SELL]
        earn = sorted(
            (r for r in rows if (d := _days(asof, r.get("next_earnings"))) is not None and 0 <= d <= EARNINGS_DAYS),
            key=lambda r: str(r.get("next_earnings")),
        )
        cols = COLS[m]
        parts.append(
            f"<h2>{title}</h2>"
            f"<h3>段階5 の上位（{len(t5)} 件）</h3>{_table(t5, key, name, cols)}"
            f"<h3>段階4 の上位（{len(t4)} 件）</h3>{_table(t4, key, name, cols)}"
            f"<h3 class=c2b>◆ 買い（CCI48・CCI288 がそろって −200 割れ）本日 {len(buy)} 件</h3>"
            f"{_table(buy, key, name, cols)}"
            f"<h3 class=c2s>◆ 売り目安（CCI48・CCI288 がそろって +200 超え）本日 {len(sell)} 件</h3>"
            f"<p class=note>利益確定・新しく買わない目安。空売りの根拠ではありません。</p>"
            f"{_table(sell, key, name, cols)}"
            + (
                f"<h3>決算が {EARNINGS_DAYS} 日以内（推定）{len(earn)} 件"
                " — 決算の前後は値動きが大きくなりやすいので注意</h3>"
                f"{_table(earn, key, name, cols)}"
                if m != "etf"
                else ""
            )
            + f"<h3>段階ごとの検証（20営業日後）</h3>{_tiers((v.get('score_tiers') or {}).get(m))}"
        )
    return (
        '<!DOCTYPE html>\n<html lang="ja"><head><meta charset="utf-8">'
        f"<title>今日の要点 {html.escape(asof)}</title>"
        "<style>body{font-family:sans-serif;font-size:13px;max-width:1400px;margin:12px auto;padding:0 12px}"
        "table{border-collapse:collapse;margin:4px 0 10px}th,td{border:1px solid #ccc;padding:2px 6px;text-align:left}"
        "th{background:#eee}h2{border-bottom:2px solid #333;margin-top:28px}h3{margin:14px 0 4px;font-size:14px}"
        ".c2b{color:#0891b2}.c2s{color:#c026d3}.note,.none{color:#666}.warn{color:#b45309;font-weight:bold}</style>"
        f"</head><body><h1>今日の要点（{html.escape(asof)}）</h1>"
        "<p>このファイルは Mac mini のローカルにだけあります（公開しない・J-Quants 由来の数値を含む）。"
        "スコアの配分は verify_local.json の score_rules。インバース ETF は対象外。投資助言ではありません。</p>"
        + "".join(parts)
        + "</body></html>\n"
    )


def write(cfg: Config, doc: dict[str, Any]) -> Path:
    p = cfg.out_dir / "today.html"
    _check_outside_repo(p, cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(render(doc), encoding="utf-8")
    os.replace(tmp, p)
    return p
