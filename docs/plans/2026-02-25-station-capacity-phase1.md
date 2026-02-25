# Station Capacity Enforcement (Phase 1) — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add station capacity limits (2 primary + 1 auxiliary), slot progression enforcement in the dispatcher, capacity event logging, narrative Telegram advisories, and updated ops terminal visuals showing AUXILIARY/CONTRACTOR sections.

**Architecture:** Extend `bridge_stations` with capacity columns. Add `station_capacity_events` table for telemetry. Modify the dispatcher's `request_work()` and `create_job()` to count active slot occupancy and log transitions. Update `_renderOpsAgents()` in consciousness.js to show three crew sections (STATION CREW / AUXILIARY / CONTRACTOR) with occupancy counts. Enhance Telegram advisory messages with narrative style.

**Tech Stack:** PostgreSQL (migration), Python/Flask (dispatcher), JavaScript (ops terminal UI), python-telegram-bot (notifications)

**Key files reference:**
- Dispatcher: `ai_bridge/bridge_dispatcher.py` (3,384 lines)
- JS ops terminal: `platform_v2/static/js/consciousness.js` (2,297 lines)
- Bridge HTML (CREW tab renderer): `platform_v2/templates/tools/bridge.html` (~11,000 lines)
- Template CSS: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`
- Migrations: `database/migrations/122_station_capacity.sql`

**Note on HTML rendering:** The codebase uses `setHtml()` (a wrapper around innerHTML with escaping via `escHtml()`) as established pattern. All dynamic values MUST be escaped with `escHtml()` before insertion. This is the existing XSS-safe pattern used throughout consciousness.js.

---

### Task 1: Database Migration — Station Capacity Schema

**Files:**
- Create: `database/migrations/122_station_capacity.sql`

**Step 1: Write the migration**

```sql
-- Migration 122: Station Capacity Model (ADR-055)
-- Adds capacity columns to bridge_stations and creates station_capacity_events table

-- 1. Extend bridge_stations with capacity columns
ALTER TABLE bridge_stations
ADD COLUMN IF NOT EXISTS max_primary INTEGER DEFAULT 2,
ADD COLUMN IF NOT EXISTS max_auxiliary INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS allow_overflow BOOLEAN DEFAULT TRUE;

