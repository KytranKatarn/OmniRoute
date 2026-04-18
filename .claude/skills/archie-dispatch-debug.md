---
name: archie-dispatch-debug
description: Trace why an A.R.C.H.I.E. capability is routing to agent X instead of Y. Inspect match_capability candidates, score_agent breakdown, welfare/busy/budget blocks, and live dispatch result. Invoke when a capability is dispatching to the wrong model, when an agent seems "missing" from dispatch, or when debugging dispatcher routing.
---

# A.R.C.H.I.E. Dispatcher Debugging

Codifies the debug pattern used on 2026-04-18 to diagnose why `translate` was routing to embedder models instead of CODEX. Saves 20+ minutes of trial-and-error every time.

## The flow (top to bottom)

```
caller
  → dispatch_json(capability=, prompt=, module_id=)
  → dispatcher.request_json
  → dispatcher.request_work
  → smart_router.classify_task      (advisory only)
  → coordinator.select_agent        (PICKS the agent)
     └─ for each agent in agent_cache filtered by department:
          score_agent(name, info, capability, department)
            - status/shift_state check (hard block if not active)
            - budget exhaustion check (hard block if ≥95%)
            - welfare score (stress, energy)
            - capability proficiency bonus
            - department match bonus
            - is_department_ai bonus
            - model tier match bonus
  → dispatcher.ensure_model_ready
  → execute LLM call
  → agent_service.increment_budget + decrement_budget
```

## Quick diagnostic snippet

```python
from tools.department_hq.services.department_dispatcher import get_dispatcher
from services.department_coordinator import get_coordinator
from services.agent_service import match_capability, get_agent_cache

capability = "translate"  # change as needed
department = "Documentation & Knowledge"

# 1. Who has this skill at all?
candidates = match_capability(capability)
print(f"{capability}: {len(candidates)} skilled candidates")
for c in candidates[:10]:
    print(f"  {c['name']:<12}  prof={c.get('proficiency_level')}  "
          f"model={c.get('model'):<20}  state={c.get('shift_state')}")

# 2. Score each — who wins and why?
coord = get_coordinator()
cache = get_agent_cache()
for c in candidates:
    info = cache.get(c['name'])
    if not info:
        continue
    score, blocked = coord.score_agent(c['name'], info, capability, department)
    print(f"  {c['name']:<12}  score={score:.2f}  blocked={blocked}")

# 3. Live dispatch — confirm the pick
d = get_dispatcher()
result = d.request_work(
    capability=capability,
    prompt="Translate to French. Respond JSON. TEXT: Hello",
    module_id="dispatch_debug",
    json_mode=True,
    timeout=30,
)
print(f"picked agent={getattr(result, 'agent_name', None)}")
print(f"picked model={getattr(result, 'model', None)}")
print(f"success={result.success}")
print(f"response={(result.response or '')[:200]!r}")
```

Save as `/mnt/archie_brain/scripts/dispatch_debug.py` and run via:

```bash
docker exec archie_platform bash -c '
cd /app
PYTHONPATH=/app:/mnt/archie_brain:/mnt/archie_brain/ai_bridge \
python3 /mnt/archie_brain/scripts/dispatch_debug.py'
```

(The PYTHONPATH matters — without it `from db import _get_db_password` fails. `app.py:285` sets it in Flask runtime; your subprocess needs the same.)

## Common failure patterns

### "Wrong agent gets picked"
- Check `is_department_ai` bonus (+0.3) — department director always beats peers unless explicit blocker
- Check welfare — stressed/low-energy agent still wins if score > others'
- Check **budget counter drift** — a blocked agent forces coordinator to next-best. See `/archie-budget`

### "Translate routes to arctic-embed-cpu (embedder)"
Actual bug observed 2026-04-18. Root cause was CODEX (Lv5 translate) budget-blocked by stale counter (14/10), coordinator fell to EMBER (no translate skill), dispatcher used EMBER's `arctic-embed-cpu` model which doesn't support chat → HTTP 400.
Fix: `/archie-budget` → reconcile, CODEX returns as top pick.

### "Dispatch returns None"
- Model load failed — check `docker logs archie_platform | grep model_service`
- Welfare-based hard block — check `emo.stress_level > 0.85`
- Budget exhaustion — see `/archie-budget`
- `dispatch_json` called with `task=` instead of `capability=` — will TypeError (fixed by generator.py migration 2026-04-18)

### "Response is literal 'mock'"
Caught 2026-04-18. Dispatcher has a fallback path that returned stub string when no valid agent could be resolved. Symptom of capability misroute — fix the routing, not the parsing. Task #2099 history.

## Inspect a specific dispatch

```sql
-- Last 20 dispatches for a capability
SELECT id, agent_name, model_used, capability,
       LEFT(prompt, 60) AS prompt_preview,
       success, duration_ms, created_at
FROM task_execution_log
WHERE capability = 'translate'
ORDER BY created_at DESC LIMIT 20;
```

## Check the coordinator's agent cache

Cache refreshes every 30s from `agents` table. If you just updated an agent and it's not picked:

```python
from services.department_coordinator import get_coordinator
coord = get_coordinator()
coord._refresh_caches()   # force refresh (normally automatic)
print(list(coord._agent_cache.keys()))
```

## Override — force a specific agent

Only for one-off tests, not production:

```python
result = d.request_work(
    capability="translate",
    prompt="...",
    prefer_agent="ROSETTA",   # HINT not override; coordinator may still skip if blocked
    module_id="forced_test",
    json_mode=True,
)
```

Note: `prefer_agent` is advisory — the coordinator still applies its own scoring. If ROSETTA is blocked, another agent wins.

## When to stop debugging and escalate

2 failures → STOP (Rule #3). Surface:
- Who gets picked, why (score breakdown)
- What the user expected
- What you've verified (budget, welfare, model ready, skill present)

Dispatcher internals are deep; over-tweaking creates instability. Often the real fix is upstream (budget counter, model choice, agent welfare) rather than inside `select_agent`.

## Related

- `/archie-agent` — agent-level welfare + skills + proposing peer hire
- `/archie-budget` — counter drift is the #1 cause of mysterious routing failures
- `/archie-status` — platform snapshot including translate pair dispatch state
- `/archie-patterns` — Bridge dispatch canonical imports + return-value contract
