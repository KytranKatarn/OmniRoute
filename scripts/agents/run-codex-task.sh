#!/usr/bin/env bash
# run-codex-task.sh — drive Codex CLI on a scoped task inside an isolated CONTAINER.
# Usage: scripts/agents/run-codex-task.sh "implement X in the doc module"
# Codex auth: host ~/.codex/auth.json (copied read/write into the container per run).
# See .claude/rules/codex-agent.md + .claude/plans/2026-06-05-codex-cli-phase-a-plan.md.
# Supervised mode (Repair Bay attempt-owned lifecycle):
#   CODEX_ATTEMPT_ID=<UUID> CODEX_TASK_ID=<int> CODEX_SUPERVISED=1
#   Creates container with attempt-owned labels, waits for start barrier,
#   starts container, waits for completion, cleans up owned resources.
set -euo pipefail

# Ensure gh CLI is reachable in cron's restricted PATH.
export PATH="/home/kytran/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

REPO="/mnt/archie_brain"
CFG="$REPO/config/agents/codex.yaml"
TASK="${1:?usage: run-codex-task.sh \"<scoped task>\"}"
SLUG="$(echo "$TASK" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9-' | cut -c1-40)"
BRANCH="codex/$SLUG-$(date +%s)"
# Codex worktrees live on a dedicated 20G LV, NOT the 2G /tmp tmpfs — a 2G worktree there
# filled /tmp and broke the nightly git-bundle backups (#4045). Override with CODEX_WT_BASE.
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
    # Validate UUID format
    echo "$ATTEMPT_ID" | grep -Eq '^[0-9a-f-]{36}$' || { echo "Invalid ATTEMPT_ID format"; exit 3; }
    # Validate task ID is integer
    echo "$TASK_ID" | grep -Eq '^[0-9]+$' || { echo "Invalid TASK_ID format"; exit 3; }
fi

# containerized-exec config — the container IS the isolation boundary.
CODEX_IMG="archie_brain-archie_codex:latest"
NET="archie_network"
GATEWAY_URL="http://archie_mcp_gateway:7800/mcp"   # read-only MCP gateway (internal)
BEARER_FILE="$REPO/secrets/codex/mcp_bearer.txt"   # the ONLY secret given to Codex
CODEX_HOME_SRC="${CODEX_HOME:-$HOME/.codex}"        # host auth lives here
CODEX_RUN_HOME="${XDG_CACHE_HOME:-$HOME/.cache}/codex-run/$BRANCH"  # per-run HOME (mode 700)

# Attempt-owned Docker lifecycle paths (host-only, supervisor-accessible)
if [ "$SUPERVISED" = "1" ]; then
    CIDFILE="/tmp/codex-attempt-${ATTEMPT_ID}.cid"
    START_BARRIER="/tmp/codex-attempt-${ATTEMPT_ID}.start"
    STOP_SIGNAL="/tmp/codex-attempt-${ATTEMPT_ID}.stop"
    CONTAINER_NAME="archie-codex-${ATTEMPT_ID}"
    HOST_BOOT_ID="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null | tr -d '\n' || echo unknown)"
    HOST_ID="$(hostname)"
else
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
# run-task worktrees are kept for inspection (no exit-cleanup), so reclaim ones older than
# 3 days here — otherwise they slowly fill the dedicated LV (#4045).
#
# Guarded prune (2026-10-07): a blanket `git worktree prune` in this repo deletes ANY
# registration whose worktree dir cannot be statable from the current context — notably
# the /mnt/archie_sandbox registration when running somewhere that path is not mounted
# (this silently broke every Repair Bay sandbox gate for 5 days before diagnosis).
# Skip the prune when that registration exists but the sandbox worktree is invisible here.
prune_main_repo() {
    if [ -e "$REPO/.git/worktrees/archie_sandbox" ] && [ ! -e /mnt/archie_sandbox ]; then
        echo "guard: sandbox registration present but /mnt/archie_sandbox not visible here — skipping worktree prune"
    else
        git worktree prune 2>/dev/null || true
    fi
}
prune_main_repo

# Safe pruning: exclude worktrees for active/UNKNOWN Codex attempts.
# Query DB for tasks in 'in_progress' or 'review' with a codex_branch.
# Those worktrees must not be removed until the attempt is confirmed stopped.
if [ "$SUPERVISED" = "1" ]; then
    # In supervised mode, the worker manages lifecycle; skip age-based pruning entirely
    # to avoid racing with other supervised runs. Worker handles cleanup post-receipt.
    echo "Supervised mode: skipping age-based worktree pruning (worker manages lifecycle)"
