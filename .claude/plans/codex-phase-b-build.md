# Phase B — Codex as a delegatable team agent (BUILD SPEC)

**Goal:** `delegate_task(capability='codex_task', reason=<task>, project_id=<n>)` → Codex
works **headless on the side** → opens a PR → sandbox preview → **Telegram "done, review"**
→ you approve → merge → prod. Interactive ttyd stays as-is (already works).

**Status:** Phase A done (Codex grounded: AGENTS.md + `.claude/rules/company-vision.md` +
KB #271833/#271834). This spec builds the delegation loop. Execute in a FRESH session.

## Existing pieces to reuse (do NOT rebuild)
- `scripts/agents/run-codex-task.sh` — sandboxed headless runner (container, scrubbed env,
  baked `/opt/codex-guard` scope guard). Opens a `codex/*` PR. Already logs tokens via
  `platform_v2/services/agents/codex_telemetry.py` → `task_execution_log` (agent_name
  `Codex (CLI)`, provider `openai`) → Token Economy orange tier.
- `scripts/agents/sandbox-auto-preview.sh` — deploys newest open codex PR to sandbox.
- `codex_promote_service.py` + agent_loop `codex_promote` branch — Telegram approve→merge→prod
  (built + verified this session, PR #1500).
- `config/agents/codex.yaml` — deny-by-default allowlist (6 Apps modules).

## Build steps (each its own commit/PR)
1. **Register Codex as a contract agent** — via `agent_service.create_agent` ONLY (single-writer;
   never raw SQL on `agents`). worker_type=`contract`, dept `Engineering & Technology`,
   `agent_skills` row skill_name=`codex_task` proficiency 5. Gives roster visibility + makes
   `codex_task` a real capability (else dispatcher defaults to F.O.R.G.E.).
2. **Delegation branch** — in `services/delegation_service.py` (`delegate_task_worker`): when
   `capability=='codex_task'`, DO NOT dispatch to the cluster. Mark the `unified_tasks` row
   `status='deferred'` + a metadata flag `{codex:true, project_id}`. The host poller owns it.
3. **Host poller** `scripts/agents/codex-delegation-worker.sh` (+ cron, e.g. 60s):
   - psql-reads deferred codex_task rows (read-only).
   - For each: read project goal (`unified_projects.name`/description) + task
     (`unified_tasks.title`/description) and COMPOSE the prompt (inject roadmap context —
     this is how the roadmap reaches Codex per AGENTS.md).
   - Run `run-codex-task.sh "<composed prompt>"` (concurrency 1, same caps).
   - On PR open: write PR# back to the task row, flip `in_progress`.
   - Security: poller only READS unified_*; never writes `agents`; never gets docker socket.
4. **Telegram done-notice** — after PR opens, `telegram_service.send_with_buttons` (reuse the
   `codex_promote` approve/reject buttons → merge to prod): "Codex finished task #N → PR #X,
   preview sandbox.kytranempowerment.com/tools/<module>".
5. **Verify** (don't claim done without proof): `delegate_task(capability='codex_task',
   reason='add a docstring to faith routes', project_id=310)` → confirm poller runs, PR opens,
   Telegram fires, a `Codex (CLI)` row lands in `task_execution_log` (Token Economy).

## Hard invariants (security — do not violate)
- NEVER give Codex the Docker socket (host-root escape). The runner is already containerised.
- NEVER auto-merge — Telegram human approve only (codex_promote).
- All Codex work stays inside the 6-module allowlist via baked `/opt/codex-guard`.
- Poller is READ-ONLY on platform data; agents-table writes go through `agent_service`.
- Trigger model: EXPLICIT delegation first (you/Claude). Auto-pull of pending roadmap tasks
  is a later toggle, not v1.

## Open decision for the user
- Explicit-delegate (recommended v1) vs auto-pull pending roadmap tasks for the 6 apps.
