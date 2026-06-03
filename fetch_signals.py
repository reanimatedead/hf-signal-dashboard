#!/usr/bin/env python3
"""
HF Signal Scanner Pro v2 - Daily Signal Generator
- Stocks : EMA + RSI + MACD + BB composite scoring (unchanged)
- FX     : CCI(288) + BB(288, 2σ/3σ) on Daily + 4H, Monte Carlo ≥55% filter
"""

import json, sys, time, warnings, csv
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ─── CONFIG ──────────────────────────────────────────────
OUTPUT_DIR  = Path(__file__).parent / "docs"
OUTPUT_FILE = OUTPUT_DIR / "data.json"
DATA_PERIOD = "6mo"
BATCH_SIZE  = 50
JST         = timezone(timedelta(hours=9))
CCI_PERIOD  = 288
BB_PERIOD   = 288

# ─── SYMBOLS ─────────────────────────────────────────────

NIKKEI225 = {
    "9984.T":"SoftBank Group","8035.T":"Tokyo Electron","6857.T":"Advantest",
    "6920.T":"Lasertec","6954.T":"Fanuc","6861.T":"Keyence",
    "6981.T":"Murata Manufacturing","6762.T":"TDK","6976.T":"Taiyo Yuden",
    "6971.T":"Kyocera","6963.T":"Rohm","6806.T":"Hirose Electric",
    "6724.T":"Seiko Epson","6479.T":"Minebea Mitsumi","6645.T":"Omron",
    "6869.T":"Sysmex","6841.T":"Yokogawa Electric","4704.T":"Trend Micro",
    "9613.T":"NTT Data Group","6702.T":"Fujitsu","6701.T":"NEC",
    "6752.T":"Panasonic Holdings","6501.T":"Hitachi","7751.T":"Canon",
    "7741.T":"HOYA","7733.T":"Olympus","4901.T":"Fujifilm Holdings",
    "4902.T":"Konica Minolta","7203.T":"Toyota Motor","7267.T":"Honda Motor",
    "7270.T":"Subaru","7201.T":"Nissan Motor","7261.T":"Mazda Motor",
    "7269.T":"Suzuki Motor","7272.T":"Yamaha Motor","6902.T":"DENSO",
    "5108.T":"Bridgestone","7011.T":"Mitsubishi Heavy Ind.","7013.T":"IHI",
    "7012.T":"Kawasaki Heavy Ind.","9983.T":"Fast Retailing","7974.T":"Nintendo",
    "7832.T":"Bandai Namco","9766.T":"Konami Group","4661.T":"Oriental Land",
    "3382.T":"Seven & i Holdings","8267.T":"Aeon","7532.T":"Pan Pacific Intl",
    "4519.T":"Chugai Pharmaceutical","4568.T":"Daiichi Sankyo",
    "4502.T":"Takeda Pharmaceutical","4503.T":"Astellas Pharma",
    "4507.T":"Shionogi","4523.T":"Eisai","4578.T":"Otsuka Holdings",
    "4543.T":"Terumo","4151.T":"Kyowa Kirin","4063.T":"Shin-Etsu Chemical",
    "4188.T":"Mitsubishi Chemical","4005.T":"Sumitomo Chemical",
    "4183.T":"Mitsui Chemicals","3407.T":"Asahi Kasei","3402.T":"Toray Industries",
    "3401.T":"Teijin","4452.T":"Kao","2802.T":"Ajinomoto",
    "4042.T":"Tosoh","4021.T":"Nissan Chemical","5401.T":"Nippon Steel",
    "5411.T":"JFE Holdings","5713.T":"Sumitomo Metal Mining",
    "5802.T":"Sumitomo Electric","5801.T":"Furukawa Electric","5803.T":"Fujikura",
    "8306.T":"Mitsubishi UFJ FG","8316.T":"Sumitomo Mitsui FG",
    "8411.T":"Mizuho Financial","8309.T":"SMTH Holdings",
    "8604.T":"Nomura Holdings","8601.T":"Daiwa Securities",
    "8697.T":"Japan Exchange Group","8766.T":"Tokio Marine",
    "8725.T":"MS&AD Insurance","8750.T":"Dai-ichi Life","8795.T":"T&D Holdings",
    "9432.T":"NTT","9433.T":"KDDI","9434.T":"SoftBank Corp",
    "8058.T":"Mitsubishi Corp","8031.T":"Mitsui & Co",
    "8053.T":"Sumitomo Corp","8001.T":"Itochu","8002.T":"Marubeni",
    "8015.T":"Toyota Tsusho","2768.T":"Sojitz",
    "8802.T":"Mitsubishi Estate","8830.T":"Sumitomo Realty",
    "1928.T":"Sekisui House","1925.T":"Daiwa House",
    "1605.T":"INPEX","5020.T":"ENEOS Holdings",
    "5019.T":"Idemitsu Kosan","9531.T":"Tokyo Gas","9532.T":"Osaka Gas",
    "9501.T":"Tokyo Electric Power","9502.T":"Chubu Electric",
    "9503.T":"Kansai Electric","9022.T":"JR Central","9020.T":"JR East",
    "9021.T":"JR West","9201.T":"Japan Airlines","9202.T":"ANA Holdings",
    "9064.T":"Yamato Holdings","9147.T":"Nippon Express",
    "9101.T":"Nippon Yusen","9104.T":"Mitsui OSK Lines","9107.T":"Kawasaki Kisen",
    "1812.T":"Kajima","1803.T":"Shimizu","1963.T":"JGC Holdings",
    "2914.T":"Japan Tobacco","2502.T":"Asahi Group","2503.T":"Kirin Holdings",
    "2801.T":"Kikkoman","2269.T":"Meiji Holdings","2002.T":"Nisshin Seifun",
    "2501.T":"Sapporo Holdings","9735.T":"Secom","4324.T":"Dentsu Group",
    "6301.T":"Komatsu","6326.T":"Kubota","6506.T":"Yaskawa Electric",
    "6367.T":"Daikin Industries","7911.T":"Toppan Holdings",
    "7912.T":"Dai Nippon Printing","8233.T":"Takashimaya","1332.T":"Nissui",
    "5201.T":"AGC","5332.T":"TOTO","6103.T":"Okuma","6113.T":"Amada",
    "6471.T":"NSK","6473.T":"JTEKT",
}

DOW30 = {
    "AAPL":"Apple","AMGN":"Amgen","AXP":"American Express","BA":"Boeing",
    "CAT":"Caterpillar","CRM":"Salesforce","CSCO":"Cisco","CVX":"Chevron",
    "DIS":"Disney","GS":"Goldman Sachs","HD":"Home Depot","HON":"Honeywell",
    "IBM":"IBM","JNJ":"Johnson & Johnson","JPM":"JPMorgan Chase","KO":"Coca-Cola",
    "MCD":"McDonald's","MMM":"3M","MRK":"Merck","MSFT":"Microsoft","NKE":"Nike",
    "PG":"Procter & Gamble","TRV":"Travelers","UNH":"UnitedHealth","V":"Visa",
    "VZ":"Verizon","WMT":"Walmart","AMZN":"Amazon","NVDA":"NVIDIA","SHW":"Sherwin-Williams",
}

NASDAQ100 = {
    "AAPL":"Apple","MSFT":"Microsoft","NVDA":"NVIDIA","AMZN":"Amazon",
    "META":"Meta Platforms","GOOGL":"Alphabet (A)","GOOG":"Alphabet (C)",
    "TSLA":"Tesla","AVGO":"Broadcom","COST":"Costco","NFLX":"Netflix",
    "AMD":"AMD","ADBE":"Adobe","QCOM":"Qualcomm","INTC":"Intel","INTU":"Intuit",
    "CSCO":"Cisco","AMAT":"Applied Materials","TXN":"Texas Instruments",
    "MU":"Micron Technology","ISRG":"Intuitive Surgical","LRCX":"Lam Research",
    "KLAC":"KLA Corp","PANW":"Palo Alto Networks","SNPS":"Synopsys",
    "CDNS":"Cadence Design","MRVL":"Marvell Technology","ADP":"ADP",
    "FTNT":"Fortinet","MELI":"MercadoLibre","REGN":"Regeneron","MDLZ":"Mondelez",
    "GILD":"Gilead Sciences","PYPL":"PayPal","SBUX":"Starbucks",
    "BKNG":"Booking Holdings","ORLY":"O'Reilly Automotive","MNST":"Monster Beverage",
    "PAYX":"Paychex","IDXX":"IDEXX Laboratories","CTAS":"Cintas","ROST":"Ross Stores",
    "DXCM":"Dexcom","CHTR":"Charter Communications","ILMN":"Illumina",
    "NXPI":"NXP Semiconductors","CRWD":"CrowdStrike","PCAR":"PACCAR",
    "BIIB":"Biogen","ZS":"Zscaler","ODFL":"Old Dominion Freight","FAST":"Fastenal",
    "TTD":"The Trade Desk","ON":"ON Semiconductor","GEHC":"GE HealthCare",
    "CEG":"Constellation Energy","KHC":"Kraft Heinz","FANG":"Diamondback Energy",
    "VRSK":"Verisk Analytics","MCHP":"Microchip Technology","CPRT":"Copart",
    "XEL":"Xcel Energy","ALGN":"Align Technology","DDOG":"Datadog",
    "ANSS":"ANSYS","WDAY":"Workday","TMUS":"T-Mobile","MRNA":"Moderna",
    "VRTX":"Vertex Pharmaceuticals","ASML":"ASML","LULU":"Lululemon",
    "FSLR":"First Solar","SNOW":"Snowflake","NET":"Cloudflare","TEAM":"Atlassian",
    "DLTR":"Dollar Tree","EBAY":"eBay","PDD":"PDD Holdings",
    "EA":"Electronic Arts","TTWO":"Take-Two Interactive","SWKS":"Skyworks",
    "CTSH":"Cognizant","EXPE":"Expedia","ENPH":"Enphase Energy","ZM":"Zoom Video",
    "BMRN":"BioMarin","AEP":"American Electric Power","CSX":"CSX Corp",
    "HON":"Honeywell","SIRI":"Sirius XM","LCID":"Lucid Group",
}

