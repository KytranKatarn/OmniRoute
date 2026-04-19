---
globs: ["platform_v2/tools/department_hq/**"]
---

# Department HQ Dispatch Layer (Project #244 Phase 2, 2026-04-11)

Department HQ now owns the dispatch/orchestration/routing layer. Physical files
moved from `ai_bridge/` to `platform_v2/tools/department_hq/services/`.

## Files

| File | Role |
|------|------|
| `services/department_dispatcher.py` | Dispatch entry point (renamed from `bridge_dispatcher`, Decision #441). `dispatch()`, `dispatch_json()`, `get_dispatcher()`, capability matching, welfare gating, replacement hunt, tier escalation. |
| `services/orchestration_engine.py` | 8-step pipeline: intent → IAAE → welfare → route → agent → GPU → execute → log. |
| `services/smart_router.py` | GPU-aware 11-tier escalation. `get_router()`, `classify_task()`, `TIER_ORDER`, `CAPABILITY_ROUTING`. |

## Runtime Flow

```
caller → dispatch() → BridgeDispatcher.request_work()
     → classify_task() (smart_router)
     → capability match against agent_service.get_agent_cache()
     → welfare check (stress/mood/fatigue)
     → ensure_model_ready() (warmboot via agent_service.models)
     → orchestration_engine.run() (8 steps)
     → external_providers / ollama_client
     → DispatchResult(success, response, tier, agent, cost)
     → agent_service.increment_usage() + update_performance_metrics()
```

## Import Rules

**Canonical (new code):**
```python
from tools.department_hq.services.department_dispatcher import dispatch, dispatch_json, get_dispatcher
from tools.department_hq.services.orchestration_engine import OrchestrationEngine
from tools.department_hq.services.smart_router import get_router, TIER_ORDER
```

**Inside `department_hq/` package (relative):**
```python
from .services.department_dispatcher import get_dispatcher     # from routes at tools/department_hq/
from .department_dispatcher import get_dispatcher              # from siblings inside services/
from .smart_router import get_router, TIER_ORDER               # from siblings inside services/
```

**Forbidden in new code** (enforced by `scripts/check_agent_single_writer.py`):
```python
from ai_bridge.bridge_dispatcher import ...    # shim — DeprecationWarning
from ai_bridge.orchestration_engine import ... # shim — DeprecationWarning
from ai_bridge.smart_router import ...         # shim — DeprecationWarning
```

The `ai_bridge/` shims star-re-export the new modules so existing call sites keep
working during the transition window. They will be removed once all call sites
have been migrated.

## Agent Table Mutations

All agents-table writes still go through `platform_v2/services/agent_service.py`
(Project #241 Track C). The dispatcher calls `agent_service.increment_usage()` and
`agent_service.update_performance_metrics()` — it does **not** write SQL directly.

## Contractor Dispatch (Phase 7, in progress)

When the dispatcher picks a `worker_type='contract'` agent and estimated cost
exceeds `auto_approve_threshold`, it routes through `request_approval()` with
`action_type='contractor_dispatch'` and blocks on `wait_for_approval()` until a
Telegram approve/deny/escalate button press resolves it. See `autonomy.md` for
the approval pipeline.

## Agent Selection (2026-04-19)

The canonical agent selection path is **skill-based**, not name-based:

```
dispatch(capability, ...) → coordinator.select_agent(capability, department)
   → loops over _agent_cache for matching department
   → score = 1.0 + (1-stress)*0.3 + energy*0.2 - util*0.5
             + skill_proficiency * 0.2 if capability in agent.skills
             + 0.2 if dept match
             + 0.3 if is_department_ai
             + tier-match bonus if recommended_tier
   → highest positive score wins
   → if NO active candidate scores > 0:
        → _wake_barracked_specialist(capability, department)
          → finds barracked agent with proficiency ≥ 3 on the skill
          → agent_service.transition_shift_state(id, 'active', 'wake_on_demand')
          → governance_audit_log entry written
          → returns the woken agent
```

**Consequences for making an agent dispatchable:**

1. Populate `agent_skills(agent_id, skill_name, proficiency_level, can_escalate_to)` — `skill_name` must match the `capability=` string passed to `dispatch()`.
2. Active/barracked shift state both work — barracked specialists wake on demand when no active candidate qualifies.
3. `is_department_ai=true` gives a +0.3 bonus (department directors preferred unless a skilled specialist has enough raw score to overcome it).

**Removed in #2165:** `AGENT_SPECIALIZATION` dict and `get_agent_for_module()` helper are gone. All agent selection goes through `coordinator.select_agent(capability, department)` — skill-based with wake-on-demand fallback. Regression tests in `test_dispatch_scoring.py::TestLegacySymbolsRemoved` prevent reintroduction.

## Approval Queue Surface (2026-04-19)

`GET /api/approvals/pending` returns a unified list across three sources:
- `autonomy_approval_queue` (Tier-2 agent-loop actions)
- `contractor_approval_requests` (cost-gated contractor dispatch)
- `bridge_jobs.status='pending_approval'` (cloud dispatch gate)

Each row normalised to `{id, source, category, display_name, reason, agent_name, created_at}`. IDs are source-prefixed (`autonomy:123`, `contractor:456`, `bridge:789`).

The `reap_stale_pending_approvals` job (daily 04:30 UTC) auto-cancels `bridge_jobs.pending_approval` rows older than 7 days and decrements the matching `agent_budgets.current_task_count`.

**Canonical "active work" for agent_budgets**: `bridge_jobs.status NOT IN ('completed', 'failed', 'cancelled')`. This is what `reconcile_task_counters` uses; any drift observer must share the same filter.
