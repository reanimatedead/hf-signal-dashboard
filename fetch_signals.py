#!/usr/bin/env python3
"""
HF Signal Scanner Pro - Daily Signal Generator
Runs at 08:00 JST via GitHub Actions
Fetches OHLCV data, calculates indicators, and outputs data.json for the dashboard.
"""

import json
import sys
import time
import warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent / "docs"
OUTPUT_FILE = OUTPUT_DIR / "data.json"
DATA_PERIOD = "6mo"   # 6 months for stable indicator calc
BATCH_SIZE = 50       # Symbols per yfinance batch request
JST = timezone(timedelta(hours=9))

# ─────────────────────────────────────────────────────────
# SYMBOL DEFINITIONS
# ─────────────────────────────────────────────────────────

# ── Nikkei 225 (主要構成銘柄) ──────────────────────────────
NIKKEI225 = {
    # Technology & Semiconductors
    "9984.T": "SoftBank Group", "8035.T": "Tokyo Electron", "6857.T": "Advantest",
    "6920.T": "Lasertec", "6954.T": "Fanuc", "6861.T": "Keyence",
    "6981.T": "Murata Manufacturing", "6762.T": "TDK", "6976.T": "Taiyo Yuden",
    "6971.T": "Kyocera", "6963.T": "Rohm", "6806.T": "Hirose Electric",
    "6724.T": "Seiko Epson", "6479.T": "Minebea Mitsumi", "6645.T": "Omron",
    "6869.T": "Sysmex", "6841.T": "Yokogawa Electric", "4704.T": "Trend Micro",
    "9613.T": "NTT Data Group",
    # IT & Communications Hardware
    "6702.T": "Fujitsu", "6701.T": "NEC", "6752.T": "Panasonic Holdings",
    "6501.T": "Hitachi", "7751.T": "Canon", "7741.T": "HOYA",
    "7733.T": "Olympus", "4901.T": "Fujifilm Holdings", "4902.T": "Konica Minolta",
    # Automotive
    "7203.T": "Toyota Motor", "7267.T": "Honda Motor", "7270.T": "Subaru",
    "7201.T": "Nissan Motor", "7261.T": "Mazda Motor", "7269.T": "Suzuki Motor",
    "7272.T": "Yamaha Motor", "6902.T": "DENSO", "5108.T": "Bridgestone",
    "7011.T": "Mitsubishi Heavy Ind.", "7013.T": "IHI", "7012.T": "Kawasaki Heavy Ind.",
    # Consumer & Entertainment
    "9983.T": "Fast Retailing", "7974.T": "Nintendo", "7832.T": "Bandai Namco",
    "9766.T": "Konami Group", "4661.T": "Oriental Land", "3382.T": "Seven & i Holdings",
    "8267.T": "Aeon", "7532.T": "Pan Pacific Intl",
    # Pharmaceuticals
    "4519.T": "Chugai Pharmaceutical", "4568.T": "Daiichi Sankyo",
    "4502.T": "Takeda Pharmaceutical", "4503.T": "Astellas Pharma",
    "4507.T": "Shionogi", "4523.T": "Eisai", "4578.T": "Otsuka Holdings",
    "4543.T": "Terumo", "4151.T": "Kyowa Kirin",
    # Chemicals & Materials
    "4063.T": "Shin-Etsu Chemical", "4188.T": "Mitsubishi Chemical",
    "4005.T": "Sumitomo Chemical", "4183.T": "Mitsui Chemicals",
    "3407.T": "Asahi Kasei", "3402.T": "Toray Industries",
    "3401.T": "Teijin", "4452.T": "Kao", "2802.T": "Ajinomoto",
    "4042.T": "Tosoh", "4021.T": "Nissan Chemical",
    # Steel & Mining
    "5401.T": "Nippon Steel", "5411.T": "JFE Holdings",
    "5713.T": "Sumitomo Metal Mining", "5802.T": "Sumitomo Electric",
    "5801.T": "Furukawa Electric", "5803.T": "Fujikura",
    # Financials
    "8306.T": "Mitsubishi UFJ FG", "8316.T": "Sumitomo Mitsui FG",
    "8411.T": "Mizuho Financial", "8309.T": "SMTH Holdings",
    "8604.T": "Nomura Holdings", "8601.T": "Daiwa Securities",
    "8697.T": "Japan Exchange Group", "8766.T": "Tokio Marine",
    "8725.T": "MS&AD Insurance", "8750.T": "Dai-ichi Life",
    "8795.T": "T&D Holdings",
    # Telecom
    "9432.T": "NTT", "9433.T": "KDDI", "9434.T": "SoftBank Corp",
    # Trading Companies
    "8058.T": "Mitsubishi Corp", "8031.T": "Mitsui & Co",
    "8053.T": "Sumitomo Corp", "8001.T": "Itochu", "8002.T": "Marubeni",
    "8015.T": "Toyota Tsusho", "2768.T": "Sojitz",
    # Real Estate
    "8802.T": "Mitsubishi Estate", "8830.T": "Sumitomo Realty",
    "1928.T": "Sekisui House", "1925.T": "Daiwa House",
    # Energy
    "1605.T": "INPEX", "5020.T": "ENEOS Holdings",
    "5019.T": "Idemitsu Kosan", "9531.T": "Tokyo Gas", "9532.T": "Osaka Gas",
    # Utilities
    "9501.T": "Tokyo Electric Power", "9502.T": "Chubu Electric",
    "9503.T": "Kansai Electric",
    # Transportation
    "9022.T": "JR Central", "9020.T": "JR East", "9021.T": "JR West",
    "9201.T": "Japan Airlines", "9202.T": "ANA Holdings",
    "9064.T": "Yamato Holdings", "9147.T": "Nippon Express",
    "9101.T": "Nippon Yusen", "9104.T": "Mitsui OSK Lines",
    "9107.T": "Kawasaki Kisen",
    # Construction
    "1812.T": "Kajima", "1803.T": "Shimizu", "1963.T": "JGC Holdings",
    # Foods & Beverages
    "2914.T": "Japan Tobacco", "2502.T": "Asahi Group",
    "2503.T": "Kirin Holdings", "2801.T": "Kikkoman",
    "2269.T": "Meiji Holdings", "2002.T": "Nisshin Seifun",
    "2501.T": "Sapporo Holdings",
    # Services
    "9735.T": "Secom", "4324.T": "Dentsu Group",
    "6301.T": "Komatsu", "6326.T": "Kubota",
    "6506.T": "Yaskawa Electric", "6367.T": "Daikin Industries",
    "7911.T": "Toppan Holdings", "7912.T": "Dai Nippon Printing",
    "8233.T": "Takashimaya", "1332.T": "Nissui",
    "5201.T": "AGC", "5332.T": "TOTO",
    "6103.T": "Okuma", "6113.T": "Amada",
    "6471.T": "NSK", "6473.T": "JTEKT",
}

