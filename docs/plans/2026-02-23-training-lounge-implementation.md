# Training & Lounge Upgrade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild Bridge Crew Training and Lounge sub-tabs into full crew management tools with time-based skill training, wellness monitoring, auto-recommendations, and node training readiness.

**Architecture:** New API endpoints in `routes.py` for training CRUD and wellness data. APScheduler job in `app.py` handles training progression and rest recovery every 5 minutes. Frontend rebuilt in `bridge.html` with rich cards, progress bars, and recommendation panels. Dispatcher already hard-blocks resting agents (line 442 of `bridge_dispatcher.py`).

**Tech Stack:** Flask/Python, PostgreSQL, APScheduler, vanilla JS (bridge.html), existing DB tables (`training_assignments`, `agent_rest_cycles`, `agent_emotional_state`, `agent_skills`)

---

## Context for the Implementer

**Key files:**
- `platform_v2/tools/bridge/routes.py` — ~7200 lines, Flask Blueprint `bridge_bp`, all Bridge API endpoints
- `platform_v2/templates/tools/bridge.html` — ~12400 lines, all Bridge frontend JS + HTML
- `ai_bridge/bridge_dispatcher.py` — ~1700 lines, agent scoring and dispatch
- `platform_v2/app.py` — ~3100 lines, Flask app init, APScheduler setup at line 2897

**Existing DB tables (all have data or are ready):**
- `training_assignments` — skill_name, skill_category, target_proficiency (1-5), current_proficiency, status, started_at, completed_at, notes, created_by
- `v_training_room_agents` — view joining training_assignments + agents + agent_emotional_state
- `agent_rest_cycles` — rest_type, reason, started_at, ended_at, workload_before, initiated_by
- `agent_emotional_state` — agent_id, current_mood, stress_level, energy_level, timestamp
- `agent_skills` — agent_id, skill_name, skill_category, proficiency_level (1-5)
- `agent_learning_records` — learning_type, subject, lesson_learned, confidence_before/after
- `task_execution_log` — agent_id, capability, success, duration_ms, created_at

**Existing endpoints that already work:**
- `POST /api/agents/<id>/send-to-lounge` — creates rest cycle, cancels active training
- `POST /api/agents/<id>/return-from-lounge` — ends rest cycle
- `GET /api/lounge` — lists agents currently resting

**Dispatcher already handles rest hard-block** at `bridge_dispatcher.py:442` — welfare cache loads `resting` flag from `agent_rest_cycles`.

**How crew sub-tabs work:** `switchCrewSubtab(name)` in bridge.html toggles `.active` class on `.crew-subpanel[data-subpanel=name]`. Currently only `contractors` and `leaderboard` trigger data loads. Training and lounge need load triggers added.

**DB connection pattern in routes.py:**
```python
with get_db_cursor() as (conn, cur):
    cur.execute("SELECT ...", (param,))
    rows = cur.fetchall()
    return jsonify({"success": True, "data": rows})
```

**Training time thresholds (hours per level-up):**
| Level-up | Hours |
|----------|-------|
| 1 to 2   | 1     |
| 2 to 3   | 2     |
| 3 to 4   | 4     |
| 4 to 5   | 8     |

**XSS note:** All innerHTML usage in bridge.html uses data from authenticated API endpoints only (login_required). Agent names and skill names are admin-controlled DB values, not user input. This matches the existing pattern throughout bridge.html (leaderboard, manifest, contractors all use innerHTML with API data).

---

### Task 1: DB Migration — Add node training support columns

**Files:**
- Create: `database/migrations/118_training_lounge_upgrade.sql`

**Step 1: Write the migration SQL**

```sql
-- Migration 118: Training & Lounge Upgrade
-- Adds node training support and ensures emotional state snapshot on rest

-- Add node training columns to training_assignments
ALTER TABLE training_assignments
ADD COLUMN IF NOT EXISTS source_node_id INTEGER,
ADD COLUMN IF NOT EXISTS source_node_name VARCHAR(200),
ADD COLUMN IF NOT EXISTS training_type VARCHAR(30) DEFAULT 'internal';
-- training_type: 'internal' (our agent), 'node_incoming' (external agent training here), 'node_outgoing' (our agent training elsewhere)

-- Add emotional state snapshot columns to rest cycles for delta tracking
ALTER TABLE agent_rest_cycles
ADD COLUMN IF NOT EXISTS stress_at_start NUMERIC(3,2),
ADD COLUMN IF NOT EXISTS energy_at_start NUMERIC(3,2),
ADD COLUMN IF NOT EXISTS stress_at_end NUMERIC(3,2),
ADD COLUMN IF NOT EXISTS energy_at_end NUMERIC(3,2);

COMMENT ON COLUMN training_assignments.source_node_id IS 'Node ID if training request came from external node';
COMMENT ON COLUMN training_assignments.training_type IS 'internal, node_incoming, or node_outgoing';
COMMENT ON COLUMN agent_rest_cycles.stress_at_start IS 'Stress level when rest began (for delta display)';
```

**Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/118_training_lounge_upgrade.sql
```

**Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "\d training_assignments" | grep source_node
docker exec archie_database psql -U archie -d archie -c "\d agent_rest_cycles" | grep stress_at
```

**Step 4: Commit**

```bash
git add database/migrations/118_training_lounge_upgrade.sql
git commit -m "feat(db): migration 118 — training node support and rest deltas"
```

---

### Task 2: Training API Endpoints

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py` (add after the existing lounge endpoints ~line 1710)

**Step 1: Add training CRUD endpoints**

Add these 5 endpoints to `routes.py` after the existing lounge section (around line 1710):

1. `GET /api/training/active` — uses `v_training_room_agents` view
2. `POST /api/training/assign` — validates agent/skill/target, creates `training_assignments` row
3. `POST /api/training/<id>/cancel` — sets status='cancelled'
4. `GET /api/training/history` — completed/cancelled trainings with agent names
5. `GET /api/training/recommendations` — queries `task_execution_log` for failures >= 3 in 7 days where `agent_skills.proficiency_level < 4`, filters out agents already in training

Key validation in assign endpoint:
- agent must exist and be active
- no duplicate active training on same skill
- target_proficiency must be 2-5 and exceed current level
- skill_category fetched from existing agent_skills row

**Step 2: Test all endpoints via curl**

**Step 3: Commit**

```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(bridge): training CRUD API endpoints"
```

---

### Task 3: Lounge Wellness API Endpoints

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py`

**Step 1: Add wellness and lounge history endpoints**

1. `GET /api/lounge/wellness` — queries all active agents + emotional state + task volume (48h), classifies as healthy/at_risk/resting, builds burnout_alerts array with reasons
2. `GET /api/lounge/history` — past rest cycles with stress deltas

Burnout thresholds:
- stress > 0.7
- energy < 0.3
- 50+ tasks in 48 hours

**Step 2: Update `send_agent_to_lounge` to capture stress/energy snapshot**

Add query for current emotional state before INSERT, include `stress_at_start` and `energy_at_start` in the INSERT.

**Step 3: Update `return_agent_from_lounge` to capture end snapshot**

Query emotional state before UPDATE, include `stress_at_end` and `energy_at_end`.

**Step 4: Update `GET /api/lounge` to include snapshot columns**

Add `arc.stress_at_start`, `arc.energy_at_start` to the existing SELECT.

**Step 5: Test all endpoints**

**Step 6: Commit**

```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(bridge): lounge wellness API with burnout alerts and rest deltas"
```

---

### Task 4: APScheduler Job — Training Progression & Rest Recovery

**Files:**
- Modify: `platform_v2/app.py` (add job inside `init_consciousness_scheduler`, ~line 2970)

**Step 1: Add `crew_wellness_tick` function**

Define before `init_consciousness_scheduler`. This function:

1. Queries active `training_assignments` with status='in_progress'
2. For each: calculates hours elapsed, checks against HOURS_PER_LEVEL threshold
3. On level-up: updates `training_assignments.current_proficiency`, updates `agent_skills.proficiency_level` (UPSERT), logs to `agent_learning_records`
4. When target reached: sets status='completed'
5. Queries active `agent_rest_cycles` (ended_at IS NULL)
6. For each: applies stress reduction (10%/hr) and energy recovery (15%/hr) to `agent_emotional_state`

HOURS_PER_LEVEL = {2: 1, 3: 2, 4: 4, 5: 8}

**Step 2: Register the scheduler job**

Add inside `init_consciousness_scheduler` after existing jobs:
- `IntervalTrigger(minutes=5)`, id="crew_wellness_tick"

