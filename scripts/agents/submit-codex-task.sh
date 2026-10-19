#!/usr/bin/env bash
# submit-codex-task.sh — host-side command for GF workflow to submit a Codex task.
# Ensures Codex runs in its own isolated container + fresh worktree/branch.
# OpenCode, Claude, and Codex never share a writable checkout or branch.
# Safeguards: atomic lock, safe prune, scope violation blocks, proper error handling,
# cleanup trap, no --no-verify, PR errors reported.
#
# Usage:
#   submit-codex-task.sh "implement X in the doc module"
#
# Outputs the PR URL on success, or error details on failure.
set -euo pipefail

REPO="/mnt/archie_brain"
CFG="$REPO/config/agents/codex.yaml"
TASK="${1:?usage: submit-codex-task.sh \"<scoped task>\"}"
# A leading '-' would be parsed as a Codex CLI option, not as the task text.
case "$TASK" in -*) echo "ERROR: task text must not start with '-'"; exit 2 ;; esac

# ── Collision-safe branch naming ─────────────────────────────────────────────
SLUG="$(echo "$TASK" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9-' | cut -c1-30)"
TIMESTAMP="$(date +%s%N)"
RANDOM_SUFFIX="$(openssl rand -hex 4 2>/dev/null || cat /dev/urandom | tr -dc 'a-z0-9' | head -4)"
BRANCH="codex/${SLUG}-${TIMESTAMP}-${RANDOM_SUFFIX}"

# ── Worktree isolation ───────────────────────────────────────────────────────
WT_BASE="${CODEX_WT_BASE:-/mnt/codex-wt}"
WT="$WT_BASE/$BRANCH"

# ── FIXED LOCK FILE — shared across all invocations ─────────────────────────
# Per-user dir, not a predictable world-writable /tmp path (symlink/squat attacks).
LOCK_DIR="${XDG_RUNTIME_DIR:-$HOME/.cache}"
mkdir -p "$LOCK_DIR"
LOCK_FILE="$LOCK_DIR/codex-task-global.lock"
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "ERROR: Another Codex job is currently running (global lock held)."
    echo "Wait for it to finish, then re-run."
    exit 1
fi

# ── Cleanup trap — runs on ANY exit (success, error, signal) ────────────────
CODEX_RUN_HOME=""
CHANGED_FILE=""
cleanup() {
    [ -z "${CHANGED_FILE:-}" ] || rm -f "$CHANGED_FILE" 2>/dev/null || true
    [ -z "${CODEX_RUN_HOME:-}" ] || rm -rf "$CODEX_RUN_HOME" 2>/dev/null || true
    # Do NOT remove the lock file here; it's held by the fd and released on exit
}
trap cleanup EXIT

# Fetch fresh origin/main
cd "$REPO"
git fetch origin -q >/dev/null 2>&1

# ── Prune old worktrees — FAIL CLOSED on DB errors ─────────────────────────
# If DB query fails, DO NOT prune. Only delete stale worktrees NOT in active list.
# The exit status of the query MUST reach the `if` below: the old `|| true` swallowed it, so a
# failed query looked like "no active branches" and every worktree older than 3 days was deleted.
# Also: the jsonb key was unquoted (a SQL error that always tripped that path), and the
# `-not -name "codex/<slug>"` exclusion could never match (find -name never contains a slash).
if ACTIVE_BRANCHES="$(cd "$REPO/platform_v2" && python3 -c "
import sys
sys.path.insert(0, '/app')
sys.path.insert(0, '/mnt/archie_brain')
from database import get_db_cursor
try:
    with get_db_cursor() as (conn, cur):
        cur.execute('''
            SELECT metadata->>'codex_branch' AS b
            FROM unified_tasks
            WHERE status IN ('in_progress','review','blocked')
              AND metadata ? 'codex_branch'
              AND metadata->>'codex_branch' IS NOT NULL
        ''')
        for row in cur.fetchall():
            b = row['b'] if isinstance(row, dict) else row[0]
            if b:
                print(b)
except Exception:
    sys.exit(1)  # FAIL CLOSED: caller skips the prune
