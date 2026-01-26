# Shift Scheduler Guide

**Module:** Team Management > Scheduler Tab
**Phase:** 28 - Consciousness Optimization & Admin Ops Integration
**Status:** Active

---

## Overview

The Shift Scheduler provides comprehensive shift management for A.R.C.H.I.E.'s AI agent workforce. It enables time-based agent routing, conflict detection, and staffing coverage monitoring.

## Features

### 1. Shift Definitions
Three standard shifts are pre-configured:
- **Morning:** 06:00 - 14:00
- **Afternoon:** 14:00 - 22:00
- **Night:** 22:00 - 06:00

### 2. Week Calendar View
Visual calendar showing agent assignments by shift and day of week. Navigate between weeks to view past/future schedules.

### 3. On-Duty Status
Real-time display of agents currently working based on:
- Current time
- Day of week
- Assigned shift definitions

### 4. Conflict Detection
Automatic detection of scheduling issues:
- **Understaffed:** Station has no primary agent for a shift
- **No Backup:** Station has primary but no backup agent
- **Overstaffed:** Station has >3 agents (resource waste)
- **Consecutive Shifts:** Agent assigned to multiple shifts (IAAE violation)
- **IAAE Violations:** Workload limits or stress thresholds exceeded

### 5. Rotation Management
Configure automatic shift rotations (e.g., A/B/C team weekly cycling).

### 6. Bulk Assignment
Quickly assign agents to shifts based on station and role.

---

## Database Schema

### Tables

#### `shift_definitions`
```sql
id              SERIAL PRIMARY KEY
shift_name      VARCHAR(50)     -- 'Morning', 'Afternoon', 'Night'
start_time      TIME
end_time        TIME
timezone        VARCHAR(50)     DEFAULT 'America/Los_Angeles'
is_active       BOOLEAN         DEFAULT true
```

#### `agent_shifts`
```sql
id              SERIAL PRIMARY KEY
agent_id        INTEGER         REFERENCES agents(id)
shift_id        INTEGER         REFERENCES shift_definitions(id)
station_id      INTEGER         REFERENCES bridge_stations(id)
day_of_week     INTEGER         -- 0=Sun, 1=Mon, ..., 6=Sat
effective_from  DATE
effective_until DATE            -- NULL = ongoing
is_primary      BOOLEAN         DEFAULT true
```

#### `shift_conflicts`
```sql
id              SERIAL PRIMARY KEY
agent_id        INTEGER         REFERENCES agents(id)
station_id      INTEGER         REFERENCES bridge_stations(id)
shift_id        INTEGER         REFERENCES shift_definitions(id)
conflict_date   DATE
conflict_type   VARCHAR(50)
severity        VARCHAR(20)     -- 'critical', 'warning', 'info'
description     TEXT
resolved        BOOLEAN         DEFAULT false
resolution_note TEXT
```

#### `shift_rotations`
```sql
id              SERIAL PRIMARY KEY
rotation_name   VARCHAR(100)
station_id      INTEGER         REFERENCES bridge_stations(id)
rotation_pattern JSONB          -- e.g., ['A','B','C']
current_week    INTEGER         DEFAULT 1
is_active       BOOLEAN         DEFAULT true
```

---

## API Endpoints

### Shift Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/shifts` | List all shift definitions |
| POST | `/api/shifts` | Create new shift definition |
| GET | `/api/shifts/calendar` | Get week calendar view |
| GET | `/api/shifts/on-duty` | Get agents currently on duty |
| GET | `/api/shifts/conflicts` | Get unresolved conflicts |
| POST | `/api/shifts/detect-conflicts` | Run conflict detection |
| POST | `/api/shifts/conflicts/<id>/resolve` | Resolve a conflict |
| GET | `/api/shifts/staffing` | Get station staffing summary |

### Agent Shifts
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/agents/<id>/shifts` | Get agent's shift assignments |
| POST | `/api/agents/<id>/shifts` | Assign agent to shift |
| DELETE | `/api/agents/<id>/shifts/<shift_id>` | Remove shift assignment |
| POST | `/api/agents/bulk-assign-shifts` | Bulk assign shifts |

### Rotations
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/rotations` | List rotation schedules |
| POST | `/api/rotations` | Create rotation schedule |
| POST | `/api/rotations/<id>/advance` | Advance to next week |

---

## Shift-Aware Routing

The AI Bridge (`archie_bridge.py`) now includes shift-aware routing:

```python
from archie_bridge import get_agents_on_duty, get_available_agent_for_station, route_task_to_station

# Get all on-duty agents
agents = get_agents_on_duty()

# Get on-duty agents for a specific station
engineering_agents = get_agents_on_duty('Engineering')

# Get best available agent for a station (considers shifts + priority)
agent = get_available_agent_for_station('Engineering')

# Route a task to appropriate station
routing = route_task_to_station('code_review')
# Returns: {'station': 'R&D', 'agent': {...}, 'task_type': 'code_review', 'routed_at': '...'}
```

### Routing Logic
1. Check agents on-duty for the station
2. Prioritize primary agents over backups
3. If no on-duty agents, fall back to any assigned agent
4. If no station agents, fall back to contractors

---

## IAAE Compliance

The Shift Scheduler enforces IAAE (Intelligent Agent Autonomous Entity) governance:

### Workload Limits
- **Internal Agents:** Max 500 tasks/day
- **Contract Agents:** Max 100 tasks/day

### Rest Cycles
- Stress level > 0.85 triggers mandatory rest
- Consecutive shift detection prevents burnout

### Conflict Resolution
All conflicts must be resolved with a note for audit purposes.

---

## Usage Examples

### Assigning an Agent to Morning Shift
```bash
curl -X POST http://localhost:3000/tools/team-management/api/agents/77/shifts \
  -H "Content-Type: application/json" \
  -d '{"shift_id": 1, "day_of_week": 1, "is_primary": true}'
```

### Running Conflict Detection
```bash
curl -X POST http://localhost:3000/tools/team-management/api/shifts/detect-conflicts
```

### Getting Weekly Calendar
```bash
curl http://localhost:3000/tools/team-management/api/shifts/calendar?week_offset=0
```

---

## Related Documentation

- [Lean Staffing Matrix](LEAN_STAFFING_MATRIX.md)
- [Bridge Station Architecture](BRIDGE_STATION_ARCHITECTURE.md)
- [Agent Delegation System](AGENT_DELEGATION_SYSTEM.md)
- [IAAE Governance Framework](ARCHIE_GOVERNANCE_FRAMEWORK_IAAE.md)

---

**Last Updated:** 2026-01-17 (Phase 28)
