# LLM Ecosystem Redesign — Phase 3+4: Department Dispatch & Welfare System

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dispatcher capability-aware (not just tier-aware) and wire welfare metrics to produce real stress/energy data instead of flat "healthy" for everyone.

**Architecture:** The dispatcher already has agent scoring + welfare caching. classify_task() returns a tier string — we need it to also return capability tags. The welfare math in update_welfare_after_task() is already real (stress/energy from 1hr rolling window) — the issue is it's not being called after dispatches. We fix the pipeline, not rebuild it.

**Tech Stack:** Python (Flask), PostgreSQL, existing dispatcher/router/orchestration code.

**Spec:** `docs/superpowers/specs/2026-04-15-llm-ecosystem-redesign-design.md` — Sections 8, 9
**Depends on:** Phase 0-2 complete (department_capability_profiles table, agent model assignments)

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Rename | `services/bridge_dispatcher.py` → `services/department_dispatcher.py` | Clean naming (Decision #441) |
| Modify | `services/department_dispatcher.py:392` | Rename class BridgeDispatcher → DepartmentDispatcher |
| Modify | `services/smart_router.py:768` | classify_task() returns capability tag alongside tier |
| Modify | `services/department_dispatcher.py:3957` | request_work() queries contractors by capability |
| Modify | `services/orchestration_engine.py:210` | Update imports, use capability in routing step |
| Modify | `ai_bridge/bridge_dispatcher.py` | Update shim to import from renamed file |
| Modify | `services/agent_service.py:1189` | Verify update_welfare_after_task is called post-dispatch |
| Create | `database/migrations/104_dispatch_capability_routing.sql` | Add capability column to dispatch tracking |

---

### Task 1: Rename bridge_dispatcher → department_dispatcher

**Files:**
- Rename: `tools/department_hq/services/bridge_dispatcher.py` → `department_dispatcher.py`
- Modify: `tools/department_hq/services/__init__.py`
- Modify: `ai_bridge/bridge_dispatcher.py` (shim)
- Modify: All internal imports within department_hq/services/

- [ ] **Step 1: Copy file with new name (git tracks as rename)**

```bash
cd /mnt/archie_brain/platform_v2/tools/department_hq/services
git mv bridge_dispatcher.py department_dispatcher.py
```

- [ ] **Step 2: Rename class inside the file**

In `department_dispatcher.py`, find `class BridgeDispatcher:` (line 392) and rename to `class DepartmentDispatcher:`. Also update the docstring.

Search for all references to `BridgeDispatcher` within the file and rename to `DepartmentDispatcher`. Key locations:
- Line 392: class definition
- Line ~7467: `get_dispatcher()` return type / instantiation
- Any self-references in docstrings

- [ ] **Step 3: Update ai_bridge shim**

In `/mnt/archie_brain/ai_bridge/bridge_dispatcher.py`, update the import to reference the new file name and class:
```python
from tools.department_hq.services.department_dispatcher import (
    DepartmentDispatcher as BridgeDispatcher,  # backward compat alias
    dispatch,
    dispatch_json,
    get_dispatcher,
    DispatchResult,
)
```

- [ ] **Step 4: Update internal imports in department_hq/services/**

In `orchestration_engine.py`, find imports from `bridge_dispatcher` and update to `department_dispatcher`.
In `smart_router.py`, check for any bridge_dispatcher imports.
In `__init__.py`, update any re-exports.

- [ ] **Step 5: Verify no broken imports**

```bash
cd /mnt/archie_brain
docker compose restart archie_platform
docker logs --tail 30 archie_platform 2>&1 | grep -i "error\|import"
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: rename bridge_dispatcher → department_dispatcher (Decision #441)

Public API unchanged: dispatch(), dispatch_json(), get_dispatcher() still work.
Shim in ai_bridge/ updated with backward-compat alias.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: classify_task() Returns Capability Tag

**Files:**
- Modify: `tools/department_hq/services/smart_router.py`

Currently `classify_task()` (line 768) returns a **tier string** (e.g., "local", "minimax_cloud"). It needs to also return a **capability tag** from our normalized taxonomy so the dispatcher can match against `department_capability_profiles` and `contractor_providers.capabilities`.

- [ ] **Step 1: Add capability taxonomy mapping**

In `smart_router.py`, near CAPABILITY_ROUTING (line 167), add a mapping from keywords/intent to capability tags:

```python
# Capability taxonomy — maps detected intent to normalized capability tags
# Must match department_capability_profiles.required_capabilities and contractor_providers.capabilities
CAPABILITY_TAXONOMY = {
    "code_generation": ["code", "generate", "implement", "build", "create function", "write code"],
    "code_review": ["review", "audit code", "check code", "code quality"],
    "debugging": ["debug", "fix bug", "error", "traceback", "exception"],
    "architecture": ["architect", "design system", "refactor", "restructure"],
    "summarization": ["summarize", "summary", "tldr", "brief"],
    "reasoning": ["reason", "analyze", "think through", "logic", "explain why"],
    "creative_writing": ["write", "story", "creative", "compose", "draft"],
    "image_generation": ["image", "picture", "draw", "generate image", "visual"],
    "vision": ["describe image", "what is this image", "analyze photo"],
    "classification": ["classify", "categorize", "label", "tag"],
    "data_analysis": ["data", "statistics", "chart", "graph", "trend"],
    "fact_checking": ["fact check", "verify claim", "is this true"],
    "translation": ["translate", "language", "multilingual"],
    "conversation": ["chat", "talk", "discuss", "help"],
    "ethics_reasoning": ["ethical", "creed", "compliance", "policy"],
    "research_synthesis": ["research", "find information", "investigate"],
    "embedding": ["embed", "vector", "similarity"],
    "knowledge_extraction": ["extract", "parse", "pull out"],
}
```

- [ ] **Step 2: Modify classify_task() to return a tuple (tier, capability)**

In `classify_task()` (line 768), after determining the tier, add capability detection:

```python
def classify_task(self, prompt, context=None):
    """Classify task and return (tier, capability) tuple."""
    # ... existing tier classification logic ...
    tier = self._determine_tier(prompt, context)  # existing logic

    # Detect capability from prompt
    capability = self._detect_capability(prompt)

    return tier, capability

def _detect_capability(self, prompt):
    """Detect the primary capability needed from the prompt."""
    prompt_lower = prompt.lower()
    best_match = "conversation"  # default
    best_score = 0
    for capability, keywords in CAPABILITY_TAXONOMY.items():
        score = sum(1 for kw in keywords if kw in prompt_lower)
        if score > best_score:
            best_score = score
            best_match = capability
    return best_match
```

Note: This must be backward-compatible. If existing callers expect a string, use a wrapper or check callers.

- [ ] **Step 3: Update callers of classify_task()**

In `department_dispatcher.py`, find where `classify_task()` is called and update to unpack the tuple:
```python
tier, capability = classify_task(prompt, context)
```

In `orchestration_engine.py`, same update.

- [ ] **Step 4: Verify dispatcher still works**

```bash
docker compose restart archie_platform
docker logs --tail 20 archie_platform 2>&1 | grep -i error
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: classify_task returns capability tag — foundation for capability-aware dispatch

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Capability-Aware Contractor Routing

**Files:**
- Modify: `tools/department_hq/services/department_dispatcher.py`

The dispatcher's escalation currently goes straight to minimax. With the capability tag from classify_task(), it should query `contractor_providers` for matching capability and route by tier position.

- [ ] **Step 1: Add contractor capability query method**

In `department_dispatcher.py`, add a method to DepartmentDispatcher:

```python
def _find_contractor_for_capability(self, capability, max_tier=28, exclude_restricted=False):
    """Find best contractor matching capability, ordered by tier_position (cheapest first).

    Args:
        capability: Normalized capability tag (e.g., 'code', 'image_gen')
        max_tier: Max tier_position to consider (for budget control)
        exclude_restricted: If True, skip creed_compliance_tier=3 contractors

    Returns:
        List of {provider_key, display_name, tier_position, creed_compliance_tier, base_url}
    """
    try:
        from database import get_db
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        query = """
            SELECT provider_key, display_name, tier_position, creed_compliance_tier, base_url, capabilities
            FROM contractor_providers
            WHERE is_active = true
              AND tier_position <= %s
              AND capabilities::text LIKE %s
        """
        params = [max_tier, f'%"{capability}"%']

        if exclude_restricted:
            query += " AND creed_compliance_tier < 3"

        query += " ORDER BY tier_position ASC"

        cur.execute(query, params)
        results = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return results
    except Exception as e:
        logger.warning(f"Contractor capability query failed: {e}")
        return []
```

- [ ] **Step 2: Integrate into escalation flow**

In `request_work()` (line ~3957), after local agent dispatch fails, instead of going straight to minimax, use:

```python
# After local agent dispatch fails...
contractors = self._find_contractor_for_capability(capability, max_tier=13)  # free tier first
if not contractors:
    contractors = self._find_contractor_for_capability(capability, max_tier=28)  # paid tier

for contractor in contractors:
    result = self._dispatch_to_contractor(contractor, prompt, ...)
    if result and result.success:
        return result
```

- [ ] **Step 3: Add _dispatch_to_contractor method**

This calls `external_providers.call_external()` with the contractor's provider_key:

```python
def _dispatch_to_contractor(self, contractor, prompt, system_prompt=None, json_mode=False, timeout=120):
    """Dispatch to a cloud contractor provider."""
    try:
        from ai_bridge.external_providers import call_external
        result = call_external(
            provider_key=contractor['provider_key'],
            prompt=prompt,
            system_prompt=system_prompt,
            json_mode=json_mode,
            timeout=timeout,
        )
        if result.get('success'):
            return DispatchResult(
                success=True,
                response=result.get('response', ''),
                tier=f"contractor:{contractor['provider_key']}",
                agent=None,
                cost=result.get('cost_usd', 0),
            )
    except Exception as e:
        logger.warning(f"Contractor dispatch failed ({contractor['provider_key']}): {e}")
    return None
```

- [ ] **Step 4: Test with a real dispatch**

Trigger a dispatch via MCP or platform and verify it tries contractors before failing.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: capability-aware contractor routing — dispatches by capability+tier, not just minimax

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Wire Welfare Metrics to Dispatch

**Files:**
- Modify: `services/agent_service.py:1189` (update_welfare_after_task)
- Modify: `tools/department_hq/services/department_dispatcher.py`

The welfare math in `update_welfare_after_task()` is already real (stress/energy computed from 1hr rolling window, lines 1189-1250). The problem: it may not be called consistently after every dispatch. We verify and fix the call chain.

- [ ] **Step 1: Verify update_welfare_after_task is called after dispatch**

In `department_dispatcher.py`, search for calls to `update_welfare_after_task` or `svc_update_welfare_after_task`. Verify it's called in the success AND failure paths of `request_work()`.

If missing, add after each dispatch result:

```python
# After successful dispatch
svc_update_welfare_after_task(agent_id, success=True)

# After failed dispatch
svc_update_welfare_after_task(agent_id, success=False)
```

- [ ] **Step 2: Verify welfare cache refresh triggers**

In `_refresh_welfare_cache()` (line 798), verify the 30s TTL is working and that the cache actually queries `agent_emotional_state`. The welfare data should update within 30 seconds of any dispatch.

- [ ] **Step 3: Add mood state transitions**

In `agent_service.py`, after the existing mood logic in `update_welfare_after_task()` (which sets frustrated/concerned/idle/focused/productive), add the state machine transitions:

```python
# Mood state machine (from spec Section 9)
if stress > 0.7:
    mood = "exhausted"  # WINDING_DOWN state
elif stress > 0.5:
    mood = "tense"  # STRAINED state
elif total_tasks == 0:
    mood = "relaxed"  # IDLE state
elif utilization > 0.8:
    mood = "focused"  # ACTIVE state
elif failure_rate > 0.5:
    mood = "frustrated"
elif failure_rate > 0.2:
    mood = "concerned"
else:
    mood = "productive"  # ACTIVE state
```

- [ ] **Step 4: Add department welfare rollup**

In `agent_service.py`, add a new function:

```python
def get_department_welfare_summary():
    """Aggregate welfare metrics per department for K.I.N. monitoring."""
    try:
        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT a.department,
                       AVG(aes.stress_level) as avg_stress,
                       AVG(aes.energy_level) as avg_energy,
                       COUNT(*) FILTER (WHERE aes.stress_level > 0.7) as agents_at_risk,
                       COUNT(*) as total_agents
                FROM agents a
                LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
                WHERE a.worker_type = 'ai' AND a.shift_state = 'active'
                GROUP BY a.department
                ORDER BY avg_stress DESC
            """)
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Department welfare summary failed: {e}")
        return []
```

- [ ] **Step 5: Restart and verify welfare updates**

```bash
docker compose restart archie_platform
# Wait, then check welfare data is non-zero
docker exec archie_database psql -U archie -d archie -c "SELECT a.name, aes.stress_level, aes.energy_level, aes.current_mood FROM agent_emotional_state aes JOIN agents a ON a.id = aes.agent_id WHERE a.worker_type = 'ai' ORDER BY aes.stress_level DESC LIMIT 10"
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: wire welfare metrics to dispatch — real stress/energy updates, department rollup

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Summary

| Task | What It Does | Effort | Risk |
|------|-------------|--------|------|
| 1 | Rename bridge_dispatcher → department_dispatcher | medium | Medium — many imports |
| 2 | classify_task() returns capability tag | medium | Medium — must be backward-compat |
| 3 | Capability-aware contractor routing | medium | Medium — new escalation path |
| 4 | Wire welfare metrics to dispatch | medium | Low — math exists, wiring missing |

**After Phase 3+4:** Dispatcher routes by capability (not just tier), tries free contractors before paid, welfare metrics produce real data after every dispatch.
