#!/usr/bin/env bash
# Sets a bot's pull request to merge itself once its checks pass (`gh pr merge --auto`), trying again when GitHub
# fails. On 23 Nov 2026 one "Something went wrong while executing your query" right after `gh pr create` left a data PR
# open that would never merge: its events stayed off the site, and every later sweep would have waited on it and
# failed. Usage: merge-when-green.sh <pr url>. Exits 0 once the PR is set (or already merged), 1 if it never could:
# the PR stays open, with its changes, for someone to merge.
set -u
url="$1"
# Seconds between tries, about two minutes in all (tests pass shorter ones).
waits="${MERGE_RETRY_WAITS:-5 10 20 30 60}"
for wait in $waits last; do
  if gh pr merge "$url" --auto --squash --delete-branch; then exit 0; fi
  # A try whose answer was lost may still have set it, or the checks had passed and it merged.
  set_or_merged="$(gh pr view "$url" --json state,autoMergeRequest \
    --jq 'if .state == "MERGED" or .autoMergeRequest != null then "yes" else "no" end' 2>/dev/null)"
  if [ "$set_or_merged" = yes ]; then exit 0; fi
  if [ "$wait" = last ]; then break; fi
  echo "Couldn't set $url to merge itself: trying again in ${wait} s…"
  sleep "$wait"
done
echo "::error::$url couldn't be set to merge itself: merge it by hand once its checks pass."
exit 1
