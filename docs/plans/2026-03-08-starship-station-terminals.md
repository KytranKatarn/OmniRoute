# Starship Station Terminals — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace Starship Command's station toggle grid with two full StationOps terminals (OPERATIONS + ENGINEERING) showing each node's local crew and mesh-loaned agents, matching the Consciousness module's visual style.

**Architecture:** Reuse existing `StationOps` class with a new `dataUrl` config param so it fetches from a custom endpoint instead of Bridge's default `/tools/bridge/api/stations`. New endpoint returns node crew in StationOps-compatible format. Migration pre-populates the two stations for existing approved nodes.

**Tech Stack:** Flask (starship/routes.py), PostgreSQL (node_agents, node_station_assignments, mesh_agent_loans), StationOps (station-ops.js/css), Vanilla JS (starship.html)

**Security Note:** All dynamic content rendered via StationOps built-in `escHtml()` helper. No raw innerHTML.

**Dev HQ:** Project #120, linked to station terminals design

---

### Task 1: Migration 142 — Pre-populate OPERATIONS + ENGINEERING stations

**Files:**
- Create: `database/migrations/142_starship_default_stations.sql`

**What to build:**

```sql
-- Migration 142: Pre-populate OPERATIONS + ENGINEERING for approved starship nodes
-- Idempotent: ON CONFLICT DO NOTHING

INSERT INTO node_station_assignments (node_id, station_id, is_active)
SELECT rn.id, bs.id, true
FROM remote_nodes rn
CROSS JOIN bridge_stations bs
WHERE rn.status = 'approved'
  AND bs.station_code IN ('OPERATIONS', 'ENGINEERING')
  AND bs.is_active = true
ON CONFLICT DO NOTHING;
```

Test: Run migration, verify KYTRAN-StarShip has OPERATIONS + ENGINEERING in node_station_assignments.

```bash
docker exec archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/migrations/142_starship_default_stations.sql
docker exec archie_database psql -U archie -d archie -c "SELECT nsa.id, bs.station_code, nsa.is_active FROM node_station_assignments nsa JOIN bridge_stations bs ON bs.id = nsa.station_id JOIN remote_nodes rn ON rn.id = nsa.node_id WHERE rn.status = 'approved';"
```

Commit: `feat(starship): migration 142 — pre-populate OPERATIONS + ENGINEERING for approved nodes`

---

### Task 2: Add `dataUrl` config param to StationOps class

**Files:**
- Modify: `platform_v2/static/js/station-ops.js`

**What to change:**

In the constructor (line 43-56), add one new config param:

```javascript
this.dataUrl = config.dataUrl || null;  // Custom data URL (overrides default Bridge API)
```

In `renderAgents` method (line 65), change the fetch URL logic. Currently it fetches from `"/tools/bridge/api/stations"`. Wrap it:

```javascript
// At line 65, change:
//   fetch("/tools/bridge/api/stations")
// To:
var agentUrl = this.dataUrl || "/tools/bridge/api/stations";
fetch(agentUrl)
```

The response format from the custom dataUrl must match what StationOps expects. The existing code at lines 71-87 processes the station data by finding the matching station by `station_code` and extracting `assigned_agents`. The custom endpoint must return the same structure.

**Important:** The `renderAgents` method at line 65 does:
1. Fetches stations list
2. Finds station matching `this.stationCode`
3. Reads `station.assigned_agents` array (each has `first_name`, `last_name`, `name`, `title`, `assignment_type`)
4. Reads `station.assists` array (cross-station/mesh agents in auxiliary slot)
5. Reads `station.contractors` array (cloud agents)

The custom endpoint must return this exact shape. Also update the jobs fetch — if `dataUrl` is set, jobs should come from the same custom endpoint's `jobs` field rather than the Bridge jobs API. Add:

```javascript
// In renderJobs (line 301 area), if dataUrl is set, skip the Bridge fetch
// and use jobs data passed from renderAgents instead
```

Actually, the simplest approach: when `dataUrl` is set, the custom endpoint returns everything in one payload. Modify `render()` (line 291) to do a single fetch when `dataUrl` is set:

```javascript
StationOps.prototype.render = function(jobData) {
    if (this.dataUrl) {
        // Custom mode: single fetch returns crew + jobs together
        var self = this;
        fetch(this.dataUrl)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.stations) {
                    self._renderFromData(data);
                }
            })
            .catch(function(e) { console.error("StationOps fetch error:", e); });
        return;
    }
    // Default Bridge mode (existing behavior)
    this.renderAgents(jobData);
    this.renderJobs();
    this.renderCommands();
};
```

