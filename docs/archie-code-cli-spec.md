# A.R.C.H.I.E. as Delegate — Interactive Orchestrator

**Project:** #276 (renamed from "ArchieCode — OpenClaude Fork + Delegation Surface")
**Priority:** P10 · week-1 target: Phase 1–3 end-to-end by **2026-04-26**
**Authoritative spec.** Any deviation should come back and update this doc.

> **2026-04-21 pivot note:** original scope forked `Gitlawb/openclaude` for a new CLI. That upstream has a proprietary-derivative license (derivative of Anthropic's closed-source Claude Code, `NOASSERTION` on GitHub) — unsafe to fork. The project re-scoped to focus on the **delegation surface itself** (Claude ↔ A.R.C.H.I.E. ↔ agents), which is the actual missing piece. Optional CLI fork demoted to Phase 4 using `plandex` (MIT) as upstream.

## TL;DR

Build the delegation surface so Claude (and Kytran) can hand work to A.R.C.H.I.E. by capability tag. She orchestrates her agents (via the existing `OrchestrationEngine` + `department_dispatcher` + DHQ) and streams results back through the already-shipped Unified Comms (#265).

```
Claude (reasoning)
     │ mcp__archie__delegate_task(capability='run_qa_suite', …)
     ▼
delegation_service.delegate_task() — persists to unified_tasks (delegation_source='claude')
     │
     ▼
_run_delegate_task_worker (agent-loop job, 30s)
     │
     ├──► known-tool shortcut — run_qa_suite, run_misroute_audit, check_dep_drift
     │                          (direct service function)
     └──► DHQ dispatcher — everything else (agent selection + C.R.E.E.D. + cost tracking)
     │
     ▼
work_notes result + task.status='completed'
     │
     ▼  (Phase 3)
Unified Comms streaming — Telegram / web chat
```

## Why this shape

- **Reuse, don't rebuild.** `OrchestrationEngine` (line 229 of `orchestration_engine.py`) and `department_dispatcher.dispatch()` already exist and already work. Adding a persistence layer + worker loop is ~400 LOC.
- **Unified Comms (#265) is already shipped.** Streaming surface exists; Phase 3 just wires delegation events into it.
- **C.R.E.E.D. + cost gates stay in one place.** Any cloud escalation still flows through the dispatcher — no new approval path to maintain.
- **Claude and Kytran use the same tool.** Kytran can call `delegate_task` via Telegram/CLI/web; Claude calls it via MCP. One surface, many callers.

## What shipped in Phase 1 (this commit)

| File | Role |
|------|------|
| `database/migrations/344_delegation_columns_unified_tasks.sql` | Adds `delegation_source` / `delegation_args` / `streaming_channel` columns + partial index on `(status, created_at) WHERE delegation_source IS NOT NULL`. Idempotent. |
| `platform_v2/services/delegation_service.py` | `delegate_task()` (persist) + `execute_delegated_task()` (route to known-tool shortcut or dispatcher) + `fetch_pending_delegations()` / `mark_*()` helpers. |
| `platform_v2/mcp_server/tools/ai_command_tools.py` | `mcp__archie__delegate_task` MCP tool registered alongside `propose_hire` / `propose_reactivation`. |
| `ai_bridge/agent_loop.py` | New scheduler job `delegate_task_worker` (30s interval) + `_run_delegate_task_worker` method. Claims ≤3 tasks/cycle, logs one `autonomy_loop_log` row per non-empty cycle. |
| `platform_v2/tests/test_delegation_service.py` | 13 unit tests: validation, persistence, known-tool routing (misroute audit + adapter, JSON-string args), dispatcher fallback, failure paths. 0.17s, DB-free via mock cursor. |

## Known-tool capabilities (Phase 1 shortcuts)

These route straight to service functions — no LLM round-trip:

- `run_qa_suite` → `services.qa_service.run_qa_suite`
- `run_misroute_audit` → `services.misroute_audit_service.run_misroute_audit`
- `run_misroute_to_proposal_adapter` → `services.misroute_to_proposal_adapter.run`
- `check_dep_drift` → `services.dep_drift_service.check_dep_drift`
- `health_check` / `check_platform_health` → `services.health_service`

New capabilities are added by extending `KNOWN_TOOL_CAPABILITIES` and `_execute_known_tool()`. Everything else falls through to `dispatch(capability, prompt)` for LLM-based work.

## Phase 2 (next session) — conversational state

Multi-turn delegation. Today every `delegate_task` call is fire-and-forget. Phase 2 adds:
- `parent_task_id` so a task can spawn sub-tasks ("I need API docs first")
- Conversation thread ID so multi-step delegations stay linked
- Archie can reply back up the chain to clarify

Spec not written yet — next sprint.

## Phase 3 (next session) — Unified Comms streaming

Wire `_run_delegate_task_worker` events into `telegram_service` + `archie_comms`. Kytran sees each delegated task scroll in Archie's voice. Replaces the old "Telegram ping" Phase 2 item with a richer stream. Depends on #265 infrastructure (already shipped).

## Phase 4 (nice-to-have, not this week) — ArchieCode CLI fork

Optional terminal-native surface for Kytran. Upstream = **plandex** (MIT, server+CLI). Replaces the openclaude plan that couldn't be forked safely. Rebrand binary, point defaults at hub Ollama + A.R.C.H.I.E. MCP server, ship.

## Phase 5 (next sprint) — Division of labor

Decision doc: when Claude vs when Archie. Handoff pattern example. One end-to-end demo committed as `docs/delegation-demo.md`.

## Risks & gotchas

- **Worker starvation.** 30s interval, 3 tasks/cycle. If Archie gets flooded with delegations (say a Claude session batches 50 sub-tasks), they'll queue. OK for Phase 1 — add priority-based scheduling if it becomes a bottleneck.
- **Dispatcher fallback cost.** Unknown capabilities go through the LLM dispatcher which may escalate to cloud. Each cloud call goes through existing C.R.E.E.D. + approval gates, so the safety rail is the same as any other dispatch.
- **work_notes churn.** Every completed task writes a `work_notes` row. If tasks become high-frequency (>1k/day), consider batch-summarizing into a single daily row via C.O.D.E.X.
- **task status semantics.** We flip to `blocked` on failure, not `failed`. That matches the existing `status` CHECK constraint options in `unified_tasks`. Follow-up: add a `failed` state formally if we want cleaner analytics.
- **No auth on the MCP side.** Anyone with MCP write permission can delegate tasks. For now that's Kytran only (via Claude's MCP session). When we open MCP to external callers, `delegation_source='mcp_client'` gates will need a token/source verification step.

## Live check (Phase 1 exit criteria — verified this commit)

- Migration 344 applied: `delegation_source`, `delegation_args`, `streaming_channel` columns + partial index present on `unified_tasks`
- 13/13 unit tests pass (0.17s, DB-free)
- MCP tool registered — `mcp__archie__delegate_task` callable from any MCP client
- Worker job scheduled — `delegate_task_worker` appears in `autonomy_loop_log` once it processes a non-empty batch

## This week's committed scope

- ✅ Phase 0 — spec (this doc)
- ✅ Phase 1 — delegation surface (this commit)
- Phase 3 — Unified Comms streaming (target: 2026-04-26)
- **Exit criteria:** `delegate_task(capability='run_qa_suite', args={'module':'autonomy'}, reason='Verify X', delegation_source='claude')` from a Claude MCP session → row appears in unified_tasks → worker picks up within 30s → QA suite runs → work_notes row written with result → (Phase 3) Telegram ping.

Phases 2, 4, 5 deferred to next week's sprint under the same project.

---

**Spec lives at `docs/archie-code-cli-spec.md`. Update in place as design evolves.**
