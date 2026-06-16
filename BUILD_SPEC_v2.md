# BUILD_SPEC.md v2 — HF Signal Dashboard 設計図（Claude Code 投入用・単一ファイル完結）

> リポジトリ: github.com/reanimatedead/hf-signal-dashboard
> 性格: 日次〜週次のマクロ「環境」可視化ダッシュボード。**売買助言ではない**。
> 実行モデル: 5エージェント → 単一指示で「確認→実行→検証→ローカルcommit→（人手ゲート）push→報告」。
> 重要: **ユーザーのチェックは全完成後に1回のみ**。本仕様は自己完結し、Claude自身が自己点検ハーネスで合否を機械判定する。**完了報告にはハーネスの実出力を必ず添付。出力なき「完了」は無効（虚偽報告防止）。**
> 実行環境: 対話モードのClaude Code（`claude -p`ヘッドレスは使わない）。M1 Mac。無料データのみ。
> **v2変更点: ローカル永続ストア層を追加（最大250GB・リポジトリ外・Parquet主体・追記専用・容量ガード）。**

---

## 0. ゴールと非ゴール

### ゴール（このビルドで完成させる範囲＝Phase 1–3）
1. 既存の静的HTML構成（Python pipeline → `data.json` → 静的HTML+JS、GitHub Actions夜間、Cloudflare Pages、非公開エンジンは`DATA_CONTRACT.md`方式）を踏襲。
2. **ローカル永続ストア層**を新設し、取得データの長期履歴を自前保持（FRED3年窓問題等への耐性）。
3. **「お金の流れ」をCanvasアニメーションで可視化**（ヒーロー要素）。中央銀行→4つの器へ、流動性・景気局面・金利・フローで水（お金）が動く。`data.json`駆動。
4. 下記タイルを段階的に実装。各タイルは値・zスコア・色・**説明書き**・**注意（caveat）**・as_of・status を必ず表示。
5. 自己点検ハーネス（`verify.py` + ヘッドレス描画チェック）で全工程を機械判定。

### 非ゴール（明確に作らない）
- 数分以下/HFTフィード、自動執行。
- ブラックボックスの単一「後退/クラッシュ確率」スコア。
- **Citi エコノミック・サプライズ指数（有料/独自）**＝除外。
- **65か月サイクルを“タイミング”として使う表示**＝除外（文脈注記のみ可）。
- **Bloomberg Terminal / MOVE日中 / GS・Bloomberg FCI など有料データ依存**＝除外。
- 相関から因果を匂わせる表示。センチメント/ブレッドスを単独シグナル扱いすること。

---

## 1. アーキテクチャ（v2: ローカルストア層を追加）

```
                         ┌──────────────────────────────────────────┐
[無料データ源] --A1収集--> │ ~/hf-data-store/   (リポジトリ外・Git管理外) │
                         │   raw/YYYY-MM-DD/source.json.gz  (生・追記)  │
                         │   ts/<series>.parquet            (時系列・追記) │
                         │   pit/<series>.parquet           (改定前後/PIT) │
                         └──────────────────────────────────────────┘
                                        │ A2計算（zスコア等の土台に使う）
                                        ▼
[非公開エンジン(private)] --A2--> public/data.json   (← DATA_CONTRACT準拠・計算済みのみ)
[公開フロント(static)]    --A4--> public/index.html (+ app.js, flow.js)  ← data.json を読むだけ
[検証]                    --A3/A5--> verify.py, verify_render.mjs (ハーネス)
[配信] GitHub Actions(夜間) → Cloudflare Pages
```

- 公開層は計算しない。**`data.json`を読んで描画するだけ**。重い計算・生データ・履歴はローカルストア＋非公開エンジン側。
- **ローカルストアは非公開側のみ**。公開`data.json`には自前計算済みの値だけ載せる（生データ再配布しない）。J-Qu, NCEr等のライセンス制限データはストアに置いてもよいが**公開しない**。
- ブラウザの`localStorage`/`sessionStorage`は使わない（状態はJS変数のみ）。

---

## 1.5 ローカル永続ストア層（v2新設・最大250GB）

