# Codex CLI — Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an OpenAI Codex CLI run-wrapper that edits only Applications/Concepts modules in a scrubbed-env git worktree, gates the output, leaves a branch/PR for F.O.R.G.E. review (never auto-merges), and records each run into `task_execution_log` as `Codex (CLI)` so it shows in the Token Economy + Dispatch.

**Architecture:** A bash wrapper (`run-codex-task.sh`) drives Codex inside a per-task worktree with all secrets stripped. A Python scope-guard (deny-by-default allowlist) and a Python telemetry helper (direct `task_execution_log` insert, mirroring the Claude-CLI ingest) are unit-tested. No DB writes to the `agents` table; no auto-merge; reversible.

**Tech Stack:** bash, Python 3.11 (psycopg2 via `database.get_db_cursor`), git worktrees, existing pre-commit hooks, `@openai/codex` CLI (installed + ChatGPT-signed-in manually by Kytran — NOT by the worker).

**Spec:** `.claude/plans/codex-cli-integration-design.md`

---

## File structure (Phase A)

- Create `config/agents/codex.yaml` — limits, allowed/blocked paths, gate commands, model.
- Create `services/agents/__init__.py` — package marker.
- Create `services/agents/codex_scope.py` — `is_in_scope(path, cfg)` + `check_diff_paths(paths, cfg)` (deny-by-default). Unit-tested.
- Create `services/agents/codex_telemetry.py` — `record_codex_run(...)` → `task_execution_log` row (`Codex (CLI)`) + `unified_tasks` row + `logs/codex/<task_id>.json`. Unit-tested (DB row).
- Create `services/agents/tests/test_codex_scope.py`, `test_codex_telemetry.py`.
- Create `scripts/agents/run-codex-task.sh` — the wrapper (worktree → scrubbed env → codex → gates → telemetry → branch/PR).
- Create `scripts/ingest_codex_cli_tokens.py` — daily host cron for interactive Codex sessions (mirrors `scripts/ingest_claude_cli_tokens.py`).
- Create `.claude/rules/codex-agent.md` — safety policy + task template + operating guide.

Allowed scope dirs (from spec): `platform_v2/tools/fitness`, `platform_v2/tools/therapy`, `platform_v2/tools/doc`, `platform_v2/tools/family_tree`, `platform_v2/tools/media_studio`, `platform_v2/tools/game_studio`, `platform_v2/tools/media_hub`, plus `platform_v2/tests/` for those modules. Blocked always: `*.env*`, `docker-compose*`, `scripts/dr/*`, `.github/*`, `platform_v2/services/agent_service.py`, `**/department_dispatcher.py`, anything outside allowed.

---

### Task 1: Config file

**Files:**
- Create: `config/agents/codex.yaml`

- [ ] **Step 1: Write the config**

```yaml
# Codex CLI agent config (Phase A). See .claude/plans/codex-cli-integration-design.md
codex:
  model: "gpt-5-codex"            # set to the model your `codex` CLI exposes; informational for telemetry
  auth_mode: "chatgpt_signin"     # phase A; phase B may use api_key
  max_concurrent: 1
  max_runtime_sec: 1800           # 30 min hard cap per task
  max_files_changed: 25
  allowed_paths:
    - "platform_v2/tools/fitness/"
    - "platform_v2/tools/therapy/"
    - "platform_v2/tools/doc/"
    - "platform_v2/tools/family_tree/"
    - "platform_v2/tools/media_studio/"
    - "platform_v2/tools/game_studio/"
    - "platform_v2/tools/media_hub/"
    - "platform_v2/tests/"
  blocked_globs:                  # always denied even if under an allowed path
    - "*.env"
    - ".env*"
    - "docker-compose*"
    - "scripts/dr/*"
    - ".github/*"
  preflight:
    - "git status --porcelain"    # must be empty in the fresh worktree
  postflight:
    - "git diff --check"          # whitespace / conflict markers
    - "pre-commit run --files {changed}"
  # secrets stripped from Codex's env (allowlist is the default; this list is documentation)
  env_allowlist: ["HOME", "PATH", "TERM", "LANG", "CODEX_HOME"]
```

- [ ] **Step 2: Commit**

```bash
git add config/agents/codex.yaml
git commit -m "feat(codex): config for Phase A run-wrapper (limits, scope, gates)"
```

