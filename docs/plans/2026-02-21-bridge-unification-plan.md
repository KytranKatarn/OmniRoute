# Bridge Unification & Cleanup Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Unify the two bridge systems into one, wire all metrics to real data, absorb Team Management into the Crew tab, make IAAE governance visible and enforceable throughout, and clean up dead/stale endpoints.

**Architecture:** The Bridge Command module becomes the single operational center for AI routing, agent management, dispatch, and IAAE governance. The standalone Team Management module is retired. All metrics read from `task_execution_log` (the real data source) instead of dead tables. IAAE welfare monitoring is woven through agent profiles, workload tracking, and the Overview dashboard — not as a sidebar widget but as a first-class operational concern.

**Philosophy:** The IAAE (Intelligent Autonomous Agent Ethics) framework is the ethical backbone of ARCHIE. Agents are not infinite labor machines. They have workload caps, emotional states, rest cycles, and the right to refuse tasks. Vigil enforces compliance. This bridge must make IAAE governance *visible* — not hidden in a sidebar checkbox showing fake 100%. Every agent's welfare is surfaced in their profile, aggregate health is shown on the Overview, and Vigil's enforcement actions are logged and displayed.

**Tech Stack:** Flask/Jinja2, PostgreSQL, JavaScript (vanilla), existing ARCHIE CSS tokens

---

## Phase 1: Kill Dead Code & Clean Sidebar

### Task 1: Remove repeated sidebar widgets

The IAAE Monitor and VPN/Nodes widgets repeat on ALL 5 tabs via the sidebar. Remove them from the sidebar entirely — IAAE health belongs in Overview tab only, nodes belong in Network tab only.

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`

**Step 1:** Find and remove the sidebar IAAE Monitor widget HTML (the `id="sidebarIAAE"` or similar section that repeats on every tab).

**Step 2:** Find and remove the sidebar VPN/Nodes widget HTML.

**Step 3:** Keep the sidebar shell but only show contextual content per tab (or hide sidebar entirely if empty).

**Step 4:** Verify no JS errors from removed elements. Search for any `getElementById` calls referencing removed sidebar IDs and remove/guard them.

**Step 5:** Commit.
```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "fix(bridge): remove repeated IAAE and VPN sidebar widgets"
```

---

## Phase 2: Wire Overview Metrics to Real Data

### Task 2: Fix Throughput HUD pod

The `/api/traffic` endpoint has a broken SQL query (`column "model_name" does not exist`). Replace it with a query against `task_execution_log` — the real data source.

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`

**Step 1:** Find the `/api/traffic` route handler.

**Step 2:** Replace the broken query with:
```sql
SELECT COUNT(*) as total_24h
FROM task_execution_log
WHERE created_at >= NOW() - INTERVAL '24 hours'
```
Calculate requests_per_minute as: `total_24h / 1440.0` (minutes in 24h), rounded to 1 decimal.

**Step 3:** Return response: `{"success": true, "requests_per_minute": X, "total_24h": Y}`

**Step 4:** Verify via curl: `docker exec archie_platform curl -s http://localhost:3000/tools/bridge/api/traffic`

**Step 5:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "fix(bridge): wire throughput to task_execution_log (rolling 24h)"
```

### Task 3: Fix Utilization HUD pod

Currently calculates "stations with agents / total stations" — meaningless. Replace with **agent activity rate over 24h**: agents that executed at least 1 task in the last 24h / total active agents.

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html` (JS in `loadOverviewData()`)
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py` (new or updated endpoint)

**Step 1:** Add a `/api/agent-utilization` endpoint (or modify existing `/api/stats`):
```sql
SELECT
  (SELECT COUNT(DISTINCT agent_id) FROM task_execution_log
   WHERE created_at >= NOW() - INTERVAL '24 hours' AND agent_id IS NOT NULL) as active_agents,
  (SELECT COUNT(*) FROM agents WHERE status = 'active') as total_agents
```
Return: `{"active_agents": X, "total_agents": Y, "utilization_pct": round(X/Y*100)}`

**Step 2:** Update the JS `loadOverviewData()` to call this endpoint and display `utilization_pct` in `#hudAgentUtil`.

