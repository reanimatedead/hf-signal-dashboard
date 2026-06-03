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

## v3.2 — 4h / 1w charts (deferred)

**Goal:** extend the existing 1d chart to 4h and 1w, incrementally.

- Targets: major FX pairs, VIX, Crypto, US2Y/US10Y.
- Notes: 4h fetching is heavier → restrict via an allowlist. 1w needs long history for BB288.
  Watch `data.json` payload size; consider a separate data file if it grows.

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

## v3.4 — IMM positioning (deferred)

**Goal:** move JPY/EUR/GBP/AUD/CAD/CHF IMM rows from placeholder to real data.

- Start with **manual CSV input**, then consider automated CFTC weekly data.
- `long` / `short` are CFTC positioning categories only — never trade instructions.

---

## v3.5 — Equity charts (deferred)

**Goal:** extend `charts.1d` to the equity tabs.

- All constituents (Nikkei 225 / Dow 30 / Nasdaq 100 / S&P 500) is a large payload.
- Start index-level or watchlist-only; consider allowlist / lazy loading / a separate data file.
  Full per-symbol 120-bar OHLC for 380+ names is likely too heavy for one `data.json`.

---

## Guardrails (all phases)

- yfinance / free sources only; no API keys, no paid APIs.
- Per-symbol `try/except`; a single bad ticker never fails the GitHub Actions run.
- Indicators, charts, yields, curves, Elliott, and edge context are **market context only**.
- No buy/sell/long/short signal values, no order/position/leverage/TP/SL fields, no secrets.
