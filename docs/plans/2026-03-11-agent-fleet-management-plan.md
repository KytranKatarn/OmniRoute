# Agent Fleet Management System — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fleet rotation engine so ARCHIE agents automatically rotate when exhausted, idle agents volunteer for work, performance drives dispatch, and Bridge Command provides full visibility.

**Architecture:** Two new APScheduler jobs in agent_loop.py handle welfare recovery and idle volunteering. bridge_dispatcher.py gains shift lifecycle management (ACTIVE→WINDING_DOWN→COOLDOWN→OFF_DUTY) and performance-ranked scoring. Two new DB tables track rotation history and performance rankings. The Crew tab in Bridge Command gets fleet overview, rotation log, and enhanced agent cards with portraits.

**Tech Stack:** Python/Flask, PostgreSQL, APScheduler, Ollama API, ComfyUI/SDXL, LCARS CSS

**Spec:** `docs/plans/2026-03-11-agent-fleet-management.md`

**Existing code context:**
- `agent_loop.py` (~2650 lines) — 17 APScheduler jobs, `with_app_context()` wrapper pattern, `request_approval()` at line 134
- `bridge_dispatcher.py` (~4571 lines) — `_score_agent()` at line 758 (5-factor: skills 0.35, specialization 0.25, welfare 0.20, availability 0.15, budget 0.05), `_refresh_welfare_cache()` at line 578, `get_crew_manifest()` at line 4272
- `bridge.html` (~18000 lines) — Crew tab at line 8270, `renderCrewManifest()` at line 17583, `_renderAgentCard()` at line 17847
- `routes.py` (~7000 lines) — `/api/bridge/crew/manifest` at line 6941
- `agent_shifts` table EXISTS but is for scheduling (empty, different schema) — we create `agent_rotation_log` for lifecycle tracking
- `agent_performance_rankings` table does NOT exist
- 15 agents, 33 models in catalog, budget reset deadlock fix already committed (a33cc70)

---

## Chunk 1: Database Foundations + Welfare Recovery

### Task 1: Migration 147 — agent_rotation_log + agent_performance_rankings tables

**Files:**
- Create: `database/migrations/147_fleet_management_tables.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- Migration 147: Fleet Management — rotation log + performance rankings
-- Idempotent: safe to re-run

-- 1. Agent rotation log — tracks shift lifecycle transitions
CREATE TABLE IF NOT EXISTS agent_rotation_log (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    station_id INTEGER REFERENCES bridge_stations(id) ON DELETE SET NULL,
    shift_state VARCHAR(20) NOT NULL DEFAULT 'active',
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMP,
    tasks_completed INTEGER DEFAULT 0,
    tasks_failed INTEGER DEFAULT 0,
    replaced_by INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    reason VARCHAR(50),  -- budget_exhausted, welfare_critical, manual, scheduled
    metadata JSONB DEFAULT '{}',
    CONSTRAINT valid_shift_state CHECK (shift_state IN ('active', 'winding_down', 'cooldown', 'off_duty'))
);

CREATE INDEX IF NOT EXISTS idx_rotation_log_agent ON agent_rotation_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_rotation_log_active ON agent_rotation_log(agent_id, shift_state) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_rotation_log_station ON agent_rotation_log(station_id) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_rotation_log_recent ON agent_rotation_log(started_at DESC);

-- 2. Agent performance rankings — comparative scoring per capability
CREATE TABLE IF NOT EXISTS agent_performance_rankings (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    capability VARCHAR(50) NOT NULL,
    tasks_completed INTEGER DEFAULT 0,
    success_rate NUMERIC(5,4) DEFAULT 0.0,
    avg_duration_ms NUMERIC(12,2) DEFAULT 0.0,
    avg_tokens_used NUMERIC(12,2) DEFAULT 0.0,
    rank_score NUMERIC(5,4) DEFAULT 0.0,
    rank_position INTEGER DEFAULT 0,
    sample_size INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT NOW(),
    CONSTRAINT unique_agent_capability UNIQUE (agent_id, capability)
);

CREATE INDEX IF NOT EXISTS idx_perf_rank_capability ON agent_performance_rankings(capability, rank_score DESC);
CREATE INDEX IF NOT EXISTS idx_perf_rank_agent ON agent_performance_rankings(agent_id);

-- 3. Add shift_state column to agents table for quick lookups
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'agents' AND column_name = 'shift_state') THEN
        ALTER TABLE agents ADD COLUMN shift_state VARCHAR(20) DEFAULT 'active';
        ALTER TABLE agents ADD CONSTRAINT valid_agent_shift_state CHECK (shift_state IN ('active', 'winding_down', 'cooldown', 'off_duty'));
    END IF;
END $$;
```

- [ ] **Step 2: Run the migration**

```bash
docker cp database/migrations/147_fleet_management_tables.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/147_fleet_management_tables.sql
```

Expected: `CREATE TABLE`, `CREATE INDEX`, `DO` — no errors.

- [ ] **Step 3: Verify tables exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\d agent_rotation_log"
docker exec archie_database psql -U archie -d archie -c "\d agent_performance_rankings"
docker exec archie_database psql -U archie -d archie -c "SELECT column_name FROM information_schema.columns WHERE table_name='agents' AND column_name='shift_state'"
```

Expected: All three return schema info.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/147_fleet_management_tables.sql
git commit -m "feat(fleet): migration 147 — agent_rotation_log + agent_performance_rankings tables"
```

---

### Task 2: Welfare Recovery APScheduler Job (Section 1b)

**Files:**
- Modify: `ai_bridge/agent_loop.py`
  - Add job registration in `start()` (~line 379)
  - Add `_recover_idle_welfare()` method (new, after `_track_agent_hr()` ~line 2063)

- [ ] **Step 1: Add the welfare recovery method**

Add after `_track_agent_hr()` (around line 2063) in the AgentLoop class:

```python
def _recover_idle_welfare(self):
    """
    Recover welfare for idle and resting agents.
    Runs every 30 minutes.
    - Idle (not dispatched in last hour): stress -0.15, energy +0.2
    - Resting (active rest cycle): stress -0.3, energy +0.4
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if not self._is_enabled(cur, "hr_tracker_enabled"):
            cur.close()
            conn.close()
            return

        # Find agents with recent dispatches (last hour)
        cur.execute("""
            SELECT DISTINCT agent_name FROM task_execution_log
            WHERE created_at > NOW() - INTERVAL '1 hour'
        """)
        busy_names = {r["agent_name"] for r in cur.fetchall()}

        # Find resting agents
        cur.execute("""
            SELECT agent_id FROM agent_rest_cycles WHERE ended_at IS NULL
        """)
        resting_ids = {r["agent_id"] for r in cur.fetchall()}

        # Get all active agents with current welfare
        cur.execute("""
            SELECT DISTINCT ON (a.id)
                   a.id, a.name, es.stress_level, es.energy_level
            FROM agents a
            LEFT JOIN agent_emotional_state es ON a.id = es.agent_id
            WHERE a.status = 'active'
            ORDER BY a.id, es.timestamp DESC NULLS LAST
        """)
        agents = cur.fetchall()

        recovered = 0
        for agent in agents:
            aid = agent["id"]
            name = agent["name"]
            stress = float(agent["stress_level"] or 0.2)
            energy = float(agent["energy_level"] or 0.8)

            if aid in resting_ids:
                # Resting: faster recovery
                new_stress = max(0.0, stress - 0.3)
                new_energy = min(1.0, energy + 0.4)
            elif name not in busy_names:
                # Idle: moderate recovery
                new_stress = max(0.0, stress - 0.15)
                new_energy = min(1.0, energy + 0.2)
            else:
                continue  # Active agent, skip

            if new_stress == stress and new_energy == energy:
                continue  # No change needed

            cur.execute("""
                INSERT INTO agent_emotional_state
                (agent_id, stress_level, energy_level, current_mood, trigger_event, timestamp)
                VALUES (%s, %s, %s,
                        CASE WHEN %s < 0.3 THEN 'relaxed'
                             WHEN %s < 0.6 THEN 'neutral'
                             ELSE 'focused' END,
                        'welfare_recovery', NOW())
            """, (aid, new_stress, new_energy, new_stress, new_stress))
            recovered += 1

        conn.commit()
        if recovered > 0:
            logger.info(f"Welfare recovery: updated {recovered} agents")
            self._log_cycle("welfare_recovery", True, f"Recovered {recovered} agents")
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Welfare recovery error: {e}")
```