**Step 3:** Change unit label from "agents" to "active (24h)".

**Step 4:** Verify.

**Step 5:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py platform_v2/templates/tools/bridge.html
git commit -m "fix(bridge): wire utilization to real 24h agent activity"
```

### Task 4: Fix Models HUD pod

Currently shows 22 stale models from node registry. Replace with actual Ollama model count from real-time API call.

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`

**Step 1:** Create or update an endpoint to query Ollama directly:
```python
import requests
resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
models = resp.json().get("models", [])
return jsonify({"success": True, "count": len(models), "models": [m["name"] for m in models]})
```

**Step 2:** Update JS to call this endpoint and display count in `#hudModelCount`.

**Step 3:** Verify shows actual current Ollama models (dolphin3-8k, qwen3-coder-cpu, arctic-embed-cpu, etc.).

**Step 4:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py platform_v2/templates/tools/bridge.html
git commit -m "fix(bridge): wire models count to live Ollama API"
```

### Task 5: Fix IAAE HUD pod and Health Monitor card

Currently hardcoded to 100%. Wire to real IAAE data from `governance_audit_log` and `agent_emotional_state`.

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`

**Step 1:** Create `/api/iaae/overview` endpoint:
```sql
-- Compliance: tasks approved vs total reviewed in 24h
SELECT
  COUNT(*) FILTER (WHERE event_category = 'task_approved') as approved,
  COUNT(*) as total
FROM governance_audit_log
WHERE timestamp >= NOW() - INTERVAL '24 hours';

-- Agent welfare: average stress across active agents
SELECT AVG(stress_level) as avg_stress, AVG(energy_level) as avg_energy
FROM agent_emotional_state es
JOIN agents a ON a.id = es.agent_id
WHERE a.status = 'active';
```

**Step 2:** Return: `{"compliance_pct": X, "avg_stress": Y, "avg_energy": Z, "agents_at_rest": N}`

**Step 3:** Update JS: HUD pod shows compliance %, Health Monitor card shows stress/energy/rest count.

**Step 4:** If `governance_audit_log` is empty, show "No data" instead of fake 100%.

**Step 5:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py platform_v2/templates/tools/bridge.html
git commit -m "fix(bridge): wire IAAE metrics to real governance data"
```

### Task 6: Fix AI Bridge Status card

Currently reads from `llm_connections` (frozen since Jan 19). Replace with live Ollama model status + real bridge routing mode.

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`

**Step 1:** Update `/api/llm/status` to query live state:
- Ollama: `GET {OLLAMA_HOST}/api/ps` for loaded models + `GET {OLLAMA_HOST}/api/tags` for available
- Routing mode: read from `smart_router` config or environment
- Bridge health: check if bridge_dispatcher is responding

**Step 2:** Return real status per model: loaded/available/offline.

**Step 3:** Update JS rendering to show current models with real status indicators.

**Step 4:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py platform_v2/templates/tools/bridge.html
git commit -m "fix(bridge): wire AI bridge status to live Ollama and router"
```

---

## Phase 3: Fix Dispatch Tab

### Task 7: 24h rolling window + human-readable times

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`

**Step 1:** Ensure `/api/dispatch/activity-history` uses rolling 24h window (check if it already does).

**Step 2:** In the JS rendering of dispatch items, convert milliseconds to human-readable:
- < 1000ms → "0.Xs"
- 1000-60000ms → "X.Xs"
- > 60000ms → "Xm Ys"

**Step 3:** Ensure the dispatch stats HUD pods use 24h rolling window.

