# Dispatch Triage Pipeline Upgrade — Design Document

**Date**: 2026-02-23
**Goal**: Make Bridge dispatch skill-aware, workload-enforcing, and capable of requesting new agent creation when no suitable agent exists.

---

## Context

The Bridge dispatcher (`ai_bridge/bridge_dispatcher.py`) routes all LLM work through a deterministic pipeline: capability → station → agent → LLM. The routing is hardcoded via `CAPABILITY_STATION_MAP` and `AGENT_SPECIALIZATION` dicts. While welfare tracking, cloud escalation, and failure recovery exist, three gaps remain:

1. **Skills matching** — `agent_skills` table is populated but never queried during dispatch
2. **Workload enforcement** — stress/energy/rest/budgets are tracked but don't block dispatch
3. **Dynamic agent creation** — no flow exists to create agents when skill gaps are detected

---

## Section 1: Intelligent Agent Selection

### Current Flow
```
_select_agent(capability, station_code):
  1. Look up AGENT_SPECIALIZATION[station][capability] → agent name
  2. Fallback: AGENT_SPECIALIZATION[station]["default"]
  3. Fallback: any agent at station
```

### Proposed Flow
```
_select_best_agent(capability, station_code):
  1. Gather all candidate agents at station (from _agent_cache)
  2. For each candidate, compute score:
     - skills_score: query agent_skills for (agent_id, capability) → proficiency (0-5, normalized to 0-1)
     - specialization_bonus: +0.3 if agent matches AGENT_SPECIALIZATION map
     - welfare_score: (1 - stress) * energy (0-1 range)
     - availability_score: 1.0 if not busy, 0.2 if busy (still eligible, just penalized)
     - budget_score: 1.0 if under daily limit, 0.0 if at/over limit
  3. Filter out agents that are HARD-BLOCKED:
     - Active rest cycle (agent_rest_cycles WHERE ended_at IS NULL)
     - Budget exhausted (current_task_count >= task_queue_limit)
     - Stress >= 0.9 AND energy <= 0.15 (critical welfare)
  4. Sort remaining by composite score (descending)
  5. Return top candidate, or None if all blocked
```

### Scoring Weights
```python
SELECTION_WEIGHTS = {
    "skills": 0.35,        # Does agent have the right skill + proficiency?
    "specialization": 0.25, # Is this the designated specialist?
    "welfare": 0.20,        # How healthy is the agent?
    "availability": 0.15,   # Is agent currently free?
    "budget": 0.05,         # Remaining daily capacity
}
```

### Skills Matching Detail
- Query: `SELECT proficiency_level FROM agent_skills WHERE agent_id = ? AND skill_name = ?`
- Capability-to-skill mapping: reuse `CAPABILITY_STATION_MAP` keys as skill names
- If no skill row exists: score = 0.3 (generous default — agent may still handle it)
- If skill exists: score = proficiency_level / 5.0

### Caching
- Agent skills cached alongside agent metadata in `_agent_cache` (refreshed every 60s)
- Welfare state cached per-agent with 30s TTL (same pattern as Ollama cache)
- Rest cycles checked live (rare, cheap query)

---

## Section 2: Workload Enforcement

### Hard Blocks (Agent Skipped)
| Condition | Source | Check |
|-----------|--------|-------|
| Active rest cycle | `agent_rest_cycles WHERE ended_at IS NULL` | Pre-dispatch |
| Budget exhausted | `agent_budgets.current_task_count >= task_queue_limit` | Pre-dispatch |
| Critical welfare | `stress >= 0.9 AND energy <= 0.15` | Pre-dispatch |

### Soft Penalties (Score Reduced)
| Condition | Source | Effect |
|-----------|--------|--------|
| High stress (0.7-0.9) | `agent_emotional_state` | welfare_score reduced |
| Currently busy | `bridge_jobs WHERE status='running'` | availability_score = 0.2 |
| Near budget limit (>80%) | `agent_budgets` | budget_score = 0.3 |

### Enforcement Integration
In `request_work()`, after `_select_best_agent()` returns None:
1. Log the blockage reason (which agents were considered, why each was blocked)
2. Try cloud escalation (existing `_try_cloud_escalation()` path)
3. If no cloud available and capability is "critical", trigger dynamic agent creation request
4. Return appropriate error/status to caller

### Budget Tracking
After successful dispatch, increment `agent_budgets.current_task_count`. The daily reset is handled by existing APScheduler job (or add one if missing).

---

## Section 3: Dynamic Agent Creation

### Trigger Conditions
Agent creation is requested when ALL of these are true:
1. `_select_best_agent()` returns None (no suitable agent)
2. Cloud escalation is unavailable or inappropriate (local-only capability)
3. The capability gap is not transient (not just "all agents busy right now")