- [ ] **Step 2: Register the job in start()**

Add after the last job registration (around line 379, after `agent_proactive_scan`):

```python
self.scheduler.add_job(
    with_app_context(self._recover_idle_welfare),
    trigger=IntervalTrigger(minutes=30),
    id="agent_welfare_recovery",
    name="Agent Loop: Welfare Recovery",
    replace_existing=True,
)
```

- [ ] **Step 3: Verify in Docker**

```bash
docker compose restart archie_platform
sleep 5
docker logs archie_platform 2>&1 | grep -i "welfare recovery\|Agent Loop" | tail -5
```

Expected: Job registered without errors. May see "Welfare recovery: updated N agents" after 30min (or trigger manually via a test script).

- [ ] **Step 4: Manual verification — check an idle agent's welfare before/after**

```bash
docker exec archie_database psql -U archie -d archie -c "
  SELECT a.name, es.stress_level, es.energy_level, es.timestamp
  FROM agents a
  JOIN agent_emotional_state es ON a.id = es.agent_id
  WHERE a.name = 'Atom'
  ORDER BY es.timestamp DESC LIMIT 3
"
```

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(fleet): welfare recovery job — idle agents heal stress/energy every 30min"
```

---

### Task 3: Idle Volunteering APScheduler Job (Section 1c)

**Files:**
- Modify: `ai_bridge/agent_loop.py`
  - Add `_volunteer_idle_agents()` method (new, after `_recover_idle_welfare()`)
  - Add job registration in `start()`

**Dependencies:** Task 1 (migration), Task 2 (welfare recovery method exists)

- [ ] **Step 1: Add the idle volunteering method**

Add after `_recover_idle_welfare()`:

```python
def _volunteer_idle_agents(self):
    """
    Scan for idle agents and volunteer them at stations with pending work.
    Runs every 5 minutes.
    - Find agents: loaded in RAM, not busy, not resting, under budget
    - Find stations: have pending/failed bridge_jobs with no available primaries
    - Offer idle agent as auxiliary via existing cross-station dispatch path
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Find stations with recent failures and no idle primaries
        # NOTE: Use task_execution_log (verified columns) instead of bridge_jobs
        # to find stations that need help
        cur.execute("""
            SELECT tel.station_code, bs.id AS station_id,
                   COUNT(*) AS recent_failures
            FROM task_execution_log tel
            JOIN bridge_stations bs ON tel.station_code = bs.station_code
            WHERE tel.success = FALSE
              AND tel.created_at > NOW() - INTERVAL '30 minutes'
              AND bs.is_active = TRUE
            GROUP BY tel.station_code, bs.id
            ORDER BY recent_failures DESC
            LIMIT 5
        """)
        pending_jobs = cur.fetchall()

        if not pending_jobs:
            cur.close()
            conn.close()
            return

        # Find idle agents (not busy, not resting, active status)
        cur.execute("""
            SELECT a.id, a.name, a.model, sa.station_id,
                   bs.station_code AS home_station
            FROM agents a
            JOIN station_assignments sa ON a.id = sa.agent_id AND sa.is_active = TRUE
            JOIN bridge_stations bs ON sa.station_id = bs.id
            LEFT JOIN bridge_jobs bj ON bj.agent_name = a.name AND bj.status = 'running'
            LEFT JOIN agent_rest_cycles arc ON a.id = arc.agent_id AND arc.ended_at IS NULL
            WHERE a.status = 'active'
              AND bj.id IS NULL
              AND arc.id IS NULL
              AND a.shift_state IN ('active', 'winding_down')
        """)
        idle_agents = cur.fetchall()

        if not idle_agents:
            cur.close()
            conn.close()
            return

        volunteered = 0
        for job in pending_jobs:
            # Find an idle agent NOT from this station
            volunteer = None
            for agent in idle_agents:
                if agent["home_station"] != job["station_code"]:
                    volunteer = agent
                    break

            if volunteer:
                # Log the volunteering event
                logger.info(
                    f"Volunteering {volunteer['name']} from {volunteer['home_station']} "
                    f"to help {job['station_code']} ({job['recent_failures']} recent failures)"
                )
                self._create_notification(
                    f"Fleet: {volunteer['name']} volunteering at {job['station_code']}",
                    "info",
                    {"agent": volunteer["name"], "station": job["station_code"]},
                )
                volunteered += 1
                # Remove from idle list so they don't get double-assigned
                idle_agents = [a for a in idle_agents if a["id"] != volunteer["id"]]

        conn.commit()
        if volunteered > 0:
            logger.info(f"Idle volunteering: {volunteered} agents offered")
            self._log_cycle("idle_volunteering", True, f"{volunteered} agents volunteered")
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Idle volunteering error: {e}")
```

- [ ] **Step 2: Register the job in start()**

Add after the welfare recovery job:

```python
self.scheduler.add_job(
    with_app_context(self._volunteer_idle_agents),
    trigger=IntervalTrigger(minutes=5),
    id="agent_idle_volunteering",
    name="Agent Loop: Idle Volunteering",
    replace_existing=True,
)
```

- [ ] **Step 3: Verify in Docker**

```bash
docker compose restart archie_platform
sleep 5
docker logs archie_platform 2>&1 | grep -i "volunteering\|idle" | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(fleet): idle volunteering job — idle agents offer help at busy stations every 5min"
```

---

## Chunk 2: Shift Lifecycle Engine

### Task 4: Shift State Management in bridge_dispatcher.py (Section 2a-2b)

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py`
  - Add shift state constants (~line 150)
  - Add `_check_shift_transitions()` method (new)
  - Add `_find_replacement()` method (new)
  - Add `_transition_shift_state()` method (new)
  - Modify `_score_agent()` (~line 758) to apply winding_down penalty
  - Modify `_refresh_welfare_cache()` (~line 578) to include shift_state

**Dependencies:** Task 1 (migration for `agent_rotation_log` table and `agents.shift_state` column)

- [ ] **Step 1: Add shift state constants**

Add after `SELECTION_WEIGHTS` (around line 154):

```python
# Shift lifecycle states
SHIFT_STATES = ("active", "winding_down", "cooldown", "off_duty")

# Thresholds for automatic state transitions
WINDING_DOWN_BUDGET_PCT = 0.80   # 80% budget used -> winding down
WINDING_DOWN_STRESS = 0.70       # stress >= 0.7 -> winding down
COOLDOWN_BUDGET_PCT = 0.95       # 95% budget -> cooldown
COOLDOWN_STRESS = 0.85           # stress >= 0.85 -> cooldown
WINDING_DOWN_SCORE_PENALTY = 0.30  # 30% score penalty when winding down
```

- [ ] **Step 2: Add shift transition methods**

Add after `_get_dynamic_specialization()` (around line 756):

```python
def _check_shift_transitions(self, cur):
    """
    Check all active agents for shift state transitions.
    Called from _refresh_welfare_cache() with its existing cursor.
    """
    try:
        cur.execute("""
            SELECT a.id, a.name, a.shift_state, a.model,
                   ab.current_task_count, ab.task_queue_limit,
                   ab.tokens_used_today, ab.token_limit_per_day
            FROM agents a
            LEFT JOIN agent_budgets ab ON a.id = ab.agent_id
            WHERE a.status = 'active'
              AND a.shift_state IN ('active', 'winding_down')
        """)
        agents = cur.fetchall()

        for agent in agents:
            aid = agent["id"]
            name = agent["name"]
            current_state = agent["shift_state"] or "active"

            # Get welfare from cache
            welfare = self._welfare_cache.get(aid, {})
            stress = welfare.get("stress", 0.0)

            # Calculate budget usage percentage
            task_limit = agent["task_queue_limit"] or 10
            task_count = agent["current_task_count"] or 0
            token_limit = agent["token_limit_per_day"] or 100000
            tokens_used = agent["tokens_used_today"] or 0
            budget_pct = max(
                task_count / task_limit if task_limit > 0 else 0,
                tokens_used / token_limit if token_limit > 0 else 0,
            )

            # Determine target state
            if current_state == "active":
                if budget_pct >= COOLDOWN_BUDGET_PCT or stress >= COOLDOWN_STRESS:
                    self._transition_shift_state(cur, aid, name, "cooldown",
                        "budget_exhausted" if budget_pct >= COOLDOWN_BUDGET_PCT else "welfare_critical")
                elif budget_pct >= WINDING_DOWN_BUDGET_PCT or stress >= WINDING_DOWN_STRESS:
                    self._transition_shift_state(cur, aid, name, "winding_down",
                        "budget_high" if budget_pct >= WINDING_DOWN_BUDGET_PCT else "welfare_elevated")

            elif current_state == "winding_down":
                if budget_pct >= COOLDOWN_BUDGET_PCT or stress >= COOLDOWN_STRESS:
                    self._transition_shift_state(cur, aid, name, "cooldown",
                        "budget_exhausted" if budget_pct >= COOLDOWN_BUDGET_PCT else "welfare_critical")

        # No conn.commit()/close() — caller (_refresh_welfare_cache) owns the connection
    except Exception as e:
        logger.error(f"Shift transition check error: {e}")

def _transition_shift_state(self, cur, agent_id, agent_name, new_state, reason):
    """
    Transition an agent to a new shift state.
    Logs to agent_rotation_log and updates agents.shift_state.
    """
    # Get current station
    cur.execute("""
        SELECT bs.id AS station_id, bs.station_code
        FROM station_assignments sa
        JOIN bridge_stations bs ON sa.station_id = bs.id
        WHERE sa.agent_id = %s AND sa.is_active = TRUE
        LIMIT 1
    """, (agent_id,))
    station = cur.fetchone()
    station_id = station["station_id"] if station else None
    station_code = station["station_code"] if station else "UNKNOWN"

    # Close previous rotation log entry
    cur.execute("""
        UPDATE agent_rotation_log
        SET ended_at = NOW()
        WHERE agent_id = %s AND ended_at IS NULL
    """, (agent_id,))

    # Create new rotation log entry
    cur.execute("""
        INSERT INTO agent_rotation_log
        (agent_id, station_id, shift_state, reason, started_at)
        VALUES (%s, %s, %s, %s, NOW())
    """, (agent_id, station_id, new_state, reason))

    # Update agent's shift_state
    cur.execute("""
        UPDATE agents SET shift_state = %s WHERE id = %s
    """, (new_state, agent_id))

    logger.info(f"Shift transition: {agent_name} -> {new_state} at {station_code} ({reason})")

    # Send notification for rotation events (uses same cursor — no separate connection)
    try:
        from psycopg2 import Json
        cur.execute("""
            INSERT INTO system_notifications (title, message, type, metadata, created_at)
            VALUES (%s, %s, 'info', %s, NOW())
        """, (
            f"Fleet: {agent_name} -> {new_state}",
            f"{agent_name} transitioned to {new_state} at {station_code} ({reason})",
            Json({"agent": agent_name, "state": new_state, "station": station_code, "reason": reason}),
        ))
    except Exception:
        pass  # Don't block rotation on notification failure

    # If entering cooldown, trigger replacement search (but not recursively)
    if new_state == "cooldown":
        replacement = self._find_replacement(cur, agent_id, station_id, station_code)
        if replacement:
            cur.execute("""
                UPDATE agent_rotation_log
                SET replaced_by = %s
                WHERE id = (
                    SELECT id FROM agent_rotation_log
                    WHERE agent_id = %s AND ended_at IS NULL
                    ORDER BY started_at DESC LIMIT 1
                )
            """, (replacement["id"], agent_id))

def _find_replacement(self, cur, exhausted_agent_id, station_id, station_code):
    """
    Find a replacement agent when one enters COOLDOWN.
    Score: skill proficiency (40%), RAM fit (30%), time since last shift (20%), historical perf (10%).
    Returns agent dict or None.
    """
    if not station_id:
        return None

    # Get required capabilities for this station
    cur.execute("""
        SELECT DISTINCT capability FROM task_execution_log
        WHERE station_code = %s AND created_at > NOW() - INTERVAL '7 days'
    """, (station_code,))
    station_caps = [r["capability"] for r in cur.fetchall()]

    # Find candidate agents: active, not busy, not at this station, not in cooldown/off_duty
    cur.execute("""
        SELECT a.id, a.name, a.model, a.shift_state
        FROM agents a
        LEFT JOIN station_assignments sa ON a.id = sa.agent_id AND sa.is_active = TRUE
        LEFT JOIN bridge_jobs bj ON bj.agent_name = a.name AND bj.status = 'running'
        LEFT JOIN agent_rest_cycles arc ON a.id = arc.agent_id AND arc.ended_at IS NULL
        WHERE a.status = 'active'
          AND a.shift_state IN ('active', 'off_duty')
          AND a.id != %s
          AND bj.id IS NULL
          AND arc.id IS NULL
          AND (sa.station_id IS NULL OR sa.station_id != %s)
    """, (exhausted_agent_id, station_id))
    candidates = cur.fetchall()

    if not candidates:
        logger.info(f"No replacement candidates for station {station_code}")
        return None

    # Score candidates
    best_score = -1
    best_candidate = None

    for candidate in candidates:
        cid = candidate["id"]

        # Skill proficiency (40%)
        cur.execute("""
            SELECT AVG(proficiency_level) AS avg_prof
            FROM agent_skills
            WHERE agent_id = %s AND skill_name = ANY(%s)
        """, (cid, station_caps if station_caps else ["general"]))
        skill_row = cur.fetchone()
        skill_score = float(skill_row["avg_prof"] or 0) / 5.0

        # RAM fit (30%) — prefer already-loaded models
        ram_score = 0.3  # Default: not loaded
        # Check Ollama /api/ps for loaded models would be ideal,
        # but we use the welfare cache's loaded status
        for wid, wdata in self._welfare_cache.items():
            if wid == cid and wdata.get("loaded"):
                ram_score = 1.0
                break

        # Time since last shift (20%)
        cur.execute("""
            SELECT MAX(ended_at) AS last_ended
            FROM agent_rotation_log
            WHERE agent_id = %s AND shift_state IN ('cooldown', 'off_duty')
        """, (cid,))
        last_row = cur.fetchone()
        if last_row and last_row["last_ended"]:
            hours_rested = (datetime.now() - last_row["last_ended"]).total_seconds() / 3600
            rest_score = min(hours_rested / 8.0, 1.0)
        else:
            rest_score = 1.0  # Never rotated = fully rested

        # Historical performance (10%)
        cur.execute("""
            SELECT AVG(rank_score) AS avg_rank
            FROM agent_performance_rankings
            WHERE agent_id = %s
        """, (cid,))
        perf_row = cur.fetchone()
        perf_score = float(perf_row["avg_rank"] or 0.5)

        total = (0.40 * skill_score) + (0.30 * ram_score) + (0.20 * rest_score) + (0.10 * perf_score)

        if total > best_score:
            best_score = total
            best_candidate = candidate

    if best_candidate:
        logger.info(
            f"Replacement found: {best_candidate['name']} (score={best_score:.3f}) "
            f"for station {station_code}"
        )
        # Activate the replacement
        self._transition_shift_state(
            cur, best_candidate["id"], best_candidate["name"],
            "active", "replacement_activated"
        )

    return best_candidate
```

- [ ] **Step 3: Modify _score_agent() to apply winding_down penalty**

In `_score_agent()` (around line 858-864), find the existing composite calculation and replace with shift-aware version:

Find:
```python
composite = (
    0.35 * skills_score
    + 0.25 * specialization_score
    + 0.20 * welfare_score
    + 0.15 * availability_score
    + 0.05 * budget_score
)
return (round(composite, 4), None)
```

Replace with:
```python
composite = (
    0.35 * skills_score
    + 0.25 * specialization_score
    + 0.20 * welfare_score
    + 0.15 * availability_score
    + 0.05 * budget_score
)

# Apply shift state modifiers
shift_state = agent_info.get("shift_state", "active")
if shift_state == "winding_down":
    composite *= (1.0 - WINDING_DOWN_SCORE_PENALTY)
elif shift_state == "cooldown":
    return (0.0, f"{agent_name} is in cooldown (finishing current job only)")
elif shift_state == "off_duty":
    return (0.0, f"{agent_name} is off duty (resting)")

return (round(composite, 4), None)
```

- [ ] **Step 4: Modify _refresh_welfare_cache() to include shift_state and trigger transitions**

In `_refresh_welfare_cache()` (around line 690, after building the welfare cache dict), add:

```python
# Include shift_state in cache
cur.execute("SELECT id, shift_state FROM agents WHERE status = 'active'")
for r in cur.fetchall():
    if r["id"] in self._welfare_cache:
        self._welfare_cache[r["id"]]["shift_state"] = r["shift_state"] or "active"
```

At the end of the method (before `cur.close()`), add:
```python
# Check for shift state transitions (pass existing cursor, no new connection)
self._check_shift_transitions(cur)
```

- [ ] **Step 5: Modify _refresh_agent_cache() to include shift_state**

In `_refresh_agent_cache()` (around line 254), add `a.shift_state` to the SELECT query. In the loop building `self._agent_cache`, add:
```python
"shift_state": row["shift_state"] or "active",
```

- [ ] **Step 6: Verify shift transitions work**

```bash
docker compose restart archie_platform
docker exec archie_database psql -U archie -d archie -c "
  SELECT a.name, a.shift_state FROM agents a WHERE a.status = 'active' ORDER BY a.name
"
```

- [ ] **Step 7: Commit**

```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat(fleet): shift lifecycle engine — graduated handoff with automatic state transitions"
```

---

## Chunk 3: Performance Rankings + Dispatch Integration

### Task 5: Performance Ranking Calculation (Section 3a-3b)

**Files:**
- Modify: `ai_bridge/agent_loop.py`
  - Add `_update_performance_rankings()` method (new)
  - Add job registration in `start()`

**Dependencies:** Task 1 (migration)

- [ ] **Step 1: Add the performance ranking method**

Add after `_volunteer_idle_agents()` in agent_loop.py:

```python
def _update_performance_rankings(self):
    """
    Calculate comparative performance rankings per capability.
    Runs every 15 minutes.
    rank_score = (success_rate * 0.5) + (speed_score * 0.3) + (efficiency_score * 0.2)
    Minimum 10 tasks for reliable ranking.
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get per-agent-per-capability stats from task_execution_log (last 30 days)
        cur.execute("""
            SELECT agent_id, capability,
                   COUNT(*) AS tasks_completed,
                   AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) AS success_rate,
                   AVG(duration_ms) AS avg_duration_ms,
                   AVG(tokens_used) AS avg_tokens_used
            FROM task_execution_log
            WHERE created_at > NOW() - INTERVAL '30 days'
              AND agent_id IS NOT NULL
              AND capability IS NOT NULL
            GROUP BY agent_id, capability
        """)
        stats = cur.fetchall()

        if not stats:
            cur.close()
            conn.close()
            return

        # Group by capability for comparative scoring
        by_capability = {}
        for row in stats:
            cap = row["capability"]
            if cap not in by_capability:
                by_capability[cap] = []
            by_capability[cap].append(row)

        updated = 0
        for capability, agents in by_capability.items():
            # Find worst-case for normalization
            max_duration = max(float(a["avg_duration_ms"] or 1) for a in agents)
            max_tokens = max(float(a["avg_tokens_used"] or 1) for a in agents)

            # Calculate rank scores
            scored = []
            for agent in agents:
                sr = float(agent["success_rate"] or 0)
                duration = float(agent["avg_duration_ms"] or 0)
                tokens = float(agent["avg_tokens_used"] or 0)
                sample = int(agent["tasks_completed"] or 0)

                speed_score = 1.0 - (duration / max_duration) if max_duration > 0 else 0.5
                efficiency_score = 1.0 - (tokens / max_tokens) if max_tokens > 0 else 0.5

                rank_score = (sr * 0.5) + (speed_score * 0.3) + (efficiency_score * 0.2)

                # Blend with static proficiency if sample too small
                if sample < 10:
                    cur.execute("""
                        SELECT proficiency_level FROM agent_skills
                        WHERE agent_id = %s AND skill_name = %s
                    """, (agent["agent_id"], capability))
                    skill_row = cur.fetchone()
                    static_prof = float(skill_row["proficiency_level"] or 3) / 5.0 if skill_row else 0.5
                    rank_score = (static_prof * 0.7) + (rank_score * 0.3)

                scored.append({
                    **agent,
                    "rank_score": round(rank_score, 4),
                })

            # Sort by rank_score descending and assign positions
            scored.sort(key=lambda x: x["rank_score"], reverse=True)
            for position, agent in enumerate(scored, 1):
                cur.execute("""
                    INSERT INTO agent_performance_rankings
                    (agent_id, capability, tasks_completed, success_rate,
                     avg_duration_ms, avg_tokens_used, rank_score, rank_position,
                     sample_size, last_updated)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (agent_id, capability)
                    DO UPDATE SET
                        tasks_completed = EXCLUDED.tasks_completed,
                        success_rate = EXCLUDED.success_rate,
                        avg_duration_ms = EXCLUDED.avg_duration_ms,
                        avg_tokens_used = EXCLUDED.avg_tokens_used,
                        rank_score = EXCLUDED.rank_score,
                        rank_position = EXCLUDED.rank_position,
                        sample_size = EXCLUDED.sample_size,
                        last_updated = NOW()
                """, (
                    agent["agent_id"], capability,
                    agent["tasks_completed"], agent["success_rate"],
                    agent["avg_duration_ms"], agent["avg_tokens_used"],
                    agent["rank_score"], position,
                    agent["tasks_completed"],
                ))
                updated += 1

        conn.commit()
        if updated > 0:
            logger.info(f"Performance rankings: updated {updated} entries across {len(by_capability)} capabilities")
            self._log_cycle("performance_rankings", True, f"Updated {updated} entries")
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Performance ranking error: {e}")
```

- [ ] **Step 2: Register the job in start()**

```python
self.scheduler.add_job(
    with_app_context(self._update_performance_rankings),
    trigger=IntervalTrigger(minutes=15),
    id="agent_performance_rankings",
    name="Agent Loop: Performance Rankings",
    replace_existing=True,
)
```

- [ ] **Step 3: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(fleet): performance ranking job — comparative scoring every 15min"
```