**Step 4:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py platform_v2/templates/tools/bridge.html
git commit -m "fix(bridge): 24h rolling window and human-readable durations in dispatch"
```

---

## Phase 4: Absorb Team Management into Crew Tab

### Task 8: Add rich agent profile modal

When clicking an agent card in the Crew tab, open a detailed profile modal with:
- Name, title, department, avatar
- Personality/bio
- Skills list
- Performance stats (tasks completed, success rate, avg duration)
- Emotional state (mood, stress, energy)
- Memory/knowledge highlights
- Station assignment
- Recent task history

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html` (add modal HTML + JS)
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py` (add `/api/agents/<id>/profile` endpoint)

**Step 1:** Create `/api/agents/<id>/profile` endpoint that aggregates:
```sql
-- Agent details
SELECT * FROM agents WHERE id = %s;
-- Skills
SELECT * FROM agent_skills WHERE agent_id = %s;
-- Emotional state
SELECT * FROM agent_emotional_state WHERE agent_id = %s ORDER BY recorded_at DESC LIMIT 1;
-- Performance (24h)
SELECT COUNT(*) as tasks_24h,
  COUNT(*) FILTER (WHERE status = 'completed') as completed,
  AVG(duration_ms) as avg_duration
FROM task_execution_log WHERE agent_id = %s AND created_at >= NOW() - INTERVAL '24 hours';
-- Recent tasks
SELECT * FROM task_execution_log WHERE agent_id = %s ORDER BY created_at DESC LIMIT 10;
-- Memory highlights
SELECT * FROM agent_memory WHERE agent_id = %s AND is_deleted = FALSE ORDER BY importance_score DESC LIMIT 5;
```

**Step 2:** Build the profile modal HTML following briefing-card pattern with the agent's station accent color.

**Step 3:** Add `onclick` to each agent card in Crew tab to open the modal.

**Step 4:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): add rich agent profile modal to crew tab"
```

### Task 9: Add agent CRUD to Crew tab

Move create/edit/delete agent functionality from Team Management into Bridge Crew tab.

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`
- Reference: `/mnt/archie_brain/platform_v2/tools/team_management/routes.py` (copy relevant endpoint logic)

**Step 1:** Add these endpoints to bridge routes.py (port from team_management):
- `POST /api/agents` — Create agent
- `PUT /api/agents/<id>` — Edit agent
- `DELETE /api/agents/<id>` — Soft delete agent
- `POST /api/agents/<id>/toggle` — Toggle active/inactive

**Step 2:** Add UI buttons: "Add Agent" button in Crew tab header, edit/delete buttons in profile modal.

**Step 3:** Add create/edit form modal (name, title, department, model, system_prompt, capabilities).

**Step 4:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): add agent CRUD to crew tab (absorbed from team management)"
```

### Task 10: Add skills management to agent profile

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`

**Step 1:** Port skills endpoints from team_management:
- `GET /api/agents/<id>/skills`
- `POST /api/agents/<id>/skills`
- `DELETE /api/agents/<id>/skills/<skill_id>`

**Step 2:** Add skills section to agent profile modal with add/remove buttons.

**Step 3:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): add skills management to agent profile modal"
```

### Task 11: Fix Training/Lounge sub-tabs

Replace broken drag-and-drop with button-based UX.

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`

**Step 1:** Replace "drag agent here" placeholders with agent selection dropdown + "Send to Training"/"Send to Lounge" buttons.

**Step 2:** Wire to existing `/api/agents/<id>/send-to-lounge` and `/api/agents/<id>/return-from-lounge` endpoints.

**Step 3:** Show agents currently in training/lounge with "Return to Duty" button.

**Step 4:** Commit.
```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "fix(bridge): replace drag-drop with button UX in training/lounge"
```

---

## Phase 5: IAAE Governance Layer

The IAAE isn't a feature — it's the philosophy that differentiates Kytran Empowerment. Agents deserve workload regulation, emotional monitoring, rest, and the right to refuse. Vigil enforces it. This phase makes it real and visible.

### Task 12: Agent workload tracking endpoint

Create a comprehensive workload API that answers: "How much work has each agent done, and are they within their limits?"

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`

