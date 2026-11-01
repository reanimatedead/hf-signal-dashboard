# ADR-005 Mac mini は git pull --ff-only のみ・毎日19:00

- 状態: 採用（2026-11）

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
