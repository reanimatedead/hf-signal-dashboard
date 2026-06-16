# BUILD_SPEC_v4.md — 既存リポ活用（増築）モード差分

> 方針: 既存 **reanimatedead/hf-signal-dashboard（本番稼働中・per-symbol テクニカル）** を**置き換えず、増築**してマクロ「環境」レイヤー＋お金の流れアニメを追加する。
> このファイルは v3/v2 を土台に、**増築モードとして以下を上書き/追加**する（競合する箇所は v4 が優先）。
> 最優先原則: **本番 live を壊さない。** main を直接触らず、`feat/macro-environment` ブランチで作業。マージ/デプロイは人手ゲート。

---

## §A0 大原則（これを破る変更はしない）
1. **ブランチ隔離**: 作業は `feat/macro-environment` のみ。**main 直編集禁止**。人手ゲート = main へのマージ＋デプロイ。
2. **インベントリ先行**: 着手前に既存リポを棚卸しし、構造を理解してから増築（§A1）。理解前に書かない。
3. **加算のみ（additive-only）**: 既存の `fetch_signals.py`・per-symbol タブ・既存データファイル・既存 CI は**変更しない**。新規ファイル/新規タブ/新規ステップとして足す。
4. **重複させない**: 既存が既に取得している **JP rates CSV / IMM(CFTC)CSV** は再取得せず再利用（§A2）。
5. **契約は壊さず拡張**: `DATA_CONTRACT.md` は追記で拡張（マクロ節を足す）。既存スキーマは変えない。
6. **ストアは外**: `~/hf-data-store/`（最大250GB・リポジトリ外・Git管理外）はそのまま。長期履歴/z用に追加するだけ。
7. **回帰ゼロ**: 増築後も既存タブ/SVGチャートが従来どおり動くこと（受け入れ基準 §A7）。

---

## §A1 インベントリ（着手前に必須・ゲートA0）
Claude Code はローカルクローンで以下を読み、`MACRO_INTEGRATION_NOTES.md`（feature branch）にまとめてから次へ進む:
- `fetch_signals.py` の構造（関数分割・出力ファイル・スケジュール）
- `DATA_CONTRACT.md`（既存スキーマ・命名規約）
- `data/` の実レイアウト（どのCSV/JSONがあるか。**JP rates / IMM の正確なパスと列**）
- フロント: タブの生成方法（静的HTMLか、テンプレ生成か、per-symbol SVGの描画箇所）
- `.github/` ワークフロー（夜間ジョブの起動・成果物・デプロイ経路）
- Cloudflare Pages の公開ディレクトリ（どこを配信しているか）
→ この棚卸し結果に**実際に合わせて**以降のパス/結線を決める（推測で固定しない）。

---

## §A2 データ再利用（A1 収集の上書き）
- **再利用**: 既存の JP rates / IMM(CFTC=COT建玉) CSV を**入力として読む**。COT-JPY・日米金利差はここから。
- **gap だけ取得**: 既存に無いものだけ新規フェッチ → `~/hf-data-store/` へ append-only。
  - 主に: FRED（WALCL/RRP/DFII10/HY/VIX/NFCI…）, 米財務省 TGA(日次), 暗号資産(CoinGlass/Farside/CoinGecko/Glassnode/DefiLlama), ナウキャスト(GDPNow/Cleveland), 金銀現物。
- 取得規約・ライセンス・単位整合は v2/v3 のまま。

---

## §A3 出力統合（A2 計算の上書き）
- 既存データは改変しない。マクロ成果は**新規 `data/macro.json`**（v2 §3 契約 = meta/flow/tiles）として出力。
- `DATA_CONTRACT.md` に「マクロ環境（macro.json）」節を**追記**（既存節は不変）。
- z は `~/hf-data-store/` の長期履歴で算定（FRED 3年窓に依存しない）。

---