FX_PAIRS = {
    "USDJPY=X":"USD/JPY","EURJPY=X":"EUR/JPY","GBPJPY=X":"GBP/JPY",
    "AUDJPY=X":"AUD/JPY","NZDJPY=X":"NZD/JPY","CADJPY=X":"CAD/JPY",
    "CHFJPY=X":"CHF/JPY","EURUSD=X":"EUR/USD","GBPUSD=X":"GBP/USD",
    "AUDUSD=X":"AUD/USD","USDCAD=X":"USD/CAD","USDCHF=X":"USD/CHF",
    "NZDUSD=X":"NZD/USD","EURGBP=X":"EUR/GBP","EURAUD=X":"EUR/AUD",
    "GBPAUD=X":"GBP/AUD","GC=F":"Gold (XAU/USD)","SI=F":"Silver (XAG/USD)",
}


def get_sp500_tickers():
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        df = pd.read_html(url, header=0)[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        names   = dict(zip(df["Symbol"].str.replace(".", "-", regex=False), df["Security"]))
        print(f"✓ {len(tickers)} S&P 500 tickers fetched")
        return tickers, names
    except Exception as e:
        print(f"⚠ S&P 500 fallback: {e}")
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

# ─── INDICATOR LIBRARY ────────────────────────────────────

def calc_rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    ag    = gain.ewm(alpha=1/period, adjust=False).mean()
    al    = loss.ewm(alpha=1/period, adjust=False).mean()
    rs    = ag / al.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calc_macd(series, fast=12, slow=26, signal=9):
    ef  = series.ewm(span=fast,   adjust=False).mean()
    es  = series.ewm(span=slow,   adjust=False).mean()
    ml  = ef - es
    sl  = ml.ewm(span=signal, adjust=False).mean()
    return ml, sl, ml - sl

def calc_bollinger(series, period=20, std_dev=2.0):
    sma   = series.rolling(period).mean()
    std   = series.rolling(period).std(ddof=0)
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    pct_b = (series - lower) / (upper - lower + 1e-12)
    return upper, sma, lower, pct_b

def calc_atr(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def calc_cci(high, low, close, period):
    """Commodity Channel Index."""
    tp  = (high + low + close) / 3
    sma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True
    )
    return (tp - sma) / (0.015 * mad.replace(0, np.nan))

# ─── CHART DETAIL (v2.3) ─────────────────────────────────
# Symbols (yfinance fetch keys) that carry a computed charts.1d block in
# data.json. All FX / Commodities pairs are charted (BB288/CCI are already
# computed for every FX row), so the FX tab renders charts consistently.
# Equity rows are not charted (payload) and fall back gracefully.
CHART_SYMBOLS = set(FX_PAIRS.keys())
OHLC_MAX_BARS = 120

# Precious metals are fetched via reliable COMEX futures tickers (GC=F/SI=F)
# because the spot pairs XAUUSD=X / XAGUSD=X return no data on yfinance.
# A stable display symbol is presented for UI / data-contract continuity.
SYMBOL_DISPLAY = {"GC=F": "XAUUSD", "SI=F": "XAGUSD"}


def _bb_block(close, period, dev, dp):
    """One Bollinger Band (period, deviation). Volatility context, not a signal."""
    if len(close) < period:
        return {"basis": None, "upper": None, "lower": None, "width": None,
                "state": "insufficient_data",
                "comment": f"{period}-period Bollinger Band with {dev} standard deviations. Not enough OHLC data for this period."}
    sma = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    basis = float(sma.iloc[-1]); sd = float(std.iloc[-1])
    upper = basis + dev * sd; lower = basis - dev * sd
    last = float(close.iloc[-1])
    state = (f"upper_{dev}sigma_touch" if last >= upper
             else f"lower_{dev}sigma_touch" if last <= lower else "neutral")
    cycle = "Shorter" if period == 48 else "Longer"
    extreme = " Extreme" if dev == 3 else ""
    return {"basis": round(basis, dp), "upper": round(upper, dp), "lower": round(lower, dp),
            "width": round(upper - lower, dp), "state": state,
            "comment": f"{period}-period Bollinger Band with {dev} standard deviations.{extreme} {cycle}-cycle volatility context."}


def _cci_block(high, low, close, period):
    """One CCI (period). Momentum context, not a signal."""
    if len(close) < period:
        return {"value": None, "state": "insufficient_data",
                "comment": f"{period}-period CCI. Not enough OHLC data for this period."}
    s = calc_cci(high, low, close, period)
    v = float(s.iloc[-1]) if not np.isnan(s.iloc[-1]) else 0.0
    state = "overbought_context" if v >= 200 else "oversold_context" if v <= -200 else "neutral"
    cycle = "Shorter" if period == 48 else "Longer"
    return {"value": round(v, 1), "state": state, "comment": f"{cycle} cycle momentum context."}


def _elliott_1d_placeholder():
    return {"candidate": "unknown", "confidence": "low", "degree": "unknown", "phase": "unknown",
            "invalidation_level": None, "note": "Heuristic placeholder only. Not a trading signal."}


def build_empty_chart(tf_label):
    """Placeholder chart block for a not-yet-available timeframe (4h / 1w)."""
    return {"available": False, "source": None, "updated_at": None, "ohlc": [], "indicators": None,
            "elliott": {"candidate": "unknown", "confidence": "low",
                        "note": f"{tf_label} chart data is not available yet."},
            "note": f"{tf_label} chart data is planned for a later phase."}


def build_1d_chart_from_ohlc(df_d, dp, updated_at):
    """Build a computed charts['1d'] block from a daily OHLC frame.

    Bollinger Bands 48/288 (2σ/3σ) and CCI 48/288 are volatility/momentum
    context only, not trading signals. Falls back to available:false on error.
    """
    try:
        close = df_d["Close"].squeeze()
        high = df_d["High"].squeeze()
        low = df_d["Low"].squeeze()
        if len(close) < 48:
            return build_empty_chart("1d")
        ohlc = []
        for ts, r in df_d.tail(OHLC_MAX_BARS).iterrows():
            try:
                t = ts.strftime("%Y-%m-%dT00:00:00+09:00") if hasattr(ts, "strftime") else str(ts)
                ohlc.append({"time": t, "open": round(float(r["Open"]), dp), "high": round(float(r["High"]), dp),
                             "low": round(float(r["Low"]), dp), "close": round(float(r["Close"]), dp), "volume": None})
            except Exception:
                continue
        indicators = {
            "bollinger_bands": {
                "48": {"std_2": _bb_block(close, 48, 2, dp), "std_3": _bb_block(close, 48, 3, dp)},
                "288": {"std_2": _bb_block(close, 288, 2, dp), "std_3": _bb_block(close, 288, 3, dp)},
            },
            "cci": {"48": _cci_block(high, low, close, 48), "288": _cci_block(high, low, close, 288)},
        }
        return {"available": True, "source": "fx-analysis-system/yfinance", "updated_at": updated_at,
                "ohlc": ohlc, "indicators": indicators, "elliott": _elliott_1d_placeholder(),
                "note": "Indicators are market context only."}
    except Exception:
        return build_empty_chart("1d")


def attach_charts_to_symbol(row, df_d, dp, updated_at):
    """Attach 4h/1d/1w charts to a symbol row. 1d computed; 4h/1w placeholder."""
    row["charts"] = {
        "4h": build_empty_chart("4h"),
        "1d": build_1d_chart_from_ohlc(df_d, dp, updated_at),
        "1w": build_empty_chart("1w"),
    }
    return row


def build_empty_edge_context():
    """Placeholder analytical edge-context (v2.4). No scoring here.

    Edge = analytical/contextual edge that organises technical / macro /
    cross-asset / risk context for review — never a trading advantage or signal.
    """
    return {
        "overall": "unknown",
        "confidence": "low",
        "technical": {"state": "unknown", "factors": []},
        "macro": {"state": "unknown", "factors": []},
        "cross_asset": {"state": "unknown", "factors": []},
        "risk_adjusted": {"state": "unknown", "factors": []},
        "supporting_factors": [],
        "conflicting_factors": [],
        "note": "Edge context is an analytical summary for market review only. It is not investment advice, a trading signal, or an instruction to enter or exit positions.",
    }


def monte_carlo_prob(returns, n_sims=800, n_forward=5, direction="long"):
    """Vectorised bootstrap Monte Carlo – returns P(direction correct)."""
    clean = returns.dropna().values
    if len(clean) < 30:
        return 0.5
    idx   = np.random.randint(0, len(clean), size=(n_sims, n_forward))
    paths = clean[idx]
    cum   = np.prod(1 + paths, axis=1) - 1
    if direction == "long":
        return float(np.mean(cum > 0))
    return float(np.mean(cum < 0))

# ─── STOCK COMPOSITE SIGNAL ──────────────────────────────

def compute_signal(rsi, macd_hist, ema20, ema50, ema200, bb_pct, price):
    score = 0
    if   rsi <= 25: score += 25
    elif rsi <= 35: score += 21
    elif rsi <= 45: score += 16
    elif rsi <= 55: score += 12
    elif rsi <= 65: score += 7
    elif rsi <= 75: score += 3

    if macd_hist > 0:
        score += 20
    else:
        score += max(0, int(25 * (1 + macd_hist / (abs(macd_hist) + 1e-6)) * 0.4))

    if not np.isnan(ema200):
        if   price > ema20 > ema50 > ema200: score += 25
        elif price > ema20 > ema50:          score += 20
        elif price > ema50 and price > ema200: score += 15
        elif price > ema200:                 score += 8
    else:
        if   price > ema20 > ema50: score += 20
        elif price > ema50:         score += 13
        else:                       score += 3

    if   bb_pct <= 0.05: score += 25
    elif bb_pct <= 0.20: score += 21
    elif bb_pct <= 0.35: score += 16
    elif bb_pct <= 0.55: score += 10
    elif bb_pct <= 0.75: score += 5
    elif bb_pct <= 0.90: score += 2

    score = min(100, max(0, score))
    if   score >= 78: label = "STRONG BUY"
    elif score >= 63: label = "BUY"
    elif score >= 43: label = "HOLD"
    elif score >= 28: label = "WATCH"
    else:             label = "AVOID"
    return score, label

# ─── DATA FETCHING ────────────────────────────────────────

def fetch_batch(tickers, period=DATA_PERIOD):
    results = {}
    tickers = list(tickers)
    batches = [tickers[i:i+BATCH_SIZE] for i in range(0, len(tickers), BATCH_SIZE)]
    for idx, batch in enumerate(batches):
        print(f"  → Batch {idx+1}/{len(batches)} ({len(batch)})…", flush=True)
        try:
            if len(batch) == 1:
                raw = yf.download(batch[0], period=period, auto_adjust=True, progress=False)
                # Current yfinance returns MultiIndex columns even for a single
                # ticker; flatten to level-0 (Open/High/Low/Close/Volume) so
                # per-row access (iterrows) yields scalars like the multi path.
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.get_level_values(0)
                if not raw.empty:
                    results[batch[0]] = raw
            else:
                raw = yf.download(batch, period=period, auto_adjust=True,
                                  group_by="ticker", threads=True, progress=False)
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
        time.sleep(0.8)
    return results

def fetch_fx_4h(symbols):
    """Fetch 1H data → resample to 4H for FX pairs (24h market)."""
    results = {}
    print(f"  → Fetching 4H data for {len(symbols)} FX pairs…")
    for sym in symbols:
        try:
            df = yf.download(sym, period="60d", interval="1h",
                             auto_adjust=True, progress=False)
            if df.empty or len(df) < 60:
                continue
            df.index = pd.to_datetime(df.index)
            df_4h = df.resample("4h").agg({
                "Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"
            }).dropna(subset=["Close"])
            if len(df_4h) >= 40:
                results[sym] = df_4h
                print(f"    {sym}: {len(df_4h)} 4H bars")
        except Exception as e:
            print(f"    ⚠ {sym} 4H failed: {e}")
        time.sleep(0.5)
    return results

# ─── STOCK PROCESSING ────────────────────────────────────

def process_ticker(df, symbol, name):
    try:
        close = df["Close"].squeeze()
        high  = df["High"].squeeze()
        low   = df["Low"].squeeze()
        vol   = df["Volume"].squeeze() if "Volume" in df.columns else pd.Series(dtype=float)

        if len(close) < 20 or close.isna().all():
            raise ValueError("Insufficient data")

        price   = float(close.iloc[-1])
        prev    = float(close.iloc[-2]) if len(close) > 1 else price
        chg_pct = (price - prev) / abs(prev) * 100

        rsi_s      = calc_rsi(close)
        rsi        = float(rsi_s.iloc[-1]) if not np.isnan(rsi_s.iloc[-1]) else 50.0
        _, _, hist = calc_macd(close)
        macd_hist  = float(hist.iloc[-1]) if not np.isnan(hist.iloc[-1]) else 0.0
        macd_dir   = "UP" if macd_hist > 0 else "DOWN"

        ema20  = float(close.ewm(span=20,  adjust=False).mean().iloc[-1])
        ema50  = float(close.ewm(span=50,  adjust=False).mean().iloc[-1])
        e200s  = close.ewm(span=200, adjust=False).mean()
        ema200 = float(e200s.iloc[-1]) if len(close) >= 40 else float("nan")

        _, _, _, bb_pct_s = calc_bollinger(close)
        bb_pct = float(bb_pct_s.iloc[-1]) if not np.isnan(bb_pct_s.iloc[-1]) else 0.5
        bb_pct = max(0.0, min(1.0, bb_pct))

        atr_s = calc_atr(high, low, close)
        atr   = float(atr_s.iloc[-1]) if not np.isnan(atr_s.iloc[-1]) else 0.0

        ema_label = ("BULLISH" if price > ema20 > ema50
                     else "BEARISH" if price < ema20 and ema20 < ema50
                     else "MIXED")

        # Volume ratio
        vol_ratio = 1.0
        if not vol.empty and len(vol.dropna()) >= 5:
            vol_avg = float(vol.iloc[-21:-1].mean())
            if vol_avg > 0:
                vol_ratio = round(float(vol.iloc[-1]) / vol_avg, 2)

        # 6-month range position
        high_6m  = float(high.max())
        low_6m   = float(low.min())
        range_pct = (price - low_6m) / (high_6m - low_6m + 1e-12)
        range_pct = round(max(0.0, min(1.0, range_pct)), 3)

        ema200_val = ema200 if not np.isnan(ema200) else ema50
        score, signal = compute_signal(rsi, macd_hist, ema20, ema50, ema200_val, bb_pct, price)

        dp = 2
        return {
            "symbol": symbol, "name": name,
            "price": round(price, dp), "change_pct": round(chg_pct, 2),
            "rsi": round(rsi, 1),
            "macd_hist": round(macd_hist, 6), "macd_direction": macd_dir,
            "ema20": round(ema20, dp), "ema50": round(ema50, dp),
            "ema200": round(ema200, dp) if not np.isnan(ema200) else None,
            "ema_signal": ema_label,
            "bb_pct": round(bb_pct, 3), "atr": round(atr, dp),
            "vol_ratio": vol_ratio,
            "high_6m": round(high_6m, dp), "low_6m": round(low_6m, dp),
            "range_pct": range_pct,
            "composite_score": score, "signal": signal, "error": None,
        }
    except Exception as exc:
        return {"symbol": symbol, "name": name, "composite_score": -1,
                "signal": "ERROR", "error": str(exc)}

def process_market(symbols_dict, label):
    print(f"\n[{label}] {len(symbols_dict)} symbols…")
    raw = fetch_batch(list(symbols_dict.keys()))
    results = []
    for sym, df in raw.items():
        results.append(process_ticker(df, sym, symbols_dict.get(sym, sym)))
    results.sort(key=lambda x: x.get("composite_score", -1), reverse=True)
    ok = sum(1 for r in results if not r.get("error"))
    print(f"  ✓ {ok}/{len(symbols_dict)} OK")
    return results

# ─── FX ADVANCED PROCESSING ──────────────────────────────

def process_fx_advanced(fx_dict):
    """
    FX Signal = CCI(288) + BB(288, 2σ/3σ) on Daily + 4H
    Monte Carlo ≥55% required to confirm directional signals.
    Weighted: Daily 60%, 4H 40%.
    """
    print(f"\n[FX Advanced] {len(fx_dict)} pairs…")
    daily_data = fetch_batch(list(fx_dict.keys()), period="2y")
    fx_4h_data = fetch_fx_4h(list(fx_dict.keys()))
    results    = []

    for sym, name in fx_dict.items():
        out_sym = SYMBOL_DISPLAY.get(sym, sym)   # display symbol (e.g. GC=F -> XAUUSD)
        try:
            df_d = daily_data.get(sym)
            if df_d is None or len(df_d) < 60:
                results.append({"symbol":out_sym,"name":name,"composite_score":-1,
                                 "signal":"ERROR","error":"No daily data"})
                continue

            close_d = df_d["Close"].squeeze()
            high_d  = df_d["High"].squeeze()
            low_d   = df_d["Low"].squeeze()

            price   = float(close_d.iloc[-1])
            prev    = float(close_d.iloc[-2]) if len(close_d) > 1 else price
            chg_pct = (price - prev) / abs(prev) * 100

            # ── Daily CCI(288) ───────────────────────────
            p_cci_d = min(CCI_PERIOD, len(close_d) - 5)
            cci_d_s = calc_cci(high_d, low_d, close_d, p_cci_d)
            cci_d   = float(cci_d_s.iloc[-1]) if not np.isnan(cci_d_s.iloc[-1]) else 0.0

            # ── Daily BB(288) 2σ & 3σ ────────────────────
            p_bb_d   = min(BB_PERIOD, len(close_d) - 5)
            sma_d    = close_d.rolling(p_bb_d).mean()
            std_d    = close_d.rolling(p_bb_d).std(ddof=0)
            bb_u2_d  = float((sma_d + 2 * std_d).iloc[-1])
            bb_l2_d  = float((sma_d - 2 * std_d).iloc[-1])
            bb_u3_d  = float((sma_d + 3 * std_d).iloc[-1])
            bb_l3_d  = float((sma_d - 3 * std_d).iloc[-1])
            bb_mid_d = float(sma_d.iloc[-1])
            bb_pct_d = (price - bb_l2_d) / (bb_u2_d - bb_l2_d + 1e-12)

            # ── 4H indicators ────────────────────────────
            df_4h    = fx_4h_data.get(sym)
            cci_4h   = 0.0
            bb_pct_4h = bb_pct_d   # fallback
            has_4h   = False

            if df_4h is not None and len(df_4h) >= 40:
                has_4h   = True
                close_4h = df_4h["Close"].squeeze()
                high_4h  = df_4h["High"].squeeze()
                low_4h   = df_4h["Low"].squeeze()

                p_cci_4h = min(CCI_PERIOD, len(close_4h) - 5)
                cci_4h_s = calc_cci(high_4h, low_4h, close_4h, p_cci_4h)
                cci_4h   = float(cci_4h_s.iloc[-1]) if not np.isnan(cci_4h_s.iloc[-1]) else 0.0

                p_bb_4h  = min(BB_PERIOD, len(close_4h) - 5)
                sma_4h   = close_4h.rolling(p_bb_4h).mean()
                std_4h   = close_4h.rolling(p_bb_4h).std(ddof=0)
                bu2_4h   = float((sma_4h + 2 * std_4h).iloc[-1])
                bl2_4h   = float((sma_4h - 2 * std_4h).iloc[-1])
                bb_pct_4h = (float(close_4h.iloc[-1]) - bl2_4h) / (bu2_4h - bl2_4h + 1e-12)

            # ── Weighted composite ───────────────────────
            wd, w4 = (0.6, 0.4) if has_4h else (1.0, 0.0)
            cci_combo = wd * cci_d + w4 * cci_4h
            bb_combo  = wd * bb_pct_d + w4 * bb_pct_4h

            # ── Monte Carlo ──────────────────────────────
            returns_d = close_d.pct_change().dropna()
            direction = "long" if cci_combo >= 0 else "short"
            mc_prob   = monte_carlo_prob(returns_d, n_sims=800, n_forward=5,
                                        direction=direction)
            mc_valid  = mc_prob >= 0.55

            # ── Signal rules ─────────────────────────────
            # STRONG LONG  : CCI ≥ 200 + BB above 2σ + MC ≥ 55%
            # LONG         : CCI ≥ 100 + BB in upper half + MC ≥ 55%
            # NEUTRAL      : CCI in ±100 zone OR MC < 55%
            # SHORT        : CCI ≤ -100 + BB in lower half + MC ≥ 55%
            # STRONG SHORT : CCI ≤ -200 + BB below 2σ + MC ≥ 55%

            if   cci_combo >= 200 and bb_combo >= 1.0 and mc_valid:
                signal = "STRONG LONG"
                score  = min(100, int(88 + min(12, (cci_combo - 200) / 40)))
            elif cci_combo >= 100 and bb_combo >= 0.6 and mc_valid:
                signal = "LONG"
                score  = 70
            elif cci_combo <= -200 and bb_combo <= 0.0 and mc_valid:
                signal = "STRONG SHORT"
                score  = max(0, int(12 - min(12, (abs(cci_combo) - 200) / 40)))
            elif cci_combo <= -100 and bb_combo <= 0.4 and mc_valid:
                signal = "SHORT"
                score  = 30
            else:
                signal = "NEUTRAL"
                score  = 50

            # ── Standard indicators for display ──────────
            rsi_s      = calc_rsi(close_d)
            rsi        = float(rsi_s.iloc[-1]) if not np.isnan(rsi_s.iloc[-1]) else 50.0
            _, _, hist = calc_macd(close_d)
            macd_hist  = float(hist.iloc[-1]) if not np.isnan(hist.iloc[-1]) else 0.0
            macd_dir   = "UP" if macd_hist > 0 else "DOWN"
            atr_s      = calc_atr(high_d, low_d, close_d)
            atr        = float(atr_s.iloc[-1]) if not np.isnan(atr_s.iloc[-1]) else 0.0

            ema20  = float(close_d.ewm(span=20, adjust=False).mean().iloc[-1])
            ema50  = float(close_d.ewm(span=50, adjust=False).mean().iloc[-1])
            ema_lbl = ("BULLISH" if price > ema20 > ema50
                       else "BEARISH" if price < ema20 and ema20 < ema50
                       else "MIXED")

            dp = 5 if price < 10 else (3 if price < 100 else 2)
            bb_pct_display = round(max(0.0, min(1.0, bb_pct_d)), 3)

            row = {
                "symbol": out_sym, "name": name,
                "price": round(price, dp), "change_pct": round(chg_pct, 2),
                "rsi": round(rsi, 1),
                "macd_hist": round(macd_hist, 8), "macd_direction": macd_dir,
                "ema20": round(ema20, dp), "ema50": round(ema50, dp),
                "ema200": None, "ema_signal": ema_lbl,
                "bb_pct": bb_pct_display,
                "bb_upper2": round(bb_u2_d, dp), "bb_lower2": round(bb_l2_d, dp),
                "bb_upper3": round(bb_u3_d, dp), "bb_lower3": round(bb_l3_d, dp),
                "bb_mid":    round(bb_mid_d, dp),
                "cci_daily": round(cci_d, 1),
                "cci_4h":    round(cci_4h, 1),
                "mc_probability": round(mc_prob * 100, 1),
                "mc_valid": mc_valid,
                "atr": round(atr, dp), "vol_ratio": 1.0,
                "range_pct": 0.5,          # FX: not meaningful
                "composite_score": max(0, min(100, score)),
                "signal": signal, "error": None,
            }
            # v2.3: attach computed 1d chart detail for a small allowlist
            # v2.4: attach edge_context placeholder (analytical summary, no scoring)
            if sym in CHART_SYMBOLS:
                attach_charts_to_symbol(row, df_d, dp, datetime.now(JST).isoformat())
                row["edge_context"] = build_empty_edge_context()
            results.append(row)

        except Exception as exc:
            results.append({"symbol": out_sym, "name": name, "composite_score": -1,
                             "signal": "ERROR", "error": str(exc)})

    results.sort(key=lambda x: x.get("composite_score", -1), reverse=True)
    ok = sum(1 for r in results if not r.get("error"))
    print(f"  ✓ {ok}/{len(fx_dict)} FX pairs processed (CCI288+BB288+MC)")
    return results

# ─── MACRO / CRYPTO CATEGORIES (v2.5) ────────────────────
# Rates / Volatility / IMM / Crypto. yfinance only, no API key. Failures fall
# back to placeholder rows so the GitHub Actions run never fails. All outputs
# are market context only, not trading signals.

def _risk_from_change(chg):
    a = abs(chg)
    return "high" if a >= 5 else "medium" if a >= 2 else "low"


def _vix_risk(v):
    return "high" if v >= 30 else "medium" if v >= 20 else "low"


def build_chart_row(yf_sym, display_sym, name, market, risk_fn=None, extra=None):
    """Generic daily row + charts.1d (BB288/CCI, BB48 computed but UI-excluded).

    Falls back to a placeholder row (available:false) on any fetch/calc error.
    """
    try:
        df = fetch_batch([yf_sym], period="2y").get(yf_sym)
        if df is None or len(df) < 60:
            raise ValueError("no daily data")
        close = df["Close"].squeeze()
        price = float(close.iloc[-1])
        prev = float(close.iloc[-2]) if len(close) > 1 else price
        chg = (price - prev) / abs(prev) * 100 if prev else 0.0
        dp = 5 if price < 10 else (3 if price < 100 else 2)
        row = {
            "symbol": display_sym, "name": name, "market": market,
            "price": round(price, dp), "change_pct": round(chg, 2),
            "risk": risk_fn(price) if risk_fn else _risk_from_change(chg),
            "error": None,
        }
        if extra:
            row.update(extra)
        attach_charts_to_symbol(row, df, dp, datetime.now(JST).isoformat())
        row["edge_context"] = build_empty_edge_context()
        return row
    except Exception as exc:
        row = {"symbol": display_sym, "name": name, "market": market,
               "price": None, "change_pct": None, "risk": "unknown",
               "charts": {"4h": build_empty_chart("4h"), "1d": build_empty_chart("1d"),
                          "1w": build_empty_chart("1w")},
               "error": str(exc)[:60]}
        if extra:
            row.update(extra)
        return row


def process_volatility():
    print("\n[Volatility] VIX…")
    return [build_chart_row(
        "^VIX", "VIX", "CBOE Volatility Index", "Volatility", risk_fn=_vix_risk,
        extra={"relation": "Equity risk gauge; rises in risk-off. Cross-check USDJPY / Gold. Context only."},
    )]


CRYPTO = [("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum"),
          ("XRP-USD", "XRP"), ("BCH-USD", "Bitcoin Cash")]


def process_crypto():
    print(f"\n[Crypto] {len(CRYPTO)} assets…")
    return [build_chart_row(sym, sym, name, "Crypto",
                            extra={"relation": "High-volatility asset; cross-check risk / liquidity regime. Context only."})
            for sym, name in CRYPTO]


# Rates: (symbol, name, region, tenor, curve_role, [candidate yfinance tickers]).
# US10Y -> ^TNX (CBOE 10Y yield; may quote x10, normalized below). US2Y -> 2YY=F
# (CBOT 2-Year Yield futures). Japan has no stable free Yahoo yield source, so
# JP rows stay placeholder rather than show fabricated values.
RATE_TICKERS = [
    ("US2Y", "US 2Y Treasury Yield", "US", "2Y", "short_end", ["2YY=F"]),
    ("US10Y", "US 10Y Treasury Yield", "US", "10Y", "long_end", ["^TNX", "10YY=F"]),
    ("JP2Y", "Japan 2Y JGB Yield", "JP", "2Y", "short_end", []),
    ("JP10Y", "Japan 10Y JGB Yield", "JP", "10Y", "long_end", []),
]


def _normalize_yield(v):
    """Normalize a raw Yahoo rate value to a percent yield, or None if implausible.

    Some Yahoo rate tickers (legacy ^TNX) quote yield x10 (e.g. 42.5 = 4.25%).
    Values > 25 are treated as x10-scaled and divided by 10; the result must be a
    plausible yield (0 < y < 25) or it is rejected. No fabrication / no guessing.
    """
    try:
        y = float(v)
    except (TypeError, ValueError):
        return None
    if y > 25:
        y = y / 10.0
    return round(y, 3) if 0 < y < 25 else None


def fetch_rate_history(tickers):
    """Return (normalized daily OHLC df, ticker) or (None, None).

    Yields are normalized to percent (legacy x10 -> /10) and plausibility-gated
    (0 < y < 25). The whole OHLC frame is scaled so charts/indicators are consistent.
    """
    for t in tickers:
        try:
            df = fetch_batch([t], period="2y").get(t)
            if df is None or len(df) < 60:
                continue
            df = df.copy()
            raw_last = float(df["Close"].squeeze().iloc[-1])
            scale = 10.0 if raw_last > 25 else 1.0           # legacy x10 detection
            for col in ("Open", "High", "Low", "Close"):
                if col in df.columns:
                    df[col] = df[col] / scale
            df = df[(df["Close"] > 0) & (df["Close"] < 25)]   # plausibility gate
            if len(df) < 60 or _normalize_yield(float(df["Close"].iloc[-1])) is None:
                continue
            return df, t
        except Exception:
            continue
    return None, None


def load_jp_rates_from_csv(path="data/jp_rates.csv"):
    """Load user-verified Japan yields from a manual CSV (v3.3 fallback).

    Returns {"JP2Y": float, "JP10Y": float} for plausible (0 <= y < 25) numeric
    values from the latest dated row, or {} if the file is absent/empty/invalid.
    Only real, user-verified data should live in data/jp_rates.csv (samples go in
    docs/sample-jp-rates.csv). Never breaks the run.
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f)]
        if not rows:
            return {}
        latest = sorted(rows, key=lambda r: r.get("date", ""))[-1]
        out = {}
        for k in ("JP2Y", "JP10Y"):
            try:
                v = float(latest.get(k))
                if 0 <= v < 25:
                    out[k] = round(v, 3)
            except (TypeError, ValueError):
                pass
        return out
    except Exception:
        return {}


def fetch_jp_rate_yield_live():
    """Live JGB yield fetch — disabled in v3.3.

    No stable, free, keyless daily JGB 2Y/10Y source was confirmed: yfinance has
    no clean JGB-yield ticker, and unverified scrape/CSV endpoints (e.g. Stooq)
    could not be scale-validated here, so they are not adopted (avoid wrong data).
    Returns {} so the pipeline uses the manual CSV / placeholder path. This is the
    hook to enable a verified live source later.
    """
    return {}


def build_rates_market():
    """Rates rows (v3.3). US2Y/US10Y get live yield + charts.1d (BB288/CCI) from the
    daily yield series. Japan uses a verified manual CSV (data/jp_rates.csv) if
    present, else placeholder. yfinance only; failures fall back so the run never
    fails. Context only, not investment advice."""
    print("\n[Rates] US live yield + charts; Japan via manual CSV or placeholder")
    now = datetime.now(JST).isoformat()
    jp_yields = fetch_jp_rate_yield_live() or load_jp_rates_from_csv()
    rows = []
    for sym, name, region, tenor, role, tickers in RATE_TICKERS:
        df, src_t = fetch_rate_history(tickers) if tickers else (None, None)
        live = df is not None and len(df) >= 60
        csv_y = jp_yields.get(sym) if region == "JP" else None
        if live:
            close = df["Close"].squeeze()
            y = round(float(close.iloc[-1]), 3)
            chg = round(y - float(close.iloc[-2]), 3) if len(close) > 1 else None
            chart = build_1d_chart_from_ohlc(df, 3, now)      # BB48/288 + CCI48/288
            chart["source"] = "yfinance"
            chart["source_ticker"] = src_t
            chart["note"] = "Yield chart and indicators are market context only."
            charts = {"4h": build_empty_chart("4h"), "1d": chart, "1w": build_empty_chart("1w")}
            data_status, source, ticker_out, risk = "live", "yfinance", src_t, "medium"
            note = "Yield chart and indicators are market context only, not investment advice."
        elif csv_y is not None:
            y, chg = csv_y, None
            charts = {"4h": build_empty_chart("4h"), "1d": build_empty_chart("1d"),
                      "1w": build_empty_chart("1w")}
            charts["1d"]["note"] = "Japan rates chart source is not configured yet."
            data_status, source, ticker_out, risk = "manual_csv", "data/jp_rates.csv", None, "medium"
            note = "Japan yield data loaded from a user-verified manual CSV. Market context only, not investment advice."
        else:
            y, chg = None, None
            charts = {"4h": build_empty_chart("4h"), "1d": build_empty_chart("1d"),
                      "1w": build_empty_chart("1w")}
            charts["1d"]["note"] = ("Japan rates source is not configured yet."
                                    if region == "JP" else
                                    "Rates chart unavailable for this symbol.")
            data_status, source, ticker_out, risk = "placeholder", None, None, "unknown"
            note = ("Japan yield data unavailable. Add a verified data/jp_rates.csv to enable. "
                    "Placeholder retained for macro context."
                    if region == "JP" else
                    "Yield data unavailable. Placeholder row retained for macro context.")
        rows.append({
            "symbol": sym, "name": name, "market": "Rates", "region": region,
            "tenor": tenor, "yield": y, "change": chg, "curve_role": role,
            "risk": risk, "data_status": data_status, "source": source,
            "source_ticker": ticker_out, "charts": charts, "note": note, "error": None,
        })
        print(f"  {sym}: {data_status} yield={y} src={source}")
    return rows


def build_yield_curve_state(rates_rows):
    """Yield-curve states (v1). US and Japan are assessed SEPARATELY; US recession
    inversion logic is NOT applied to JGB. Context only, not a trade view."""
    y = {r["symbol"]: r.get("yield") for r in rates_rows}

    def us_curve(ten, two):
        if not isinstance(ten, (int, float)) or not isinstance(two, (int, float)):
            return None, "unknown", "unknown"
        s = round(ten - two, 3)
        if s < 0:      return s, "inverted", "high"
        if s < 0.25:   return s, "flat_or_watch", "medium"
        return s, "normal_or_steepening", "low_or_medium"

    def jp_curve(ten, two):
        if not isinstance(ten, (int, float)) or not isinstance(two, (int, float)):
            return None, "unknown", "unknown"
        s = round(ten - two, 3)
        if s < 0:      return s, "inverted_watch", "medium_or_high"
        if s < 0.25:   return s, "flat_or_policy_watch", "medium"
        return s, "normal_or_watch", "low_or_medium"

    us_s, us_state, us_risk = us_curve(y.get("US10Y"), y.get("US2Y"))
    jp_s, jp_state, jp_risk = jp_curve(y.get("JP10Y"), y.get("JP2Y"))
    usjp = (round(y["US10Y"] - y["JP10Y"], 3)
            if isinstance(y.get("US10Y"), (int, float)) and isinstance(y.get("JP10Y"), (int, float))
            else None)
    return {
        "us_10y_2y_spread": {"value": us_s, "state": us_state, "risk": us_risk,
                             "comment": "US curve. Inversion is a recession/policy-stress context, not a trade signal."},
        "jp_10y_2y_spread": {"value": jp_s, "state": jp_state, "risk": jp_risk,
                             "comment": "Japan curve assessed separately (BOJ policy / JGB). US inversion logic is not applied."},
        "us_jp_10y_spread": {"value": usjp, "state": "unknown" if usjp is None else "computed",
                             "relation": "USDJPY yield-spread context",
                             "comment": "Context only, not investment advice."},
    }


IMM = [("JPY_IMM", "JPY", "JPY IMM Positioning"), ("EUR_IMM", "EUR", "EUR IMM Positioning"),
       ("GBP_IMM", "GBP", "GBP IMM Positioning"), ("AUD_IMM", "AUD", "AUD IMM Positioning"),
       ("CAD_IMM", "CAD", "CAD IMM Positioning"), ("CHF_IMM", "CHF", "CHF IMM Positioning")]


_IMM_NOTE = ("IMM positioning is weekly market context only. long/short refer to CFTC "
             "positioning categories and are not trade instructions.")
_IMM_CCY = {"JPY", "EUR", "GBP", "AUD", "CAD", "CHF"}


def load_imm_positions_from_csv(path="data/imm_positions.csv"):
    """Load user-verified CFTC/IMM positioning from a manual CSV (v3.4).

    Returns {ccy: {net_position, weekly_change, long_contracts, short_contracts, date}}
    using the latest dated row per currency, or {} if absent/empty/invalid. Only
    real, user-verified data belongs in data/imm_positions.csv (samples in docs/).
    Never breaks the run.
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f)]
        out = {}
        for r in rows:
            ccy = (r.get("currency") or "").strip().upper()
            if ccy not in _IMM_CCY:
                continue
            try:
                net = int(round(float(r.get("net_position"))))
            except (TypeError, ValueError):
                continue
            d = (r.get("date") or "").strip()
            if ccy in out and d <= out[ccy]["date"]:
                continue
            def _opt_int(k):
                try:
                    return int(round(float(r.get(k))))
                except (TypeError, ValueError):
                    return None
            out[ccy] = {"date": d, "net_position": net,
                        "weekly_change": _opt_int("weekly_change"),
                        "long_contracts": _opt_int("long_contracts"),
                        "short_contracts": _opt_int("short_contracts")}
        return out
    except Exception:
        return {}


