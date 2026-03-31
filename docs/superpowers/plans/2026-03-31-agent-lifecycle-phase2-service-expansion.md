# Agent Lifecycle Coordination — Phase 2: agent_service Expansion

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move agent lifecycle logic (shift transitions, budget tracking, welfare updates, replacement finding) from bridge_dispatcher.py into agent_service.py, making it the single mutation layer for all agent state changes.

**Architecture:** Five functions move from BridgeDispatcher class methods to standalone functions in agent_service.py. The dispatcher then calls these functions instead of doing SQL directly. The dispatcher's welfare cache invalidation happens after each call.

**Tech Stack:** Python 3.11, Flask, psycopg2, PostgreSQL

**Spec:** `docs/superpowers/specs/2026-03-31-agent-lifecycle-coordination-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `platform_v2/services/agent_service.py` | Add 5 lifecycle functions + constants |
| Modify | `ai_bridge/bridge_dispatcher.py` | Replace 5 methods with calls to agent_service |
| Create | `platform_v2/services/tests/test_agent_lifecycle.py` | Integration tests for new functions |

---

## What Moves

| Dispatcher Method | agent_service Function | Call Sites |
|-------------------|----------------------|------------|
| `_check_shift_transitions(cur)` | `check_shift_transitions()` | `_refresh_welfare_cache()` line 829 |
| `_transition_shift_state(cur, id, name, state, reason)` | `transition_shift_state(agent_id, new_state, reason)` | Lines 947, 958, 1120 |
| `_find_replacement(cur, id, dept)` | `find_replacement(agent_id, department)` | `_transition_shift_state` line 1008 |
| `_update_agent_welfare(id, success)` | `update_welfare_after_task(agent_id, success)` | `_log_execution` line 2673 |
| `_increment_agent_budget(id, tokens)` | `increment_budget(agent_id, tokens_used)` | Lines 4797, 5533 |

---

### Task 1: Add lifecycle constants and transition functions to agent_service.py

**Files:**
- Modify: `platform_v2/services/agent_service.py`
- Create: `platform_v2/services/tests/test_agent_lifecycle.py`

- [ ] **Step 1: Write failing tests for transition_shift_state**

Create `platform_v2/services/tests/test_agent_lifecycle.py`:

```python
"""Tests for agent lifecycle functions (Phase 2).

Integration tests requiring live database.
Run: docker exec archie_platform python -m pytest services/tests/test_agent_lifecycle.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from database import get_db_cursor


@pytest.fixture
def lifecycle_agent():
    """Create a test agent for lifecycle tests, clean up after."""
    agent_id = None
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("""
            INSERT INTO agents (name, display_name, department, floor,
                                status, shift_state, model)
            VALUES ('LifecycleTestAgent', 'Lifecycle Test', 'Analytics & Intelligence',
                    'SERVICES', 'active', 'active', 'test-model')
            RETURNING id
        """)
        agent_id = cur.fetchone()["id"]
        cur.execute("""
            INSERT INTO agent_budgets (agent_id, current_task_count, task_queue_limit,
                                       tokens_used_today, token_limit_per_day, token_reset_at)
            VALUES (%s, 0, 10, 0, 100000, NOW())
        """, (agent_id,))

    yield agent_id

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM agent_rotation_log WHERE agent_id = %s", (agent_id,))
        cur.execute("DELETE FROM agent_budgets WHERE agent_id = %s", (agent_id,))
        cur.execute("DELETE FROM agent_emotional_state WHERE agent_id = %s", (agent_id,))
        cur.execute("DELETE FROM agents WHERE id = %s", (agent_id,))


def test_transition_shift_state_to_cooldown(lifecycle_agent):
    from services.agent_service import transition_shift_state
    result = transition_shift_state(lifecycle_agent, "cooldown", "test_budget_exceeded")
    assert result["success"] is True
    assert result["new_state"] == "cooldown"
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT shift_state FROM agents WHERE id = %s", (lifecycle_agent,))
        assert cur.fetchone()["shift_state"] == "cooldown"


def test_transition_shift_state_logs_rotation(lifecycle_agent):
    from services.agent_service import transition_shift_state
    transition_shift_state(lifecycle_agent, "winding_down", "test_stress")
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT shift_state, reason FROM agent_rotation_log
            WHERE agent_id = %s ORDER BY started_at DESC LIMIT 1
        """, (lifecycle_agent,))
        row = cur.fetchone()
        assert row["shift_state"] == "winding_down"
        assert row["reason"] == "test_stress"