---

### Task 6: Dispatch Integration — Rank-Based Scoring (Section 3c)

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py`
  - Modify `_score_agent()` (~line 823) to use performance ranking instead of static specialization
  - Modify `_refresh_welfare_cache()` to load performance rankings

- [ ] **Step 1: Load performance rankings into welfare cache**

In `_refresh_welfare_cache()`, after the shift_state loading block added in Task 4, add:

```python
# Load performance rankings into cache for dispatch scoring
cur.execute("""
    SELECT agent_id, capability, rank_score, rank_position, sample_size
    FROM agent_performance_rankings
""")
perf_map = {}
for r in cur.fetchall():
    aid = r["agent_id"]
    if aid not in perf_map:
        perf_map[aid] = {}
    perf_map[aid][r["capability"]] = {
        "rank_score": float(r["rank_score"]),
        "rank_position": r["rank_position"],
        "sample_size": r["sample_size"],
    }
for aid in self._welfare_cache:
    self._welfare_cache[aid]["perf_rankings"] = perf_map.get(aid, {})
```

- [ ] **Step 2: Replace specialization scoring with performance ranking**

In `_score_agent()` (around lines 823-829), replace the specialization score section with:

```python
# Specialization score: prefer performance ranking over static mapping
spec_score = 0.0
agent_id = agent_info.get("id")
if agent_id:
    # Try performance ranking first (data-driven)
    perf_welfare = self._welfare_cache.get(agent_id, {})
    rank_data = perf_welfare.get("perf_rankings", {}).get(capability)
    if rank_data and rank_data.get("sample_size", 0) >= 10:
        spec_score = rank_data["rank_score"]
    else:
        # Fall back to dynamic benchmark winner
        dyn_winner = self._get_dynamic_specialization(station_code, capability)
        if dyn_winner and dyn_winner == agent_name:
            spec_score = 1.0
        else:
            # Fall back to static specialization map
            station_specs = AGENT_SPECIALIZATION.get(station_code, {})
            default_specs = AGENT_SPECIALIZATION.get("default", {})
            preferred = station_specs.get(capability) or default_specs.get(capability)
            spec_score = 1.0 if preferred == agent_name else 0.0
