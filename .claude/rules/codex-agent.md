# Codex CLI Agent — Safety Policy, Task Template & Operating Guide

## (a) What Codex Is — Phase A vs B

**Codex CLI** (`@openai/codex`) is an OpenAI agentic coding tool that runs locally and
edits files in a git worktree. In **Phase A** (current), it uses ChatGPT sign-in mode —
no API key required, but token counts are not directly accessible (runs are logged as
estimated). In **Phase B** (future), an API key may be used for full token visibility.

Codex complements A.R.C.H.I.E.'s local fleet by handling Applications/Concepts module
code tasks (fitness, therapy, doc, family_tree, media_studio, game_studio, media_hub).
It NEVER touches infra, dispatch, agents table, or secrets.

---

## (b) Safety Policy

### Allowed paths (deny-by-default — anything not listed is blocked)

```
platform_v2/tools/fitness/
platform_v2/tools/therapy/
platform_v2/tools/doc/
platform_v2/tools/family_tree/
platform_v2/tools/media_studio/
platform_v2/tools/game_studio/
platform_v2/tools/media_hub/
platform_v2/tests/
```

### Always blocked (even if under an allowed path)

```
*.env  .env*  docker-compose*  scripts/dr/*  .github/*
platform_v2/services/agent_service.py
**/department_dispatcher.py
```

### Hard limits

| Limit | Value |
|-------|-------|
| Max concurrent runs | 1 |
| Max runtime per task | 30 min |
| Max files changed | 25 |
| Merge to main | NEVER — branch+PR only, F.O.R.G.E. must review |
| Secrets in env | NEVER — env is scrubbed (`env -i`) before Codex runs |
| Auto-merge | NEVER — push branch, open PR, wait for `/merge-pr` after review |

### Never-merge boundary

`run-codex-task.sh` pushes the branch but NEVER merges. The human operator must:
1. Open a PR (or it's opened via `/commit-push-pr`)
2. F.O.R.G.E. reviews via `/merge-pr`
3. Human approves and merges

---

## (c) Task Template

When writing a task prompt for Codex, use this structure:

```
Edit ONLY files under the allowed Applications/Concepts paths in
config/agents/codex.yaml. Do not touch secrets, infra, deploy, or
unrelated files.

Task: <one clear sentence describing what to implement or fix>

Context:
- Module: platform_v2/tools/<module>/
- Relevant file(s): <list key files>
- Pattern to follow: <e.g. "match the existing route pattern in routes.py">
- Tests: <e.g. "add/update tests in platform_v2/tests/test_<module>.py">
- Do NOT change: <any specific files or functions to leave alone>
```

**Good tasks for Codex:**
- Add a route handler to an existing module
- Implement a missing CRUD endpoint
- Add docstrings / type hints to existing functions
- Write unit tests for existing logic
- Refactor a single file within a module (no cross-module changes)

**Bad tasks (too risky / out of scope):**
- "Refactor the database layer"
- "Update the agent dispatch pipeline"
- "Add a new department"
- Anything touching `.env`, `docker-compose`, `scripts/dr/`, or `services/agent_service.py`

---

## (d) How to Run

```bash
# Basic usage — Codex must be installed and signed in first (see section e)
scripts/agents/run-codex-task.sh "add input validation to the therapy module session endpoint"

# The wrapper will:
# 1. Create a fresh git worktree off origin/main
# 2. Strip all secrets from the environment
# 3. Run Codex with the task prompt
# 4. Apply the scope guard (deny-by-default allowlist)
# 5. Run postflight gates (git diff --check + pre-commit)
# 6. Write telemetry to task_execution_log as 'Codex (CLI)'
# 7. Push the branch (if clean) — NEVER merges
```

After the run:
```bash
# Check the branch was pushed:
git branch -r | grep codex/

# Open a PR:
gh pr create --head <branch> --title "feat(codex): <task>"

# After F.O.R.G.E. review:
/merge-pr
```

---

## (e) Install (Manual — Kytran Runs This, NOT the Worker)

```bash
# 1. Install Codex CLI globally:
npm install -g @openai/codex

# 2. Sign in with ChatGPT (opens browser):
codex
# → follow the "Sign in with ChatGPT" prompt

# 3. Verify it works:
codex --version

# 4. (Optional) Add the daily token ingest cron:
# Edit /etc/cron.d/codex-ingest or crontab -e:
# 45 3 * * * /usr/bin/python3 /mnt/archie_brain/scripts/ingest_codex_cli_tokens.py >> /tmp/codex_token_ingest.log 2>&1
```

**The worker (Claude Code / automated agents) must NEVER run `npm install -g @openai/codex`
or `codex` sign-in commands.** Installation and authentication are manual operator steps.

---

## (f) Where Telemetry Lands

After each run, two records are created:

| Location | What |
|----------|------|
| `task_execution_log` | Row with `agent_name='Codex (CLI)'`, `provider='openai'`, `worker_type='contract'`. Visible in **Consciousness → Token Economy** tab (orange = external/cloud). |
| `logs/codex/<timestamp>_<branch>.json` | JSON audit log on the host filesystem. Parsed daily by `scripts/ingest_codex_cli_tokens.py`. |
| `unified_tasks` (optional) | Created when `project_id` is passed to `record_codex_run()`. Shows in **Dev HQ** task lists. |

The Token Economy chart shows Codex tokens as **orange** (external provider = openai),
alongside Claude (CLI) in the same external tier. The Dispatch tab shows `module_source='codex_cli'`
and `request_origin='codex_cli'` for filtering.

---

## Related Files

| File | Purpose |
|------|---------|
| `config/agents/codex.yaml` | Limits, allowed/blocked paths, gate commands |
| `scripts/agents/run-codex-task.sh` | The run wrapper |
| `platform_v2/services/agents/codex_scope.py` | Deny-by-default scope guard |
| `platform_v2/services/agents/codex_telemetry.py` | Telemetry → task_execution_log |
| `scripts/ingest_codex_cli_tokens.py` | Daily host cron for token aggregation |
| `.claude/plans/codex-cli-integration-design.md` | Full design spec |
