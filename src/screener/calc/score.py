"""売買スコア（割安の点・質の点・チャートの点・減点・売りの点）と 5 段階。規則と配分はここ 1 か所。

画面（公開 fetch_signals.py / Mac mini の一覧）・通知・検証（verify.json / verify_local.json）・
仕組み（About・about.json）はすべてこのモジュールの関数と W を使う（ind.P と同じ扱い）。データは持たない。

- 割安の点: 上値余地・PBR・PER の、市場ごとの順位（パーセンタイル 0〜1）× 配分。PER は正のときだけ。
- 質の点:   F（得点 / 満点）・ROE・自己資本比率（ROE と自己資本比率は市場ごとの順位）× 配分。
            未検証の安全条件として合計（score）には入れず、別の列で見せる。
- チャートの点: 判定（強い買い・買い・買い（長期の売られすぎ））＋ CCI ±200 の判定（ind.cci200_days: buy_cci200 /
            sell_cci200）を市場ごとの配分 CCI200 で。日本株の buy_cci200 は「一斉に割れ」の日だけ加点、
            sell_cci200 は減点。
            その市場の検証で直近6か月の成績が基準を下回ったもの（「根拠が弱まっています」と同じ events.weakened）は
            自動で 0 点（gate）。売り目安（sell_cci200）は「中央値が基準を上回った」= 外れたとき 0 点。
- 減点:     一時的な利益（one_off）・決算発表まで 5 営業日以内・売買代金（20 日平均）が市場の下位 10%。
            inverse ETF はスコアを付けない（物差しの対象外）。
- 売りの点: 売り・強い売り。「利益確定・新しく買わない」の目安（空売りの根拠ではない）。合計には入れない。
- 合計 score = 割安 + チャート − 減点。5 段階 score_tier は TIERS の線で切る。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np

from . import events, ind

# ── 配分（About と about.json に自動で出る）──────────────────────────────
W: dict[str, dict[str, int]] = {
    "value": {"upside": 15, "pbr": 10, "per": 10},
    "quality": {"f": 10, "roe": 8, "equity_ratio": 7},
    "chart": {ind.LABELS[2]: 30, ind.LABELS[1]: 20, ind.LONG_OVERSOLD_LABEL: 15},
    "penalty": {"one_off": 10, "earnings_soon": 10, "low_turnover": 10},
    "sell": {ind.LABELS[-1]: 20, ind.LABELS[-2]: 30},
}
# CCI ±200 の判定の点（市場ごと・検証の結果で決めた配分。ここ1か所）。キーが無いもの・0 は「表示だけ」。
# jp の buy_cci200_spike = 「一斉に割れ」（ind.spike_line を超えた日）の buy_cci200。ふだんの日の buy_cci200 は 0 点。
CCI200: dict[str, dict[str, int]] = {
    "us": {ind.CCI200_BUY: 10, ind.CCI200_SELL: 0},
    "jp": {ind.CCI200_BUY: 0, ind.CCI200_BUY + "_spike": 10, ind.CCI200_SELL: -10},
    "etf": {ind.CCI200_BUY: 0, ind.CCI200_SELL: 0},
    "fx": {ind.CCI200_BUY: 0, ind.CCI200_SELL: 0},
    "crypto": {ind.CCI200_BUY: 0, ind.CCI200_SELL: 0},
}
CCI200_UNVERIFIED = ("fx", "crypto")
# 合計が「以上」なら段階（上から順に最初に当てはまったもの）。どれにも当てはまらなければ TIER_ELSE。
TIERS: tuple[tuple[int, int], ...] = ((40, 5), (25, 4), (15, 3), (5, 2))
TIER_ELSE = 1
TIER_KEYS = tuple(f"tier{k}" for k in (5, 4, 3, 2, 1))
TOP_TIER = "tier5"
EARNINGS_SOON_BDAYS = 5  # 決算発表まで この営業日数以内 なら減点
LOW_TURNOVER_Q = 0.10  # 売買代金（20 日平均）が市場の下位 10% なら減点
TURNOVER_DAYS = 20
# 次の決算の推定: 過去の開示日 + 364 日（同じ曜日）。その 60 日前以降に実際の開示があれば済んだものとみなす。
EARN_YEAR_DAYS = 364
EARN_DONE_WINDOW = 60
NOT_SCORED_KINDS = ("inverse",)  # ETF の種類（calc.assets.etf_kind）でスコアを付けないもの
SELL_NOTE = ind.SELL_NOTE  # 売りの点は「利益確定・新しく買わない」の目安

# 行の列名（市場ごとに違う列名は呼ぶ側が fields で渡す）
FIELDS = {
    "upside": "upside_pct",
    "pbr": "PBR",
    "per": "PER",
    "f": "F",
    "f_max": "f_max",
    "roe": "roe_pct",
    "equity_ratio": "equity_ratio_pct",
    "turnover": "turnover_20d",
    "one_off": "one_off_flag",
    "earnings_soon": "earnings_soon",
    "label": "chart_signal",
    "cci200": "cci200_signal",
    "cci200_spike": "cci200_spike",
    "kind": "etf_kind",
}
OUT_KEYS = (
    "score",
    "score_tier",
    "score_value",
    "score_chart",
    "score_penalty",
    "score_penalties",
    "score_quality",
    "score_sell",
    "score_note",
)
ALL_PARTS = ("value", "chart", "penalty", "quality")
CHART_ONLY = ("chart",)


# ── 部品 ──────────────────────────────────────────────────────────────
def _fin(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def percentiles(vals: Sequence[Any], higher_better: bool = True) -> list[float | None]:
    """値の市場内の順位 0〜1（1 = 最も良い）。同じ値は平均の順位。None・非有限は None。1 件だけなら 0.5。"""
    v = [_fin(x) for x in vals]
    idx = [i for i, x in enumerate(v) if x is not None]
    out: list[float | None] = [None] * len(v)
    if not idx:
        return out
    a = np.array([v[i] for i in idx], dtype=float)
    if not higher_better:
        a = -a
    order = a.argsort(kind="mergesort")
    ranks = np.empty(len(a))
    ranks[order] = np.arange(len(a), dtype=float)
    for u in np.unique(a):  # 同順位は平均
        m = a == u
        ranks[m] = ranks[m].mean()
    n = len(a)
    for j, i in enumerate(idx):
        out[i] = 0.5 if n == 1 else round(float(ranks[j] / (n - 1)), 4)
    return out


def value_points(up_p: float | None, pbr_p: float | None, per_p: float | None) -> float:
    w = W["value"]
    return float(sum(w[k] * (p or 0.0) for k, p in (("upside", up_p), ("pbr", pbr_p), ("per", per_p))))


def quality_points(f: Any, f_max: Any, roe_p: float | None, eq_p: float | None) -> float | None:
    w = W["quality"]
    ff, fm = _fin(f), _fin(f_max)
    parts = [w["f"] * ff / fm if ff is not None and fm else None, None, None]
    parts[1] = w["roe"] * roe_p if roe_p is not None else None
    parts[2] = w["equity_ratio"] * eq_p if eq_p is not None else None
    if all(p is None for p in parts):
        return None
    return round(sum(p or 0.0 for p in parts), 1)


def _cci200_key(code: str | None, market: str, spike: bool) -> str | None:
    if not code:
        return None
    return code + "_spike" if (code == ind.CCI200_BUY and spike and code + "_spike" in CCI200.get(market, {})) else code


def gate_from_verify(
    chart_recent: Mapping[str, Any] | None,
    base_recent: Mapping[str, Any] | None,
    cci200: Mapping[str, Any] | None = None,
) -> dict[str, bool]:
    """点を付けてよいか（{判定コード: bool}）。直近6か月で中央値が基準を下回った（events.weakened が True =
    「根拠が弱まっています」と同じ規則）買い系は False = 0 点。件数が少なく判定できないものは True。
    cci200 は cci200_verify の出力: buy_cci200（recent6m）・buy_cci200_spike（一斉に割れの日の recent6m）・
    sell_cci200（売り目安。直近6か月の中央値が基準を「上回った」= 外れたら 0 点）。"""
    chart_recent = chart_recent or {}
    base = base_recent or {}
    out = {k: events.weakened(chart_recent.get(k), base) is not True for k in W["chart"]}
    c = cci200 or {}
    cb = (c.get("base") or {}).get("recent6m") or {}
    buy = c.get(ind.CCI200_BUY) or {}
    sell = c.get(ind.CCI200_SELL) or {}
    out[ind.CCI200_BUY] = events.weakened(buy.get("recent6m"), cb) is not True
    out[ind.CCI200_BUY + "_spike"] = events.weakened(buy.get("spike_recent6m"), cb) is not True
    out[ind.CCI200_SELL] = events.weakened(cb, sell.get("recent6m") or {}) is not True  # 売り目安後が基準より上 = 外れ
    return out


def chart_points(
    label: str | None,
    cci200: str | None = None,
    gate: Mapping[str, bool] | None = None,
    market: str = "us",
    spike: bool = False,
) -> int:
    """チャート判定の点 + CCI ±200 の判定の点（市場ごとの CCI200。gate で 0 点になるものは 0）。"""
    g = gate or {}
    p = W["chart"].get(label or "", 0) if g.get(label or "", True) else 0
    k = _cci200_key(cci200, market, spike)
    if k and g.get(k, True):
        p += CCI200.get(market, {}).get(k, 0)
    return int(p)


def sell_points(label: str | None) -> int:
    return int(W["sell"].get(label or "", 0))


def penalty(one_off: bool = False, earnings_soon: bool = False, low_turnover: bool = False) -> tuple[int, list[str]]:
    """(減点の合計（負の数）, 当てはまったコード)。"""
    codes = [
        k for k, on in (("one_off", one_off), ("earnings_soon", earnings_soon), ("low_turnover", low_turnover)) if on
    ]
    return -sum(W["penalty"][k] for k in codes), codes


def tier(total: float | None) -> int | None:
    if total is None:
        return None
    return next((t for th, t in TIERS if total >= th), TIER_ELSE)


def tiers_array(total: np.ndarray) -> np.ndarray:
    """合計の配列 → 段階の配列（tier と同じ線。NaN は 0 = 段階なし）。"""
    t = np.full(len(total), TIER_ELSE, dtype=int)
    done = np.zeros(len(total), dtype=bool)
    with np.errstate(invalid="ignore"):
        for th, k in TIERS:
            m = ~done & (total >= th)
            t[m] = k
            done |= m
    t[~np.isfinite(total)] = 0
    return t


# ── 売買代金・決算日 ───────────────────────────────────────────────────
def rolling_mean(v: Any, n: int = TURNOVER_DAYS) -> np.ndarray:
    """直近 n 日の平均（NaN は飛ばす。n 日のうち有効な日が半分未満なら NaN）。"""
    a = np.asarray(v, dtype=float)
    ok = np.isfinite(a)
    z = np.where(ok, a, 0.0)
    cs = np.concatenate([[0.0], np.cumsum(z)])
    cn = np.concatenate([[0], np.cumsum(ok)])
    out = np.full(len(a), np.nan)
    for i in range(len(a)):
        lo = max(0, i - n + 1)
        k = cn[i + 1] - cn[lo]
        if k >= max(1, n // 2):
            out[i] = (cs[i + 1] - cs[lo]) / k
    return out


def turnover_values(close: Any, volume: Any) -> np.ndarray:
    """日ごとの売買代金（終値 × 出来高）。"""
    return np.asarray(close, dtype=float) * np.asarray(volume, dtype=float)


def low_turnover_line(values: Iterable[Any], q: float = LOW_TURNOVER_Q) -> float | None:
    v = np.array([x for x in (_fin(t) for t in values) if x is not None and x > 0], dtype=float)
    return float(np.quantile(v, q)) if len(v) >= 10 else None


def low_turnover_matrix(mat: np.ndarray, q: float = LOW_TURNOVER_Q) -> np.ndarray:
    """銘柄 × 日 の売買代金（20 日平均）→ 日ごとの下位 q に入るか（bool 同じ形）。"""
    out = np.zeros(mat.shape, dtype=bool)
    for j in range(mat.shape[1]):
        col = mat[:, j]
        line = low_turnover_line(col[np.isfinite(col)], q)
        if line is not None:
            with np.errstate(invalid="ignore"):
                out[:, j] = col <= line
    return out


def _d(s: str) -> np.datetime64:
    return np.datetime64(str(s)[:10], "D")


def _candidates(past: Sequence[str]) -> list[tuple[np.datetime64, np.datetime64]]:
    """[(推定日, その推定が「済んだ」とみなす開示の下限日)]。"""
    p = sorted({str(x)[:10] for x in past if x})
    yd, dw = np.timedelta64(EARN_YEAR_DAYS, "D"), np.timedelta64(EARN_DONE_WINDOW, "D")
    return [(_d(x) + yd, _d(x) + yd - dw) for x in p]


def next_earnings(past: Sequence[str], today: str) -> str | None:
    """次の決算の推定日（YYYY-MM-DD）。past は過去の決算の開示日（10-K / 10-Q の提出日・決算短信の開示日）。
    1 年前の開示日 + 364 日 のうち today より後で最も近いもの。その 60 日前以降に実際の開示があれば済んだもの。"""
    t = _d(today)
    acts = sorted({_d(x) for x in past if x and _d(x) <= t})
    best = None
    for c, lo in _candidates([str(a) for a in acts]):
        if c <= t or any(lo <= a <= t for a in acts):
            continue
        best = c if best is None or c < best else best
    return str(best) if best is not None else None


def earnings_soon_days(days: Sequence[str], past: Sequence[str], n: int = EARNINGS_SOON_BDAYS) -> np.ndarray:
    """各日について、その日までの開示から推定した次の決算が n 営業日以内か（bool 配列）。
    画面の earnings_soon（最新日）と検証（日ごと）の両方がこれを使う。"""
    D = np.array([_d(x) for x in days], dtype="datetime64[D]")
    out = np.zeros(len(D), dtype=bool)
    if not len(D):
        return out
    acts = np.array(sorted({_d(x) for x in past if x}), dtype="datetime64[D]")
    for c, lo in _candidates([str(a) for a in acts]):
        bc = np.busday_count(D, c)
        win = (bc > 0) & (bc <= n)
        # 推定のもとになった開示より前の日には使わない・実際の開示（lo 以降）が出た日からは使わない
        win &= D > c - np.timedelta64(EARN_YEAR_DAYS, "D")
        done = acts[acts >= lo]
        if len(done):
            win &= D < done[0]
        out |= win
    return out


def earnings_soon(past: Sequence[str], today: str, n: int = EARNINGS_SOON_BDAYS) -> bool:
    return bool(earnings_soon_days([today], past, n)[-1])


def business_days_until(today: str, date: str | None) -> int | None:
    return None if not date else int(np.busday_count(_d(today), _d(date)))


# ── 行に付ける（画面・一覧）──────────────────────────────────────────────
def _empty(r: dict[str, Any], note: str = "") -> None:
    for k in OUT_KEYS:
        r[k] = None
    r["score_note"] = note or None


def score_rows(
    rows: list[dict[str, Any]],
    gate: Mapping[str, bool] | None = None,
    parts: Sequence[str] = ALL_PARTS,
    fields: Mapping[str, str] | None = None,
    market: str = "us",
) -> list[dict[str, Any]]:
    """1 つの市場の行にスコアの列（OUT_KEYS）を付ける（rows を書き換える）。
    parts に無い部分は None（公開の日本株は CHART_ONLY）。順位・下位 10% はこの rows の中で決める。"""
    f = {**FIELDS, **(fields or {})}
    live = [r for r in rows if (r.get(f["kind"]) or "") not in NOT_SCORED_KINDS]
    for r in rows:
        if r not in live:
            _empty(r, "not_scored_inverse")
    use = set(parts)

    def col(k: str, hb: bool, pos_only: bool = False) -> list[float | None]:
        vals = [_fin(r.get(f[k])) for r in live]
        if pos_only:
            vals = [v if v is not None and v > 0 else None for v in vals]
        return percentiles(vals, hb)

    up, pb, pe = col("upside", True), col("pbr", False, True), col("per", False, True)
    roe, eqr = col("roe", True), col("equity_ratio", True)
    line = low_turnover_line(r.get(f["turnover"]) for r in live) if "penalty" in use else None
    for i, r in enumerate(live):
        label = r.get(f["label"])
        v = round(value_points(up[i], pb[i], pe[i]), 1) if "value" in use else None
        if "value" in use and all(p is None for p in (up[i], pb[i], pe[i])):
            v = None
        c = (
            chart_points(label, r.get(f["cci200"]), gate, market, bool(r.get(f["cci200_spike"])))
            if label is not None
            else None
        )
        pen, codes = 0, list[str]()
        if "penalty" in use:
            t = _fin(r.get(f["turnover"]))
            low = line is not None and t is not None and t <= line
            pen, codes = penalty(bool(r.get(f["one_off"])), bool(r.get(f["earnings_soon"])), low)
        if c is None and v is None:
            _empty(r, "no_inputs")
            continue
        total = (v or 0.0) + (c or 0) + pen
        r["score"] = round(total, 1)
        r["score_tier"] = tier(total)
        r["score_value"] = v
        r["score_chart"] = c
        r["score_penalty"] = pen if "penalty" in use else None
        r["score_penalties"] = "|".join(codes) if "penalty" in use else None
        r["score_quality"] = (
            quality_points(r.get(f["f"]), r.get(f["f_max"]), roe[i], eqr[i]) if "quality" in use else None
        )
        r["score_sell"] = sell_points(label) if label is not None else None
        r["score_note"] = None
    return rows


# ── 検証（日ごとの段階 → 20 営業日後）─────────────────────────────────────
def chart_points_days(
    x: dict[str, Any],
    gate: Mapping[str, bool] | None = None,
    market: str = "us",
    ds: Sequence[str] | None = None,
    spike_days: set[str] | None = None,
) -> np.ndarray:
    """日ごとのチャートの点（画面と同じ chart_points を日ごとに）。spike_days は「一斉に割れ」の日付。"""
    lab = ind.day_labels(x)
    cd = ind.cci200_days(x)
    sp = spike_days or set()
    out = np.zeros(len(lab))
    for i in range(len(lab)):
        code = ind.CCI200_BUY if cd[ind.CCI200_BUY][i] else ind.CCI200_SELL if cd[ind.CCI200_SELL][i] else None
        out[i] = chart_points(str(lab[i]), code, gate, market, bool(ds is not None and ds[i] in sp))
    return out


def value_points_by_month(
    month_inputs: Mapping[str, Mapping[str, tuple[Any, Any, Any]]],
) -> dict[str, dict[str, float]]:
    """{月初: {銘柄: (上値余地, PBR, PER)}} → {月初: {銘柄: 割安の点}}
    （その月の市場の中の順位。score_rows と同じ式）。"""
    out: dict[str, dict[str, float]] = {}
    for m, rows in month_inputs.items():
        codes = list(rows)
        up = percentiles([rows[c][0] for c in codes], True)
        pos = [[v if (v := _fin(rows[c][k])) is not None and v > 0 else None for c in codes] for k in (1, 2)]
        pb, pe = percentiles(pos[0], False), percentiles(pos[1], False)
        out[m] = {
            c: round(value_points(up[i], pb[i], pe[i]), 1)
            for i, c in enumerate(codes)
            if not all(p is None for p in (up[i], pb[i], pe[i]))
        }
    return out


def by_month_days(code: str, days: Sequence[str], monthly: Mapping[str, Mapping[str, Any]], default: Any) -> list[Any]:
    """各日の値 = その日以前で最も近い月初の値（無ければ default）。"""
    import bisect

    ms = sorted(monthly)
    out = []
    for d in days:
        k = bisect.bisect_right(ms, d) - 1
        out.append(monthly[ms[k]].get(code, default) if k >= 0 else default)
    return out


def total_days(
    x: dict[str, Any],
    ds: Sequence[str],
    code: str,
    gate: Mapping[str, bool] | None = None,
    parts: Sequence[str] = ALL_PARTS,
    value_by_month: Mapping[str, Mapping[str, float]] | None = None,
    one_off_by_month: Mapping[str, Mapping[str, bool]] | None = None,
    earn_past: Sequence[str] | None = None,
    low_turnover: np.ndarray | None = None,
    market: str = "us",
    spike_days: set[str] | None = None,
) -> np.ndarray:
    """日ごとの合計点（score_rows と同じ部品: chart_points・割安の点（その月初の順位）・penalty）。
    割安の点の無い日は 0 点（score_rows と同じ扱い）。x と ds は同じ長さ（Close が有限な日だけ）。"""
    use = set(parts)
    tot = chart_points_days(x, gate, market, ds, spike_days) if "chart" in use else np.zeros(len(ds))
    if "value" in use and value_by_month:
        tot = tot + np.array(by_month_days(code, ds, value_by_month, 0.0), dtype=float)
    if "penalty" in use:
        oo = (
            np.array(by_month_days(code, ds, one_off_by_month, False), dtype=bool)
            if one_off_by_month
            else np.zeros(len(ds), dtype=bool)
        )
        es = earnings_soon_days(ds, earn_past or [])
        lt = np.asarray(low_turnover, dtype=bool) if low_turnover is not None else np.zeros(len(ds), dtype=bool)
        tot = (
            tot - W["penalty"]["one_off"] * oo - W["penalty"]["earnings_soon"] * es - W["penalty"]["low_turnover"] * lt
        )
    return tot


def low_turnover_by_symbol(turn: Mapping[str, tuple[Sequence[str], np.ndarray]]) -> dict[str, np.ndarray]:
    """{銘柄: (日付, 売買代金20日平均)} → {銘柄: 日ごとに市場の下位 10% か}
    （日付の和集合で並べて low_turnover_matrix）。"""
    days = sorted({d for ds, _ in turn.values() for d in ds})
    pos = {d: i for i, d in enumerate(days)}
    syms = list(turn)
    mat = np.full((len(syms), len(days)), np.nan)
    for i, s in enumerate(syms):
        ds, v = turn[s]
        mat[i, [pos[d] for d in ds]] = v
    low = low_turnover_matrix(mat)
    return {s: low[i, [pos[d] for d in turn[s][0]]] for i, s in enumerate(syms)}


def verify_tiers(
    items: Iterable[tuple[np.ndarray, np.ndarray, list[str]]],
    since: str | None,
    parts: Sequence[str] = ALL_PARTS,
) -> dict[str, Any]:
    """items: [(終値, 日ごとの合計点（NaN = 段階なし）, 日付)] → 段階ごとの 20 営業日後（全期間・直近6か月・件数）。
    最上位の段階（tier5）の直近の中央値が基準を下回れば weakened
    （「根拠が弱まっています」と同じ規則 events.weakened）。"""
    full: dict[str, list[float]] = {}
    recent: dict[str, list[float]] = {}
    n = 0
    for close, total, ds in items:
        t = tiers_array(np.asarray(total, dtype=float))
        conds = {f"tier{k}": t == k for k in range(1, 6)}
        events.merge(full, events.event_returns(close, conds))
        if since:
            events.merge(recent, events.event_returns(close, conds, dates=ds, since=since))
        n += 1
    keys = ("base", *TIER_KEYS)
    fs = {k: events.stats(full.get(k, [])) for k in keys}
    rs = {k: events.stats(recent.get(k, [])) for k in keys}
    wk = events.weakened(rs[TOP_TIER], rs["base"])
    return {
        "definition": "score_tiers",
        "parts": list(parts),
        "tiers": [{"tier": k, "ge": th} for th, k in TIERS] + [{"tier": TIER_ELSE, "ge": None}],
        "symbols": n,
        "horizon_days": events.H,
        "gap_days": events.GAP,
        "since": since,
        "full": fs,
        "recent6m": rs,
        "top_tier": TOP_TIER,
        "weakened": wk,
        "top_below_base_full": events.weakened(fs[TOP_TIER], fs["base"]),
    }


def cci200_verify(
    xs: Iterable[tuple[dict[str, Any], Sequence[str]]], spike_days: set[str] | None, since: str | None
) -> dict[str, Any]:
    """buy_cci200 / sell_cci200 の 20 営業日後
    （全期間・「一斉に割れ」の日を除く・一斉に割れの日だけ・直近6か月・件数）。
    基準 = 同じ銘柄・同じ期間の全営業日（base）。検証（verify / verify_local.json）と gate が同じこれを使う。"""
    acc: dict[str, list[tuple[str, float]]] = {}
    for x, ds in xs:
        events.merge(acc, events.event_returns_dated(x["c"], ind.cci200_days(x), list(ds)))
    sp = spike_days or set()

    def part(pairs: list[tuple[str, float]]) -> dict[str, Any]:
        return {
            "full": events.stats([f for _, f in pairs]),
            "excluding_spike_days": events.stats([f for d, f in pairs if d not in sp]),
            "spike_days_only": events.stats([f for d, f in pairs if d in sp]),
            "recent6m": events.stats([f for d, f in pairs if since and d >= since]),
            "spike_recent6m": events.stats([f for d, f in pairs if d in sp and since and d >= since]),
        }

    out: dict[str, Any] = {k: part(acc.get(k, [])) for k in ind.CCI200_LABELS}
    out["base"] = part(acc.get("base", []))
    out["since"] = since
    out["spike_days"] = len(sp)
    return out


def per_symbol_labels(x: dict[str, Any]) -> dict[str, Any]:
    """1 銘柄（ETF）の判定ごとの 20 営業日後（全期間）。ind.label_conditions と同じ規則。"""
    acc = events.event_returns(x["c"], ind.label_conditions(x))
    return {k: events.stats(v) for k, v in acc.items()}


def rules() -> dict[str, Any]:
    """配分と規則（仕組み（About）と about.json 用）。"""
    return {
        "weights": {k: dict(v) for k, v in W.items()},
        "max": {
            "value": sum(W["value"].values()),
            "quality": sum(W["quality"].values()),
            "chart": max(W["chart"].values()) + max(max(v.values()) for v in CCI200.values()),
            "penalty": -sum(W["penalty"].values()),
        },
        "total": ["value", "chart", "penalty"],
        "separate": ["quality", "sell"],
        "tiers": [{"ge": th, "tier": k} for th, k in TIERS],
        "tier_else": TIER_ELSE,
        "earnings_soon_bdays": EARNINGS_SOON_BDAYS,
        "earnings_estimate": {"year_days": EARN_YEAR_DAYS, "done_window_days": EARN_DONE_WINDOW},
        "low_turnover_q": LOW_TURNOVER_Q,
        "turnover_days": TURNOVER_DAYS,
        "not_scored_kinds": list(NOT_SCORED_KINDS),
        "chart_gate": "recent6m_median_below_base_zero",
        "cci200": {m: dict(v) for m, v in CCI200.items()},
        "cci200_unverified": list(CCI200_UNVERIFIED),
        "cci200_labels": list(ind.CCI200_LABELS),
        "per_positive_only": True,
        "sell_note": SELL_NOTE,
        "public_japan_parts": list(CHART_ONLY),
        "weakened_rule": "recent6m_top_tier_median_below_base",
    }


def today_iso() -> str:
    return dt.date.today().isoformat()
