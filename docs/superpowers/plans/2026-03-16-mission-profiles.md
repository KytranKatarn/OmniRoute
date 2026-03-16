# Mission Profiles Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 reconfigurable mission profiles that dynamically change Bridge dispatch routing, IAAE welfare, warmup priority, and UI presentation.

**Architecture:** New `mission_profiles` + `mission_schedules` tables seeded with 6 profiles. `mission_manager.py` handles profile loading/activation/scheduling. Dispatcher checks active profile before routing. Bridge UI shows active mission banner.

**Tech Stack:** Python/Flask, PostgreSQL, JavaScript (Bridge UI), APScheduler

**Spec:** `docs/superpowers/specs/2026-03-16-mission-profiles-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `database/migrations/173_mission_profiles.sql` | Tables + 6 seed profiles |
| `ai_bridge/mission_manager.py` | Profile CRUD, activation, schedule check, event triggers |
| `ai_bridge/bridge_dispatcher.py` | `_resolve_station()` with profile overrides |
| `ai_bridge/agent_loop.py` | `_check_mission_schedule()` job |
| `platform_v2/tools/bridge/routes.py` | 6 mission API endpoints |
| `platform_v2/templates/tools/bridge.html` | Mission banner + profile selector |

---

## Chunk 1: Database + Mission Manager

### Task 1: Create migration with tables + seed data

**Files:**
- Create: `database/migrations/173_mission_profiles.sql`

- [ ] **Step 1: Write migration SQL**

Tables: `mission_profiles` (id, name, display_name, description, color, icon, job_routing_overrides JSONB, station_priorities JSONB, agent_config JSONB, loop_job_config JSONB, event_triggers JSONB, is_default BOOLEAN, created_at, updated_at) + `mission_schedules` (id, profile_id FK, cron_expression, duration_minutes, is_active, created_at).

Seed 6 profiles with appropriate JSONB configs:
- standard_operations (default, cyan, all equal weights)
- security_audit (red, SECURITY+OPERATIONS high priority, scan intervals reduced)
- feature_sprint (green, ENGINEERING+ANALYTICS high, code models prioritized)
- content_push (pink, CREATIVE+COMMUNICATIONS high)
- maintenance (amber, reduced everything, aggressive rest)
- emergency_response (dark red, all max, skip rest, cloud auto-approve)

- [ ] **Step 2: Run migration**

```bash
docker cp database/migrations/173_mission_profiles.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/173_mission_profiles.sql
```

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT name, display_name, color, is_default FROM mission_profiles;"
```

- [ ] **Step 4: Commit**

```bash
git add database/migrations/173_mission_profiles.sql
git commit -m "feat(bridge): mission profiles migration — 6 seed profiles"
```

---

### Task 2: Build mission_manager.py

**Files:**
- Create: `ai_bridge/mission_manager.py`

- [ ] **Step 1: Write the mission manager**

Class `MissionManager` with methods:
- `__init__()` — cache for active profile (60s TTL)
- `get_active_profile()` — read from system_config, return full profile dict
- `get_all_profiles()` — list all 6
- `get_profile(name)` — single profile by name
- `activate_profile(name, triggered_by='manual', reason='')` — update system_config, log to governance_audit_log, send Telegram notification
- `check_schedule()` — evaluate cron rules, activate if due
- `check_event_triggers(event_type, event_data)` — evaluate profile event_triggers, activate if matched
- `get_routing_overrides()` — return active profile's job_routing_overrides
- `get_station_priorities()` — return active profile's station_priorities
- `get_agent_config()` — return active profile's agent_config

Use `from database import get_db_cursor` pattern. Cache active profile with time-based TTL.

- [ ] **Step 2: Test from Docker**

```bash
docker exec archie_platform python3 -c "
from ai_bridge.mission_manager import MissionManager
mm = MissionManager()
print('Active:', mm.get_active_profile())
print('All:', [p['name'] for p in mm.get_all_profiles()])
"
```

- [ ] **Step 3: Commit**

```bash
git add ai_bridge/mission_manager.py
git commit -m "feat(bridge): mission manager — profile CRUD, activation, scheduling"
```

---

## Chunk 2: Dispatcher + Agent Loop Integration

### Task 3: Integrate with Bridge dispatcher

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py`

- [ ] **Step 1: Add profile-aware station resolution**

Add to the dispatcher class:
```python
def _resolve_station(self, job_type):
    """Resolve station for job type, checking mission profile overrides first."""
    try:
        from ai_bridge.mission_manager import MissionManager
        mm = MissionManager()
        overrides = mm.get_routing_overrides()
        if overrides and job_type in overrides:
            return overrides[job_type]
    except Exception:
        pass
    return JOB_TYPE_STATION_MAP.get(job_type)
```

Update the existing dispatch logic to call `_resolve_station()` instead of directly reading `JOB_TYPE_STATION_MAP`.

- [ ] **Step 2: Commit**

```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat(bridge): dispatcher uses mission profile routing overrides"
```

---

### Task 4: Add schedule check to agent loop

**Files:**
- Modify: `ai_bridge/agent_loop.py`

- [ ] **Step 1: Add schedule check job**

Register:
```python
self.scheduler.add_job(
    with_app_context(self._check_mission_schedule),
    trigger=IntervalTrigger(minutes=5),
    id="agent_mission_schedule",
    name="Agent Loop: Mission Profile Schedule",
    replace_existing=True,
)
```

Method:
```python
def _check_mission_schedule(self):
    try:
        from ai_bridge.mission_manager import MissionManager
        mm = MissionManager()
        mm.check_schedule()
    except Exception as e:
        logger.debug(f"Mission schedule check failed: {e}")
```

- [ ] **Step 2: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(bridge): mission profile schedule check in agent loop (5 min)"
```

---

## Chunk 3: API + Bridge UI

### Task 5: Add mission API endpoints

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py`

- [ ] **Step 1: Add 6 endpoints**

```python
GET  /api/mission/active      — current profile
GET  /api/mission/profiles    — list all 6
PUT  /api/mission/activate/<id> — switch profile
POST /api/mission/schedule    — add schedule rule
GET  /api/mission/schedule    — list schedules
DELETE /api/mission/schedule/<id> — remove schedule
```

All require @login_required @admin_required.

- [ ] **Step 2: Test endpoints**

```bash
curl /api/mission/active
curl /api/mission/profiles
curl -X PUT /api/mission/activate/1
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(bridge): 6 mission profile API endpoints"
```

---

### Task 6: Add mission banner to Bridge UI

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

- [ ] **Step 1: Add mission banner**

Below the tab bar, add a mission status banner that shows:
- Active profile name + color accent
- Profile selector dropdown (changes on click)
- "Since X minutes ago" indicator

Fetch from `/api/mission/active` on page load.

- [ ] **Step 2: Add profile selector modal**

LCARS tablet modal (bm-) showing all 6 profiles as cards. Click to activate. Confirmation before switching.

- [ ] **Step 3: Station glow intensity**

Update the isometric station map to adjust glow/brightness based on active profile's `station_priorities` weights.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): mission banner + profile selector in Bridge UI"
```

---

### Task 7: Integration test + final commit

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Test full flow**

1. Check default profile is "Standard Operations"
2. Switch to "Security Audit" via API
3. Verify Telegram notification sent
4. Verify dispatch routing changed
5. Switch back to "Standard Operations"

- [ ] **Step 3: Mark task complete in Dev HQ**

- [ ] **Step 4: Final commit + push**
