# Station Operations Implementation Guide

> **This is the definitive reference for implementing station panels in any A.R.C.H.I.E. module.**
> Reference implementation: Consciousness module (`consciousness.js` + `consciousness_dashboard.html`)

## Architecture

Bridge Command is the central nervous system. ALL agent work flows through it:
- **Bridge Dispatcher** routes jobs to stations → agents
- **StationOps** (shared JS component) renders crew, jobs, commands in any module
- **Action Registry** registers module actions that create Bridge jobs
- **5-Step Escalation**: primary → backup → cross-station → free cloud → paid cloud

## HTML Structure

```html
<!-- Station Operations Terminal -->
<div class="stn-ops-terminal cs-ops-terminal" id="secOpsTerminal">
    <div class="stn-ops-header cs-ops-header">
        <div class="stn-ops-elbow cs-ops-elbow"></div>
        <div class="stn-ops-title cs-ops-title">SECURITY OPERATIONS</div>
        <div class="stn-ops-status cs-ops-status" id="secOpsOnline">
            <span class="stn-ops-dot cs-ops-dot"></span> ONLINE
        </div>
    </div>
    <div class="stn-ops-body cs-ops-body">
        <div id="secOpsAgents"></div>
        <div id="secOpsJobs"></div>
        <div class="cs-ops-commands" id="secOpsCommands"></div>
    </div>
</div>
```

**Key points:**
- Use BOTH `stn-ops-*` AND `cs-ops-*` classes (shared + module-specific)
- IDs follow pattern: `{prefix}OpsAgents`, `{prefix}OpsJobs`, `{prefix}OpsCommands`, `{prefix}OpsOnline`
- The `cs-ops-commands` class provides the grid layout for command buttons

## JavaScript Initialization

### Step 1: Create StationOps instance (lazy singleton)

```javascript
var _secOps = null;

function _getSecOps() {
    if (!_secOps) {
        _secOps = new StationOps({
            stationCode: 'SECURITY',        // Must match bridge_stations.station_code
            moduleSource: 'security_network', // Must match module_source in action_registry
            agentsElId: 'secOpsAgents',       // div ID for crew display
            jobsElId: 'secOpsJobs',           // div ID for running jobs
            commandsElId: 'secOpsCommands',   // div ID for action buttons
            statusElId: 'secOpsOnline',       // div ID for ONLINE/OFFLINE
            commands: [
                { label: 'NMAP SCAN', cls: 'red', fn: "runNmapScan()", id: 'secCmdNmap' },
                { label: 'SSL CHECK', cls: 'green', fn: "runSslCheck()", id: 'secCmdSsl' },
                { label: 'DEVICE AUDIT', cls: 'cyan', fn: "runDeviceAudit()", id: 'secCmdDevices' },
                { label: 'DNS REPORT', cls: 'blue', fn: "runDnsReport()", id: 'secCmdDns' }
            ],
            onCapacityChange: function(atCap) {
                // Disable ALL action buttons when station is full
                ['secCmdNmap','secCmdSsl','secCmdDevices','secCmdDns'].forEach(function(id) {
                    var btn = document.getElementById(id);
                    if (btn) { btn.disabled = atCap; btn.title = atCap ? 'Station at capacity' : ''; }
                });
            }
        });
    }
    return _secOps;
}
```

### Step 2: Render function (called on tab load)

```javascript
function renderSecurityOps(jobData) {
    var ops = _getSecOps();
    if (ops) ops.render(jobData);  // render() handles agents + jobs + commands
}
```

**IMPORTANT:** Call `ops.render(jobData)` — NOT `renderAgents()` + `renderJobs()` separately.

### Step 3: Initialize on page/tab load

```javascript
// On DOMContentLoaded or tab switch:
renderSecurityOps();
```

## What render() does automatically

1. Fetches `/tools/bridge/api/stations` → finds agents assigned to your stationCode
2. Renders PRIMARY slot (agent 1) + SECONDARY slot (agent 2) + AUXILIARY slot
3. Fetches `/tools/bridge/api/bridge/jobs?status=running` → filters by moduleSource
4. Shows running jobs with progress bars
5. Renders command buttons from the `commands` array
6. Fires `onCapacityChange(atCapacity)` when station becomes full/available
7. Cross-station assists and cloud contractors display automatically

## Station Slots

- **PRIMARY** (green badge): First assigned agent
- **SECONDARY** (blue badge): Second assigned agent
- **AUXILIARY** (yellow badge): Cross-station helper or cloud contractor (auto-managed by Bridge)

Capacity: PRIMARY_COUNT >= max_primary AND AUXILIARY_COUNT >= max_auxiliary = FULL

## Action Registration (__init__.py)

```python
try:
    from services.action_registry import register_station_actions
    register_station_actions([
        {
            "action_key": "security_network.nmap_scan",
            "station_code": "SECURITY",
            "module_source": "security_network",
            "label": "NMAP SCAN",
            "description": "Port scan + service detection",
            "icon": "radar",
            "color_class": "red",
            "sort_order": 10,
            "endpoint_path": "/tools/security-network/api/recon/scan",  # REQUIRED
            "creates_job": True,
            "job_type": "vulnerability_scan",
        },
    ])
except Exception:
    pass
```

**CRITICAL:** Every action MUST have `endpoint_path` or registration silently fails.

## Capacity Gating Pattern

```javascript
onCapacityChange: function(atCapacity) {
    // Disable command buttons
    var btns = document.querySelectorAll('#secOpsCommands button');
    btns.forEach(function(b) { b.disabled = atCapacity; });

    // Update status indicator
    var status = document.getElementById('secOpsOnline');
    var dot = status.querySelector('.cs-ops-dot');
    if (atCapacity) {
        dot.style.background = '#f59e0b';
        status.lastChild.textContent = ' AT CAPACITY';
    } else {
        dot.style.background = '';
        status.lastChild.textContent = ' ONLINE';
    }
}
```

## 5-Step Escalation Chain

When a job is dispatched via `dispatcher.create_job()`:

1. **PRIMARY**: Try agents assigned to the station
2. **BACKUP**: Try backup-type assignments
3. **CROSS-STATION**: Borrow idle agent from another station (fills aux slot)
4. **FREE CLOUD**: Auto-approved cloud model (no cost)
5. **PAID CLOUD**: Requires Telegram human approval

Cross-station and cloud agents appear automatically in the AUXILIARY slot.

## Checklist for New Modules

- [ ] HTML: `stn-ops-terminal` with agents/jobs/commands/status divs
- [ ] JS: Create StationOps singleton with lazy `_getOps()` pattern
- [ ] JS: Use `ops.render(jobData)` — NOT renderAgents/renderJobs separately
- [ ] JS: Add `onCapacityChange` callback to disable buttons
- [ ] Python: `register_station_actions()` in `__init__.py` with `endpoint_path` on ALL actions
- [ ] Python: API endpoints that call `dispatcher.create_job()`
- [ ] DB: Verify station exists in `bridge_stations` with agents in `station_assignments`

## Source Files

| File | Purpose |
|------|---------|
| `/platform_v2/static/js/station-ops.js` | Shared StationOps component |
| `/platform_v2/static/css/station-ops.css` | Shared styling |
| `/platform_v2/static/js/consciousness.js` lines 1679-1760 | Reference implementation |
| `/platform_v2/tools/consciousness/templates/consciousness_dashboard.html` lines 2355-2370 | Reference HTML |
| `/ai_bridge/bridge_dispatcher.py` | Dispatch + escalation |
| `/platform_v2/services/action_registry.py` | Action registration |
