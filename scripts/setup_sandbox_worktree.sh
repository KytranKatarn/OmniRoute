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

# Guarded prune (2026-10-07): a blanket `git worktree prune` deletes ANY registration
# whose worktree dir cannot be statable FROM THIS CONTEXT. Running this script where
# /mnt/archie_sandbox is invisible (e.g. a container with .git mounted but not the
# sandbox) destroyed the sandbox registration this way — every Repair Bay sandbox
# gate then failed "not a git repository" for 5 days. Skip when the registration
# exists but the worktree is invisible here.
if [ -e "$REPO_DIR/.git/worktrees/archie_sandbox" ] && [ ! -e "$SANDBOX_DIR" ]; then
    echo "[sandbox-setup] SKIP prune: registration exists but $SANDBOX_DIR is not visible from here"
else
    git worktree prune 2>/dev/null || true
fi

# Add / self-heal / verify
if [ -d "$SANDBOX_DIR/.git" ] || [ -f "$SANDBOX_DIR/.git" ]; then
    if [ -d "$REPO_DIR/.git/worktrees/archie_sandbox" ]; then
        echo "[sandbox-setup] Worktree already exists at $SANDBOX_DIR"
    else
        # Self-heal — the blind spot this script had (it only checked the .git file,
        # never the registration). `git worktree repair` alone CANNOT rebuild a
        # fully-pruned entry, so recreate the metadata files by hand: trailing
        # newlines in gitdir/commondir/HEAD are REQUIRED (without them git reports
        # "not a git repository"; the file must be exactly "commondir" — a "commdir"
        # typo reproduces the same failure), then repair cross-links and rebuild the
        # index only — working files are never touched.
        echo "[sandbox-setup] REPAIR: worktree present but registration missing — restoring..."
        REG_DIR="$REPO_DIR/.git/worktrees/archie_sandbox"
        mkdir -p "$REG_DIR"
        printf '%s\n' "$SANDBOX_DIR/.git" > "$REG_DIR/gitdir"
        printf '%s\n' '../..' > "$REG_DIR/commondir"
        printf '%s\n' "ref: refs/heads/$BRANCH" > "$REG_DIR/HEAD"
        git -C "$REPO_DIR" worktree repair "$SANDBOX_DIR" >/dev/null 2>&1 || true
        git -C "$SANDBOX_DIR" reset -q || true
        echo "[sandbox-setup] Registration restored on '$BRANCH'. Staging usually runs"
        echo "[sandbox-setup] '_sandbox_preview' — verify with: git -C $SANDBOX_DIR status"
    fi
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
