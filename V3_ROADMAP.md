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

## v4.7 — H1 single-hypothesis (US → JP overnight spillover) / Phase 1.9 (this release)

**Goal:** Phase 1.8 で「素の予測器では edge 無し」と分かった上で、
**仮説駆動** で 1 本だけ素の予測力を測る。今回は H1 のみ:
「前セッションの US ^GSPC 終値リターンが、日本株 (^N225) の翌オーバーナイト方向を
同符号で予測する」。H2..H10 は本フェーズで実装しない (多重検定・無限ビルド防止)。
学習も追加していない (test_no_learning_code が backtest/+collector/ を grep)。

- **`backtest/h1.py` (shipped).** `build_us_close_returns(us_bars)` →
  `build_features(jp_bars, us_returns)` の 2 段組で **特徴量を pre-compute**。
  JP date T に対して `strictly less than` の最大 US date のリターンを引く。
  同日 US (= JST 翌朝確定) は構造的に触れない。predictor は features dict のみ
  受け取り、US 生バーは見ない (型シグネチャ + テスト二重保証)。
- **3 ラベル.** `overnight` / `open_to_close` / `next_week (+5 bars)` を `compute_labels()`
  で計算。各ラベルで hit_rate / Brier / EV 95% CI (bootstrap) / judge を `metrics.summarize`
  経由で算出。EV は `realized = label * sign(feature) * 100` で「純粋な forecast 精度」
  (Phase 1.8 の slip/fee 込み trade EV とは別物)。
- **2 セグメント.** `pre_2023` (~2023-01-01) と `since_2023` で別々に集計。
  BOJ 正常化前後の構造断絶を尊重した分割。
- **サニティチェック.** `_pearson()` で `(US 前日, ラベル)` の相関と t 統計を出し、
  `overnight = r > 0 かつ |t| > 2` を PASS / `open_to_close = |r| < |overnight_r|`
  を PASS とする。両方 PASS しないとデータのタイムゾーンが壊れている疑い。
- **SURVIVAL `#sv-h1` (shipped).** 銘柄/source/セグメント名 + サニティ表 + ラベル
  別メトリクス表を描画。judge は緑 (edge) / 灰 (inconclusive) / 赤 (no-edge) で色分け。
  「単一仮説の素の予測力測定 / not investment advice / Phase 2 未実装」を上部に明示。
- **CLI.** `python3 -m backtest.cli --hypothesis=h1 --source=local`
  で 1 コマンド実走。詳細結果は `data/local/h1/<run>.json` (リポ外)、
  公開抜粋は `docs/data/h1_summary_public.json`。

**Phase 1.9 実測結果 (`^N225` × `^GSPC`, 1965-2026, bootstrap=300):**

| segment      | label         | n      | hit  | Brier | EV 95% CI            | judge        |
|--------------|---------------|--------|------|-------|----------------------|--------------|
| pre_2023     | overnight     | 14,261 | 0.645| 0.238 | [+0.209, +0.233]     | **edge**     |
| pre_2023     | open_to_close | 14,262 | 0.308| 0.272 | [+0.034, +0.064]     | **edge**     |
| pre_2023     | next_week     | 14,262 | 0.504| 0.252 | [-0.015, +0.071]     | inconclusive |
| since_2023   | overnight     |   846  | 0.727| 0.230 | [+0.334, +0.424]     | **edge**     |
| since_2023   | open_to_close |   846  | 0.500| 0.253 | [+0.012, +0.157]     | **edge**     |
| since_2023   | next_week     |   841  | 0.520| 0.251 | [-0.220, +0.250]     | inconclusive |

- **overnight サニティ**: 両セグメント PASS (pre_2023 r=0.43 t=56.7, since_2023 r=0.60 t=21.9)
- **open_to_close サニティ**: 両セグメント PASS (overnight より弱い同符号; pre_2023 r=0.15, since_2023 r=0.22)
- **next_week**: 期待値なし (両セグメントで `|r| < 0.05`, |t| < 1.4)

