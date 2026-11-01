#!/usr/bin/env bash
# Mac mini の初期設定（この1本だけ）。何度実行しても同じ状態になる。
#
#   1. リポジトリ ~/hf-signal-dashboard（main・ローカルの変更なし）を確認して uv sync
#   2. J-Quants のキーを macOS キーチェーンに登録（read -rs。画面にもファイルにも出さない）
#   3. ntfy のトピック（ランダム）を作り ~/.config/screener/config.toml に保存（1回だけ表示）
#   4. launchd: 毎日 19:00 に `uv run python -m screener.daily`（ログは <data_dir>/logs）
#   5. sudo pmset repeat wakeorpoweron MTWRFSU 18:55:00（19:00 の前に起こす）
#   6. ntfy の試し送信（本文は「screener 日付 OK」だけ）
#
# 使い方: bash ~/hf-signal-dashboard/scripts/install_macmini.sh [--rekey]
#   --rekey  キーチェーンのキーを入れ直す
set -euo pipefail

REPO_DIR="$HOME/hf-signal-dashboard"
DATA_DIR="$HOME/screener-data"
CONF_DIR="$HOME/.config/screener"
CONF="$CONF_DIR/config.toml"
SERVICE="screener-jquants"
LABEL="com.screener.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

REKEY=0
if [ "${1:-}" = "--rekey" ]; then REKEY=1; fi

die() { printf '中止: %s\n' "$1" >&2; exit 1; }

# ── 1. リポジトリの確認（git の clone・main・変更なし）と uv sync ─────────────
[ -d "$REPO_DIR/.git" ] || die "$REPO_DIR が git リポジトリではありません（git clone してから実行）"
branch="$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD)"
[ "$branch" = "main" ] || die "$REPO_DIR のブランチが main ではありません（今は $branch）"
[ -z "$(git -C "$REPO_DIR" status --porcelain)" ] || die "$REPO_DIR にローカルの変更があります（Mac mini では変更しない）"

command -v uv >/dev/null 2>&1 || die "uv がありません（https://docs.astral.sh/uv/ の手順で入れてから実行）"
UV="$(command -v uv)"
(cd "$REPO_DIR" && "$UV" sync)

# ── 2. J-Quants のキー（キーチェーンだけに置く）─────────────────────────────
if [ "$REKEY" = 1 ] || ! security find-generic-password -s "$SERVICE" >/dev/null 2>&1; then
  printf 'J-Quants の API キーを貼り付けて Enter（画面には出ません）: '
  read -rs KEY
  printf '\n'
  [ -n "$KEY" ] || die "キーが空です"
  security add-generic-password -U -s "$SERVICE" -a "$USER" -w "$KEY"
  unset KEY
  printf 'キーチェーンに登録しました（service=%s）\n' "$SERVICE"
else
  printf 'キーチェーンに登録済み（service=%s）。入れ直すときは --rekey\n' "$SERVICE"
fi

# ── 3. 設定ファイルと ntfy のトピック ─────────────────────────────────────
mkdir -p "$CONF_DIR" "$DATA_DIR/logs"
TOPIC=""
if [ -f "$CONF" ]; then
  TOPIC="$(sed -n 's/^topic *= *"\(screener-[0-9a-f]*\)".*/\1/p' "$CONF" | head -n 1)"
fi
NEW_TOPIC=0
if [ -z "$TOPIC" ]; then
  TOPIC="screener-$(openssl rand -hex 16)"
  NEW_TOPIC=1
fi
umask 077
cat >"$CONF" <<EOF_CONF
# screener の設定（install_macmini.sh が作成）。キーはここに書かない（キーチェーン）。
[paths]
data_dir = "$DATA_DIR"
repo_dir = "$REPO_DIR"

[jquants]
keychain_service = "$SERVICE"
rate_per_min = 50
history_years = 5

[ntfy]
server = "https://ntfy.sh"
topic = "$TOPIC"
EOF_CONF
umask 022
if [ "$NEW_TOPIC" = 1 ]; then
  printf '\nntfy のトピック（スマホの ntfy アプリでこの名前を購読してください。表示はこの1回だけ）:\n  %s\n\n' "$TOPIC"
else
  printf 'ntfy のトピックは前回のまま（%s を参照）\n' "$CONF"
fi

# ── 4. launchd（毎日 19:00）────────────────────────────────────────────────
mkdir -p "$HOME/Library/LaunchAgents"
cat >"$PLIST" <<EOF_PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$REPO_DIR</string>
  <key>ProgramArguments</key>
  <array>
    <string>$UV</string>
    <string>run</string>
    <string>--project</string>
    <string>$REPO_DIR</string>
    <string>python</string>
    <string>-m</string>
    <string>screener.daily</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$(dirname "$UV"):/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>19</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>$DATA_DIR/logs/daily.log</string>
  <key>StandardErrorPath</key><string>$DATA_DIR/logs/daily.err.log</string>
</dict>
</plist>
EOF_PLIST
plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
printf 'launchd に登録しました（%s・毎日 19:00）\n' "$LABEL"

# ── 5. 19:00 の前に起こす ─────────────────────────────────────────────────
sudo pmset repeat wakeorpoweron MTWRFSU 18:55:00
pmset -g sched

# ── 6. ntfy の試し送信 ───────────────────────────────────────────────────
(cd "$REPO_DIR" && "$UV" run python -m screener.notify test) && printf 'ntfy に試し送信しました\n'

printf '\n完了。初回の一括取得（5年分・50回/分のため時間がかかります）:\n'
printf "  cd %s && uv run python -m screener.japan.fetch --full && uv run python -m screener.us.fetch --universe --edgar --prices --full\n" "$REPO_DIR"