### 配置とポリシー
- 置き場所: **`~/hf-data-store/`（A方式: リポジトリ外・Git管理外）**。リポジトリは汚さない。
- 上限: **250GB**（512GB中の許可枠）。`verify.py`の容量ゲートで監視。
- 役割:
  1. **FREDの直近3年ローリング窓**（HY OAS `BAMLH0A0HYM2`, IG `BAMLC0A0CM` 等）を超える**長期履歴を自前保持**。窓が縮んでもストアの履歴でzスコア/将来のバックテストが組める。
  2. zスコア用の3〜5年ローリングの土台。
  3. API障害時のフォールバック（取得失敗でも直近ストア値で描画継続可。ただし`status:"stale"`明示）。
  4. 改定系列のポイントインタイム（PIT）保持。

### 形式
- 時系列: **Parquet**（列指向・圧縮効率が高くM1で軽い）。`ts/<series>.parquet`。
- 生APIレスポンス: 日付別 gzip JSON `raw/YYYY-MM-DD/<source>.json.gz`（監査・再計算用）。
- 改定系列（GDP/Sahm/TIC/バランスシート等）: `pit/<series>.parquet` に**改定前後を両方保持**（最新値=最終値にしない方針の実装）。

### 追記専用（append-only）＋スナップショット
- 既存履歴は上書きせず**追記**。同一日付の再取得は新リビジョンとして`vintage`列に記録（破壊しない）。
- 破壊的整理（古い生JSONの圧縮/間引き）は**人手ゲート**（容量超過時のみA5が提案、削除は確認後）。

### 容量見積り（参考）
- 時系列Parquet主体なら全系列でも**数百MB〜数GB規模**。生JSONを無圧縮で貯め続けない限り250GBは桁違いに余る。容量枠は「履歴の安全弁」と割り切る。

---

## 2. 5エージェント構成（役割・並列性・引き継ぎゲート）

> 単一指示原則: 1つの指示で全工程を完走。**破壊的操作とpushのみ人手ゲート**。

| ID | 名称 | 責務 | 依存 | 終了ゲート |
|----|------|------|------|-----------|
| **A1** | データ収集 | 全無料ソースを取得→**ローカルストアへ追記**（`raw/`生gzip＋`ts/`Parquet）。単位整合（百万vs十億）・robots.txt・freshness検証・ライセンス制限データは非公開のみ。サブ取得は**並列**。 | なし | 各ソース非空＋鮮度OK＋ストア追記成功 |
| **A2** | 指標計算 | **ストアの長期履歴**からzスコア(3–5年ローリング)、景気局面(GDPNow+ナウキャスト)、ネット流動性、各比率、色ルール、アニメ用basin_tilt/currentsを計算し`data.json`生成。 | A1 | schema検証通過 |
| **A3** | 検証(ハーネス) | gate-0ファイル存在→**ストア健全性/容量**→schema→単位健全性→鮮度→欠損の正直さ→zスコア健全性→説明/注意の存在→除外厳守。**機械PASS/FAILを出力**。 | A1,A2 | `verify.py`がPASS |
| **A4** | フロント生成 | 静的HTML+Canvasお金の流れアニメ(data.json駆動)+各タイル(値/z/色/説明書き/caveat/as_of/status)。ダークSOCテーマ。ヘッドレス描画チェック。 | A2 | 描画チェックPASS |
| **A5** | レビュー/統合 | 看板倒れ防止(全タイルにcaveat+as_of+status)・GRC文言("not advice")・除外厳守・レジーム崩れ注記・**ハーネス全体再実行**→ローカルcommit→**push手前で停止(人手ゲート)**→完了報告(ハーネス実出力添付)。容量超過時は整理を提案（削除は人手ゲート）。 | A1–A4 | 報告提出・push待ち |

並列指針: A1のソース別フェッチは並列。A2はA1完了後。A3はA1+A2を検証。A4はA2(data.json)完了後。A5は全体。

---

## 3. データ契約（`public/data.json` スキーマ）

