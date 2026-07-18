# SPEC_MONEYFLOW.md — お金の流れ / IA再構成 / 背景アニメ 設計契約

> 本ファイルは **テストより先にコミットされる**。実装はこの契約に従う。
> テストを書き換えて契約を捻じ曲げない（spec-first）。

---

## 0. 大原則

- **可視化目的**: 相場「環境」の可視化 (not investment advice)。全パネルに明示維持。
- **キーレス**: APIキーをコード/コミット/CIに置かない。FRED は keyless CSV エンドポイント (`fredgraph.csv?id=...`)、財務省データは `fiscaldata.treasury.gov` の公開JSON、yfinance は無認証。
- **捏造禁止**: 取得できない系列は `data_status: "placeholder"` のまま、value は `null`。それ以外の placeholder 値は禁止。
- **配線疎結合**: フロントとバックは `docs/data.json` のスキーマだけで連絡する。
- **5エージェント維持**: 6人目を作らない。背景アニメは Agent A に内包する。

---

## 1. data.json 追加スキーマ (`markets.money_flow` ではなく **トップレベル `money_flow`**)

```jsonc
{
  "meta": { ... },
  "summary": { ... },
  "markets": { ... },
  "money_flow": {
    "as_of": "2026-06-20T00:00:00+00:00",   // 全体パイプライン実行時刻 (UTC)
    "us": <RegionBlock>,
    "eu": <RegionBlock>,
    "jp": <RegionBlock>
  }
}
```

### 1.1 RegionBlock (3地域共通フォーマット)

```jsonc
{
  "region": "us" | "eu" | "jp",
  "cb_assets": {
    "label": "Fed total assets" | "ECB total assets" | "BoJ total assets",
    "value_usd_tn": <number|null>,          // 米=tn USD, 欧=tn EUR(表示はEUR), 日=tn JPY(表示はJPY)
    "unit": "USD_TN" | "EUR_TN" | "JPY_TN",
    "as_of": "YYYY-MM-DD",                  // 系列の最新公表日
    "lag_days": <int>,                      // (today - as_of) 計算
    "data_status": "live" | "weekly" | "monthly" | "stale" | "placeholder",
    "source": "FRED:WALCL" | "FRED:ECBASSETSW" | "FRED:JPNASSETS",
    "wow_change": <number|null>             // 前回公表値からの差 (同単位)
  },
  "tga": <Series|null>,                     // US のみ。EU/JP は null
  "rrp": <Series|null>,                     // US のみ
  "net_liquidity": {                        // US のみ計算 (WALCL - TGA - RRP)。EU/JP は null
    "value_usd_tn": <number|null>,
    "as_of": "YYYY-MM-DD",
    "lag_days": <int>,
    "data_status": "live" | "stale" | "placeholder",
    "components": {"walcl": <num>, "tga": <num>, "rrp": <num>}
  },
  "debt": {
    "label": "US gross national debt" | "EU general govt debt" | "JP central govt debt",
    "value_local_tn": <number|null>,        // 兆 単位、現地通貨
    "unit": "USD_TN" | "EUR_TN" | "JPY_TN",
    "as_of": "YYYY-MM-DD",
    "lag_days": <int>,
    "data_status": "live" | "quarterly" | "stale" | "placeholder",
    "source": "fiscaldata:debt_to_penny" | "placeholder",
    "change_prev_day": <number|null>        // US のみ前日差を出す。EU/JP は null
  },
  "freshness_badge": "daily" | "weekly" | "monthly" | "quarterly" | "stale"
}
```

### 1.2 Series (TGA/RRP)

```jsonc
{
  "label": "Treasury General Account" | "Reverse Repo",
  "value_usd_tn": <number|null>,
  "as_of": "YYYY-MM-DD",
  "lag_days": <int>,
  "data_status": "live" | "stale" | "placeholder",
  "source": "fiscaldata:operating_cash_balance" | "FRED:RRPONTSYD"
}
```

### 1.3 鮮度判定 (`freshness_badge` 集計ルール)

地域の代表系列 (`cb_assets.lag_days` または最も鈍い指標) に基づき:

- US: `cb_assets.lag_days <= 8` → `weekly`、`debt.lag_days <= 2` → `daily`、 `> 30日` → `stale`
- EU: `cb_assets.lag_days <= 12` → `weekly`、`> 60日` → `stale`
- JP: `cb_assets.lag_days <= 35` → `monthly`、`> 90日` → `stale`

代表系列が `placeholder` の場合 `stale` を強制。

---

## 2. 既存スキーマへの追加 (回帰しない条件で)

### 2.1 `markets.rates` に追加