def classify_imm_positioning(net):
    """(positioning_state, crowding_risk) from net position. Context, not a signal."""
    if not isinstance(net, (int, float)):
        return "invalid_data", "unknown"
    a = abs(net)
    crowd = "high" if a >= 100000 else "medium" if a >= 50000 else "low"
    state = ("net_long_context" if net > 10000 else
             "net_short_context" if net < -10000 else "neutral_context")
    return state, crowd


def build_imm_market():
    """IMM rows (v3.4). Uses a verified manual CSV (data/imm_positions.csv) if
    present, else placeholder. CFTC auto-download is a later phase. Context only."""
    data = load_imm_positions_from_csv()
    print(f"\n[IMM] {'manual CSV (' + str(len(data)) + ' ccy)' if data else 'placeholder (no verified CSV)'}")
    rows = []
    for sym, ccy, name in IMM:
        d = data.get(ccy)
        if d:
            state, crowd = classify_imm_positioning(d["net_position"])
            row = {
                "symbol": sym, "name": name, "market": "IMM", "currency": ccy,
                "date": d["date"], "net_position": d["net_position"],
                "weekly_change": d["weekly_change"],
                "long_contracts": d["long_contracts"], "short_contracts": d["short_contracts"],
                "positioning_state": state, "crowding_risk": crowd,
                "data_status": "manual_csv", "source": "data/imm_positions.csv",
                "note": _IMM_NOTE, "error": None,
            }
        else:
            row = {
                "symbol": sym, "name": name, "market": "IMM", "currency": ccy,
                "date": None, "net_position": None, "weekly_change": None,
                "long_contracts": None, "short_contracts": None,
                "positioning_state": "placeholder", "crowding_risk": "unknown",
                "data_status": "placeholder", "source": None,
                "note": _IMM_NOTE + " Add a verified data/imm_positions.csv to enable.",
                "error": None,
            }
        rows.append(row)
    return rows

