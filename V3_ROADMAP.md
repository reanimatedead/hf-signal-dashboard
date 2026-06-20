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

## v4 — Macro Valuation Extension

### v4.0 — Buffett Indicator  ✅ (manual-CSV path shipped)

**Purpose:** add long-term equity-market **valuation context** to the dashboard.

**Shipped (v4.0):**
- `markets.valuation` + a **Valuation** UI tab (Symbol / Region / Metric / Value / Context / Data /
  Source) with a dedicated detail panel (explanation + value / market_cap / GDP / context / source
  + disclaimer). Charts arrive in v4.1 (below).
- Buffett Indicator = total market capitalization / GDP × 100, for **US** and **Japan**
  (`US_BUFFETT_INDICATOR`, `JP_BUFFETT_INDICATOR`).
- **Manual CSV** path: a verified `data/valuation_metrics.csv`
  (`date,region,metric,market_cap,gdp,value,source,note`; see `docs/sample-valuation-metrics.csv`)
  populates rows (`data_status: manual_csv`, latest dated row per region). `value` = explicit value,
  else `market_cap / gdp × 100`; plausibility `0 < v < 1000`. Without the file, rows stay
  `placeholder` — **no fabricated market-cap or GDP values**.
- `valuation_context` regime labels (`historically_extreme` ≥ 200 / `elevated` ≥ 150 /
  `neutral_to_elevated` ≥ 100 / `moderate` ≥ 70 / `low_valuation` < 70 / `placeholder`) —
  **long-term valuation context, not a timing signal**; no undervalued/overvalued verdicts.
- No API keys, no auto-fetch, per-region `try/except` via the loader; never breaks the workflow.

### v4.1 — Buffett Indicator charts  ✅ (manual-CSV time series shipped)

**Goal:** when the CSV holds a time series, render the long-term valuation history as a chart.

- **Shipped:** a multi-date `data/valuation_metrics.csv` (**≥ 2 dated points** per region) gives the
  region a `charts.1d` — flat OHLC of the value series (`open = high = low = close = value`, capped
  at 120 bars), with BB 48/288 (2σ/3σ) + CCI 48/288 computed on the **full** series (so BB288/CCI288
  show `insufficient_data` until 288 points exist; a short series renders the value line only). The
  shared 1d chart renderer draws it in the Valuation detail panel (clearly captioned as the Buffett
  Indicator value over time — long-term context, not a price or timing signal). 4h/1w stay
  `available:false`. Fewer than two verified points (or no CSV) → `charts.1d.available:false` with an
  explicit note — **no fabricated or single-point line**.
- **Deferred:** same as v4.0 — automated live market-cap / GDP feeds. The chart activates the moment
  a verified multi-date CSV is committed; until then the placeholder fallback shows.

**Deferred (later phase):**
- Automated live market-cap / GDP feeds (World Bank / FRED / official GDP; a reliable total
  market-cap source; Japan via TSE market cap / nominal GDP). v4.x stays manual-CSV until a verified,
  scale-validated live source is confirmed.

**Disclaimer:** the Buffett Indicator (and its chart) is long-term valuation context only. It is not
a trading signal, a market-timing tool, or investment advice.

---

## v4.2 — External data ingestion (no UI/design change)  ✅

**Goal:** move beyond `manual_csv` / `placeholder` "decoration" by wiring at least one **official**
external auto-source, and supply charts for the remaining manual series — **without touching the UI**.

- **CFTC IMM auto-ingestion (shipped):** IMM rows are populated automatically from the official CFTC
  Commitments of Traders report (legacy futures-only) via the public Socrata endpoint
  `publicreporting.cftc.gov` — **no API key**. JPY/EUR/GBP/AUD/CAD/CHF keyed by stable CFTC
  contract-market codes; `net = noncomm long − short`, `data_status: auto_cftc`. Timeout + `try/except`
  → falls back to verified `manual_csv` → `placeholder` (never breaks the run). Feeds the USDJPY edge
  JPY-IMM context factor. `long`/`short` are CFTC categories only, not trade instructions.
