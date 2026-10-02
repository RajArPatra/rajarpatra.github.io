#!/usr/bin/env bash
# Refresh activity.json from local Claude Code sessions and publish it.
# Prints exactly one status word on the last line:
#   NO_CHANGE  data identical, nothing committed
#   PUSHED     new data committed and pushed
#   DIVERGED   remote history moved in a way we won't resolve unattended
#   FAILED     something else went wrong
set -uo pipefail
cd "$(dirname "$0")/.." || { echo FAILED; exit 1; }

# Refuse to run on top of unrelated uncommitted work.
if ! git diff --quiet -- ':!activity.json' || ! git diff --cached --quiet; then
  echo "Working tree has changes other than activity.json; skipping."
  echo DIVERGED; exit 2
fi

git fetch -q origin main || { echo "fetch failed"; echo FAILED; exit 1; }

# Fast-forward only. This repo's history has been rewritten before, and an
# automated job must not guess at a rebase; bail and let a human look.
if ! git merge --ff-only origin/main >/dev/null 2>&1; then
  echo "Local branch cannot fast-forward to origin/main."
  echo DIVERGED; exit 2
fi

python3 tools/export_claude_activity.py || { echo FAILED; exit 1; }

if git diff --quiet -- activity.json; then
  echo NO_CHANGE; exit 0
fi

git add activity.json
git commit -q -m "Update Claude Code activity data" || { echo FAILED; exit 1; }
git push -q origin main || { echo "push rejected"; echo DIVERGED; exit 2; }
echo PUSHED
