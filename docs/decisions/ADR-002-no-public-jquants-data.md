# ADR-002 J-Quants 由来データは公開しない（.gitignore・ローカル出力のみ）

- 状態: 採用（2026-11）

## 背景
J-Quants の利用規約上、取得したデータ（株価・決算・それから計算した理論株価などの値）を公開・再配布できない。
リポジトリは公開で、GitHub Pages も公開。

## 決定
- J-Quants 由来のデータはリポジトリの外に置く。既定のデータ置き場は `~/screener-data`
  （`~/.config/screener/config.toml` で変更可。リポジトリの中を指すと `screener.config` が止める）。
- 日本株の一覧は Mac mini のローカル `<data_dir>/out/`（CSV・HTML・counts.json）にだけ書く（`screener.local_report`）。
- 二重の守り: `.gitignore` に `screener-data/` `out/` `data/jquants/` `local_report/` `*.jq.json`。
- 通知にも株のデータを入れない（ADR-004）。docs/verification.md にも J-Quants の値は書かない。
- テストは架空の J-Quants 形データ（`tests/screener/fixtures/make_fixtures.py` がテスト時に一時ディレクトリへ作る）だけ。

## 結果
- 日本株の理論株価・割安度・総合判定は公開画面に出ない（Mac mini でだけ見る）。
