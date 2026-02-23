# Training & Lounge Upgrade Design

**Goal:** Transform the barebones Training and Lounge sub-tabs in Bridge Crew into fully functional crew management tools with real operational control, live data, and auto-recommendations.

**Architecture:** Time-based training progression with APScheduler, dispatcher hard-block for resting agents, simple rules-based recommendation engine. All backed by existing DB tables (`training_assignments`, `agent_rest_cycles`, `agent_emotional_state`, `agent_skills`).

**Tech Stack:** Flask endpoints, vanilla JS (bridge.html), APScheduler, PostgreSQL

---

## Decisions

- **Training model**: Time-based. Proficiency increases after set hours in training (exponential: 1h/2h/4h/8h per level).
- **Rest enforcement**: Hard block. Agents in lounge are skipped by dispatcher entirely (score = -1).
- **Automation**: Auto-recommend only. System flags agents needing rest or training, human makes final call.
- **Scope**: Full upgrade — both tabs + backend + dispatcher integration in one pass.

## Training Tab

### Recommendations Panel
- System scans `task_execution_log` for failed dispatches by capability in last 7 days
- Cross-references `agent_skills` — if failures >= 3 AND proficiency < 4, surfaces recommendation card
- Card shows: agent name, skill, failure count, current level, suggested target
- Actions: "Assign Training" (one-click) or "Dismiss"

### Assign Training Flow
- Pick agent from dropdown
- Second dropdown shows agent's current skills with proficiency levels (from `agent_skills`)
- Pick skill, set target proficiency (default: current + 1)
- Creates `training_assignments` row with status `in_progress`

### Active Training Cards
- Agent name, skill being trained, progress bar (time-based)
- Current → target level display
- Time elapsed / estimated completion
- Cancel button

### Training Time Thresholds

| Level-up | Hours Required |
|----------|---------------|
| 1 → 2   | 1             |
| 2 → 3   | 2             |
| 3 → 4   | 4             |
| 4 → 5   | 8             |

### Progress Engine
- APScheduler job `crew_wellness_tick` runs every 5 minutes
- Checks active training assignments, computes elapsed time
- When threshold met: increments `current_proficiency` on assignment, updates `agent_skills.proficiency_level`, logs to `agent_learning_records`
- When target reached: marks training `completed`

### Training History
- Collapsed section at bottom
- Shows completed/cancelled trainings with dates and outcome

## Lounge Tab

### Wellness Overview
- Compact row at top: "3 healthy / 1 at risk / 1 resting"
- Color-coded status indicators

### Burnout Risk Alerts
- Flags agents where: stress > 70% OR energy < 30% OR 50+ tasks in 48 hours
- Alert card: agent name, stress/energy gauges, task volume
- Actions: "Send to Rest" (one-click) or "Dismiss"

### Active Rest Cards
- Agent name, reason for rest, live duration timer
- Stress/energy at entry vs current (delta display)
- "Return to Duty" button with warning if stress still high (> 50%)

### Dispatcher Hard-Block
- `_score_agent()` checks `is_resting` flag (loaded with agent cache)
- If resting → return -1 (skip), log in dispatch triage

### Emotional State Recovery
- While resting: stress drops ~10% per hour, energy recovers ~15% per hour
- Updated by same `crew_wellness_tick` APScheduler job
- Floor: stress 0%, energy caps at 100%

### Rest History
- Collapsed section at bottom
- Past rest cycles: who, when, how long, reason, stress delta

## Backend

### New API Endpoints
- `POST /api/training/assign` — create training assignment
- `GET /api/training/active` — list active trainings (uses `v_training_room_agents` view)
- `GET /api/training/recommendations` — skill gap recommendations
- `POST /api/training/<id>/cancel` — cancel training
- `GET /api/training/history` — completed/cancelled history
- `GET /api/lounge/wellness` — crew wellness summary + burnout alerts
- `GET /api/lounge/history` — past rest cycles with deltas

### APScheduler Job
- `crew_wellness_tick` — every 5 minutes
- Handles both training progression and rest recovery in one job
- Lightweight queries, no heavy computation

### Dispatcher Integration
- Add `is_resting` boolean to `_load_agents_cache()`
- Early return in `_score_agent()` if resting
- Cache-friendly — no extra DB hit per dispatch

### Recommendation Logic (Simple Rules)
- **Training**: failures >= 3 in 7 days at a capability where proficiency < 4
- **Burnout**: stress > 0.7 OR energy < 0.3 OR 50+ tasks in 48 hours

## Existing DB Tables Used
- `training_assignments` — skill, target/current proficiency, status, timestamps
- `v_training_room_agents` — view joining training + agents + emotional state
- `agent_rest_cycles` — rest type, reason, started/ended, workload_before
- `agent_emotional_state` — mood, stress, energy per agent
- `agent_skills` — proficiency levels updated on training completion
- `agent_learning_records` — logs training completions
- `task_execution_log` — source for failure-based recommendations