- `US30Y` (region:"US", tenor:"30Y", curve_role:"long_end", source:"yfinance", ticker:"^TYX")
- `JP30Y` (region:"JP", tenor:"30Y", curve_role:"long_end", source:"MoF JGB CSV / auto_mof")

既存 `US2Y/US10Y/JP2Y/JP10Y` は維持。

### 2.2 `markets.volatility` に追加

- `MOVE` (^MOVE, yfinance、失敗時 `data_status: placeholder` で value=null)。

### 2.3 既存タブ UI への影響

- フロントの「金利・債券・VOL」タブで `markets.rates` + `markets.volatility` を縦結合表示する。
- 既存の `cols()` ロジックは `tab="rates_vol"` で `[...C_RATES, ...C_VOL]` 互換のカラム集合を使う(または rates のカラムでVOL行はnull埋め)。

---

## 3. タブ統合 (11 → 8)

| # | tab_id            | 表示 (JA)           | 表示 (EN)            | データソース |
|---|-------------------|--------------------|---------------------|-------------|
| 1 | nikkei225         | 日経 225            | Nikkei 225          | markets.nikkei225 |
| 2 | dow30             | Dow 30              | Dow 30              | markets.dow30 |
| 3 | nasdaq100         | Nasdaq 100          | Nasdaq 100          | markets.nasdaq100 |
| 4 | sp500             | S&P 500             | S&P 500             | markets.sp500 |
| 5 | fx                | FX / 商品           | FX / Commodities    | markets.fx |
| 6 | **rates_vol**     | 金利・債券・VOL      | Rates / Bonds / Vol | markets.rates + markets.volatility |
| 7 | **pos_val**       | ポジション/割安度    | Positioning / Value | markets.imm + markets.crypto + markets.valuation (3セクション) |
| 8 | **moneyflow**     | お金の流れ           | Money Flow          | money_flow.{us,eu,jp} |

- `volatility` / `imm` / `crypto` / `valuation` の独立タブは廃止。データそのものは `markets.*` に残る。
- 旧 `Macro / お金の流れ` タブは `moneyflow` に置換 (canvas+tilesの非破壊増築は撤去 or 内部移植)。

### 3.1 セクション区切り (pos_val / rates_vol)

renderBody で `data-section` 行をテーブル先頭/中央に挿入し、`IMM / Crypto / Valuation` のような subhead を表示する。

---

## 4. 背景アニメ層 (Agent A 内、Agent C と共有モジュール)

### 4.1 配線

- 単一 `<canvas id="bg-fx" aria-hidden="true">` を `<body>` 直下に配置。
  - `position: fixed; inset: 0; pointer-events: none; z-index: 0;`
  - データUI (`#header`, `#sum-bar`, `#tabs`, `#toolbar`, `.tbl-wrap`, `#hf-macro-pane`) は `position: relative; z-index: 1` 以上で前面。
- 共有粒子エンジン `docs/assets/lib/particles.js` を `Agent A` `Agent C` 両方が読み込む。`window.HFParticles` を公開する単一モジュール。

### 4.2 3モード仕様

| モード        | 内容                            | デフォルト |
|---------------|--------------------------------|-----------|
| `clean`       | 静止 (1フレームだけ薄塗りして停止) | ◯ 既定   |
| `starfield`   | 漂う星 (粒子のドリフト)          |           |
| `constellation` | プレクサス (点 + 近接ライン)    |           |
| `aurora` (任意) | 縦オーロラ。実装可だが必須でない |           |

### 4.3 操作

- ヘッダの Dark/Light トグル隣に `BG` トグル (i18n: `背景` / `BG`)。クリックで `clean → starfield → constellation → clean` 循環。
- `localStorage`:
  - `hf_bg_mode`: "clean" | "starfield" | "constellation"
  - `hf_theme`: 既存
- 配色は CSS 変数 (`--accent`, `--text-dim`) を流用 (テーマ非干渉)。

### 4.4 パフォーマンス (全て必須)

- `requestAnimationFrame` 30fps 上限 (前フレームから 33ms 未満ならスキップ)。
- 粒子数 = `Math.floor((width*height) / 25000)` を上限。モバイル(`<768px`) では `0.45` 倍。
- `prefers-reduced-motion: reduce` → 1フレーム静止のみ、`raf` 停止。
- Page Visibility API: `hidden` で停止、 `visible` で再開。
- `devicePixelRatio` は `Math.min(2, dpr)` にクランプ。
- `resize` は 150ms デバウンス。
- 三者依存ゼロ。`canvas 2d` のみ。

### 4.5 干渉防止

