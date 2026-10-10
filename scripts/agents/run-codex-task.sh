#!/usr/bin/env bash
# run-codex-task.sh — drive Codex CLI on a scoped task inside an isolated CONTAINER.
# Usage: scripts/agents/run-codex-task.sh "implement X in the doc module"
# Codex auth: host ~/.codex/auth.json (copied read/write into the container per run).
# See .claude/rules/codex-agent.md + .claude/plans/2026-06-05-codex-cli-phase-a-plan.md.
# Supervised mode (Repair Bay attempt-owned lifecycle):
#   CODEX_ATTEMPT_ID=<UUID> CODEX_TASK_ID=<int> CODEX_SUPERVISED=1
#   Creates container with attempt-owned labels, waits for start barrier,
#   starts container, waits for completion, leaves evidence for supervisor.
set -euo pipefail

# Ensure gh CLI is reachable in cron's restricted PATH.
export PATH="/home/kytran/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

REPO="/mnt/archie_brain"
CFG="$REPO/config/agents/codex.yaml"
TASK="${1:?usage: run-codex-task.sh \"<scoped task>\"}"
SLUG="$(echo "$TASK" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9-' | cut -c1-40)"
BRANCH="codex/$SLUG-$(date +%s)"
WT_BASE="${CODEX_WT_BASE:-/mnt/codex-wt}"
WT="$WT_BASE/$BRANCH"
START=$(date +%s%3N)

# Supervised mode (attempt-owned lifecycle) — set by codex-delegation-worker.py
ATTEMPT_ID="${CODEX_ATTEMPT_ID:-}"
TASK_ID="${CODEX_TASK_ID:-}"
SUPERVISED="${CODEX_SUPERVISED:-0}"
if [ "$SUPERVISED" = "1" ]; then
    [ -n "$ATTEMPT_ID" ] || { echo "SUPERVISED=1 requires CODEX_ATTEMPT_ID"; exit 3; }
    [ -n "$TASK_ID" ] || { echo "SUPERVISED=1 requires CODEX_TASK_ID"; exit 3; }
    echo "$ATTEMPT_ID" | grep -Eq '^[0-9a-f-]{36}$' || { echo "Invalid ATTEMPT_ID format"; exit 3; }
    echo "$TASK_ID" | grep -Eq '^[0-9]+$' || { echo "Invalid TASK_ID format"; exit 3; }
fi

# containerized-exec config
CODEX_IMG="archie_brain-archie_codex:latest"
NET="archie_network"
GATEWAY_URL="http://archie_mcp_gateway:7800/mcp"
BEARER_FILE="$REPO/secrets/codex/mcp_bearer.txt"
CODEX_HOME_SRC="${CODEX_HOME:-$HOME/.codex}"
CODEX_RUN_HOME="${XDG_CACHE_HOME:-$HOME/.cache}/codex-run/$BRANCH"

# Attempt-owned Docker lifecycle paths (supervisor-owned directory)
if [ "$SUPERVISED" = "1" ]; then
    SUPERVISOR_DIR="/run/user/$(id -u)/codex-attempt-${ATTEMPT_ID}"
    mkdir -p "$SUPERVISOR_DIR"
    chmod 700 "$SUPERVISOR_DIR"
    CIDFILE="$SUPERVISOR_DIR/container.cid"
    START_BARRIER="$SUPERVISOR_DIR/start.barrier"
    STOP_SIGNAL="$SUPERVISOR_DIR/stop.signal"
    CONTAINER_NAME="archie-codex-${ATTEMPT_ID}"
    HOST_BOOT_ID="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null | tr -d '\n' || echo unknown)"
    HOST_ID="$(hostname)"
else
    SUPERVISOR_DIR=""
    CIDFILE=""
    START_BARRIER=""
    STOP_SIGNAL=""
    CONTAINER_NAME=""
    HOST_BOOT_ID=""
    HOST_ID=""
fi

# 1) fresh worktree off origin/main
cd "$REPO"
git fetch origin -q

prune_main_repo() {
    if [ -e "$REPO/.git/worktrees/archie_sandbox" ] && [ ! -e /mnt/archie_sandbox ]; then
        echo "guard: sandbox registration present but /mnt/archie_sandbox not visible here — skipping worktree prune"
    else
        git worktree prune 2>/dev/null || true
    fi
}
prune_main_repo

