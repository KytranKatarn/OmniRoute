#!/usr/bin/env bash
# Run one scoped task in the opencode lane and ship the result — WITHOUT putting a
# credential in the lane. #6736.
#
# THE SPLIT: the container edits, the HOST verifies and ships. This mirrors
# run-codex-task.sh, and for the same reason — opencode/Dockerfile.terminal is explicit
# that the container is the isolation boundary ("no host filesystem, no platform DB
# credentials, its own volumes, cap_drop ALL"), and a third-party binary is exactly the
# thing you do not hand a GitHub token. Measured 2026-09-12: inside the lane both
# `git fetch` and `git push` fail with "could not read Username for github.com", which
# is the design working, not a fault.
#
# archie_engine takes the other road (holds a scoped ARCHIE_GITHUB_TOKEN, refreshes
# itself). Reasonable for OUR code; a different calculus for a vendored binary. Keeping
# opencode credential-free leaves that decision open rather than making it by default.
#
# NEVER MERGES. Pushes a branch and opens a PR; a human runs /merge-pr after F.O.R.G.E.
# approves — same rule as the codex runner.
#
# Usage: scripts/agents/run-opencode-task.sh "<scoped task>"

set -euo pipefail

REPO="/mnt/archie_brain"
CFG="$REPO/config/agents/opencode.yaml"
CONTAINER="${CONTAINER:-archie_opencode_terminal}"
LANE_REPO="${LANE_REPO:-/work/archie-platform}"
TASK="${1:?usage: run-opencode-task.sh \"<scoped task>\"}"
SLUG="$(echo "$TASK" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9-' | cut -c1-40)"
# A commit SUBJECT, not the whole prompt. The first run shipped a subject that was
# the entire multi-sentence task ("Add a pure function parse_duration... Run the
# tests yourself with: cd ... Only modify those two files."), which is unreadable
# in `git log --oneline`, in the PR list and in every blame view thereafter. Take
# the first sentence, cap it, and keep the full task in the commit BODY where the
# detail belongs.
SUBJECT="$(printf '%s' "$TASK" | sed 's/\. .*//' | cut -c1-64)"
BRANCH="opencode/$SLUG-$(date +%s)"
# Default under the user cache, not /mnt: creating a directory at /mnt needs root,
# and a runner that cannot run unprivileged is a runner nobody runs. (The codex
# runner uses /mnt/codex-wt, which works only because that dir was created once by
# hand — a dependency invisible until it bites.) Override with OPENCODE_WT_BASE.
WT_BASE="${OPENCODE_WT_BASE:-${XDG_CACHE_HOME:-$HOME/.cache}/opencode-wt}"
WT="$WT_BASE/$BRANCH"
START=$(date +%s%3N)
TIMEOUT="${OPENCODE_TASK_TIMEOUT:-1800}"

# Run git in the lane as the user the lane ACTUALLY runs as. Reading it from the
# container rather than assuming is load-bearing: the whole #6736 bug was a uid
# mismatch, and `docker exec -u node` succeeds where the real lane user failed, so a
# check run as the wrong user reports the lane healthy.
LANE_UID="$(docker inspect "$CONTAINER" --format '{{.Config.User}}')"; LANE_UID="${LANE_UID:-0}"
lane()     { docker exec -u "$LANE_UID" "$CONTAINER" "$@"; }
lane_git() { lane git -C "$LANE_REPO" "$@"; }

# ---------------------------------------------------------------------------
# 1) preflight — the lane must be clean and current, or the patch will not apply
# ---------------------------------------------------------------------------
if [ -n "$(lane_git status --porcelain)" ]; then
    echo "REFUSING: the lane has uncommitted work from a previous run:" >&2
    lane_git status --porcelain | sed 's/^/    /' >&2
    echo "Collect or discard it first (scripts/agents/opencode-lane-sync.sh --force)." >&2
    exit 2
fi
"$REPO/scripts/agents/opencode-lane-sync.sh"
BASE_SHA="$(lane_git rev-parse HEAD)"