- お金の流れタブの「データ駆動粒子」(Agent C) は `#mf-cv-{region}` という別 canvas で動く。`HFParticles` を import して使う。
- 背景 canvas (`#bg-fx`) は常に背面。クリック/ホバーを通さない (`pointer-events: none`)。

---

## 5. お金の流れタブ (Agent C)

### 5.1 レイアウト

- `<section id="mf-pane">` に 3 つの `<article class="mf-region" data-region="us|eu|jp">`。
- 各 region:
  - **借金カウンター行**: 数字ロールで表示。US は前日差 (`change_prev_day`) を緑/赤で。EU/JP は「直近公表 + 経過 XX 日」のみ。
  - **粒子 Canvas (`#mf-cv-{region}`)**: 中央銀行 → 株/金/暗号資産/現金 の流れ。粒子量は `cb_assets.wow_change` の符号と大きさ・もしくは `net_liquidity` の方向に比例。各バスケットに到達% (累積カウントベース) を表示。
  - **鮮度バッジ**: `freshness_badge` を色付きピル。
  - **as_of / source 行**: 小さく明示。
- カラム数: モバイル=1、タブレット=2、デスクトップ=3。

### 5.2 アニメ仕様

- `HFParticles` の `createFlowField()` を使い、`source`→`sinks[]` 構造で構築。
- 描画ライブラリ未使用 (素 Canvas2D)。
- not advice 文言を pane 上部に維持。

### 5.3 借金カウンター

- 0時(JST)起算で1日1回値を取り直す (ページロード時の `as_of` を参照)。
- ロール演出は 1.2 秒以内の小数 tween (粒子と同じ rAF を共有して 30fps 上限)。
- 数値の桁区切りは `Intl.NumberFormat(lang)` で。

---

## 6. CI / テスト (Agent E)

### 6.1 cron 変更

- `.github/workflows/update_signals.yml`: `cron: "0 15 * * *"` (= 00:00 JST)。
- 既存ジョブ列はそのまま、`fetch_signals.py` の中で `money_flow` も生成する。

### 6.2 pytest

- `tests/test_money_flow_schema.py`: `docs/data.json` の `money_flow` ブロックが本 SPEC に従うことを検証。
- `tests/test_smoke_pipeline.py`: `fetch_signals._build_money_flow()` が単体で呼べ、3地域全てに必須キーが存在することを検証 (ネットワーク失敗時は placeholder で埋まる)。

検証項目 (test_money_flow_schema):
- `money_flow.as_of` が ISO 文字列
- `money_flow.us`, `eu`, `jp` 全て存在
- 各 RegionBlock に `cb_assets/debt/freshness_badge` キー
- US だけ `tga/rrp/net_liquidity` が non-null か placeholder で存在
- 任意系列の `data_status` が許可リストに含まれる

### 6.3 README / V3_ROADMAP

- README に「タブ統合 (11→8)」「お金の流れ 3地域」「背景アニメ」のセクションを追加。
- V3_ROADMAP に「v4.1: money_flow + bg-fx」を done として記録、未完項目を deferred として残す。

### 6.4 スモークテスト

- `cd docs && python3 -m http.server 5173` で 8タブ表示・3地域アニメ・カウンター・3モード背景を確認 (手動)。
- E は実証コマンドのログを納品に残す (`ls -la docs/assets/lib/`, `wc -l docs/index.html` 等)。

---

## 7. 受け入れ条件 (PR本文に転写)

(タスク文の §4 全項目をそのまま転記。SPEC遵守の証明としてここに保管。)

- [ ] タブが正確に 8 枚。
- [ ] `money_flow.{us,eu,jp}` が存在、各々 `as_of/lag_days/data_status` 付与。
- [ ] 米国借金=日次+前日比、欧日=直近+経過日数。
- [ ] 3地域 Canvas 粒子アニメ + 到達%、ライブラリ未使用。
- [ ] cron `0 15 * * *`、pytest 緑、1ティッカー失敗で全体落ちず。
- [ ] APIキー無し、placeholder 値捏造無し。
- [ ] 背景 canvas が全データUIの背面・pointer-events無効・aria-hidden、文字/チャート/表に被らない。
- [ ] clean/starfield/constellation 切替 + localStorage 保持、既定 clean。
- [ ] reduced-motion で静止、非表示で停止、モバイルで粒子半減、約 30fps 上限。
- [ ] 既存の 検索/ウォッチリスト/CSV/JA-EN/Dark-Light/SVGチャート 回帰なし。
- [ ] 背景は Agent A、粒子エンジンは A/C 共有 (5エージェント維持)。

---