Add a new `_renderFromData(data)` method that processes the custom endpoint response:

```javascript
StationOps.prototype._renderFromData = function(data) {
    // Find our station in the response
    var station = null;
    for (var i = 0; i < data.stations.length; i++) {
        if (data.stations[i].station_code === this.stationCode) {
            station = data.stations[i];
            break;
        }
    }
    if (!station) return;

    // Render crew using same logic as renderAgents
    var el = document.getElementById(this.agentsElId);
    if (!el) return;
    el.textContent = '';

    var crew = station.assigned_agents || [];
    var assists = station.assists || [];
    var maxAux = 1;

    // Primary + Secondary slots (same rendering as lines 149-177)
    var labels = ["PRIMARY", "SECONDARY"];
    var colors = ["#10b981", "#3b82f6"];
    for (var s = 0; s < 2; s++) {
        var agent = crew[s] || null;
        var row = document.createElement("div");
        row.className = "stn-ops-agent-row";
        // ... (same DOM construction as existing renderAgents)
        // Build indicator, label badge, name, title, status dot
        // Use StationOps.escHtml() for all text content
        el.appendChild(row);
    }

    // Auxiliary slot (same rendering as lines 180-196)
    var auxAgent = assists[0] || null;
    // ... (same DOM construction)

    // Capacity check
    var busyCrew = crew.filter(function(a) { return a && a.status === "active"; }).length;
    var atCapacity = (busyCrew >= crew.length && crew.length > 0) && (assists.length >= maxAux);
    // Update status element
    var statusEl = document.getElementById(this.statusElId);
    if (statusEl) {
        statusEl.textContent = atCapacity ? "AT CAPACITY" : "ONLINE";
        statusEl.className = "stn-ops-status " + (atCapacity ? "stn-ops-capacity" : "stn-ops-online");
    }

    // Render jobs
    var jobsEl = document.getElementById(this.jobsElId);
    if (jobsEl) {
        var jobs = station.jobs || [];
        jobsEl.textContent = '';
        if (jobs.length === 0) {
            var empty = document.createElement("div");
            empty.className = "stn-ops-empty";
            empty.textContent = "No active jobs";
            jobsEl.appendChild(empty);
        }
        // ... render job progress bars same as existing renderJobs
    }

    // No commands for now (skip renderCommands)
};
```

**Simpler alternative** (RECOMMENDED): Rather than duplicating all the DOM construction, refactor `renderAgents` to accept data as a parameter. If data is passed, use it directly instead of fetching. This is less code:

```javascript
// Change renderAgents signature at line 65:
StationOps.prototype.renderAgents = function(jobData, stationData) {
    var self = this;
    if (stationData) {
        // Use provided data directly
        self._processStationData(stationData, jobData);
        return;
    }
    // Existing fetch logic...
    fetch("/tools/bridge/api/stations")
        .then(...)
};

// Extract processing into _processStationData (move lines 71-210 logic)
```

**Actually, simplest approach:** Keep changes minimal. Just add `dataUrl` to constructor and modify the fetch URL in `renderAgents`. The custom endpoint returns the same format Bridge does. This is the least invasive change.

Final implementation — just these 2 changes to station-ops.js:

1. **Constructor** (after line 53): `this.dataUrl = config.dataUrl || null;`
2. **renderAgents fetch** (line 65): `var url = this.dataUrl || "/tools/bridge/api/stations"; fetch(url)`

The custom endpoint must return `{stations: [{station_code, assigned_agents, assists, contractors}]}` — same shape as Bridge.

Test: Existing Consciousness/Bridge station terminals still work (no dataUrl = unchanged behavior).

Commit: `feat(station-ops): add optional dataUrl config param for custom data sources`

---

### Task 3: Backend — `GET /api/nodes/<node_id>/stations-live` endpoint

**Files:**
- Modify: `platform_v2/tools/starship/routes.py` (add after line 729, before NODE SETUP section at ~732)

**New endpoint:**