" 2>/dev/null)"; then
    if [ -d "$WT_BASE/codex" ]; then
        EXCLUDE_ARGS=()
        while IFS= read -r branch; do
            [ -n "$branch" ] || continue
            EXCLUDE_ARGS+=(-not -name "${branch#codex/}")  # dir name under $WT_BASE/codex
        done <<< "$ACTIVE_BRANCHES"
        while IFS= read -r -d '' stale; do
            # Unregister from git first; a bare rm -rf leaves a dangling worktree entry.
            git worktree remove --force "$stale" >/dev/null 2>&1 || rm -rf "$stale"
        done < <(find "$WT_BASE/codex" -maxdepth 1 -mindepth 1 -type d -mtime +3 "${EXCLUDE_ARGS[@]}" -print0 2>/dev/null)
        git worktree prune >/dev/null 2>&1 || true
    fi
else
    echo "DB query failed — skipping prune (fail closed)"
fi

# ── Create worktree AFTER prune and lock ────────────────────────────────────
mkdir -p "$WT_BASE"
git worktree add -B "$BRANCH" "$WT" origin/main >/dev/null 2>&1

# ── Preflight: worktree must be clean ───────────────────────────────────────
[ -z "$(git -C "$WT" status --porcelain)" ] || { echo "preflight: worktree dirty"; exit 2; }

# ── Per-run CODEX_HOME with cleanup trap ────────────────────────────────────
CODEX_IMG="archie_brain-archie_codex:latest"
NET="archie_network"
GATEWAY_URL="http://archie_mcp_gateway:7800/mcp"
BEARER_FILE="$REPO/secrets/codex/mcp_bearer.txt"
CODEX_HOME_SRC="${CODEX_HOME:-$HOME/.codex}"
CODEX_RUN_HOME="${XDG_CACHE_HOME:-$HOME/.cache}/codex-run/$BRANCH"

mkdir -p "$CODEX_RUN_HOME"
chmod 700 "$CODEX_RUN_HOME"
install -m 600 "$CODEX_HOME_SRC/auth.json" "$CODEX_RUN_HOME/auth.json"
cat > "$CODEX_RUN_HOME/config.toml" <<TOML_EOF
[projects."$WT"]
trust_level = "trusted"

[mcp_servers.archie_kb]
url = "$GATEWAY_URL"
bearer_token_env_var = "ARCHIE_KB_BEARER"
TOML_EOF
printf 'ARCHIE_KB_BEARER=%s\n' "$(cat "$BEARER_FILE")" > "$CODEX_RUN_HOME/codex.env"

# ── Execute Codex — NO || true; capture exit code and output ────────────────
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
    --security-opt no-new-privileges --pids-limit 512
)

echo "=== Codex Task Submission ==="
echo "Task: $TASK"
echo "Branch: $BRANCH"
echo "Worktree: $WT"
echo "Codex image: $CODEX_IMG"
echo ""

set +e
DOCKER_OUT="$(docker run --rm "${DOCKER_ARGS[@]}" archie_brain-archie_codex \
    exec --dangerously-bypass-approvals-and-sandbox "$TASK" 2>&1)"
DOCKER_RC=$?
set -e

if [ $DOCKER_RC -ne 0 ]; then
    echo "=== Codex container exited with code $DOCKER_RC ==="
    echo "$DOCKER_OUT"
    echo ""
    echo "Codex run failed. Branch $BRANCH left for inspection."
    echo "  git worktree remove --force $WT"
    exit $DOCKER_RC
fi

# ── Postflight: changes ─────────────────────────────────────────────────────
# File names come from Codex-controlled content: keep them NUL-delimited and in a FILE. They
# must never be interpolated into code (a name containing a quote ran as Python on the host)
# and must never be word-split (a name with a space turned one path into two).
CHANGED_FILE="$(mktemp "${XDG_RUNTIME_DIR:-$HOME/.cache}/codex-changed.XXXXXX")"
{ git -C "$WT" diff -z --name-only; git -C "$WT" diff -z --cached --name-only; git -C "$WT" ls-files -z --others --exclude-standard; } \
    | sort -zu > "$CHANGED_FILE"   # -z: a newline inside a name must not split it into two
CHANGED="$(tr '\0' '\n' < "$CHANGED_FILE")"   # display / emptiness test only

