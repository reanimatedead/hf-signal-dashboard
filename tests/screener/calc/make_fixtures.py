"""架空の5銘柄×400営業日・決算2期分のサンプルデータを作る（決まった乱数で毎回同じ）。
本物のデータは一切使わない。実行: python tests/screener/calc/make_fixtures.py"""
import datetime as dt
import json
import pathlib

import numpy as np

OUT = pathlib.Path(__file__).parent / "fixtures"
TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE"]
N = 400


def bdays(n, start=dt.date(2025, 1, 2)):
    d, out = start, []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def series(k, rng):
    t = np.arange(N)
    if k == 0:   # 長期上向き → 最後に急落（買い・強い買いが出る）
        c = 100 * np.exp(0.0015 * t); c[-6:] *= np.array([0.97, 0.94, 0.91, 0.88, 0.85, 0.82])
    elif k == 1:  # 長期下向き → 最後に急騰（売りが出る）
        c = 100 * np.exp(-0.0015 * t); c[-6:] *= np.array([1.03, 1.06, 1.09, 1.12, 1.15, 1.18])
    elif k == 2:  # 横ばいの波
        c = 100 + 5 * np.sin(t / 15)
    elif k == 3:  # ランダムウォーク
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, N)))
    else:         # 長期の大きな下落（長期の売られすぎ）
        c = 100 * np.exp(0.0005 * t); c[-40:] *= np.linspace(1.0, 0.6, 40)
    c = c * (1 + rng.normal(0, 0.002, N))
    h = c * (1 + np.abs(rng.normal(0, 0.005, N))); l = c * (1 - np.abs(rng.normal(0, 0.005, N)))
    return h, l, c


def facts(k):
    """EDGAR companyfacts 形（2期分の 10-K）。"""
    base = 1e9 * (k + 1)
    def fy(tag, v0, v1, unit="USD"):
        return {tag: {"units": {unit: [
            {"start": "2023-01-01", "end": "2023-12-31", "val": v0, "form": "10-K", "fp": "FY", "filed": "2024-02-15"},
            {"start": "2024-01-01", "end": "2024-12-31", "val": v1, "form": "10-K", "fp": "FY", "filed": "2025-02-15"}]}}}
    def inst(tag, v0, v1):
        return {tag: {"units": {"USD": [
            {"end": "2023-12-31", "val": v0, "form": "10-K", "fp": "FY", "filed": "2024-02-15"},
            {"end": "2024-12-31", "val": v1, "form": "10-K", "fp": "FY", "filed": "2025-02-15"}]}}}
    g = {}
    g.update(fy("NetIncomeLoss", 0.10 * base, 0.12 * base)); g.update(fy("OperatingIncomeLoss", 0.15 * base, 0.18 * base))
    g.update(fy("NetCashProvidedByUsedInOperatingActivities", 0.14 * base, 0.16 * base))
    g.update(fy("Revenues", 1.0 * base, 1.1 * base)); g.update(fy("GrossProfit", 0.4 * base, 0.46 * base))
    g.update(inst("StockholdersEquity", 0.9 * base, 1.0 * base)); g.update(inst("Assets", 2.0 * base, 2.1 * base))
    g.update(inst("AssetsCurrent", 0.8 * base, 0.85 * base)); g.update(inst("LiabilitiesCurrent", 0.5 * base, 0.5 * base))
    g.update(inst("PropertyPlantAndEquipmentNet", 0.6 * base, 0.62 * base))
    g.update(inst("LongTermDebtNoncurrent", 0.5 * base, 0.45 * base)); g.update(inst("CashAndCashEquivalentsAtCarryingValue", 0.2 * base, 0.25 * base))
    g.update(fy("WeightedAverageNumberOfDilutedSharesOutstanding", 1e7 * (k + 1), 1e7 * (k + 1), "shares"))
    dei = {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2025-01-31", "val": 1e7 * (k + 1), "form": "10-K", "filed": "2025-02-15"}]}}}
    return {"facts": {"us-gaap": g, "dei": dei}}


def main():
    OUT.mkdir(exist_ok=True)
    rng = np.random.default_rng(42)
    days = bdays(N)
    ts = [int(dt.datetime(d.year, d.month, d.day, 14, 30, tzinfo=dt.timezone.utc).timestamp()) for d in days]
    for k, t in enumerate(TICKERS):
        h, l, c = series(k, rng)
        ev = {}
        if k == 3:  # DDD は途中で 2:1 分割（株価は Yahoo と同じく分割調整後）
            ev = {"splits": {str(ts[200]): {"numerator": 2, "denominator": 1}}}
        j = {"chart": {"result": [{"timestamp": ts, "events": ev, "indicators": {
            "quote": [{"high": [round(float(v), 4) for v in h], "low": [round(float(v), 4) for v in l],
                       "close": [round(float(v), 4) for v in c]}],
            "adjclose": [{"adjclose": [round(float(v), 4) for v in c]}]}}]}}
        (OUT / f"px_{t}.json").write_text(json.dumps(j))
        (OUT / f"facts_{t}.json").write_text(json.dumps(facts(k)))
    uni = {t: {"name": f"Fake {t} Inc", "sector": "Financials" if t == "EEE" else "Industrials", "idx": ["S&P500"]} for t in TICKERS}
    (OUT / "universe.json").write_text(json.dumps(uni))
    print("fixtures ->", OUT)


if __name__ == "__main__":
    main()