```python
@starship_bp.route("/api/nodes/<int:node_id>/stations-live")
@login_required
def api_node_stations_live(node_id):
    """Return node's crew in StationOps-compatible format for terminal rendering."""
    with get_db_cursor() as (conn, cur):
        # Get node info
        cur.execute("SELECT id, node_id FROM remote_nodes WHERE id = %s", (node_id,))
        node = cur.fetchone()
        if not node:
            return jsonify({"error": "Node not found"}), 404

        # Get node's enabled stations
        cur.execute("""
            SELECT bs.station_code, bs.station_name, bs.color, bs.icon,
                   nsa.is_active
            FROM node_station_assignments nsa
            JOIN bridge_stations bs ON bs.id = nsa.station_id
            WHERE nsa.node_id = %s AND nsa.is_active = true
            ORDER BY bs.position_row, bs.position_order
        """, (node_id,))
        enabled_stations = cur.fetchall()

        stations = []
        for st in enabled_stations:
            code = st["station_code"]

            # Get primary/secondary agents for this station
            cur.execute("""
                SELECT na.id, na.name, na.display_name, na.title, na.model,
                       na.status, na.station_codes
                FROM node_agents na
                WHERE na.node_id = %s AND na.status = 'active'
                  AND %s = ANY(na.station_codes)
                ORDER BY na.id
                LIMIT 2
            """, (node_id, code))
            crew = cur.fetchall()

            # Build assigned_agents in StationOps format
            assigned_agents = []
            assignment_labels = ["primary", "secondary"]
            for i, agent in enumerate(crew):
                # Parse display_name into first/last
                parts = (agent["display_name"] or agent["name"] or "Unknown").split(" ", 1)
                first_name = parts[0]
                last_name = parts[1] if len(parts) > 1 else ""
                assigned_agents.append({
                    "first_name": first_name,
                    "last_name": last_name,
                    "name": agent["name"],
                    "title": agent["title"] or assignment_labels[i] if i < 2 else "crew",
                    "assignment_type": assignment_labels[i] if i < 2 else "crew",
                    "status": "active" if agent["status"] == "active" else "paused"
                })

            # Get mesh-loaned agents (auxiliary slot)
            cur.execute("""
                SELECT mal.id, na.name, na.display_name, na.title,
                       mal.task_description
                FROM mesh_agent_loans mal
                LEFT JOIN node_agents na ON na.id = mal.agent_id
                WHERE mal.target_node_id = %s AND mal.status = 'active'
                LIMIT 1
            """, (node["node_id"],))
            loan = cur.fetchone()

            assists = []
            if loan:
                parts = ((loan["display_name"] or loan["name"] or "Helper").split(" ", 1))
                assists.append({
                    "first_name": parts[0],
                    "last_name": parts[1] if len(parts) > 1 else "",
                    "name": loan["name"] or "mesh-assist",
                    "title": "MESH ASSIST",
                    "assignment_type": "auxiliary",
                    "status": "active"
                })

            # Get jobs for this station on this node (from bridge_jobs)
            cur.execute("""
                SELECT bj.id, bj.agent_name, bj.station_code, bj.job_type,
                       bj.status, bj.description, bj.completed_steps, bj.total_steps
                FROM bridge_jobs bj
                WHERE bj.node_id = %s AND bj.station_code = %s
                  AND bj.status = 'running'
                ORDER BY bj.created_at DESC
                LIMIT 5
            """, (node["node_id"], code))
            jobs_raw = cur.fetchall()

            jobs = []
            for j in jobs_raw:
                total = j["total_steps"] or 1
                completed = j["completed_steps"] or 0
                jobs.append({
                    "id": j["id"],
                    "agent_name": j["agent_name"],
                    "station_code": j["station_code"],
                    "job_type": j["job_type"],
                    "status": j["status"],
                    "description": j["description"],
                    "progress_pct": round((completed / total) * 100),
                    "completed_steps": completed,
                    "total_steps": total,
                    "failed_steps": 0
                })

            stations.append({
                "station_code": code,
                "station_name": st["station_name"],
                "color": st["color"],
                "assigned_agents": assigned_agents,
                "assists": assists,
                "contractors": [],
                "jobs": jobs
            })

        return jsonify({"stations": stations})
```

**Note:** The `bridge_jobs` table may not have a `node_id` column. If not, the jobs query should be omitted or return empty (jobs will be empty for now per the design — "no commands for now" implies no node-local jobs yet). Check the schema and adjust. Safe fallback: return `"jobs": []` for each station.

Test: `curl http://192.168.1.200:3000/tools/starship/api/nodes/1/stations-live` — should return OPERATIONS and ENGINEERING stations with crew from node_agents.

Commit: `feat(starship): add stations-live endpoint for StationOps terminal data`

---

### Task 4: Frontend — Replace Stations tab with StationOps terminals

**Files:**
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html`

**4a. Add CSS/JS includes (in `<head>` or before closing `</body>`):**

Add after existing CSS includes:
```html
<link rel="stylesheet" href="/static/css/station-ops.css">
```

Add after existing JS includes:
```html
<script src="/static/js/station-ops.js"></script>
```

**4b. Replace Stations tab HTML (lines 431-443):**

Replace the entire `#panel-stations` content:

