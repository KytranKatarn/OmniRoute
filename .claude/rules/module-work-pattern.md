# Module Work Pattern — MANDATORY (ADR-002 / decision #676, 2026-06-01)

**Every module's recurring and async work runs on the agent fleet via DHQ — never synchronously on the web thread, never ground through by Claude hands-on.**

The platform is a 34-AI-agent organization on a GPU cluster. The agents are the workforce; Claude coordinates and ships. Work must drain continuously, in parallel, welfare-gated, cost-tracked, and visible.

## The contract (every module)

A module's work is expressed as one or both of:

1. **Scheduled jobs** — APScheduler jobs (in `ai_bridge/agent_loop.py` or a module jobs file) that **dispatch to the fleet** via `tools.department_hq.services.department_dispatcher.dispatch()`. For recurring work (polls, scans, loops, digests).
2. **Backlog drained on the fleet**:
   - **Cross-module work items** (`unified_tasks`) → the **generic Fleet Backlog Runner** (scheduled job: scans pending tasks → maps capability → `delegate_task` → fleet, rate-limited + K.I.N. welfare-gated).
   - **Domain-specific backlog** (e.g. WTF article reprocessing, KB unembedded entries) → its **own scheduled job**, which still **dispatches to the fleet** (never sync, never hands-on).

Everything routes through the **DHQ dispatcher** → fleet agent on the cluster → result in `work_notes` / `task_execution_log`. Long LLM calls use the async+poll pattern (return 202, poll a DB row) — never block the web worker.

## Reference implementations (copy these)

| Module | Jobs | Backlog |
|--------|------|---------|
| **Consciousness** | embedding / analysis / translate loops (every 30 min) | unembedded `knowledge_base` entries, batched |
| **Repair Bay** | proactive scan (6h), scan→propose pipeline | weekly batch (Sun 02:00) for medium issues |
| **WTF** | `wtf-ingest` RSS poll (30 min) | LLM backlog (`WTF_LLM_BACKLOG_ENABLED`, capped/night) |
| **Dept HQ** | `delegate_task_worker` (30s, 3/cycle) | — (it IS the generic delegation drain) |

## Forbidden

- ❌ Synchronous LLM/inference on the web thread (times out the gunicorn worker).
- ❌ Direct Ollama calls from modules (ADR-013 — go through DHQ dispatch). Embeddings are the documented exception.
- ❌ **Claude grinding backlog by hand.** "coordinate N in parallel" / "work the backlog" = `delegate_task` to the fleet. Claude reserves hands-on for orchestration + the final merge/deploy/verify. (KB #250231 / #269994.)
- ❌ A new module with no declared jobs **and** no backlog routing.

## Governance gate (new modules)

A module is **not complete** until it declares, in its capability-index entry, **how its recurring + async work reaches the fleet** (which jobs, which backlog). Non-conforming modules → file a remediation task and delegate the fix to the fleet.

## How to delegate (the mechanism)

```python
mcp__archie__delegate_task(
    capability="research|analyze|module_audit|security|compliance|code|...",
    reason="<actionable task description — this is the agent's prompt>",
    delegation_source="claude",   # or "automation" for scheduled runners
)
# → unified_tasks → delegate_task_worker (30s, 3/cycle) → DHQ dispatcher
# → fleet agent on cluster → result in work_notes
```

Map capability → department: research→D.A.R.W.I.N. · analyze/knowledge_analysis→S.P.E.C.T.R.A./W.A.T.C.H. · security/compliance→V.I.G.I.L. · module_audit/documentation→C.O.D.E.X. · code/code_review→F.O.R.G.E. (see `CAPABILITY_DEPARTMENT_MAP` in `department_coordinator.py`).

---
*Standard set 2026-06-01 (ADR-002). The generic Fleet Backlog Runner is the always-on drain that makes every module's `unified_tasks` flow to the fleet without manual delegation.*