- **JP rates auto-ingestion (shipped, v4.3):** JP2Y/JP10Y are auto-ingested from the **official Japan
  Ministry of Finance** JGB historical CSV (`data/jgbcm_all.csv`, daily since 1974, Shift-JIS, **no API
  key**) → `data_status: auto_mof`, with the daily series driving `charts.1d` and the latest row the
  current yield. Japan curve / US-JP 10Y spread compute automatically and the USDJPY edge picks up the
  spread. Timeout + `try/except` falls back to a verified `data/jp_rates.csv` (`manual_csv`) then
  `placeholder` (no fabrication). `fetch_jp_rate_yield_live()` remains a hook for any future live tick.
- **Buffett charts + verified US data (v4.1 + v4.4):** `data/valuation_metrics.csv` now ships a real
  **US** series (301 quarters, 1947→present) from two official **keyless** FRED downloads
  (`fredgraph.csv`): `NCBEILQ027S` (Z.1 nonfinancial corporate equities, $M)→$B ÷ `GDP` (nominal SAAR,
  $B) × 100, matched by quarter. US → `manual_csv` (verified offline import; `source` shows FRED),
  value ≈ 232.7%, `charts.1d` with BB288/CCI288 computed (301-pt series). **Japan stays placeholder**
  (World Bank ratio ends 2020; no current keyless definition-aligned source — no fabrication).
- **No design change:** `docs/index.html`, CSS, layout, tabs, and the detail panel are unchanged —
  the new data/charts flow into the existing renderer. `manual_csv` = verified offline import,
  `placeholder` = intentional no-fabrication fallback.

**Deferred:** a current, definition-aligned **keyless** source for the **Japan** Buffett Indicator
(World Bank GFDD ended 2020; JPX market cap + Cabinet-Office nominal GDP are not cleanly keyless-
alignable). Japan stays placeholder rather than show stale or single-side data. US is shipped (FRED).

---

## v4.1 — Money Flow + UI re-invention  ✅ (this release)

**Goal:** unify scattered macro context into a single "お金の流れ" panel; collapse the
11-tab IA into 8; add a non-interfering background animation layer; remain keyless.

- **Tabs 11 → 8 (shipped).**
  - `rates_vol` = Rates (US 2Y/10Y/30Y + JP 2Y/10Y/30Y) + Volatility (VIX + MOVE).
  - `pos_val` = CFTC IMM + Crypto + Buffett Indicator, sectioned.
  - `moneyflow` = お金の流れ 3-region panel (replaces the legacy Macro / お金の流れ tab).
  - 旧 `volatility / imm / crypto / valuation` の独立タブは廃止 (データは `markets.*` に保持)。
- **New top-level `money_flow.{us,eu,jp}` (shipped).** Keyless 3-region data:
  - US: FRED `WALCL` (weekly), TGA closing balance via fiscaldata (`open_today_bal` fallback,
    daily), FRED `RRPONTSYD` (daily), and `net_liquidity = WALCL - TGA - RRP`. Debt via
    `debt_to_penny` with daily delta. Freshness badge = `daily | weekly | stale`.
  - EU: FRED `ECBASSETSW` (weekly). Govt debt remains `placeholder` (Eurostat quarterly not yet
    keyless-wired). Freshness badge = `weekly | stale`.
  - JP: FRED `JPNASSETS` (monthly). Central-govt debt remains `placeholder`. Badge = `monthly | stale`.
  - 1 ticker failure ⇒ that series only goes to `data_status:"placeholder"` (no fabrication);
    the run continues.
- **`markets.rates` adds `US30Y` (^TYX) + `JP30Y`** from the MoF JGB CSV (30年 column,
  optional; 2Y/10Y unaffected when missing). **`markets.volatility` adds `MOVE` (^MOVE).**
- **Background animation `<canvas id="bg-fx">` (shipped).** Always behind data UI
  (`z-index:0; pointer-events:none; aria-hidden`); three modes (`clean`, `starfield`,
  `constellation`) cycled via header button; 30fps cap, `prefers-reduced-motion` static,
  Page Visibility pause, `devicePixelRatio<=2`, mobile particle halving, resize debounced 150ms.
  Persisted in `localStorage.hf_bg_mode`; default = `clean`. Zero dependencies.
- **Shared particle engine `docs/assets/lib/particles.js` (shipped).** Single module powering
  both the background and the お金の流れ flow fields (Agent A + Agent C share a single rAF /
  ResizeObserver / vis-handler — no double draw, no interference).