def test_increment_budget(lifecycle_agent):
    from services.agent_service import increment_budget
    increment_budget(lifecycle_agent, tokens_used=500)
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT current_task_count, tokens_used_today
            FROM agent_budgets WHERE agent_id = %s
        """, (lifecycle_agent,))
        row = cur.fetchone()
        assert row["current_task_count"] == 1
        assert row["tokens_used_today"] == 500


def test_increment_budget_accumulates(lifecycle_agent):
    from services.agent_service import increment_budget
    increment_budget(lifecycle_agent, tokens_used=100)
    increment_budget(lifecycle_agent, tokens_used=200)
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT current_task_count, tokens_used_today
            FROM agent_budgets WHERE agent_id = %s
        """, (lifecycle_agent,))
        row = cur.fetchone()
        assert row["current_task_count"] == 2
        assert row["tokens_used_today"] == 300


def test_update_welfare_after_task(lifecycle_agent):
    from services.agent_service import update_welfare_after_task
    # Seed emotional state
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("""
            INSERT INTO agent_emotional_state (agent_id, stress_level, energy_level,
                                               current_mood, mood_intensity)
            VALUES (%s, 0.3, 0.7, 'focused', 0.5)
            ON CONFLICT (agent_id) DO UPDATE SET stress_level = 0.3, energy_level = 0.7
        """, (lifecycle_agent,))
    result = update_welfare_after_task(lifecycle_agent, success=True)
    assert result["success"] is True
    assert "stress" in result
    assert "energy" in result


