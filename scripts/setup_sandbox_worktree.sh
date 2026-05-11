#!/usr/bin/env bash
# scripts/setup_sandbox_worktree.sh
# One-time setup: creates /mnt/archie_sandbox git worktree on the 'sandbox' branch.
# Run from /mnt/archie_brain as: bash scripts/setup_sandbox_worktree.sh
set -euo pipefail

REPO_DIR="/mnt/archie_brain"
SANDBOX_DIR="/mnt/archie_sandbox"
BRANCH="sandbox"
BASE_BRANCH="main"

echo "[sandbox-setup] Checking repo..."
cd "$REPO_DIR"

git -C "$REPO_DIR" rev-parse --is-inside-work-tree > /dev/null 2>&1 || { echo "[sandbox-setup] ERROR: $REPO_DIR is not a git repo"; exit 1; }

# Create the sandbox branch if it doesn't exist
if ! git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    echo "[sandbox-setup] Creating branch '$BRANCH' from $BASE_BRANCH..."
    git branch "$BRANCH" "$BASE_BRANCH"
else
    echo "[sandbox-setup] Branch '$BRANCH' already exists."
fi

# Always prune stale worktree registrations before any add
git worktree prune 2>/dev/null || true

# Add worktree if not already present
if [ -d "$SANDBOX_DIR/.git" ] || [ -f "$SANDBOX_DIR/.git" ]; then
    echo "[sandbox-setup] Worktree already exists at $SANDBOX_DIR"
else
    echo "[sandbox-setup] Adding worktree at $SANDBOX_DIR..."
    if ! sudo -n true 2>/dev/null; then
        echo "[sandbox-setup] ERROR: sudo access required to create $SANDBOX_DIR under /mnt"
        exit 1
    fi
    sudo mkdir -p "$SANDBOX_DIR"
    sudo chown "$(whoami)":"$(whoami)" "$SANDBOX_DIR"
    git worktree add "$SANDBOX_DIR" "$BRANCH"
fi

echo ""
echo "[sandbox-setup] Done."
echo "[sandbox-setup] Sandbox worktree: $SANDBOX_DIR (branch: $BRANCH)"
echo "[sandbox-setup] To develop:       cd $SANDBOX_DIR"
echo "[sandbox-setup] To start staging: docker compose -f $REPO_DIR/docker-compose.staging.yml up -d"