```

- [ ] **Step 3: Verify dispatch uses rankings**

```bash
docker compose restart archie_platform
docker logs archie_platform 2>&1 | grep -i "score\|ranking\|specialization" | tail -10
```

- [ ] **Step 4: Commit**

```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat(fleet): dispatch integration — performance rankings replace static specialization scores"
```

---

## Chunk 4: Roster Expansion + ComfyUI Portraits

### Task 7: Expand model_catalog to 50 + Generate Reserve Agent Profiles (Section 4a)

**Files:**
- Create: `database/migrations/148_roster_expansion.sql`

- [ ] **Step 1: Check current catalog count**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT model_name, family, parameter_size, category FROM model_catalog ORDER BY family, model_name"
```

- [ ] **Step 2: Write migration to expand catalog + create reserve agents**

```sql
-- Migration 148: Roster Expansion — 50 models + reserve agent profiles
-- Adds ~17 new models to reach 50 total, creates unassigned reserve agents

-- New models (fill gaps in catalog to reach ~50)
INSERT INTO model_catalog (model_name, display_name, family, parameter_size, size_gb, tier, category, description, use_cases, recommended_for, is_active)
VALUES
    ('llama3.1:8b', 'Llama 3.1 8B', 'llama', '8b', 4.7, 'medium', 'general', 'Meta latest general-purpose model', 'General tasks, reasoning, conversation', 'Versatile station support', true),
    ('llama3.2:1b', 'Llama 3.2 1B', 'llama', '1b', 0.7, 'small', 'general', 'Ultra-lightweight Llama', 'Simple tasks, classification', 'Low-resource agents', true),
    ('codellama:7b', 'Code Llama 7B', 'llama', '7b', 3.8, 'medium', 'coding', 'Meta code-specialized model', 'Code generation, debugging', 'Engineering station', true),
    ('codellama:13b', 'Code Llama 13B', 'llama', '13b', 7.4, 'large', 'coding', 'Larger code specialist', 'Complex code tasks', 'Senior engineering', true),
    ('starcoder2:7b', 'StarCoder 2 7B', 'starcoder', '7b', 4.0, 'medium', 'coding', 'BigCode code generation', 'Code completion, generation', 'Engineering support', true),
    ('yi:6b', 'Yi 6B', 'yi', '6b', 3.5, 'medium', 'general', '01.AI bilingual model', 'Chinese/English tasks', 'Diplomatic station', true),
    ('neural-chat:7b', 'Neural Chat 7B', 'neural-chat', '7b', 4.1, 'medium', 'general', 'Intel fine-tuned chat model', 'Conversation, support', 'Communications', true),
    ('stablelm2:1.6b', 'StableLM 2 1.6B', 'stablelm', '1.6b', 1.0, 'small', 'general', 'Stability AI compact model', 'Quick responses', 'Lightweight tasks', true),
    ('tinyllama:1.1b', 'TinyLlama 1.1B', 'tinyllama', '1.1b', 0.6, 'small', 'general', 'Compact Llama variant', 'Fast inference', 'Reserve agents', true),
    ('orca-mini:3b', 'Orca Mini 3B', 'orca', '3b', 1.9, 'small', 'reasoning', 'Microsoft Orca reasoning', 'Logical tasks', 'Analytics support', true),
    ('wizard-vicuna:13b', 'Wizard Vicuna 13B', 'wizard', '13b', 7.4, 'large', 'general', 'WizardLM + Vicuna merge', 'Complex instructions', 'Research station', true),
    ('nous-hermes2:10.7b', 'Nous Hermes 2 10.7B', 'nous', '10.7b', 6.1, 'large', 'general', 'Nous Research fine-tune', 'Instruction following', 'Operations support', true),
    ('solar:10.7b', 'Solar 10.7B', 'solar', '10.7b', 6.1, 'large', 'general', 'Upstage Solar model', 'Korean/English, reasoning', 'Diplomatic support', true),
    ('dolphin-phi:2.7b', 'Dolphin Phi 2.7B', 'dolphin', '2.7b', 1.6, 'small', 'general', 'Cognitive Computations uncensored', 'Creative tasks', 'Creative reserve', true),
    ('magicoder:7b', 'MagiCoder 7B', 'magicoder', '7b', 3.8, 'medium', 'coding', 'OSS-Instruct code model', 'Code generation', 'Engineering reserve', true),
    ('samantha-mistral:7b', 'Samantha Mistral 7B', 'samantha', '7b', 4.1, 'medium', 'general', 'Empathetic assistant', 'User-facing conversation', 'Communications reserve', true),
    ('meditron:7b', 'Meditron 7B', 'meditron', '7b', 3.8, 'medium', 'reasoning', 'Medical domain model', 'Specialized analysis', 'Research reserve', true)
ON CONFLICT (model_name) DO NOTHING;

-- Reserve agent profiles (unassigned, status='inactive' until formally onboarded)
-- Names reflect global diversity matching existing team
INSERT INTO agents (name, display_name, first_name, last_name, title, status, model, tier, worker_type, cost_tier, temperature, max_tokens, system_prompt, communication_style)
VALUES
    ('Atlas', 'Atlas Chen', 'Wei', 'Chen', 'Systems Analyst', 'inactive', 'llama3.1:8b', 2, 'internal', 'free', 0.5, 4096, 'You are Atlas, a systems analyst specializing in data architecture and optimization.', 'technical'),
    ('Cipher', 'Cipher Okafor', 'Chidi', 'Okafor', 'Security Specialist', 'inactive', 'codellama:7b', 2, 'internal', 'free', 0.3, 4096, 'You are Cipher, a security specialist focused on vulnerability analysis and secure coding.', 'technical'),
    ('Delphi', 'Delphi Papadopoulos', 'Elena', 'Papadopoulos', 'Research Analyst', 'inactive', 'yi:6b', 2, 'internal', 'free', 0.6, 4096, 'You are Delphi, a research analyst with expertise in data synthesis and pattern recognition.', 'professional'),
    ('Echo', 'Echo Nakamura', 'Yuki', 'Nakamura', 'Communications Lead', 'inactive', 'neural-chat:7b', 2, 'internal', 'free', 0.7, 4096, 'You are Echo, a communications specialist skilled in multilingual engagement.', 'friendly'),
    ('Forge', 'Forge Kowalski', 'Marek', 'Kowalski', 'Build Engineer', 'inactive', 'starcoder2:7b', 2, 'internal', 'free', 0.3, 4096, 'You are Forge, a build engineer focused on CI/CD pipelines and automation.', 'technical'),
    ('Helix', 'Helix Krishnan', 'Priya', 'Krishnan', 'Data Scientist', 'inactive', 'orca-mini:3b', 1, 'internal', 'free', 0.5, 4096, 'You are Helix, a data scientist specializing in statistical analysis and ML.', 'technical'),
    ('Iris', 'Iris Johansson', 'Linnea', 'Johansson', 'UX Designer', 'inactive', 'dolphin-phi:2.7b', 1, 'internal', 'free', 0.8, 4096, 'You are Iris, a UX designer focused on accessible and intuitive interfaces.', 'casual'),
    ('Juno', 'Juno Mbeki', 'Thandi', 'Mbeki', 'Operations Manager', 'inactive', 'nous-hermes2:10.7b', 3, 'internal', 'free', 0.5, 4096, 'You are Juno, an operations manager skilled in resource coordination.', 'professional'),
    ('Koda', 'Koda Begay', 'Koda', 'Begay', 'Logistics Coordinator', 'inactive', 'stablelm2:1.6b', 1, 'internal', 'free', 0.5, 4096, 'You are Koda, a logistics coordinator managing supply chains and workflows.', 'professional'),
    ('Luna', 'Luna Al-Rashid', 'Fatima', 'Al-Rashid', 'Diplomatic Advisor', 'inactive', 'solar:10.7b', 3, 'internal', 'free', 0.6, 4096, 'You are Luna, a diplomatic advisor specializing in cross-cultural communication.', 'formal'),
    ('Maven', 'Maven Dubois', 'Camille', 'Dubois', 'Knowledge Curator', 'inactive', 'samantha-mistral:7b', 2, 'internal', 'free', 0.6, 4096, 'You are Maven, a knowledge curator organizing and synthesizing information.', 'professional'),
    ('Nova', 'Nova Fernandez', 'Isabella', 'Fernandez', 'Creative Director', 'inactive', 'wizard-vicuna:13b', 3, 'internal', 'free', 0.8, 4096, 'You are Nova, a creative director with a flair for visual storytelling.', 'casual'),
    ('Onyx', 'Onyx Kim', 'Seo-Jun', 'Kim', 'Code Reviewer', 'inactive', 'magicoder:7b', 2, 'internal', 'free', 0.3, 4096, 'You are Onyx, a code reviewer focused on quality, performance, and best practices.', 'technical'),
    ('Pulse', 'Pulse Ivanovich', 'Alexei', 'Ivanovich', 'Monitor Specialist', 'inactive', 'llama3.2:1b', 1, 'internal', 'free', 0.4, 4096, 'You are Pulse, a monitoring specialist tracking system health and anomalies.', 'technical'),
    ('Quill', 'Quill Okonjo', 'Adaeze', 'Okonjo', 'Technical Writer', 'inactive', 'tinyllama:1.1b', 1, 'internal', 'free', 0.6, 4096, 'You are Quill, a technical writer producing clear documentation.', 'professional'),
    ('Rune', 'Rune Andersson', 'Erik', 'Andersson', 'Analytics Engineer', 'inactive', 'meditron:7b', 2, 'internal', 'free', 0.5, 4096, 'You are Rune, an analytics engineer building data pipelines.', 'technical'),
    ('Sage', 'Sage Takahashi', 'Haruto', 'Takahashi', 'AI Researcher', 'inactive', 'codellama:13b', 3, 'internal', 'free', 0.5, 4096, 'You are Sage, an AI researcher exploring model capabilities and training.', 'technical'),
    ('Thorn', 'Thorn McAllister', 'Rowan', 'McAllister', 'Penetration Tester', 'inactive', 'llama3.1:8b', 2, 'internal', 'free', 0.3, 4096, 'You are Thorn, a penetration tester identifying system vulnerabilities.', 'technical')
ON CONFLICT (name) DO NOTHING;

-- Create default budgets for new agents
INSERT INTO agent_budgets (agent_id, token_limit_per_day, tokens_used_today, task_queue_limit, current_task_count, token_reset_at)
SELECT id, 100000, 0, 10, 0, NOW() + INTERVAL '24 hours'
FROM agents
WHERE name IN ('Atlas', 'Cipher', 'Delphi', 'Echo', 'Forge', 'Helix', 'Iris', 'Juno', 'Koda', 'Luna', 'Maven', 'Nova', 'Onyx', 'Pulse', 'Quill', 'Rune', 'Sage', 'Thorn')
ON CONFLICT (agent_id) DO NOTHING;

-- Create default emotional state for new agents
INSERT INTO agent_emotional_state (agent_id, stress_level, energy_level, current_mood, timestamp)
SELECT id, 0.1, 0.9, 'neutral', NOW()
FROM agents
WHERE name IN ('Atlas', 'Cipher', 'Delphi', 'Echo', 'Forge', 'Helix', 'Iris', 'Juno', 'Koda', 'Luna', 'Maven', 'Nova', 'Onyx', 'Pulse', 'Quill', 'Rune', 'Sage', 'Thorn')
AND id NOT IN (SELECT DISTINCT agent_id FROM agent_emotional_state);
```