- **Minimal i18n (JA / EN) (shipped).** Header toggle, persisted in `localStorage.hf_lang`.
- **Cron 00:00 JST (15:00 UTC) (shipped).** Workflow runs `pytest tests/test_money_flow_schema.py
  tests/test_index_html_contract.py` before push, failing fast on schema regression.

**Deferred:**
- BoJ "営業毎旬報告" 10日次差替 (current monthly FRED series is a stand-in).
- EU/JP central-govt debt live wiring (Eurostat / MoF quarterly).
- `money_flow.*.tilt` (basin allocation per region) — to be ingested from the legacy
  `macro.json` flow block in v4.2.

---

## v4.2 — SURVIVAL loop / Phase 1 (this release)

**Goal:** install a "死なない土台 + 嘘発見器" before any learning loop is built.
External-condition-independent: hard ceilings cannot move with market state.
Zero human input. No learning. Risk in % only.

- **Fixed hard ceilings (no learning).** `survival/risk_engine.py` ships `HARD_CAPS`:
  per-trade risk ≤ 0.5%, DD shrink at -10%, DD stop at -15%, max concurrent positions = 3,
  Kelly fraction = 1/4. Unit tests reject any input that would breach these ceilings.
- **Inverse-vol × 1/4 Kelly position sizing (shipped).** `design_daily_risk()` outputs
  `per_trade_pct` and `position_size_pct` clamped by `HARD_CAPS`. Win probability defaults to
  0.50 in Phase 1 (no history-based estimator yet).
- **Pattern-based exit table (shipped).** `survival/pattern_table.py` keys on
  `(regime ∈ {high_vol, low_vol}) × (distortion ∈ {high, mid, low})`. `daily_update()`
  EWMA-adjusts only the take-profit cell, clamped to `[0.5%, 6%]`. **Stop loss is never
  touched** (asymmetric: missing profit ≠ death; loosening stop = death).
- **Monte Carlo bankruptcy simulator (shipped).** `survival/bankruptcy.py` ships both
  order-dependent MC RoR and the Kaufman/Vince closed-form. Heatmap walks risk options ×
  balance-tier rows. Balance variation only affects the absolute-amount display layer.
- **Edge-score candidate pipeline (shipped).** `survival/edge_score.py` reads each existing
  market row and produces `stretch / positioning_fuel / vol_context / edge_score`.
  Candidates ≥ 55 are surfaced (top 20); ≥ 70 become virtual Mode A entries (machine, ≤ 3).
- **`data.json.survival_loop` (shipped).** Top-level block with `risk_gate`, `auto_risk`,
  `pattern_table`, `candidates`, `mode_a_positions`, `bankruptcy_simulation`. Single ticker /
  single fetch failure degrades to `placeholder`; the run never breaks.
- **SURVIVAL tab is the default (shipped).** First thing a visitor sees is the risk-gate
  banner, auto-risk card, edge candidate table (one-tap "take / skip" buttons writing **only**
  to `localStorage.hf_survival_log_v1`), Mode A virtual positions, pattern table (stop-loss
  column visually marked as fixed), bankruptcy heatmap, client-side aggregates.
- **GRC.** Disclaimer remains on every pane. No execution advice text. `config.local*` is in
  `.gitignore`; the public repo never sees P&L or balances.

**Explicitly out of Phase 1 (deferred):**
- Model weight re-learning, regime auto-switching, win-probability calibration from realized
  results (Brier-based update). These are Phase 2/3 — Phase 1 deliberately freezes them out
  to prevent over-fitting on a thin history.

---

## Guardrails (all phases)

- yfinance / free sources only; no API keys, no paid APIs.
- Per-symbol `try/except`; a single bad ticker never fails the GitHub Actions run.
- Indicators, charts, yields, curves, Elliott, and edge context are **market context only**.
- No buy/sell/long/short signal values, no order/position/leverage/TP/SL fields, no secrets.
- (v4.2 addition) Stop-loss / margin-call / DD ceilings are **fixed**. Daily updates only
  move take-profit. Phase 1 implementations cannot bypass `survival.risk_engine.HARD_CAPS`.