def test_check_shift_transitions_triggers_cooldown(lifecycle_agent):
    from services.agent_service import check_shift_transitions
    # Set budget to 100% (10/10 tasks)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("""
            UPDATE agent_budgets SET current_task_count = 10, task_queue_limit = 10
            WHERE agent_id = %s
        """, (lifecycle_agent,))
    result = check_shift_transitions()
    # Agent should have transitioned
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT shift_state FROM agents WHERE id = %s", (lifecycle_agent,))
        state = cur.fetchone()["shift_state"]
        assert state in ("cooldown", "winding_down")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform python -m pytest services/tests/test_agent_lifecycle.py -v 2>&1 | tail -20
```

Expected: FAIL — `ImportError: cannot import name 'transition_shift_state'`

- [ ] **Step 3: Add lifecycle constants to agent_service.py**

Add after the existing `COOLDOWN_ENERGY_THRESHOLD = 0.15` line:

```python
# Shift transition thresholds (from bridge_dispatcher.py Phase 2 migration)
WINDING_DOWN_BUDGET_PCT = 0.80   # 80% budget -> winding_down
WINDING_DOWN_STRESS = 0.70       # stress >= 0.70 -> winding_down
COOLDOWN_BUDGET_PCT = 0.95       # 95% budget -> cooldown
COOLDOWN_STRESS = 0.85           # stress >= 0.85 -> cooldown
WINDING_DOWN_SCORE_PENALTY = 0.30
```

- [ ] **Step 4: Implement transition_shift_state**

```python
def transition_shift_state(agent_id, new_state, reason):
    """Transition an agent's shift state with rotation logging.

    Closes the previous rotation log entry, inserts a new one,
    updates the agent's shift_state. If transitioning to cooldown,
    calls find_replacement() to activate a barracked agent.

    Returns dict with success, agent_name, new_state, replacement (if any).
    """
    if new_state not in VALID_SHIFT_STATES:
        return {"success": False, "error": f"Invalid state: {new_state}"}

    with get_db_cursor(commit=True) as (conn, cur):
        # Get agent info
        cur.execute("SELECT name, department FROM agents WHERE id = %s", (agent_id,))
        agent = cur.fetchone()
        if not agent:
            return {"success": False, "error": f"Agent {agent_id} not found"}

        agent_name = agent["name"]
        department = agent["department"]

        # Close previous rotation log entry
        cur.execute("""
            UPDATE agent_rotation_log
            SET ended_at = NOW()
            WHERE agent_id = %s AND ended_at IS NULL
        """, (agent_id,))

        # Insert new rotation log entry
        cur.execute("""
            INSERT INTO agent_rotation_log
                (agent_id, shift_state, reason, started_at)
            VALUES (%s, %s, %s, NOW())
            RETURNING id
        """, (agent_id, new_state, reason))
        rotation_id = cur.fetchone()["id"]

        # Update agent shift state
        cur.execute(
            "UPDATE agents SET shift_state = %s WHERE id = %s",
            (new_state, agent_id),
        )

        replacement = None
        if new_state == "cooldown":
            replacement = find_replacement(agent_id, department, _cur=cur)
            if replacement:
                cur.execute("""
                    UPDATE agent_rotation_log SET replaced_by = %s WHERE id = %s
                """, (replacement["id"], rotation_id))

        logger.info(
            "[Lifecycle] %s -> %s (reason=%s, replacement=%s)",
            agent_name, new_state, reason,
            replacement["name"] if replacement else "none",
        )

    return {
        "success": True,
        "agent_name": agent_name,
        "new_state": new_state,
        "replacement": replacement,
    }
```

- [ ] **Step 5: Implement find_replacement**

```python
def find_replacement(exhausted_agent_id, department, _cur=None):
    """Find and activate a replacement agent in the same department.

    Looks for barracked or off_duty agents in the same department,
    scores them by skill proficiency, and activates the best one.

    Args:
        exhausted_agent_id: The agent being replaced
        department: Department to find replacement in
        _cur: Optional cursor (for transaction sharing with transition_shift_state)

    Returns dict with id/name/score or None.
    """
    def _do_find(cur):
        # Find candidates: same department, available shift states
        cur.execute("""
            SELECT a.id, a.name,
                   COALESCE(AVG(s.proficiency_level), 0.5) AS avg_proficiency
            FROM agents a
            LEFT JOIN agent_skills s ON a.id = s.agent_id
            WHERE a.department = %s
              AND a.status = 'active'
              AND a.shift_state IN ('barracked', 'off_duty')
              AND a.id != %s
            GROUP BY a.id, a.name
            ORDER BY COALESCE(AVG(s.proficiency_level), 0.5) DESC
            LIMIT 1
        """, (department, exhausted_agent_id))
        candidate = cur.fetchone()

        if not candidate:
            logger.info("[Lifecycle] No replacement found in %s", department)
            return None

        # Activate the replacement
        cur.execute(
            "UPDATE agents SET shift_state = 'active' WHERE id = %s",
            (candidate["id"],),
        )
        cur.execute("""
            INSERT INTO agent_rotation_log
                (agent_id, shift_state, reason, started_at)
            VALUES (%s, 'active', 'replacement_activated', NOW())
        """, (candidate["id"],))

        logger.info(
            "[Lifecycle] Replacement: %s activated (proficiency=%.2f)",
            candidate["name"], candidate["avg_proficiency"],
        )
        return {
            "id": candidate["id"],
            "name": candidate["name"],
            "score": float(candidate["avg_proficiency"]),
        }

    if _cur:
        return _do_find(_cur)
    else:
        with get_db_cursor(commit=True) as (conn, cur):
            return _do_find(cur)
```

- [ ] **Step 6: Implement increment_budget**

```python
def increment_budget(agent_id, tokens_used=0):
    """Increment an agent's task count and token usage.

    If token_reset_at has passed, resets counters first.
    Creates budget row if none exists.

    Returns dict with new task_count and tokens_used_today.
    """
    if not agent_id:
        return {"success": False, "error": "No agent_id"}

    with get_db_cursor(commit=True) as (conn, cur):
        # Try reset-if-overdue first
        cur.execute("""
            UPDATE agent_budgets
            SET current_task_count = 1,
                tokens_used_today = %s,
                token_reset_at = NOW() + INTERVAL '1 day'
            WHERE agent_id = %s
              AND token_reset_at < NOW()
            RETURNING current_task_count, tokens_used_today
        """, (tokens_used, agent_id))

        if cur.rowcount == 0:
            # No reset needed — increment
            cur.execute("""
                INSERT INTO agent_budgets
                    (agent_id, current_task_count, tokens_used_today,
                     task_queue_limit, token_limit_per_day, token_reset_at)
                VALUES (%s, 1, %s, 10, 100000, NOW() + INTERVAL '1 day')
                ON CONFLICT (agent_id) DO UPDATE SET
                    current_task_count = agent_budgets.current_task_count + 1,
                    tokens_used_today = agent_budgets.tokens_used_today + %s
                RETURNING current_task_count, tokens_used_today
            """, (agent_id, tokens_used, tokens_used))

        row = cur.fetchone()

    return {
        "success": True,
        "task_count": row["current_task_count"],
        "tokens_used_today": row["tokens_used_today"],
    }
```

- [ ] **Step 7: Implement update_welfare_after_task**

```python
def update_welfare_after_task(agent_id, success=True):
    """Update agent welfare metrics after task completion.

    Calculates stress, energy, mood from recent task history
    (1-hour rolling window from task_execution_log).

    Returns dict with success, stress, energy, mood.
    """
    if not agent_id:
        return {"success": False, "error": "No agent_id"}

    with get_db_cursor(commit=True) as (conn, cur):
        # Get 1-hour rolling task stats
        cur.execute("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN success = false THEN 1 ELSE 0 END) AS failures
            FROM task_execution_log
            WHERE agent_id = %s
              AND created_at > NOW() - INTERVAL '1 hour'
        """, (agent_id,))
        stats = cur.fetchone()
        total = stats["total"] or 0
        failures = stats["failures"] or 0

        # Calculate metrics
        utilization = min(total / 20.0, 1.0) if total > 0 else 0.0
        failure_rate = failures / total if total > 0 else 0.0

        stress = min(utilization * 0.5 + failure_rate * 0.4, 0.9)
        energy = max(0.9 - utilization * 0.3 - failure_rate * 0.2, 0.1)

        if failure_rate > 0.3:
            mood, mood_intensity = "overwhelmed", min(0.5 + failure_rate, 0.9)
        elif utilization > 0.8:
            mood, mood_intensity = "busy", min(utilization, 0.9)
        elif utilization > 0.3:
            mood, mood_intensity = "focused", 0.5 + utilization * 0.2
        else:
            mood, mood_intensity = "idle", 0.3

        # Update emotional state (respect CHECK constraints: stress <= 0.9, energy >= 0.1)
        cur.execute("""
            INSERT INTO agent_emotional_state
                (agent_id, stress_level, energy_level, current_mood, mood_intensity)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (agent_id) DO UPDATE SET
                stress_level = EXCLUDED.stress_level,
                energy_level = EXCLUDED.energy_level,
                current_mood = EXCLUDED.current_mood,
                mood_intensity = EXCLUDED.mood_intensity
        """, (agent_id, stress, energy, mood, mood_intensity))

    return {
        "success": True,
        "stress": stress,
        "energy": energy,
        "mood": mood,
        "mood_intensity": mood_intensity,
    }
