# Starship Command Refactor — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor Starship Command from 6 tabs to 3, add Starbase card, fix 6 bugs, delete ~278 lines of dead routes.

**Architecture:** Landing page shows Starbase (hub) card at top + fleet node cards below. Node detail panel has 3 tabs: STATUS, OTA/SYNC, CREW. Dead routes (privacy, stations, profile) deleted. New install endpoint serves OS-appropriate scripts. All write endpoints get ownership checks.

**Tech Stack:** Flask/Jinja2, PostgreSQL (psycopg2), vanilla JS, LCARS CSS

**Spec:** `docs/superpowers/specs/2026-03-12-starship-command-refactor-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `platform_v2/tools/starship/routes.py` | Modify | Delete 6 routes, add 2 new routes, fix bugs in 8 existing routes |
| `platform_v2/tools/starship/templates/tools/starship/starship.html` | Modify | Replace 6-tab layout with Starbase card + 3-tab node detail |
| `platform_v2/tools/bridge/routes.py` | Modify | Fix `user_id` → `registered_by` bug (1 line) |

No new files. No migrations. No new dependencies.

---

## Chunk 1: Backend — Route Cleanup + Bug Fixes

### Task 1: Delete Dead Routes from routes.py

**Files:**
- Modify: `platform_v2/tools/starship/routes.py:621-898`

These 6 route functions are being deleted (tabs removed per spec):

| Function | Lines | Tab |
|----------|-------|-----|
| `api_update_profile()` | 621-641 | PROFILE (replaced by new PUT /settings) |
| `api_update_privacy()` | 643-669 | PRIVACY |
| `api_node_privacy()` | 671-711 | PRIVACY |
| `api_toggle_agent_access()` | 713-740 | PRIVACY |
| `api_toggle_station()` | 742-785 | STATIONS |
| `api_node_stations_live()` | 787-898 | STATIONS |

- [ ] **Step 1: Delete the 6 dead route functions**

Delete lines 621-898 in `routes.py` — all 6 functions listed above. These are contiguous (~278 lines).

- [ ] **Step 2: Verify no internal references to deleted routes**

Run:
```bash
cd /mnt/archie_brain && grep -rn "api_update_profile\|api_update_privacy\|api_node_privacy\|api_toggle_agent_access\|api_toggle_station\|api_node_stations_live" platform_v2/tools/starship/
```
Expected: Only matches in the template JS (cleaned up in Task 6). No Python imports or cross-references.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/starship/routes.py
git commit -m "refactor(starship): delete 6 dead routes (~278 lines — privacy, stations, profile)"
```

---

### Task 2: Add New `PUT /api/nodes/<node_id>/settings` Route

**Files:**
- Modify: `platform_v2/tools/starship/routes.py` (insert after `api_node_status` function)

This replaces the deleted `POST /profile` route. Allows inline editing of node name, deployment mode, and priority from the STATUS tab.

- [ ] **Step 1: Add the new settings endpoint**

