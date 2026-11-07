"""日本株の一覧を Mac mini のローカル（<data_dir>/out/）にだけ書き出す。リポジトリ・Pages には出さない（ADR-002）。

out/japan_list.csv    日本株の一覧（列名・値はコード: grade A/B/C・chart_signal・fair_price・one_off_note など）
out/japan_list.html   同じ内容の簡単な表（言葉は screener.labels で付ける。ブラウザで開くだけ。外部の読み込みなし）
out/us_list.csv       米国株の一覧
out/us_list.html      同じ形の簡単な表（米国株）
out/etf_list.csv      ETF（J-Quants の銘柄一覧で「市場：その他」の ETF・ETN。種類 etf_kind・チャート判定・スコア）
out/etf_list.html     同じ形の簡単な表（ETF）
out/verify_local.json 検証（20営業日後 vs 基準。cci_both_down.<jp/us/fx/crypto> = CCI 両方 −200 割れの検証）
out/cci_alerts.html   CCI ±200 の抜けの一覧（最新・日本株/米国株/FX/仮想通貨）。日付つきの
                      cci_alerts_YYYY-MM-DD.html も残す（通知の本文の最後にこの場所を書く）
out/counts.json       件数（前回の件数 previous と、日本株の件数のずれ % も入れる）
"""

from __future__ import annotations

import collections
import csv
import datetime as dt
import html
import json
import os
from pathlib import Path
from typing import Any

from . import alerts, labels
from .config import PACKAGE_REPO, Config, _inside

GRADE_ORDER = {"A": 0, "B": 1, "C": 2}
SCORE_COLS = [
    "score", "score_tier", "score_value", "score_chart", "score_penalty", "score_penalties", "score_quality",
    "score_sell",
]  # fmt: skip
HTML_COLS = [
    "grade", "code", "company_name", "market", "sector", "chart_signal", "cci200_signal", *SCORE_COLS, "price",
    "fair_price",
    "upside_pct", "value_quintile", "quality_candidate", "PBR", "per_fwd", "per_act", "roe_act_pct",
    "div_yield_fwd_pct", "equity_ratio_pct", "turnover_20d", "next_earnings", "F", "f_max", "magic_rank", "fin_tag",
    "mcap_oku_jpy", "one_off_note", "one_off_reasons",
]  # fmt: skip
US_HTML_COLS = [
    "grade", "ticker", "name", "idx", "sector", "chart_signal", "cci200_signal", *SCORE_COLS, "trend", "price",
    "fair_price",
    "upside_pct", "value_check", "PER", "PBR", "roe_pct", "div_yield_pct", "equity_ratio_pct", "turnover_20d",
    "next_earnings", "fin_tag", "magic_rank", "F", "f_max",
]  # fmt: skip
ETF_HTML_COLS = [
    "code", "name", "etf_kind", "chart_signal", "cci200_signal", "score", "score_tier", "score_chart", "score_penalty",
    "score_penalties", "score_sell", "score_note", "price", "turnover_20d", "cci48", "cci288", "bb48_z", "bb288_z",
]  # fmt: skip
JP_NOTE = (
    "総合判定 A = 割安5分の1（プライム・スタンダード／金融を除く／時価総額300億円以上の中で上値余地が上位20%）"
    "× 買い系のチャート判定。"
    "品質の候補（長期候補・中期候補）は別の列です。一時利益の目印がある銘柄は決算短信で確認してください。"
)
SCORE_NOTE = (
    "スコア = 割安の点（上値余地・PBR・PER の市場内の順位）＋ チャートの点 − 減点（一時利益・決算まで5営業日以内・"
    "売買代金が下位10%）。質の点（F・ROE・自己資本比率）は未検証の安全条件として合計に入れず別の列です。"
    "売りの点は「利益確定・新しく買わない」の目安で、空売りの根拠ではありません。"
    "配分は verify_local.json の score_rules。"
)
ETF_NOTE = (
    "J-Quants の銘柄一覧で「市場：その他」の ETF・ETN。種類は名前から判定（レバレッジ・ブル・2倍 → leveraged、"
    "ベア・インバース・-1倍 → inverse、指数名 → index、それ以外 → unknown）。"
    "inverse は物差しの対象外でスコアを付けません。"
    "判定ごとの20営業日後の成績は verify_local.json の etf。"
)
US_NOTE = (
    "総合判定 A = 財務判定（割安×質 上位50・中期候補）× 買い系のチャート判定"
    "（米国株は理論株価の余地を出していません）。"
)


def _check_outside_repo(p: Path, cfg: Config) -> None:
    for repo in {PACKAGE_REPO, cfg.repo_dir}:
        if _inside(p, repo):
            raise RuntimeError(f"出力先がリポジトリの中です: {p}（J-Quants 由来のデータはリポジトリに書かない）")