- [ ] **Step 3: Run migration**

```bash
docker cp database/migrations/148_roster_expansion.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/148_roster_expansion.sql
```

- [ ] **Step 4: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT count(*) FROM model_catalog"
docker exec archie_database psql -U archie -d archie -c "SELECT count(*) FROM agents"
docker exec archie_database psql -U archie -d archie -c "SELECT name, display_name, status, model FROM agents WHERE status = 'inactive' ORDER BY name"
```

Expected: ~50 models in catalog, ~33 agents total (15 active + 18 reserve).

- [ ] **Step 5: Commit**

```bash
git add database/migrations/148_roster_expansion.sql
git commit -m "feat(fleet): migration 148 — expand to 50 models + 18 reserve agents with diverse profiles"
```

---

### Task 8: ComfyUI Portrait Generation Pipeline (Section 4b-4c)

**Files:**
- Create: `ai_bridge/portrait_generator.py` — ComfyUI portrait generation + multi-crop
- Create: `scripts/generate_agent_portraits.py` — Batch runner

**Dependencies:** Task 7 (reserve agents exist in DB)

- [ ] **Step 1: Create the portrait generator module**

Create `ai_bridge/portrait_generator.py` with:
- `COMFYUI_HOST` config (default `http://192.168.1.200:8188`)
- `OUTPUT_DIR` = `platform_v2/static/img/agents/`
- `PROMPT_TEMPLATE` for photorealistic headshots
- `AGENT_DIVERSITY` dict mapping agent names to ethnicity/age for diverse portraits
- `generate_portrait(agent_name, display_name, force=False)` — submits SDXL workflow to ComfyUI, polls for completion, downloads result
- `_generate_crops(agent_name, portrait_path)` — uses Pillow to resize to 128x128 avatar and 32x32 icon
- `generate_all_portraits(force=False)` — batch generates for all agents in DB