---

### Task 2: Scope guard (deny-by-default) — unit tested

**Files:**
- Create: `services/agents/__init__.py`
- Create: `services/agents/codex_scope.py`
- Test: `services/agents/tests/test_codex_scope.py`

- [ ] **Step 1: Write the failing test**

```python
# services/agents/tests/test_codex_scope.py
from services.agents.codex_scope import is_in_scope

CFG = {
    "allowed_paths": ["platform_v2/tools/fitness/", "platform_v2/tests/"],
    "blocked_globs": ["*.env", "docker-compose*", "scripts/dr/*"],
}

def test_allowed_module_path():
    assert is_in_scope("platform_v2/tools/fitness/routes.py", CFG) is True

def test_outside_scope_denied():
    assert is_in_scope("platform_v2/app.py", CFG) is False

def test_blocked_glob_denied_even_if_under_allowed():
    # an .env dropped inside an allowed dir is still blocked
    assert is_in_scope("platform_v2/tools/fitness/.env", CFG) is False

def test_dr_script_denied():
    assert is_in_scope("scripts/dr/failover.sh", CFG) is False

def test_test_dir_allowed():
    assert is_in_scope("platform_v2/tests/test_fitness.py", CFG) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/archie_brain/platform_v2 && python -m pytest services/agents/tests/test_codex_scope.py -v`
Expected: FAIL — `ModuleNotFoundError: services.agents.codex_scope`

- [ ] **Step 3: Write minimal implementation**

```python
# services/agents/__init__.py
# (empty package marker)
```

```python
# services/agents/codex_scope.py
"""Deny-by-default path scope guard for Codex CLI runs (Phase A).

A path is in scope ONLY IF it sits under an allowed_paths prefix AND does not
match any blocked_globs. Blocked always wins. This is the primary safety gate.
"""
from __future__ import annotations
import fnmatch
from typing import Iterable


def is_in_scope(path: str, cfg: dict) -> bool:
    p = path.lstrip("./")
    for pat in cfg.get("blocked_globs", []):
        # match against the full path AND the basename so "*.env" catches nested
        if fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p.split("/")[-1], pat):
            return False
        if pat.endswith("/*") and p.startswith(pat[:-1]):
            return False
    for prefix in cfg.get("allowed_paths", []):
        if p.startswith(prefix):
            return True
    return False


def check_diff_paths(paths: Iterable[str], cfg: dict) -> list[str]:
    """Return the list of out-of-scope paths (empty list == all clean)."""
    return [p for p in paths if p and not is_in_scope(p, cfg)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/archie_brain/platform_v2 && python -m pytest services/agents/tests/test_codex_scope.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add services/agents/__init__.py services/agents/codex_scope.py services/agents/tests/test_codex_scope.py
git commit -m "feat(codex): deny-by-default scope guard + tests"
```

---

### Task 3: Telemetry helper — unit tested

**Files:**
- Create: `services/agents/codex_telemetry.py`
- Test: `services/agents/tests/test_codex_telemetry.py`
- Reference (read first): `scripts/ingest_claude_cli_tokens.py` (how "Claude (CLI)" rows are inserted into `task_execution_log`).

- [ ] **Step 1: Write the failing test**