# ---------------------------------------------------------------------------
# 2) run the task in the lane
# ---------------------------------------------------------------------------
# `timeout` bounds a wedged model; without it a stuck run holds the single-seat lane
# open indefinitely (ttyd --max-clients 1).
OC_EXIT=0
OC_OUT="$(lane sh -c "cd $LANE_REPO && timeout $TIMEOUT opencode run \"\$1\"" _ "$TASK" 2>&1)" || OC_EXIT=$?
printf '%s\n' "$OC_OUT" | tail -25

# ---------------------------------------------------------------------------
# 3) collect what changed — INCLUDING new files
# ---------------------------------------------------------------------------
# `git diff --name-only` lists only modified TRACKED files, so a task that CREATES a
# file (most useful tasks: "add tests/...") would yield an empty list, the work would be
# dropped as "no changes", AND the new file would bypass the scope check entirely. Stage
# everything first so both the listing and the patch include untracked files. This is
# the same trap the codex runner documents.
lane_git add -A
CHANGED="$(lane_git diff --cached --name-only)"
NFILES="$(printf '%s\n' "$CHANGED" | grep -c . || true)"

if [ "$NFILES" -eq 0 ]; then
    echo "opencode made no changes (exit $OC_EXIT) — nothing to ship."
    lane_git reset -q
    exit 0
fi

# ---------------------------------------------------------------------------
# 4) scope guard (deny-by-default) — BEFORE the work touches a branch
# ---------------------------------------------------------------------------
# Same guard as codex: one implementation, two configs, so they cannot drift apart.
OUT="$(cd "$REPO/platform_v2" && CHANGED="$CHANGED" CFG="$CFG" python3 -c "
import os, sys, yaml
from services.agents.codex_scope import check_diff_paths
cfg = yaml.safe_load(open(os.environ['CFG']))['opencode']
print('\n'.join(check_diff_paths(os.environ['CHANGED'].split(), cfg)))
")"
if [ -n "$OUT" ]; then
    echo "SCOPE VIOLATION (blocked, no PR):" >&2
    printf '%s\n' "$OUT" | sed 's/^/    /' >&2
    lane_git reset -q
    exit 3
fi

MAX_FILES="$(grep -E '^\s+max_files_changed:' "$CFG" | grep -oE '[0-9]+' | head -1)"
if [ "$NFILES" -gt "${MAX_FILES:-25}" ]; then
    echo "REFUSING: $NFILES files changed, cap is ${MAX_FILES:-25}" >&2
    lane_git reset -q
    exit 3
fi

# ---------------------------------------------------------------------------
# 5) carry the work out as a patch, onto a fresh worktree off the SAME base
# ---------------------------------------------------------------------------
# --binary so a non-text file survives the round trip. Branching from BASE_SHA (what the
# lane actually edited) rather than origin/main means the patch applies to the tree it
# was written against, even if main moved while the model was thinking.
PATCH="$(mktemp -t opencode-XXXXXX.patch)"
trap 'rm -f "$PATCH"' EXIT
lane_git diff --cached --binary > "$PATCH"

# ACTUALLY clean the lane. `git reset` (mixed) only UNSTAGES — the working-tree
# changes survive, so the next run's preflight sees a dirty lane and refuses. Found
# by simply trying to run twice: the runner could not. The work is already captured
# in $PATCH and about to be committed to a branch, so discarding the lane's copy is
# safe; `clean -fd` is needed as well because reset --hard leaves untracked files
# (and a "create tests/..." task produces exactly those).
lane_git reset --hard -q HEAD
lane_git clean -fdq

mkdir -p "$WT_BASE"
git -C "$REPO" worktree add -q -b "$BRANCH" "$WT" "$BASE_SHA"
git -C "$WT" apply --index "$PATCH"

SUCCESS=true

# ---------------------------------------------------------------------------
# 6) postflight gates
# ---------------------------------------------------------------------------
git -C "$WT" diff --cached --check || SUCCESS=false

