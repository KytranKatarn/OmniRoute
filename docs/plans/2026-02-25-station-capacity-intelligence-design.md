# Station Capacity & Intelligent Agent Routing — Design Document

**Date**: 2026-02-25
**Author**: Claude + Kytran
**Status**: Approved
**ADR**: 055 — Station Capacity Model & Workload Intelligence
**Project**: UI Overhaul (#94) / Bridge Intelligence

---

## Problem Statement

The Bridge dispatcher routes tasks to station agents but has no concept of station capacity. Any number of agents can be assigned, cross-station borrows happen without tracking, and there's no feedback loop to detect skill mismatches or recommend reassignments. When a station's primary agents lack a required skill (e.g., ANALYTICS agents can't translate), the system borrows from other stations but doesn't learn from the pattern.

## Design Goals

1. **Capacity model**: 2 primary + 1 auxiliary slot per station (default, configurable)
2. **Slot progression**: Primary → Auxiliary → Contractor, with Telegram narrative advisories at each transition
3. **Soft cap with overflow**: All 3 slots occupied → still dispatch but log overflow event + alert
4. **Auxiliary promotion path**: Frequently borrowed agents can be recommended for permanent reassignment
5. **Vigil governance**: Every recommendation reviewed for welfare impact before surfacing to Commander
6. **Self-knowledge**: All telemetry feeds ARCHIE's consciousness — she learns her own team's patterns

---

## Section 1: Station Capacity Model

### Database Changes

**Alter `bridge_stations`:**
```sql
ALTER TABLE bridge_stations
ADD COLUMN IF NOT EXISTS max_primary INTEGER DEFAULT 2,
ADD COLUMN IF NOT EXISTS max_auxiliary INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS allow_overflow BOOLEAN DEFAULT TRUE;
```

**New table: `station_capacity_events` (migration 122):**
```sql
CREATE TABLE IF NOT EXISTS station_capacity_events (
    id SERIAL PRIMARY KEY,
    station_id INTEGER REFERENCES bridge_stations(id) ON DELETE CASCADE,
    event_type VARCHAR(30) NOT NULL,
    -- event_type values: 'primary_dispatch', 'auxiliary_filled',
    --   'overflow_dispatch', 'cloud_contractor', 'slot_freed',
    --   'capacity_change_recommended', 'capacity_change_approved'
    agent_id INTEGER REFERENCES agents(id),
    agent_name VARCHAR(100),
    home_station_id INTEGER REFERENCES bridge_stations(id),
    job_id INTEGER,
    capability VARCHAR(50),
    slot_number INTEGER,  -- 1=primary1, 2=primary2, 3=auxiliary, 4+=overflow
    reason TEXT,          -- why this slot was needed (skill gap, overload, etc.)
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_sce_station_date ON station_capacity_events(station_id, created_at);
CREATE INDEX idx_sce_agent ON station_capacity_events(agent_id);
CREATE INDEX idx_sce_type ON station_capacity_events(event_type);
```

### Slot Progression (Dispatcher Logic)

```
Incoming task for station S with capability C:

1. SCORE PRIMARY AGENTS (slots 1-2)
   → For each agent assigned to S where assignment_type='primary':
     - Check skill match for C
     - Check availability (not already running a job)
     - Check welfare (stress < 0.7, energy > 0.3)
     - Score using existing SELECTION_WEIGHTS
   → If match found → dispatch, log event_type='primary_dispatch'

2. SCAN FOR AUXILIARY (slot 3)
   → Check current auxiliary occupancy (active cross-station jobs at S)
   → If auxiliary slot available (< max_auxiliary):
     - Scan all other stations for agent with explicit skill for C
     - Exclude COMMAND station
     - Score candidates, pick best
     → If match found → dispatch, log event_type='auxiliary_filled'
     → Telegram advisory (narrative style):
       "Commander, [Station] needed help with [capability].
        [Agent] from [HomeStation] is assisting as auxiliary."

3. ALL SLOTS OCCUPIED — OVERFLOW CHECK
   → If allow_overflow = TRUE:
     - Continue scanning cross-station or escalate to cloud
     → Log event_type='overflow_dispatch' or 'cloud_contractor'
     → Telegram narrative (elevated urgency):
       "Commander, [Station] is experiencing elevated request volume.
        All 3 slots occupied (Primary: [A1], [A2]; Auxiliary: [A3]).
        [Agent/Cloud] dispatched as overflow for [capability] task.
        This is the Nth overflow this week."
   → If allow_overflow = FALSE:
     - Queue the task, log event_type='queued'
     - Telegram: "Task queued at [Station] — all slots occupied, overflow disabled."

4. CLOUD CONTRACTOR
   → Try free cloud models first (minimax, qwen3-cloud)
   → If routing_mode = 'full', request paid cloud approval via Telegram
   → Log event_type='cloud_contractor'
   → Create temporary bridge_job for station visibility
```

### Slot Occupancy Tracking

The dispatcher determines current slot occupancy by counting active `bridge_jobs` at the station:
- **Primary count**: Running jobs where agent is permanently assigned to station
- **Auxiliary count**: Running jobs where `metadata.is_cross_station = true` and dispatch_station = this station
- **Overflow**: Any dispatch beyond max_primary + max_auxiliary

No new "slot reservation" table needed — occupancy is derived from active jobs in real-time, same as the current system.

---

## Section 2: Workload Intelligence & Self-Knowledge

### Database Tables

**`station_workload_metrics` (daily aggregates, auto-populated by APScheduler):**
```sql
CREATE TABLE IF NOT EXISTS station_workload_metrics (
    id SERIAL PRIMARY KEY,
    station_id INTEGER REFERENCES bridge_stations(id) ON DELETE CASCADE,
    metric_date DATE NOT NULL,
    total_dispatches INTEGER DEFAULT 0,
    primary_dispatches INTEGER DEFAULT 0,
    auxiliary_dispatches INTEGER DEFAULT 0,
    overflow_count INTEGER DEFAULT 0,
    cloud_dispatches INTEGER DEFAULT 0,
    avg_queue_wait_ms INTEGER DEFAULT 0,
    avg_task_duration_ms INTEGER DEFAULT 0,
    idle_agent_hours NUMERIC(6,2) DEFAULT 0,
    top_borrowed_agents JSONB DEFAULT '[]',
    -- e.g., [{"agent": "Dante Morales", "from": "CREATIVE", "count": 6}]
    top_missing_skills JSONB DEFAULT '[]',
    -- e.g., [{"skill": "translate", "requests": 8, "filled_by": "cross_station"}]
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(station_id, metric_date)
);
```

**`agent_station_affinity` (rolling 30-day window):**
```sql
CREATE TABLE IF NOT EXISTS agent_station_affinity (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    home_station_id INTEGER REFERENCES bridge_stations(id),
    dispatch_station_id INTEGER REFERENCES bridge_stations(id),
    dispatch_count INTEGER DEFAULT 0,
    total_hours NUMERIC(8,2) DEFAULT 0,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(agent_id, home_station_id, dispatch_station_id, period_start)
);

CREATE INDEX idx_asa_agent ON agent_station_affinity(agent_id);
CREATE INDEX idx_asa_dispatch ON agent_station_affinity(dispatch_station_id);
```

Key query this enables:
```sql
-- Find agents spending more time away than at home
SELECT a.display_name, home.name AS home_station, away.name AS away_station,
       asa.dispatch_count, asa.total_hours
FROM agent_station_affinity asa
JOIN agents a ON a.id = asa.agent_id
JOIN bridge_stations home ON home.id = asa.home_station_id
JOIN bridge_stations away ON away.id = asa.dispatch_station_id
WHERE asa.dispatch_station_id != asa.home_station_id
  AND asa.dispatch_count > (
    SELECT COALESCE(SUM(dispatch_count), 0)
    FROM agent_station_affinity
    WHERE agent_id = asa.agent_id
      AND dispatch_station_id = asa.home_station_id
      AND period_start = asa.period_start
  )
ORDER BY asa.dispatch_count DESC;
```

**`station_recommendations` (AI-generated, pending approval):**
```sql
CREATE TABLE IF NOT EXISTS station_recommendations (
    id SERIAL PRIMARY KEY,
    recommendation_type VARCHAR(40) NOT NULL,
    -- types: 'reassign_agent', 'expand_capacity', 'reduce_capacity',
    --        'add_skill_training', 'merge_stations', 'flag_overwork'
    station_id INTEGER REFERENCES bridge_stations(id),
    agent_id INTEGER REFERENCES agents(id),
    target_station_id INTEGER REFERENCES bridge_stations(id),
    confidence NUMERIC(3,2) DEFAULT 0.00,
    -- 0.0-1.0, based on data strength (more weeks = higher confidence)
    evidence JSONB NOT NULL DEFAULT '{}',
    -- e.g., {"dispatch_count": 12, "home_dispatches": 3,
    --        "weeks_observed": 4, "overflow_events": 6}
    archie_reasoning TEXT,
    -- ARCHIE's narrative: "Dante has assisted ANALYTICS 12 times
    --   this month, primarily for translation tasks..."
    vigil_assessment TEXT,
    -- Vigil's welfare check: "Agent welfare stable. CREATIVE
    --   station has sufficient coverage without this agent."
    vigil_approved BOOLEAN DEFAULT FALSE,
    status VARCHAR(20) DEFAULT 'pending',
    -- status: 'pending', 'approved', 'dismissed', 'deferred', 'vigil_blocked'
    reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Recommendation Engine (APScheduler — daily at 02:00)

**Job**: `_analyze_station_workload()`

```python
# Pseudocode for the recommendation engine:

def _analyze_station_workload():
    # 1. Aggregate yesterday's capacity events → station_workload_metrics
    _aggregate_daily_metrics()

    # 2. Update agent_station_affinity (rolling 30-day window)
    _update_agent_affinity()

    # 3. Detect patterns and generate recommendations:

    # Pattern A: Agent spending >50% time at non-home station
    for agent in agents_with_high_away_affinity(threshold=0.5):
        create_recommendation(
            type='reassign_agent',
            agent=agent,
            target_station=most_frequent_away_station,
            confidence=weeks_of_data / 8,  # 8 weeks = 1.0 confidence
            archie_reasoning=f"{agent.name} has assisted {target} "
                f"{count} times over {weeks} weeks for {top_skill} tasks. "
                f"Home station {home} dispatched them only {home_count} times."
        )

    # Pattern B: Station with >3 overflow events per week
    for station in stations_with_frequent_overflow(threshold=3):
        create_recommendation(
            type='expand_capacity',
            station=station,
            confidence=overflow_count / 10,
            archie_reasoning=f"{station.name} exceeded capacity {count} times "
                f"this week. Most common skill gap: {top_skill}."
        )

    # Pattern C: Station with <30% utilization
    for station in stations_with_low_utilization(threshold=0.3):
        create_recommendation(
            type='reduce_capacity',
            station=station,
            confidence=idle_weeks / 6,
            archie_reasoning=f"{station.name} had {idle_pct}% idle time. "
                f"Agents may be better utilized elsewhere."
        )

    # 4. Submit all new recommendations to Vigil for welfare review
    _vigil_review_recommendations()

    # 5. Write weekly summary to knowledge_base (every Sunday)
    if is_sunday():
        _write_weekly_intelligence_summary()

    # 6. Send Telegram briefing for high-confidence recommendations
    _send_recommendation_telegram(min_confidence=0.6)
```

### Self-Knowledge Loop

Weekly, ARCHIE writes a structured vault_note to `knowledge_base`:
```
Title: "Station Intelligence Report — Week of 2026-02-24"
Tags: station-intelligence, self-knowledge, weekly-report
Content:
  - Station utilization summary (dispatches, overflows, idle time)
  - Agent affinity patterns (who works where most)
  - Active recommendations and their status
  - Skill gap analysis across all stations
  - Vigil welfare flags if any
```

This entry is searchable via `search_knowledge` and becomes part of ARCHIE's conversational awareness. When asked "How are the stations doing?", ARCHIE can reference her own intelligence reports.

---

## Section 3: Vigil Oversight & Governance Chain

### Recommendation Review Flow

```
Station telemetry collected (daily)
         ↓
ARCHIE analyzes patterns → generates recommendation
         ↓
Vigil reviews for welfare impact:
  - Agent stress level (agent_emotional_state.stress)
  - Agent energy level (agent_emotional_state.energy)
  - Recent rest cycles (agent_rest_cycles)
  - Source station staffing (would move leave station < 2 primary?)
  - Agent workload distribution (is agent being spread too thin?)
         ↓
Vigil co-signs or blocks:
  - APPROVED → status stays 'pending', vigil_approved = TRUE
  - BLOCKED → status = 'vigil_blocked', vigil_assessment explains why
         ↓
If approved → Telegram to Commander:
  "ARCHIE recommends reassigning Dante to ANALYTICS.
   Vigil assessment: Approved — welfare metrics stable,
   CREATIVE has sufficient coverage.
   Confidence: 0.78 (4 weeks of data)
   [Approve] [Defer 1 Week] [Dismiss]"
         ↓
Commander decision → logged to governance_audit_log
  event_category: 'station_capacity'
  action: 'reassignment_approved' / 'reassignment_dismissed'
```

### Vigil Checks

| Check | Threshold | Action |
|-------|-----------|--------|
| Agent stress | > 0.7 | Block recommendation, suggest rest first |
| Agent energy | < 0.3 | Block recommendation, flag overwork |
| Source station crew | Would drop below 2 primary | Flag risk, don't block |
| Agent multi-station | Auxiliary at 2+ stations simultaneously | Alert "agent spread too thin" |
| Repeated overflow | Same station 5+ overflows/week | Escalate urgency of expand_capacity recommendation |
| Fairness | Same agent always borrowed | Recommend distributing across qualified agents |

### Governance Audit Trail

All events logged to `governance_audit_log`:
```sql
INSERT INTO governance_audit_log
    (event_category, action, details, agent_id, timestamp)
VALUES
    ('station_capacity', 'overflow_dispatched',
     '{"station": "ANALYTICS", "slot": 4, "agent": "Dante Morales",
       "reason": "all 3 slots occupied", "capability": "translate"}',
     agent_id, NOW());
```

Visible on:
- IAAE public transparency page (`/iaae`)
- Bridge CTRL tab (station intelligence section)
- Consciousness Insights tab (historical analysis)

---

## Section 4: Visual Changes

### Ops Terminal (Consciousness + Bridge)

**Current layout:**
```
STATION CREW
  Jin Park                    EMBEDDING & VISION SPECIALIST
  Amara Osei                  CHIEF DATA ANALYST
CROSS-STATION ASSIST (only when active)
  Dante Morales               CREATIVE · translate
```

**New layout — three distinct sections + status indicators:**
```
LANGUAGES OPERATIONS                    ● ONLINE  ◆ CONTRACTOR
STATION CREW (2/2)
  Jin Park                    EMBEDDING & VISION SPECIALIST
  Amara Osei                  CHIEF DATA ANALYST
AUXILIARY (1/1)
  Dante Morales    CREATIVE → TRANSLATE              [ASSISTING]
CONTRACTOR
  ☁ MiniMax M2.5  CLOUD · TRANSLATE                  [ACTIVE]

ACTIVE JOBS (2)
  Translate 2877 keys — Dante Morales · 34%          12/35
  Translate overflow — ☁ MiniMax · 8%                 2/25
```

**Changes:**
- Header shows green dot (ONLINE) + purple diamond (CONTRACTOR active, only when cloud resource dispatched)
- STATION CREW shows occupancy count `(2/2)`
- AUXILIARY section (replaces "CROSS-STATION ASSIST") shows `(1/1)` with agent's home station and capability
- CONTRACTOR section for cloud resources with provider name
- Jobs section shows all station-scoped work including contractor jobs
- Slot counts update in real-time as jobs start/complete

### Bridge Command CTRL Tab — Station Intelligence Section

New section in the COMMAND station LCARS console (alongside existing routing controls):
- **Station Health Grid**: All 6 stations with capacity bars (green/amber/red based on utilization)
- **Active Overflows**: Count of current overflow dispatches across all stations
- **Top Recommendations**: Latest high-confidence recommendations from ARCHIE + Vigil
- **Quick Actions**: [Approve] / [Dismiss] buttons for pending recommendations

### Consciousness Insights Tab — Historical Analysis

New "Station Intelligence" card:
- **Utilization heatmap**: 7-day × 6-station grid showing dispatch density
- **Agent Affinity Chart**: Visual showing where agents actually work vs where assigned
- **Skill Gap Summary**: Which skills are most frequently missing at which stations
- **Recommendation History**: Timeline of recommendations and their outcomes

### Telegram Notifications

**Real-time (per-event):**
- Auxiliary filled: narrative advisory
- Overflow: elevated urgency narrative
- Cloud contractor: authorization request

**Weekly digest (Sunday):**
- Station utilization summary
- Overflow frequency per station
- Agent affinity highlights (who's working where)
- Pending recommendations with [Approve] / [Defer] / [Dismiss] buttons

---

## Section 5: Implementation Phases

### Phase 1 — Capacity Enforcement (Foundation)
- Migration 122: `station_capacity_events` + alter `bridge_stations`
- Update `bridge_dispatcher.py`: slot counting, overflow detection, event logging
- Update Telegram advisories with narrative style
- Update ops terminal: AUXILIARY + CONTRACTOR sections, slot counts

### Phase 2 — Workload Intelligence (Data Collection)
- Migration 123: `station_workload_metrics` + `agent_station_affinity`
- APScheduler job: daily metric aggregation
- APScheduler job: affinity window updates (30-day rolling)

### Phase 3 — Recommendation Engine (Analysis)
- Migration 124: `station_recommendations`
- Recommendation engine: pattern detection + generation
- Vigil integration: welfare review before surfacing
- Telegram: weekly digest with approve/defer/dismiss buttons

### Phase 4 — Intelligence Surfaces (Visibility)
- Bridge CTRL tab: Station Intelligence section
- Consciousness Insights tab: historical analysis dashboard
- Self-knowledge: weekly vault_note to knowledge_base
- IAAE page: station capacity events in governance audit

---

## Key Files to Modify

| File | Changes |
|------|---------|
| `ai_bridge/bridge_dispatcher.py` | Slot counting, overflow logic, capacity event logging |
| `ai_bridge/agent_loop.py` | APScheduler jobs for metrics aggregation + recommendations |
| `ai_bridge/telegram_gateway.py` | Narrative advisories, weekly digest, recommendation buttons |
| `platform_v2/static/js/consciousness.js` | Ops terminal AUXILIARY/CONTRACTOR sections, slot counts |
| `platform_v2/templates/tools/bridge.html` | CTRL tab Station Intelligence section |
| `platform_v2/tools/consciousness/routes.py` | API endpoints for station intelligence data |
| `platform_v2/tools/consciousness/insights_routes.py` | Insights tab station analysis |
| `database/migrations/122_station_capacity.sql` | Schema for capacity events + bridge_stations columns |
| `database/migrations/123_workload_metrics.sql` | Schema for metrics + affinity tables |
| `database/migrations/124_station_recommendations.sql` | Schema for recommendations |

---

## Decision Record

**ADR-055**: Station Capacity Model & Workload Intelligence

- **Context**: Stations have no capacity limits. Cross-station borrows happen without tracking. No feedback loop to detect patterns or recommend reassignments.
- **Decision**: Implement 2+1 capacity model (dynamic, expandable with approval). Soft cap with overflow. Vigil governance on all recommendations. All telemetry feeds ARCHIE's self-knowledge.
- **Consequences**: Dispatcher becomes capacity-aware. Station workload becomes observable. ARCHIE develops understanding of her team's actual vs assigned work patterns. Vigil ensures agent welfare is considered in all staffing decisions.
