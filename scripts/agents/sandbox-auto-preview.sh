#!/usr/bin/env bash
# sandbox-auto-preview.sh — keep sandbox.kytranempowerment.com showing the NEWEST
# open codex/* PR automatically. Run from cron (every few min): when the newest
# open codex PR's HEAD changes, it redeploys that branch to the sandbox so you can
# just push from the Codex terminal and refresh the sandbox URL — no manual step.
#
# No-ops when: no open codex/* PRs, or the newest one is already deployed.
# Install (user crontab, runs as you — has docker + gh):
#   */3 * * * * /mnt/archie_brain/scripts/agents/sandbox-auto-preview.sh
set -euo pipefail
export PATH="/home/kytran/.local/bin:/usr/local/bin:/usr/bin:/bin"  # gh lives in ~/.local/bin

REPO="/mnt/archie_brain"
STATE="/tmp/codex-sandbox-preview.sha"
LOG="/tmp/codex-sandbox-preview.log"
cd "$REPO"

# Worktree-registration watchdog (2026-10-07): if the sandbox worktree dir exists but its
# registration under .git/worktrees/archie_sandbox has been deleted (a blanket
# `git worktree prune` from a context where /mnt/archie_sandbox is invisible does this),
# every deploy AND every Repair Bay sandbox gate fails "not a git repository" — and did
# so silently for 5 days. This script runs every 3 min, so surface it here: exit before
# the deploy path with an actionable error instead of a generic failure.
if [ -e /mnt/archie_sandbox/.git ] && [ ! -d "$REPO/.git/worktrees/archie_sandbox" ]; then
  echo "$(date '+%F %T') ERROR: sandbox worktree registration MISSING — run: bash $REPO/scripts/setup_sandbox_worktree.sh (self-heal)" >>"$LOG"
  exit 1
fi

# Newest open PR whose head branch is codex/* → "branch sha" (uses gh's built-in jq).
LINE="$(gh pr list --state open --json headRefName,headRefOid,updatedAt \
  --jq 'map(select(.headRefName|startswith("codex/")))|sort_by(.updatedAt)|last
        |if .==null then "" else "\(.headRefName) \(.headRefOid)" end' 2>>"$LOG")"

[ -z "$LINE" ] && exit 0          # no open codex PRs — leave sandbox as-is
BRANCH="${LINE%% *}"
SHA="${LINE##* }"
[ "$SHA" = "$(cat "$STATE" 2>/dev/null || true)" ] && exit 0   # already deployed

echo "$(date '+%F %T') auto-preview → $BRANCH ($SHA)" >>"$LOG"
if "$REPO/scripts/agents/sandbox-deploy.sh" "$BRANCH" >>"$LOG" 2>&1; then
  echo "$SHA" >"$STATE"
else
  echo "$(date '+%F %T') deploy FAILED for $BRANCH" >>"$LOG"
fi