# ─── EDGE SCORING v1 (v3.1) ──────────────────────────────
# USDJPY-only analytical edge context: integrate technical / macro / cross-asset
# / risk context into one summary. "Edge" = clarity of the analytical picture,
# NOT a trading advantage. No buy/sell, entry/exit, target, TP/SL, or automation.

_EDGE_NOTE = ("Edge context is an analytical summary for market review only. "
              "It is not investment advice or a trading signal.")


def classify_technical_edge(chart1d):
    sup, con = [], []
    ind = (chart1d or {}).get("indicators") or {}
    bb = (ind.get("bollinger_bands") or {}).get("288") or {}
    cci = ind.get("cci") or {}
    c48, c288 = (cci.get("48") or {}), (cci.get("288") or {})
    ohlc = (chart1d or {}).get("ohlc") or []
    if not ohlc or c48.get("value") is None or c288.get("value") is None:
        return "insufficient_data", sup, con
    dir_of = {"overbought_context": 1, "oversold_context": -1}.get
    d48, d288 = dir_of(c48.get("state")), dir_of(c288.get("state"))
    if c48.get("state") == "neutral" and c288.get("state") == "neutral":
        state = "neutral_context"; sup.append("CCI 48/288 both neutral — no extreme momentum")
    elif d48 is not None and d48 == d288:
        state = "favorable_context"; sup.append("CCI 48/288 aligned — clear momentum-context read")
    elif d48 is not None and d288 is not None and d48 != d288:
        state = "neutral_context"; con.append("CCI 48/288 divergent — mixed momentum context")
    else:
        state = "neutral_context"
    last = ohlc[-1].get("close")
    s2, s3 = (bb.get("std_2") or {}), (bb.get("std_3") or {})
    up2, lo2, up3, lo3 = s2.get("upper"), s2.get("lower"), s3.get("upper"), s3.get("lower")
    if isinstance(last, (int, float)):
        if isinstance(up3, (int, float)) and last >= up3:
            con.append("Close above BB288 3σ — extreme stretch (caution)")
        elif isinstance(lo3, (int, float)) and last <= lo3:
            con.append("Close below BB288 3σ — extreme stretch (caution)")
        elif isinstance(up2, (int, float)) and isinstance(lo2, (int, float)) and lo2 <= last <= up2:
            sup.append("Close within BB288 2σ band — contained volatility context")
    return state, sup, con