```jsonc
{
  "meta": {
    "generated_at": "ISO8601",
    "pipeline_version": "string",
    "sources_as_of": { "fred": "ISO", "cot": "ISO", "jpx": "ISO", "crypto": "ISO" },
    "store": { "path": "~/hf-data-store", "used_gb": 0.0, "limit_gb": 250 }
  },

  // === お金の流れアニメーション駆動データ ===
  "flow": {
    "net_liquidity": { "value_usd_tn": 0.0, "wow_change_tn": 0.0, "z": 0.0, "trend": "expand|contract" },
    "clock_phase": "reflation|recovery|overheat|stagflation",
    "policy_rate_friction": 0.0,            // 0..1 実質政策金利由来。高いほど現金へ
    "basin_tilt": { "stocks": 0.0, "gold": 0.0, "oil": 0.0, "cash": 0.0 }, // 合計1
    "currents": {                            // 流れの向き・強さ(-1..1)
      "foreign_jp_flow_z": 0.0,              // 海外投資家フロー
      "cot_jpy_z": 0.0,                      // 円投機ポジション
      "risk_off": 0.0                        // HY+VIX合成。+で現金へ吸引
    }
  },

  // === タイル ===
  "tiles": {
    "<tile_id>": {
      "label": "string",
      "value": 0.0, "unit": "string",
      "z": 0.0,
      "color": "green|amber|red|neutral",
      "as_of": "ISO", "lag_days": 0,
      "status": "ok|stale|missing",
      "source": "live|store_fallback",       // v2: ストアからのフォールバック明示
      "explain": "説明書き(小学生でも分かる平易さ)",
      "caveat": "信頼度の注意。レジーム崩れがあれば明記"
    }
  }
}
```

ルール:
- 取得不能→`status:"missing"`、鮮度超過→`status:"stale"`。**勝手に前回値で“新鮮”を装わない**（虚偽防止）。ストアの直近値で描画継続する場合は`status:"stale"`＋`source:"store_fallback"`を必ず立てる。
- 色: 4週変化方向で着色（絶対水準ではなく変化）。z正常域=neutral、極端=色付け。
- `explain`/`caveat`は必須。空ならA3でFAIL（看板倒れ防止）。

---

## 4. タイル仕様一覧（Phase順 / 除外済み）

> 各列: id / 式 / 無料データ源(系列ID・API) / 頻度・遅延 / 説明書き / 色ルール / zスコア / caveat。zスコアは原則**ローカルストアの長期履歴**で算定（FRED窓に依存しない）。

### Phase 1（建玉直結・最優先・アニメのコア）

| id | 式 | 源(ID/API) | 頻度/遅延 | 説明書き | 色 | z | caveat |
|----|----|-----------|-----------|---------|----|---|--------|
| `net_liquidity` | WALCL−TGA−RRP | FRED `WALCL`/`WTREGEN`(or 財務省Fiscal Data日次TGA `…/operating_cash_balance`)/`RRPONTSYD` | 週/日・1日 | 「市場で実際に使えるドルの総量。増=追い風、減=逆風。」 | 4週変化 | ストア長期 | 代理指標。**単位:WALCL/TGAは百万・RRPは十億→揃える**。構成で誤誘導しうる |
| `usdjpy_carry` | Fed中央値−BOJ政策金利、+ドル円 | FRED `DEXJPUS`,`DFEDTARU/L`,BOJ | 日 | 「日米金利差。差が縮むと円高→キャリー巻き戻し→世界的リスクオフ。」 | 差の縮小で警戒色 | 差のz | 条件で引き金でない。2024/8/5 日経−12.40%の前提 |
| `cot_jpy` | CFTC COT 円先物 非商業ネット | CFTC COT(週) | 週/3日 | 「投機筋の円売り/買い越し。極端な円売りは巻き戻しの燃料。」 | 極端で色 | ネットのz | 既存COT取り込みにJPY契約コード追加のみ |
| `real_yield_usd` | DFII10、DTWEXBGS | FRED `DFII10`,`DTWEXBGS` | 日 | 「実質金利が下がると金の魅力増。広義ドル(26通貨)はDXYより正確。」 | 変化方向 | 各z | **2022年以降 金vs実質金利は崩れた→注記必須** |
| `foreign_jp_flow` | 海外投資家 現物 週間ネット(累積+4週) | JPX 投資部門別売買状況 週間 | 週 | 「日本株を動かす主役=海外投資家の売買。売り越し転換は日本株安(ショート追い風)。」 | 売り越しで色 | ネットのz | 週次で遅い。確認用 |
| `jp_short_feasibility` | 個別: 貸借銘柄?/逆日歩/一般信用在庫/空売り比率 | JSF(品貸料率・申込停止 日次)、JPX(個別信用残・空売り集計) | 日/週 | 「空売りの可否と借株コスト。逆日歩は予測不能で青天井のテールリスク。」 | 逆日歩発生/停止で警戒 | — | ショートシグナルには必ず併記 |

### Phase 2（リスクオフ/過熱の文脈）

