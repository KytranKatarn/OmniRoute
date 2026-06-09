#!/usr/bin/env bash
# run-codex-task.sh — drive Codex CLI on a scoped task inside an isolated CONTAINER.
# Usage: scripts/agents/run-codex-task.sh "implement X in the doc module"
# Codex auth: host ~/.codex/auth.json (copied read/write into the container per run).
# See .claude/rules/codex-agent.md + .claude/plans/2026-06-05-codex-cli-phase-a-plan.md.
set -euo pipefail

REPO="/mnt/archie_brain"
CFG="$REPO/config/agents/codex.yaml"
TASK="${1:?usage: run-codex-task.sh \"<scoped task>\"}"
SLUG="$(echo "$TASK" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9-' | cut -c1-40)"
BRANCH="codex/$SLUG-$(date +%s)"
WT="/tmp/codex-wt/$BRANCH"
START=$(date +%s%3N)

# containerized-exec config — the container IS the isolation boundary.
CODEX_IMG="archie_brain-archie_codex:latest"
NET="archie_network"
GATEWAY_URL="http://archie_mcp_gateway:7800/mcp"   # read-only MCP gateway (internal)
BEARER_FILE="$REPO/secrets/codex/mcp_bearer.txt"   # the ONLY secret given to Codex
CODEX_HOME_SRC="${CODEX_HOME:-$HOME/.codex}"        # host auth lives here
CODEX_RUN_HOME="${XDG_CACHE_HOME:-$HOME/.cache}/codex-run/$BRANCH"  # per-run HOME (mode 700)

# 1) fresh worktree off origin/main
cd "$REPO"
git fetch origin -q
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
  module's entry in .claude/rules/module-capability-index.md.
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

# 4) run Codex INSIDE the container. The container is the sandbox (only the worktree
#    mounted rw, repo .git ro for git reads, no host fs/secrets, run as host uid),
#    so bypassing Codex's own (broken-on-this-host) bwrap sandbox is safe here.
docker run --rm \
  --network "$NET" \
  --user "$(id -u):$(id -g)" \
  -v "$WT":"$WT":rw \
  -v "$REPO/.git":"$REPO/.git":ro \
  -v "$CODEX_RUN_HOME":/codex-home:rw \
  -e HOME=/codex-home -e CODEX_HOME=/codex-home \
  --env-file "$CODEX_RUN_HOME/codex.env" \
  -w "$WT" \
  --read-only --tmpfs /tmp:size=64m \
  --memory 2g --cpus 2 --cap-drop ALL \
  "$CODEX_IMG" \
  exec --dangerously-bypass-approvals-and-sandbox "$ASSIGN" \
  || echo "codex exited non-zero (continuing to gates)"
rm -rf "$CODEX_RUN_HOME"

# 5) scope guard (deny-by-default) — fail the run if anything out of scope changed
CHANGED=$(git -C "$WT" diff --name-only)
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
    ( cd "$WT" && $PRECOMMIT run --files $CHANGED ) || SUCCESS=false  # pass 2: must be clean
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
record_codex_run(task_label='''$TASK''', branch='$BRANCH', prompt_tokens=0, completion_tokens=0,
  model='gpt-5-codex', files_changed='''$CHANGED'''.split(), tests='n/a',
  success=$( [ "$SUCCESS" = true ] && echo True || echo False ), duration_ms=$DUR, estimated=True)
")

# 8) outcome: commit + push branch for F.O.R.G.E. review (NEVER merge to main)
if [ "$SUCCESS" = true ] && [ "$NFILES" -gt 0 ]; then
  git -C "$WT" commit -q -m "feat(codex): $TASK"
  git -C "$WT" push --no-verify -u origin "$BRANCH"
  echo "PR-READY branch pushed: $BRANCH — open a PR + run /merge-pr after F.O.R.G.E. review."
else
  echo "Run blocked or no changes — branch $BRANCH left for inspection, no push."
fi
echo "worktree: $WT (remove with: git worktree remove --force $WT)"