**判断材料 (Phase 2 着工):** overnight は明確に edge (since_2023 で EV 中央値 +0.38%, hit 73%)。
open_to_close は hit < 50% にも関わらず EV CI 正だが、これは「方向は外すが当たった時の方が
動きが大きい」非対称性を反映 — トレード可能性は別議論 (slip/fee + 約定タイミング)。
Phase 2 で「H1 ベースの予測器を Phase 1.8 の simulator に流す」段階に進む価値あり。

---

## v4.6 — Live-rate walk-forward / Phase 1.8

**Goal:** Phase 1.7 の配線を実レート (data/local/history_*.jsonl, 14万行 / 15銘柄) に
流し、システム単体の想定精度を測る。**自分の実トレード結果は使わない**。
Phase 2 (学習) 着工可否は本フェーズの overall EV CI を見て別途判断。

- **`backtest/local_loader.py` (shipped).** `data/local/` をスキャンし、銘柄ごとに
  時系列整列 / 重複除去 (同 ts は最新で上書き) / 非数値 close 排除 / `min_bars` 未満は
  `excluded[]` に "insufficient_data" マークで分離 (捏造しない)。DuckDB 優先 → 失敗時
  jsonl fallback。
- **`backtest/cli.py --source=local` (shipped).** 銘柄横断で walk-forward + 仮想売買 +
  IS/OOS 並列メトリクスを 1 パスで算出 (per_symbol の trade テープを overall に流して
  計算量半減)。look-ahead は既存 WatchedBars で物理保証。
- **`_classify_judge` (shipped).** OOS CI を `edge / no-edge / inconclusive /
  insufficient` の 4 値に正規化。SURVIVAL `#sv-backtest` は per_symbol 表を緑/灰/赤
  で色分け、overall 較正曲線を SVG (bin n に比例したバブル) で描画。詳細結果は
  `data/local/backtest/<run>_live.json`、公開抜粋は `docs/data/backtest_summary_public.json`。
- **`tests/test_no_learning_code.py` (shipped).** Phase 2 が密かに混ざらない構造保証。
  `backtest/` と `collector/` を grep し、`sklearn / torch / tensorflow / xgboost /
  .fit( / .train( / optimizer. / learning_rate` 等を検知して即 fail。
- **既存予測器の暫定使用 (shipped).** 過去 10 本リターンの符号 → 方向、
  `predicted_prob=0.55` 固定 — 「システム素の精度」のベースラインを測るために
  最も単純な予測器をそのまま使う。これより劣る予測器は Phase 2 でも採用しない方針。
- **GRC.** SURVIVAL の表に「想定精度 / not investment advice / Phase 2 未実装」を
  最上部に明示。`data/local/` (履歴 + backtest 結果) はリポに出ない。

**判断基準 (Phase 2 着工可否).** 実走後 overall OOS EV 95% CI の位置で判断:
- `edge` (CI 全正) → 既存予測器でも edge あり。Phase 2 は予測器強化で伸ばす方向。
- `inconclusive` (CI 0 跨ぎ) → 予測器の入替えが必要。Phase 2 は差替実装が筋。
- `no-edge` (CI 全負) → slip/fee/サイズ設計 or ロジック自体の見直しが先。
- `insufficient` → backfill を延長して bar 数を稼ぐ。

---

## v4.5 — Walk-forward backtest + data backfill / Phase 1.7

**Goal:** ship a structurally-anti-overfit "予測 vs 実レート" harness and the
depth-builder that feeds it, so tomorrow morning we have meaningful out-of-sample
samples. Tonight delivers the wiring; the actual data backfill runs tomorrow.

- **`backtest/walk_forward.py` (shipped).** anchored and rolling modes; mandatory
  purge + embargo (both zero → `ValueError`). `run_fold()` wraps `bars` in a
  `WatchedBars` view that asserts every index ≤ `train_end` — a predictor cannot
  peek at the future without exploding.
- **`backtest/simulator.py` (shipped).** 1-fold virtual execution. Entry/exit
  prices include slippage on both legs; fees are deducted from realized %. Size
  is clamped to `survival.risk_engine.HARD_CAPS["PER_TRADE_PCT_MAX"]=0.5%`; the
  simultaneous-position count is capped at `MAX_CONCURRENT=3`. TP / SL /
  TIMEOUT (40 bars) all fire. Trade log lands in `data/local/backtest/<run>.jsonl`
  (never committed).