```python
# services/agents/tests/test_codex_telemetry.py
from services.agents.codex_telemetry import record_codex_run
from database import get_db_cursor

def test_record_codex_run_inserts_task_execution_log():
    res = record_codex_run(
        task_label="unit-test scope change",
        branch="codex/unit-test",
        prompt_tokens=100, completion_tokens=50,
        model="gpt-5-codex", files_changed=["platform_v2/tools/doc/routes.py"],
        tests="2 passed", success=True, duration_ms=1234, estimated=True,
    )
    assert res["task_execution_log_id"]
    with get_db_cursor() as (_c, cur):
        cur.execute(
            "SELECT agent_name, provider, tokens_used, success FROM task_execution_log WHERE id=%s",
            (res["task_execution_log_id"],),
        )
        row = cur.fetchone()
    assert row["agent_name"] == "Codex (CLI)"
    assert row["provider"] == "openai"
    assert row["tokens_used"] == 150
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /mnt/archie_brain/platform_v2 && python -m pytest services/agents/tests/test_codex_telemetry.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# services/agents/codex_telemetry.py
"""Record a Codex CLI run into platform telemetry so it appears in the Token
Economy ('Codex (CLI)', provider=openai, cloud=orange) and the DHQ Dispatch/ARMADA
feeds. Mirrors how scripts/ingest_claude_cli_tokens.py logs 'Claude (CLI)'.

Does NOT use department_dispatcher.log_external_call — that overrides agent_name to
A.R.C.H.I.E. and reassigns the agent. We insert directly with a fixed CLI identity.
"""
from __future__ import annotations
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

AGENT_NAME = "Codex (CLI)"
LOG_DIR = "/mnt/archie_brain/logs/codex"


def record_codex_run(task_label, branch, prompt_tokens, completion_tokens, model,
                     files_changed, tests, success, duration_ms, estimated=False,
                     project_id=None):
    from database import get_db_cursor

    total = int(prompt_tokens or 0) + int(completion_tokens or 0)
    meta = {"branch": branch, "files_changed": files_changed, "tests": tests,
            "estimated_tokens": bool(estimated), "source": "run-codex-task.sh"}
    tel_id = None
    task_id = None
    with get_db_cursor(commit=True) as (_c, cur):
        cur.execute(
            """
            INSERT INTO task_execution_log
                (agent_name, worker_type, task_type, task_description, module_source,
                 model_used, provider, prompt_tokens, completion_tokens, tokens_used,
                 duration_ms, success, request_origin, created_at)
            VALUES (%s,'external','codex_implement',%s,'codex_cli',
                    %s,'openai',%s,%s,%s,%s,%s,'codex_cli',NOW())
            RETURNING id
            """,
            (AGENT_NAME, task_label[:500], f"codex/{model}",
             int(prompt_tokens or 0), int(completion_tokens or 0), total,
             int(duration_ms or 0), bool(success)),
        )
        tel_id = cur.fetchone()["id"]
        # Dev HQ task row so it shows in task lists too (spec decision b = yes)
        if project_id:
            cur.execute(
                """
                INSERT INTO unified_tasks (project_id, title, status, priority, task_type, created_at, updated_at)
                VALUES (%s,%s,%s,5,'implementation',NOW(),NOW()) RETURNING id
                """,
                (project_id, f"[Codex] {task_label}"[:200], "completed" if success else "blocked"),
            )
            task_id = cur.fetchone()["id"]

    os.makedirs(LOG_DIR, exist_ok=True)
    stamp = datetime.now(ZoneInfo("America/Toronto")).strftime("%Y%m%d_%H%M%S")
    with open(f"{LOG_DIR}/{stamp}_{branch.replace('/', '_')}.json", "w") as f:
        json.dump({"task_execution_log_id": tel_id, "unified_task_id": task_id,
                   "branch": branch, "model": model, "tokens": total,
                   "success": success, "meta": meta}, f, indent=2)
    return {"task_execution_log_id": tel_id, "unified_task_id": task_id, "tokens": total}
```

NOTE for implementer: verify the exact NOT-NULL columns on `task_execution_log` first
(`\d task_execution_log`) and the `unified_tasks` schema (`priority` INTEGER, `slug`
constraints — see `.claude/rules/database.md`); adjust the INSERT column list if the
live schema differs. `task_type` on task_execution_log is NOT NULL — keep it set.

- [ ] **Step 4: Run to verify it passes**

Run: `cd /mnt/archie_brain/platform_v2 && python -m pytest services/agents/tests/test_codex_telemetry.py -v`
Expected: PASS. Then sanity-check it surfaces: `GET /tools/consciousness/api/code-health/token-usage?range=24h` should include `Codex (CLI)` once a row exists.

- [ ] **Step 5: Commit**

```bash
git add services/agents/codex_telemetry.py services/agents/tests/test_codex_telemetry.py
git commit -m "feat(codex): telemetry helper -> task_execution_log as 'Codex (CLI)' + tests"
```

---

### Task 4: The run-wrapper

**Files:**
- Create: `scripts/agents/run-codex-task.sh`

- [ ] **Step 1: Write the wrapper**

```bash
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
```

- [ ] **Step 2: Make executable + commit**

```bash
chmod +x scripts/agents/run-codex-task.sh
git add scripts/agents/run-codex-task.sh
git commit -m "feat(codex): run-codex-task.sh wrapper (worktree+scrubbed env+gates+telemetry)"
```