# Two-pass pre-commit: the FIRST pass may REFORMAT (black, end-of-file-fixer) and exit
# non-zero, which is benign — re-stage and require a CLEAN SECOND pass, which still
# catches real errors (flake8, the K.I.N. single-writer and V.I.G.I.L. dispatch
# guardrails, timezone drift, secrets). Both of opencode's shipped commits today needed
# pass 1 to reformat, so without this every one of them would have been blocked.
if [ "$SUCCESS" = true ]; then
    PRECOMMIT=""
    if command -v pre-commit >/dev/null 2>&1; then PRECOMMIT="pre-commit"
    elif python3 -m pre_commit --version >/dev/null 2>&1; then PRECOMMIT="python3 -m pre_commit"; fi
    if [ -n "$PRECOMMIT" ]; then
        ( cd "$WT" && $PRECOMMIT run --files $CHANGED ) || true   # pass 1: reformat allowed
        git -C "$WT" add -A
        LINT_RC=0
        ( cd "$WT" && $PRECOMMIT run --files $CHANGED ) || LINT_RC=$?
        [ "$LINT_RC" -eq 0 ] || SUCCESS=false                      # pass 2: must be clean
    else
        # F.O.R.G.E. reviews every PR regardless, so a missing local linter must not
        # block delivery — this is what stranded a codex task once (#3867).
        echo "WARN: pre-commit not found — skipping lint gate; F.O.R.G.E. will review."
    fi
fi

# ---------------------------------------------------------------------------
# 6b) run the changed TESTS against the patched tree, with the real dependency set
# ---------------------------------------------------------------------------
# The lane has python3 but NOT the platform's dependencies: platform code does
# `from database import get_db_cursor`, so importing any module pulls psycopg2, and
# every module test fails at the import line inside the lane. Measured 2026-09-12 —
# opencode hit exactly this, could not apt/pip/sudo its way out, and correctly
# declined to write assertions it could not verify.
#
# Rather than bloat the lane image with the whole platform requirements set, run the
# tests where those dependencies already exist: a THROWAWAY container from the
# archie_platform image with the WORKTREE mounted at /app. That gives the real
# dependency set AND the patched code, and touches the running platform not at all.
#
#   --network none : these are unit tests; no DB, no egress, nothing to reach
#   :ro            : the gate must not be able to mutate the tree it is judging
#   --noconftest   : tests/conftest.py::_seed_admin_user currently errors for the
#                    WHOLE suite (#6730) — without this every run fails on an
#                    unrelated, pre-existing fixture break
if [ "$SUCCESS" = true ]; then
    TEST_FILES="$(printf '%s\n' "$CHANGED" | grep -E '^platform_v2/tests/.*\.py$' | sed 's|^platform_v2/||' || true)"
    if [ -n "$TEST_FILES" ]; then
        PLATFORM_IMG="${PLATFORM_IMG:-$(docker inspect archie_platform --format '{{.Config.Image}}' 2>/dev/null)}"
        if [ -n "$PLATFORM_IMG" ]; then
            echo "running changed tests in $PLATFORM_IMG against the patched tree:"
            printf '%s\n' "$TEST_FILES" | sed 's/^/    /'
            # Capture docker's OWN exit status. A `| tail` pipe returns tail's status,
            # so a piped form would report a FAILING suite as a pass — the same trap
            # this runner already guards for `gh pr create`. Verified: a deliberately
            # broken assertion exits non-zero here and reads 0 through a pipe.
            TEST_RC=0
            docker run --rm -v "$WT/platform_v2":/app:ro -w /app --network none \
                "$PLATFORM_IMG" python3 -m pytest $TEST_FILES -q --noconftest \
                -p no:cacheprovider || TEST_RC=$?
            if [ "$TEST_RC" -ne 0 ]; then
                echo "TESTS FAILED (exit $TEST_RC) — no PR." >&2
                SUCCESS=false
            fi
        else
            # Never silently skip a verification gate: say so, loudly.
            echo "WARN: archie_platform image not resolvable — changed tests NOT executed." >&2
        fi
    fi
fi

