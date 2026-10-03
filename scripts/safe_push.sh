#!/usr/bin/env bash
# safe_push.sh — commit, push, and PROVE the remote received what you pushed.
#
# Why this exists (2026-10-03, handover/wtf-2026-10-03):
#   A commit was aborted by the `end-of-file-fixer` pre-commit hook, which
#   rewrites files to add a trailing newline. The `git push` that followed was a
#   separate command rather than an `&&` continuation, so it ran anyway. The
#   result was an EMPTY branch on origin: pushed, reported success, carrying none
#   of the work. Nothing failed loudly.
#
# What it enforces:
#   1. Refuses to push main/master.
#   2. Refuses to run when TRACKED files are modified or staged. Those are
#      either uncommitted work or another agent's in-progress edits, and
#      sweeping them into a commit is how unrelated work gets shipped by accident.
#   3. Commits only files you name (or all tracked modifications when you say so
#      explicitly) — never a blanket `git add -A`.
#   4. Treats a hook-rewritten file as recoverable: re-stage, retry once.
#   5. Pushes, then RE-READS the remote ref and compares it to local HEAD.
#   6. Exits non-zero unless the remote SHA equals local HEAD.
#
# It cannot detect every way a push can lie. It catches the observed class:
# a push that returned success while not carrying the commit just made.
#
# Usage:
#   scripts/safe_push.sh <branch> [commit-message] [--staged-only|--all-tracked]
#
# Examples:
#   # ship what is already staged/committed
#   scripts/safe_push.sh fix/wtf-election-calendar
#
#   # commit the named files, then push and verify
#   scripts/safe_push.sh fix/wtf-election-calendar "docs: correct migration notes" --staged-only
#
# Environment:
#   REMOTE=<name>   remote to push to            (default: origin)
#   DRY_RUN=1       commit but skip the push and the verification
#
# Exit codes: 0 verified, 1 refused/failed. Only 0 means "the remote has it."

set -euo pipefail

REMOTE="${REMOTE:-origin}"
DRY_RUN="${DRY_RUN:-0}"

die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
ok()  { printf '\033[32mok:\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarn:\033[0m %s\n' "$*" >&2; }

# --- arguments ---------------------------------------------------------------
[ $# -ge 1 ] || die "usage: $0 <branch> [commit-message] [--staged-only|--all-tracked]"

BRANCH="$1"; shift
MSG=""
SCOPE="staged-only"

while [ $# -gt 0 ]; do
  case "$1" in
    --staged-only)  SCOPE="staged-only" ;;
    --all-tracked)  SCOPE="all-tracked" ;;
    -*)             die "unknown option: $1" ;;
    *)
      [ -z "$MSG" ] || die "unexpected extra argument: $1"
      MSG="$1"
      ;;
  esac
  shift
done

command -v git >/dev/null || die "git not found"
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# --- 0. refuse to operate on the default branch ------------------------------
case "$BRANCH" in
  main|master) die "refusing to push to '$BRANCH'. Open a branch first." ;;
esac

CURRENT="$(git rev-parse --abbrev-ref HEAD)"
[ "$CURRENT" = "$BRANCH" ] || die "you are on '$CURRENT' but asked to push '$BRANCH'. Checkout first."

# --- 1. worktree hygiene -----------------------------------------------------
# `git status --porcelain` gives two status columns: index (staged) then
# worktree (unstaged). They must be read separately — treating a staged file as
# "dirty" would block the exact operation this script exists to perform.
#
#   X Y  meaning
#   ?  ?  untracked            -> tolerated, never committed
#   U  *  unmerged / conflict -> always fatal, cannot be shipped
#   *  ' ' staged change       -> expected under --staged-only
#   ' ' *  unstaged change     -> fatal under --staged-only; user must stage
#                                 it, or pass --all-tracked to adopt it
STATUS="$(git status --porcelain || true)"

UNTRACKED="$(printf '%s\n' "$STATUS" | grep '^??' || true)"
CONFLICTS="$(printf '%s\n' "$STATUS" | grep -E '^(U.|.U)' || true)"
UNSTAGED="$(printf '%s\n' "$STATUS" | grep -v '^??' | grep -vE '^(U.|.U)' | grep -E '^.[^ ]' || true)"

