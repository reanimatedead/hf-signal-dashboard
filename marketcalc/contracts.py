"""外部データの契約テスト用の判定関数（データ・通信は持たない）。
戻り値はすべて (ok: bool, message: str)。"""

EXPECTED_COUNTS = {"nikkei225": 225, "nasdaq100": 100, "sp500": 500, "dow30": 30}
COUNT_TOL = 0.05
MISSING_MAX = 0.10
JQ_DAILY_MIN = 3500
JQ_FIN_COLUMNS = ("NP", "Eq", "BPS", "NxFEPS", "EPS", "OP", "Sales", "TA", "CFO", "DocType", "CurFYEn", "DiscDate")
JQ_API_VERSION = "v2"
# 主要20銘柄（契約テストのサンプル。構成の変化に強い大型株）
US_PROBE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "V", "JNJ", "PG",
            "XOM", "WMT", "KO", "HD", "UNH", "CSCO", "PEP", "MRK", "CVX", "MCD"]
JP_PROBE = ["7203.T", "6758.T", "9984.T", "8306.T", "6861.T", "9432.T", "8035.T", "4063.T", "6098.T", "9983.T",
            "7974.T", "6501.T", "8058.T", "4502.T", "6367.T", "7267.T", "8031.T", "6954.T", "4568.T", "6902.T"]


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