# ── Dow Jones 30 ──────────────────────────────────────────
DOW30 = {
    "AAPL": "Apple", "AMGN": "Amgen", "AXP": "American Express",
    "BA": "Boeing", "CAT": "Caterpillar", "CRM": "Salesforce",
    "CSCO": "Cisco", "CVX": "Chevron", "DIS": "Disney",
    "GS": "Goldman Sachs", "HD": "Home Depot", "HON": "Honeywell",
    "IBM": "IBM", "JNJ": "Johnson & Johnson", "JPM": "JPMorgan Chase",
    "KO": "Coca-Cola", "MCD": "McDonald's", "MMM": "3M",
    "MRK": "Merck", "MSFT": "Microsoft", "NKE": "Nike",
    "PG": "Procter & Gamble", "TRV": "Travelers", "UNH": "UnitedHealth",
    "V": "Visa", "VZ": "Verizon", "WMT": "Walmart",
    "AMZN": "Amazon", "NVDA": "NVIDIA", "SHW": "Sherwin-Williams",
}

# ── Nasdaq 100 ────────────────────────────────────────────
NASDAQ100 = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA",
    "AMZN": "Amazon", "META": "Meta Platforms", "GOOGL": "Alphabet (A)",
    "GOOG": "Alphabet (C)", "TSLA": "Tesla", "AVGO": "Broadcom",
    "COST": "Costco", "NFLX": "Netflix", "AMD": "AMD",
    "ADBE": "Adobe", "QCOM": "Qualcomm", "INTC": "Intel",
    "INTU": "Intuit", "CSCO": "Cisco", "AMAT": "Applied Materials",
    "TXN": "Texas Instruments", "MU": "Micron Technology",
    "ISRG": "Intuitive Surgical", "LRCX": "Lam Research",
    "KLAC": "KLA Corp", "PANW": "Palo Alto Networks",
    "SNPS": "Synopsys", "CDNS": "Cadence Design",
    "MRVL": "Marvell Technology", "ADP": "ADP",
    "FTNT": "Fortinet", "MELI": "MercadoLibre",
    "REGN": "Regeneron", "MDLZ": "Mondelez",
    "GILD": "Gilead Sciences", "PYPL": "PayPal",
    "SBUX": "Starbucks", "BKNG": "Booking Holdings",
    "ORLY": "O'Reilly Automotive", "MNST": "Monster Beverage",
    "PAYX": "Paychex", "IDXX": "IDEXX Laboratories",
    "CTAS": "Cintas", "ROST": "Ross Stores",
    "DXCM": "Dexcom", "CHTR": "Charter Communications",
    "ILMN": "Illumina", "NXPI": "NXP Semiconductors",
    "CRWD": "CrowdStrike", "PCAR": "PACCAR",
    "BIIB": "Biogen", "ZS": "Zscaler",
    "ODFL": "Old Dominion Freight", "FAST": "Fastenal",
    "TTD": "The Trade Desk", "ON": "ON Semiconductor",
    "GEHC": "GE HealthCare", "CEG": "Constellation Energy",
    "KHC": "Kraft Heinz", "FANG": "Diamondback Energy",
    "VRSK": "Verisk Analytics", "MCHP": "Microchip Technology",
    "CPRT": "Copart", "XEL": "Xcel Energy",
    "ALGN": "Align Technology", "DDOG": "Datadog",
    "ANSS": "ANSYS", "WDAY": "Workday",
    "TMUS": "T-Mobile", "MRNA": "Moderna",
    "VRTX": "Vertex Pharmaceuticals", "ASML": "ASML",
    "LULU": "Lululemon", "FSLR": "First Solar",
    "SNOW": "Snowflake", "NET": "Cloudflare",
    "TEAM": "Atlassian", "DLTR": "Dollar Tree",
    "EBAY": "eBay", "PDD": "PDD Holdings",
    "EA": "Electronic Arts", "TTWO": "Take-Two Interactive",
    "SWKS": "Skyworks", "CTSH": "Cognizant",
    "EXPE": "Expedia", "ATVI": "Activision Blizzard",
    "ENPH": "Enphase Energy", "ZM": "Zoom Video",
    "BMRN": "BioMarin", "AEP": "American Electric Power",
    "CSX": "CSX Corp", "HON": "Honeywell",
    "SIRI": "Sirius XM", "LCID": "Lucid Group",
}