## 8. 相関パネル (correlations) + sink_metrics 拡張 (feat/corr-panel)

> 本セクションは §0-7 (v4.1 money_flow / IA再構成) の後続拡張。既存スキーマは
> 無改変で、`correlations` トップレベルキーの新設と `money_flow.<region>` への
> `sink_metrics` 追記のみを行う。取得は `pipeline/corr_sources.py`、計算・マージは
> `pipeline/build_corr.py` が担う。両ファイルとも `fetch_signals.py` とは独立。

### 8.1 `correlations` トップレベルスキーマ

```jsonc
{
  "correlations": {
    "as_of": "2026-07-16T00:00:00+00:00",   // 結合後の最新観測日 (データ駆動。wall-clock禁止)
    "window": { "long": 60, "short": 20 },   // 営業日
    "n_obs": 187,                            // 10系列共通日 inner join 後の行数
    "matrix_60d": [[...10x10...]],           // 直近60営業日(不足時は使える分だけ)
    "matrix_20d": [[...10x10...]],           // 直近20営業日
    "labels": [
      "N225", "SPX", "US5Y", "US10Y", "US30Y",
      "JGB5Y", "JGB10Y", "JGB30Y", "USDJPY", "US-JP10Yspread"
    ],
    "key_pairs": [
      { "pair": ["N225", "USDJPY"], "series_60d": [{"date": "YYYY-MM-DD", "r": 0.1234}, ...] },
      { "pair": ["SPX", "US10Y"],   "series_60d": [...] },
      { "pair": ["USDJPY", "US-JP10Yspread"], "series_60d": [...] }
    ],
    "data_status": "live",                   // "live" | "stale" | "placeholder"
    "lag_days": 1,                            // 実行日 - 最新観測日 (暦日)。実行日依存で変動してよい
    "sources": ["yfinance", "FRED:fredgraph", "MOF:jgbcm"],
    "method": "log-returns (equity/FX) and bp-changes (yields), inner join (no forward fill), Pearson rolling 60/20 business days",
    "note": "For data visualization purposes only. Not investment advice."
  }
}
```

- `labels` は上記10本で**順序固定**。`matrix_60d`/`matrix_20d` の行列インデックスは
  この順序に対応する(順序が変わるとフロントの対応表が壊れる)。
- `matrix_60d` / `matrix_20d` は共に 10×10。対角はデータがあれば `1.0`、
  データなし列は `null`。値域は `[-1.0, 1.0]` (丸め4桁)。
- `key_pairs` は3組固定 (`N225×USDJPY`, `SPX×US10Y`, `USDJPY×US-JP10Yspread`)。
  各ペアの `series_60d` は直近250営業日分のローリング60日相関の時系列。
- `data_status` enum: `live`(全系列生存・lag正常) / `stale`(一部欠損 or lag>7暦日) /
  `placeholder`(共通観測数 `n_obs` が `window.long` 未満で行列計算不能)。
- `as_of` は**データ駆動**(結合後系列の最新観測日)であり、パイプライン実行時刻
  (wall-clock) を埋め込んではならない。同一入力からは同一 `as_of` が出る
  (決定論)。`lag_days` のみ実行日依存で変動してよい。

### 8.2 計算契約 (禁止事項含む)

- **水準相関の禁止**: 価格・利回りの生値(水準)同士の相関は見せかけの相関
  (spurious correlation) になりやすいため計算に使わない。必ず「変化系列」に
  変換してから相関を取る。
  - 株価指数・為替 (`N225`, `SPX`, `USDJPY`): 対数リターン `ln(P_t / P_{t-1})`。
  - 利回り系列 (`US5Y/10Y/30Y`, `JGB5Y/10Y/30Y`): bp変化幅
    `(y_t - y_{t-1}) * 100`。
  - 派生系列 `US-JP10Yspread`: まず水準 `DGS10 - JGB10Y` を構築し、その
    スプレッド自体の日次bp変化を相関計算に使う。
- **inner join**: 変化系列同士は、両方に値がある日のみで結合する。**前方補完
  (ffill) は一切行わない**(休場日のズレをごまかさない)。
- **未確定バー除外**: yfinance由来の全系列から「今日(UTC) または 今日(JST)」
  日付の観測を計算前に除外する(`correlations` と `sink_metrics` 両方の入力に
  適用)。同一暦日内の再実行はバイト同一(決定論)になり、新しい確定バーが
  増えた時だけ差分が出る。
- ローリング窓: `long=60`営業日, `short=20`営業日。

### 8.3 `sink_metrics` スキーマ (`money_flow.<region>.sink_metrics`)

