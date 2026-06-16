# MACRO_INTEGRATION_NOTES.md

> `feat/macro-environment` 棚卸し結果（BUILD_SPEC v4 §A1 ゲート通過用）。
> 推測で固定しない／既存実体に合わせて結線する。

## 1. 既存リポ構造（実体）

```
hf-signal-dashboard/
├── fetch_signals.py              # 既存ピプライン (1864行)。docs/data.json を生成。
├── requirements.txt              # numpy pandas yfinance requests
├── data/
│   └── valuation_metrics.csv     # 既存（Buffett Indicator US/JP, 多日付）
├── docs/                         # ★ Cloudflare 公開ディレクトリ（root: ./docs）
│   ├── index.html                # 既存ダッシュボード（per-symbol タブ・SVGチャート）
│   ├── data.json                 # 既存ダッシュボードデータ（1.2MB）
│   ├── sample-jp-rates.csv       # 形式サンプル（実 jp_rates.csv はライブ取得）
│   ├── sample-imm-positions.csv  # 形式サンプル（実 imm は CFTC ライブ取得）
│   ├── sample-valuation-metrics.csv
│   ├── sample-signals.json
│   └── assets/
│       └── *.png                 # README 用スクリーンショット
├── .github/workflows/
│   └── update_signals.yml        # cron "0 23 * * *" → python fetch_signals.py → docs/data.json コミット＆プッシュ
├── seed/                         # v4 増築用シード（flow.js/app.js/build_data.py/verify.py/verify_render.mjs）
└── BUILD_SPEC_v{2,3,4}.md, CLAUDE.md, DATA_CONTRACT.md, INDEX.md, V3_ROADMAP.md, README.md
```

## 2. fetch_signals.py の構造（変更しない／読むだけ）

- 出力: `docs/data.json`（`OUTPUT_FILE = Path(__file__).parent / "docs" / "data.json"`）。
- 主要関数群:
  - `process_market(NIKKEI225|DOW30|NASDAQ100|SP500)` → equity
  - `process_fx_advanced(FX)` → FX
  - `build_rates_market()` → rates（米=yfinance, 日=MoF JGB CSV scrape `mof.go.jp/jgbs/.../jgbcm_all.csv`、または `data/jp_rates.csv` 手動 → placeholder）
  - `process_volatility()` → VIX（yfinance）
  - `build_imm_market()` → IMM（CFTC Socrata API `publicreporting.cftc.gov/resource/6dca-aqww.json` → `data/imm_positions.csv` 手動 → placeholder）
  - `process_crypto()` → BTC/ETH/SOL/XRP
  - `build_valuation_market()` → Buffett Indicator（`data/valuation_metrics.csv` 必須）
- スケジュール: 08:00 JST 毎日（cron `0 23 * * *` UTC）。`docs/data.json` のみ git commit & push。

## 3. 既存 docs/data.json 内のマクロ素材（再利用 = JP rates / IMM）

これが「既存が既に取得している JP rates / IMM(CFTC)」の実体。**再取得しない**。
直近観測（2026-06-16 ファイル）:

- `markets.rates[*]`: `{ symbol: US2Y|US10Y|JP2Y|JP10Y, yield: float (%), data_status, source, date(JP=None) }`
  - US2Y=3.84%, US10Y=4.469%, JP2Y=1.393%, JP10Y=2.657%
- `markets.imm[*]`: `{ symbol: {JPY|EUR|GBP|AUD|CAD|CHF}_IMM, net_position, weekly_change, positioning_state, crowding_risk, date: YYYY-MM-DD, data_status: auto_cftc }`
  - JPY net=-145818, EUR=13932, GBP=-64213, AUD=18160, CAD=-119999, CHF=-36665（2026-06-09）
- `markets.volatility[0]`: VIX `price: 16.2`（`data_status` 欠損だが `price` 生）
- `markets.valuation[*]`: US/JP Buffett Indicator
- `meta.yield_curve`: `us_10y_2y_spread`, `jp_10y_2y_spread`, `us_jp_10y_spread`（state付き）

**結論**: マクロ層は `docs/data.json` を入力として読み、不足分（FRED系・TGA・暗号オンチェーン・ナウキャスト等）だけ追加取得。これが §A2「gap だけ取得」の実装方針。

