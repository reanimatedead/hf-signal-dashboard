# v3 Roadmap

hf-signal-dashboard reached a public-portfolio finish line at v2.5.x. v3 advances depth in
small, independent, low-risk steps. Each phase ships on its own; none breaks the finished line.

**Everything below is market context only — not investment advice, not a trading signal, no
buy/sell recommendation, no entry/exit/TP/SL, no automated trading.**

Recommended order: **v3.1 → v3.3 → v3.2 → v3.4 → v3.5**.

---

## v3.1 — Edge Scoring v1  ✅ (this release)

**Goal:** make `edge_context` *meaningful* for USDJPY by integrating technical / macro /
cross-asset / risk context into one analytical summary.

- **Scope:** `USDJPY=X` only, `1d` only, only when `charts.1d.available === true`.
- **Inputs:** BB288 2σ/3σ, CCI48/288, US2Y/US10Y, US 10Y-2Y spread (`meta.yield_curve`), VIX,
  XAUUSD/Gold, DXY (placeholder if unavailable), risk regime (placeholder).
- **Output:** `overall`, `confidence`, `technical`, `macro`, `cross_asset`, `risk_adjusted`,
  `supporting_factors`, `conflicting_factors`, `note`.
- **Allowed `overall`:** `moderate_contextual_edge`, `limited_contextual_edge`, `neutral_context`,
  `conflicting_context`, `insufficient_data`, `unknown_context`. **Not** `strong_contextual_edge`.
- **`confidence`:** `low` or `medium` only.
- **Forbidden:** buy/sell/long/short recommendation, entry/exit, take-profit/stop-loss, target
  price, automated trading.

Other symbols keep the `unknown_context` placeholder ("No clear edge context" in the UI).

---

## v3.2 — 4h / 1w charts  ✅ (allowlist shipped)

**Goal:** extend the existing 1d chart to 4h and 1w, incrementally.

- **Shipped:** `charts.4h` (1h→4h resample, ~60d) and `charts.1w` (1d→1w resample, ~5y) for an
  allowlist — USDJPY, EURUSD, XAUUSD, XAGUSD, VIX, BTC, ETH, US2Y, US10Y — reusing the shared 1d
  chart builder (BB288 2σ/3σ + CCI ±200; BB48 not chart-rendered). OHLC capped at 120 bars per
  timeframe; 1w typically has <288 weeks so BB288/CCI288 report `insufficient_data` while the
  close line + CCI48 still render. UI timeframe tabs (4時間足/日足/週足) now switch the chart.
  Per-symbol `try/except`; failures fall back to `available:false`.
- **Deferred:** full-symbol expansion (all FX / equities), 4h/1w on every market — kept off to
  control `data.json` payload and Actions time.

---

## v3.3 — Japan rates live  ✅ (manual-CSV path shipped)

**Goal:** make JP2Y / JP10Y real and complete the Japan curve + US-JP 10Y spread.

- **Decision:** no stable free keyless **live** source was confirmed (yfinance has no clean
  JGB-yield ticker; unverified scrape/CSV endpoints could not be scale-validated). Shipped the
  **manual CSV** path: commit a user-verified `data/jp_rates.csv`
  (`date,JP2Y,JP10Y,source,note`; see `docs/sample-jp-rates.csv`) → JP rows become `manual_csv`,
  and the Japan curve, US-JP 10Y spread, and the USDJPY edge cross-asset factor compute
  automatically. Without the file, Japan stays `placeholder`.
- No fabrication, no API key, never breaks the workflow. `fetch_jp_rate_yield_live()` is a hook to
  enable a verified live source later. Japan is always assessed separately from the US curve.

---

## v3.4 — IMM positioning  ✅ (manual-CSV path shipped)

**Goal:** move JPY/EUR/GBP/AUD/CAD/CHF IMM rows from placeholder to real data.

- **Shipped:** a verified `data/imm_positions.csv` (see `docs/sample-imm-positions.csv`) populates
  net_position / weekly_change / long & short contracts / positioning_state / crowding_risk
  (`data_status: manual_csv`, latest dated row per currency). Without it, rows stay `placeholder`
  (no fabrication). When `JPY_IMM` is present, the USDJPY edge cross-asset dimension gains a
  (non-trade) positioning-context factor. A `Data` column shows live/manual_csv/placeholder.
- **Deferred:** automated CFTC weekly download (fragile; needs verification). `long` / `short` are
  CFTC positioning categories only — never trade instructions.

---

## v3.5 — Equity charts  ✅ (index + allowlist shipped)

**Goal:** extend `charts.1d` to the equity tabs.

- **Shipped:** index-proxy rows (^N225 / ^DJI / ^NDX / ^GSPC) are scored (`process_ticker`) and
  charted, pinned atop each equity tab; a small constituent allowlist (AAPL, MSFT, NVDA, AMZN,
  GOOGL, META, TSLA, JPM, UNH, 7203.T, 9984.T, 8035.T) gains `charts.1d` (BB288 2σ/3σ + CCI ±200).
  Equity 4h/1w are deferred (`available:false`) to control payload. ~16 charts; `data.json` kept
  well under 1.5MB. Per-symbol `try/except`; failures fall back.
- **Deferred:** full per-symbol equity charts (380+ names), equity 4h/1w, and lazy loading / a
  separate per-market JSON — these would bloat a single `data.json`; revisit only if needed.

---

## v3 status

v3.1 (edge), v3.2 (4h/1w allowlist), v3.3 (JP rates CSV), v3.4 (IMM CSV), v3.5 (equity charts) are
all shipped. Remaining items are intentionally deferred (full-symbol expansion, automated CFTC/JP
live feeds, lazy loading) — each would add payload/fragility without proportional portfolio value.

---

## Future v4: Macro Valuation Extension (roadmap only — not implemented)

> Recorded for planning only. No code, data, or fetch is part of this entry.

### Buffett Indicator

**Purpose:** add long-term equity-market **valuation context** to the dashboard.

**Scope:**
- Buffett Indicator = total market capitalization / GDP
- US market cap to GDP
- Japan market cap to GDP (only if reliable data is available)
- Equity valuation regime label + historical valuation context
- **Not a timing signal. Not investment advice.**

**Data source policy:**
- Use only reliable, verifiable public data.
- No API keys in v1.
- If a live source is unstable, use a **manual CSV fallback** (same pattern as JP rates / IMM).
- Do **not** fabricate market-cap or GDP values; manual CSV fallback is acceptable when live data
  is unreliable, but only with verified figures.

**UI:**
- Add to a Macro / Valuation section or a Market Overview view.
- Show as **long-term valuation context** only.
- Do **not** present as trade timing or an entry/exit trigger.

**Disclaimer:** the Buffett Indicator is long-term valuation context only. It is not a trading
signal, a market-timing tool, or investment advice.

---

## Guardrails (all phases)

- yfinance / free sources only; no API keys, no paid APIs.
- Per-symbol `try/except`; a single bad ticker never fails the GitHub Actions run.
- Indicators, charts, yields, curves, Elliott, and edge context are **market context only**.
- No buy/sell/long/short signal values, no order/position/leverage/TP/SL fields, no secrets.
