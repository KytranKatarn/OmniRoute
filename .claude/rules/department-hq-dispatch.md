---
globs: ["platform_v2/tools/department_hq/**"]
---

# Department HQ Dispatch Layer (Project #244 Phase 2, 2026-04-11)

Department HQ now owns the dispatch/orchestration/routing layer. Physical files
moved from `ai_bridge/` to `platform_v2/tools/department_hq/services/`.

## Files

| File | Role |
|------|------|
| `services/bridge_dispatcher.py` | Dispatch entry point. `dispatch()`, `dispatch_json()`, `get_dispatcher()`, capability matching, welfare gating, replacement hunt, tier escalation. |
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
from tools.department_hq.services.bridge_dispatcher import dispatch, dispatch_json, get_dispatcher
from tools.department_hq.services.orchestration_engine import OrchestrationEngine
from tools.department_hq.services.smart_router import get_router, TIER_ORDER
```

**Inside `department_hq/services/` itself (relative):**
```python
from .bridge_dispatcher import get_dispatcher
from .smart_router import get_router, TIER_ORDER
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
