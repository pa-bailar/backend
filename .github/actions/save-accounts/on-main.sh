#!/usr/bin/env bash
# accounts.txt as this run changed it, put on main as it is now, in a new worktree at $2 on branch $1.
# Every admin addition goes at the same spot (storage.add_account: the end of its section), so until 12 Nov 2026 two
# accounts PRs open at once conflicted, and the second never merged while its answer said "Agregué". Two causes:
# - an earlier accounts PR still open: this waits for it (up to SAVE_ACCOUNTS_WAIT_SECONDS);
# - this run's copy older than main (a sweep's copy is taken when it starts, and it may wait for a data PR first):
#   both sides' lines are kept (a union merge of accounts.txt), so the PR changes only what this run added.
set -euo pipefail
branch="$1"
dir="$2"

deadline=$(($(date +%s) + ${SAVE_ACCOUNTS_WAIT_SECONDS:-600}))
while [ "$(date +%s)" -lt "$deadline" ]; do
  open="$(gh api "repos/$GITHUB_REPOSITORY/pulls?state=open&per_page=100" \
    --jq '[.[] | select(.head.ref | startswith("accounts/"))] | length' || echo "?")"
  if [ "$open" = 0 ]; then break; fi
  echo "Waiting for an earlier accounts PR to merge (open: ${open})…"
  sleep "${SAVE_ACCOUNTS_PAUSE_SECONDS:-20}"
done

git fetch -q --depth=1 origin main
tmp="$(mktemp -d)"
git show HEAD:accounts.txt >"$tmp/base"
git show FETCH_HEAD:accounts.txt >"$tmp/main"
cp accounts.txt "$tmp/ours"
git merge-file --union "$tmp/main" "$tmp/base" "$tmp/ours" || true # main's lines, then this run's: no conflict
git worktree add -q -b "$branch" "$dir" FETCH_HEAD
cp "$tmp/main" "$dir/accounts.txt"
