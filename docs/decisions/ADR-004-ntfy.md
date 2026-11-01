# ADR-004 通知は ntfy（OK/失敗＋日付のみ）

- 状態: 採用（2026-11）

## 背景
Mac mini の毎日の実行が止まったことに気づく手段が要る。GitHub Issue は非公開リポが無くなったので使いにくい。

## 決定
- 通知は ntfy（`POST https://ntfy.sh/<topic>`）。トピックは推測されない文字列
  `screener-` + `openssl rand -hex 16`（install_macmini.sh が作り `~/.config/screener/config.toml` に保存、1回だけ表示）。
- 本文は `screener YYYY-MM-DD OK` / `失敗` / `週次 OK` だけ（`screener.notify.BODY_RE`、テストで厳しい正規表現を確認）。
  株のデータ・件数・エラーの中身は送らない（エラーはローカルのログだけ）。
- 失敗した日だけ「失敗」。成功した日は送らない。月曜は成功の最後に「週次 OK」を1回（生きていることの確認）。
- 通知が送れなくても本処理の結果は変えない。

## 結果
- トピックを知っている人は通知を読めるが、中身は OK/失敗と日付だけなので漏れて困る情報は無い。
