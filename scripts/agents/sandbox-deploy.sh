#!/usr/bin/env bash
# sandbox-deploy.sh — preview a Codex branch (or PR) on sandbox.kytranempowerment.com
# BEFORE it reaches production. Checks the branch out into the sandbox git checkout
# (/mnt/archie_sandbox) and restarts the staging container; the page then renders at
# https://sandbox.kytranempowerment.com/tools/<module>.
#
# Usage:
#   scripts/agents/sandbox-deploy.sh codex/polish-the-faith-...   # by branch
#   scripts/agents/sandbox-deploy.sh 1489                         # by PR number
#   scripts/agents/sandbox-deploy.sh --reset                      # back to baseline
#
# NOTE: sandbox shares the PROD DB. UI/read testing is safe; write-paths touch prod
# (fine for the 6 low-data modules — fitness/family_tree/therapy/faith/brainstorm/doc).
set -euo pipefail

SANDBOX_DIR="/mnt/archie_sandbox"
STAGING="archie_staging"
BASE_BRANCH="sandbox"   # the sandbox baseline branch (has the amber sandbox banner)
ARG="${1:?usage: sandbox-deploy.sh <branch>|<pr#>|--reset}"

cd "$SANDBOX_DIR"
# Refuse to clobber uncommitted sandbox edits.
if [ -n "$(git status --porcelain)" ]; then
  echo "sandbox working tree is dirty — commit/stash in $SANDBOX_DIR first" >&2
  exit 2
fi
git fetch origin --prune -q

if [ "$ARG" = "--reset" ]; then
  git checkout -q "$BASE_BRANCH"
  echo "[sandbox] reset to baseline branch '$BASE_BRANCH'"
else
  # numeric → resolve PR head branch via gh
  if echo "$ARG" | grep -qE '^[0-9]+$'; then
    BRANCH="$(gh pr view "$ARG" --json headRefName --jq .headRefName)"
  else
    BRANCH="$ARG"
  fi
  git checkout -q -B _sandbox_preview "origin/$BRANCH"
  echo "[sandbox] now previewing 'origin/$BRANCH'"
fi

docker restart "$STAGING" >/dev/null
echo "[sandbox] restarted $STAGING — preview at: https://sandbox.kytranempowerment.com"
echo "[sandbox] (reset with: scripts/agents/sandbox-deploy.sh --reset)"
