# ADR-005 Mac mini は git pull --ff-only のみ・毎日19:00

- 状態: 採用（2026-11）。実行の場所と更新のしかたは下の「追記 2026-11-07」で置き換えた

## 決定
- Mac mini の clone は `~/hf-signal-dashboard`（main・ローカルの変更なし）。ローカルで変更・コミットしない。
  install_macmini.sh は git リポジトリでない・main でない・変更があるときは止まる。
- launchd（`~/Library/LaunchAgents/com.screener.daily.plist`）で毎日 19:00 に
  `uv run --project ~/hf-signal-dashboard python -m screener.daily`。ログは `<data_dir>/logs/`。
- `sudo pmset repeat wakeorpoweron MTWRFSU 18:55:00` で直前に起こす。
- daily.py の順序: `git pull --ff-only` → J-Quants 契約テスト（V2・日足 ≥3500 件・決算短信の列）→
  今日の差分 → 一覧 → local_report。どこかで失敗したら「失敗」を通知して終了コード 1。
- J-Quants の呼び出しは 50 回/60 秒（スレッド安全）。初回の一括取得（`--full`・5年分）も同じ制限。
- キーは環境変数 JQ → macOS キーチェーン（`screener-jquants`）。ファイル・ログに書かない。
- 別の launchd（週次など）は作らない。

## 結果
- 変更は必ず GitHub（PR → CI → main）を通る。fast-forward できなければ失敗として通知される。

## 追記 2026-11-07: 毎日の実行は専用の作業ツリーで
- 11/6・11/7 に、開発用のクローンが追跡先のないブランチのままで `git pull --ff-only` が失敗して止まった。
- 毎日の実行は `~/hf-signal-dashboard-run`（`git worktree`）で動かす。launchd の WorkingDirectory・`--project`、
  `config.toml` の `repo_dir` はここを指す。開発用のクローン `~/hf-signal-dashboard` はどのブランチでもよく、daily は触らない。
- 更新は `git fetch origin main` → `git checkout --detach origin/main`。同じブランチは2か所で開けないので
  （開発用のクローンの main と衝突する）、作業ツリーは detached HEAD で origin/main を指す。
- `repo_dir` が通常のクローンを指していたら、動かさず「失敗」を通知する。開発用のクローンのローカルの main は自動では進まない。
