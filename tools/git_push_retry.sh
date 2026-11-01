#!/usr/bin/env bash
# tools/git_push_retry.sh — bot コミットを push（並走 push での non-fast-forward を rebase で再試行）。
# collect.yml の "Push (with conflict retry)" と同じ手順を、新しい週次/月次 workflow で共用する。
# 使い方: tools/git_push_retry.sh "commit message" path [path...]
set -euo pipefail
msg="$1"; shift
git config --local user.email "github-actions[bot]@users.noreply.github.com"
git config --local user.name  "github-actions[bot]"
for p in "$@"; do
  if [ -e "$p" ]; then git add "$p"; fi
done
if git diff --cached --quiet; then
  echo "No changes to commit"; exit 0
fi
git commit -m "$msg"
BRANCH="${GITHUB_REF_NAME:-main}"
for attempt in 1 2 3 4; do
  if ! git pull --rebase --autostash origin "$BRANCH"; then
    git rebase --abort || true
    echo "::error::git pull --rebase failed (attempt ${attempt})"; exit 1
  fi
  if git push origin "HEAD:${BRANCH}"; then
    echo "Push succeeded (attempt ${attempt})"; exit 0
  fi
  echo "Push rejected (attempt ${attempt}), re-rebasing..."
done
echo "::error::Push failed after retries"; exit 1