| id | 式 | 源 | 頻度/遅延 | 説明書き | caveat |
|----|----|----|-----------|---------|--------|
| `hy_spread` | ICE BofA US HY OAS | FRED `BAMLH0A0HYM2`(+IG `BAMLC0A0CM`) | 日 | 「低格付け社債と国債の利回り差。広がる=信用不安=リスクオフ。株安に先行しやすい。」 | **FRED3年窓→ストアに自前保存**。水準より“広がる速さ” |
| `vol_regime` | VIX, VIX3M/VIX, SKEW, NFCI | Yahoo `^VIX`,`^VIX3M`,`^VIX9D`,`^SKEW`; FRED `NFCI` | 日/週 | 「VIX=株の恐怖、SKEW=暴落保険料。VIX>VIX3M(逆転)はストレス。NFCI+は引き締め。」 | VIXは同時的で予測でない |
| `crypto_position` | ファンディング率, OI, 清算, 現物BTC ETFフロー | CoinGlass(無料), Farside, CoinGecko | 日/8h | 「ファンディング高=ロング過熱。OI急増+清算連鎖=ボラ急騰。ETFフロー=機関の出入り。」 | レジーム依存 |
| `btc_onchain` | MVRV-Z, NUPL | Glassnode無料 | 日 | 「サイクルの過熱/底の目安。NUPL>0.75陶酔、MVRV-Z<0底圏。中期文脈であり短期タイミングでない。」 | 中期のみ |
| `metals_context` | 金/銀比, COT(金銀), GLD/SLV残高, COMEX在庫 | 価格, CFTC COT, 発行体, CME | 日/週 | 「金/銀比=恐怖と実需。ETF残高=紙の需要、COMEX在庫=現物。価格上昇が残高増を伴うか。」 | 確認用 |

### Phase 3（マクロ背景・心理 / 既存格上げ）

| id | 式 | 源 | 頻度/遅延 | 説明書き | caveat |
|----|----|----|-----------|---------|--------|
| `clock_phase` | GDPNow+インフレナウキャストで4象限判定 | Atlanta Fed GDPNow, Cleveland Fed Inflation Nowcasting(無料) | ほぼ即時 | 「景気局面(リフレ/回復/過熱/スタグ)。ナウキャストで“今”を判定し、お金がどの器に傾くかを決める。」 | モデル推計・改定あり。時計は逆行/飛ばしあり |
| `yield_curve` | T10Y3M, T10Y2Y, Sahm | FRED `T10Y3M`,`T10Y2Y`,`SAHMREALTIME` | 日/月 | 「長短金利の逆転は後退の先行サイン。Sahmは後退の初期検知。」 | 先行が6–24か月と長く可変。Sahmは今サイクル過大警告リスク |
| `breadth` | %>200dMA, A/D, 新高値−新安値 | 無料株価から自前計算(ストア蓄積) | 日 | 「指数の“中身”。多数が上昇=健全、少数主力のみ=脆い。」 | 単独シグナル不可。確認用 |
| `sentiment` | AAII強気−弱気, Fear&Greed, Put-Call | AAII(週), CNN(日,APIなし=注意), CBOE Put-Call(日) | 日/週 | 「心理の極端は反転に先行。楽観過剰=調整に弱い、悲観ピーク=底に近い。」 | 強トレンドでは行き過ぎが続く。確認用 |
| `margin_debt` | 米FINRA(YoY), 日本信用倍率(買残÷売残) | FINRA(月,DL/APIなし), JPX信用取引現在高(週) | 月/週 | 「株を買うための借金残高=レバレッジ過熱度。水準より前年比で見る。」 | 株価と連動し増える。先行性は弱い |
| `stablecoin` | 総時価総額, USDT/USDCペグ, 準備健全性 | DefiLlama, CoinGecko | 日 | 「ステーブルコインは米短期国債の新たな買い手。発行量増=暗号資産の流動性。デペッグ監視。」 | Tetherは完全監査なし(アテステーションのみ) |

### Phase 4（任意・今回は対象外、フラグのみ）
季節性 / Baltic Dry / 地域プレミアム / インサイダー / グローバル流動性プロキシ（PBOC弱点）。**今回は実装しない**（スコープ固定）。

---

## 5. お金の流れアニメーション仕様（`flow.js` / Canvas 2D）

