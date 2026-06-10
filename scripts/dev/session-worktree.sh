#!/usr/bin/env bash
# session-worktree.sh — per-session git worktrees for /mnt/archie_brain co-tenancy.
#
# WHY (2026-06-09, owner-confirmed two parallel Claude sessions): the primary
# checkout at /mnt/archie_brain is the DEPLOY TREE — containers volume-mount it,
# so it must sit on main. Interactive sessions branching/committing/resetting in
# it collide with each other and with automation (see KB #272080/#272097, tasks
# #3919/#3926). Each session works in its OWN worktree instead.
#
# PROTOCOL (mirrors project_session-handoff.md):
#   * Primary /mnt/archie_brain: main only. Allowed there: fetch, file edits for
#     live hot-testing, and clean-tree `reset --hard origin/main` after merges.
#     NEVER `checkout -b` / commit in the primary again.
#   * All branch + commit + push happen inside YOUR session worktree.
#   * Pre-merge live test (containers read the primary): copy the changed files
#     primary-ward by hand, then restore primary with reset after the merge.
#
# Worktrees live on /mnt/data2 (root FS is at 99%; each tree is ~2.2 GB).
#
# Usage:
#   scripts/dev/session-worktree.sh create <name>   # create or reuse; prints path
#   scripts/dev/session-worktree.sh list
#   scripts/dev/session-worktree.sh remove <name>   # refuses if dirty
set -euo pipefail

REPO="/mnt/archie_brain"
WT_ROOT="/mnt/data2/worktrees"
CMD="${1:?usage: session-worktree.sh create|list|remove [name]}"

case "$CMD" in
  create)
    NAME="${2:?usage: session-worktree.sh create <name>}"
    DIR="$WT_ROOT/$NAME"
    mkdir -p "$WT_ROOT"
    if [ -d "$DIR" ]; then
      echo "exists: $DIR ($(git -C "$DIR" branch --show-current 2>/dev/null || echo detached))"
      exit 0
    fi
    git -C "$REPO" fetch origin -q
    # Detached at origin/main: the session creates its own feature branches
    # inside the worktree; no branch-name collisions between worktrees.
    git -C "$REPO" worktree add --detach "$DIR" origin/main >/dev/null
    echo "created: $DIR"
    echo "next:    cd $DIR && git checkout -b feat/<your-branch>"
    ;;
  list)
    git -C "$REPO" worktree list
    ;;
  remove)
    NAME="${2:?usage: session-worktree.sh remove <name>}"
    DIR="$WT_ROOT/$NAME"
    [ -d "$DIR" ] || { echo "no such worktree: $DIR"; exit 1; }
    if [ -n "$(git -C "$DIR" status --porcelain)" ]; then
      echo "REFUSE: $DIR has uncommitted changes — commit+push or clean it first"
      exit 1
    fi
    git -C "$REPO" worktree remove "$DIR"
    echo "removed: $DIR"
    ;;
  *)
    echo "unknown command: $CMD (create|list|remove)"; exit 1
    ;;
esac