## §A4 フロント統合（A4 の上書き）
- **新規スタンドアロンサイトを作らない。** 既存ダッシュボードに**「Macro / お金の流れ」タブ（またはページ）を1枚追加**する。
- シードの `flow.js`（Canvasアニメ）/`app.js`（タイル描画）の**ロジックを流用**し、マウント先は§A1で判明した既存タブ機構に合わせる（読むのは `data/macro.json`）。
- **既存の per-symbol タブ・SVGチャート・スタイルは一切変更しない**（共通CSSに触る場合も追加クラスのみ、既存セレクタを壊さない）。
- 「概念可視化 / 売買助言ではない」を当該タブに常時表示。

---

## §A5 パイプライン/CI 統合（A5 周辺の上書き）
- 既存夜間 GitHub Actions に**マクロ計算ステップを追加**（既存ステップの後段に append）。既存 `fetch_signals.py` の挙動・出力は不変。
- ハーネス（`verify.py` / `verify_render.mjs`）を**追加**。当面は既存CIを止めないため**非ブロッキング**で走らせ、ローカル/エージェント工程では**ブロッキング**（PASSしないと commit しない）。
- `verify.py` のパスは §A1 のインベントリ結果に合わせて調整（`data/macro.json` と既存配信ディレクトリを参照）。`verify_render.mjs` は **Macro タブが既存サイト内で描画されるか**を確認。

---

## §A6 エージェント挙動の上書き（役割は不変・スコープのみ変更）
- **A1**: 新規取得は gap のみ。既存 CSV(JP rates/IMM) は読むだけ。`~/hf-data-store/` へ追記。
- **A2**: `data/macro.json` を生成。DATA_CONTRACT は追記拡張。
- **A3**: 既存パスに合わせた `verify.py`。**既存タブの回帰チェック**（既存データファイルが消えていない・既存ページが200で返る）も追加。
- **A4**: タブ1枚を**追加**（新サイトを作らない）。既存UIに非破壊でマウント。
- **A5**: `feat/macro-environment` に**ローカルcommit**。**main マージ・デプロイ・push は人手ゲート**（commit手前まで自走、その先は停止して報告）。

---

## §A7 受け入れ基準（増築版・完成後にユーザーが確認）
- [ ] **回帰ゼロ**: 既存 per-symbol タブ/SVGチャートが従来どおり表示（既存データファイル不変、既存ページ200）。
- [ ] **Macro タブ追加**: お金の流れアニメ + タイルが `data/macro.json` 駆動で表示。各タイルに値/z/色/説明書き/caveat/as_of/status/source。
- [ ] JP rates / IMM は**再取得せず既存を再利用**（重複フェッチなし）。
- [ ] `DATA_CONTRACT.md` は**追記拡張**のみ（既存節は差分なし）。
- [ ] `verify.py` / `verify_render.mjs` が PASS（実出力添付）。
- [ ] `~/hf-data-store/` は Git 管理外（リポジトリに生データ混入なし）。
- [ ] 除外厳守（CSEI/65か月timing/Bloomberg/有料/HFT）。「売買助言ではない」常時表示。
- [ ] 作業は `feat/macro-environment` のみ。**main 未マージ・未デプロイ**（人手ゲート待ち）。

---

## §A8 人手ゲート（自走しない）
- **main へのマージ / Cloudflare デプロイ / push**
- 既存ファイルの**破壊的変更/削除**（増築は加算のみ。やむを得ず触る場合は提案して停止）
- `~/hf-data-store/` の間引き削除

---

## 起動手順（増築モード）
1. 既存ローカルクローンに移動し、`git switch -c feat/macro-environment`。
2. 配布物を**ブランチに配置**: `CLAUDE.md`・`BUILD_SPEC_v2.md`・`BUILD_SPEC_v3.md`・`BUILD_SPEC_v4.md`・`.claude/agents/a1〜a5.md`・`seed/`（参照実装）。`.gitignore` に `~/hf-data-store/` 相当と生成物を追加。
3. Claude Code を**対話モードで起動**（配置後は再起動 or `/agents`）。
4. **まず §A1 インベントリ**を実行 → `MACRO_INTEGRATION_NOTES.md`。その後 確認→A1→A2→A3(PASS)→A4→A5→feature branch へ commit。**merge/deploy 手前で停止**。
5. 完成後にユーザーが §A7 で一括チェック → 承認で main マージ＆デプロイ。