if [ -n "$CHANGED" ]; then
    echo "Codex made changes:"
    printf '%s\n' "$CHANGED"
else
    echo "Codex completed but modified 0 files — task may already be done or model got stuck"
fi

# ── Scope guard — FAIL CLOSED on Python errors ─────────────────────────────
# Run scope check; if Python fails (non-zero), BLOCK the run
set +e
SCOPE_OUT="$(cd "$REPO/platform_v2" && python3 -c "
import sys, yaml
from services.agents.codex_scope import check_diff_paths
cfg_path, changed_path = sys.argv[1], sys.argv[2]
try:
    cfg = yaml.safe_load(open(cfg_path))['codex']
    paths = [p for p in open(changed_path, 'rb').read().decode('utf-8', 'surrogateescape').split('\0') if p]
    bad = check_diff_paths(paths, cfg)
    print('\n'.join(bad) if bad else '')  # empty = no violations
except Exception as e:
    print(f'SCOPE_ERROR:{e}', file=sys.stderr)
    sys.exit(1)
" "$CFG" "$CHANGED_FILE")"
SCOPE_RC=$?
set -e

if [ $SCOPE_RC -ne 0 ]; then
    echo "SCOPE CHECK FAILED (Python error blocked the run):"
    echo "$SCOPE_OUT"
    echo "Branch $BRANCH left for inspection."
    echo "  git worktree remove --force $WT"
    exit 1
fi

if [ -n "$(echo "$SCOPE_OUT" | grep -v '^$')" ]; then
    echo "SCOPE VIOLATION (blocked, no PR):"
    echo "$SCOPE_OUT"
    echo ""
    echo "Branch $BRANCH left for inspection."
    echo "  git worktree remove --force $WT"
    exit 1
fi

# ── Commit + push — NO --no-verify ─────────────────────────────────────────
if [ -n "$CHANGED" ]; then
    echo ""
    echo "Committing Codex changes..."
    # Stage exactly the paths the scope guard approved (not `add -A`, which could pick up more).
    xargs -0 -a "$CHANGED_FILE" git -C "$WT" add --
    git -C "$WT" commit -q -m "feat(codex): $TASK"
    echo "codex: commit succeeded"

    echo "codex: pushing changes..."
    git -C "$WT" push -u origin "$BRANCH"
    echo "codex: push succeeded"
fi

# ── Create PR — NO || true; report errors ──────────────────────────────────
if [ -n "$CHANGED" ]; then
    echo ""
    echo "Creating PR via gh..."
    PR_CREATE_OUT="$(gh pr create \
        --head "$BRANCH" \
        --title "feat(codex): $TASK" \
        --body "$(printf '## Codex\n\n- **Task**: %s\n- **Branch**: %s\n\n## Test Plan\n- [ ] F.O.R.G.E. review passes\n- [ ] Deploy via /merge-pr after approval\n\n🤖 Codex CLI — auto-generated, review via Repair Bay → PR Review' "$TASK" "$BRANCH")" 2>&1)"
    PR_RC=$?

    PR_URL="$(printf '%s\n' "$PR_CREATE_OUT" | tail -1)"
    PR_NUM="$(echo "$PR_URL" | grep -oE '[0-9]+$')"

    if [ $PR_RC -eq 0 ] && [ -n "$PR_NUM" ]; then
        echo ""
        echo "PR #${PR_NUM} created: $PR_URL"
        echo ""
        echo "Next steps:"
        echo "1. F.O.R.G.E. reviews the PR in Repair Bay → PR Review"
        echo "2. A human must approve and merge via /merge-pr"
        echo "3. Branch $BRANCH and worktree $WT can be removed after merge"
    else
        echo ""
        echo "gh pr create failed (exit $PR_RC). PR output:"
        echo "$PR_CREATE_OUT"
        echo ""
        echo "Branch $BRANCH and worktree $WT left for inspection."
        echo "  git worktree remove --force $WT"
        exit $PR_RC
    fi
else
    echo ""
    echo "No changes produced by Codex — branch $BRANCH left for inspection."
    echo "To clean up:"
    echo "  git worktree remove --force $WT"
fi

echo ""
echo "worktree: $WT (remove with: git worktree remove --force $WT)"
