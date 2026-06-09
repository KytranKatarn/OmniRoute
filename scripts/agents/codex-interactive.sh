#!/usr/bin/env bash
# codex-interactive.sh — Human-in-the-loop Codex session integrated with A.R.C.H.I.E.
#
# Usage:
#   scripts/agents/codex-interactive.sh          # pick from queue
#   scripts/agents/codex-interactive.sh <task_id> # claim a specific task
#
# Run from the ttyd browser terminal at codex.kytranempowerment.com.
# This is the Option B integration: claim a deferred codex_task row from
# unified_tasks, drive it interactively in Codex, then fire the same Telegram
# approve gate + F.O.R.G.E. review as the autonomous loop (codex-delegation-worker.py).
#
# Security invariants (mirrors run-codex-task.sh):
#   * Task reason only reaches Codex as displayed text — never interpolated into SQL.
#   * Only integers (task_id, pr_num) and regex-safe values go into SQL strings.
#   * Custom task insert uses psql -v bind variable, not string interpolation.
#   * NEVER auto-merge — Telegram human approve only (codex_promote).
#   * Scope guard enforced post-session; out-of-scope changes release task to deferred.
set -euo pipefail
export PATH="/home/kytran/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

REPO="/mnt/archie_brain"
CFG="$REPO/config/agents/codex.yaml"
GH="/home/kytran/.local/bin/gh"

# Filled after claim — used by cleanup trap
TASK_ID=""
BRANCH=""
WT=""