# ── FX Pairs ──────────────────────────────────────────────
FX_PAIRS = {
    # JPY pairs (最重要)
    "USDJPY=X": "USD/JPY", "EURJPY=X": "EUR/JPY", "GBPJPY=X": "GBP/JPY",
    "AUDJPY=X": "AUD/JPY", "NZDJPY=X": "NZD/JPY", "CADJPY=X": "CAD/JPY",
    "CHFJPY=X": "CHF/JPY",
    # Major pairs
    "EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "AUDUSD=X": "AUD/USD",
    "USDCAD=X": "USD/CAD", "USDCHF=X": "USD/CHF", "NZDUSD=X": "NZD/USD",
    # Cross pairs
    "EURGBP=X": "EUR/GBP", "EURAUD=X": "EUR/AUD", "GBPAUD=X": "GBP/AUD",
    # Commodities (via FX-like Yahoo tickers)
    "XAUUSD=X": "Gold (XAU/USD)", "XAGUSD=X": "Silver (XAG/USD)",
}


def get_sp500_tickers():
    """Fetch S&P 500 tickers from Wikipedia."""
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        df = pd.read_html(url, header=0)[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        # Build a name mapping too
        names = dict(zip(
            df["Symbol"].str.replace(".", "-", regex=False),
            df["Security"]
        ))
        print(f"✓ Fetched {len(tickers)} S&P 500 tickers from Wikipedia")
        return tickers, names
    except Exception as e:
        print(f"⚠ S&P 500 fetch failed: {e}. Using fallback list.")
        fallback = [
            "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","BRK-B","UNH","JPM",
            "V","XOM","MA","JNJ","PG","HD","AVGO","LLY","MRK","ABBV","CVX","COST",
            "PEP","KO","BAC","MCD","CSCO","TMO","ADBE","CRM","ACN","ABT","NFLX",
            "WFC","DHR","TXN","LIN","PM","QCOM","AMGN","LOW","CAT","NEE","ORCL",
            "HON","IBM","ELV","INTU","UPS","DE","SPGI","SCHW","RTX","MDT","ISRG",
            "BMY","BLK","GILD","T","CVS","CI","MO","CB","AMD","BA","ZTS","C","AXP",
            "MMC","GE","USB","MS","NOW","REGN","EOG","TJX","VRTX","SLB","ITW","LRCX",
            "CL","SO","PLD","MDLZ","DUK","HUM","GM","F","GS","SBUX","BKNG","MET",
            "OXY","WM","NSC","EMR","PNC","ADI","KLAC","MAR","FIS","AIG","ECL",
        ]
        return fallback, {}


# ─────────────────────────────────────────────────────────
# INDICATOR CALCULATIONS
# ─────────────────────────────────────────────────────────

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_bollinger(series: pd.Series, period=20, std_dev=2.0):
    sma = series.rolling(period).mean()
    std = series.rolling(period).std(ddof=0)
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    pct_b = (series - lower) / (upper - lower + 1e-12)
    return upper, sma, lower, pct_b


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period=14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def compute_signal(rsi, macd_hist, ema20, ema50, ema200, bb_pct, price, is_fx=False):
    """Composite score (0-100) and trade signal label."""
    score = 0

    # ① RSI Component (0–25 pts)
    if rsi <= 25:
        score += 25
    elif rsi <= 35:
        score += 21
    elif rsi <= 45:
        score += 16
    elif rsi <= 55:
        score += 12
    elif rsi <= 65:
        score += 7
    elif rsi <= 75:
        score += 3
    else:
        score += 0

    # ② MACD Histogram Component (0–25 pts)
    if macd_hist > 0:
        score += 20
    else:
        # Softly penalize negative histogram
        score += max(0, int(25 * (1 + macd_hist / (abs(macd_hist) + 1e-6)) * 0.4))

    # ③ EMA Trend Component (0–25 pts)
    if not np.isnan(ema200):
        if price > ema20 and ema20 > ema50 and ema50 > ema200:
            score += 25
        elif price > ema20 and ema20 > ema50:
            score += 20
        elif price > ema50 and price > ema200:
            score += 15
        elif price > ema200:
            score += 8
        else:
            score += 0
    else:
        if price > ema20 and ema20 > ema50:
            score += 20
        elif price > ema50:
            score += 13
        else:
            score += 3

    # ④ Bollinger Band Component (0–25 pts)
    if bb_pct <= 0.05:
        score += 25
    elif bb_pct <= 0.20:
        score += 21
    elif bb_pct <= 0.35:
        score += 16
    elif bb_pct <= 0.55:
        score += 10
    elif bb_pct <= 0.75:
        score += 5
    elif bb_pct <= 0.90:
        score += 2
    else:
        score += 0

    score = min(100, max(0, score))

    if is_fx:
        if score >= 78:   label = "STRONG LONG"
        elif score >= 63: label = "LONG"
        elif score >= 43: label = "NEUTRAL"
        elif score >= 28: label = "SHORT"
        else:             label = "STRONG SHORT"
    else:
        if score >= 78:   label = "STRONG BUY"
        elif score >= 63: label = "BUY"
        elif score >= 43: label = "HOLD"
        elif score >= 28: label = "WATCH"
        else:             label = "AVOID"

    return score, label


# ─────────────────────────────────────────────────────────
# DATA FETCHING & PROCESSING
# ─────────────────────────────────────────────────────────

def fetch_batch(tickers, period=DATA_PERIOD):
    """Download OHLCV for a list of tickers via yfinance batch API."""
    results = {}
    tickers = list(tickers)
    batches = [tickers[i:i + BATCH_SIZE] for i in range(0, len(tickers), BATCH_SIZE)]

    for idx, batch in enumerate(batches):
        print(f"  → Batch {idx+1}/{len(batches)} ({len(batch)} symbols)…", flush=True)
        try:
            if len(batch) == 1:
                raw = yf.download(batch[0], period=period, auto_adjust=True, progress=False)
                if not raw.empty:
                    results[batch[0]] = raw
            else:
                raw = yf.download(
                    batch, period=period, auto_adjust=True,
                    group_by="ticker", threads=True, progress=False,
                )
                for t in batch:
                    try:
                        df = raw[t].dropna(how="all")
                        if len(df) >= 20:
                            results[t] = df
                    except Exception:
                        pass
        except Exception as e:
            print(f"  ⚠ Batch error: {e}", flush=True)
            time.sleep(3)

        time.sleep(0.8)  # Rate-limit courtesy

    return results


def process_ticker(df: pd.DataFrame, symbol: str, name: str, is_fx=False) -> dict:
    """Calculate all indicators for a single ticker DataFrame."""
    try:
        close = df["Close"].squeeze()
        high  = df["High"].squeeze()
        low   = df["Low"].squeeze()
        vol   = df["Volume"].squeeze() if "Volume" in df.columns else pd.Series(dtype=float)

        if len(close) < 20 or close.isna().all():
            raise ValueError("Insufficient data")

        price     = float(close.iloc[-1])
        prev      = float(close.iloc[-2]) if len(close) > 1 else price
        chg_pct   = (price - prev) / abs(prev) * 100

        # Indicators
        rsi_s       = calc_rsi(close)
        rsi         = float(rsi_s.iloc[-1]) if not np.isnan(rsi_s.iloc[-1]) else 50.0
        _, _, hist  = calc_macd(close)
        macd_hist   = float(hist.iloc[-1]) if not np.isnan(hist.iloc[-1]) else 0.0

        ema20  = float(close.ewm(span=20,  adjust=False).mean().iloc[-1])
        ema50  = float(close.ewm(span=50,  adjust=False).mean().iloc[-1])
        ema200_s = close.ewm(span=200, adjust=False).mean()
        ema200 = float(ema200_s.iloc[-1]) if len(close) >= 40 else float("nan")

        _, _, _, bb_pct_s = calc_bollinger(close)
        bb_pct = float(bb_pct_s.iloc[-1]) if not np.isnan(bb_pct_s.iloc[-1]) else 0.5
        bb_pct = max(0.0, min(1.0, bb_pct))

        atr_s = calc_atr(high, low, close)
        atr   = float(atr_s.iloc[-1]) if not np.isnan(atr_s.iloc[-1]) else 0.0

        # EMA trend label
        if price > ema20 and ema20 > ema50:
            ema_label = "BULLISH"
        elif price < ema20 and ema20 < ema50:
            ema_label = "BEARISH"
        else:
            ema_label = "MIXED"

        # MACD direction
        macd_dir = "UP" if macd_hist > 0 else "DOWN"

        # Volume ratio (current vs 20d avg)
        if not vol.empty and len(vol.dropna()) >= 5:
            vol_avg = float(vol.iloc[-21:-1].mean())
            vol_ratio = round(float(vol.iloc[-1]) / vol_avg, 2) if vol_avg > 0 else 1.0
        else:
            vol_ratio = 1.0

        # Composite score & signal
        ema200_val = ema200 if not np.isnan(ema200) else ema50
        score, signal = compute_signal(rsi, macd_hist, ema20, ema50, ema200_val, bb_pct, price, is_fx)

        decimals = 5 if is_fx and price < 10 else (4 if is_fx else 2)
        return {
            "symbol":         symbol,
            "name":           name,
            "price":          round(price, decimals),
            "change_pct":     round(chg_pct, 2),
            "rsi":            round(rsi, 1),
            "macd_hist":      round(macd_hist, 6),
            "macd_direction": macd_dir,
            "ema20":          round(ema20, decimals),
            "ema50":          round(ema50, decimals),
            "ema200":         round(ema200, decimals) if not np.isnan(ema200) else None,
            "ema_signal":     ema_label,
            "bb_pct":         round(bb_pct, 3),
            "atr":            round(atr, decimals),
            "vol_ratio":      vol_ratio,
            "composite_score": score,
            "signal":         signal,
            "error":          None,
        }
    except Exception as exc:
        return {"symbol": symbol, "name": name, "composite_score": -1,
                "signal": "ERROR", "error": str(exc)}


def process_market(symbols_dict: dict, label: str, is_fx=False) -> list:
    """Fetch and process a full market category."""
    print(f"\n[{label}] Fetching {len(symbols_dict)} symbols…")
    raw_data = fetch_batch(list(symbols_dict.keys()))
    results = []
    for sym, df in raw_data.items():
        name = symbols_dict.get(sym, sym)
        row  = process_ticker(df, sym, name, is_fx)
        results.append(row)

    # Sort by composite score descending
    results.sort(key=lambda x: x.get("composite_score", -1), reverse=True)
    ok = sum(1 for r in results if r.get("error") is None)
    print(f"  ✓ {ok}/{len(symbols_dict)} processed successfully")
    return results


def build_summary(rows: list) -> dict:
    """Count signal labels in a market result list."""
    counts = {}
    for r in rows:
        sig = r.get("signal", "ERROR")
        counts[sig] = counts.get(sig, 0) + 1
    return counts


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────

def main():
    start = time.time()
    now_jst = datetime.now(JST)
    print(f"=== HF Signal Scanner Pro ===")
    print(f"Run at: {now_jst.strftime('%Y-%m-%d %H:%M:%S JST')}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Fetch S&P 500 tickers
    sp500_tickers, sp500_names = get_sp500_tickers()
    sp500_dict = {t: sp500_names.get(t, t) for t in sp500_tickers}

    # Process each market
    nk_results  = process_market(NIKKEI225,  "Nikkei225")
    dj_results  = process_market(DOW30,      "Dow30")
    nq_results  = process_market(NASDAQ100,  "Nasdaq100")
    sp_results  = process_market(sp500_dict, "S&P500")
    fx_results  = process_market(FX_PAIRS,   "FX", is_fx=True)

    # Build output JSON
    next_run = (now_jst + timedelta(days=1)).replace(
        hour=8, minute=0, second=0, microsecond=0
    )
    payload = {
        "meta": {
            "updated_at":      now_jst.isoformat(),
            "updated_at_str":  now_jst.strftime("%Y-%m-%d %H:%M JST"),
            "next_update_str": next_run.strftime("%Y-%m-%d %H:%M JST"),
            "elapsed_sec":     round(time.time() - start, 1),
            "counts": {
                "nikkei225": len(nk_results),
                "dow30":     len(dj_results),
                "nasdaq100": len(nq_results),
                "sp500":     len(sp_results),
                "fx":        len(fx_results),
            },
        },
        "summary": {
            "nikkei225": build_summary(nk_results),
            "dow30":     build_summary(dj_results),
            "nasdaq100": build_summary(nq_results),
            "sp500":     build_summary(sp_results),
            "fx":        build_summary(fx_results),
        },
        "markets": {
            "nikkei225": nk_results,
            "dow30":     dj_results,
            "nasdaq100": nq_results,
            "sp500":     sp_results,
            "fx":        fx_results,
        },
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = OUTPUT_FILE.stat().st_size / 1024
    elapsed = time.time() - start
    print(f"\n✅ data.json written → {OUTPUT_FILE}")
    print(f"   Size: {size_kb:.1f} KB | Elapsed: {elapsed:.0f}s")


if __name__ == "__main__":
    main()