```jsonc
{
  "money_flow": {
    "us": {
      "...": "既存 v4.1 RegionBlock フィールドは無改変",
      "sink_metrics": {
        "label_type": "weekly_change",
        "as_of": "2026-07-16",
        "stocks": { "symbol": "^GSPC",     "wow_pct": 1.23, "as_of": "2026-07-16", "data_status": "live" },
        "gold":   { "symbol": "GC=F",      "wow_pct": -0.45, "as_of": "2026-07-16", "data_status": "live" },
        "crypto": { "symbol": "BTC-USD",   "wow_pct": 3.10, "as_of": "2026-07-16", "data_status": "live" },
        "cash":   { "symbol": "DX-Y.NYB",  "wow_pct": 0.02, "as_of": "2026-07-16", "data_status": "live" },
        "note": "Weekly % change of representative series. Particle arrival % is a visual effect, not measured flow."
      }
    },
    "eu": { "...": "sink_metrics 同型 (symbols: ^STOXX50E / GC=F / BTC-USD / EURUSD=X)" },
    "jp": { "...": "sink_metrics 同型 (symbols: ^N225 / GC=F / BTC-USD / JPY=X)" }
  }
}
```

- **「シェア×総資産」による額の捏造禁止**: 中央銀行総資産等に「シンク別配分比率」
  を掛けて流入額を偽装しない。`sink_metrics` は各シンク代表系列の
  **週次変化%のみ**(`(直近終値 / 「最新日-7暦日以前で最も近い日」の終値 - 1) * 100`)。
- `label_type` は **`"weekly_change"` に固定**。フロントはこれを額ではなく
  「週次変化」として表示する。
- 粒子アニメーションの「到達%」は演出値であり、実測フローではない
  (`note` 文言 `"Particle arrival % is a visual effect, not measured flow."`
  として明文化。§4/§5 のアニメ仕様と矛盾しない)。
- `wow_pct` が `null` の場合、`data_status` は必ず `"placeholder"` (捏造禁止の
  原則を §0 から継承)。

### 8.4 更新スケジュール

- `.github/workflows/corr.yml` (新設): cron 2本。
  - `30 22 * * 0-4` (UTC) = **07:30 JST 月-金**: 米国クローズ + FRED反映後。
  - `0 2 * * 1-5` (UTC) = **11:00 JST 月-金**: 財務省JGB利回り公表後。
  - `workflow_dispatch` で手動実行可。
  - 実行内容: `python3 pipeline/build_corr.py` → pytest 契約ゲート →
    無変化ガード (`git diff --cached --quiet` で空コミット防止) → push。
  - 元データ(株価指数・利回り・為替)が**日次更新**のため、3時間毎などの
    高頻度実行は不採用。更新間隔を変える場合は cron 行の変更のみで済む。
- **既存2ワークフローへの再マージ注入**: `fetch_signals.py` (`update_signals.yml`)
  および `collector.cli --workflow=collect` (`collect.yml`) は `docs/data.json`
  を全再構築するため、そのままでは `correlations` / `sink_metrics` が消える。
  両ワークフローの本体ステップ直後に `python3 pipeline/build_corr.py` を
  再マージステップとして挿入し、消失を防ぐ(`fetch_signals.py` 自体は
  編集禁止のため、後段の再マージで対応する)。

### 8.5 `verify.py` 新設ゲート (8件)

| ゲート名 | 検証内容 |
|---|---|
| `gate_corr_schema` | `correlations` の必須キー・`labels` 順序10本固定・`data_status` enum・`key_pairs` 3組 |
| `gate_corr_matrix` | `matrix_60d`/`matrix_20d` が共に10×10・対称性・対角・値域 `[-1,1]` |
| `gate_corr_level_misuse` | 水準相関の誤実装を検出(bp変化なら起きない高相関パターンの検知) |
| `gate_corr_era` | `pipeline.corr_sources.era_to_iso` の単体テスト(和暦→ISO変換) |
| `gate_corr_nobs` | `n_obs >= window.long`。未達なら `data_status == "placeholder"` を要求 |
| `gate_corr_determinism` | `as_of` が wall-clock 由来でない(過去営業日) + 相関値が小数4桁丸め |
| `gate_corr_selftest` | 水準相関検出ロジック自体の自己テスト(合成データ・シード固定・オフライン) |
| `gate_sink_metrics` | `money_flow.<region>.sink_metrics` の契約(`label_type`, `note`, symbol一致, `wow_pct`/`data_status` 整合) |

既存ゲート (Gate-1〜Gate-10, Gate-1c, Gate-1d) は無改変。上記8件はそれに
追加される形で `verify.py` の末尾に実装されている。
