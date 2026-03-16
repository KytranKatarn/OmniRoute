# Station Panel Snippet — Copy-Paste Template

> Drop-in station operations panel for any ARCHIE module.
> Reference implementations: Security Network, Consciousness, Dev Pipeline.

---

## Required Includes

Add these to your module's HTML template (usually already included via base template):

```html
<link rel="stylesheet" href="/static/css/station-ops.css">
<script src="/static/js/station-ops.js"></script>
```

---

## HTML Template

```html
<!-- Copy this into your module template, inside the first tab/section -->
<div class="stn-ops-terminal cs-ops-terminal" id="{{PREFIX}}OpsTerminal">
    <div class="stn-ops-header cs-ops-header">
        <div class="stn-ops-elbow cs-ops-elbow"></div>
        <div class="stn-ops-title cs-ops-title">{{STATION_NAME}} OPERATIONS</div>
        <div class="stn-ops-status cs-ops-status" id="{{PREFIX}}OpsOnline">
            <span class="stn-ops-dot cs-ops-dot"></span> ONLINE
        </div>
    </div>
    <div class="stn-ops-body cs-ops-body">
        <div id="{{PREFIX}}OpsAgents"></div>
        <div id="{{PREFIX}}OpsJobs"></div>
        <div class="cs-ops-commands" id="{{PREFIX}}OpsCommands"></div>
    </div>
</div>
```

---

## JavaScript Template

```javascript
// Replace: STATION_CODE, MODULE_SOURCE, PREFIX, commands
var _{{PREFIX}}Ops = null;

function _get{{PREFIX}}Ops() {
    if (!_{{PREFIX}}Ops) {
        if (typeof StationOps === 'undefined') return null;
        _{{PREFIX}}Ops = new StationOps({
            stationCode: '{{STATION_CODE}}',
            moduleSource: '{{MODULE_SOURCE}}',
            agentsElId: '{{PREFIX}}OpsAgents',
            jobsElId: '{{PREFIX}}OpsJobs',
            commandsElId: '{{PREFIX}}OpsCommands',
            statusElId: '{{PREFIX}}OpsOnline',
            commands: [
                // Valid cls values: purple, amber, green, cyan
                { label: 'ACTION 1', cls: 'green', fn: "myFunction1()", id: '{{PREFIX}}Cmd1' },
                { label: 'ACTION 2', cls: 'amber', fn: "myFunction2()", id: '{{PREFIX}}Cmd2' }
            ],
            onCapacityChange: function(atCap) {
                ['{{PREFIX}}Cmd1','{{PREFIX}}Cmd2'].forEach(function(id) {
                    var btn = document.getElementById(id);
                    if (btn) { btn.disabled = atCap; btn.title = atCap ? 'Station at capacity' : ''; }
                });
                var status = document.getElementById('{{PREFIX}}OpsOnline');
                if (status) {
                    var dot = status.querySelector('.cs-ops-dot');
                    var txt = status.childNodes[status.childNodes.length - 1];
                    if (atCap) {
                        if (dot) { dot.style.background = '#f59e0b'; dot.style.boxShadow = '0 0 4px #f59e0b'; }
                        if (txt && txt.nodeType === 3) txt.textContent = ' AT CAPACITY';
                        status.style.color = '#f59e0b';
                    } else {
                        if (dot) { dot.style.background = ''; dot.style.boxShadow = ''; }
                        if (txt && txt.nodeType === 3) txt.textContent = ' ONLINE';
                        status.style.color = '';
                    }
                }
            }
        });
    }
    return _{{PREFIX}}Ops;
}

function render{{PREFIX}}Ops(jobData) {
    var ops = _get{{PREFIX}}Ops();
    if (ops) ops.render(jobData);
}

// Call on page load or tab switch:
render{{PREFIX}}Ops();
```

---

## Python `__init__.py` Template

```python
# Add to your module's __init__.py, after blueprint registration
try:
    from services.action_registry import register_station_actions

    register_station_actions(
        [
            {
                "action_key": "{{MODULE_SOURCE}}.action1",
                "station_code": "{{STATION_CODE}}",
                "module_source": "{{MODULE_SOURCE}}",
                "label": "ACTION 1",
                "description": "Description of action",
                "icon": "icon-name",
                "color_class": "green",
                "sort_order": 10,
                "endpoint_path": "/tools/{{MODULE_ROUTE}}/api/action1",  # REQUIRED
                "creates_job": True,
                "job_type": "job_type_name",
            },
        ]
    )
except Exception:
    pass
```

---

## Variables to Replace

| Variable | Example | Description |
|----------|---------|-------------|
| `{{PREFIX}}` | `sec` | Short prefix for element IDs (keeps them unique per module) |
| `{{STATION_CODE}}` | `SECURITY` | Must match `bridge_stations.station_code` |
| `{{STATION_NAME}}` | `SECURITY` | Display name shown in the panel header |
| `{{MODULE_SOURCE}}` | `security_network` | Must match `module_source` in action registry |
| `{{MODULE_ROUTE}}` | `security-network` | URL prefix for API endpoints (hyphenated) |

---

## Integration Checklist

1. **Add HTML** — Copy the HTML template into your module's Jinja2 template, inside the first visible tab or section.
2. **Add CSS include** — Ensure `station-ops.css` is loaded (check base template; may already be included).
3. **Add JS include** — Ensure `station-ops.js` is loaded before your module's script block.
4. **Add JS init** — Copy the JavaScript template into your module's `<script>` block. Replace all `{{PREFIX}}` placeholders.
5. **Register actions** — Add `register_station_actions()` call to your module's `__init__.py` with correct `endpoint_path` values.
6. **Wire API endpoints** — Each action's `endpoint_path` must exist and return JSON with `{success: true, job_id: ...}` for job-creating actions.
7. **Call render on load** — Invoke `render{{PREFIX}}Ops()` on page load and/or tab switch so the panel populates immediately.
8. **Test capacity** — Verify the `onCapacityChange` callback correctly disables your command buttons when all station agent slots are full.

---

## Working Examples

| Module | File | Prefix | Station |
|--------|------|--------|---------|
| Security Network | `templates/tools/security_network.html` | `sec` | SECURITY |
| Consciousness | `templates/tools/consciousness/dashboard.html` | `cs` | ANALYTICS |
| Dev Pipeline | `templates/tools/dev_pipeline/dev_pipeline.html` | `eng` | ENGINEERING |

---

## How It Works

`StationOps` (defined in `static/js/station-ops.js`) handles:

- **Agent display** — Fetches assigned agents from Bridge API, shows avatars + status
- **Job tracking** — Polls active jobs for this station, renders progress bars
- **Command buttons** — Renders action buttons with dispatch integration
- **Capacity management** — Tracks agent slot usage (2 primary + 1 auxiliary = 3 max), fires `onCapacityChange` callback

The panel talks to Bridge via `/api/bridge/stations/{stationCode}` endpoints. No direct database access needed from your module.
