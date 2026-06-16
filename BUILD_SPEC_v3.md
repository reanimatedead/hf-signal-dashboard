# BUILD_SPEC_v3.md — 差分（エージェントチーム実体化）

> v2（ローカルストア250GB版）からの**変更点のみ**。ここに無い項目（§1.5 ローカルストア / §3 データ契約 / §4 タイル / §5 アニメ / §6 ハーネス / §8 受け入れ基準 / §10 留保）は **`BUILD_SPEC_v2.md` をそのまま継続**。
> v3 の主眼: 5エージェントを「仕様の表」から **`.claude/agents/` の実体ファイル + `CLAUDE.md` オーケストレーション**へ昇格。モデル割当・A1並列フェッチ・ファイル経由受け渡しを確定。

---

## v3 変更サマリ
1. **エージェントチームを実ファイル化**（§1.6 新設）。
2. **§2 を更新**：各エージェントに対応ファイル・`model: sonnet`・tools・成果物パスを明記。A1 に**ソース別並列フェッチ（同時3〜5本）**を内蔵。
3. **実行モデル更新**：対話モード固定（`claude -p` 不可）、サブエージェント Sonnet、オーケストレーターは上位モデル可。
4. **受け渡しはファイル経由**を明文化（サブエージェント間は実行中に直接通信不可）。
5. **運用 gotcha**：agent定義はセッション開始時ロード→編集後は再起動 or `/agents`。

---

## §1.6（新設）エージェントチームの実体とレイアウト

```
リポジトリルート/
├── CLAUDE.md                         # オーケストレーション（メインセッションが読む）
├── BUILD_SPEC_v3.md / BUILD_SPEC_v2.md
├── .claude/agents/
│   ├── a1-data-collector.md          # A1 収集（並列フェッチ）
│   ├── a2-indicator-compute.md       # A2 計算 → public/data.json
│   ├── a3-validation-harness.md      # A3 検証 verify.py（PASS/FAIL）
│   ├── a4-frontend-builder.md        # A4 フロント + Canvasアニメ + verify_render.mjs
│   └── a5-review-integrator.md       # A5 監査 + 全体再検証 + ローカルcommit（push手前で停止）
├── public/                           # index.html, app.js, flow.js, data.json
├── verify.py / verify_render.mjs     # ハーネス
└── (~/hf-data-store/ はリポジトリ外・Git管理外)
```

- 形式: 各 agent は **YAML フロントマター（name / description / tools / model）+ 本文=システムプロンプト**。公式仕様準拠。
- スコープ: プロジェクト用 `.claude/agents/`（チーム共有・バージョン管理可）。
- **受け渡しは全てファイル**：`~/hf-data-store/fetch_manifest.json`（A1）→ `public/data.json`（A2）→ `~/hf-data-store/verify_report.json`（A3）→ `public/*` `verify_render.mjs`（A4）→ commit（A5）。サブエージェント同士は直接通信しない。

---

## §2（更新）5エージェント構成 ＋ モデル・ファイル・成果物

| ID | ファイル | model | tools | 責務(要点) | 成果物 | 終了ゲート |
|----|---------|-------|-------|-----------|--------|-----------|
| **A1** | `a1-data-collector.md` | sonnet | Bash,Read,Write,Glob,Grep | 無料ソースを**ソース別並列(同時3〜5)**取得→`~/hf-data-store/`へ append-only。単位整合・鮮度・ライセンス順守 | `fetch_manifest.json`, ストア | 各ソース status 記録・捏造なし |
| **A2** | `a2-indicator-compute.md` | sonnet | Bash,Read,Write,Glob,Grep | ストア長期履歴で z/局面/net_liquidity/flow を計算、explain・caveat付与 | `public/data.json` | schema一致・basin_tilt≈1 |
| **A3** | `a3-validation-harness.md` | sonnet | Bash,Read,Grep | `verify.py` 実行（10ゲート）→**実出力でPASS/FAIL** | `verify_report.json` + 標準出力 | verify.py PASS |
| **A4** | `a4-frontend-builder.md` | sonnet | Read,Write,Edit,Bash,Glob,Grep | 静的HTML+Canvasお金の流れアニメ(data.json駆動)+タイル描画→`verify_render.mjs` | `public/*`, `verify_render.mjs` | 描画チェックPASS |
| **A5** | `a5-review-integrator.md` | sonnet | Read,Grep,Bash | 全体監査+ハーネス全体再実行→**ローカルcommit→push手前で停止**→実出力添付報告 | commit(未push), 報告 | 両ハーネス PASS の実出力 |

並列指針（変更なし）: A1 のソース別フェッチのみ並列（同時3〜5本・I/O storm回避）。A2←A1 / A3←A1,A2 / A4←A2 / A5←全。**工程の鎖は直列**（10エージェント化しても増分はA1並列度のみ→不採用）。

---

## §7（更新）実行ワークフロー（単一指示）

```
確認 → A1(並列フェッチ) → A2 → A3(PASSまで) → A4 → A5
     → ローカルcommit(ストアはGit管理外) → [人手ゲート] push → 報告(両ハーネス実出力添付)
```

- 実行: **対話モード固定**（`claude -p` ヘッドレスは使わない）。
- **サブエージェントは Sonnet**（各 agent `model: sonnet` / 必要なら `CLAUDE_CODE_SUBAGENT_MODEL` 指定）。オーケストレーターは上位モデル可。
- **人手ゲート**：push / 破壊的操作 / ストア間引き削除。
- **反虚偽報告**：完了主張の前に verify.py と verify_render.mjs を実行し生出力を貼る。
- **gotcha**：`.claude/agents/*` はセッション開始時ロード。編集後は再起動 or `/agents`。

---

## §9 追補（依存）
- Python: `requests`,`pandas`,`numpy`,`pyarrow`。
- Claude Code: サブエージェント（`.claude/agents/`）。`/agents` で確認・編集可。
- 他のデータ源・契約・アニメ・ハーネス・受け入れ基準は **v2 を継続**。

---

## 起動手順（まとめ）
1. リポジトリに `CLAUDE.md`・`BUILD_SPEC_v3.md`・`BUILD_SPEC_v2.md`・`.claude/agents/a1〜a5.md` を配置。
2. （アニメの器を「日本株/金/銀/BTC」にする場合のみ）`BUILD_SPEC_v2.md` §5 ラベルと §3 `basin_tilt` キーを投入前に差し替え。
3. Claude Code を**対話モードで起動**（既に起動済みなら**再起動**して agent をロード）。
4. CLAUDE.md の「起動例」プロンプトで実行。push 手前で停止 → 完成後にユーザーが一括チェック。
