# HF Signal Scanner Pro

A public, auto-updating **cross-asset market dashboard** — equities, FX, commodities, rates,
volatility, IMM positioning, and crypto — with per-symbol technical charts (Bollinger Bands,
CCI) and an investment-bank-style macro layer (yield curve, regime context).

**▶ Live dashboard: https://hf-signal-dashboard.pages.dev/**

> **30-second pitch:** A Python pipeline pulls daily market data from Yahoo Finance, scores it
> across 9 market groups, and writes a single `data.json`. A dependency-free static front-end
> (inline-SVG charts, no chart library) renders it, deployed on Cloudflare Pages and refreshed
> automatically every day by GitHub Actions. It demonstrates an end-to-end data pipeline,
> CI-driven data refresh, a documented data contract between a public UI and a private analysis
> engine, and careful GRC framing (everything is market *context*, never trade advice).

> **For data visualization and portfolio demonstration only. Not investment advice. No buy/sell recommendation.**

---

## What it is

A two-component market-analysis stack:

| Component | Role |
|---|---|
| **hf-signal-dashboard** (this repo) | Public UI + its own data pipeline. Renders the dashboard. |
| **fx-analysis-system** *(private engine)* | Deeper macro risk scoring / COT / event-risk analysis. Kept private. |

The dashboard is **self-contained**: the data format, sample data, and signal logic needed to
understand the project all live in this public repo. The integration interface to the private
engine is documented in [DATA_CONTRACT.md](DATA_CONTRACT.md) — so the engine can stay private
without leaving the portfolio incomplete.

---

## Features

- **10 market tabs** — Nikkei 225, Dow 30, Nasdaq 100, S&P 500, FX / Commodities, Rates / Bonds,
  VIX, IMM, Crypto, Valuation.
- **Click-to-expand detail panel** per symbol with lightweight **inline-SVG charts** (no external
  chart library, mobile-friendly), with **switchable 4h / 1d / 1w timeframe tabs** (4h/1w on an
  allowlist of liquid symbols — USDJPY, EURUSD, XAUUSD, XAGUSD, VIX, BTC, ETH, US2Y, US10Y):
  - Close / yield line
  - **Bollinger Bands 288** (2σ and 3σ) overlay — long-cycle volatility context
  - **CCI 48 / 288** lower panel with ±200 reference — extended momentum context
  - Heuristic **Elliott** candidate (badge/note only, `confidence: low`)
- **Live yields & yield curve** — US2Y / US10Y fetched and normalized from Yahoo; **US and Japan
  curves are assessed separately** (US recession-inversion logic is never applied to JGB);
  US-JP 10Y spread as USDJPY context. Japan (JP2Y/JP10Y) has no stable free live source, so it can
  be supplied via a **user-verified** `data/jp_rates.csv` (`data_status: manual_csv`; see
  `docs/sample-jp-rates.csv`); without it, Japan stays an explicit placeholder rather than show
  unverified data. When JP yields are present, the Japan curve and US-JP spread compute and the
  USDJPY edge context picks up the spread automatically.
- **Cross-asset macro layer** (data contract) — rates, volatility (VIX/MOVE), commodities incl.
  Gold/Silver & Copper/Gold ratios, regime labels, and an `edge_context` analytical summary.
- **Valuation (v4.0) — Buffett Indicator** — long-term equity-market valuation context
  (market cap ÷ GDP × 100) for US & Japan, supplied via a **user-verified**
  `data/valuation_metrics.csv` (`data_status: manual_csv`; see `docs/sample-valuation-metrics.csv`);
  without it, rows stay an explicit placeholder (no fabricated market-cap/GDP). Shown as a
  long-term valuation regime label only — **not market timing**, not a trading signal.
- **Watchlist, search, signal filters, CSV export, dark/light theme** in the UI.
- **Graceful degradation** — symbols without chart data, errored tickers, and placeholder rows
  all fall back cleanly; the daily pipeline never fails on a single bad ticker.

Markets/symbols without computed charts (e.g. equities, IMM, Japan rates) show a clear
"chart data not available" fallback — no fabricated values.

---

## Supported markets

