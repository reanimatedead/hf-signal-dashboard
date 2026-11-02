"""FX と仮想通貨の銘柄（Yahoo のシンボル → 表示名）。公開サイト（fetch_signals.py）と Mac mini の CCI 通知の
両方がこれだけを使う（同じ一覧を2か所に書かない）。データは持たない。"""

FX_PAIRS = {
    "USDJPY=X": "USD/JPY", "EURJPY=X": "EUR/JPY", "GBPJPY=X": "GBP/JPY",
    "AUDJPY=X": "AUD/JPY", "NZDJPY=X": "NZD/JPY", "CADJPY=X": "CAD/JPY",
    "CHFJPY=X": "CHF/JPY", "EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD",
    "AUDUSD=X": "AUD/USD", "USDCAD=X": "USD/CAD", "USDCHF=X": "USD/CHF",
    "NZDUSD=X": "NZD/USD", "EURGBP=X": "EUR/GBP", "EURAUD=X": "EUR/AUD",
    "GBPAUD=X": "GBP/AUD", "GC=F": "Gold (XAU/USD)", "SI=F": "Silver (XAG/USD)",
}  # fmt: skip

CRYPTO = [("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum"), ("XRP-USD", "XRP"), ("BCH-USD", "Bitcoin Cash")]