# ---------------------------------------------------------------------------
# 7) telemetry (always) — the lane's work must be as visible as anyone else's
# ---------------------------------------------------------------------------
DUR=$(( $(date +%s%3N) - START ))
while IFS='=' read -r _k _v; do export "$_k=$_v"; done < <(grep -E '^(DB_PORT|DB_NAME|DB_USER|DB_PASSWORD)=' "$REPO/.env")
export DB_HOST=192.168.1.200
(cd "$REPO/platform_v2" && TASK="$TASK" BRANCH="$BRANCH" CHANGED="$CHANGED" python3 -c "
import os
from services.agents.codex_telemetry import record_codex_run
record_codex_run(task_label=os.environ['TASK'], branch=os.environ['BRANCH'],
  prompt_tokens=0, completion_tokens=0, model='opencode/auto/coding:free',
  files_changed=os.environ['CHANGED'].split(), tests='n/a',
  success=$( [ "$SUCCESS" = true ] && echo True || echo False ), duration_ms=$DUR,
  estimated=True, project_id=380)
") || echo "WARN: telemetry insert failed (non-fatal)"

# ---------------------------------------------------------------------------
# 8) ship — branch + PR only, never a merge
# ---------------------------------------------------------------------------
if [ "$SUCCESS" != true ]; then
    echo "GATES FAILED — branch left at $WT for inspection, no PR opened." >&2
    exit 1
fi

git -C "$WT" commit -q -m "feat(opencode): $SUBJECT

Authored by the opencode lane; verified and shipped by
scripts/agents/run-opencode-task.sh (the lane holds no git credential).

Task as given:
$TASK

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git -C "$WT" push --no-verify -q -u origin "$BRANCH"

# Capture gh's OWN exit status: a `| tail -1` pipe returns tail's status, so a failed
# create would look successful and the pushed branch would strand with no PR — exactly
# how a codex branch was orphaned once.
PR_OUT="$(gh pr create --head "$BRANCH" \
    --title "feat(opencode): $SUBJECT" \
    --body "$(printf '## opencode lane\n\n- **Task**: %s\n- **Branch**: `%s`\n- **Base**: `%s`\n\nAuthored in the sandboxed opencode lane and carried out as a patch by `scripts/agents/run-opencode-task.sh` — the lane holds no git credential in either direction, by design.\n\nScope-checked against `config/agents/opencode.yaml` (deny-by-default) and put through the repo pre-commit gates before this PR was opened.\n\n## Test Plan\n- [ ] F.O.R.G.E. review passes\n- [ ] Merge via `/merge-pr` after approval\n\n🤖 opencode via OmniRoute — review in Repair Bay → PR Review' "$TASK" "$BRANCH" "${BASE_SHA:0:9}")" \
    2>&1)" && PR_RC=0 || PR_RC=$?
PR_URL="$(printf '%s\n' "$PR_OUT" | tail -1)"
PR_NUM="$(echo "$PR_URL" | grep -oE '[0-9]+$')"

if [ "${PR_RC:-1}" -eq 0 ] && [ -n "$PR_NUM" ]; then
    echo "PR #${PR_NUM} created: $PR_URL"
    # Register + queue the diff-grounded review. Backgrounded: review_pr blocks for
    # minutes on a cold model and must not hold the runner open.
    (docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.repair_bay.services.pr_review_service import poll_open_prs, get_review
poll_open_prs()
print('Repair Bay:', 'tracked' if get_review($PR_NUM) else 'WARNING: not found')
from tools.repair_bay.services.pr_diff_analyzer import review_pr
r = review_pr($PR_NUM)
print('F.O.R.G.E.:', r.get('verdict'))
" &) 2>/dev/null
    echo "F.O.R.G.E. review queued — check Repair Bay → PR Review"
else
    # Fail LOUD. A pushed branch with no PR is invisible work.
    echo "ERROR: branch pushed but 'gh pr create' FAILED — $BRANCH is stranded." >&2
    printf '%s\n' "$PR_OUT" | tail -5 >&2
    exit 1
fi
