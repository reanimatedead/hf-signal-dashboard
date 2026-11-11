#!/usr/bin/env python3
"""tools/layer_fallback.py — 層ごとに切り分けて、欠けた層だけ前回の正常なデータで公開する。

なぜ: 2026-11-10/11（Deploy #296・#298）、ECB の 10 年金利 API が GitHub の実行環境から 504 / 30 秒
タイムアウトになり relations.eu.series が 0 件になった。データ試験（200 件以上）が落ちて full ジョブ
全体が止まり、米国・日本・全タブの更新まで 11/9 のまま止まった（corr_refresh も 48 時間超で連鎖失敗）。

単位（unit）:
  relations.us / relations.eu / relations.jp   — 地域ごと（balance は米国の系列から作るので relations.us に属す）
  macro_v2 / gamma                              — ファイルごと

規則:
  - 今回の値が正常 → そのまま使い、stale=false・as_of=今回の時刻を付ける。
  - 今回の値が欠けた → 公開中（前回）の同じ単位が正常ならそれを使い、stale=true・as_of=その単位が
    最後に本当に取れた時刻（前回の as_of。前回も古いデータなら、その元の時刻のまま）を付ける。
  - 止める（exit 1）: relations の 3 地域が全部欠けた（取得の仕組みごと壊れている。前回データで全部を
    置き換えて「更新した」ことにしない）／relations の欠けた地域の前回分が無い・前回分も壊れている。
    macro_v2 / gamma は前回分も無ければ今までどおり今回のファイル（画面は「取得に失敗」）で公開し、警告だけ出す。
  - 古いデータの期限は設けない（as_of がそのまま画面に出て、ntfy が実行のたびに 1 回知らせ続ける）。
    止めた場合は upload/deploy が走らず、公開中のサイトはそのまま（今までどおり）。

出力: docs/ の各ファイルを書き換える。GITHUB_OUTPUT に stale=<カンマ区切りの単位>（無ければ空）。
deploy.yml はこれを見て、公開成功後に ntfy で 1 回知らせる。

前回分: 既定は公開中のサイト（PAGES_BASE）から取る。--prev-dir でローカルの前回分を渡せる（テスト用）。

Usage:
  python3 tools/layer_fallback.py [--docs docs] [--prev-dir DIR]
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

BASE = os.environ.get(
    "PAGES_BASE", "https://reanimatedead.github.io/hf-signal-dashboard").rstrip("/")
LAYERS = ("relations", "macro_v2", "gamma")
REGIONS = ("us", "eu", "jp")
MIN_SERIES = 200   # tests/test_contract_v2.py::test_relations_three_regions_series_length と同じ線
STALE_REASON = "fetch_failed_previous_kept"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


@dataclass
class Report:
    stale: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


# ── 正常かどうか ────────────────────────────────────────────────────────────
def region_ok(r) -> bool:
    return (isinstance(r, dict) and r.get("data_status") == "live"
            and len(r.get("series") or []) >= MIN_SERIES)


def macro_ok(m) -> bool:
    s = (m or {}).get("series") if isinstance(m, dict) else None
    return bool(s) and any((v or {}).get("data_status") == "live" for v in s.values())


def gamma_ok(g) -> bool:
    return isinstance(g, dict) and g.get("data_status") == "live"


FILE_OK = {"macro_v2": macro_ok, "gamma": gamma_ok}


def _as_of(unit, payload):
    """その単位が最後に本当に取れた時刻。単位に as_of があればそれ（前回も古いデータのとき元の時刻を保つ）。"""
    return (unit or {}).get("as_of") or (payload or {}).get("as_of")


# ── 本体（I/O なし）──────────────────────────────────────────────────────────
def apply(fresh: dict, prev: dict, now: datetime):
    """fresh / prev: {"relations": dict|None, "macro_v2": ..., "gamma": ...} → (out, Report)。"""
    rep = Report()
    out = {k: copy.deepcopy(v) for k, v in fresh.items()}
    prev = prev or {}

    # relations（地域ごと）
    rel = out.get("relations")
    prel = prev.get("relations") or {}
    if not isinstance(rel, dict):
        rep.errors.append("relations: 今回の relations.json が無い・読めない")
    else:
        regs = rel.setdefault("regions", {})
        bad = [k for k in REGIONS if not region_ok(regs.get(k))]
        if len(bad) == len(REGIONS):
            rep.errors.append("relations: us/eu/jp が全部欠けた（取得の仕組みごと壊れている）— 前回データで置き換えず止める")
        else:
            for k in REGIONS:
                if k not in bad:
                    regs[k]["stale"] = False
                    regs[k]["as_of"] = rel.get("as_of")
                    continue
                p = (prel.get("regions") or {}).get(k)
                if not region_ok(p):
                    rep.errors.append(f"relations.{k}: 今回欠けた・前回の正常なデータも無い — 欠けたまま公開しない")
                    continue
                q = copy.deepcopy(p)
                q.update({"stale": True, "as_of": _as_of(p, prel), "stale_reason": STALE_REASON})
                regs[k] = q
                rep.stale.append(f"relations.{k}")
            # balance（regime / beta / rebalance）は米国の系列から作る → 米国と運命を共にする
            if "relations.us" in rep.stale and isinstance(prel.get("balance"), dict):
                b = copy.deepcopy(prel["balance"])
                b.update({"stale": True, "as_of": _as_of(prel["balance"], prel), "stale_reason": STALE_REASON})
                rel["balance"] = b
            elif isinstance(rel.get("balance"), dict):
                rel["balance"]["stale"] = False
                rel["balance"]["as_of"] = rel.get("as_of")

    # macro_v2 / gamma（ファイルごと）
    for name, ok in FILE_OK.items():
        cur = out.get(name)
        if ok(cur):
            cur["stale"] = False
            continue
        p = prev.get(name)
        if not ok(p):
            if isinstance(cur, dict):
                # 今までどおり: この層は欠けても画面が「取得に失敗」と出すだけで公開は止めていなかった
                # （health_gate も警告だけ）。前回分も無いときは今回のファイルのまま公開する。
                cur["stale"] = False
                rep.warnings.append(f"{name}: 今回欠けた・前回の正常なデータも無い — 今回の値（取得失敗の表示）のまま公開")
            else:
                rep.errors.append(f"{name}: 今回の {name}.json が無い・読めない・前回分も無い — 止める")
            continue
        q = copy.deepcopy(p)
        q.update({"stale": True, "as_of": _as_of(p, p), "stale_reason": STALE_REASON})
        out[name] = q
        rep.stale.append(name)

    return out, rep


# ── I/O ─────────────────────────────────────────────────────────────────────
def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _fetch_prev(name: str):
    url = f"{BASE}/{name}.json?t={int(datetime.now().timestamp())}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  前回分を取れない: {url} ({type(e).__name__}: {e})")
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="docs")
    ap.add_argument("--prev-dir", default=None)
    a = ap.parse_args(argv)
    docs = Path(a.docs)

    fresh = {n: _read(docs / f"{n}.json") for n in LAYERS}
    if a.prev_dir:
        prev = {n: _read(Path(a.prev_dir) / f"{n}.json") for n in LAYERS}
    else:
        prev = {n: _fetch_prev(n) for n in LAYERS}

    out, rep = apply(fresh, prev, datetime.now(timezone.utc))

    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write(f"stale={','.join(rep.stale)}\n")

    for w in rep.warnings:
        print(f"::warning::layer_fallback: {w}")
    if rep.errors:
        for e in rep.errors:
            print(f"::error::layer_fallback: {e}")
        print("止めます（upload/deploy は走らず、公開中のサイトはそのまま）。")
        return 1

    for n in LAYERS:
        if out.get(n) is not None:
            (docs / f"{n}.json").write_text(
                json.dumps(out[n], ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if rep.stale:
        for u in rep.stale:
            print(f"::warning::layer_fallback: {u} は今回取れなかったため、前回の正常なデータ（古いデータの印付き）で公開します")
    else:
        print("layer_fallback: 全部の層が今回の値で正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