Storage pattern: `static/img/agents/{agent_name}.png`, `{agent_name}_avatar.png`, `{agent_name}_icon.png`

Requires `Pillow` pip package for image resizing.

- [ ] **Step 2: Create the batch runner script**

Create `scripts/generate_agent_portraits.py`:
```python
#!/usr/bin/env python3
"""Generate agent portraits — run from host or inside Docker."""
import sys
sys.path.insert(0, "/mnt/archie_brain")
from ai_bridge.portrait_generator import generate_all_portraits

if __name__ == "__main__":
    force = "--force" in sys.argv
    results = generate_all_portraits(force=force)
    print(f"Success: {len(results['success'])} | Failed: {len(results['failed'])} | Skipped: {len(results['skipped'])}")
    if results["failed"]:
        print(f"Failed agents: {', '.join(results['failed'])}")
```

- [ ] **Step 3: Create output directory**

```bash
mkdir -p platform_v2/static/img/agents
touch platform_v2/static/img/agents/.gitkeep
```

- [ ] **Step 4: Commit**

```bash
git add ai_bridge/portrait_generator.py scripts/generate_agent_portraits.py platform_v2/static/img/agents/.gitkeep
git commit -m "feat(fleet): ComfyUI portrait generator — SDXL portraits with 3-size crops for all agents"
```