else
    # Legacy mode: load DB creds and query for active Codex worktrees
    while IFS='=' read -r _k _v; do export "$_k=$_v"; done < <(grep -E '^(DB_PORT|DB_NAME|DB_USER|DB_PASSWORD)=' "$REPO/.env")
    export DB_HOST=192.168.1.200
    ACTIVE_BRANCHES="$(cd "$REPO/platform_v2" && python3 -c "
import sys, os
sys.path.insert(0, '/app')
sys.path.insert(0, '/mnt/archie_brain')
from database import get_db_cursor
try:
    with get_db_cursor() as (conn, cur):
        cur.execute(\"\"\"
            SELECT metadata->>'codex_branch'
            FROM unified_tasks
            WHERE status IN ('in_progress', 'review')
              AND metadata ? 'codex_branch'
              AND metadata->>'codex_branch' IS NOT NULL
              AND metadata->>'codex_branch' != ''
        \"\"\")
        for row in cur.fetchall():
            if row[0]:
                print(row[0])
except Exception:
    pass  # On any DB error, allow pruning (fail open for legacy)
" 2>/dev/null || true)"
    # Build find command that excludes active branches
    if [ -n "$ACTIVE_BRANCHES" ]; then
        EXCLUDE_ARGS=()
        while IFS= read -r branch; do
            [ -n "$branch" ] && EXCLUDE_ARGS+=(-not -name "$branch")
        done <<< "$ACTIVE_BRANCHES"
        echo "Preserving worktrees for active Codex attempts: $(echo "$ACTIVE_BRANCHES" | tr '\n' ' ')"
        find "$WT_BASE" -maxdepth 1 -mindepth 1 -type d -mtime +3 "${EXCLUDE_ARGS[@]}" -exec rm -rf {} + 2>/dev/null || true
    else
        find "$WT_BASE" -maxdepth 1 -mindepth 1 -type d -mtime +3 -exec rm -rf {} + 2>/dev/null || true
    fi
    prune_main_repo
fi

mkdir -p "$WT_BASE"
git worktree add -B "$BRANCH" "$WT" origin/main >/dev/null

# 2) preflight: worktree must be clean
[ -z "$(git -C "$WT" status --porcelain)" ] || { echo "preflight: worktree dirty"; exit 2; }

# 3) CONTEXT LAYER #2 — inject relevant KB excerpts (host-side, via the read-only
#    gateway container; codex_ro creds stay in the gateway, never reach Codex).
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

# 3b) CONTEXT LAYER #1 + #3 — build the prompt: tell Codex to read the repo rules and
#     to use the live read-only KB tools (archie_kb MCP), then the task.
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

# 3c) per-run CODEX_HOME (mode 700): writable auth.json copy (token refresh) + MCP
#     config + the bearer env-file. All owner-only — never group/world readable.
mkdir -p "$CODEX_RUN_HOME"
chmod 700 "$CODEX_RUN_HOME"
install -m 600 "$CODEX_HOME_SRC/auth.json" "$CODEX_RUN_HOME/auth.json"
( umask 077
  cat > "$CODEX_RUN_HOME/config.toml" <<EOF
[projects."$WT"]
trust_level = "trusted"

# Live read-only knowledge access — Codex holds ONLY this bearer (no DB creds).
[mcp_servers.archie_kb]
url = "$GATEWAY_URL"
bearer_token_env_var = "ARCHIE_KB_BEARER"
EOF
  # bearer via --env-file (mode 600) so it never lands on argv / docker inspect
  printf 'ARCHIE_KB_BEARER=%s\n' "$(cat "$BEARER_FILE")" > "$CODEX_RUN_HOME/codex.env"
)

# 4) run Codex INSIDE the container — attempt-owned lifecycle (create/start/wait/cleanup).
#    In supervised mode: create with labels, wait for start barrier, start, wait, cleanup.
#    In legacy mode: create/start/wait/rm without start barrier.
CODEX_EXIT=0
CODEX_OUT=""

# Build common Docker args
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
    # Supervised: attempt-owned container with labels, cidfile, start barrier
    # Labels encode attempt/task/host/boot identity for recovery
    LABELS=(
        --label "codex.attempt.id=${ATTEMPT_ID}"
        --label "codex.task.id=${TASK_ID}"
        --label "codex.host.id=${HOST_ID}"
        --label "codex.host.boot_id=${HOST_BOOT_ID}"
    )
    # Create container (not start) — persist ID via cidfile for supervisor
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

    # Verify container was created and cidfile written
    [ -f "$CIDFILE" ] || { echo "FAIL: cidfile not created at $CIDFILE"; exit 4; }
    CREATED_CID="$(cat "$CIDFILE" | tr -d '\n')"
    [ -n "$CREATED_CID" ] || { echo "FAIL: empty container ID in cidfile"; exit 4; }
    echo "Created container $CREATED_CID (attempt $ATTEMPT_ID, task $TASK_ID)"

    # Wait for start barrier from supervisor (max 60s)
    BARRIER_TIMEOUT=60
    echo "Waiting for start barrier at $START_BARRIER..."
    while [ ! -f "$START_BARRIER" ]; do
        if [ -f "$STOP_SIGNAL" ]; then
            echo "Stop signal received before start — cleaning up"
            docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
            rm -f "$CIDFILE" "$STOP_SIGNAL" 2>/dev/null || true
            exit 5
        fi
        BARRIER_TIMEOUT=$((BARRIER_TIMEOUT - 1))
        if [ "$BARRIER_TIMEOUT" -le 0 ]; then
            echo "FAIL: start barrier timeout"
            docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
            rm -f "$CIDFILE" 2>/dev/null || true
            exit 6
        fi
        sleep 1
    done
    echo "Start barrier released — starting container"

    # Start the container and wait for completion
    docker start "$CONTAINER_NAME" >/dev/null
    # Capture output via docker wait + logs (docker wait blocks until exit)
    if docker wait "$CONTAINER_NAME" >/dev/null; then
        CODEX_EXIT=0
    else
        CODEX_EXIT=$?
    fi
    CODEX_OUT="$(docker logs "$CONTAINER_NAME" 2>&1)" || CODEX_OUT=""

    # Supervised cleanup: leave container for supervisor to inspect/remove.
    # Supervisor will verify terminal state, write receipt, then remove.
    # Only remove our coordination files.
    rm -f "$CIDFILE" "$START_BARRIER" "$STOP_SIGNAL" 2>/dev/null || true
    # Note: container $CONTAINER_NAME left for supervisor inspection/removal

else
    # Legacy/unsupervised: create/start/wait/rm without start barrier
    # Use a unique container name to avoid collisions
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
    if docker wait "$LEGACY_NAME" >/dev/null; then
        CODEX_EXIT=0
    else
        CODEX_EXIT=$?
    fi
    CODEX_OUT="$(docker logs "$LEGACY_NAME" 2>&1)" || CODEX_OUT=""
    docker rm -f "$LEGACY_NAME" >/dev/null 2>&1 || true
fi

printf '%s\n' "$CODEX_OUT"
rm -rf "$CODEX_RUN_HOME"
# Parse Codex's "tokens used\n<N>" (comma-formatted) so the Consciousness Token Economy
# counts REAL Codex usage (~80k+/run) instead of zeros. Last occurrence wins; 0 if absent.
CODEX_TOKENS=$(printf '%s\n' "$CODEX_OUT" | awk '/tokens used/{getline; gsub(/[^0-9]/,"",$0); if($0!="") v=$0} END{print v+0}')

# 5) scope guard (deny-by-default) — fail the run if anything out of scope changed.
# Include UNTRACKED (new) files: `git diff --name-only` lists only modified TRACKED files,
# so a task that CREATES a file (most of the backlog — "Create tests/...", "Create
# validators.py") yields an EMPTY list → NFILES=0 → step 8 drops real work as "no changes"
# AND the new file silently bypasses this allowlist scope check. Union staged + unstaged +
# untracked, deduped, so new-file tasks are both delivered and scope-checked (#4045 follow-up).
CHANGED=$( { git -C "$WT" diff --name-only; git -C "$WT" diff --cached --name-only; git -C "$WT" ls-files --others --exclude-standard; } | sort -u )
OUT=$(cd "$REPO/platform_v2" && python3 -c "
import sys, yaml
from services.agents.codex_scope import check_diff_paths
cfg=yaml.safe_load(open('$CFG'))['codex']
bad=check_diff_paths('''$CHANGED'''.split(), cfg)
print('\n'.join(bad))
")
if [ -n "$OUT" ]; then echo "SCOPE VIOLATION (blocked, no PR):"; echo "$OUT"; SUCCESS=false; else SUCCESS=true; fi

# 6) postflight gates (only if in scope)
# Two-pass pre-commit: the FIRST pass may REFORMAT files (black, end-of-file-fixer,
# trailing-whitespace) and exit non-zero — that is benign, not a failure. Re-stage
# and require a CLEAN SECOND pass, which still catches real lint/guardrail errors
# (flake8, single-writer, dispatch-signature, timezone, secrets). Without this, any
# Codex change that black touches silently fails the run and never opens a PR.
if [ "$SUCCESS" = true ]; then
  git -C "$WT" add -A
  git -C "$WT" diff --cached --check || SUCCESS=false
  # Resolve pre-commit robustly — the cron PATH may lack the console-script (this is what
  # stranded task #3867: "pre-commit: command not found" → SUCCESS=false → blocked, even
  # though Codex's change was correct). Fall back to `python3 -m pre_commit`; if NEITHER is
  # available, SKIP the lint gate with a warning rather than failing the run — F.O.R.G.E.
  # reviews every PR regardless, so a missing local linter must not block delivery.
  PRECOMMIT=""
  if command -v pre-commit >/dev/null 2>&1; then PRECOMMIT="pre-commit"
  elif python3 -m pre_commit --version >/dev/null 2>&1; then PRECOMMIT="python3 -m pre_commit"; fi
  if [ -n "$PRECOMMIT" ]; then
    ( cd "$WT" && $PRECOMMIT run --files $CHANGED ) || true   # pass 1: reformat allowed
    git -C "$WT" add -A                                        # re-stage reformatted files
    LINT_OUTPUT=""; LINT_RC=0
    LINT_OUTPUT="$( cd "$WT" && $PRECOMMIT run --files $CHANGED 2>&1 )" || LINT_RC=$?
    [ "$LINT_RC" -eq 0 ] || SUCCESS=false  # pass 2: must be clean
  else
    echo "WARN: pre-commit not found (PATH or 'python3 -m pre_commit') — skipping lint gate; F.O.R.G.E. will review."
  fi
fi

# 7) telemetry (always)
DUR=$(( $(date +%s%3N) - START ))
NFILES=$(echo "$CHANGED" | grep -c . || true)
# telemetry runs on the HOST, where the Docker hostname 'archie_database' does not resolve.
# Load DB creds from .env (literal parse, no shell eval — matches docker env_file semantics)
# and point at the host-reachable address (192.168.1.200:5432 is published).
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

# 8) outcome: commit + push + auto-open PR + register in Repair Bay + queue F.O.R.G.E. review
# NEVER merges to main — push branch only; human runs /merge-pr after F.O.R.G.E. approves.
if [ "$SUCCESS" = true ] && [ "$NFILES" -gt 0 ]; then
  git -C "$WT" commit -q -m "feat(codex): $TASK"
  git -C "$WT" push --no-verify -u origin "$BRANCH"
  # Auto-open PR. Capture the FULL output AND gh's own exit status — a `| tail -1` pipe
  # would mask a `gh pr create` failure (the pipe returns tail's status, not gh's), so a
  # failed create would look successful and the pushed branch would strand silently.
  PR_CREATE_OUT="$(gh pr create \
    --head "$BRANCH" \
    --title "feat(codex): $TASK" \
    --body "$(printf '## Codex\n\n- **Task**: %s\n- **Branch**: %s\n\n## Test Plan\n- [ ] F.O.R.G.E. review passes\n- [ ] Deploy via `/merge-pr` after approval\n\n🤖 Codex CLI — auto-generated, review via Repair Bay → PR Review' "$TASK" "$BRANCH")" \
    2>&1)" && PR_RC=0 || PR_RC=$?
  PR_URL="$(printf '%s\n' "$PR_CREATE_OUT" | tail -1)"
  PR_NUM="$(echo "$PR_URL" | grep -oE '[0-9]+$')"
  if [ "${PR_RC:-1}" -eq 0 ] && [ -n "$PR_NUM" ]; then
    echo "PR #${PR_NUM} created: $PR_URL"
    # Register in Repair Bay + trigger diff-grounded F.O.R.G.E. analysis (background — non-blocking).
    # PR_NUM is digits-only (grep -oE '[0-9]+$') so embedding it as a Python int literal is safe.
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
    # The branch is PUSHED but got NO PR (gh pr create failed, or no PR number parsed).
    # Without this branch it strands silently — no F.O.R.G.E. review, no alert — which is
    # exactly how a Codex branch was orphaned before. Fail LOUD: escalate via the same
    # notify_codex_stuck path (fires Telegram to Kytran) so a pushed-but-PR-less branch is
    # always surfaced. Non-fatal — errors here must never crash the run.
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

# 9) escalation: blocked or no-op runs → F.O.R.G.E. via delegation pipeline (fires Telegram)
# Chain: delegate_task(code_review) → delegate_task_worker (≤30s) → DHQ → F.O.R.G.E.
#        → emit_delegation_event → send_info → Telegram notification to Kytran.
# Non-fatal: errors here must never crash the script.
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
  # Pass values as argv — NEVER interpolate into Python source (code injection risk).
  # Heredoc stdin + sys.argv treats every value as pure data regardless of content.
  (cd "$REPO/platform_v2" && python3 - "$TASK" "$BRANCH" "$_FAIL_REASON" "$_FAIL_DETAIL" <<'PY'
import sys
from services.agents.codex_telemetry import notify_codex_stuck
task, branch, reason, detail = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
r = notify_codex_stuck(task_label=task, branch=branch, failure_reason=reason, error_detail=detail)
print('F.O.R.G.E. escalation:', r.get('success'), '| task_id:', r.get('task_id', 'n/a'))
PY
  ) || echo "WARN: F.O.R.G.E. escalation call failed (non-fatal)"
fi
