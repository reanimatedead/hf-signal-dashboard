"""米国株（S&P500・NASDAQ100・DOW30）: その時点で入手できた決算だけで指標を計算する。

式は screener.calc.fund_us（F・魔法の公式・残余利益）。ここはファイルの読み込みだけ。
決算（<data_dir>/us/facts/<ticker>.json）は1社ずつ読み、使い終わったら捨てる
（全社の companyfacts を同時にメモリに載せない）。
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from ..calc import contracts, fund_us
from ..config import Config

Row = dict[str, Any]
_px_cache: dict[tuple[str, str], Any] = {}


def universe(cfg: Config) -> dict[str, dict[str, Any]]:
    p = cfg.us("universe.json")
    if not p.exists():
        return {}
    with open(p) as fh:
        out: dict[str, dict[str, Any]] = json.load(fh)
        return out


def load_facts(t: str, cfg: Config) -> dict[str, Any] | None:
    try:
        with open(cfg.us("facts", f"{t}.json")) as fh:
            facts: dict[str, Any] = json.load(fh)["facts"]
            return facts
    except (OSError, ValueError, KeyError):
        return None


def load_px(t: str, cfg: Config) -> Any:
    key = (str(cfg.us_dir), t)
    if key not in _px_cache:
        try:
            with open(cfg.us("px", f"{t}.json")) as fh:
                _px_cache[key] = trim_last(fund_us.parse_yahoo_chart(json.load(fh)), t)
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            _px_cache[key] = None
    return _px_cache[key]


def trim_last(p: dict[str, Any], t: str, now: Any = None) -> dict[str, Any]:
    """米国の取引時間中の当日の未確定の足と、最後の足の単位の誤り（直近20本の中央値の 0.2 倍未満・5 倍超）を外す。
    規則は calc.contracts の 1 か所（公開側の fetch_signals.clean_bars と同じ）。"""
    if not p or not p.get("d"):
        return p
    last = dt.date.fromisoformat(p["d"][-1])
    c = [x if x is not None else float("nan") for x in p["c"]]
    if contracts.unfinished_last_bar("us", last, now) or contracts.last_bar_glitch(c):
        p = {k: (v[:-1] if isinstance(v, list) and k != "splits" else v) for k, v in p.items()}
    return p


def clear_cache() -> None:
    _px_cache.clear()


def screen(
    asof: str, p1y: str | None, p1m: str | None, cfg: Config, uni: dict[str, dict[str, Any]] | None = None
) -> list[Row]:
    uni = uni if uni is not None else universe(cfg)
    fixes = load_share_fixes(cfg)
    rows: list[Row] = []
    for t, info in uni.items():
        facts = load_facts(t, cfg)  # 1社ずつ
        r = fund_us.screen_one(t, info, facts, load_px(t, cfg), asof, p1y, p1m, fixes.get(t))
        del facts
        if r:
            rows.append(r)
    fund_us.apply_relative(rows, load_sics(cfg))  # 理論株価・上値余地は業種別 PER の中央値から（公開側と同じ関数）
    fund_us.rank(rows)
    return rows


def _fund_rows(cfg: Config) -> dict[str, Any]:
    """リポジトリの data/us_fundamentals.json の rows（SEC 由来）。無ければ空。"""
    try:
        with open(cfg.repo_dir / "data" / "us_fundamentals.json", encoding="utf-8") as fh:
            return json.load(fh).get("rows") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def load_sics(cfg: Config) -> dict[str, Any]:
    """{ticker: SIC}。無ければ空（全体の中央値になる）。"""
    return {t: (v or {}).get("sic") for t, v in _fund_rows(cfg).items()}


def load_share_fixes(cfg: Config) -> dict[str, tuple[float, str]]:
    """{ticker: (株数, 日付)}: 株の種類を換算した株数（週次の build_us_fundamentals.py が表紙から読んだ値）。"""
    return {t: (v["sh"], v["sh_end"]) for t, v in _fund_rows(cfg).items() if (v or {}).get("sh_src") == "cover"}


SCORE_INPUTS_CACHE = "score_inputs_v2"  # 定義を変えたら名前を変える（v2: 株の種類の換算・株数が古い月を除く）


def monthly_score_inputs(
    cfg: Config, months: list[str], uni: dict[str, Any] | None = None
) -> dict[str, dict[str, Any]]:
    """各月初の {ticker: [上値余地, PBR, PER, 一時利益の目印]}（売買スコアの検証用）。その月初より前に提出された決算
    （fund_us.fundamentals）× その月初の終値（Yahoo の分割調整済み close。株数も今の分割基準）。
    式は fund_us.value_inputs。
    過去の月初は変わらないので <data_dir>/us/derived/ に控える。"""
    import bisect
    import os

    uni = uni if uni is not None else universe(cfg)
    cdir = cfg.us("derived", SCORE_INPUTS_CACHE)
    out: dict[str, dict[str, Any]] = {}
    todo = []
    for m in months:
        cp = cdir / f"{m}.json"
        if cp.exists():
            with open(cp) as fh:
                out[m] = json.load(fh)
        else:
            todo.append(m)
            out[m] = {}
    if not todo:
        return rerate(out, cfg)
    fixes = load_share_fixes(cfg)
    for t in uni:
        facts = load_facts(t, cfg)  # 1社ずつ
        p = load_px(t, cfg)
        if not facts or not p:
            continue
        for m in todo:
            fd = fund_us.fundamentals(facts, m, p["splits"], fixes.get(t))
            k = bisect.bisect_right(p["d"], m) - 1
            while k >= 0 and p["c"][k] is None:
                k -= 1
            if not fd or k < 0 or fd.get("sh_stale"):  # 株数が古い月（要確認）は使わない
                continue
            up, pbr, per = fund_us.value_inputs(fd["ni"], fd["eq"], fd["sh"], fd["roe"], float(p["c"][k]))
            out[m][t] = [up, pbr, per, bool(fd.get("one_off"))]
        del facts
    cdir.mkdir(parents=True, exist_ok=True)
    last = max(months) if months else None
    for m in todo:
        if m == last:
            continue  # 今月はまだ決算が増えうるので控えない
        tmp = cdir / f"{m}.json.tmp"
        tmp.write_text(json.dumps(out[m]))
        os.replace(tmp, cdir / f"{m}.json")
    return rerate(out, cfg)


def rerate(out: dict[str, dict[str, Any]], cfg: Config) -> dict[str, dict[str, Any]]:
    """控えの余地（残余利益）を、月初ごとの業種別 PER の中央値からの余地に置き換える（fund_us.rerate_month）。"""
    sics = load_sics(cfg)
    return {m: fund_us.rerate_month(v, sics) for m, v in out.items()}


def fwd(t: str, a: str, b: str, cfg: Config) -> float | None:
    p = load_px(t, cfg)
    if not p:
        return None
    x, y = fund_us.price_at(p, a, True), fund_us.price_at(p, b, True)
    return (y / x - 1) * 100 if x and y else None