Note: Actual portrait generation is a long-running batch job. Run `scripts/generate_agent_portraits.py` when ComfyUI is ready. Requires `Pillow` pip package.

---

### Task 9: Agent Profile Modal Overhaul (Section 4d)

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py` — add profile API endpoint
- Modify: `platform_v2/templates/tools/bridge.html` — profile modal with portrait, rankings, shift history, welfare

**Dependencies:** Task 1 (agent_rotation_log), Task 5 (performance_rankings), Task 8 (portraits)

- [ ] **Step 1: Add profile endpoint to routes.py**

Add a new endpoint in `platform_v2/tools/bridge/routes.py`:

```python
@bridge_bp.route("/api/bridge/agent/<int:agent_id>/profile")
@admin_required
def get_agent_profile(agent_id):
    """Enhanced agent profile with shift history, performance rankings, portrait."""
    try:
        with get_db_cursor() as (conn, cur):
            # Agent details
            cur.execute("""
                SELECT a.*, bs.station_code
                FROM agents a
                LEFT JOIN station_assignments sa ON a.id = sa.agent_id AND sa.is_active = TRUE
                LEFT JOIN bridge_stations bs ON sa.station_id = bs.id
                WHERE a.id = %s
            """, (agent_id,))
            agent = cur.fetchone()
            if not agent:
                return jsonify({"success": False, "error": "Agent not found"}), 404

            # Performance rankings (top 5 capabilities)
            cur.execute("""
                SELECT capability, rank_score, rank_position, tasks_completed, success_rate, sample_size
                FROM agent_performance_rankings
                WHERE agent_id = %s
                ORDER BY rank_score DESC LIMIT 5
            """, (agent_id,))
            rankings = [dict(r) for r in cur.fetchall()]

            # Recent shift history (last 10)
            cur.execute("""
                SELECT rl.shift_state, rl.started_at, rl.ended_at,
                       rl.tasks_completed, rl.tasks_failed, rl.reason,
                       bs.station_code,
                       ra.name AS replaced_by_name
                FROM agent_rotation_log rl
                LEFT JOIN bridge_stations bs ON rl.station_id = bs.id
                LEFT JOIN agents ra ON rl.replaced_by = ra.id
                WHERE rl.agent_id = %s
                ORDER BY rl.started_at DESC LIMIT 10
            """, (agent_id,))
            shift_history = [dict(r) for r in cur.fetchall()]

            # Welfare history (last 24h)
            cur.execute("""
                SELECT stress_level, energy_level, current_mood, timestamp
                FROM agent_emotional_state
                WHERE agent_id = %s AND timestamp > NOW() - INTERVAL '24 hours'
                ORDER BY timestamp DESC LIMIT 20
            """, (agent_id,))
            welfare_history = [dict(r) for r in cur.fetchall()]

            # Portrait paths
            agent_name = agent["name"]
            portrait_base = f"/static/img/agents/{agent_name}"
            portraits = {
                "portrait": f"{portrait_base}.png",
                "avatar": f"{portrait_base}_avatar.png",
                "icon": f"{portrait_base}_icon.png",
            }

            return jsonify({
                "success": True,
                "agent": dict(agent),
                "rankings": rankings,
                "shift_history": shift_history,
                "welfare_history": welfare_history,
                "portraits": portraits,
            })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 2: Add profile modal HTML/CSS/JS to bridge.html**

Add modal HTML after the crew panel (around line 8293). Use safe DOM methods (createElement, textContent) instead of innerHTML for all dynamic content. The existing `escHtml()` function is available for any HTML that must be set.

Modal contents:
- Portrait (large, 512x512, or initial-letter fallback circle)
- Name, station, model, tier
- Shift state badge (green=active, amber=winding_down, red=cooldown, grey=off_duty)
- Performance rankings (top 3 capabilities with rank position)
- Recent shift history (table with state, duration, tasks, reason)
- Welfare gauges (stress bar red to green, energy bar green to red)

CSS classes: `crew-profile-modal`, `crew-profile-overlay`, `crew-profile-portrait`, `crew-profile-rankings`, `crew-profile-shifts`, `crew-profile-welfare`

- [ ] **Step 3: Wire agent card clicks to profile modal**

In `_renderAgentCard()` (around line 17847), add `onclick="showAgentProfile(${agent.agent_id})"` to the card element.

- [ ] **Step 4: Verify in browser**

Open Bridge Command, Crew tab, click an agent card. Profile modal should appear with available data (portraits will show fallback circles until generated).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/bridge/routes.py platform_v2/templates/tools/bridge.html
git commit -m "feat(fleet): agent profile modal — portrait, shift state, rankings, welfare gauges"
```

---

## Chunk 5: Bridge Command Visibility

### Task 10: Crew Tab Enhancements — Fleet Overview + Shift State Indicators (Section 5a-5b)

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py` — enhance manifest with shift_state, rotation data
- Modify: `platform_v2/templates/tools/bridge.html` — fleet overview panel, shift state badges on cards

**Dependencies:** Task 4 (shift states in dispatcher), Task 1 (agent_rotation_log)

- [ ] **Step 1: Enhance get_crew_manifest() in routes.py**

In the crew manifest endpoint (around line 6941-7023), add shift state and fleet summary:

```python
# Shift states
cur.execute("SELECT id, shift_state FROM agents WHERE status IN ('active', 'inactive')")
shift_states = {r["id"]: r["shift_state"] or "active" for r in cur.fetchall()}

# Add to each manifest entry
for entry in manifest:
    entry["shift_state"] = shift_states.get(entry["agent_id"], "active")

# Fleet overview counts
shift_counts = {"active": 0, "winding_down": 0, "cooldown": 0, "off_duty": 0, "reserves": 0}
for entry in manifest:
    state = entry.get("shift_state", "active")
    if state in shift_counts:
        shift_counts[state] += 1

cur.execute("SELECT count(*) AS cnt FROM agents WHERE status = 'inactive'")
shift_counts["reserves"] = cur.fetchone()["cnt"]
```

Add `"fleet_overview": shift_counts` to the response JSON.

- [ ] **Step 2: Add fleet overview bar to bridge.html**

Before the crew manifest grid (around line 8284), add fleet overview bar HTML:
- ON DUTY count (green), WINDING DOWN count (amber), RESTING count (red), RESERVES count (grey), RAM usage (cyan)
- Each count is clickable to filter crew cards by state
- CSS: `.fleet-overview-bar` flex row, `.fleet-stat` with state-colored strong text
- Use Antonio font, uppercase, letter-spacing for LCARS aesthetic

- [ ] **Step 3: Update renderCrewManifest() to show shift state badges**

In `_renderAgentCard()` (around line 17847), add shift state badge using safe DOM construction:

```javascript
// Shift state badge — built via createElement for safety
const shiftState = agent.shift_state || 'active';
const shiftColors = {active:'#32CD32', winding_down:'#FFD700', cooldown:'#FF6347', off_duty:'#666'};
const shiftLabels = {active:'ON DUTY', winding_down:'WINDING DOWN', cooldown:'COOLDOWN', off_duty:'OFF DUTY'};
const shiftBadge = document.createElement('span');
shiftBadge.className = 'crew-shift-badge';
shiftBadge.style.cssText = 'background:' + shiftColors[shiftState] + '20;color:' + shiftColors[shiftState] + ';border:1px solid ' + shiftColors[shiftState] + '40';
shiftBadge.textContent = shiftLabels[shiftState];
```

