"""日本株の一覧を Mac mini のローカル（<data_dir>/out/）にだけ書き出す。リポジトリ・Pages には出さない（ADR-002）。

out/japan_list.csv    日本株の一覧（総合判定 A/B/C・チャート判定・理論株価・一時利益の目印 など）
out/japan_list.html   同じ内容の簡単な表（ブラウザで開くだけ。外部の読み込みなし）
out/us_list.csv       米国株の一覧
out/verify_local.json 検証（20営業日後 vs 基準）
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

from .config import PACKAGE_REPO, Config, _inside

GRADE_ORDER = {"A": 0, "B": 1, "C": 2}
HTML_COLS = [
    "総合判定", "コード", "会社名", "市場", "業種", "チャート判定", "株価", "理論株価", "上値余地%", "PBR",
    "F", "F満点", "魔法の公式順位", "財務判定", "時価総額(億円)", "一時利益の目印", "一時利益の理由",
]  # fmt: skip


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
    return GRADE_ORDER.get(r.get("総合判定", "C"), 9), -(r.get("上値余地%") or -1e9)


def render_html(rows: list[dict[str, Any]], asof: str) -> str:
    head = "".join(f"<th>{html.escape(c)}</th>" for c in HTML_COLS)
    body = []
    for r in rows:
        tds = "".join(f"<td>{html.escape('' if r.get(c) is None else str(r.get(c)))}</td>" for c in HTML_COLS)
        body.append(f'<tr class="g{html.escape(str(r.get("総合判定", "")))}">{tds}</tr>')
    return (
        '<!DOCTYPE html>\n<html lang="ja"><head><meta charset="utf-8">'
        f"<title>日本株の一覧 {html.escape(asof)}</title>"
        "<style>body{font-family:sans-serif;font-size:13px}table{border-collapse:collapse}"
        "th,td{border:1px solid #ccc;padding:2px 6px}th{background:#eee;position:sticky;top:0}"
        ".gA{background:#e6ffe6}.gB{background:#fffbe6}</style></head><body>"
        f"<h1>日本株の一覧（{html.escape(asof)}・{len(rows)} 件）</h1>"
        "<p>このファイルは Mac mini のローカルにだけあります（公開しない）。"
        "一時利益の目印がある銘柄は決算短信で確認してください。</p>"
        f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></body></html>\n"
    )


def counts(doc: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    jp, us = doc.get("jp") or [], doc.get("us") or []
    c: dict[str, Any] = {
        "asof": doc.get("asof"),
        "japan_rows": len(jp),
        "us_rows": len(us),
        "japan_grades": dict(sorted(collections.Counter(r.get("総合判定") for r in jp).items())),
        "us_grades": dict(sorted(collections.Counter(r.get("総合判定") for r in us).items())),
    }
    if previous:
        prev = {k: v for k, v in previous.items() if k not in ("previous", "japan_diff_pct")}
        c["previous"] = prev
        pj = prev.get("japan_rows") or 0
        c["japan_diff_pct"] = round(100 * (len(jp) - pj) / pj, 1) if pj else None
    return c


def write(cfg: Config, doc: dict[str, Any]) -> dict[str, Any]:
    out = cfg.out_dir
    _check_outside_repo(out, cfg)
    out.mkdir(parents=True, exist_ok=True)
    jp = sorted(doc.get("jp") or [], key=_sort_key)
    us = sorted(doc.get("us") or [], key=_sort_key)
    asof = str(doc.get("asof") or "")
    _write_csv(out / "japan_list.csv", jp)
    (out / "japan_list.html").write_text(render_html(jp, asof), encoding="utf-8")
    _write_csv(out / "us_list.csv", us)
    dump_json(out / "verify_local.json", doc.get("verify") or {})
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