- **`backtest/metrics.py` (shipped).** `summarize()` returns hit_rate, Brier with
  Murphy decomposition (`reliability − resolution + uncertainty`), a 10-bin
  calibration table, bootstrap-1000 CI on average net %, and a `judge` field
  that flips to `undetermined` when `N<30` or the CI straddles 0.
  `summarize_pair()` surfaces `in_sample`, `out_of_sample`, and `overfit_gap`
  so the IS-OOS divergence is impossible to hide.
- **`backtest/cli.py --smoke` (shipped).** Generates a deterministic random-walk,
  runs the full pipeline, writes `docs/data/backtest_summary_public.json` for the
  UI. Expected on noise: negative-edge CI, no profit claim from luck.
- **`collector/backfill.py` (shipped).** `python3 -m collector.backfill` downloads
  max-history bars from yfinance for a default watchlist into
  `data/local/history.duckdb` (or per-symbol jsonl fallback when DuckDB isn't
  installed). Idempotent on (symbol, interval, ts). Failures land in
  `errors`; run never aborts. Polite UA via `collector.runtime`. Surfaces
  progress + low-disk WARN at < 20 GB.
- **SURVIVAL `#sv-backtest` and `#sv-backfill` (shipped).** Two client-side
  cards that fetch the public abridged JSONs. Missing files render 「履歴蓄積中」
  so the SURVIVAL tab never breaks before backfill runs.
- **Explicitly out of Phase 1.7 (deferred).** Real-data backtest connection
  (`backtest/cli.py --source=duckdb`), model retraining, win/loss adjudication.

**Tomorrow's runbook:**
1. `python3 -m collector.backfill --period=max --interval=1d` (時間がかかる).
2. Re-run `python3 -m backtest.cli` against real bars (Phase 2 で `--source=duckdb`
   を実装する).
3. Verify `judge=ok` on a watchlist before considering any live position.

---

## v4.4 — Instant notify + tamper-evident log / Phase 1.6

**Goal:** when the engine emits an ENTRY or EXIT verdict, the human gets
notified **the moment it happens** on two independent channels, and every
verdict is written into a chain that cannot be edited after the fact.

- **Two-route delivery (shipped).** `notify/bus.py` ships `send_osascript()`
  (Mac mini local notification via `osascript display notification ... with sound`)
  and `send_ntfy()` (HTTP POST to `https://ntfy.sh/<topic>` with `Title` /
  `Priority` headers, Priority="urgent" for ENTRY, "high" for EXIT_TP/SL).
  Both routes are 100% keyless. ntfy.sh accepts unauthenticated publishes;
  the topic string is the only secret and lives only in `config.local`.
- **Queue + retry (shipped).** When both routes fail, `bus.send_both()` writes
  the row into `data/local/notify_queue.jsonl`. The receiver's next sweep
  calls `bus.flush()` to drain queued rows. `event_id`-based dedup over a
  24h window prevents the same verdict being re-delivered.
- **Append-only hash chain (shipped).** `notify/chain.py` keeps
  `data/local/notifications.jsonl` write-only: `Chain.append()` is the only
  mutator, and its public API exposes no update/delete method (enforced by
  `test_chain_has_no_update_or_delete_api`). Each row carries
  `prev_hash + canonical_json(payload) → sha256 → curr_hash`. `chain.verify()`
  re-reads the file from disk on each call and surfaces the first broken
  index. Tests prove that (a) tampering one row, (b) deleting one row, or
  (c) injecting a forged row all flip `verify()` to False.
- **EXIT pairing enforcement (shipped).** EXIT_TP / EXIT_SL / EXIT_TIMEOUT
  payloads must carry an `entry_ref` matching a prior ENTRY id. Appending an
  EXIT with no ref, an unknown ref, or an already-closed ref raises
  `ValueError`. `Chain.unmatched_entries()` lists ENTRY rows still missing
  their EXIT — the "hide one side" cheat is structurally impossible.