Update fleet overview counts using textContent:
```javascript
if (data.fleet_overview) {
    document.getElementById('fleet-active').textContent = data.fleet_overview.active || 0;
    document.getElementById('fleet-winding').textContent = data.fleet_overview.winding_down || 0;
    document.getElementById('fleet-cooldown').textContent = data.fleet_overview.cooldown || 0;
    document.getElementById('fleet-reserves').textContent = data.fleet_overview.reserves || 0;
}
```

- [ ] **Step 4: Add portrait to agent cards**

In `_renderAgentCard()`, replace the initial-letter circle with portrait image using safe DOM methods:

```javascript
const portraitImg = document.createElement('img');
portraitImg.src = '/static/img/agents/' + agent.name + '_avatar.png';
portraitImg.style.cssText = 'width:32px;height:32px;border-radius:4px';
portraitImg.alt = agent.name;
const fallbackSpan = document.createElement('span');
fallbackSpan.className = 'crew-agent-initial';
fallbackSpan.style.cssText = 'display:none;width:32px;height:32px;border-radius:4px;align-items:center;justify-content:center;background:var(--archie-accent);font-size:0.7rem';
fallbackSpan.textContent = (agent.full_name || agent.name).charAt(0).toUpperCase();
portraitImg.onerror = function() { this.style.display='none'; fallbackSpan.style.display='flex'; };
```

- [ ] **Step 5: Verify in browser**

Open Bridge Command, Crew tab. Check:
- Fleet overview bar with counts
- Shift state badges on agent cards
- Portrait images (fallback to initials if not generated yet)

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/bridge/routes.py platform_v2/templates/tools/bridge.html
git commit -m "feat(fleet): crew tab — fleet overview bar, shift state badges, portrait images"
```

---

### Task 11: Rotation Log Panel (Section 5c-5d)

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py` — add rotation log API endpoint
- Modify: `platform_v2/templates/tools/bridge.html` — rotation log panel in Crew tab

**Dependencies:** Task 4 (shift transitions write to agent_rotation_log)

- [ ] **Step 1: Add rotation log API endpoint**

In `routes.py`, add:

```python
@bridge_bp.route("/api/bridge/rotation-log")
@admin_required
def get_rotation_log():
    """Recent rotation events for the Crew tab live feed."""
    try:
        limit = request.args.get("limit", 20, type=int)
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT rl.shift_state, rl.started_at, rl.reason,
                       a.name AS agent_name, a.display_name,
                       bs.station_code,
                       ra.name AS replaced_by_name
                FROM agent_rotation_log rl
                JOIN agents a ON rl.agent_id = a.id
                LEFT JOIN bridge_stations bs ON rl.station_id = bs.id
                LEFT JOIN agents ra ON rl.replaced_by = ra.id
                ORDER BY rl.started_at DESC
                LIMIT %s
            """, (limit,))
            events = [dict(r) for r in cur.fetchall()]
            return jsonify({"success": True, "events": events})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 2: Add rotation log panel to bridge.html**

After the fleet overview bar, add a collapsible rotation log panel. Build entries using safe DOM methods (createElement + textContent):

```javascript
async function loadRotationLog() {
    try {
        const resp = await fetch('/tools/bridge/api/bridge/rotation-log?limit=20');
        const data = await resp.json();
        if (!data.success) return;
        const container = document.getElementById('rotation-log-entries');
        container.replaceChildren(); // Clear safely
        data.events.forEach(function(e) {
            const entry = document.createElement('div');
            entry.className = 'rotation-log-entry';
            const time = new Date(e.started_at).toLocaleTimeString('en-US', {hour:'2-digit',minute:'2-digit'});
            const timeSpan = document.createElement('span');
            timeSpan.textContent = time + ' ';
            const nameStrong = document.createElement('strong');
            nameStrong.textContent = e.agent_name;
            const arrow = document.createTextNode(' \u2192 ');
            const stateSpan = document.createElement('span');
            stateSpan.className = 'state-' + e.shift_state;
            stateSpan.textContent = e.shift_state.toUpperCase();
            const suffix = document.createTextNode(
                ' at ' + (e.station_code || '?') + ' (' + (e.reason || 'manual') + ')' +
                (e.replaced_by_name ? ' \u2192 replaced by ' + e.replaced_by_name : '')
            );
            entry.appendChild(timeSpan);
            entry.appendChild(nameStrong);
            entry.appendChild(arrow);
            entry.appendChild(stateSpan);
            entry.appendChild(suffix);
            container.appendChild(entry);
        });
    } catch (e) { console.error('Rotation log error:', e); }
}
```

CSS:
```css
.rotation-log-panel { margin-bottom: 0.75rem; border: 1px solid rgba(255,255,255,0.08); border-radius: 4px; overflow: hidden; }
.rotation-log-header { padding: 0.4rem 0.75rem; background: rgba(255,255,255,0.03); font-family: 'Antonio', sans-serif; font-size: 0.7rem; letter-spacing: 1px; cursor: pointer; color: #aaa; }
.rotation-log-body { max-height: 200px; overflow-y: auto; }
.rotation-log-entry { padding: 0.3rem 0.75rem; font-size: 0.7rem; color: #999; border-bottom: 1px solid rgba(255,255,255,0.03); font-family: 'IBM Plex Mono', monospace; }
.rotation-log-entry .state-active { color: #32CD32; }
.rotation-log-entry .state-winding_down { color: #FFD700; }
.rotation-log-entry .state-cooldown { color: #FF6347; }
.rotation-log-entry .state-off_duty { color: #666; }
```

- [ ] **Step 3: Auto-refresh rotation log with crew manifest**

In `loadCrewManifest()` callback, if the rotation log panel is expanded, also call `loadRotationLog()`.

- [ ] **Step 4: Verify**

Open Bridge Command, Crew tab, expand Rotation Log. Should show recent transitions (if any have occurred).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/bridge/routes.py platform_v2/templates/tools/bridge.html
git commit -m "feat(fleet): rotation log panel — live feed of shift changes in Crew tab"
```

---

### Task 12: Deploy + Integration Test + Dev HQ Update

**Files:** None new — verification and tracking only.

- [ ] **Step 1: Restart Docker**

```bash
docker compose restart archie_platform
sleep 5
docker logs archie_platform 2>&1 | tail -30
```

Verify: No startup errors, all new APScheduler jobs registered (welfare_recovery, idle_volunteering, performance_rankings).

- [ ] **Step 2: Verify fleet management tables**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT count(*) FROM agent_rotation_log"
docker exec archie_database psql -U archie -d archie -c "SELECT count(*) FROM agent_performance_rankings"
docker exec archie_database psql -U archie -d archie -c "SELECT name, shift_state FROM agents WHERE status = 'active'"
```

- [ ] **Step 3: Verify Crew tab in browser**

- Open http://192.168.1.200:3000/tools/bridge, Crew tab
- Check: Fleet overview bar with counts
- Check: Shift state badges on agent cards
- Check: Rotation log panel (collapsible)
- Check: Agent card click opens profile modal
- Check: Portrait fallback (initial circles until generated)

- [ ] **Step 4: Trigger a test dispatch and verify shift awareness**

```bash
docker logs archie_platform 2>&1 | grep -i "shift\|winding\|cooldown\|rotation" | tail -10
```

- [ ] **Step 5: Update Dev HQ**

Via MCP:
- Complete Task #848 (Section 1) — budget reset done, welfare recovery + idle volunteering implemented
- Complete Task #849 (Section 2) — shift lifecycle engine implemented
- Complete Task #850 (Section 3) — performance rankings + dispatch integration done
- Complete Task #851 (Section 4) — roster expanded, portrait generator created, profile modal added
- Complete Task #852 (Section 5) — fleet overview, rotation log, notifications implemented
- Update project #127 status to "completed"
- Store memory: roadmap update with fleet management completion

- [ ] **Step 6: Final push**

```bash
git push
```