def classify_macro_edge(rates, yield_curve):
    sup, con = [], []
    by = {r["symbol"]: r for r in (rates or [])}
    us2, us10 = by.get("US2Y", {}).get("yield"), by.get("US10Y", {}).get("yield")
    if not isinstance(us2, (int, float)) or not isinstance(us10, (int, float)):
        return "insufficient_data", sup, con
    st = ((yield_curve or {}).get("us_10y_2y_spread") or {}).get("state")
    if st == "inverted":
        con.append("US 10Y-2Y inverted — recession / policy-stress context"); state = "mixed_macro_context"
    elif st == "normal_or_steepening":
        sup.append("US 10Y-2Y normal/steepening — non-recessionary curve context"); state = "favorable_context"
    elif st == "flat_or_watch":
        con.append("US 10Y-2Y flat — late-cycle watch"); state = "mixed_macro_context"
    else:
        state = "neutral_context"
    if us10 >= 4.0:
        sup.append("US10Y elevated (>=4%) — yield context supportive for USD")
    return state, sup, con


def classify_cross_asset_edge(usdjpy_row, fx, vol, yield_curve, imm=None):
    # sup/con = market context (counted in overall); gaps = data-availability notes
    # (shown for transparency but NOT counted as market conflicts).
    sup, con, gaps = [], [], []
    vix = (vol[0] if vol else {}) or {}
    if vix.get("risk") in ("high", "medium") and vix.get("price") is not None:
        con.append("VIX elevated — risk-off pressure (yen safe-haven context)")
    elif vix.get("risk") == "low":
        sup.append("Volatility contained (VIX low) — calm risk environment")
    gold = next((r for r in (fx or []) if r.get("symbol") in ("XAUUSD", "XAUUSD=X")), {}) or {}
    gch, uch = gold.get("change_pct"), usdjpy_row.get("change_pct")
    if isinstance(gch, (int, float)) and isinstance(uch, (int, float)) and gch > 0 and uch > 0:
        con.append("Gold and USDJPY both firming — cross-asset risk-on/off tension")
    usjp = (yield_curve or {}).get("us_jp_10y_spread") or {}
    if usjp.get("value") is None:
        gaps.append("US-JP 10Y spread unavailable (JP yields placeholder) — incomplete FX-rates context")
    else:
        sup.append("US-JP 10Y spread available — USDJPY yield-spread context")
    # v3.4: JPY IMM positioning context (only when verified CSV data is present)
    jpy_imm = next((r for r in (imm or []) if r.get("symbol") == "JPY_IMM"), {}) or {}
    if jpy_imm.get("data_status") == "manual_csv" and jpy_imm.get("positioning_state") not in (None, "placeholder", "invalid_data"):
        sup.append(f"JPY IMM positioning available — {jpy_imm.get('positioning_state')} "
                   f"(crowding {jpy_imm.get('crowding_risk')}); CFTC category context only")
    else:
        gaps.append("JPY IMM positioning unavailable (no verified CSV) — positioning context incomplete")
    gaps.append("DXY not in dataset — USD-strength cross-check unavailable")
    state = "partially_aligned" if (sup and con) else ("favorable_context" if sup else "mixed_macro_context")
    return state, sup, con, gaps