- 既存の概念試作 `liquidity-flow-dashboard.html` のCanvas粒子系をベースに、**`data.json.flow`駆動**へ改造。
- 構成: 上部に中央銀行(ポンプ)。下に4つの器=**株/金/原油/現金**。粒子=水(お金)。
  - ※建玉どおり「日本株/金/銀/BTC」に変えたい場合は§3 `basin_tilt`キーと本節ラベルを差し替え（投入前に1点だけ編集）。
- 駆動マッピング:
  - `net_liquidity.trend=expand`→中央銀行が粒子を供給、`contract`→器から吸い戻し。供給量∝`|wow_change_tn|`。
  - `basin_tilt`→各器へ向かう粒子の配分（景気局面で決まる）。
  - `policy_rate_friction`→現金の器への摩擦上乗せ（高金利=現金へ逃げる）。
  - `currents.foreign_jp_flow_z` / `cot_jpy_z`→株の器への流入/流出の矢印強度（海外勢売り越し/円売り過熱で流出方向）。
  - `currents.risk_off`(+)→全器から現金へ吸引（HY拡大・VIX急騰で発火）。
- 表示: 各器の水位%、中央銀行の供給↑/吸収↓、凡例。M1で軽量に動く純Canvas（three.js等の重い3Dは不可）。
- ラベル: 「概念可視化 / 売買助言ではない」を常時表示。

---

## 6. 自己点検ハーネス（`verify.py` + `verify_render.mjs`）

> A3が主実行、A5が全体再実行。**PASS/FAILを標準出力にJSONで吐く。完了報告にこの実出力を貼る。**

### 6.1 `verify.py`（データ/契約/ストアの機械検証）
順にゲートを通す。1つでもFAILなら以降中断し、FAIL理由を出力:

1. **Gate-0 ファイル存在**: `public/data.json`,`public/index.html`,`public/app.js`,`public/flow.js`,`verify.py`,`verify_render.mjs` が実在。（存在しないのに「完了」と言わない）
2. **ストア健全性/容量(v2)**: `~/hf-data-store/` が存在し書込可。**使用量 < 250GB**（超過はFAIL→整理提案、削除は人手ゲート）。`ts/*.parquet`が読込可・主要系列が非空・最終日付が期待ラグ内。
3. **Schema検証**: `data.json`が§3契約に一致（必須キー・型）。`flow.basin_tilt`合計≈1.0。`meta.store.used_gb`を記録。
4. **単位健全性**: `net_liquidity.value_usd_tn` が 0〜20 兆ドルの常識域（百万/十億の混在を検出）。
5. **鮮度**: 各`tiles.*.as_of`が期待ラグ内（例: FRED系≤7日、COT≤10日、JPX週次≤14日）。超過は`status:"stale"`であること（黙って新鮮を装わない）。ストア代替時は`source:"store_fallback"`。
6. **欠損の正直さ**: 取得不能ソースは`status:"missing"`かつ`value`を捏造していない。
7. **z健全性**: 各`z`が有限・|z|≤6（外れ値検出）。zはストア長期履歴で算定されている。
8. **説明・注意の存在**: 全`tiles.*.explain`と`caveat`が非空。
9. **レジーム注記**: `real_yield_usd`,`btc_onchain`等のcaveatに崩れ注記を含む。
10. **除外厳守**: data.jsonにCSEI/65か月/有料系のキーが無い。

出力例:
```json
{"harness":"verify.py","result":"PASS|FAIL","store_used_gb":12.3,"gates":{"gate0_files":"PASS","store":"PASS",...},"failed":[...],"generated_at":"ISO"}
```

### 6.2 `verify_render.mjs`（描画の機械検証 / ヘッドレス）
- ヘッドレスブラウザで`public/index.html`を開く。
- JSコンソールエラー0件。
- `data.json`を読み込み、全タイルDOMが値/説明書き/caveat/as_of/statusを描画。`store_fallback`は視覚的に明示。
- Canvasアニメが初期化し、粒子が生成され`flow`値に反応（少なくとも1フレーム進行）。
- 「売買助言ではない」文言がDOMに存在。
- PASS/FAILをJSON出力。

### 6.3 反虚偽報告ルール（必須）
- 「完了」と書く前に **6.1と6.2を実行し、その実出力をそのまま報告に貼る**。
- いずれかFAILなら「完了」と書かない。原因と次手を報告。
- 出力を伴わない主観的「できました」は無効。

---

## 7. 実行ワークフロー（単一指示）