| Tab | Coverage | Detail charts |
|---|---|---|
| Nikkei 225 / Dow 30 / Nasdaq 100 / S&P 500 | Major index constituents (380+ symbols) | Signal table; index proxy (^N225/^DJI/^NDX/^GSPC) + selected constituents have 1d charts (BB288 + CCI ±200); others fall back |
| FX / Commodities | Major & minor pairs, Gold, Silver | Close + BB288 + CCI ±200 (live) |
| Rates / Bonds | US2Y, US10Y (live) · JP2Y, JP10Y (placeholder) + yield curve | US2Y/US10Y yield charts (live) |
| VIX | CBOE Volatility Index (live) | Close + BB288 + CCI ±200 (live) |
| IMM | CFTC currency positioning (JPY/EUR/GBP/AUD/CAD/CHF) | Verified manual CSV (`data/imm_positions.csv`) → net position / state / crowding; else placeholder |
| Crypto | BTC, ETH, XRP, BCH (live) | Close + BB288 + CCI ±200 (live) |
| Valuation | Buffett Indicator — US, Japan (market cap ÷ GDP) | Verified manual CSV (`data/valuation_metrics.csv`) → value + long-term valuation context; else placeholder. No charts (slow-moving). |

---

## Architecture

```
GitHub Actions (daily 08:00 JST / 23:00 UTC, or manual)
  └── Python + yfinance  →  fetch_signals.py  →  docs/data.json (auto-committed)
        └── Cloudflare Pages serves docs/ as the public site
              └── docs/index.html (vanilla JS + inline SVG) reads data.json
```

- **Data source:** Yahoo Finance via `yfinance` — **no API key, no paid API**.
- **Pipeline:** `fetch_signals.py` fetches, scores, computes indicators (RSI/MACD/EMA/Bollinger/CCI),
  and writes one `docs/data.json`.
- **Hosting:** Cloudflare Pages (free tier).
- **Scheduler:** GitHub Actions (`.github/workflows/update_signals.yml`) — runs the pipeline daily,
  commits the refreshed `data.json`, which redeploys Pages. ~2000 free minutes/month is ample.
- **Front-end:** a single static `index.html` (no build step, no framework, no chart library) —
  charts are drawn with hand-rolled inline SVG.

### Data flow

```
fetch_signals.py ──> docs/data.json ──> Cloudflare Pages ──> browser (index.html renders)
        ▲                                   ▲
   GitHub Actions (daily)            auto-redeploy on commit
```

---

## Signal scoring (technical methodology)

A transparent composite of four indicators (this is a documented methodology, **not** advice):

| Indicator | Weight | Logic |
|---|---|---|
| RSI(14) | 0–25 | RSI ≤ 30 scores highest (oversold) |
| MACD Histogram | 0–25 | Positive momentum adds score |
| EMA Trend | 0–25 | Price > EMA20 > EMA50 > EMA200 = max |
| Bollinger %B | 0–25 | Near lower band scores higher |

The composite (0–100) maps to a labelled state shown in the table (equities and FX use their own
label sets). Labels are a **scoring output for context**, not a recommendation to trade.

---

## Data model & contract

[DATA_CONTRACT.md](DATA_CONTRACT.md) is the single source of truth for the `data.json` /
`signals.json` schema, including the full version history (v1.0 → v2.5.x). In summary it covers:

- per-symbol signal rows and the cross-asset `macro` section (rates / yield_curve / volatility /
  commodities / cross_asset / regime),
- per-symbol `charts` (OHLC + Bollinger 48/288 with 2σ/3σ + CCI 48/288 + Elliott candidate),
- `edge_context` (an analytical summary — *contextual* edge, never a trading advantage),
- forbidden fields (no API keys, no account or execution data, and no directional signal values).

Sample data: [docs/sample-signals.json](docs/sample-signals.json).

All of it is **market context only** — not investment advice, price targets, trade execution,
or buy/sell recommendations. IMM `long`/`short` refer to CFTC positioning categories only.

---

## Screenshots

Live: **https://hf-signal-dashboard.pages.dev/** — the captures below are of the live site.

### FX / Commodities detail with Edge Context

USDJPY=X with switchable 4h / 1d / 1w timeframe tabs, a 1d close line, Bollinger Bands 288
(2σ / 3σ) overlay, a CCI ±200 lower panel, an Elliott placeholder, and the USDJPY **Edge Context**
(overall / confidence + technical / macro / cross-asset / risk-adjusted dimensions with supporting
vs conflicting factors) — analytical context only.