### Deduplication Checks
Before proposing creation:
1. **Existing agent check**: Query `agents` table for any agent with matching skill in `agent_skills` — if found but blocked (rest/budget), this is transient → queue, don't create
2. **Pending creation check**: Query `agent_creation_events WHERE is_approved = FALSE AND terminated_at IS NULL` for same capability → if exists, don't duplicate
3. **Recent creation check**: Query `agent_creation_events WHERE created_at > NOW() - INTERVAL '24 hours'` for same capability → warn in Telegram message

### Telegram Advisory Flow
```
1. System detects skill gap (no agent for capability X)
2. INSERT INTO autonomy_approval_queue:
   - action_type: 'create_agent'
   - action_data: {capability, station_code, suggested_name, suggested_skills, reason}
   - tier: 2 (require human approval)
   - requested_by: 'bridge_dispatcher'
   - reason: "No agent with skill '{capability}' available at station {station}"
3. Send Telegram notification via existing agent_loop.request_approval():
   - Message: "🤖 Agent Creation Request\n\nSkill gap: {capability}\nStation: {station}\nSuggested: {name} with skills [{skills}]\n\nApprove? /approve_{id} or /reject_{id}"
4. On approval:
   - INSERT INTO agents (name, department, station_code, ...)
   - INSERT INTO agent_skills (agent_id, skill_name, proficiency_level=3, ...)
   - INSERT INTO agent_budgets (agent_id, token_limit_per_day=100000, task_queue_limit=10)
   - INSERT INTO agent_creation_events (child_agent_id, creation_reason, is_approved=TRUE, ...)
   - INSERT INTO agent_emotional_state (agent_id, current_mood='neutral', ...)
   - Log to governance_audit_log
   - Invalidate _agent_cache
5. On rejection:
   - UPDATE autonomy_approval_queue SET status='rejected'
   - Log reason to governance_audit_log
```

### Agent Template
New agents are created with sensible defaults:
- `worker_type`: 'internal'
- `cost_tier`: 'free'
- `agent_generation`: parent's generation + 1
- `model`: 'dolphin3-8k' (default local model)
- `proficiency_level`: 3 (mid-level, improves with use)
- Station assignment: the station that triggered the gap

### Safety Rails
- `max_sub_agents` check: ARCHIE (parent) limited to 20 sub-agents
- `agent_generation` depth limit: max 2 (prevents recursive spawning, per IAAE constraint)
- 24-hour cooldown warning for same capability creation
- Human approval required (tier 2) — no auto-creation

---

## Section 4: Integration Points

### Modified Functions
| Function | File | Change |
|----------|------|--------|
| `_select_agent()` | bridge_dispatcher.py | Replace with `_select_best_agent()` (scoring + welfare gates) |
| `request_work()` | bridge_dispatcher.py | Add creation-request fallback after cloud escalation fails |
| `_refresh_agent_cache()` | bridge_dispatcher.py | Load agent_skills + agent_budgets alongside agent metadata |

### New Functions
| Function | File | Purpose |
|----------|------|---------|
| `_score_agent()` | bridge_dispatcher.py | Compute composite selection score |
| `_get_agent_welfare()` | bridge_dispatcher.py | Cached welfare state lookup |
| `_check_hard_blocks()` | bridge_dispatcher.py | Rest cycles + budget + critical welfare |
| `_request_agent_creation()` | bridge_dispatcher.py | Dedup checks + Telegram approval request |
| `_create_agent_from_approval()` | bridge_dispatcher.py | Execute approved creation (INSERT rows) |

### New Endpoint
| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/api/agents/create-from-gap` | Manual trigger from Bridge UI (admin only) |
| GET | `/api/dispatch/agent-gaps` | List recent skill gaps (for UI display) |

### Existing Integrations (No Changes Needed)
- `agent_loop.request_approval()` — already handles Telegram tier-2 flow
- `_try_cloud_escalation()` — unchanged, runs before creation check
- `_update_agent_welfare()` — unchanged, continues post-dispatch tracking
- `governance_audit_log` — already has INSERT pattern for audit events

---

## File Changes Summary

| File | Changes |
|------|---------|
| `ai_bridge/bridge_dispatcher.py` | Replace `_select_agent()` with `_select_best_agent()`, add scoring/welfare/creation functions (~200 lines added, ~20 lines modified) |
| `platform_v2/tools/bridge/routes.py` | Add 2 endpoints for gap visibility + manual creation trigger (~60 lines) |
| `platform_v2/templates/tools/bridge.html` | Optional: skill gap indicator in dispatch tab (~30 lines) |

**Total**: ~290 lines added, ~20 lines modified. No lines removed.
