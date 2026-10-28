#!/usr/bin/env bash
# Commit generated files onto the latest branch head.
# Generated files are always taken from this run, so two workflows writing
# the same outputs can't leave a rebase conflict. Usage: commit_outputs.sh MSG PATH...
set -euo pipefail
msg="$1"; shift
branch="${GITHUB_REF_NAME}"
stash=$(mktemp -d)
for p in "$@"; do
  if [ -e "$p" ]; then mkdir -p "$stash/$(dirname "$p")"; cp -r "$p" "$stash/$(dirname "$p")/"; fi
done
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
for attempt in 1 2 3; do
  git fetch -q origin "$branch"
  git checkout -q -f -B "$branch" "origin/$branch"
  cp -r "$stash"/. .
  for p in "$@"; do if [ -e "$p" ]; then git add -f "$p"; fi; done
  if git diff --cached --quiet; then echo "nothing to commit"; exit 0; fi
  git commit -q -m "$msg"
  if git push -q origin "$branch"; then echo "pushed"; exit 0; fi
  echo "push rejected, retrying ($attempt)"; sleep $((attempt * 5))
done
exit 1