Insert after the `api_node_status()` function (which ends around line 619 after Task 1's deletion):

```python
@starship_bp.route("/api/nodes/<node_id>/settings", methods=["PUT"])
@login_required
def api_update_node_settings(node_id):
    """Update node name, deployment mode, and priority (inline edit from STATUS tab)."""
    user_id = current_user.id
    node = _get_node_for_user(node_id, user_id)
    if not node:
        return jsonify({"success": False, "error": "Node not found"}), 404

    data = request.get_json() or {}

    updates = []
    params = []
    if "node_name" in data:
        name = data["node_name"].strip()
        if not name or len(name) > 100:
            return jsonify({"success": False, "error": "Invalid name"}), 400
        updates.append("node_name = %s")
        params.append(name)
    if "deployment_mode" in data:
        mode = data["deployment_mode"]
        if mode not in ("starship", "satellite", "outpost"):
            return jsonify({"success": False, "error": "Invalid mode"}), 400
        updates.append("deployment_mode = %s")
        params.append(mode)
    if "bridge_priority" in data:
        try:
            prio = int(data["bridge_priority"])
            prio = max(0, min(100, prio))
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Invalid priority"}), 400
        updates.append("bridge_priority = %s")
        params.append(prio)

    if not updates:
        return jsonify({"success": False, "error": "No fields to update"}), 400

    params.append(node_id)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE remote_nodes SET {', '.join(updates)} WHERE node_id = %s",
            params,
        )
    return jsonify({"success": True})
```

- [ ] **Step 2: Verify route is syntactically correct**

```bash
docker exec archie_platform python3 -c "from tools.starship.routes import starship_bp; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/starship/routes.py
git commit -m "feat(starship): add PUT /settings endpoint for inline node editing"
```

---

### Task 3: Add New `GET /install` Endpoint (Bug Fix 1)

**Files:**
- Modify: `platform_v2/tools/starship/routes.py` (insert near request-node routes)

This is the missing install endpoint that the Add Node onboarding generates URLs for. Token-authenticated, no login required, returns OS-appropriate install scripts.

- [ ] **Step 1: Add the install endpoint**

Insert after the `api_setup_instructions()` function:

```python
@starship_bp.route("/install")
def starship_install_script():
    """Serve OS-appropriate install script authenticated by setup token.

    PowerShell (irm) → deploy-node.ps1 content
    Bash (curl)      → install.sh content
    No login required — token authenticates.
    """
    from flask import Response

    token = request.args.get("token", "").strip()
    if not token:
        return Response("Error: missing token parameter\n", mimetype="text/plain", status=400)

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT node_id, node_name, setup_token FROM remote_nodes WHERE setup_token = %s",
            (token,),
        )
        node = cur.fetchone()
        if not node:
            return Response("Error: invalid or expired token\n", mimetype="text/plain", status=403)

    hub_url = os.environ.get("STARSHIP_HUB_URL", "https://archie.kytranempowerment.com")
    node_id = node["node_id"]

    ua = (request.headers.get("User-Agent") or "").lower()
    is_powershell = "powershell" in ua or "windowspowershell" in ua

    if is_powershell:
        script = _generate_powershell_installer(hub_url, node_id, token)
        return Response(script, mimetype="text/plain", status=200)
    else:
        script = _generate_bash_installer(hub_url, node_id, token)
        return Response(script, mimetype="text/plain", status=200)


def _generate_bash_installer(hub_url, node_id, token):
    """Generate bash install script with credentials injected."""
    return f"""#!/bin/bash
set -e
echo "=== A.R.C.H.I.E. Starship Node Installer ==="
echo "Hub: {hub_url}"
echo "Node: {node_id}"

# Download node package
curl -fsSL "{hub_url}/starship/download/node-package" -o archie-node.tar.gz

# Extract
mkdir -p archie-node && tar xzf archie-node.tar.gz -C archie-node --strip-components=1
cd archie-node

# Write .env
cat > .env << 'ENVEOF'
HUB_URL={hub_url}
NODE_ID={node_id}
HUB_API_KEY={token}
ENVEOF

# Detect timezone
if [ -f /etc/timezone ]; then
    TZ=$(cat /etc/timezone)
elif [ -L /etc/localtime ]; then
    TZ=$(readlink /etc/localtime | sed 's|.*/zoneinfo/||')
else
    TZ="UTC"
fi
echo "NODE_TIMEZONE=$TZ" >> .env

echo "Starting containers..."
docker compose -f docker-compose.node.yml up -d

echo ""
echo "=== Installation complete ==="
echo "Node API: http://localhost:3001/health"
"""


def _generate_powershell_installer(hub_url, node_id, token):
    """Generate PowerShell install script with credentials injected."""
    return f"""# A.R.C.H.I.E. Starship Node Installer
Write-Host "=== A.R.C.H.I.E. Starship Node Installer ===" -ForegroundColor Cyan
Write-Host "Hub: {hub_url}"
Write-Host "Node: {node_id}"

# Download node package
$ProgressPreference = 'SilentlyContinue'
Invoke-WebRequest -Uri "{hub_url}/starship/download/node-package" -OutFile archie-node.tar.gz

# Extract
New-Item -ItemType Directory -Force -Path archie-node | Out-Null
tar xzf archie-node.tar.gz -C archie-node --strip-components=1
Set-Location archie-node

# Write .env
@"
HUB_URL={hub_url}
NODE_ID={node_id}
HUB_API_KEY={token}
NODE_TIMEZONE=$((Get-TimeZone).Id)
"@ | Set-Content .env

Write-Host "Starting containers..." -ForegroundColor Yellow
docker compose -f docker-compose.node.yml up -d

Write-Host ""
Write-Host "=== Installation complete ===" -ForegroundColor Green
Write-Host "Node API: http://localhost:3001/health"
"""
```

- [ ] **Step 2: Verify syntax**

```bash
docker exec archie_platform python3 -c "from tools.starship.routes import starship_bp; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/starship/routes.py
git commit -m "feat(starship): add GET /install endpoint for token-based node setup"
```

---

### Task 4: Fix Bug 3 — `user_id` Column in bridge/routes.py

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py:370`

- [ ] **Step 1: Fix the column reference**

Change line 370 from:
```python
                WHERE user_id = %s AND deployment_mode = 'starship' AND is_active = true
```
to:
```python
                WHERE registered_by = %s AND deployment_mode = 'starship' AND is_active = true
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "fix(bridge): user_id → registered_by in get_starship_node_for_user()"
```

---

### Task 5: Fix Bug 4 — Claim Orphan Nodes + Bug 6 — NULL Descriptions

**Files:**
- Modify: `platform_v2/tools/starship/routes.py` — `_get_node_for_user()` (line ~335 before deletions) and `api_model_catalog()` (line ~900 before deletions; ~624 after Task 1 deletes 278 lines)

- [ ] **Step 1: Add atomic claim to `_get_node_for_user()`**

Replace the `_get_node_for_user` function body. When `require_owner=True` and the node has `registered_by IS NULL`, atomically claim it for the requesting user:

```python
def _get_node_for_user(node_id, user_id, require_owner=True):
    """Get a specific node, verifying ownership.
    Nodes with NULL registered_by are atomically claimed on first access."""
    with get_db_cursor(commit=True) as (conn, cur):
        if require_owner:
            # Try to claim orphan nodes atomically
            cur.execute(
                """UPDATE remote_nodes SET registered_by = %s
                   WHERE node_id = %s AND registered_by IS NULL""",
                (user_id, node_id),
            )
            cur.execute(
                """SELECT * FROM remote_nodes
                   WHERE node_id = %s AND registered_by = %s""",
                (node_id, user_id),
            )
        else:
            cur.execute("SELECT * FROM remote_nodes WHERE node_id = %s", (node_id,))
        return cur.fetchone()
```

- [ ] **Step 2: Fix NULL descriptions in model catalog**

In `api_model_catalog()`, change:
```python
"SELECT * FROM model_catalog WHERE is_active = true AND category = %s ORDER BY size_gb"
```
to:
```python
"SELECT id, name, COALESCE(description, '') as description, category, size_gb, quantization, is_active FROM model_catalog WHERE is_active = true AND category = %s ORDER BY size_gb"
```

And the non-filtered query similarly:
```python
"SELECT id, name, COALESCE(description, '') as description, category, size_gb, quantization, is_active FROM model_catalog WHERE is_active = true ORDER BY category, size_gb"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/starship/routes.py
git commit -m "fix(starship): claim orphan nodes atomically + COALESCE NULL catalog descriptions"
```

---

### Task 6: Fix Bug 5 — Add Ownership Checks to Write Endpoints

**Files:**
- Modify: `platform_v2/tools/starship/routes.py` — 6 functions

These write endpoints currently lookup nodes by integer `id` without verifying the requesting user owns them. Add `_get_node_for_user()` call at the start of each.

The pattern for each is the same — replace the raw `SELECT id, node_id FROM remote_nodes WHERE id = %s` with the ownership-checking helper. Since these use integer DB `id` but `_get_node_for_user` uses string `node_id`, we need a small adapter.

- [ ] **Step 1: Add integer-ID ownership helper**

Add this helper near `_get_node_for_user`:

```python
def _get_node_for_user_by_int_id(int_id, user_id):
    """Get a node by its integer DB id, verifying ownership."""
    with get_db_cursor(commit=True) as (conn, cur):
        # Claim orphan if needed
        cur.execute(
            """UPDATE remote_nodes SET registered_by = %s
               WHERE id = %s AND registered_by IS NULL""",
            (user_id, int_id),
        )
        cur.execute(
            """SELECT * FROM remote_nodes
               WHERE id = %s AND registered_by = %s""",
            (int_id, user_id),
        )
        return cur.fetchone()
```

- [ ] **Step 2: Add ownership check to `api_update_node_agent()`**

At the start of the function (after `data` check), add:
```python
    user_id = current_user.id
    node = _get_node_for_user_by_int_id(node_id, user_id)
    if not node:
        return jsonify({"success": False, "error": "Node not found"}), 404
```

- [ ] **Step 3: Add ownership check to `api_add_agent_to_node()`**

Replace the raw node lookup:
```python
            cur.execute(
                "SELECT id, node_id FROM remote_nodes WHERE id = %s",
                (node_id,),
            )
            node = cur.fetchone()
            if not node:
                return jsonify({"success": False, "error": "Node not found"}), 404
```
with:
```python
    node = _get_node_for_user_by_int_id(node_id, current_user.id)
    if not node:
        return jsonify({"success": False, "error": "Node not found"}), 404
```
(Move it before the `with get_db_cursor` block since the helper has its own cursor.)

- [ ] **Step 4: Add ownership check to `api_remove_agent_from_node()`**

At the start:
```python
    node = _get_node_for_user_by_int_id(node_id, current_user.id)
    if not node:
        return jsonify({"success": False, "error": "Node not found"}), 404
```

- [ ] **Step 5: Add ownership check to `api_push_agent_config()`**

Replace the raw node lookup with:
```python
    node = _get_node_for_user_by_int_id(node_id, current_user.id)
    if not node:
        return jsonify({"success": False, "error": "Node not found"}), 404
    node_id_str = node["node_id"]
```

- [ ] **Step 6: Add ownership check to `api_pull_model()`**

Same pattern — replace raw lookup.

- [ ] **Step 7: Add ownership check to `api_push_code_update()`**

Same pattern — replace raw lookup.

- [ ] **Step 8: Verify syntax**

```bash
docker exec archie_platform python3 -c "from tools.starship.routes import starship_bp; print('OK')"
```

- [ ] **Step 9: Commit**

```bash
git add platform_v2/tools/starship/routes.py
git commit -m "fix(starship): add ownership checks to all write endpoints"
```

---

## Chunk 2: Frontend — Template Refactor

### Task 7: Replace Landing Page with Starbase Card + Fleet Grid

**Files:**
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html`

The current landing page just shows fleet node cards. We need to add a Starbase (hub) card at the top that shows live stats from ARCHIE itself.

- [ ] **Step 1: Add Starbase card HTML**

Before the existing fleet grid (`<div class="sc-fleet-grid">`), insert the Starbase card section:

```html
<!-- ── STARBASE (HUB) ── -->
<div class="sc-starbase-card" id="starbase-card">
    <div class="sc-node-header" style="cursor:default;">
        <div class="sc-node-dot online"></div>
        <span class="sc-node-name">A.R.C.H.I.E. STARBASE</span>
        <span class="sc-node-mode">HUB</span>
    </div>
    <div class="sc-node-body">
        <div class="sc-node-stats" id="starbase-stats">
            <div class="sc-stat"><span class="sc-stat-val" id="sb-agents">--</span><span class="sc-stat-label">AGENTS</span></div>
            <div class="sc-stat"><span class="sc-stat-val" id="sb-jobs">--</span><span class="sc-stat-label">ACTIVE JOBS</span></div>
            <div class="sc-stat"><span class="sc-stat-val" id="sb-models">--</span><span class="sc-stat-label">MODELS</span></div>
            <div class="sc-stat"><span class="sc-stat-val" id="sb-stations">10</span><span class="sc-stat-label">STATIONS</span></div>
        </div>
        <div class="sc-node-stats" style="margin-top:10px;">
            <div class="sc-stat"><span class="sc-stat-val" id="sb-cpu">--</span><span class="sc-stat-label">CPU</span></div>
            <div class="sc-stat"><span class="sc-stat-val" id="sb-ram">--</span><span class="sc-stat-label">RAM</span></div>
            <div class="sc-stat"><span class="sc-stat-val" id="sb-gpu">--</span><span class="sc-stat-label">GPU</span></div>
        </div>
    </div>
</div>
```

- [ ] **Step 2: Add Starbase CSS**

In the `<style>` block, add:

```css
.sc-starbase-card {
    background: rgba(0, 0, 0, 0.4);
    border: 1px solid rgba(0, 229, 255, 0.3);
    border-radius: 8px;
    overflow: hidden;
    margin-bottom: 24px;
    box-shadow: 0 0 20px rgba(0, 229, 255, 0.08);
}
```

- [ ] **Step 3: Add Starbase data loader JS**

In the `<script>` block, add a function to fetch hub stats:

```javascript
async function loadStarbaseStats() {
    try {
        // Agent + model counts from Bridge manifest
        const crewResp = await fetch('/tools/bridge/api/crew-manifest');
        const crewData = await crewResp.json();
        if (crewData.agents) {
            document.getElementById('sb-agents').textContent = crewData.agents.length;
            var activeJobs = crewData.agents.filter(a => a.current_job).length;
            document.getElementById('sb-jobs').textContent = activeJobs;
        }

        // Hardware from Bridge capacity
        const hwResp = await fetch('/tools/bridge/api/hardware-capacity');
        const hwData = await hwResp.json();
        if (hwData.success) {
            const hw = hwData;
            document.getElementById('sb-cpu').textContent = hw.cpu_model || '--';
            document.getElementById('sb-ram').textContent = hw.total_ram_gb ? hw.total_ram_gb + ' GB' : '--';
            document.getElementById('sb-gpu').textContent = hw.gpu_name || '--';
            if (hw.loaded_models !== undefined) {
                document.getElementById('sb-models').textContent = hw.total_models || hw.loaded_models || '--';
            }
        }
    } catch(e) {
        console.warn('Starbase stats load failed:', e);
    }
}
```

Call `loadStarbaseStats()` on page load and on a 30s interval.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/starship/templates/tools/starship/starship.html
git commit -m "feat(starship): add Starbase hub card to landing page"
```

---

### Task 8: Refactor Node Detail Tabs — 6 Tabs → 3

**Files:**
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html`

Replace the 6 tab buttons and 6 panels with 3: STATUS, OTA/SYNC, CREW.

- [ ] **Step 1: Replace tab buttons**

Replace lines 525-530 (the 6 tab buttons):
```html
<button class="sc-tab active" onclick="switchTab('status')" data-tab="status">STATUS</button>
<button class="sc-tab" onclick="switchTab('stations')" data-tab="stations">STATIONS</button>
<button class="sc-tab" onclick="switchTab('agents')" data-tab="agents">AGENTS</button>
<button class="sc-tab" onclick="switchTab('models')" data-tab="models">MODELS</button>
<button class="sc-tab" onclick="switchTab('privacy')" data-tab="privacy">PRIVACY</button>
<button class="sc-tab" onclick="switchTab('profile')" data-tab="profile">PROFILE</button>
```

With 3 tab buttons:
```html
<button class="sc-tab active" onclick="switchTab('status')" data-tab="status">STATUS</button>
<button class="sc-tab" onclick="switchTab('ota')" data-tab="ota">OTA / SYNC</button>
<button class="sc-tab" onclick="switchTab('crew')" data-tab="crew">CREW</button>
```

- [ ] **Step 2: Rebuild STATUS panel**

Keep the existing STATUS panel content (health, hardware gauges, fleet summary) and add inline-editable fields for node name, deployment mode, and priority (previously on PROFILE tab):

After the existing status content, add:
```html
<div class="sc-section">
    <h4>NODE SETTINGS</h4>
    <div class="sc-row">
        <span class="sc-label">Name</span>
        <input type="text" class="sc-input" id="settings-name" style="width:200px;" onchange="saveNodeSettings()">
    </div>
    <div class="sc-row">
        <span class="sc-label">Mode</span>
        <select class="sc-input" id="settings-mode" style="width:200px;" onchange="saveNodeSettings()">
            <option value="starship">Starship</option>
            <option value="satellite">Satellite</option>
            <option value="outpost">Outpost</option>
        </select>
    </div>
    <div class="sc-row">
        <span class="sc-label">Priority</span>
        <input type="number" class="sc-input" id="settings-priority" min="0" max="100" style="width:200px;" onchange="saveNodeSettings()">
    </div>
</div>
```

- [ ] **Step 3: Create OTA/SYNC panel**

Replace the deleted STATIONS and MODELS panels with a new OTA/SYNC panel:

```html
<div class="sc-panel" id="panel-ota">
    <div class="sc-section">
        <h4>OTA ACTIONS</h4>
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px;">
            <button class="sc-btn" onclick="pushCodeUpdate()">PUSH UPDATE</button>
            <button class="sc-btn" onclick="pushAgentConfig()">PUSH AGENT CONFIG</button>
        </div>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
            <select class="sc-input" id="pull-model-select" style="width:250px;">
                <option value="">Select model...</option>
            </select>
            <button class="sc-btn" onclick="pullModelToNode(document.getElementById('pull-model-select').value, this)">PULL MODEL</button>
        </div>
    </div>
    <div class="sc-section">
        <h4>SYNC STATUS</h4>
        <div id="sync-status-panel" style="margin-bottom:12px;">
            <span class="sc-label">Checking...</span>
        </div>
    </div>
    <div class="sc-section">
        <h4>SYNC LOG</h4>
        <div id="sync-log-container">
            <table style="width:100%;border-collapse:collapse;">
                <thead><tr>
                    <th class="sc-label" style="text-align:left;padding:6px;">Type</th>
                    <th class="sc-label" style="text-align:left;padding:6px;">Status</th>
                    <th class="sc-label" style="text-align:left;padding:6px;">Time</th>
                </tr></thead>
                <tbody id="sync-log-body"></tbody>
            </table>
        </div>
    </div>
</div>
```

- [ ] **Step 4: Rename AGENTS panel to CREW**

Change `id="panel-agents"` to `id="panel-crew"`. Keep agent card rendering and recommendations. **Remove add/remove/edit buttons from the CREW tab UI** — routes are kept for API compatibility but the CREW tab is read-only per spec (agent management stays on Bridge Command). Remove any agent-access toggle UI and station-toggle UI (those were part of deleted tabs).

- [ ] **Step 5: Delete PRIVACY and PROFILE panel HTML**

Remove the PRIVACY panel (lines ~692-763) and PROFILE panel (lines ~766-785) entirely.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/starship/templates/tools/starship/starship.html
git commit -m "refactor(starship): 6 tabs → 3 (STATUS, OTA/SYNC, CREW) + Starbase card"
```

---

### Task 9: Update JavaScript — Delete Dead Functions + Add New Ones

**Files:**
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html` (script block)

- [ ] **Step 1: Delete dead JS functions**

Remove these functions that served deleted tabs:
- `toggleStation()` (~line 1713)
- `initStationTerminals()` (~line 1739)
- `toggleAgentAccess()` (~line 1767)
- `savePrivacy()` (~line 1787)
- `saveMeshPrivacy()` (~line 1810)
- `saveProfile()` (~line 1830)

- [ ] **Step 2: Add `saveNodeSettings()` function**

```javascript
async function saveNodeSettings() {
    if (!window._selectedNodeId) return;
    const name = document.getElementById('settings-name').value.trim();
    const mode = document.getElementById('settings-mode').value;
    const priority = parseInt(document.getElementById('settings-priority').value) || 0;
    try {
        const resp = await fetch(`/tools/starship/api/nodes/${window._selectedNodeId}/settings`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({node_name: name, deployment_mode: mode, bridge_priority: priority})
        });
        const data = await resp.json();
        if (data.success) scToast('Settings saved', 'success');
        else scToast(data.error || 'Save failed', 'error');
    } catch(e) { scToast('Network error', 'error'); }
}
```

- [ ] **Step 3: Update `renderDetail()` to populate settings fields**

In `renderDetail(data)`, add after existing field population:
```javascript
// Populate inline settings
document.getElementById('settings-name').value = data.node_name || '';
document.getElementById('settings-mode').value = data.deployment_mode || 'starship';
document.getElementById('settings-priority').value = data.bridge_priority || 0;
```

- [ ] **Step 4: Update `selectNode()` to load OTA tab data**

After loading node detail, also load sync log and model catalog:
```javascript
// After renderDetail(data):
loadSyncLog(data.db_id || data.id);
loadModelCatalog();
pollSyncStatus();
```

- [ ] **Step 5: Ensure OTA tab JS functions exist**

These functions already exist in the template (they were built for the previous MODELS and OTA tabs). Verify they work with the new OTA/SYNC panel IDs. If any are missing or broken, here are the implementations:

```javascript
// loadSyncLog already exists (~line 1657). Just verify it writes to #sync-log-body.
// loadModelCatalog already exists (~line 1883). Wire it to populate #pull-model-select.
// pollSyncStatus already exists (~line 2347). Just verify it writes to #sync-status-panel.

// If loadModelCatalog doesn't populate the select dropdown, add this adapter:
async function populatePullModelDropdown() {
    try {
        var resp = await fetch('/tools/starship/api/model-catalog');
        var data = await resp.json();
        if (!data.success) return;
        var sel = document.getElementById('pull-model-select');
        // Clear existing options using DOM methods
        while (sel.firstChild) sel.removeChild(sel.firstChild);
        var defaultOpt = document.createElement('option');
        defaultOpt.value = '';
        defaultOpt.textContent = 'Select model...';
        sel.appendChild(defaultOpt);
        data.models.forEach(function(m) {
            var opt = document.createElement('option');
            opt.value = m.name;
            opt.textContent = m.name + ' (' + (m.size_gb || '?') + ' GB)';
            sel.appendChild(opt);
        });
    } catch(e) { console.warn('Model catalog load failed:', e); }
}
```

- [ ] **Step 6: Fix install command URLs in `createNode()`**

In the `createNode()` function (around the install command generation), update to use the new `/starship/install` endpoint. The existing template uses `/tools/starship/` prefix for all fetch calls:

```javascript
var hubUrl = (data.config && data.config.hub_url) || 'https://archie.kytranempowerment.com';
var token = data.setup_token || '';
var winCmd = 'irm "' + hubUrl + '/starship/install?token=' + token + '" | iex';
var linuxCmd = 'curl -fsSL "' + hubUrl + '/starship/install?token=' + token + '" | bash';
```

Note: The install URL uses `/starship/install` (not `/tools/starship/install`) because it's the external-facing URL that nodes call — the Nginx proxy resolves this.

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/starship/templates/tools/starship/starship.html
git commit -m "refactor(starship): update JS — dead functions removed, settings + OTA wired up"
```

---

## Chunk 3: Integration + Deploy

### Task 10: Clean Up Dead CSS + Polish

**Files:**
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html`

- [ ] **Step 1: Remove CSS for deleted components**

Remove the privacy toggle CSS (`.sc-toggle-row`, `.sc-toggle-info`, `.sc-toggle-name`, `.sc-toggle-desc`, `.sc-switch`, `.sc-slider`) — lines ~72-81.

Remove the profile form `.sc-input` styles only if unused (check — they're reused by settings fields, so keep them).

- [ ] **Step 2: Add sync log table styling**

```css
#sync-log-body tr { border-bottom: 1px solid rgba(255,255,255,0.05); }
#sync-log-body td { padding: 6px; color: rgba(255,255,255,0.7); font-family: 'IBM Plex Mono', monospace; font-size: 0.8rem; }
.sync-status-sent { color: var(--sc-amber); }
.sync-status-acked { color: var(--sc-green); }
.sync-status-failed { color: var(--sc-red); }
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/starship/templates/tools/starship/starship.html
git commit -m "style(starship): remove dead CSS, add sync log table styles"
```

---

### Task 11: Update Module Docstring

**Files:**
- Modify: `platform_v2/tools/starship/routes.py:1-6`

- [ ] **Step 1: Update the module docstring**

Replace:
```python
"""
Starship Command — Fleet node management module.

Fleet owners see all their nodes. Node operators see their own ship.
Privacy controls let operators choose what to share with the fleet.
"""
```
with:
```python
"""
Starship Command — Fleet node management module.

Starbase (hub) overview + fleet node management.
3 tabs: STATUS, OTA/SYNC, CREW.
"""
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/starship/routes.py
git commit -m "docs(starship): update module docstring to reflect refactor"
```

---

### Task 12: Deploy + Integration Test

**Files:** None (testing only)

- [ ] **Step 1: Restart platform**

```bash
cd /mnt/archie_brain && docker compose restart archie_platform
```

- [ ] **Step 2: Verify module loads**

```bash
docker logs --tail 50 archie_platform 2>&1 | grep -i starship
```
Expected: No import errors.

- [ ] **Step 3: Test landing page**

Navigate to `http://192.168.1.200:3000/starship/` — verify:
- Starbase card visible at top with live stats
- Fleet node cards visible below
- No STATIONS/MODELS/PRIVACY/PROFILE tabs in node detail
- STATUS + OTA/SYNC + CREW tabs work

- [ ] **Step 4: Test new install endpoint**

```bash
curl -s "http://localhost:3000/starship/install?token=invalid"
```
Expected: `Error: invalid or expired token`

- [ ] **Step 5: Test settings endpoint**

With a valid node_id, test inline edit:
```bash
curl -s -X PUT "http://localhost:3000/tools/starship/api/nodes/KYTRAN-StarShip/settings" \
  -H "Content-Type: application/json" \
  -d '{"bridge_priority": 50}' \
  -b "session=<cookie>"
```
Expected: `{"success": true}`

- [ ] **Step 6: Commit deploy confirmation**

No code changes — this is verification only.

---

### Task 13: Update Dev HQ

- [ ] **Step 1: Complete the refactor task in Dev HQ**

Use MCP `complete_task` for the Starship refactor work.

- [ ] **Step 2: Log the architectural decision**

Use MCP `log_decision` — "Starship Command refactored from 6 tabs to 3 (STATUS, OTA/SYNC, CREW). Removed privacy/stations/profile tabs. Added Starbase hub card. Fixed 6 bugs including install endpoint, ownership checks, orphan node claim."

- [ ] **Step 3: Update project understanding**

Use MCP `update_project_understanding` for the Starship module changes.