## 4. フロント（既存 docs/index.html）のタブ生成方法

- 単一 HTML 内ハードコード。`#tabs` 内の `<button class="tab" onclick="sw('key',this)">…</button>` を 10 個並列（nikkei225, dow30, nasdaq100, sp500, fx, rates, volatility, imm, crypto, valuation）。
- `sw(key, btn)` がアクティブクラス付け替え＋テーブル再描画。
- 既存はテーブル表示一択（`#toolbar` + `.tbl-wrap`）。
- per-symbol SVG チャートは別 `renderChart()` 系（既存テンプレ）。

**Macro タブ増築方針**:
1. `#tabs` の末尾に **追加ボタン1個**（DOM 注入 or 直接 HTML 追記）。
2. `#main` 内に **新規ペイン `#macro-pane`** を追加（display:none で初期化）。
3. Macro クリック時: `#toolbar` と `.tbl-wrap` を display:none、`#macro-pane` を display:block、Canvas を初期化。
4. 他タブクリック時（既存 `sw()`）: 逆動作で復帰。
5. 既存 CSS セレクタは触らない。Macro 用は `.macro-*` プレフィックスで完全分離。

## 5. .github/workflows / Cloudflare

- ワークフロー: `update_signals.yml`（既存・1本のみ）。`fetch_signals.py` → `git add docs/data.json` → push。
- Cloudflare 公開ディレクトリ: `docs/`（既存ダッシュボードの mount root）。
- v4 追加: 後段に macro 計算ステップを足す予定（**今回は CI 変更しない**、ローカル commit までで人手ゲート）。

## 6. 出力配置の決定

- canonical: **`docs/data/macro.json`**（Cloudflare publish root 配下に置かないと本番で fetch 不可）。
- 既存 `.gitignore` は `data/macro.json`（root）を ignore 済み。`docs/data/macro.json` も同様に ignore へ追加し**生成物を git に混入させない**（A0 原則: ストアはバックアップではない／生データ混入なし）。
- 但し、ローカル commit (A5) では一度だけ生成物を含めない＝既存方針通り。

## 7. 環境変数

- `FRED_API_KEY`: 既存リポでは未使用。Macro 層で初参照。**未設定なら `status: "missing"` で正直に**（捏造禁止）。
- 取得時タイムアウト: `socket.setdefaulttimeout(15)` を builder で設定。失敗時も例外を投げず missing で続行。

## 8. 加算のみ（additive-only）の徹底

変更しないもの:
- `fetch_signals.py`、`docs/index.html` の既存タブ・SVG・table 系セレクタ
- `docs/data.json` の既存スキーマ
- `data/valuation_metrics.csv`
- `.github/workflows/update_signals.yml`
- `DATA_CONTRACT.md` の既存節（追記のみ）

追加するもの:
- `pipeline/build_macro.py`（新規）
- `docs/data/macro.json`（生成物・gitignore）
- `docs/assets/macro/flow.js`、`docs/assets/macro/macro.js`（フロント部品）
- `docs/index.html` への最小パッチ: タブボタン1個 + `#macro-pane` + 末尾 `<script src="assets/macro/...">` 2本
- `verify.py`（リポルートに新規・既存ファイルとは別）と `verify_render.mjs`（同）
- `DATA_CONTRACT.md` 末尾に「マクロ環境（macro.json）」節を**追記**
- `MACRO_INTEGRATION_NOTES.md`（このファイル）

## 9. 主要パス一覧（決定済）

| 役割 | パス |
|---|---|
| マクロ入力（既存・再利用） | `docs/data.json` の markets.rates / markets.imm / markets.volatility / meta.yield_curve |
| 既存 Buffett 元データ | `data/valuation_metrics.csv` |
| Macro 出力 | `docs/data/macro.json` |
| Macro ビルダ | `pipeline/build_macro.py` |
| フロント部品 | `docs/assets/macro/flow.js`, `docs/assets/macro/macro.js` |
| ハーネス | `verify.py`, `verify_render.mjs`（リポルート） |
| 公開 URL（本番） | `https://…/data/macro.json`（Cloudflare の docs/ root） |
| 公開 URL（ローカル） | `http://localhost:8000/data/macro.json`（cwd=docs/ で `python3 -m http.server`） |

以上をもって §A1 ゲート通過。
