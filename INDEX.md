# INDEX.md — HF Macro Dashboard 成果物 索引（迷ったらここ）

> 目的: チャットで増えたファイルの「どれが何か・どれが有効か・どこに置くか」を1枚で確定。
> 現在の方針: **既存リポ reanimatedead/hf-signal-dashboard を増築（BUILD_SPEC_v4）**。`feat/macro-environment` ブランチで作業、main/デプロイは人手ゲート。

---

## 1. 設計図（仕様）— 優先順位 v4 > v3 > v2、v1は廃止

| ファイル | 状態 | 役割 | 読む順 |
|---|---|---|---|
| `BUILD_SPEC.md`（v1） | **廃止** | 最初の単一設計図。v2に吸収済み。**使わない** | — |
| `BUILD_SPEC_v2.md` | **有効・土台** | 本体: §1.5 ローカルストア / §3 data契約 / §4 タイル / §5 アニメ / §6 ハーネス / §8 受入 / §10 留保 | ③ |
| `BUILD_SPEC_v3.md` | **有効・差分** | エージェント実体化: §1.6 構成 / §2 役割 / §7 ワークフロー / §9 依存 | ② |
| `BUILD_SPEC_v4.md` | **有効・最優先** | 既存活用（増築）モード: ブランチ隔離 / インベントリ先行 / 既存CSV再利用 / Macroタブ追加 / 回帰ゼロ | ① |

読み方: **v4を最優先**に、v3（エージェント）→ v2（中身）の順で参照。競合は v4 が勝つ。

## 2. オーケストレーション・エージェント

| ファイル | 状態 | 役割 |
|---|---|---|
| `CLAUDE.md` | 有効 | 起動順・単一指示・人手ゲート・モデル(Sonnet)・反虚偽報告・gotcha |
| `.claude/agents/a1-data-collector.md` | 有効 | A1 収集（gap取得・既存CSV再利用・ストア追記） |
| `.claude/agents/a2-indicator-compute.md` | 有効 | A2 計算（z/局面/flow → data/macro.json） |
| `.claude/agents/a3-validation-harness.md` | 有効 | A3 検証（verify.py + 既存回帰チェック） |
| `.claude/agents/a4-frontend-builder.md` | 有効 | A4 フロント（Macroタブ1枚追加・既存UI不変） |
| `.claude/agents/a5-review-integrator.md` | 有効 | A5 監査→feature branch commit→merge/deploy手前で停止 |

## 3. 参照シード（動く土台・実走確認済み）

| ファイル | 役割 |
|---|---|
| `seed/pipeline/build_data.py` | 収集+計算の参照実装（A1/A2の土台） |
| `seed/verify.py` | ハーネス本体（10ゲート・このチャットで PASS 実証済み） |
| `seed/verify_render.mjs` | ブラウザ描画チェック（本番MacBookで実行） |
| `seed/public/{index.html, app.js, flow.js}` | お金の流れアニメ+タイル描画。増築では**タブに流用** |
| `seed/README_RUN.md` | ローカル実行手順 + Claude Code 引き渡し |

## 4. 配布物

| ファイル | 役割 |
|---|---|
| `hf-macro-dashboard-v4.zip` | **これ1つが最新の完全セット**（上記の有効ファイル全部＋.gitignore＋このINDEX）。v1は同梱せず |

---

## 5. Claude Code に渡すもの（増築モード）
`feat/macro-environment` ブランチに、zip を展開して配置:
```
（既存リポのまま）
├── BUILD_SPEC_v2.md  BUILD_SPEC_v3.md  BUILD_SPEC_v4.md  ← v4最優先
├── CLAUDE.md  INDEX.md
├── .claude/agents/a1〜a5.md
├── seed/ …（参照実装）
└── （既存の fetch_signals.py / data/ / docs/ / .github/ は不変）
```
→ まず §A1 インベントリ → `MACRO_INTEGRATION_NOTES.md` → 増築 → feature branch commit → 停止。

---

## 6. 完成後に作る4点（このチャットで作成）
**完成＝Macroタブがlive(未デプロイ)・ハーネスPASS・main未マージ** になってから、実データで作成する:

| 成果物 | 中身 | 必要な実データ（下記7から） |
|---|---|---|
| `RETROSPECTIVE.md`（反省） | 何を狙い何ができ何が壊れたか・方針転換(並行→増築)・虚偽報告/単位罠などの実例 → ルール化 | インベントリ・検証出力・git log・インシデント記録・所要時間 |
| `DESIGN.md`（設計書・統合版） | v2+v3+v4 を1枚に統合した**完成形の設計書**（as-built）。今後はこれ1枚＝混乱解消 | 最終 macro.json のタイル一覧・実装パス |
| `AGENTS.md`（エージェント構成） | 実際に使ったA1〜A5の役割/tools/model/受け渡し/ゲート（最終形） | 実運用での調整点 |
| `REPORT.md`（報告書） | 納品物・受入基準§A7の結果・liveタブURL・検証PASS証跡・残作業(merge/deploy)・次の一手 | 受入チェック結果・URL・検証出力 |

---

## 7. 完成までに「残しておく」採取リスト（後で正確に書くため）
Claude Code に走らせる間、以下を保存しておくと反省/報告書が捏造なしで書けます:
- `MACRO_INTEGRATION_NOTES.md`（§A1 インベントリ結果）
- `verify.py` と `verify_render.mjs` の**最終実出力**（PASS/FAIL のJSONそのまま）
- `git log feat/macro-environment`（コミット履歴・ハッシュ）
- データ源の **live / missing 一覧**（どれが取れてどれが欠損か）
- **インシデント記録**: 偽の完了報告・既存破壊しかけ・ロールバック・単位罠（百万/十億）など、起きたこと
- **所要時間/コスト感**（5時間枠の消費・サブエージェント回数の体感）
- 最終 `data/macro.json`（またはタイルID一覧）

> 完成後、これらを貼ってくれれば、4点（反省・設計書・エージェント構成・報告書）を実データで作成します。