```

- [ ] **Step 8: Implement check_shift_transitions**

```python
def check_shift_transitions():
    """Check all active/winding_down agents for automatic state transitions.

    Reads budget and stress levels, transitions agents that exceed thresholds:
    - 95% budget or stress >= 0.85 -> cooldown
    - 80% budget or stress >= 0.70 -> winding_down

    Returns dict with transitions list.
    """
    transitions = []
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("""
            SELECT a.id, a.name, a.shift_state, a.department,
                   COALESCE(ab.current_task_count, 0) AS task_count,
                   COALESCE(ab.task_queue_limit, 10) AS task_limit,
                   COALESCE(ab.tokens_used_today, 0) AS tokens_used,
                   COALESCE(ab.token_limit_per_day, 100000) AS token_limit,
                   COALESCE(es.stress_level, 0.0) AS stress
            FROM agents a
            LEFT JOIN agent_budgets ab ON a.id = ab.agent_id
            LEFT JOIN agent_emotional_state es ON a.id = es.agent_id
            WHERE a.status = 'active'
              AND a.shift_state IN ('active', 'winding_down')
        """)
        rows = cur.fetchall()

    # Process transitions outside the read cursor
    for row in rows:
        task_pct = row["task_count"] / row["task_limit"] if row["task_limit"] > 0 else 0.0
        token_pct = row["tokens_used"] / row["token_limit"] if row["token_limit"] > 0 else 0.0
        budget_pct = max(task_pct, token_pct)
        stress = row["stress"]

        if budget_pct >= COOLDOWN_BUDGET_PCT or stress >= COOLDOWN_STRESS:
            if row["shift_state"] != "cooldown":
                reason = (f"budget={budget_pct:.0%}"
                          if budget_pct >= COOLDOWN_BUDGET_PCT
                          else f"stress={stress:.2f}")
                result = transition_shift_state(row["id"], "cooldown", reason)
                if result["success"]:
                    transitions.append({"agent": row["name"], "to": "cooldown", "reason": reason})

        elif budget_pct >= WINDING_DOWN_BUDGET_PCT or stress >= WINDING_DOWN_STRESS:
            if row["shift_state"] == "active":
                reason = (f"budget={budget_pct:.0%}"
                          if budget_pct >= WINDING_DOWN_BUDGET_PCT
                          else f"stress={stress:.2f}")
                result = transition_shift_state(row["id"], "winding_down", reason)
                if result["success"]:
                    transitions.append({"agent": row["name"], "to": "winding_down", "reason": reason})

    if transitions:
        logger.info("[Lifecycle] Shift transitions: %s", transitions)
    return {"transitions": transitions}
