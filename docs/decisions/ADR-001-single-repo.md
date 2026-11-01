# ADR-001 単一リポジトリ化

- 状態: 採用（2026-11）
- 関連: PLAN2

## 背景
公開ダッシュボード（hf-signal-dashboard）と非公開の screener-private を git submodule でつないでいた。
計算式（marketcalc）が2つのリポジトリにまたがり、版ずれ・submodule 更新忘れ・二重の CI が起きやすかった。

## 決定
- リポジトリは hf-signal-dashboard の1つだけにする。screener-private と submodule は作らない。
- 計算式は `src/screener/calc/`（旧 marketcalc を git mv）だけに置く。`marketcalc/` は既存の import を壊さない互換の再エクスポートだけ。
- ローカル実行（日本株・米国株のスクリーニング）は `src/screener/` に置き、uv（pyproject.toml・uv.lock）で版を固定する。
- ruff・mypy は `src/screener` だけ。既存のトップレベルのファイルは整形・検査の対象にしない。

## 結果
- 式を直す場所が1か所になる。CI は ci.yml の1本（旧 marketcalc.yml は統合）。
- 公開してはいけないものはコードではなくデータなので、データの置き場所で分ける（ADR-002）。