```html
<!-- STATIONS TAB -->
<div class="sc-panel" id="panel-stations">
    <div style="display:flex; gap:1.5rem; flex-wrap:wrap;">
        <!-- OPERATIONS Terminal -->
        <div class="stn-ops-terminal" style="flex:1; min-width:320px;">
            <div class="stn-ops-header">
                <div class="stn-ops-header-bar" style="background:#00e5ff;"></div>
                <span class="stn-ops-title">OPERATIONS</span>
                <span class="stn-ops-status" id="ops-status">OFFLINE</span>
            </div>
            <div class="stn-ops-section">
                <div class="stn-ops-section-label">CREW ROSTER</div>
                <div id="ops-agents"></div>
            </div>
            <div class="stn-ops-section">
                <div class="stn-ops-section-label">ACTIVE JOBS</div>
                <div id="ops-jobs"></div>
            </div>
        </div>
        <!-- ENGINEERING Terminal -->
        <div class="stn-ops-terminal" style="flex:1; min-width:320px;">
            <div class="stn-ops-header">
                <div class="stn-ops-header-bar" style="background:#00e5ff;"></div>
                <span class="stn-ops-title">ENGINEERING</span>
                <span class="stn-ops-status" id="eng-status">OFFLINE</span>
            </div>
            <div class="stn-ops-section">
                <div class="stn-ops-section-label">CREW ROSTER</div>
                <div id="eng-agents"></div>
            </div>
            <div class="stn-ops-section">
                <div class="stn-ops-section-label">ACTIVE JOBS</div>
                <div id="eng-jobs"></div>
            </div>
        </div>
    </div>
</div>
```

**4c. Add StationOps initialization JS (after existing JS functions, ~line 879 area):**

```javascript
// Station terminal instances
var opsTerminal = null;
var engTerminal = null;

function initStationTerminals(nodeDbId) {
    if (!nodeDbId) return;
    var dataUrl = '/tools/starship/api/nodes/' + nodeDbId + '/stations-live';

    opsTerminal = new StationOps({
        stationCode: 'OPERATIONS',
        moduleSource: 'starship',
        agentsElId: 'ops-agents',
        jobsElId: 'ops-jobs',
        statusElId: 'ops-status',
        dataUrl: dataUrl,
        commands: []
    });

    engTerminal = new StationOps({
        stationCode: 'ENGINEERING',
        moduleSource: 'starship',
        agentsElId: 'eng-agents',
        jobsElId: 'eng-jobs',
        statusElId: 'eng-status',
        dataUrl: dataUrl,
        commands: []
    });

    opsTerminal.render();
    engTerminal.render();
}
```

**4d. Wire into node selection and tab switching:**

In `selectNode()` (line 714), after `selectedNodeDbId = data.node.db_id || null;`, add:
```javascript
initStationTerminals(selectedNodeDbId);
```

In `switchTab()`, when stations tab is selected, re-render:
```javascript
case 'stations':
    if (opsTerminal) opsTerminal.render();
    if (engTerminal) engTerminal.render();
    break;
```

**4e. Remove old station toggle grid rendering** from `renderDetail()` (lines 821-858). The toggle grid JS that builds `sc-station-card` elements is no longer needed for the Stations tab. Keep the `toggleStation()` function (lines 1307-1327) — it may still be useful, or remove it if not referenced elsewhere.

Test:
1. Select a node in Starship Command
2. Click Stations tab
3. Should see two LCARS terminals side-by-side: OPERATIONS and ENGINEERING
4. Each shows crew from node_agents with PRIMARY/SECONDARY slots
5. Auxiliary slot shows mesh-loaned agent if any active loans exist
6. No JS console errors

Commit: `feat(starship): replace station grid with StationOps terminals for OPERATIONS + ENGINEERING`

---

### Task 5: Integration Test & Deploy

1. Run migration 142:
```bash
docker exec archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/migrations/142_starship_default_stations.sql
```

2. Restart platform:
```bash
docker compose restart archie_platform
```

3. Verify checklist:
   - KYTRAN-StarShip has OPERATIONS + ENGINEERING in node_station_assignments
   - `/api/nodes/1/stations-live` returns both stations with crew
   - Starship > select node > Stations tab shows 2 LCARS terminals
   - Crew names match node_agents for that node
   - Existing Bridge/Consciousness station terminals unchanged (no regression)
   - No JS errors in console

4. Push to origin/main

5. Update Dev HQ: complete related tasks, log decisions

Commit: N/A (testing only)