```

- [ ] **Step 9: Run tests**

```bash
docker exec archie_platform python -m pytest services/tests/test_agent_lifecycle.py -v 2>&1 | tail -20
```

Expected: All 7 tests PASS

- [ ] **Step 10: Commit**

```bash
git add platform_v2/services/agent_service.py platform_v2/services/tests/test_agent_lifecycle.py
git commit -m "feat(agent-service): add lifecycle functions — shift, budget, welfare, replacement

Phase 2 of Agent Lifecycle Coordination. Adds transition_shift_state,
find_replacement, increment_budget, update_welfare_after_task, and
check_shift_transitions to agent_service.py as standalone functions."
```

---

### Task 2: Update bridge_dispatcher.py to call agent_service

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py`

This is the critical refactor — replacing the dispatcher's internal methods with calls to agent_service.

- [ ] **Step 1: Add agent_service imports to bridge_dispatcher.py**

Near the top of bridge_dispatcher.py (after existing imports), add:

```python
# Phase 2: Agent lifecycle delegated to agent_service
from services.agent_service import (
    transition_shift_state as svc_transition_shift_state,
    find_replacement as svc_find_replacement,
    increment_budget as svc_increment_budget,
    update_welfare_after_task as svc_update_welfare_after_task,
    check_shift_transitions as svc_check_shift_transitions,
)
```

Use aliased imports to avoid name collisions with the existing methods during migration.

- [ ] **Step 2: Replace _check_shift_transitions call**

In `_refresh_welfare_cache()` around line 829, find where `_check_shift_transitions(cur2)` is called. Replace with:

```python
# Phase 2: Delegate to agent_service
svc_check_shift_transitions()
# Invalidate welfare cache to pick up state changes
self._welfare_cache_time = 0
```

Remove the cursor that was only used for shift transitions (cur2/conn2) if it's no longer needed for anything else.

- [ ] **Step 3: Replace _update_agent_welfare call**

In `_log_execution()` around line 2673, find:

```python
self._update_agent_welfare(result.agent_id, result.success)
```

Replace with:

```python
svc_update_welfare_after_task(result.agent_id, result.success)
self._welfare_cache_time = 0  # Invalidate cache
```

- [ ] **Step 4: Replace _increment_agent_budget calls**

At line ~4797 in `request()` and line ~5533 in `create_job()`, find:

```python
self._increment_agent_budget(agent.get("id"), tokens_used=...)
```

Replace with:

```python
svc_increment_budget(agent.get("id"), tokens_used=...)
```

- [ ] **Step 5: Mark old methods as deprecated**

Add a deprecation comment to each of the 5 old methods (do NOT delete them yet — keeps backward compatibility):

```python
def _check_shift_transitions(self, cur):
    """DEPRECATED: Use services.agent_service.check_shift_transitions() instead.
    Kept for backward compatibility during Phase 2 migration.
    """
    # Original implementation stays but is no longer called
    ...
```

- [ ] **Step 6: Run the full test suite**

```bash
docker exec archie_platform python -m pytest services/tests/ -v 2>&1 | tail -30
```

Expected: All tests pass (Phase 1 + Phase 2 tests)

- [ ] **Step 7: Restart and verify logs**

```bash
docker compose restart archie_platform
sleep 15
docker logs --since=30s archie_platform 2>&1 | grep -i 'lifecycle\|shift.*transition\|welfare\|budget.*increment\|embedding' | tail -15
```

Expected: No errors, embedding still processing

- [ ] **Step 8: Commit**

```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "refactor(dispatcher): delegate lifecycle to agent_service

Phase 2: Bridge dispatcher now calls agent_service for shift transitions,
budget increments, welfare updates, and replacement finding instead of
doing SQL directly. Old methods marked deprecated."
```

---

## Summary

| Task | What | Files | Commits |
|------|------|-------|---------|
| 1 | Lifecycle functions in agent_service | agent_service.py + tests | 1 |
| 2 | Dispatcher calls agent_service | bridge_dispatcher.py | 1 |

**Total: 2 commits, 1 new test file, 2 modified files**

After Phase 2:
- agent_service.py is the single mutation layer for all agent state
- Bridge dispatcher is a pure router (reads state, delegates mutations)
- Old dispatcher methods still exist but marked deprecated (removed in Phase 5)
- Embedding pipeline continues working (verified in Task 2 Step 7)
