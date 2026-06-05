# Codex CLI Integration — Design Spec

**Date:** 2026-06-05 · **Status:** Approved (design) — Phase A to build, Phase B design-only
**Owner:** Kytran · **Author:** Claude (Opus 4.8)

## Goal

Add **OpenAI Codex CLI** as a controlled, scoped **patch + test + review specialist** alongside the existing Claude Code / multi-LLM (DHQ) orchestration — *not* an unrestricted autonomous operator. It must be a first-class, **tracked** participant: its token usage flows into the Token Economy and its jobs appear in fleet dispatch, the same way Claude CLI and platform agents are tracked.

Two integration modes, sequenced:
- **Phase A (BUILD NOW):** Codex as a CLI Kytran drives manually on Applications & Concepts work.
- **Phase B (DESIGN ONLY):** Codex as a delegatable platform agent via `delegate_task`.

## Key principle: reuse the existing stack, don't build a parallel one

The platform already provides the orchestration the generic plan said to "create." Codex plugs into it:

| Need | Existing mechanism Codex reuses |
|------|--------------------------------|
| Task queue / delegation | `delegate_task(capability, reason)` → `unified_tasks` → `delegate_task_worker` → DHQ `department_dispatcher` (Phase B) |
| Per-task isolation | git **worktrees** per task + sandbox env |
| Approval boundary (never auto-merge) | branch protection + pre-push hook + `/commit-push-pr` → **F.O.R.G.E.** review (Repair Bay) → `/merge-pr` |
| Postflight gates | pre-commit hooks (black, flake8, gitleaks, K.I.N./V.I.G.I.L./timezone guardrails) + P.R.O.B.E. QA |
| Token + dispatch telemetry | `department_dispatcher.log_external_call(...)` → `task_execution_log` → Token Economy + ARMADA/Dispatch |
| Audit | `task_execution_log`, `work_notes`, `autonomy_loop_log` |

## Decisions (locked)

- **Mode:** design both, build Phase A first.
- **Isolation:** worktree + **scrubbed env** as `kytran` (allowlist `HOME`/`PATH`/Codex auth dir; unset all secrets). Graduate Phase B to a dedicated `codex-agent` user or container if autonomy grows.
- **Auth:** Phase A = **Sign in with ChatGPT** (free with paid plan, interactive). If the CLI doesn't expose exact tokens in sign-in mode, record **estimated** tokens (capacity-ceiling, flagged in metadata). Phase B headless auth decided at build time (likely API key for exact usage + headless capability).
- **Scope:** Codex may edit **only** `platform_v2/tools/{fitness,therapy,doc,family_tree,media_studio,game_studio,…}` (Applications & Concepts) + their tests. Everything else is read-only context. Hard-blocked: `.env*`, `docker-compose*`, `scripts/dr/*`, deploy workflows, agent/dispatch single-writer guardrails.
- **Tracking:** tokens + jobs recorded as identity **`Codex (CLI)`**, `provider="openai"` (mirrors `Claude (CLI)`). Each run also drops a **`unified_task`** so it shows in Dev HQ task lists.
- **Roster name (Phase B, OPEN):** plain "Codex" vs a fleet-style acronym. Recommendation: an acronym (e.g. **C.O.D.E.X.** is taken by Documentation dept → pick another, e.g. **F.O.R.G.E.** is taken too; candidate **P.A.T.C.H.** = "Programmatic Automated Test & Change Handler"). Decide at Phase B.

## Phase A — components / deliverables (BUILD)

1. **`scripts/agents/run-codex-task.sh`** — the wrapper:
   - args: a scoped task description (+ optional target module).
   - creates a worktree off `main` (`codex/<slug>` branch);
   - launches Codex with a **scrubbed environment** (allowlist only);
   - **preflight:** clean worktree, branch created;
   - runs Codex on the scoped task;
   - **postflight:** `git diff --check`; **scope-allowlist guard** (`git diff --name-only` must be within allowed paths, else fail); `pre-commit run --files <changed>`; test cmd if present; optional `mcp__archie__run_qa_suite`/`/archie-scan` on the touched module;
   - on pass: push branch + open PR (via `/commit-push-pr` path) → F.O.R.G.E. review; on fail: leave branch, mark job blocked, no PR;
   - calls the telemetry helper (below) regardless of outcome.