-- 2. Station capacity events — telemetry for every slot transition
CREATE TABLE IF NOT EXISTS station_capacity_events (
    id SERIAL PRIMARY KEY,
    station_id INTEGER REFERENCES bridge_stations(id) ON DELETE CASCADE,
    event_type VARCHAR(30) NOT NULL,
    -- event_type values:
    --   'primary_dispatch'   — task assigned to primary crew member
    --   'auxiliary_filled'   — cross-station agent filled auxiliary slot
    --   'overflow_dispatch'  — dispatch beyond max_primary + max_auxiliary
    --   'cloud_contractor'   — cloud resource dispatched to station
    --   'slot_freed'         — job completed, slot opened
    --   'queued'             — task queued because overflow disabled
    agent_id INTEGER REFERENCES agents(id),
    agent_name VARCHAR(100),
    home_station_id INTEGER REFERENCES bridge_stations(id),
    job_id INTEGER,
    capability VARCHAR(50),
    slot_number INTEGER,  -- 1-2=primary, 3=auxiliary, 4+=overflow
    reason TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sce_station_date
    ON station_capacity_events(station_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sce_agent
    ON station_capacity_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_sce_type
    ON station_capacity_events(event_type);

-- 3. Convenience view: current slot occupancy per station
CREATE OR REPLACE VIEW v_station_slot_occupancy AS
SELECT
    bs.id AS station_id,
    bs.station_code,
    bs.name AS station_name,
    bs.max_primary,
    bs.max_auxiliary,
    bs.allow_overflow,
    COUNT(CASE WHEN bj.metadata->>'is_cross_station' IS NULL
               OR bj.metadata->>'is_cross_station' = 'false'
               THEN 1 END) AS primary_occupied,
    COUNT(CASE WHEN bj.metadata->>'is_cross_station' = 'true'
               AND (bj.metadata->>'is_cloud' IS NULL
                    OR bj.metadata->>'is_cloud' = 'false')
               THEN 1 END) AS auxiliary_occupied,
    COUNT(CASE WHEN bj.metadata->>'is_cloud' = 'true' THEN 1 END) AS contractor_occupied
FROM bridge_stations bs
LEFT JOIN bridge_jobs bj ON bj.station_code = bs.station_code
    AND bj.status = 'running'
GROUP BY bs.id, bs.station_code, bs.name, bs.max_primary, bs.max_auxiliary, bs.allow_overflow;
```

**Step 2: Run the migration in Docker**

```bash
docker exec -it archie_database psql -U archie -d archie -f /migrations/122_station_capacity.sql
```

Expected: Tables created, columns added, view created — no errors.

**Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "\d station_capacity_events"
docker exec archie_database psql -U archie -d archie -c "SELECT station_code, max_primary, max_auxiliary, allow_overflow FROM bridge_stations LIMIT 3"
docker exec archie_database psql -U archie -d archie -c "SELECT * FROM v_station_slot_occupancy"
```

Expected: All 3 queries return valid results. max_primary=2, max_auxiliary=1, allow_overflow=true for all stations.

**Step 4: Commit**

```bash
git add database/migrations/122_station_capacity.sql
git commit -m "feat: migration 122 — station capacity schema (ADR-055)"
```

---

### Task 2: Dispatcher — Slot Counting and Event Logging Helpers

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py` (add after `_refresh_agent_cache()`, around line 325)

**Step 1: Add `_get_station_slot_occupancy()` method**

Add this method to the `BridgeDispatcher` class after `_refresh_agent_cache()`. It queries active `bridge_jobs` to determine current slot occupancy:

```python
def _get_station_slot_occupancy(self, station_code):
    """Count current slot occupancy at a station from active bridge_jobs.
    Returns dict with primary/auxiliary/contractor counts and capacity config.
    """
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, max_primary, max_auxiliary, allow_overflow
            FROM bridge_stations WHERE station_code = %s AND is_active = true
        """, (station_code,))
        station = cur.fetchone()
        if not station:
            return {"primary": 0, "auxiliary": 0, "contractor": 0, "total": 0,
                    "max_primary": 2, "max_auxiliary": 1, "allow_overflow": True}

        cur.execute("""
            SELECT
                COUNT(*) FILTER (
                    WHERE (metadata->>'is_cross_station') IS DISTINCT FROM 'true'
                    AND (metadata->>'is_cloud') IS DISTINCT FROM 'true'
                ) AS primary_count,
                COUNT(*) FILTER (
                    WHERE metadata->>'is_cross_station' = 'true'
                    AND (metadata->>'is_cloud') IS DISTINCT FROM 'true'
                ) AS auxiliary_count,
                COUNT(*) FILTER (
                    WHERE metadata->>'is_cloud' = 'true'
                ) AS contractor_count
            FROM bridge_jobs
            WHERE station_code = %s AND status = 'running'
        """, (station_code,))
        counts = cur.fetchone() or {}
        cur.close()

        primary = counts.get("primary_count", 0) or 0
        auxiliary = counts.get("auxiliary_count", 0) or 0
        contractor = counts.get("contractor_count", 0) or 0
        return {
            "primary": primary, "auxiliary": auxiliary,
            "contractor": contractor, "total": primary + auxiliary + contractor,
            "max_primary": station.get("max_primary", 2),
            "max_auxiliary": station.get("max_auxiliary", 1),
            "allow_overflow": station.get("allow_overflow", True),
            "station_id": station.get("id"),
        }
    except Exception as e:
        logger.warning(f"[CAPACITY] Error getting slot occupancy for {station_code}: {e}")
        return {"primary": 0, "auxiliary": 0, "contractor": 0, "total": 0,
                "max_primary": 2, "max_auxiliary": 1, "allow_overflow": True}
```

**Step 2: Add `_log_capacity_event()` method**

Add immediately after the above method:

```python
def _log_capacity_event(self, station_code, event_type, agent_id=None,
                        agent_name=None, home_station_id=None, job_id=None,
                        capability=None, slot_number=None, reason=None, metadata=None):
    """Log a station capacity event for workload intelligence (ADR-055)."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM bridge_stations WHERE station_code = %s", (station_code,))
        row = cur.fetchone()
        station_id = row[0] if row else None
        cur.execute("""
            INSERT INTO station_capacity_events
                (station_id, event_type, agent_id, agent_name, home_station_id,
                 job_id, capability, slot_number, reason, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (station_id, event_type, agent_id, agent_name, home_station_id,
              job_id, capability, slot_number, reason,
              psycopg2.extras.Json(metadata or {})))
        conn.commit()
        cur.close()
    except Exception as e:
        logger.warning(f"[CAPACITY] Error logging event {event_type} for {station_code}: {e}")
```

**Step 3: Verify platform starts cleanly**

```bash
docker compose restart archie_platform
docker logs archie_platform 2>&1 | tail -20
```

Expected: No import errors, platform starts normally.

**Step 4: Commit**

```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat(dispatcher): add slot occupancy counting and capacity event logging"
```

---

### Task 3: Dispatcher — Integrate Capacity Checks into `create_job()`

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py:2666-2906` (`create_job()` method)

The `create_job()` method is used by Consciousness tabs (GitHub reindex, translation jobs, knowledge analysis). It follows the same home to cross-station escalation pattern as `request_work()`.

**Step 1: Add occupancy check and slot number tracking**

After the agent selection logic resolves (around line 2809, after cross-station scan completes), add occupancy check before the INSERT:

```python
# Check capacity and determine slot number
occupancy = self._get_station_slot_occupancy(dispatch_station)
if is_cross_station:
    slot_number = occupancy["max_primary"] + occupancy["auxiliary"] + 1
    if occupancy["auxiliary"] >= occupancy["max_auxiliary"]:
        if not occupancy["allow_overflow"]:
            logger.info(f"[CAPACITY] {dispatch_station} at capacity, overflow disabled")
            # Continue to cloud fallback or return None
        else:
            slot_number = occupancy["total"] + 1
            logger.info(f"[CAPACITY] {dispatch_station} overflow dispatch slot {slot_number}")
else:
    slot_number = occupancy["primary"] + 1
```

**Step 2: Log capacity event after job INSERT**

After the INSERT INTO bridge_jobs (around line 2866), add capacity event logging:

```python
# Log capacity event (ADR-055)
cap_event_type = "primary_dispatch"
if is_cross_station:
    max_cap = occupancy.get("max_primary", 2) + occupancy.get("max_auxiliary", 1)
    cap_event_type = "auxiliary_filled" if slot_number <= max_cap else "overflow_dispatch"

self._log_capacity_event(
    station_code=dispatch_station,
    event_type=cap_event_type,
    agent_id=selected_agent_id,
    agent_name=agent_name,
    job_id=job_id,
    capability=cap_key,
    slot_number=slot_number,
    reason=f"{'cross-station' if is_cross_station else 'primary'} dispatch for {cap_key}",
    metadata={"module_source": module_source, "is_cross_station": is_cross_station}
)
```

**Step 3: Verify with a test dispatch**

```bash
docker compose restart archie_platform
```

Trigger a translation job from Languages tab, then check:

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT event_type, agent_name, capability, slot_number, created_at FROM station_capacity_events ORDER BY created_at DESC LIMIT 5"
```

Expected: Capacity event(s) from the test dispatch.

**Step 4: Commit**

```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat(dispatcher): capacity-aware job creation with slot tracking"
```

---

### Task 4: Dispatcher — Integrate Capacity Checks into `request_work()`

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py:1795-2126` (`request_work()` method)

Same pattern as Task 3, but for the real-time dispatch path (chat, bridge dispatch).

**Step 1: Add occupancy check before cross-station scan**

Around line 1867 (where cross-station fallback begins), add:

```python
occupancy = self._get_station_slot_occupancy(dispatch_station or capability_station)
```

**Step 2: Add capacity event logging at each dispatch outcome**

At each dispatch outcome point:
- After primary dispatch (around line 1856): log `primary_dispatch`
- After cross-station dispatch (around line 1920): log `auxiliary_filled` or `overflow_dispatch`
- After cloud dispatch (around line 1960): log `cloud_contractor`

Use `_log_capacity_event()` at each point with appropriate event_type and slot_number.

**Step 3: Verify and commit**

```bash
docker compose restart archie_platform
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat(dispatcher): capacity-aware request_work with overflow detection"
```

---

### Task 5: Telegram — Narrative Advisory Messages

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py:2518-2660` (`_telegram_dispatch_advisory()`)

**Step 1: Enhance cross_station advisory with narrative style and capacity context**

In the message building section for `cross_station` type (around lines 2546-2595), replace with narrative format that includes slot occupancy:

```python
if advisory_type == "cross_station":
    occ = self._get_station_slot_occupancy(dispatch_station)
    slots_used = occ["total"]
    max_cap = occ["max_primary"] + occ["max_auxiliary"]
    is_overflow = slots_used > max_cap
    station_label = dispatch_station or "unknown"
    agent_label = self._agent_display(agent_name)
    home_label = kwargs.get("agent_home_station", "another station")

    if is_overflow:
        msg = (
            f"Commander, {station_label} station is experiencing elevated request volume.\n\n"
            f"All {max_cap} slots are occupied. {agent_label} from {home_label} "
            f"dispatched as overflow (slot {slots_used}/{max_cap}) for {capability} task.\n\n"
            f"Module: {module_source or 'N/A'}"
        )
    else:
        msg = (
            f"Commander, {station_label} station needed assistance with {capability}.\n\n"
            f"{agent_label} from {home_label} is assisting as auxiliary "
            f"(slot {slots_used}/{max_cap}).\n\n"
            f"Module: {module_source or 'N/A'}"
        )
```

**Step 2: Allow capacity-related events through SILENT_CAPABILITIES**

At lines 2536-2543, the SILENT_CAPABILITIES set silences Telegram for translate jobs. For overflow events, bypass the silence:

```python
if capability in SILENT_CAPABILITIES and not kwargs.get("is_overflow"):
    return
```

**Step 3: Verify and commit**

```bash
docker compose restart archie_platform
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat(telegram): narrative station capacity advisories with overflow alerts"
```

---

### Task 6: Ops Terminal — AUXILIARY and CONTRACTOR Sections

**Files:**
- Modify: `platform_v2/static/js/consciousness.js:1782-1856` (`_renderOpsAgents()`)
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` (CSS)

**Step 1: Rewrite `_renderOpsAgents()` with three sections**

Replace the function at lines 1782-1856 with the new version that shows STATION CREW (count/max), AUXILIARY (count/max), and CONTRACTOR sections. The new version:

- Fetches station data including max_primary and max_auxiliary from `/tools/bridge/api/stations`
- Separates jobData into assists (cross-station, non-cloud) and contractors (cloud)
- Renders three sections with occupancy counts
- All dynamic values escaped with `escHtml()` (existing XSS-safe pattern)
- Updates ops terminal header with purple diamond when contractor active

**Step 2: Add CSS for agent badges**

In consciousness_dashboard.html CSS, add after existing `.cs-ops-agent-role` styles:

```css
.cs-ops-agent-badge {
    font-size: 0.58rem; font-weight: 700; letter-spacing: 0.06em;
    text-transform: uppercase; padding: 1px 6px; border-radius: 3px;
    flex-shrink: 0;
}
.cs-ops-agent-badge.working {
    background: rgba(16,185,129,0.15); color: #10b981;
}
```

**Step 3: Verify visually**

Navigate to Consciousness -> Languages tab. Verify:
- STATION CREW shows `(2/2)` with Jin Park and Amara Osei
- AUXILIARY shows `(0/1)` with "Slot available" in italic
- No CONTRACTOR section (since none active)

**Step 4: Commit**

```bash
git add platform_v2/static/js/consciousness.js platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat(ops-terminal): AUXILIARY and CONTRACTOR sections with slot counts"
```

---

### Task 7: Bridge Stations API — Expose Capacity Fields

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py` (the `/api/stations` endpoint)

**Step 1: Add capacity columns to the stations query SELECT**

Find the stations query and add: `bs.max_primary, bs.max_auxiliary, bs.allow_overflow`

Include in the response dict:
```python
station_dict["max_primary"] = row.get("max_primary", 2)
station_dict["max_auxiliary"] = row.get("max_auxiliary", 1)
```

**Step 2: Verify API returns new fields**

```bash
docker compose restart archie_platform
curl -s http://192.168.1.200:3000/tools/bridge/api/stations | python3 -m json.tool | grep -A2 max_primary
```

Expected: `"max_primary": 2, "max_auxiliary": 1` for each station.

**Step 3: Commit**

```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(bridge-api): expose station capacity fields in /api/stations"
```

---

### Task 8: Bridge CREW Tab — Match Three-Section Pattern

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html:8944-9060` (CREW tab renderer)

**Step 1: Add occupancy counts to section labels**

At line 8952-8953 (ASSIGNED CREW label): add count from agents.length and maxPrimary from zone data.

At line 9047-9051 (ASSISTING CREW label): rename to AUXILIARY, add count/max, and separate cloud helpers into CONTRACTOR section.

**Step 2: Pass capacity data into zone data object**

Where zone data is assembled from station API data, add:
```javascript
zd.maxPrimary = stationData.max_primary || 2;
zd.maxAuxiliary = stationData.max_auxiliary || 1;
```

**Step 3: Add CONTRACTOR subsection for cloud jobs**

After the helpers loop, filter for cloud helpers and render them under a separate CONTRACTOR label with purple styling.

**Step 4: Verify visually**

Navigate to Bridge Command, click any station, check CREW tab shows the three sections.

**Step 5: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): CREW tab shows AUXILIARY/CONTRACTOR sections with capacity counts"
```

---

### Task 9: Capacity Event Logging on Job Completion

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py` (find job completion logic where status changes to completed/failed)

**Step 1: Log `slot_freed` event when a bridge_job completes**

Find where bridge_jobs status is updated to completed or failed. Add:

```python
self._log_capacity_event(
    station_code=job_station_code,
    event_type="slot_freed",
    agent_id=job_agent_id,
    agent_name=job_agent_name,
    job_id=job_id,
    capability=job_type,
    reason=f"Job {status} - slot freed"
)
```

**Step 2: Verify**

Run a translation job, wait for completion, then:

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT event_type, agent_name, slot_number, reason, created_at FROM station_capacity_events ORDER BY created_at DESC LIMIT 10"
```

Expected: Both dispatch and slot_freed events visible.

**Step 3: Commit**

```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat(dispatcher): log slot_freed capacity events on job completion"
```

---

### Task 10: Integration Test — End-to-End Capacity Flow

**Step 1: Trigger a translation job and verify the full flow**

From Consciousness Languages tab, click GENERATE ALL. Verify:
1. `create_job()` dispatches (primary or cross-station)
2. Capacity event logged in station_capacity_events
3. Ops terminal shows agent in correct section
4. Job completes and slot_freed event logged

**Step 2: Check capacity events**

```bash
docker exec archie_database psql -U archie -d archie -c "
  SELECT event_type, agent_name, capability, slot_number, reason,
         to_char(created_at, 'HH24:MI:SS') as time
  FROM station_capacity_events
  ORDER BY created_at DESC LIMIT 10"
```

**Step 3: Check slot occupancy view**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT * FROM v_station_slot_occupancy"
```

**Step 4: Take screenshots for visual verification**

**Step 5: Final commit if any fixups needed**

```bash
git add -A
git commit -m "fix: phase 1 capacity enforcement integration adjustments"
```

---

## Summary of Commits

| # | Commit Message | Files |
|---|---------------|-------|
| 1 | `feat: migration 122 - station capacity schema` | `database/migrations/122_station_capacity.sql` |
| 2 | `feat(dispatcher): slot occupancy counting + event logging` | `ai_bridge/bridge_dispatcher.py` |
| 3 | `feat(dispatcher): capacity-aware job creation` | `ai_bridge/bridge_dispatcher.py` |
| 4 | `feat(dispatcher): capacity-aware request_work` | `ai_bridge/bridge_dispatcher.py` |
| 5 | `feat(telegram): narrative capacity advisories` | `ai_bridge/bridge_dispatcher.py` |
| 6 | `feat(ops-terminal): AUXILIARY/CONTRACTOR sections` | `consciousness.js`, `consciousness_dashboard.html` |
| 7 | `feat(bridge-api): expose capacity fields` | `bridge/routes.py` |
| 8 | `feat(bridge): CREW tab capacity sections` | `bridge.html` |
| 9 | `feat(dispatcher): slot_freed events on completion` | `ai_bridge/bridge_dispatcher.py` |
| 10 | Integration verification (fixups if needed) | various |