- [ ] **Step 3: Verify scope-guard blocks out-of-scope (no Codex needed — mock a diff)**

Run a manual check that the guard logic rejects `platform_v2/app.py`:
```bash
cd /mnt/archie_brain/platform_v2 && python -c "
import yaml; from services.agents.codex_scope import check_diff_paths
cfg=yaml.safe_load(open('../config/agents/codex.yaml'))['codex']
print('blocked:', check_diff_paths(['platform_v2/app.py','platform_v2/tools/doc/x.py'], cfg))
"
```
Expected: `blocked: ['platform_v2/app.py']`

---

### Task 5: Interactive-session token ingest cron

**Files:**
- Create: `scripts/ingest_codex_cli_tokens.py`
- Reference: `scripts/ingest_claude_cli_tokens.py` (copy its structure; swap the session-log path + agent_name).

- [ ] **Step 1: Implement** — mirror the Claude ingest: find Codex session/usage logs under `~/.codex/` (verify the real path with `ls ~/.codex` after sign-in), sum daily prompt/completion tokens, INSERT one daily `task_execution_log` row per day with `agent_name='Codex (CLI)'`, `provider='openai'`, `module_source='codex_cli'`, dedup on the day (UPSERT or skip-if-exists like the Claude script). If Codex stores no token counts in sign-in mode, record an estimated row flagged `estimated` in metadata and `log()` that it was estimated.

- [ ] **Step 2: Commit + document cron (do NOT install yet — Kytran adds after sign-in)**

```bash
git add scripts/ingest_codex_cli_tokens.py
git commit -m "feat(codex): daily host-cron token ingest for interactive Codex sessions"
```
Cron line to add later: `45 3 * * * /usr/bin/python3 /mnt/archie_brain/scripts/ingest_codex_cli_tokens.py >> /tmp/codex_token_ingest.log 2>&1`

---

### Task 6: Safety/ops rules doc + manual-command handoff

**Files:**
- Create: `.claude/rules/codex-agent.md`

- [ ] **Step 1: Write the doc** — sections: (a) what Codex is + Phase A vs B; (b) **safety policy** — allowed/blocked paths, never-merge boundary, no-secrets, max files/runtime, concurrency 1; (c) **task template** (the prompt from the spec); (d) **how to run**: `scripts/agents/run-codex-task.sh "<task>"`; (e) **install (manual, Kytran runs)**: `npm install -g @openai/codex`, then `codex` → "Sign in with ChatGPT"; (f) where telemetry lands (Token Economy `Codex (CLI)`, Dispatch).

- [ ] **Step 2: Commit**

```bash
git add .claude/rules/codex-agent.md
git commit -m "docs(codex): agent safety policy + task template + operating guide"
```

---

### Task 7: Acceptance dry-run (after Kytran installs + signs in)

- [ ] Kytran (manual): `npm install -g @openai/codex` + `codex` sign-in.
- [ ] Run `scripts/agents/run-codex-task.sh "add a clarifying docstring to platform_v2/tools/doc/routes.py"`.
- [ ] Verify: worktree created; env scrub (the wrapper's `env -i`); a docstring-only diff; scope guard passes; gates pass; branch pushed (not merged); a `task_execution_log` row for `Codex (CLI)` appears in the Token Economy + Dispatch; a `unified_task` shows in Dev HQ.
- [ ] Open a PR + `/merge-pr` after F.O.R.G.E. review to confirm the full approval boundary.

---

## Self-review notes
- Spec coverage: isolation (Task 4 scrubbed env), scope (Task 2), telemetry tokens+dispatch (Task 3), gates (Task 4), audit (Task 3 JSON + log row), never-merge (Task 4 push-only), install-not-run (Task 6/7), config (Task 1). Phase B is design-only in the spec — no tasks here.
- The wrapper passes `prompt_tokens=0`/`estimated=True` because sign-in mode token capture is unverified; Task 5 + the `estimated` flag handle that. If Codex `exec` prints a usage line, parse it in Task 4 step 1 and pass real counts.
- Implementer MUST verify live `task_execution_log` / `unified_tasks` NOT-NULL columns before finalizing the INSERTs (noted in Task 3).