![HF Signal Dashboard — FX detail with multi-timeframe tabs, BB288, CCI ±200, and Edge Context](docs/assets/hf-signal-dashboard-detail.png)

### Rates / Bonds live yield view

The Rates / Bonds tab separates live US2Y / US10Y yields (`data_status: live`) from placeholder
Japan rows (`data_status: placeholder`), with a yield chart (BB288 + CCI ±200) for the available
US rates. US and Japan curves are assessed separately.

![HF Signal Dashboard — Rates / Bonds with live US yields and a US10Y yield chart](docs/assets/hf-signal-dashboard-rates.png)

### Equity chart view

Index proxies (^N225/^DJI/^NDX/^GSPC) and a selected constituent allowlist (e.g. AAPL, shown)
include a 1d chart with BB288 (2σ / 3σ) and CCI ±200; non-allowlist symbols fall back gracefully.

![HF Signal Dashboard — S&P 500 equity (AAPL) 1d chart with BB288 and CCI ±200](docs/assets/hf-signal-dashboard-v3-equity.png)

### Valuation / Buffett Indicator view

The Valuation tab adds long-term equity market valuation context through the Buffett Indicator framework. Verified market-cap/GDP data can be supplied through a manual CSV, while missing data remains explicit placeholder rather than fabricated.

![HF Signal Dashboard v4 valuation view](docs/assets/hf-signal-dashboard-v4-valuation.png)

---

## Quick start (local)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python fetch_signals.py            # generates docs/data.json (10–20 min; Yahoo rate limits)
cd docs && python -m http.server 8080
# open http://localhost:8080
```

### Deploy your own

- **GitHub Actions:** Actions tab → "Daily Signal Update" → **Run workflow** (also runs daily on cron).
- **Cloudflare Pages:** Connect the repo → Build command *(empty)* → Output directory `docs` → Deploy.

---

## Portfolio context (what this demonstrates)

- **End-to-end data pipeline:** fetch → score → compute indicators → serialize → serve.
- **CI-driven automation:** GitHub Actions refreshes and commits data daily, with per-symbol
  fault tolerance so one bad ticker never breaks the run.
- **Zero-dependency front-end:** responsive inline-SVG charts with no chart library or build step.
- **Interface design:** a documented data contract lets a public UI and a private analysis engine
  evolve independently — the engine can go private without breaking the portfolio.
- **Cross-asset / macro thinking:** equities, FX, rates, yield curve (US vs Japan handled
  separately), volatility, positioning, and crypto in one view.
- **GRC discipline:** consistent, explicit framing as market *context* — no investment advice,
  no buy/sell instructions, no fabricated data, secrets kept out of the repo.

---

## Disclaimer

This project is for **market data visualization and portfolio demonstration purposes only**.
It is **not** investment advice, financial advice, or an automated trading system.
**No buy/sell recommendation is provided.** Charts, indicators, yield curves, Elliott candidates,
and edge context are market context only.

本プロジェクトは市場データの可視化およびポートフォリオ目的のデモです。
投資助言、金融助言、自動売買システムではありません。
売買判断は利用者自身の責任で行ってください。

---

## File structure

```
hf-signal-dashboard/
├── .github/workflows/
│   └── update_signals.yml      # Daily GitHub Actions pipeline
├── docs/                       # Cloudflare Pages root
│   ├── index.html              # Dashboard UI (vanilla JS + inline SVG)
│   ├── data.json               # Generated market data (auto-updated daily)
│   └── sample-signals.json     # Sample data in the integration-contract format
├── fetch_signals.py            # Data pipeline: fetch → score → indicators → data.json
├── DATA_CONTRACT.md            # Schema + version history (single source of truth)
├── requirements.txt
└── README.md
```

---

## Troubleshooting

- **Actions fail:** check `requirements.txt` pinning; `yfinance` timeouts are usually transient — re-run.
- **No signals displayed:** run the workflow manually; locally use `python -m http.server` (avoid `file://` CORS).
- **Symbol not found:** Japanese stocks use the `.T` suffix (e.g. `7203.T`); tickers can change on delisting.
