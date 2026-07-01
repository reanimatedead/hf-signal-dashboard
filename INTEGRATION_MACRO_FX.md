# INTEGRATION_MACRO_FX.md — macro-fx-base 14 派生指標の統合（2026-07-01）

本命ダッシュボード（このリポ / `hf-signal-dashboard.pages.dev`）の「金利・債券・VOL」（`rates_vol`）タブに、
別リポ **macro-fx-base**（`macro-fx-base.pages.dev`）が算出する 14 派生指標を **1 データソースとして live 参照**で差し込んだ。

## 差し込んだ 14 指標
- イールドカーブ slope 3 本（10Y−2Y / 10Y−3M / 30Y−5Y）
- 実質利回り 5 本（1Y/2Y/5Y/10Y/30Y）
- FX×米金利 ローリング相関 6 本（USD/EUR・JPY/EUR・GBP/EUR × 2Y/10Y）

## 更新フローの設計 — 二重メンテを避けた理由

**採用: live cross-origin fetch（HF フロントが macro-fx の公開 JSON を実行時に読む）**

- HF の `docs/index.html` が `https://macro-fx-base.pages.dev/api/latest.json` を `loadMacroFx()` で取得し、
  `getCombinedRows()` の `rates_vol` に 3 つ目のセクションとして描画する。
- **14 指標の計算ロジックは macro-fx-base が単独所有**。HF 側は再計算も再取得もしない（コピーも持たない）。
- macro-fx-base は自身の launchd/Cloudflare Pages で **自動デプロイ**済み。HF はそれを読むだけ。

### 二重メンテにならない根拠
| 観点 | 本設計 | 却下案（HF側で再取得/コピー） |
|---|---|---|
| 指標計算の所有 | macro-fx-base 1 箇所 | 2 箇所に散る |
| HF の更新フロー変更 | **なし**（`update_signals.yml` / `fetch_signals.py` 無改変） | curl/生成ステップ追加が必要 |
| データの複製 | なし（live 参照） | docs/ にミラー = 鮮度ずれ・二重管理 |
| 既存自動更新への影響 | ゼロ（`data.json` 生成は不変） | パイプライン増設 |

### トレードオフ（正直に明記）
- 実行時に macro-fx-base.pages.dev へ依存する。到達不可なら macro セクションは**出さないだけ**
  （`MACRO_FX=null` → `buildMacroFxRows()` 空 → セクション非表示）。既存タブは一切影響を受けない＝グレースフル劣化。
- CORS は Cloudflare Pages が静的アセットに既定で `Access-Control-Allow-Origin: *` を付与（実測確認済）。追加設定不要。

## additive-only（既存無改変）
変更したのは `docs/index.html` に以下を **追加**しただけ：
`MACRO_FX_URL` / `MACRO_FX` 状態、`loadMacroFx()` / `buildMacroFxRows()` / `macroFxSymbol()` / `macroFxRisk()`、
`getCombinedRows()` の `rates_vol` 分岐末尾に 1 セクション push、`loadData()` 末尾に `loadMacroFx()` 呼び出し 1 行。
既存タブ・CSS セレクタ・i18n・自動更新・SVG チャートは無改変。回帰は `node verify_render.mjs`（`failed: []`）で確認。

## 検証
- ヘッドレス（puppeteer）で `rates_vol` タブに **14 行が live 値で描画**されることを確認（PASS）。
- 他タブ回帰なし（fx=18 行 / nikkei225=143 行）。
