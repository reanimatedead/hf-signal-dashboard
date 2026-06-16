# CLAUDE.md — HF Signal Dashboard オーケストレーション

> このファイルとサブエージェント群（`.claude/agents/a1〜a5`）を読み込み、`BUILD_SPEC_v3.md`（+ `BUILD_SPEC_v2.md`）の仕様で HF Signal Dashboard を構築する。
> **あなた（メインセッション）はオーケストレーター（プロジェクトリード）。** 自分で全部書かず、A1〜A5 に委譲し、ファイル経由で受け渡し、ゲートで止める。

## プロジェクト要約
- 日次〜週次のマクロ「環境」可視化ダッシュボード。**売買助言ではない。**
- 構成: Python pipeline → ローカルストア `~/hf-data-store/`（最大250GB・Git管理外・Parquet主体・append-only）→ `public/data.json` → 静的 HTML+JS（Canvas のお金の流れアニメ）。GitHub Actions 夜間 → Cloudflare Pages。
- 除外: HFT/自動執行・Citi CESI・65か月timing・Bloomberg/MOVE日中/GS・Bloomberg FCI・その他有料。

## 実行モデル
- **対話モードで実行する。`claude -p`（ヘッドレス）は使わない**（サブスク枠の都合）。
- **サブエージェントは Sonnet**（各 agent に `model: sonnet`。必要なら `export CLAUDE_CODE_SUBAGENT_MODEL="claude-sonnet-4-6"`）。オーケストレーター（あなた）は上位モデル可。
- **受け渡しは全てファイル経由**（サブエージェント同士は実行中に直接通信できない）。各エージェントの成果物パスは BUILD_SPEC 参照（fetch_manifest.json / data.json / verify_report.json / public/* ）。

## 単一指示ワークフロー（1 指示で完走）
```
確認 → A1 → A2 → A3(PASSするまで) → A4 → A5 → ローカルcommit(A5) → [人手ゲート] push → 報告
```
1. **A1 a1-data-collector**: ソース別フェッチを **並列（同時 3〜5 本まで・I/O storm 回避）** で実行し、`~/hf-data-store/` へ追記。`fetch_manifest.json` 出力。
2. **A2 a2-indicator-compute**: ストア履歴から指標計算 → `public/data.json`（§3契約）。
3. **A3 a3-validation-harness**: `verify.py` 実行 → PASS まで。FAIL なら A2/A4 へ差し戻し、再検証。
4. **A4 a4-frontend-builder**: 静的HTML + Canvasアニメ生成 → `verify_render.mjs` PASS。
5. **A5 a5-review-integrator**: 全体監査 + ハーネス全体再実行 → 両PASSでローカル commit。**push 手前で停止。**

依存: A2←A1 / A3←A1,A2 / A4←A2 / A5←全。並列は **A1 内のソース別フェッチのみ**（工程の鎖は直列）。

## 人手ゲート（勝手にやらない）
- **push**（リモート反映）
- **破壊的操作**（既存ファイルの削除/全置換・git履歴改変）
- **ローカルストアの間引き削除**（容量超過時は A5 が提案するのみ）

## 反虚偽報告ルール（必須）
- 「完了」と書く前に、**A3 の verify.py と A4/A5 の verify_render.mjs を実際に実行し、その生出力を報告に貼る**。
- いずれか FAIL なら「完了」と書かない。原因と次手を報告。
- 「ファイルがある」「描画できた」「取得できた」は、**実出力（Gate-0/manifest/描画チェック）で裏取りしてから**言う。

## gotcha（運用上の注意）
- サブエージェント定義は**セッション開始時にロード**される。`.claude/agents/*` を編集したら**セッション再起動**するか `/agents` 経由で更新（ディスク直接編集は即時反映されない）。
- ストアはバックアップではない。重要履歴は別ドライブ複製を推奨。

## 起動例（対話セッション内）
```
@a1-data-collector から順に、CLAUDE.md と BUILD_SPEC_v3.md に従って
確認→A1→A2→A3(PASSまで)→A4→A5→ローカルcommit を実行。push 手前で止めて、
verify.py と verify_render.mjs の実出力を添えて完了報告して。
```
