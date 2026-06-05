#!/usr/bin/env bash
# run-codex-task.sh — drive Codex CLI on a scoped task in an isolated worktree.
# Usage: scripts/agents/run-codex-task.sh "implement X in the doc module"
# Codex must already be installed + signed in (see .claude/rules/codex-agent.md).
set -euo pipefail

REPO="/mnt/archie_brain"
CFG="$REPO/config/agents/codex.yaml"
TASK="${1:?usage: run-codex-task.sh \"<scoped task>\"}"
SLUG="$(echo "$TASK" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9-' | cut -c1-40)"
BRANCH="codex/$SLUG-$(date +%s)"
WT="/tmp/codex-wt/$BRANCH"
START=$(date +%s%3N)

# 1) fresh worktree off origin/main
cd "$REPO"
git fetch origin -q
git worktree add -B "$BRANCH" "$WT" origin/main >/dev/null

# 2) scrubbed env: start from nothing, pass only the allowlist
RUN_ENV=(env -i HOME="$HOME" PATH="$PATH" TERM="${TERM:-xterm}" LANG="${LANG:-C.UTF-8}" CODEX_HOME="${CODEX_HOME:-$HOME/.codex}")

# 3) preflight: worktree must be clean
[ -z "$(git -C "$WT" status --porcelain)" ] || { echo "preflight: worktree dirty"; exit 2; }

# 4) run Codex on the scoped task (interactive/auto per your codex config)
ASSIGN="Edit ONLY files under the allowed Applications/Concepts paths in config/agents/codex.yaml. Do not touch secrets, infra, deploy, or unrelated files. Task: $TASK"
( cd "$WT" && "${RUN_ENV[@]}" codex exec "$ASSIGN" ) || echo "codex exited non-zero (continuing to gates)"

# 5) scope guard (deny-by-default) — fail the run if anything out of scope changed
CHANGED=$(git -C "$WT" diff --name-only)
OUT=$(cd "$REPO/platform_v2" && python -c "
import sys, yaml
from services.agents.codex_scope import check_diff_paths
cfg=yaml.safe_load(open('$CFG'))['codex']
bad=check_diff_paths('''$CHANGED'''.split(), cfg)
print('\n'.join(bad))
")
if [ -n "$OUT" ]; then echo "SCOPE VIOLATION (blocked, no PR):"; echo "$OUT"; SUCCESS=false; else SUCCESS=true; fi

# 6) postflight gates (only if in scope)
if [ "$SUCCESS" = true ]; then
  git -C "$WT" add -A
  git -C "$WT" diff --cached --check || SUCCESS=false
  ( cd "$WT" && pre-commit run --files $CHANGED ) || SUCCESS=false
fi

# 7) telemetry (always)
DUR=$(( $(date +%s%3N) - START ))
NFILES=$(echo "$CHANGED" | grep -c . || true)
(cd "$REPO/platform_v2" && python -c "
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