def dump_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    obj = {"computed_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), **obj}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


def verify_dir(cfg: Config, month: str | None = None) -> Path:
    from .config import today_jst

    p = cfg.out("verify", month or today_jst().strftime("%Y-%m"))
    _check_outside_repo(p, cfg)
    return p


def _write_csv(p: Path, rows: list[dict[str, Any]]) -> None:
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
        if rows:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    os.replace(tmp, p)


def _sort_key(r: dict[str, Any]) -> tuple[int, float]:
    return GRADE_ORDER.get(r.get("grade", "C"), 9), -(r.get("upside_pct") or -1e9)


def _score_key(r: dict[str, Any]) -> tuple[float, str]:
    v = r.get("score")
    return -(float(v) if v is not None else -1e9), str(r.get("code", ""))


def render_html(
    rows: list[dict[str, Any]],
    asof: str,
    cols: list[str] = HTML_COLS,
    title: str = "日本株の一覧",
    note: str = JP_NOTE,
    warning: str = "",
) -> str:
    """HTML の表（日本株・米国株で同じ形）。データはコードのまま渡し、列名・値の言葉は screener.labels で付ける。"""
    head = "".join(f"<th>{html.escape(labels.col(c))}</th>" for c in cols)
    body = []
    for r in rows:
        tds = "".join(f"<td>{html.escape(labels.value(r.get(c)))}</td>" for c in cols)
        body.append(f'<tr class="g{html.escape(str(r.get("grade", "")))}">{tds}</tr>')
    return (
        '<!DOCTYPE html>\n<html lang="ja"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)} {html.escape(asof)}</title>"
        "<style>body{font-family:sans-serif;font-size:13px}table{border-collapse:collapse}"
        "th,td{border:1px solid #ccc;padding:2px 6px}th{background:#eee;position:sticky;top:0}"
        ".gA{background:#e6ffe6}.gB{background:#fffbe6}</style></head><body>"
        f"<h1>{html.escape(title)}（{html.escape(asof)}・{len(rows)} 件）</h1>"
        + (f'<p style="color:#b45309;font-weight:bold">{html.escape(warning)}</p>' if warning else "")
        + f"<p>このファイルは Mac mini のローカルにだけあります（公開しない）。{html.escape(note)}</p>"
        f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></body></html>\n"
    )


def weak_warning(v: dict[str, Any]) -> str:
    """「根拠が弱まっています」（verify_local.json の weakened_items。売買スコアの最上位の段階を含む）。"""
    items = v.get("weakened_items") or []
    if not v.get("weakened"):
        return ""
    return "⚠ 根拠が弱まっています: " + "・".join(labels.weak_item(x) for x in items)


def counts(doc: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    jp, us = doc.get("jp") or [], doc.get("us") or []
    c: dict[str, Any] = {
        "asof": doc.get("asof"),
        "japan_rows": len(jp),
        "us_rows": len(us),
        "etf_rows": len(doc.get("etf") or []),
        "japan_grades": dict(sorted(collections.Counter(r.get("grade") for r in jp).items())),
        "us_grades": dict(sorted(collections.Counter(r.get("grade") for r in us).items())),
    }
    if previous:
        prev = {k: v for k, v in previous.items() if k not in ("previous", "japan_diff_pct")}
        c["previous"] = prev
        pj = prev.get("japan_rows") or 0
        c["japan_diff_pct"] = round(100 * (len(jp) - pj) / pj, 1) if pj else None
    return c


def alerts_html(cfg: Config, doc: dict[str, Any]) -> Path:
    """その日の CCI ±200 の一覧（通知を押すと開く）。"""
    return cfg.out_dir / f"cci_alerts_{(doc.get('cci_alerts') or {}).get('asof')}.html"


def write(cfg: Config, doc: dict[str, Any]) -> dict[str, Any]:
    out = cfg.out_dir
    _check_outside_repo(out, cfg)
    out.mkdir(parents=True, exist_ok=True)
    jp = sorted(doc.get("jp") or [], key=_sort_key)
    us = sorted(doc.get("us") or [], key=_sort_key)
    asof = str(doc.get("asof") or "")
    etf = sorted(doc.get("etf") or [], key=_score_key)
    warn = weak_warning(doc.get("verify") or {})
    _write_csv(out / "japan_list.csv", jp)
    (out / "japan_list.html").write_text(
        render_html(jp, asof, note=JP_NOTE + SCORE_NOTE, warning=warn), encoding="utf-8"
    )
    _write_csv(out / "us_list.csv", us)
    (out / "us_list.html").write_text(
        render_html(us, asof, US_HTML_COLS, "米国株の一覧", US_NOTE + SCORE_NOTE, warn), encoding="utf-8"
    )
    _write_csv(out / "etf_list.csv", etf)
    (out / "etf_list.html").write_text(
        render_html(etf, asof, ETF_HTML_COLS, "ETF の一覧", ETF_NOTE + SCORE_NOTE, warn), encoding="utf-8"
    )
    dump_json(out / "verify_local.json", doc.get("verify") or {})
    a = doc.get("cci_alerts")
    if a:
        page = alerts.render_html(a)
        (out / f"cci_alerts_{a['asof']}.html").write_text(page, encoding="utf-8")
        (out / "cci_alerts.html").write_text(page, encoding="utf-8")
    cp = out / "counts.json"
    previous = None
    if cp.exists():
        try:
            previous = json.loads(cp.read_text())
        except ValueError:
            previous = None
    c = counts(doc, previous)
    dump_json(cp, c)
    return c