def classify_risk_adjusted_edge(vol, conflict_count):
    sup, con = [], []
    vix = (vol[0] if vol else {}) or {}
    if vix.get("risk") == "high":
        con.append("Volatility regime elevated — wider risk band")
    if conflict_count >= 3:
        con.append("Multiple cross-context conflicts — mixed risk picture"); state = "mixed_risk_context"
    elif conflict_count <= 1 and vix.get("risk") == "low":
        sup.append("Few conflicts and contained volatility — steadier risk context"); state = "favorable_risk_context"
    else:
        state = "mixed_risk_context"
    return state, sup, con


def build_usdjpy_edge_context(usdjpy_row, fx, rates, vol, yield_curve, imm=None):
    """Populated edge_context for USDJPY=X (v3.1). Returns None to keep placeholder."""
    chart = (usdjpy_row.get("charts") or {}).get("1d") or {}
    if chart.get("available") is not True:
        return None
    t_state, t_sup, t_con = classify_technical_edge(chart)
    m_state, m_sup, m_con = classify_macro_edge(rates, yield_curve)
    c_state, c_sup, c_con, c_gaps = classify_cross_asset_edge(usdjpy_row, fx, vol, yield_curve, imm)
    r_state, r_sup, r_con = classify_risk_adjusted_edge(vol, len(t_con + m_con + c_con))
    # supporting/conflicting drive `overall`; data-availability gaps are shown on the
    # cross_asset dimension only (not counted as market conflicts).
    supporting = t_sup + m_sup + c_sup + r_sup
    conflicting = t_con + m_con + c_con + r_con
    if "insufficient_data" in (t_state, m_state):
        overall, conf = "insufficient_data", "low"
    elif len(supporting) >= 3 and len(conflicting) <= 1:
        overall, conf = "moderate_contextual_edge", "medium"
    elif len(supporting) >= 1 and len(conflicting) <= 2:
        overall, conf = "limited_contextual_edge", "medium" if len(supporting) >= 3 else "low"
    elif supporting and conflicting:
        overall, conf = "conflicting_context", "low"
    else:
        overall, conf = "neutral_context", "low"
    return {
        "overall": overall, "confidence": conf,
        "technical": {"state": t_state, "factors": t_sup + t_con},
        "macro": {"state": m_state, "factors": m_sup + m_con},
        "cross_asset": {"state": c_state, "factors": c_sup + c_con + c_gaps},
        "risk_adjusted": {"state": r_state, "factors": r_sup + r_con},
        "supporting_factors": supporting,
        "conflicting_factors": conflicting,
        "note": _EDGE_NOTE,
    }