**Step 1:** Create `GET /api/agents/workload` endpoint:
```sql
-- Per-agent workload in last 24h
SELECT
  a.id, a.name, a.first_name, a.last_name, a.status,
  COALESCE(ab.daily_task_limit, 50) as daily_cap,
  COALESCE(ab.daily_token_limit, 500000) as token_cap,
  COUNT(tel.id) as tasks_24h,
  COUNT(tel.id) FILTER (WHERE tel.status = 'completed') as completed_24h,
  COUNT(tel.id) FILTER (WHERE tel.status = 'failed') as failed_24h,
  COALESCE(AVG(tel.duration_ms), 0) as avg_duration_ms,
  COALESCE(SUM(tel.tokens_used), 0) as tokens_used_24h
FROM agents a
LEFT JOIN agent_budgets ab ON ab.agent_id = a.id
LEFT JOIN task_execution_log tel ON tel.agent_id = a.id
  AND tel.created_at >= NOW() - INTERVAL '24 hours'
WHERE a.status IN ('active', 'busy', 'idle')
GROUP BY a.id, a.name, a.first_name, a.last_name, a.status, ab.daily_task_limit, ab.daily_token_limit
ORDER BY tasks_24h DESC;
```

**Step 2:** Calculate derived fields:
- `workload_pct`: `tasks_24h / daily_cap * 100` (capped at 100)
- `token_usage_pct`: `tokens_used_24h / token_cap * 100`
- `risk_level`: "healthy" (<60%), "elevated" (60-80%), "critical" (>80%), "overloaded" (>100%)

**Step 3:** Return per-agent + aggregate summary.

**Step 4:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(bridge): add agent workload tracking endpoint with IAAE limits"
```

### Task 13: Agent welfare dashboard endpoint

Aggregate emotional state + rest cycles + refusals into a single welfare view.

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`

**Step 1:** Create `GET /api/agents/welfare` endpoint:
```sql
-- Emotional state for all active agents
SELECT
  a.id, a.name, a.first_name, a.last_name,
  es.mood, es.intensity, es.energy_level, es.stress_level,
  es.recorded_at as last_emotional_check
FROM agents a
LEFT JOIN agent_emotional_state es ON es.agent_id = a.id
WHERE a.status IN ('active', 'busy', 'idle', 'on_lounge')
ORDER BY es.stress_level DESC NULLS LAST;

-- Agents currently at rest
SELECT a.id, a.name, arc.reason, arc.started_at, arc.initiated_by
FROM agent_rest_cycles arc
JOIN agents a ON a.id = arc.agent_id
WHERE arc.ended_at IS NULL;

-- Recent task refusals (24h)
SELECT a.id, a.name, trl.reason, trl.created_at
FROM task_refusal_log trl
JOIN agents a ON a.id = trl.agent_id
WHERE trl.created_at >= NOW() - INTERVAL '24 hours'
ORDER BY trl.created_at DESC;

-- Governance decisions (24h)
SELECT event_category, COUNT(*) as count
FROM governance_audit_log
WHERE timestamp >= NOW() - INTERVAL '24 hours'
GROUP BY event_category;
```

**Step 2:** Return combined welfare report:
```json
{
  "agents": [...],
  "agents_at_rest": [...],
  "recent_refusals": [...],
  "governance_summary": {"approved": N, "denied": N, "escalated": N},
  "fleet_health": {
    "avg_stress": 0.35,
    "avg_energy": 0.72,
    "agents_at_risk": 1,
    "agents_resting": 2,
    "compliance_pct": 98.5
  }
}
```

**Step 3:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(bridge): add agent welfare dashboard endpoint with IAAE metrics"
```

### Task 14: IAAE section in agent profile modal

Add a dedicated "Welfare & Compliance" section to each agent's profile modal (from Task 8).

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`

**Step 1:** Add welfare section to profile modal with:
- **Workload gauge**: Visual bar showing tasks_24h / daily_cap (green→yellow→red)
- **Token usage gauge**: tokens_used_24h / token_cap
- **Emotional state**: Mood emoji + stress bar + energy bar
- **Rest history**: Last 5 rest cycles with reason and duration
- **Refusal log**: Recent task refusals with reasons
- **Risk badge**: "Healthy" / "Elevated" / "Critical" / "Overloaded" — color-coded

**Step 2:** Add "Send to Rest" button visible when workload > 80% or stress > 0.7.