cleanup() {
    if [ -n "$WT" ] && [ -d "$WT" ]; then
        git -C "$REPO" worktree remove --force "$WT" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
psql_q() {
    docker exec -i archie_database psql \
        -U archie -d archie -tA -F "|" -c "$1" 2>/dev/null \
        | grep -vE '^(UPDATE|INSERT|DELETE|SELECT|MERGE)[[:space:]]+[0-9]'
}

hr() { printf '%.0s─' {1..68}; echo; }

box() {
    echo ""
    printf '╔══════════════════════════════════════════════════════════════════╗\n'
    printf "║  %-64s  ║\n" "$1"
    printf '╚══════════════════════════════════════════════════════════════════╝\n'
}

# ---------------------------------------------------------------------------
# 1. Pre-flight: verify codex CLI is installed
# ---------------------------------------------------------------------------
if ! command -v codex >/dev/null 2>&1; then
    echo "ERROR: 'codex' CLI not found on PATH."
    echo "Install: npm install -g @openai/codex  then  codex  (sign in once)"
    exit 1
fi

box "A.R.C.H.I.E. × Codex — Interactive Session"
echo ""

# ---------------------------------------------------------------------------
# 2. If a specific task_id was passed, claim it directly
# ---------------------------------------------------------------------------
DIRECT_ID="${1:-}"

if [ -n "$DIRECT_ID" ]; then
    # Validate it looks like an integer
    if ! echo "$DIRECT_ID" | grep -qE '^[0-9]+$'; then
        echo "ERROR: task_id must be a positive integer, got: $DIRECT_ID"
        exit 1
    fi
    CLAIMED=$(psql_q "
        UPDATE unified_tasks SET status='in_progress', updated_at=now()
        WHERE id=${DIRECT_ID}
          AND status='deferred'
          AND delegation_args->>'capability'='codex_task'
        RETURNING id, coalesce(replace(delegation_args->>'reason',E'\n',' '),'');
    ")
    if [ -z "$CLAIMED" ]; then
        echo "Task #${DIRECT_ID} not found, not a codex_task, or already claimed."
        exit 1
    fi
    TASK_ID=$(echo "$CLAIMED" | cut -d'|' -f1)
    TASK_DESC=$(echo "$CLAIMED" | cut -d'|' -f2)
    echo "Claimed task #${TASK_ID}: ${TASK_DESC:0:80}"

# ---------------------------------------------------------------------------
# 3. Otherwise, show the queue and let the user pick
# ---------------------------------------------------------------------------
else
    ROWS=$(psql_q "
        SELECT ut.id,
               coalesce(up.name, ut.project_id::text, 'n/a'),
               coalesce(replace(ut.delegation_args->>'reason', E'\n', ' '), 'untitled')
        FROM unified_tasks ut
        LEFT JOIN unified_projects up ON up.id = ut.project_id::int
        WHERE ut.status = 'deferred'
          AND ut.delegation_args->>'capability' = 'codex_task'
        ORDER BY ut.created_at ASC
        LIMIT 20;
    ")

    declare -a ROW_IDS ROW_DESCS
    TOTAL=0

    if [ -n "$ROWS" ]; then
        echo "Pending Codex tasks:"
        echo ""
        I=1
        while IFS='|' read -r TID PROJ REASON; do
            printf "  [%2d] #%-5s  %-18s  %s\n" \
                "$I" "$TID" "${PROJ:0:18}" "${REASON:0:58}"
            ROW_IDS[$I]="$TID"
            ROW_DESCS[$I]="$REASON"
            I=$((I+1))
        done <<< "$ROWS"
        TOTAL=$((I-1))
        echo ""
        printf "  [ n] Enter a new custom task\n"
    else
        echo "No pending Codex tasks in the queue."
        echo ""
        printf "  [ n] Enter a new custom task (or Ctrl-C to exit)\n"
    fi

    echo ""
    printf "Pick [1]: "
    read -r CHOICE

    if [ "${CHOICE:-1}" = "n" ]; then
        # ---- custom task: insert via psql -v to avoid SQL injection ----
        printf "Task description: "
        read -r TASK_DESC
        if [ -z "$TASK_DESC" ]; then
            echo "No task entered. Exiting."
            exit 0
        fi
        # The -v bind variable prevents the user's text from ever landing in
        # the SQL string (handles quotes, backslashes, etc.).
        TASK_ID=$(docker exec -i archie_database psql \
            -U archie -d archie -tA \
            -v "reason=$TASK_DESC" \
            -c "INSERT INTO unified_tasks
                    (title, status, delegation_args, created_at, updated_at)
                VALUES
                    (substring(:'reason', 1, 80),
                     'in_progress',
                     jsonb_build_object('capability','codex_task','reason',:'reason'),
                     now(), now())
                RETURNING id;" 2>/dev/null | grep -v '^INSERT')
        echo "Created and claimed task #${TASK_ID}"
    else
        N="${CHOICE:-1}"
        if [ "$TOTAL" -eq 0 ]; then
            echo "No tasks to pick from. Use 'n' to enter a custom task."
            exit 0
        fi
        if ! echo "$N" | grep -qE '^[0-9]+$' || [ "$N" -lt 1 ] || [ "$N" -gt "$TOTAL" ]; then
            echo "Invalid choice '$N'. Exiting."
            exit 1
        fi
        TASK_ID="${ROW_IDS[$N]}"
        TASK_DESC="${ROW_DESCS[$N]}"
        # Atomic claim — AND status='deferred' guard prevents racing with the cron worker
        CLAIMED=$(psql_q "
            UPDATE unified_tasks SET status='in_progress', updated_at=now()
            WHERE id=${TASK_ID}
              AND status='deferred'
            RETURNING id;
        ")
        if [ -z "$CLAIMED" ]; then
            echo "Task #${TASK_ID} was already claimed by the autonomous worker."
            echo "Re-run to see updated queue."
            exit 0
        fi
        echo "Claimed task #${TASK_ID}: ${TASK_DESC:0:80}"
    fi
fi

# ---------------------------------------------------------------------------
# 4. Create git worktree off origin/main
# ---------------------------------------------------------------------------
SLUG="$(echo "$TASK_DESC" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9-' | cut -c1-40)"
BRANCH="codex/$SLUG-$(date +%s)"
WT="/tmp/codex-wt/$BRANCH"

cd "$REPO"
git fetch origin -q
git worktree add -B "$BRANCH" "$WT" origin/main >/dev/null
echo "Worktree : $WT"
echo "Branch   : $BRANCH"

# ---------------------------------------------------------------------------
# 5. Show task context panel
# ---------------------------------------------------------------------------
echo ""
hr
echo " Task    : $TASK_DESC"
echo " Branch  : $BRANCH"
echo ""
echo " Allowed paths (scope guard enforces these on exit):"
python3 -c "
import yaml, sys
try:
    cfg = yaml.safe_load(open('$CFG'))
    paths = (cfg.get('codex', cfg) or {}).get('allowed_paths', [])
    for p in paths: print('   ' + p)
except Exception as e:
    print('   (could not parse config: ' + str(e) + ')')
" 2>/dev/null
hr
echo ""
echo "Launching Codex. Build the feature, then exit when done."
echo "F.O.R.G.E. review + Telegram gate fire automatically on clean exit."
echo ""

# ---------------------------------------------------------------------------
# 6. Launch Codex interactively in the worktree (user drives)
# ---------------------------------------------------------------------------
( cd "$WT" && codex ) || true   # non-zero exit is fine — check the actual diff

# ---------------------------------------------------------------------------
# 7. No-op check: if nothing changed, release the task and exit cleanly
# ---------------------------------------------------------------------------
CHANGED=$(git -C "$WT" diff --name-only origin/main 2>/dev/null || true)
NFILES=$(printf '%s' "$CHANGED" | grep -c . || true)

if [ "$NFILES" -eq 0 ]; then
    echo ""
    echo "No files changed — releasing task #${TASK_ID} back to deferred."
    psql_q "UPDATE unified_tasks SET status='deferred', updated_at=now() WHERE id=${TASK_ID};" >/dev/null
    exit 0
fi

echo ""
echo "Changed ($NFILES files):"
echo "$CHANGED"
echo ""

# ---------------------------------------------------------------------------
# 8. Scope guard (deny-by-default — mirrors run-codex-task.sh section 5)
#    SECURITY: never interpolate $CHANGED into Python source — pipe on stdin.
#    A Codex-created file with a crafted name could otherwise escape the
#    triple-quoted string and execute arbitrary code.
# ---------------------------------------------------------------------------
SCOPE_OUT=$(cd "$REPO/platform_v2" && printf '%s\n' $CHANGED | python3 -c "
import sys, yaml
sys.path.insert(0, '.')
from services.agents.codex_scope import check_diff_paths
cfg = yaml.safe_load(open('$CFG'))
codex_cfg = cfg.get('codex', cfg)
files = [l for l in sys.stdin.read().splitlines() if l]
print('\n'.join(check_diff_paths(files, codex_cfg)))
" 2>/dev/null || echo "")

if [ -n "$SCOPE_OUT" ]; then
    echo "⛔  SCOPE VIOLATION — changes outside allowed paths:"
    echo "$SCOPE_OUT"
    echo ""
    echo "Task #${TASK_ID} released to deferred. Fix the paths and re-run."
    psql_q "UPDATE unified_tasks SET status='deferred', updated_at=now() WHERE id=${TASK_ID};" >/dev/null
    exit 1
fi

# ---------------------------------------------------------------------------
# 9. Two-pass pre-commit (mirrors run-codex-task.sh section 6)
#    Pass 1: allow reformat (black, end-of-file-fixer, trailing-whitespace)
#    Pass 2: must be clean — catches real lint / guardrail errors
# ---------------------------------------------------------------------------
git -C "$WT" add -A
git -C "$WT" diff --cached --check || true

PRECOMMIT=""
if command -v pre-commit >/dev/null 2>&1; then
    PRECOMMIT="pre-commit"
elif python3 -m pre_commit --version >/dev/null 2>&1; then
    PRECOMMIT="python3 -m pre_commit"
fi

if [ -n "$PRECOMMIT" ]; then
    ( cd "$WT" && $PRECOMMIT run --files $CHANGED ) || true   # pass 1: reformat OK
    git -C "$WT" add -A                                       # re-stage reformatted files
    LINT_OUTPUT=""
    LINT_RC=0
    LINT_OUTPUT="$( cd "$WT" && $PRECOMMIT run --files $CHANGED 2>&1 )" || LINT_RC=$?
    if [ "$LINT_RC" -ne 0 ]; then
        echo ""
        echo "❌  Pre-commit (pass 2) failed. Fix the issues and re-run:"
        echo "$LINT_OUTPUT"
        echo ""
        echo "Task #${TASK_ID} released to deferred."
        psql_q "UPDATE unified_tasks SET status='deferred', updated_at=now() WHERE id=${TASK_ID};" >/dev/null
        exit 1
    fi
else
    echo "WARN: pre-commit not found — skipping lint gate; F.O.R.G.E. will review."
fi

# ---------------------------------------------------------------------------
# 10. Commit + push + open PR
#     PR_NUM is always grep -oE '[0-9]+$' — digits only, safe to embed as int literal
# ---------------------------------------------------------------------------
git -C "$WT" add -A
git -C "$WT" commit -q -m "feat(codex): $TASK_DESC [interactive]"
git -C "$WT" push --no-verify -u origin "$BRANCH"

PR_URL="$($GH pr create \
    --head "$BRANCH" \
    --title "feat(codex): ${TASK_DESC:0:60} [interactive]" \
    --body "$(printf '## Codex (Interactive)\n\n- **Task #%s**: %s\n- **Branch**: `%s`\n- **Runner**: Human-in-the-loop via ttyd (`codex.kytranempowerment.com`)\n\n## Test Plan\n- [ ] F.O.R.G.E. review passes\n- [ ] Deploy via `/merge-pr` after Telegram approval\n\n🤖 Codex CLI (interactive) — review via Repair Bay → PR Review' \
        "$TASK_ID" "$TASK_DESC" "$BRANCH")" \
    2>&1 | tail -1)"

PR_NUM="$(echo "$PR_URL" | grep -oE '[0-9]+$' || true)"

if [ -z "$PR_NUM" ]; then
    echo ""
    echo "ERROR: PR creation failed. Branch $BRANCH is pushed."
    echo "Open the PR manually, then run:"
    echo "  docker exec archie_platform python3 -c \"..."
    echo "  from services.codex_promote_service import promote_codex_pr"
    echo "  promote_codex_pr(<pr_num>, title='Codex task #${TASK_ID} (interactive)')\""
    psql_q "UPDATE unified_tasks SET status='blocked', updated_at=now() WHERE id=${TASK_ID};" >/dev/null
    exit 1
fi
echo "PR #${PR_NUM} created: $PR_URL"

# ---------------------------------------------------------------------------
# 11. Write PR metadata back to the task row
#     BRANCH is codex/<slug>-<epoch> — alphanumeric+hyphen only (safe literal)
#     PR_NUM is digits-only (safe literal)
# ---------------------------------------------------------------------------
BLOB="{\"codex_pr\":${PR_NUM},\"codex_branch\":\"${BRANCH}\"}"
psql_q "UPDATE unified_tasks
        SET metadata = coalesce(metadata,'{}'::jsonb) || '${BLOB}'::jsonb,
            updated_at = now()
        WHERE id = ${TASK_ID};" >/dev/null

# ---------------------------------------------------------------------------
# 12. Queue Telegram approve gate (same as worker's queue_promote)
# ---------------------------------------------------------------------------
docker exec -i archie_platform python3 -c "
import sys
sys.path[:0]=['/app','/mnt/archie_brain','/mnt/archie_brain/ai_bridge']
from services.codex_promote_service import promote_codex_pr
r = promote_codex_pr(${PR_NUM}, title='Codex task #${TASK_ID} (interactive)')
sent = 'sent' if r.get('button_sent') else 'queued'
print('Telegram: ' + sent + ' | approval_id: ' + str(r.get('approval_id','?')))
" || echo "WARN: Telegram promote failed (non-fatal — check Repair Bay manually)"

# ---------------------------------------------------------------------------
# 13. Register in Repair Bay + trigger F.O.R.G.E. review (background, non-blocking)
# ---------------------------------------------------------------------------
(docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.repair_bay.services.pr_review_service import poll_open_prs, get_review
from tools.repair_bay.services.pr_diff_analyzer import review_pr
pr = ${PR_NUM}
poll_open_prs()
get_review(pr)
review_pr(pr)
print('F.O.R.G.E. review queued for PR #' + str(pr))
" 2>/dev/null || echo "WARN: Repair Bay/F.O.R.G.E. registration failed (non-fatal)") &

# ---------------------------------------------------------------------------
# 14. Summary
# ---------------------------------------------------------------------------
echo ""
box "Session complete — Task #${TASK_ID}"
echo "  Branch : $BRANCH"
echo "  PR     : #${PR_NUM}"
echo "  URL    : $PR_URL"
echo "  Status : in_progress → waiting for Telegram approve"
printf '╚══════════════════════════════════════════════════════════════════╝\n'
echo ""
echo "Tap Approve in Telegram to merge to main."
echo "(Or: /merge-pr ${PR_NUM} after F.O.R.G.E. review completes)"