```
確認 → 実行(A1→A2→A3→A4→A5・A1内は並列・A1はストアへ追記) → 検証(6.1+6.2をPASSまで) 
     → ローカルcommit(意味のある単位・ストアはGit管理外) → [人手ゲート] push → 報告(ハーネス実出力添付)
```

- **破壊的操作（既存ファイル削除/上書き・履歴改変・ストアの間引き削除）とpushは人手ゲート**。それ以外は自走。
- ヘッドレス`-p`は使わず対話モードで実行。
- 途中失敗は中断し、Gate-0から状態を再確認してから再開。

---

## 8. 受け入れ基準（ユーザーが完成後に確認する観点）

- [ ] `verify.py` が `result:"PASS"`（実出力が報告に添付・`store_used_gb`が250未満）。
- [ ] `verify_render.mjs` が `result:"PASS"`。
- [ ] `~/hf-data-store/` に `ts/*.parquet` 等が蓄積され、Git管理外（リポジトリに混入していない）。
- [ ] お金の流れアニメが`data.json.flow`に反応して動く（局面切替・金利・流動性で挙動変化）。
- [ ] Phase 1全タイル＋Phase 2/3が表示され、各々に値/z/色/説明書き/caveat/as_of/status。
- [ ] 取得不能/古いデータが`missing`/`stale`(+`store_fallback`)として**正直に**表示（捏造なし）。
- [ ] `real_yield`/`btc_onchain`等にレジーム崩れの注記。
- [ ] 除外項目（CSEI/65か月timing/Bloomberg/有料/HFT）が一切含まれない。
- [ ] 「売買助言ではない」文言が常時表示。
- [ ] commitはローカルのみ・**未push**（pushは人手ゲートで待機）。

---

## 9. 環境・依存・データ源クイックリファレンス

- Python: `requests`,`pandas`,`numpy`,`pyarrow`(Parquet)。TA系は不要なら入れない。
- フロント: 素のHTML+JS+Canvas（フレームワーク不要）。`localStorage`禁止。
- ローカルストア: `~/hf-data-store/`（Git管理外・上限250GB・Parquet+gzip JSON・append-only・PIT保持）。
- 主要無料源:
  - FRED API（要無料キー）: WALCL, WTREGEN, RRPONTSYD, DEXJPUS, DFEDTARU/L, DFII10, DTWEXBGS, BAMLH0A0HYM2, BAMLC0A0CM, VIXCLS, NFCI, T10Y3M, T10Y2Y, SAHMREALTIME, GDPC1, CPILFESL
  - 米財務省 Fiscal Data API: `…/v1/accounting/dts/operating_cash_balance`（日次TGA）
  - CFTC COT: 金・銀・**JPY**（非商業ネット）
  - JPX: 投資部門別売買状況(週間)、信用取引現在高(週)、個別信用残、空売り集計
  - JSF(taisyaku.jp): 品貸料率(逆日歩)・申込停止・日次貸借残
  - 暗号資産: CoinGlass(無料・ファンディング/OI/清算)、Farside(ETFフロー)、CoinGecko(価格/ペグ)、Glassnode無料(MVRV/NUPL)、DefiLlama(ステーブル時価総額)
  - Yahoo/CBOE: `^VIX`,`^VIX3M`,`^VIX9D`,`^SKEW`、Put-Call
  - AAII(週次センチメント)、Atlanta Fed GDPNow、Cleveland Fed Inflation Nowcasting
  - 金銀現物: SPDR GLD / iShares SLV 残高、CME COMEX在庫
- 取得規約: robots.txt順守。ライセンス制限データ(J-Quants等)は**非公開ストアのみ**・生データ非公開。CNN Fear&Greedは公式APIなし（スクレイプ可否を確認、不可なら`missing`）。

---

## 10. 留保事項（仕様に内在する限界）

- 多くは週次/月次で遅行・改定される。最新値=最終値ではない（PITストアで両保持）。
- センチメント/ブレッドス/COT/投資部門別は**確認用**であり単独の引き金にしない。
- レジーム依存（金vs実質金利は2022年以降、BTCvs流動性は2024–25に崩れた）→**ならさず注記**。
- ローカルストアはバックアップではない（ディスク障害対策は別途。重要履歴は別ドライブ複製を推奨）。
- これは“環境”の可視化であって**売買シグナルではない。投資助言ではない。**