**Step 3: Restart and verify no startup errors**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform
docker logs archie_platform 2>&1 | tail -20
```

**Step 4: Commit**

```bash
git add platform_v2/app.py
git commit -m "feat(bridge): APScheduler crew wellness tick — training progression and rest recovery"
```

---

### Task 5: Training Tab Frontend

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Step 1: Replace the Training sub-panel HTML** (~lines 5967-5988)

New structure:
1. **Skill Gap Alerts** card — `#training-recommendations` container
2. **Training Rooms** card — agent dropdown, skill dropdown (populated on agent select), target level select, "Assign Training" button, `#training-active-list` container showing active training cards with progress bars
3. **Training History** card — collapsed, expandable, shows completed/cancelled
4. **Node Training Requests** card — placeholder "Coming Soon" for future node integration

**Step 2: Add Training JS functions** (after existing lounge functions ~line 11874)

Functions:
- `loadTrainingTab()` — calls recommendations, active, and populates agent select
- `populateTrainingAgentSelect()` — fetches crew manifest, populates dropdown
- Change event listener on `#training-agent-select` — fetches agent profile, populates skill dropdown with current levels
- `assignTraining()` — POSTs to /api/training/assign
- `loadActiveTraining()` — fetches /api/training/active, renders cards with progress bars using HOURS_PER_LEVEL
- `cancelTraining(id)` — POSTs cancel
- `loadTrainingRecommendations()` — fetches /api/training/recommendations, renders alert cards with "Train" buttons
- `quickAssignTraining(agentId, skill, target)` — one-click assign from recommendation
- `toggleTrainingHistory()` / `loadTrainingHistory()` — expand/collapse history section

Progress bar calculation: `hoursElapsed / HOURS_PER_LEVEL[nextLevel] * 100`

**Step 3: Wire into `switchCrewSubtab`**

Add `if (name === 'training') loadTrainingTab();` after the contractors line.

**Step 4: Restart and verify in browser**

**Step 5: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): training tab UI — recommendations, skill picker, progress bars"
```

---

### Task 6: Lounge Tab Frontend

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Step 1: Replace the Lounge sub-panel HTML** (~lines 5990-6011)

New structure:
1. **Wellness Summary** — 3-column row: Healthy (green), At Risk (amber), Resting (purple) with counts
2. **Burnout Risk Alerts** card — `#burnout-alerts` container with stress/energy gauges and "Send to Rest" buttons
3. **Lounge / Rest** card — agent dropdown + reason text input + "Send to Rest" button, `#lounge-agents-list` showing active rest cards with duration, reason, and "Return to Duty"
4. **Rest History** card — collapsed, expandable, shows past cycles with stress deltas

**Step 2: Add Lounge JS functions**

Functions:
- `loadLoungeTab()` — calls wellness, lounge agents, populates agent select
- `populateLoungeAgentSelect()` — fetches crew manifest
- `loadWellnessSummary()` — fetches /api/lounge/wellness, updates summary counters and renders burnout alerts with stress/energy gauge bars
- `loadLoungeAgents()` — fetches /api/lounge, renders active rest cards
- Override `sendToLounge()` — includes reason from text input
- Update `sendToLoungeById()` and `returnFromLounge()` — also refresh lounge tab
- `toggleRestHistory()` / `loadRestHistory()` — expand/collapse history
- Remove old broken `sendToTraining()` function
- Remove old lounge rendering from `loadCrewManifest()`

**Step 3: Wire into `switchCrewSubtab`**

Add `if (name === 'lounge') loadLoungeTab();`

**Step 4: Restart and verify in browser**

**Step 5: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): lounge tab UI — wellness dashboard, burnout alerts, rest history"
```

---

### Task 7: Integration Test — Full Lifecycle

**Step 1: Test training lifecycle**
- Assign DataMind to train 'code' to level 3 via UI
- Verify progress bar appears
- Verify skill gap recommendations load
- Cancel training, verify it moves to history

**Step 2: Test rest lifecycle**
- Send Vigil to rest with reason via UI
- Verify wellness summary updates (resting count increases)
- Verify lounge shows Vigil with stress snapshot
- Return from rest, verify history shows cycle with deltas

**Step 3: Test dispatcher hard-block**
- Send an agent to rest
- Trigger a dispatch that would normally go to that agent
- Verify dispatch log shows agent was skipped (resting)

**Step 4: Final push**

```bash
git push origin main
```
