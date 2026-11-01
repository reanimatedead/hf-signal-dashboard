# ADR-003 Pages は公開データのタブだけ・deploy-pages・data.json 非コミット

- 状態: 採用（2026-11。配信方式は 2026-07 から変更なし）

## 決定
- GitHub Pages には公開してよいデータ（Yahoo・FRED・EDGAR など）のタブだけを出す。J-Quants 由来は出さない（ADR-002）。
- 配信は deploy.yml の `actions/upload-pages-artifact` → `actions/deploy-pages`（build_type=workflow）。
- `docs/data.json` などの生成物は git にコミットしない（.gitignore 済）。コミットしていた update_signals.yml の
  ステップは削除済み、廃止済みの corr.yml は `_to_delete/workflows/` へ移した。
- 生成物が要るテスト（marker `needs_data_json`）はオフラインでは skip、deploy.yml full の
  「Data tests」ステップ（`REQUIRE_DATA_JSON=1`）ではスキップ禁止。失敗すれば upload/deploy に進まず前日のまま。
- タブは11（検証タブを通常の `class="tab"` で追加。契約テストも 11 に更新）。

## 結果
- 壊れたデータで上書きしない仕組みは deploy-pages のまま（失敗したジョブは配信しない）。