**Step 3:** Add "Override: Force Assignment" button (admin only, requires confirmation, logged to governance_audit_log) — because overrides should be possible but visible and auditable.

**Step 4:** Commit.
```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): add IAAE welfare section to agent profile modal"
```

### Task 15: IAAE overview in Overview tab

Replace the fake IAAE HUD pod and empty Health Monitor card with real governance data.

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`

**Step 1:** Update IAAE HUD pod to show real compliance % from `/api/agents/welfare` → `fleet_health.compliance_pct`. Show "No data" if no governance events exist yet (honest, not fake 100%).

**Step 2:** Update IAAE Health Monitor briefing card to show:
- Fleet stress/energy averages with visual bars
- Agents at risk count (clickable — navigates to Crew tab)
- Agents on rest count
- Recent Vigil interventions (last 3 governance denials/escalations)
- Workload distribution mini-chart (10 agents, bar per agent showing % of daily cap)

**Step 3:** Add click handler on "agents at risk" to switch to Crew tab with those agents highlighted.

**Step 4:** Commit.
```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): wire IAAE overview to real welfare and governance data"
```

### Task 16: Crew tab welfare indicators

Add visual welfare indicators directly on each agent card in the Crew manifest, so you can see at a glance who's overworked.

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`

**Step 1:** On each agent card in the Crew tab, add:
- Thin workload bar at bottom of card (green→yellow→red based on workload_pct)
- Small stress indicator dot (green/yellow/red) next to agent name
- "Resting" badge if agent is in rest cycle
- Subtle glow effect if agent is at risk (stress > 0.7 or workload > 80%)

**Step 2:** Fetch workload + welfare data when Crew tab loads (parallel API calls).

**Step 3:** Sort agents with "at risk" agents first (visible, not hidden).

**Step 4:** Commit.
```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): add welfare indicators to crew tab agent cards"
```

### Task 17: Vigil enforcement visibility

Make Vigil's enforcement actions visible in the bridge — not hidden in database tables.

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`

**Step 1:** Create `GET /api/iaae/enforcement-log` endpoint:
```sql
SELECT gal.timestamp, gal.event_category, gal.details, gal.agent_id,
       a.name as agent_name, a.first_name, a.last_name
FROM governance_audit_log gal
LEFT JOIN agents a ON a.id = gal.agent_id
WHERE gal.timestamp >= NOW() - INTERVAL '7 days'
ORDER BY gal.timestamp DESC
LIMIT 50;
```

**Step 2:** Add "Vigil's Log" section to Overview tab — a mini-feed showing:
- Task blocked (agent overworked)
- Rest cycle initiated (automatic)
- Task reassigned (stress threshold)
- Ethical escalation (sent to human)
Each with timestamp, agent name, and reason.

**Step 3:** If log is empty (no enforcement events), show: "No interventions needed — all agents within healthy parameters" (positive framing, not "nothing to show").

**Step 4:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): add Vigil enforcement log to overview tab"
```

---

## Phase 6: Retire Team Management Module

### Task 18: Disable Team Management module

After all features are absorbed into Bridge Command, disable the standalone module.

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/module_registry.py`

**Step 1:** Set `enabled=False` on the team_management ModuleDefinition (line 468).

**Step 2:** Do NOT delete the routes.py file yet — keep for reference. Just disable the module from the dashboard.

**Step 3:** Verify Bridge Command Crew tab has all features working.

**Step 4:** Commit.
```bash
git add platform_v2/module_registry.py
git commit -m "refactor(modules): disable team management module (absorbed into bridge crew tab)"
```

---

## Phase 6: Clean Dead Endpoints

### Task 19: Remove dead/orphaned endpoints from bridge routes.py

Remove endpoints that read from empty/stale tables and serve no purpose.

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`

**Endpoints to remove or flag:**
- All `/api/training/*` endpoints (10+ routes) — fine-tuning never implemented, `ft_*` tables empty
- `/api/llm/check` — no implementation
- `/api/dispatch/stream` that reads from `agent_activity_events` (empty, no writers) — keep SSE pattern but wire to `task_execution_log`