# ─── MULTI-TIMEFRAME CHARTS (v3.2) ───────────────────────
# 4h (1h→4h resample) and 1w (1d→1w resample) charts for a small allowlist,
# reusing build_1d_chart_from_ohlc. yfinance only; failures fall back to the
# existing available:false placeholder. Context only, not trading signals.

# display symbol -> (yfinance source ticker, is_yield)
MTF_ALLOWLIST = {
    "USDJPY=X": ("USDJPY=X", False), "EURUSD=X": ("EURUSD=X", False),
    "XAUUSD": ("GC=F", False), "XAGUSD": ("SI=F", False),
    "VIX": ("^VIX", False), "BTC-USD": ("BTC-USD", False), "ETH-USD": ("ETH-USD", False),
    "US10Y": ("^TNX", True), "US2Y": ("2YY=F", True),
}


def fetch_ohlc_history(ticker, interval, period):
    """Daily/intraday OHLC via yfinance, with single-ticker MultiIndex flattened."""
    try:
        raw = yf.download(ticker, interval=interval, period=period, auto_adjust=True, progress=False)
        if raw is None or raw.empty:
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        return raw
    except Exception:
        return None


def resample_ohlc(df, rule):
    """Resample OHLC to `rule` (e.g. '4h', '1W'). Returns None on failure."""
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    if "Volume" in df.columns:
        agg["Volume"] = "sum"
    try:
        return df.resample(rule).agg(agg).dropna()
    except Exception:
        return None


def _normalize_yield_df(df):
    """Scale-normalize a yield OHLC frame to percent (legacy x10 -> /10), 0<y<25."""
    try:
        last = float(df["Close"].iloc[-1])
        scale = 10.0 if last > 25 else 1.0
        if scale != 1.0:
            df = df.copy()
            for c in ("Open", "High", "Low", "Close"):
                if c in df.columns:
                    df[c] = df[c] / scale
        return df[(df["Close"] > 0) & (df["Close"] < 25)]
    except Exception:
        return None


def build_tf_chart(ticker, interval, period, rule, dp, now, is_yield=False):
    """Build a charts[tf] block from a resampled OHLC series. None on failure."""
    try:
        df = fetch_ohlc_history(ticker, interval, period)
        if df is None or len(df) < 10:
            return None
        df = resample_ohlc(df, rule)
        if df is not None and is_yield:
            df = _normalize_yield_df(df)
        if df is None or len(df) < 10:
            return None
        chart = build_1d_chart_from_ohlc(df, dp, now)   # BB48/288 + CCI48/288
        if chart.get("available") is not True:
            return None
        chart["source"] = "yfinance"
        chart["source_ticker"] = ticker
        chart["note"] = "Chart and indicators are market context only."
        return chart
    except Exception:
        return None


def attach_multitimeframe_charts(row, source_ticker, is_yield, dp, now):
    """Attach 4h (1h→4h) and 1w (1d→1w) charts for an allowlist row; keep 1d."""
    c4 = build_tf_chart(source_ticker, "1h", "60d", "4h", dp, now, is_yield)
    if c4:
        row["charts"]["4h"] = c4
    c1w = build_tf_chart(source_ticker, "1d", "5y", "1W", dp, now, is_yield)
    if c1w:
        row["charts"]["1w"] = c1w
    return row