# Safe pruning: exclude worktrees for active/blocked/UNKNOWN Codex attempts.
# FAIL CLOSED on DB errors — if we can't determine active worktrees, DO NOT prune.
if [ "$SUPERVISED" = "1" ]; then
    echo "Supervised mode: skipping age-based worktree pruning (worker manages lifecycle)"
else
    while IFS='=' read -r _k _v; do export "$_k=$_v"; done < <(grep -E '^(DB_PORT|DB_NAME|DB_USER|DB_PASSWORD)=' "$REPO/.env")
    export DB_HOST=192.168.1.200
    ACTIVE_BRANCHES="$(cd "$REPO/platform_v2" && python3 << 'PYEOF'
import sys
sys.path.insert(0, '/app')
sys.path.insert(0, '/mnt/archie_brain')
from database import get_db_cursor
try:
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT metadata->>'codex_branch'
            FROM unified_tasks
            WHERE status IN ('in_progress', 'review', 'blocked')
              AND metadata ? 'codex_branch'
              AND metadata->>'codex_branch' IS NOT NULL
              AND metadata->>'codex_branch' != ''
        """)
        for row in cur.fetchall():
            if row[0]:
                print(row[0])
except Exception:
    print('__PRUNE_DISABLED__')
PYEOF
 2>/dev/null || echo '__PRUNE_DISABLED__')"
    if echo "$ACTIVE_BRANCHES" | grep -q '__PRUNE_DISABLED__'; then
        echo "DB query failed — disabling age-based pruning (fail closed)"
    else
        # Worktrees are at $WT_BASE/codex/<branch> — search there, not at parent
        CODEX_WT_DIR="$WT_BASE/codex"
        if [ -n "$ACTIVE_BRANCHES" ] && [ -d "$CODEX_WT_DIR" ]; then
            EXCLUDE_NAMES=()
            while IFS= read -r branch; do
                [ -n "$branch" ] && EXCLUDE_NAMES+=(-not -name "$branch")
            done <<< "$ACTIVE_BRANCHES"
            echo "Preserving worktrees for active/blocked Codex attempts: $(echo "$ACTIVE_BRANCHES" | tr '\n' ' ')"
            find "$CODEX_WT_DIR" -maxdepth 1 -mindepth 1 -type d -mtime +3 "${EXCLUDE_NAMES[@]}" -exec rm -rf {} + 2>/dev/null || true
        elif [ -d "$CODEX_WT_DIR" ]; then
            find "$CODEX_WT_DIR" -maxdepth 1 -mindepth 1 -type d -mtime +3 -exec rm -rf {} + 2>/dev/null || true
        fi
    fi
    prune_main_repo
fi

mkdir -p "$WT_BASE"
git worktree add -B "$BRANCH" "$WT" origin/main >/dev/null

# 2) preflight: worktree must be clean
[ -z "$(git -C "$WT" status --porcelain)" ] || { echo "preflight: worktree dirty"; exit 2; }

# 3) CONTEXT LAYER #2 — inject relevant KB excerpts
KB_CONTEXT="$(docker exec archie_mcp_gateway python3 -c "
import asyncio, sys
from mcp_server.tools.knowledge import search_knowledge_handler
async def m():
    r = await search_knowledge_handler({'query': sys.argv[1], 'limit': 5})
    for x in (r.get('results') or [])[:5]:
        t=str(x.get('title')); c=str(x.get('content'))[:160].replace(chr(10),' ')
        print('- ['+str(x.get('type'))+'] '+t+': '+c)
asyncio.run(m())
" "$TASK" 2>/dev/null || true)"

# 3b) CONTEXT LAYER #1 + #3 — build the prompt
ASSIGN="You are coding in the A.R.C.H.I.E. platform (Kytran Empowerment civic-intelligence cluster).
GROUND YOURSELF FIRST, then make the smallest correct change:
- Read in the worktree: CLAUDE.md, the relevant file(s) under .claude/rules/, and the
  module's entry in docs/generated/module-capability-index.md.
- You have a read-only MCP server 'archie_kb' — call search_knowledge / search_mistakes /
  recall_context to ground the change in real platform patterns + prior decisions.

Relevant knowledge base excerpts for this task:
${KB_CONTEXT:-(none returned)}

Edit ONLY files under the allowed Applications/Concepts paths in config/agents/codex.yaml.
Do NOT touch secrets, infra, deploy, or unrelated files.

Task: $TASK"

# 3c) per-run CODEX_HOME (mode 700): writable auth.json copy + MCP config + bearer
mkdir -p "$CODEX_RUN_HOME"
chmod 700 "$CODEX_RUN_HOME"
install -m 600 "$CODEX_HOME_SRC/auth.json" "$CODEX_RUN_HOME/auth.json"
( umask 077
  cat > "$CODEX_RUN_HOME/config.toml" <<EOF
[projects."$WT"]
trust_level = "trusted"

[mcp_servers.archie_kb]
url = "$GATEWAY_URL"
bearer_token_env_var = "ARCHIE_KB_BEARER"
EOF
  printf 'ARCHIE_KB_BEARER=%s\n' "$(cat "$BEARER_FILE")" > "$CODEX_RUN_HOME/codex.env"
)

# 4) run Codex INSIDE the container — attempt-owned lifecycle (create/start/wait/cleanup)
CODEX_EXIT=0
CODEX_OUT=""

DOCKER_ARGS=(
    --network "$NET"
    --user "$(id -u):$(id -g)"
    -v "$WT":"$WT":rw
    -v "$REPO/.git":"$REPO/.git":ro
    -v "$CODEX_RUN_HOME":/codex-home:rw
    -e HOME=/codex-home -e CODEX_HOME=/codex-home
    --env-file "$CODEX_RUN_HOME/codex.env"
    -w "$WT"
    --read-only --tmpfs /tmp:size=64m
    --memory 2g --cpus 2 --cap-drop ALL
)

if [ "$SUPERVISED" = "1" ]; then
    LABELS=(
        --label "codex.attempt.id=${ATTEMPT_ID}"
        --label "codex.task.id=${TASK_ID}"
        --label "codex.host.id=${HOST_ID}"
        --label "codex.host.boot_id=${HOST_BOOT_ID}"
    )
    if ! docker create \
        "${DOCKER_ARGS[@]}" \
        "${LABELS[@]}" \
        --cidfile "$CIDFILE" \
        --name "$CONTAINER_NAME" \
        "$CODEX_IMG" \
        exec --dangerously-bypass-approvals-and-sandbox "$ASSIGN" >/dev/null; then
        echo "FAIL: docker create exited with code $?"
        exit 4
    fi

    [ -f "$CIDFILE" ] || { echo "FAIL: cidfile not created at $CIDFILE"; exit 4; }
    CREATED_CID="$(cat "$CIDFILE" | tr -d '\n')"
    [ -n "$CREATED_CID" ] || { echo "FAIL: empty container ID in cidfile"; exit 4; }
    echo "Created container $CREATED_CID (attempt $ATTEMPT_ID, task $TASK_ID)"

    # Start/stop race: check stop signal at TOP of loop, always
    BARRIER_TIMEOUT=60
    echo "Waiting for start barrier at $START_BARRIER..."
    while true; do
        # STOP CHECK FIRST — always check before barrier
        if [ -f "$STOP_SIGNAL" ]; then
            echo "Stop signal received — leaving container for supervisor"
            # Leave container and ALL evidence for supervisor
            exit 5
        fi
        if [ -f "$START_BARRIER" ]; then
            echo "Start barrier present — starting container"
            break
        fi
        BARRIER_TIMEOUT=$((BARRIER_TIMEOUT - 1))
        if [ "$BARRIER_TIMEOUT" -le 0 ]; then
            echo "FAIL: start barrier timeout — leaving container for supervisor"
            # Leave container and ALL evidence for supervisor
            exit 6
        fi
        sleep 1
    done
    echo "Starting container"

    docker start "$CONTAINER_NAME" >/dev/null
    CONTAINER_EXIT_CODE="$(docker wait "$CONTAINER_NAME" 2>/dev/null || echo 255)"
    CODEX_EXIT=$CONTAINER_EXIT_CODE
    CODEX_OUT="$(docker logs "$CONTAINER_NAME" 2>&1)" || CODEX_OUT=""

    # Leave ALL evidence for supervisor — do NOT remove container or coordination files
    echo "Container $CONTAINER_NAME exited with code $CODEX_EXIT — evidence left for supervisor at $SUPERVISOR_DIR"

else
    LEGACY_NAME="codex-${BRANCH//\//-}-$(date +%s%N)"
    if ! docker create \
        "${DOCKER_ARGS[@]}" \
        --name "$LEGACY_NAME" \
        "$CODEX_IMG" \
        exec --dangerously-bypass-approvals-and-sandbox "$ASSIGN" >/dev/null; then
        echo "FAIL: docker create (legacy) exited with code $?"
        exit 4
    fi

    docker start "$LEGACY_NAME" >/dev/null
    LEGACY_EXIT_CODE="$(docker wait "$LEGACY_NAME" 2>/dev/null || echo 255)"
    CODEX_EXIT=$LEGACY_EXIT_CODE
    CODEX_OUT="$(docker logs "$LEGACY_NAME" 2>&1)" || CODEX_OUT=""
    docker rm -f "$LEGACY_NAME" >/dev/null 2>&1 || true
fi

printf '%s\n' "$CODEX_OUT"
rm -rf "$CODEX_RUN_HOME"

CODEX_TOKENS=$(printf '%s\n' "$CODEX_OUT" | awk '/tokens used/{getline; gsub(/[^0-9]/,"",$0); if($0!="") v=$0} END{print v+0}')

# 5) scope guard
CHANGED=$( { git -C "$WT" diff --name-only; git -C "$WT" diff --cached --name-only; git -C "$WT" ls-files --others --exclude-standard; } | sort -u )
OUT=$(cd "$REPO/platform_v2" && python3 -c "
import sys, yaml
from services.agents.codex_scope import check_diff_paths
cfg=yaml.safe_load(open('$CFG'))['codex']
bad=check_diff_paths('''$CHANGED'''.split(), cfg)
print('\n'.join(bad))
")
if [ -n "$OUT" ]; then echo "SCOPE VIOLATION (blocked, no PR):"; echo "$OUT"; SUCCESS=false; else SUCCESS=true; fi

# 6) postflight gates
if [ "$SUCCESS" = true ]; then
  git -C "$WT" add -A
  git -C "$WT" diff --cached --check || SUCCESS=false
  PRECOMMIT=""
  if command -v pre-commit >/dev/null 2>&1; then PRECOMMIT="pre-commit"
  elif python3 -m pre_commit --version >/dev/null 2>&1; then PRECOMMIT="python3 -m pre_commit"; fi
  if [ -n "$PRECOMMIT" ]; then
    ( cd "$WT" && $PRECOMMIT run --files $CHANGED ) || true
    git -C "$WT" add -A
    LINT_OUTPUT=""; LINT_RC=0
    LINT_OUTPUT="$( cd "$WT" && $PRECOMMIT run --files $CHANGED 2>&1 )" || LINT_RC=$?
    [ "$LINT_RC" -eq 0 ] || SUCCESS=false
  else
    echo "WARN: pre-commit not found — skipping lint gate; F.O.R.G.E. will review."
  fi
fi

# 7) telemetry
DUR=$(( $(date +%s%3N) - START ))
NFILES=$(echo "$CHANGED" | grep -c . || true)
while IFS='=' read -r _k _v; do export "$_k=$_v"; done < <(grep -E '^(DB_PORT|DB_NAME|DB_USER|DB_PASSWORD)=' "$REPO/.env")
export DB_HOST=192.168.1.200
(cd "$REPO/platform_v2" && python3 -c "
from services.agents.codex_telemetry import record_codex_run
record_codex_run(task_label='''$TASK''', branch='$BRANCH', prompt_tokens=0, completion_tokens=${CODEX_TOKENS:-0},
  model='gpt-5-codex', files_changed='''$CHANGED'''.split(), tests='n/a',
  success=$( [ "$SUCCESS" = true ] && echo True || echo False ), duration_ms=$DUR,
  estimated=$( [ "${CODEX_TOKENS:-0}" -gt 0 ] && echo False || echo True ),
  project_id=376)
")

# 8) outcome: commit + push + auto-open PR + register in Repair Bay
if [ "$SUCCESS" = true ] && [ "$NFILES" -gt 0 ]; then
  git -C "$WT" commit -q -m "feat(codex): $TASK"
  git -C "$WT" push --no-verify -u origin "$BRANCH"
  PR_CREATE_OUT="$(gh pr create \
    --head "$BRANCH" \
    --title "feat(codex): $TASK" \
    --body "$(printf '## Codex\n\n- **Task**: %s\n- **Branch**: %s\n\n## Test Plan\n- [ ] F.O.R.G.E. review passes\n- [ ] Deploy via \`/merge-pr\` after approval\n\n🤖 Codex CLI — auto-generated, review via Repair Bay → PR Review' "$TASK" "$BRANCH")" \
    2>&1)" && PR_RC=0 || PR_RC=$?
  PR_URL="$(printf '%s\n' "$PR_CREATE_OUT" | tail -1)"
  PR_NUM="$(echo "$PR_URL" | grep -oE '[0-9]+$')"
  if [ "${PR_RC:-1}" -eq 0 ] && [ -n "$PR_NUM" ]; then
    echo "PR #${PR_NUM} created: $PR_URL"
    (docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.repair_bay.services.pr_review_service import poll_open_prs, get_review
from tools.repair_bay.services.pr_diff_analyzer import review_pr
pr = ${PR_NUM}
poll_open_prs()
r = get_review(pr)
print('Repair Bay:', 'tracked' if r else 'WARNING: not found')
review_pr(pr)
print('F.O.R.G.E. review queued for PR #' + str(pr))
" 2>/dev/null || echo "WARN: Repair Bay/F.O.R.G.E. registration failed (non-fatal)") &
    echo "F.O.R.G.E. analysis queued (background) — check Repair Bay → PR Review."
  else
    echo "ERROR: auto-PR creation FAILED for pushed branch $BRANCH (gh rc=${PR_RC:-?}): $PR_CREATE_OUT"
    (cd "$REPO/platform_v2" && python3 - "$TASK" "$BRANCH" "pr_create_failed" "branch pushed but gh pr create failed (rc=${PR_RC:-?}): $PR_CREATE_OUT" <<'PY'
import sys
from services.agents.codex_telemetry import notify_codex_stuck
task, branch, reason, detail = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
r = notify_codex_stuck(task_label=task, branch=branch, failure_reason=reason, error_detail=detail)
print('F.O.R.G.E. escalation:', r.get('success'), '| task_id:', r.get('task_id', 'n/a'))
PY
    ) || echo "WARN: F.O.R.G.E. escalation call failed (non-fatal)"
  fi
else
  echo "Run blocked or no changes — branch $BRANCH left for inspection, no push."
fi
echo "worktree: $WT (remove with: git worktree remove --force $WT)"

# 9) escalation
if [ "$SUCCESS" != true ] || [ "$NFILES" -eq 0 ]; then
  _FAIL_REASON="unknown"
  _FAIL_DETAIL=""
  if [ -n "${OUT:-}" ]; then
    _FAIL_REASON="scope_violation"
    _FAIL_DETAIL="$OUT"
  elif [ "${LINT_RC:-0}" -ne 0 ]; then
    _FAIL_REASON="lint_failure"
    _FAIL_DETAIL="${LINT_OUTPUT:-pre-commit pass 2 failed}"
  elif [ "${CODEX_EXIT:-0}" -ne 0 ]; then
    _FAIL_REASON="codex_exit_nonzero"
    _FAIL_DETAIL="Codex container exited $CODEX_EXIT"
  else
    _FAIL_REASON="no_changes_made"
    _FAIL_DETAIL="Codex completed but modified 0 files — task may be already done or model got stuck"
  fi
  (cd "$REPO/platform_v2" && python3 - "$TASK" "$BRANCH" "$_FAIL_REASON" "$_FAIL_DETAIL" <<'PY'
import sys
from services.agents.codex_telemetry import notify_codex_stuck
task, branch, reason, detail = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
r = notify_codex_stuck(task_label=task, branch=branch, failure_reason=reason, error_detail=detail)
print('F.O.R.G.E. escalation:', r.get('success'), '| task_id:', r.get('task_id', 'n/a'))
PY
  ) || echo "WARN: F.O.R.G.E. escalation call failed (non-fatal)"
fi
