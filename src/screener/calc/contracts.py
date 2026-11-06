"""外部データの契約テスト用の判定関数（データ・通信は持たない）。
戻り値はすべて (ok: bool, message: str)。"""

EXPECTED_COUNTS = {"nikkei225": 225, "nasdaq100": 100, "sp500": 500, "dow30": 30}
COUNT_TOL = 0.05
MISSING_MAX = 0.10
JQ_DAILY_MIN = 3500
JQ_FIN_COLUMNS = ("NP", "Eq", "BPS", "NxFEPS", "EPS", "OP", "Sales", "TA", "CFO", "DocType", "CurFYEn", "DiscDate")
JQ_API_VERSION = "v2"
# 主要20銘柄（契約テストのサンプル。構成の変化に強い大型株）
US_PROBE = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "JPM",
    "V",
    "JNJ",
    "PG",
    "XOM",
    "WMT",
    "KO",
    "HD",
    "UNH",
    "CSCO",
    "PEP",
    "MRK",
    "CVX",
    "MCD",
]
JP_PROBE = [
    "7203.T",
    "6758.T",
    "9984.T",
    "8306.T",
    "6861.T",
    "9432.T",
    "8035.T",
    "4063.T",
    "6098.T",
    "9983.T",
    "7974.T",
    "6501.T",
    "8058.T",
    "4502.T",
    "6367.T",
    "7267.T",
    "8031.T",
    "6954.T",
    "4568.T",
    "6902.T",
]


def count_within(name, n, expected=None, tol=COUNT_TOL):
    e = expected if expected is not None else EXPECTED_COUNTS[name]
    ok = abs(n - e) <= e * tol
    return ok, f"{name}: {n} 件（想定 {e} ±{int(tol * 100)}%）" + ("" if ok else " → 外れ")


def missing_ratio_ok(name, got, total, max_ratio=MISSING_MAX):
    miss = (total - got) / total if total else 1.0
    ok = miss <= max_ratio
    return ok, f"{name}: 取れない割合 {miss * 100:.0f}%（上限 {int(max_ratio * 100)}%）" + ("" if ok else " → 止める")


def min_count(name, n, minimum):
    ok = n >= minimum
    return ok, f"{name}: {n} 件（最低 {minimum}）" + ("" if ok else " → 足りない")


def has_columns(name, row, cols):
    miss = [c for c in cols if c not in (row or {})]
    return not miss, f"{name}: 列 " + ("すべてあり" if not miss else f"不足 {miss}")


def summarize(results):
    """[(ok,msg),...] → (全部ok, 本文)。"""
    ok = all(r[0] for r in results)
    body = "\n".join(("✅ " if r[0] else "❌ ") + r[1] for r in results)
    return ok, body


# ── 価格の単位の誤り（Yahoo の日本の ETF で 1 本だけ 1/100・1/10 になる等）──────────────────
GLITCH_FACTOR = 3.0  # 前後の終値の中央値から 3 倍以上（1/3 以下）離れた 1 本を誤りとみなす
GLITCH_WINDOW = 2  # 前後それぞれ 2 本ずつ


def price_glitch_mask(close, factor=GLITCH_FACTOR, w=GLITCH_WINDOW):
    """終値の配列 → 単位の誤りとみなす日の bool 配列（前後 w 本ずつの中央値から factor 倍以上離れた日）。"""
    import numpy as np

    c = np.asarray(close, dtype=float)
    out = np.zeros(len(c), dtype=bool)
    for i in range(len(c)):
        if not np.isfinite(c[i]) or c[i] <= 0:
            continue
        nb = np.concatenate([c[max(0, i - w) : i], c[i + 1 : i + 1 + w]])
        nb = nb[np.isfinite(nb) & (nb > 0)]
        if len(nb) < 2:
            continue
        m = float(np.median(nb))
        out[i] = c[i] > m * factor or c[i] < m / factor
    return out


# ── 最後の足の単位の誤り（全銘柄。直近20本の中央値と比べる）────────────────────────────────
LAST_GLITCH_WINDOW = 20  # 最後の足の前の 20 本
LAST_GLITCH_LO = 0.2  # 中央値の 0.2 倍未満
LAST_GLITCH_HI = 5.0  # 中央値の 5 倍超


def last_bar_glitch(close, w=LAST_GLITCH_WINDOW, lo=LAST_GLITCH_LO, hi=LAST_GLITCH_HI):
    """終値の配列 → 最後の足が単位の誤りか（その前の w 本の中央値の lo 倍未満か hi 倍超）。"""
    import numpy as np

    c = np.asarray(close, dtype=float)
    if not len(c) or not np.isfinite(c[-1]) or c[-1] <= 0:
        return False
    prev = c[:-1][-w:]
    prev = prev[np.isfinite(prev) & (prev > 0)]
    if len(prev) < 5:
        return False
    m = float(np.median(prev))
    return bool(c[-1] < m * lo or c[-1] > m * hi)


# ── 取引時間中の未確定の足（その市場の取引時間中に走らせたとき、当日の足は判定・検証に使わない）──
# 東証は 9:00〜15:30 JST（昼休みも含めて未確定）、米国は現地時間 9:30〜16:00（夏時間は zoneinfo が扱う）。
SESSIONS = {
    "jp": ("Asia/Tokyo", (9, 0), (15, 30)),
    "us": ("America/New_York", (9, 30), (16, 0)),
}


def market_of(symbol):
    """銘柄コード → "jp" | "us" | None（FX・暗号資産など取引時間の決まりがないもの）。"""
    s = str(symbol or "")
    if s.endswith(".T") or s in ("^N225", "^TOPX"):
        return "jp"
    if "=" in s or s.endswith("-USD"):
        return None
    return "us"


def session_today(market, now=None):
    """その市場がいま取引時間中なら、現地の今日の日付（datetime.date）。時間外・週末・市場なしは None。"""
    import datetime as dt
    from zoneinfo import ZoneInfo

    if market not in SESSIONS:
        return None
    tz, (oh, om), (ch, cm) = SESSIONS[market]
    t = (now or dt.datetime.now(dt.UTC)).astimezone(ZoneInfo(tz))
    if t.weekday() >= 5 or not (dt.time(oh, om) <= t.time() < dt.time(ch, cm)):
        return None
    return t.date()


def unfinished_last_bar(market, last_date, now=None):
    """最後の足の日付が、取引時間中の市場の「今日」なら True（未確定の足）。休場日は今日の足が無いので False。"""
    d = session_today(market, now)
    return d is not None and last_date is not None and last_date == d