def attach_mtf_for_allowlist(market_groups):
    """For each allowlist symbol with an available 1d chart, add 4h/1w charts."""
    print("\n[Multi-timeframe] 4h/1w for allowlist symbols…")
    now = datetime.now(JST).isoformat()
    for grp in market_groups:
        for r in grp:
            spec = MTF_ALLOWLIST.get(r.get("symbol"))
            if not spec:
                continue
            if not ((r.get("charts") or {}).get("1d") or {}).get("available"):
                continue
            src, is_yield = spec
            price = r.get("yield") if is_yield else r.get("price")
            dp = 3 if is_yield else (5 if (price or 0) < 10 else 3 if (price or 0) < 100 else 2)
            try:
                attach_multitimeframe_charts(r, src, is_yield, dp, now)
                ch = r["charts"]
                print(f"  {r['symbol']:9s} 4h={ch['4h'].get('available')} 1w={ch['1w'].get('available')}")
            except Exception as exc:
                print(f"  {r['symbol']}: mtf skipped ({str(exc)[:50]})")

# ─── EQUITY CHARTS (v3.5) ────────────────────────────────
# Index-level proxies + a small constituent allowlist get charts.1d (1d only;
# 4h/1w deferred for equities to control payload). yfinance only; failures fall
# back. All 364+ constituents are NOT charted (payload). Context only.

# Index proxy rows added to each equity tab: (yfinance ticker, name, group).
EQUITY_INDEX = [
    ("^N225", "Nikkei 225 Index", "nikkei225"),
    ("^DJI", "Dow Jones Industrial Average", "dow30"),
    ("^NDX", "Nasdaq 100 Index", "nasdaq100"),
    ("^GSPC", "S&P 500 Index", "sp500"),
]
# Existing constituents that get charts.1d (must match data.json symbols).
EQUITY_ALLOWLIST = {
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "UNH",
    "7203.T", "9984.T", "8035.T",
}


def _equity_empty_charts():
    c = {"4h": build_empty_chart("4h"), "1d": build_empty_chart("1d"), "1w": build_empty_chart("1w")}
    c["4h"]["note"] = "Equity 4h chart is deferred to avoid payload expansion."
    c["1w"]["note"] = "Equity weekly chart is deferred to avoid payload expansion."
    return c


def build_equity_chart_1d(df, source_ticker, now, dp):
    """charts.1d (BB288/CCI) from a daily equity/index OHLC frame, or None."""
    chart = build_1d_chart_from_ohlc(df, dp, now)
    if chart.get("available") is not True:
        return None
    chart["source"] = "yfinance"
    chart["source_ticker"] = source_ticker
    chart["note"] = "Equity chart and indicators are market context only."
    return chart


def attach_equity_charts(equity_markets):
    """Add charts.1d to allowlisted constituents and insert scored+charted index
    proxy rows. yfinance only; per-symbol try/except so the run never fails."""
    print("\n[Equity charts] index proxies + selected constituents (1d only)…")
    now = datetime.now(JST).isoformat()
    # selected existing constituents
    for grp in ("nikkei225", "dow30", "nasdaq100", "sp500"):
        for r in equity_markets.get(grp, []):
            if r.get("symbol") not in EQUITY_ALLOWLIST or r.get("error"):
                continue
            try:
                df = fetch_batch([r["symbol"]], period="2y").get(r["symbol"])
                if df is None or len(df) < 60:
                    continue
                price = r.get("price") or float(df["Close"].squeeze().iloc[-1])
                dp = 2 if (price or 0) >= 100 else 3 if (price or 0) >= 1 else 5
                chart = build_equity_chart_1d(df, r["symbol"], now, dp)
                if chart:
                    r["charts"] = {"4h": _equity_empty_charts()["4h"], "1d": chart,
                                   "1w": _equity_empty_charts()["1w"]}
            except Exception:
                continue
    # index-level proxy rows (scored via process_ticker + charted), pinned on top
    for idx_t, name, grp in EQUITY_INDEX:
        try:
            df = fetch_batch([idx_t], period="2y").get(idx_t)
            if df is None or len(df) < 60:
                continue
            row = process_ticker(df, idx_t, name)
            if row.get("error"):
                continue
            price = row.get("price") or 0
            dp = 2 if (price or 0) >= 100 else 3
            chart = build_equity_chart_1d(df, idx_t, now, dp)
            ec = _equity_empty_charts()
            row["charts"] = {"4h": ec["4h"], "1d": chart or ec["1d"], "1w": ec["1w"]}
            equity_markets.setdefault(grp, []).insert(0, row)
            print(f"  {idx_t:7s} index row added to {grp} (chart={bool(chart)})")
        except Exception as exc:
            print(f"  {idx_t}: index chart skipped ({str(exc)[:50]})")

# ─── SUMMARY ─────────────────────────────────────────────

def build_summary(rows):
    counts = {}
    for r in rows:
        sig = r.get("signal", "ERROR")
        counts[sig] = counts.get(sig, 0) + 1
    return counts

# ─── MAIN ────────────────────────────────────────────────

def main():
    t0      = time.time()
    now_jst = datetime.now(JST)
    print(f"=== HF Signal Scanner Pro v2 ===")
    print(f"Run at: {now_jst.strftime('%Y-%m-%d %H:%M:%S JST')}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sp500_tickers, sp500_names = get_sp500_tickers()
    sp500_dict = {t: sp500_names.get(t, t) for t in sp500_tickers}

    nk_results  = process_market(NIKKEI225,  "Nikkei225")
    dj_results  = process_market(DOW30,      "Dow30")
    nq_results  = process_market(NASDAQ100,  "Nasdaq100")
    sp_results  = process_market(sp500_dict, "S&P500")
    fx_results  = process_fx_advanced(FX_PAIRS)

    # v2.5: macro / crypto categories (yfinance only; failures fall back)
    rates_results = build_rates_market()
    vol_results   = process_volatility()
    imm_results   = build_imm_market()
    crypto_results = process_crypto()
    yield_curve   = build_yield_curve_state(rates_results)

    # v3.1: populate USDJPY=X edge_context from integrated context (USDJPY only)
    _usdjpy = next((r for r in fx_results if r.get("symbol") == "USDJPY=X"), None)
    if _usdjpy is not None:
        _edge = build_usdjpy_edge_context(_usdjpy, fx_results, rates_results, vol_results, yield_curve, imm_results)
        if _edge:
            _usdjpy["edge_context"] = _edge
            print(f"\n[Edge v1] USDJPY=X -> {_edge['overall']} ({_edge['confidence']}), "
                  f"sup={len(_edge['supporting_factors'])} con={len(_edge['conflicting_factors'])}")

    # v3.2: 4h / 1w charts for a small allowlist (reuses existing chart builder)
    attach_mtf_for_allowlist((fx_results, vol_results, crypto_results, rates_results))

    # v3.5: equity charts — index proxies + selected constituents (1d only)
    attach_equity_charts({"nikkei225": nk_results, "dow30": dj_results,
                          "nasdaq100": nq_results, "sp500": sp_results})

    next_run = (now_jst + timedelta(days=1)).replace(
        hour=8, minute=0, second=0, microsecond=0)

    payload = {
        "meta": {
            "updated_at":      now_jst.isoformat(),
            "updated_at_str":  now_jst.strftime("%Y-%m-%d %H:%M JST"),
            "next_update_str": next_run.strftime("%Y-%m-%d %H:%M JST"),
            "elapsed_sec":     round(time.time() - t0, 1),
            "counts": {
                "nikkei225": len(nk_results), "dow30": len(dj_results),
                "nasdaq100": len(nq_results), "sp500": len(sp_results),
                "fx": len(fx_results), "rates": len(rates_results),
                "volatility": len(vol_results), "imm": len(imm_results),
                "crypto": len(crypto_results),
            },
            "yield_curve": yield_curve,
        },
        "summary": {
            "nikkei225": build_summary(nk_results),
            "dow30":     build_summary(dj_results),
            "nasdaq100": build_summary(nq_results),
            "sp500":     build_summary(sp_results),
            "fx":        build_summary(fx_results),
        },
        "markets": {
            "nikkei225": nk_results, "dow30": dj_results,
            "nasdaq100": nq_results, "sp500": sp_results,
            "fx":        fx_results,
            "rates":      rates_results, "volatility": vol_results,
            "imm":        imm_results,   "crypto":     crypto_results,
        },
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    kb = OUTPUT_FILE.stat().st_size / 1024
    print(f"\n✅ data.json → {OUTPUT_FILE} ({kb:.1f} KB, {time.time()-t0:.0f}s)")

if __name__ == "__main__":
    main()