- **Look-ahead is impossible by design (shipped).** `notify/triggers.evaluate(
  bars, t_index, ...)` consumes `bars[:t_index+1]` only. A test wraps `bars`
  in a watcher list that flips a flag whenever an index > `t_index` is read;
  the test would fail if the evaluator ever peeked at the future.
- **Mac mini launchd (shipped).** `scripts/notify_receiver.py` is the launchd
  entry point. `scripts/com.hf.notify.plist` declares `KeepAlive=true`,
  `RunAtLoad=true`, and a 30 s throttle. macOS restarts the daemon if it
  dies; the ntfy route still hits the phone if the Mac mini itself is offline.
- **Public chain view (shipped).** `Chain.export_public()` strips the `price`
  field (judgement timing is public; entry price is private). The SURVIVAL
  tab pane `#sv-notify` fetches `docs/data/notifications_public.jsonl`,
  re-computes the SHA-256 chain in the browser via Web Crypto, and renders a
  red warning banner if anything fails to verify. ENTRY rows without matching
  EXITs are listed as "open positions".
- **GRC.** Every notification body contains `事実記録 / not investment advice`
  (tested in `tests/test_notify_bus.py`). `config.local` and `data/local/` are
  in `.gitignore`; `tests/test_notify_security.py` greps the tracked file set
  for API tokens / ntfy topic leakage and fails the build if any are found.
- **Explicitly out of Phase 1.6 (deferred).** No win/loss adjudication
  (Phase 3), no model training (Phase 2). The receiver records ENTRYs
  generated by `survival.survival_loop.mode_a_positions`; EXIT autogeneration
  from continuous bar feeds is the natural Phase 3 follow-up.

---

## v4.3 — Weekend Autocollect / Phase 1.5

**Goal:** turn the dashboard into a self-running data collector for the weekend.
Push once on Friday, by Monday morning the history directory has fresh samples.
No human action. No learning yet (samples too thin); only the recording boxes.

- **Two extra cron schedules (shipped).** `.github/workflows/collect.yml` adds
  `0 15 * * 4,5,6` (= Fri/Sat/Sun 0:00 JST) and `0 18 * * 0` (= Mon 03:00 JST).
  The existing `update_signals.yml` (daily 00:00 JST) is untouched — the two
  workflows have different `name:` and different commit messages, so the
  GitHub Actions UI shows them as separate jobs.
- **`collector/` package (shipped).** Five focused modules:
  - `collector.runtime` — `retry()` with exponential backoff + jitter,
    `HostRateLimiter` enforcing ≥ 0.4 s between hits to the same host,
    `USER_AGENT` referencing the public repo URL (politeness + traceability).
  - `collector.snapshot` — `extract(data.json dict)` returns an abridged payload
    (data_status counts, money_flow snapshot, survival_loop top-5 candidates +
    mode_a positions) capped at ~6 KB per day; `write_snapshot()` is idempotent
    via a *substantive diff* (everything except `as_of_utc`).
  - `collector.log` — `data/collect_log.jsonl` append-only structured log with
    per-source `ok/failed/ratelimited` counters and a 5-error cap.
  - `collector.cli` — `python -m collector.cli --workflow=collect` is the single
    entry point. A failure inside `fetch_signals.main()` is caught, classified
    by source name, and recorded; the run still emits a snapshot and log row.
- **History store layout (shipped).** `data/history/YYYY-MM-DD.json` per day plus
  `data/history/index.jsonl` (one row per date, ordered, sorted on every write).
  Committed to the repo (visible to anyone), so Phase 2 has a public sample.
- **Phase 2/3 scope freeze.** No model training, no win/loss adjudication. The
  snapshot contract includes a `mode_b_intents: []` placeholder array and a
  `TODO(phase-3)` comment in `collector.snapshot` documenting where the
  discretionary intent intake will hook in. The cross-day P&L adjudication
  follows in Phase 3.
- **GRC.** All sources keyless (yfinance / FRED CSV / fiscaldata / CFTC COT /
  CoinGecko / MoF JGB CSV). No personal balance / P&L in the repo (still in
  `localStorage` + `.gitignore`'d `config.local*`). Disclaimer text unchanged.

---

## v4.2 — SURVIVAL loop / Phase 1

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
