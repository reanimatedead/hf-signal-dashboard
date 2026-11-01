"""構成銘柄の取得結果の「形」を固定したテスト用ファイルを作る（決まった内容で毎回同じ）。
- nasdaq100_api.json: Nasdaq 公式 API（list-type/nasdaq100）の応答の形。data.data.rows[].symbol / companyName。
- dia_holdings.xlsx : SPDR DIA の保有銘柄 xlsx の形。先頭 4 行は説明、5 行目が見出し（Name / Ticker / ...）、
                      末尾に現金の行と注記。
銘柄は fetch_signals.py の内蔵一覧（101 / 30）を使う。価格・ウェイトは架空（形だけを固定する）。
実行: python3 tests/fixtures/universe/make_universe_fixtures.py
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))


def main():
    import fetch_signals as fs
    from openpyxl import Workbook

    rows = [{"symbol": t, "companyName": n, "marketCap": "1,000,000,000", "lastSalePrice": "$100.00",
             "netChange": "0.00", "percentageChange": "0.00%", "deltaIndicator": ""}
            for t, n in sorted(fs.NASDAQ100.items())]
    api = {"data": {"date": "Nov 2, 2026", "data": {
        "headers": {"symbol": "Symbol", "companyName": "Name", "marketCap": "Market Cap",
                    "lastSalePrice": "Last Sale", "netChange": "Net Change", "percentageChange": "% Change"},
        "rows": rows}}, "message": None, "status": {"rCode": 200, "bCodeMessage": None, "developerMessage": None}}
    (HERE / "nasdaq100_api.json").write_text(json.dumps(api, ensure_ascii=False, indent=1), encoding="utf-8")

    wb = Workbook()
    ws = wb.active
    ws.append(["Fund Name:", "SPDR Dow Jones Industrial Average ETF Trust"])
    ws.append(["Ticker Symbol:", "DIA"])
    ws.append(["Holdings:", "As of 31-Oct-2026"])
    ws.append([])
    ws.append(["Name", "Ticker", "Identifier", "SEDOL", "Weight", "Sector", "Shares Held", "Local Currency"])
    for i, (t, n) in enumerate(sorted(fs.DOW30.items())):
        ws.append([n.upper(), t, f"ID{i:04d}", f"S{i:06d}", round(3.3 + i * 0.01, 2), "Fake Sector", 1000 + i, "USD"])
    ws.append(["US DOLLAR", "CASH_USD", "", "", 0.05, "", 12345, "USD"])
    ws.append([])
    ws.append(["Past performance is not a reliable indicator of future performance."])
    wb.save(HERE / "dia_holdings.xlsx")
    print("fixtures ->", HERE)


if __name__ == "__main__":
    main()