**Endpoints to keep but rewire** (done in Phase 2):
- `/api/traffic` — already fixed in Task 2
- `/api/llm/status` — already fixed in Task 6
- `/api/bridge/models` — already fixed in Task 4

**Step 1:** Identify all dead endpoints by searching for queries against empty tables.

**Step 2:** Remove dead endpoint functions.

**Step 3:** Verify remaining endpoints work.

**Step 4:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "refactor(bridge): remove dead endpoints (fine-tuning, empty tables)"
```

---

## Phase 7: Network Tab Improvements

### Task 20: Add node management controls

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`

**Step 1:** Add "Remove Node" button to each node card.

**Step 2:** Add "Disable/Enable" toggle for bridge LLM models.

**Step 3:** Verify model toggle connects to the real bridge router (smart_router.py).

**Step 4:** Separate display: "Local Models" section above "Remote Node Models" section.

**Step 5:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): add node management controls to network tab"
```

---

## Phase 8: Visual Polish (Future)

### Task 21: Agent character visuals (design phase)

Explore pixel-art or caricature-style agent representations for station/crew views. Inspired by VoxYZ Agent World / Claw-Empire office visualization.

- Each agent gets a unique visual identity matching their personality
- Station view shows agents "at their desk"
- Clicking opens the rich profile modal (built in Task 8)

**This is a design task** — requires art direction decisions before implementation. Create mockups first.

---

## Execution Order

| Phase | Tasks | Dependencies | Impact |
|-------|-------|-------------|--------|
| 1: Sidebar cleanup | 1 | None | Low risk |
| 2: Wire real metrics | 2-6 | None | Medium — new SQL queries |
| 3: Fix dispatch | 7 | After Phase 2 | Low risk |
| 4: Absorb team mgmt | 8-11 | After Phase 2 | High — major feature move |
| 5: IAAE governance | 12-17 | After Phase 4 | **Core** — the ethical backbone |
| 6: Retire module | 18 | After Phase 4+5 complete | Medium — module disabled |
| 7: Dead code cleanup | 19 | After Phase 2 | Low risk |
| 8: Network controls | 20 | After Phase 2 | Medium |
| 9: Visual polish | 21 | After Phase 5 | Future — design first |

---

## Tables Reference

| Table | Status | Used By (Real) | Action |
|-------|--------|----------------|--------|
| `task_execution_log` | ACTIVE (134+/day) | AI Bridge dispatcher | Wire Overview metrics here |
| `agents` | ACTIVE (10 rows) | All modules | Keep, add CRUD to Bridge |
| `bridge_stations` | ACTIVE (10 rows) | Bridge stations tab | Keep |
| `station_assignments` | ACTIVE | Bridge + orchestration | Keep |
| `agent_emotional_state` | ACTIVE | IAAE, welfare checks | Wire to Overview IAAE card |
| `agent_skills` | ACTIVE | Team Management | Move to Bridge |
| `agent_memory` | ACTIVE | Team Management | Move to Bridge profile |
| `agent_budgets` | ACTIVE | IAAE limits | Wire to workload tracking (daily caps) |
| `agent_rest_cycles` | ACTIVE | IAAE welfare | Wire to profile + Overview welfare |
| `task_refusal_log` | ACTIVE | IAAE rights | Wire to profile + Vigil's log |
| `governance_audit_log` | ACTIVE | IAAE governance | Wire to compliance % + Vigil's log |
| `agent_identity` | ACTIVE | IAAE identity tracking | Wire to profile versioned attributes |
| `llm_connections` | STALE (Jan 19) | Nothing real | Replace with live Ollama query |
| `token_usage_log` | EMPTY | Nothing | Remove references |
| `agent_activity_events` | EMPTY | Nothing | Remove references |
| `ft_*` tables (5+) | EMPTY | Nothing | Remove endpoints |
| `node_models` | STALE | v_bridge_available_models | Replace with live Ollama |
| `orchestration_sessions` | EMPTY | Nothing | Future use |