[ -z "$CONFLICTS" ] || { printf '%s\n' "$CONFLICTS" >&2; die "unmerged conflicts present. Resolve them before shipping."; }

if [ "$SCOPE" = "staged-only" ] && [ -n "$UNSTAGED" ]; then
  printf '%s\n' "$UNSTAGED" >&2
  die "tracked files have UNSTAGED changes (listed above).
       Stage what you mean to ship (git add <path>), or pass --all-tracked
       to adopt every tracked modification. This script will not guess."
fi

[ -z "$UNTRACKED" ] || warn "$(printf '%s\n' "$UNTRACKED" | grep -c . || true) untracked entr(ies) will NOT be committed."

if [ "$SCOPE" = "all-tracked" ] && [ -n "$(printf '%s\n' "$STATUS" | grep -v '^??' | grep -E '^[^ ]' || true)" ]; then
  warn "--all-tracked: committing every tracked modification, not just staged ones."
  printf '%s\n' "$STATUS" | grep -v '^??' | grep -E '^[^ ]' | sed 's/^/warn:  will commit: /' >&2
fi
ok "worktree hygiene checked (scope: $SCOPE)"

# --- 2. commit ---------------------------------------------------------------
if [ -n "$MSG" ]; then
  case "$SCOPE" in
    all-tracked) git add -u -- . || die "git add -u failed" ;;
    staged-only) : ;;  # respect the index exactly as the caller left it
  esac

  if git diff --cached --quiet; then
    die "nothing staged to commit. Stage the files you want to ship first."
  fi

  if ! git commit -q -m "$MSG"; then
    warn "commit failed — a pre-commit hook may have rewritten files."
    warn "re-staging hook-modified files and retrying once."
    # Pick up hook edits to tracked files only (-u). Never -A: untracked files
    # are not ours to ship, and adding them here is how unrelated work rides
    # along in a commit nobody reviewed.
    git add -u -- . || die "re-stage failed"
    if ! git commit -q -m "$MSG"; then
      die "commit still failing after a re-stage. Inspect the hooks directly:
       SKIP=commit git commit -m '$MSG'"
    fi
    warn "second attempt succeeded after the hook rewrote files."
  fi
  ok "committed: $(git log --oneline -1)"
else
  # Omitting the message means "ship what is already committed". If there is
  # staged-but-uncommitted work, that is NOT what the caller meant — and pushing
  # anyway is exactly how an empty branch gets published and reported as success.
  # Observed for real on 2026-10-03 with this script.
  if ! git diff --cached --quiet; then
    warn "no commit message given, but there IS staged work:"
    git diff --cached --name-status | sed 's/^/warn:  /' >&2
    die "pass a commit message to ship this, or unstage it (git reset) to push
         only what is already committed."
  fi
  warn "no commit message given — shipping already-committed work only"
fi

# A commit may still be pending if hooks are async; HEAD is the source of truth.
LOCAL_SHA="$(git rev-parse HEAD)"

# --- 3. push -----------------------------------------------------------------
if [ "$DRY_RUN" = "1" ]; then
  warn "DRY_RUN=1 — skipping push and verification"
  exit 0
fi

git push -u "$REMOTE" "$BRANCH" || die "push failed"

# --- 4. verify the remote actually has it ------------------------------------
REMOTE_SHA="$(git ls-remote "$REMOTE" "refs/heads/$BRANCH" | cut -f1 || true)"
[ -n "$REMOTE_SHA" ] || die "branch '$BRANCH' does not exist on $REMOTE after push!"

if [ "$REMOTE_SHA" != "$LOCAL_SHA" ]; then
  die "REMOTE MISMATCH!
       local  HEAD: $LOCAL_SHA
       remote     : $REMOTE_SHA
       The push did not deliver this commit. Do not report success."
fi

ok "VERIFIED: $REMOTE/$BRANCH == $(git rev-parse --short HEAD) (remote matches local HEAD)"
