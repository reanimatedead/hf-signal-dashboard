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

# ── ETF ─────────────────────────────────────────────────────────────────────
# 公開サイトの ETF タブ（Yahoo のシンボル → (表示名, 種類)）。一覧はここ1か所。
# 種類: index / leveraged / inverse / unknown（Mac mini の J-Quants 一覧は etf_kind で名前から判定）。
ETFS: dict[str, tuple[str, str]] = {
    "1306.T": ("NEXT FUNDS TOPIX ETF", "index"),
    "1321.T": ("NEXT FUNDS Nikkei 225 ETF", "index"),
    "1348.T": ("MAXIS TOPIX ETF", "index"),
    "1475.T": ("iShares Core TOPIX ETF", "index"),
    "1343.T": ("NEXT FUNDS TSE REIT Index ETF", "index"),
    "2558.T": ("MAXIS S&P500 (Yen) ETF", "index"),
    "1570.T": ("NEXT FUNDS Nikkei 225 Leveraged ETF", "leveraged"),
    "1458.T": ("Rakuten ETF Nikkei Leveraged", "leveraged"),
    "1360.T": ("Simplex Nikkei 225 Bear -2x ETF", "inverse"),
    "1357.T": ("NEXT FUNDS Nikkei 225 Double Inverse ETF", "inverse"),
    "1459.T": ("Rakuten ETF Nikkei Double Inverse", "inverse"),
}  # fmt: skip

ETF_KINDS = ("index", "leveraged", "inverse", "unknown")
# 名前から種類を決める語（NFKC で正規化してから探す）。inverse を先に見る（「ダブルインバース」は inverse）。
_INVERSE_WORDS = ("インバース", "ベア", "-1倍", "-2倍", "−1倍", "−2倍", "INVERSE", "BEAR")
_LEVERAGED_WORDS = ("レバレッジ", "ブル", "2倍", "DOUBLE BULL", "LEVERAGED", "BULL")
_INDEX_WORDS = (
    "TOPIX",
    "トピックス",
    "日経",
    "225",
    "JPX",
    "S&P",
    "連動型上場投信",
    "インデックス",
    "INDEX",
    "MSCI",
    "FTSE",
    "REIT",
    "リート",
    "ダウ",
    "NASDAQ",
    "ナスダック",
)
_NOT_BULL = ("ブルサ",)  # 「ブルサ・マレーシア」（取引所の名前）はブルではない


def etf_kind(name: str) -> str:
    """ETF の名前 → index / leveraged / inverse / unknown（規則はここ1か所）。
    「レバレッジ」「ブル」「2倍」→ leveraged、「ベア」「インバース」「-1倍」→ inverse。どれでも無ければ
    指数の名前（TOPIX・日経・S&P など）を含むものは index、それも無ければ unknown。"""
    import unicodedata

    s = unicodedata.normalize("NFKC", name or "").upper()
    for w in _NOT_BULL:
        s = s.replace(w, "")
    if any(w.upper() in s for w in _INVERSE_WORDS):
        return "inverse"
    if any(w.upper() in s for w in _LEVERAGED_WORDS):
        return "leveraged"
    if any(w.upper() in s for w in _INDEX_WORDS):
        return "index"
    return "unknown"