2. **`config/agents/codex.yaml`** — `max_concurrent: 1`, `max_runtime_sec`, `max_files_changed`, `allowed_paths` glob list, `blocked_paths`, `preflight`/`postflight` command lists, `model`.
3. **Telemetry helper** (`services/agents/codex_telemetry.py` or similar): `record_codex_run(task_id, branch, prompt_tokens, completion_tokens, model, files_changed, tests, success, duration_ms, estimated=False)` → `department_dispatcher.log_external_call(...)` → `task_execution_log` (agent_name=`Codex (CLI)`, provider=`openai`, model_used=`codex/<model>`, capability=`codex_implement`, module_source=`codex_cli`) + a `unified_task` (completed/blocked) + a `work_notes` entry + a per-run JSON under `logs/codex/<task_id>.json`.
4. **`scripts/ingest_codex_cli_tokens.py`** — host cron mirroring `ingest_claude_cli_tokens.py`: parses Codex session/usage logs into daily `task_execution_log` rows for `Codex (CLI)` (covers interactive you-driven sessions outside the wrapper).
5. **Docs (repo convention — NOT `/docs/`, which is archived per CLAUDE.md):** a single `.claude/rules/codex-agent.md` covering integration guide + **safety policy** (allowed/blocked paths, gates, never-merge boundary) + the **task template** (below). Loaded into session context like other rules. The merge close-out also stores a coder + user `vault_note` in the KB.

**Install (documented, NOT run by Claude):** `npm install -g @openai/codex`; then Kytran runs `codex` + "Sign in with ChatGPT". No login/credential commands executed by the agent.

## Phase B — design only (delegatable agent)

- `delegate_task(capability='codex_implement'|'codex_review', reason=...)` → `delegate_task_worker` known-tool branch → runs the **same `run-codex-task.sh`** headlessly → PR.
- Adds: headless auth (API key likely), a roster identity (acronym TBD) with `agent_skills` (`codex_implement`, `codex_review`, `test_authoring`), and an executor type (Codex is external cloud, closer to the `contractor_providers` pattern than an Ollama agent).
- Inherits all Phase-A gates + telemetry. Concurrency stays 1 until trust established.

## Task template (Codex prompt)

> Use Codex CLI to implement only the requested scoped change on the assigned branch/worktree. Edit only files under the allowed Applications/Concepts paths. Do not modify unrelated files, secrets, infra, or deploy config. Before finishing, run the required checks and summarize: files changed, tests run, failures, and remaining risks.

## Testing the integration (Phase A acceptance)

Dry-run on a trivial scoped change (e.g., a docstring in a Concepts module):
1. Worktree created off main, branch `codex/...`.
2. **Env scrub verified** — assert `DB_PASSWORD`/`STRIPE_*` absent in Codex's process env.
3. **Scope guard** — an out-of-scope edit (e.g. touching `app.py`) fails postflight and blocks the PR.
4. **Telemetry** — a `task_execution_log` row + `unified_task` land, attributed to `Codex (CLI)`; visible in Token Economy + Dispatch.
5. PR opens, F.O.R.G.E. can review; nothing reaches main without `/merge-pr`.

## Non-goals / constraints honored

No deploy-workflow changes; no auto-merge to main; no hardcoded keys/tokens; Claude Code functionality untouched; all changes minimal + reversible (delete script/config/branch = fully removed).

## Risks / blockers

- **Headless auth (Phase B):** ChatGPT-session auth is fragile headless (same class as interactive-MCP-in-cron) → likely needs an API key.
- **Token granularity in sign-in mode:** may be coarse/absent → estimated tokens fallback.
- **Two CLIs on one repo:** worktree isolation is mandatory (already standard here).
- **Scope-guard correctness:** the allowlist check is the primary safety gate for Phase A — must be airtight (deny-by-default).
