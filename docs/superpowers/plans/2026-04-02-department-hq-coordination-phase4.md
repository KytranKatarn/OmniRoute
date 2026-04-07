# Department HQ Coordination — Phase 4: Starbase UI + Cloud Provider Integration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Starbase UI's Fleet Map tab to use the new `cloud_providers` table from Phase 3, add cloud provider CRUD API routes, enhance the providers grid and usage dashboard to show real data from `cloud_providers` + `cloud_usage_log`, and ensure node detail panels show deployed agents from `fleet_service`.

**Architecture:** The Fleet Map tab, Leaflet.js map, providers grid HTML, and usage dashboard already exist in Starbase. The `api_fleet_map()` route already calls `fleet_service.get_fleet_map_data()`. The gap is: (1) `api_list_providers()` reads from old `contractor_providers` table — need a unified endpoint that also includes `cloud_providers`, (2) toggle/budget APIs hit `contractor_providers` directly — need `cloud_providers` equivalents, (3) the JS `loadFleetUsage()` function renders providers grid but needs to handle the new cloud_providers data shape. All changes are in `fleet_routes.py` (backend) and `starbase.js` (frontend).

**Tech Stack:** Python 3.11, Flask, PostgreSQL, Leaflet.js, LCARS CSS

**Security Note:** All HTML rendering of provider data in the JS must use DOM textContent or escHtml() for user-provided strings. Never insert raw HTML from API responses. The existing starbase.js uses `escHtml()` for this purpose.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `platform_v2/tools/starbase/fleet_routes.py` | Add cloud provider CRUD routes, unified providers endpoint |
| Modify | `platform_v2/static/js/starbase.js` | Update loadFleetUsage to render cloud_providers cards + budget table |
| Modify | `platform_v2/static/css/starbase.css` | Provider card LCARS styles |
| Modify | `platform_v2/tools/starbase/templates/starbase.html` | Rename section header |

---

### Task 1: Add cloud provider CRUD API routes

**Files:**
- Modify: `platform_v2/tools/starbase/fleet_routes.py`

Add routes for managing cloud_providers (the new Phase 3 table). The existing routes for `contractor_providers` stay untouched.

- [ ] **Step 1: Add GET /api/cloud-providers endpoint**

In `fleet_routes.py`, inside `register_fleet_routes()`, add after the existing `api_update_provider_budget` route:

```python
    # ------------------------------------------------------------------ #
    # GET /api/cloud-providers — list cloud_providers table
    # ------------------------------------------------------------------ #
    @bp.route("/api/cloud-providers")
    @admin_required
    def api_list_cloud_providers():
        """List all cloud providers from cloud_providers table."""
        try:
            from services.fleet_service import list_cloud_providers
            providers = list_cloud_providers()
            for p in providers:
                for key in ("latitude", "longitude", "monthly_budget", "monthly_usage"):
                    if p.get(key) is not None:
                        p[key] = float(p[key])
            return jsonify({"providers": providers})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
```

- [ ] **Step 2: Add POST /api/cloud-providers endpoint (create)**

```python
    # ------------------------------------------------------------------ #
    # POST /api/cloud-providers — create a new cloud provider
    # ------------------------------------------------------------------ #
    @bp.route("/api/cloud-providers", methods=["POST"])
    @admin_required
    def api_create_cloud_provider():
        """Create a new cloud provider."""
        try:
            from services.fleet_service import register_provider
            data = request.get_json() or {}
            name = data.get("name", "").strip()
            if not name:
                return jsonify({"error": "name is required"}), 400

            pid = register_provider(
                name=name,
                provider_type=data.get("provider_type", "cloud"),
                api_key_env_var=data.get("api_key_env_var", ""),
                tier=data.get("tier", "free"),
                capabilities=data.get("capabilities", []),
                models_available=data.get("models_available", []),
                api_endpoint=data.get("api_endpoint", ""),
                headquarters_city=data.get("headquarters_city", ""),
                latitude=data.get("latitude"),
                longitude=data.get("longitude"),
                monthly_budget=data.get("monthly_budget", 0),
            )
            return jsonify({"success": True, "id": pid})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
```

- [ ] **Step 3: Add POST /api/cloud-providers/<id>/toggle endpoint**

```python
    # ------------------------------------------------------------------ #
    # POST /api/cloud-providers/<id>/toggle — toggle status
    # ------------------------------------------------------------------ #
    @bp.route("/api/cloud-providers/<int:provider_id>/toggle", methods=["POST"])
    @admin_required
    def api_toggle_cloud_provider(provider_id):
        """Toggle a cloud provider active/inactive."""
        try:
            from database import get_db_cursor
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE cloud_providers
                       SET status = CASE WHEN status = 'active' THEN 'inactive' ELSE 'active' END,
                           updated_at = NOW()
                       WHERE id = %s
                       RETURNING id, name, status""",
                    (provider_id,),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"error": "Provider not found"}), 404
                return jsonify({"success": True, "id": row["id"], "name": row["name"], "status": row["status"]})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
```

- [ ] **Step 4: Add POST /api/cloud-providers/<id>/budget and GET /api/cloud-providers/<id>/usage**

```python
    # ------------------------------------------------------------------ #
    # POST /api/cloud-providers/<id>/budget — update monthly budget
    # ------------------------------------------------------------------ #
    @bp.route("/api/cloud-providers/<int:provider_id>/budget", methods=["POST"])
    @admin_required
    def api_update_cloud_provider_budget(provider_id):
        """Update a cloud provider's monthly budget."""
        try:
            from database import get_db_cursor
            data = request.get_json() or {}
            budget = data.get("monthly_budget")
            if budget is None:
                return jsonify({"error": "monthly_budget is required"}), 400
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE cloud_providers
                       SET monthly_budget = %s, updated_at = NOW()
                       WHERE id = %s
                       RETURNING id, name, monthly_budget""",
                    (budget, provider_id),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"error": "Provider not found"}), 404
                return jsonify({"success": True, "id": row["id"], "monthly_budget": float(row["monthly_budget"])})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------ #
    # GET /api/cloud-providers/<id>/usage — usage stats for one provider
    # ------------------------------------------------------------------ #
    @bp.route("/api/cloud-providers/<int:provider_id>/usage")
    @admin_required
    def api_cloud_provider_usage(provider_id):
        """Get usage stats for a specific cloud provider."""
        try:
            from database import get_db_cursor
            days = int(request.args.get("days", 30))
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT model_name,
                              COUNT(*) AS calls,
                              SUM(tokens_in) AS tokens_in,
                              SUM(tokens_out) AS tokens_out,
                              SUM(estimated_cost) AS total_cost
                       FROM cloud_usage_log
                       WHERE provider_id = %s
                         AND created_at > NOW() - INTERVAL '%s days'
                       GROUP BY model_name
                       ORDER BY total_cost DESC""",
                    (provider_id, days),
                )
                rows = cur.fetchall()
                return jsonify({
                    "provider_id": provider_id,
                    "days": days,
                    "by_model": [
                        {
                            "model": r["model_name"],
                            "calls": r["calls"],
                            "tokens_in": r["tokens_in"] or 0,
                            "tokens_out": r["tokens_out"] or 0,
                            "cost": float(r["total_cost"] or 0),
                        }
                        for r in rows
                    ],
                })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
```

- [ ] **Step 5: Restart and verify routes load**

```bash
cd /mnt/archie_brain && docker compose restart archie_platform
sleep 15
docker logs --since=30s archie_platform 2>&1 | grep -iE 'error|traceback' | head -5
```

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/starbase/fleet_routes.py
git commit -m "feat(starbase): add cloud provider CRUD API routes

Phase 4: GET/POST /api/cloud-providers for listing and creating,
toggle status, update budget, and per-provider usage stats.
All routes use cloud_providers table via fleet_service."
```

---

### Task 2: Update JS to render cloud providers in fleet tab

**Files:**
- Modify: `platform_v2/static/js/starbase.js`

The `loadFleetUsage()` function (around line 11208) already renders the providers grid and budget table. We need to also load from `/api/cloud-providers` and render cloud provider cards using DOM methods (no raw HTML insertion for user data).

- [ ] **Step 1: Add loadCloudProviders function**

Find the `loadFleetUsage` function (around line 11208). Add a new function AFTER the `updateFleetStats` function (around line 11180):

```javascript
async function loadCloudProviders() {
    try {
        const resp = await fetch('/tools/starbase/api/cloud-providers');
        const data = await resp.json();
        if (data.error) { console.error('Cloud providers error:', data.error); return; }

        const grid = document.getElementById('fleetProvidersGrid');
        if (!grid) return;

        const providers = data.providers || [];
        const countEl = document.getElementById('fleetProviderCount');
        if (countEl) countEl.textContent = providers.length;

        if (providers.length === 0) {
            grid.textContent = '';
            var emptyMsg = document.createElement('div');
            emptyMsg.style.cssText = 'text-align:center;color:#6b7280;padding:24px;';
            emptyMsg.textContent = 'No cloud providers configured';
            grid.appendChild(emptyMsg);
            return;
        }

        grid.textContent = '';
        providers.forEach(function(p) {
            var statusColor = p.status === 'active' ? '#10b981' : '#6b7280';
            var budgetPct = p.monthly_budget > 0
                ? Math.min(((p.monthly_usage || 0) / p.monthly_budget) * 100, 100).toFixed(0)
                : 0;
            var budgetColor = budgetPct > 80 ? '#ef4444' : budgetPct > 50 ? '#f59e0b' : '#10b981';

            var card = document.createElement('div');
            card.className = 'fleet-provider-card';

            // Header
            var header = document.createElement('div');
            header.className = 'fleet-provider-card-header';
            var nameSpan = document.createElement('span');
            nameSpan.className = 'fleet-provider-name';
            nameSpan.textContent = p.name;
            var statusSpan = document.createElement('span');
            statusSpan.className = 'fleet-provider-status';
            statusSpan.style.color = statusColor;
            statusSpan.textContent = (p.status || 'unknown').toUpperCase();
            header.appendChild(nameSpan);
            header.appendChild(statusSpan);
            card.appendChild(header);

            // Body rows
            var body = document.createElement('div');
            body.className = 'fleet-provider-card-body';
            [['Type', p.provider_type || 'cloud'], ['Tier', p.tier || 'free'],
             ['City', p.headquarters_city || '--'],
             ['Budget', '$' + (p.monthly_usage || 0).toFixed(2) + ' / $' + (p.monthly_budget || 0).toFixed(2)]
            ].forEach(function(pair) {
                var row = document.createElement('div');
                row.className = 'fleet-provider-row';
                var lbl = document.createElement('span');
                lbl.textContent = pair[0];
                var val = document.createElement('span');
                val.textContent = pair[1];
                row.appendChild(lbl);
                row.appendChild(val);
                body.appendChild(row);
            });

            // Budget bar
            if (p.monthly_budget > 0) {
                var barWrap = document.createElement('div');
                barWrap.className = 'fleet-provider-budget-bar';
                var barFill = document.createElement('div');
                barFill.style.cssText = 'width:' + budgetPct + '%;background:' + budgetColor + ';height:100%;border-radius:2px;';
                barWrap.appendChild(barFill);
                body.appendChild(barWrap);
            }

            // Capability tags
            var caps = document.createElement('div');
            caps.className = 'fleet-provider-caps';
            (p.capabilities || []).forEach(function(c) {
                var tag = document.createElement('span');
                tag.className = 'fleet-cap-tag';
                tag.textContent = c;
                caps.appendChild(tag);
            });
            body.appendChild(caps);
            card.appendChild(body);

            // Actions
            var actions = document.createElement('div');
            actions.className = 'fleet-provider-card-actions';
            var toggleBtn = document.createElement('button');
            toggleBtn.className = 'fleet-btn-sm';
            toggleBtn.textContent = p.status === 'active' ? 'Disable' : 'Enable';
            toggleBtn.addEventListener('click', function() { toggleCloudProvider(p.id); });
            actions.appendChild(toggleBtn);
            card.appendChild(actions);

            grid.appendChild(card);
        });
    } catch(e) {
        console.error('loadCloudProviders failed:', e);
    }
}

async function toggleCloudProvider(providerId) {
    try {
        const resp = await fetch('/tools/starbase/api/cloud-providers/' + providerId + '/toggle', { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            loadCloudProviders();
            loadFleetData();
        }
    } catch(e) {
        console.error('Toggle cloud provider failed:', e);
    }
}
```

- [ ] **Step 2: Wire loadCloudProviders into fleet tab initialization**

Find where `loadFleetUsage()` is called (around lines 10934, 11196, 11327, 11339). Add `loadCloudProviders();` right after each `loadFleetUsage();` call.

Also in `initFleetMap()` after `loadFleetData();` add `loadCloudProviders();`.

- [ ] **Step 3: Add cloud providers to budget table in loadFleetUsage**

In the existing `loadFleetUsage()` function, after it finishes building budget table rows from contractor data, add cloud provider rows using DOM methods:

```javascript
        // Cloud providers budget rows
        try {
            const cloudResp = await fetch('/tools/starbase/api/cloud-providers');
            const cloudData = await cloudResp.json();
            (cloudData.providers || []).forEach(function(p) {
                var budgetPct = p.monthly_budget > 0
                    ? ((p.monthly_usage || 0) / p.monthly_budget * 100).toFixed(0)
                    : '--';
                var statusColor = p.status === 'active' ? '#10b981' : '#6b7280';
                var row = document.createElement('tr');
                var cells = [p.name, p.tier || 'free',
                    '$' + (p.monthly_budget || 0).toFixed(2),
                    '$' + (p.monthly_usage || 0).toFixed(2),
                    budgetPct + (budgetPct !== '--' ? '%' : ''),
                    (p.status || '--').toUpperCase()];
                cells.forEach(function(text, i) {
                    var td = document.createElement('td');
                    td.textContent = text;
                    if (i === 5) td.style.color = statusColor;
                    row.appendChild(td);
                });
                tbody.appendChild(row);
            });
        } catch(e) {
            console.error('Cloud providers budget table error:', e);
        }
```

- [ ] **Step 4: Restart and verify**

```bash
cd /mnt/archie_brain && docker compose restart archie_platform
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/static/js/starbase.js
git commit -m "feat(starbase): render cloud providers in fleet tab

Phase 4: loadCloudProviders() fetches from /api/cloud-providers and
renders provider cards with DOM methods (XSS-safe). Budget table
includes cloud provider rows. Toggle buttons update provider status."
```

---

### Task 3: Add provider card CSS + rename section header

**Files:**
- Modify: `platform_v2/static/css/starbase.css`
- Modify: `platform_v2/tools/starbase/templates/starbase.html`

- [ ] **Step 1: Add provider card styles to starbase.css**

At the end of `starbase.css`, add:

```css
/* Fleet Provider Cards (Phase 4) */
.fleet-provider-card {
    background: rgba(30, 30, 50, 0.8);
    border: 1px solid rgba(0, 229, 255, 0.2);
    border-radius: 8px;
    padding: 12px;
    transition: border-color 0.2s;
}
.fleet-provider-card:hover {
    border-color: rgba(0, 229, 255, 0.5);
}
.fleet-provider-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}
.fleet-provider-name {
    font-family: 'Antonio', sans-serif;
    font-size: 1rem;
    color: #00e5ff;
    text-transform: uppercase;
    letter-spacing: 1px;
}
.fleet-provider-status {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 1px;
}
.fleet-provider-card-body {
    font-size: 0.8rem;
    color: #9ca3af;
}
.fleet-provider-row {
    display: flex;
    justify-content: space-between;
    padding: 2px 0;
    border-bottom: 1px solid rgba(255,255,255,0.05);
}
.fleet-provider-row span:last-child {
    color: #e5e7eb;
}
.fleet-provider-budget-bar {
    height: 4px;
    background: rgba(255,255,255,0.1);
    border-radius: 2px;
    margin: 6px 0;
    overflow: hidden;
}
.fleet-provider-caps {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 8px;
}
.fleet-cap-tag {
    font-size: 0.65rem;
    padding: 1px 6px;
    border-radius: 3px;
    background: rgba(139, 92, 246, 0.2);
    color: #a78bfa;
    border: 1px solid rgba(139, 92, 246, 0.3);
}
.fleet-provider-card-actions {
    margin-top: 8px;
    display: flex;
    gap: 6px;
}
.fleet-btn-sm {
    font-size: 0.7rem;
    padding: 3px 10px;
    border-radius: 4px;
    border: 1px solid rgba(0, 229, 255, 0.3);
    background: rgba(0, 229, 255, 0.1);
    color: #00e5ff;
    cursor: pointer;
    text-transform: uppercase;
    letter-spacing: 1px;
    font-family: 'Antonio', sans-serif;
    transition: background 0.2s;
}
.fleet-btn-sm:hover {
    background: rgba(0, 229, 255, 0.25);
}
```

- [ ] **Step 2: Rename section header in template**

In `starbase.html`, find around line 412:
```html
                            <span>CLOUD CONTRACTORS</span>
```
Replace with:
```html
                            <span>CLOUD PROVIDERS</span>
```

- [ ] **Step 3: Restart and verify**

```bash
cd /mnt/archie_brain && docker compose restart archie_platform
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/static/css/starbase.css platform_v2/tools/starbase/templates/starbase.html
git commit -m "style(starbase): LCARS provider cards + rename to CLOUD PROVIDERS

Phase 4: Provider card CSS with LCARS theme (dark bg, cyan accents,
budget bar, capability tags). Renamed section from CLOUD CONTRACTORS
to CLOUD PROVIDERS."
```

---

### Task 4: Enhance node detail panel with deployed agents

**Files:**
- Modify: `platform_v2/static/js/starbase.js`

The `showNodeDetail()` at line ~11086 builds a detail panel for fleet nodes. Add an agents section using DOM methods.

- [ ] **Step 1: Add agents section to showNodeDetail**

Find `showNodeDetail(node)` at line ~11086. Find where `body.appendChild` is called for existing sections. After the last section append, add:

```javascript
    // Agents section
    if (node.agents && node.agents.length > 0) {
        var agentSection = document.createElement('div');
        agentSection.className = 'fleet-detail-section';

        var agentTitle = document.createElement('div');
        agentTitle.className = 'fleet-detail-section-title';
        agentTitle.textContent = 'Deployed Agents (' + node.agents.length + ')';
        agentSection.appendChild(agentTitle);

        node.agents.forEach(function(agent) {
            var agentRow = document.createElement('div');
            agentRow.className = 'fleet-detail-row';
            var labelSpan = document.createElement('span');
            labelSpan.className = 'fleet-detail-label';
            labelSpan.textContent = agent.display_name || 'Unknown';
            var valueSpan = document.createElement('span');
            valueSpan.className = 'fleet-detail-value';
            valueSpan.textContent = agent.department || '--';
            agentRow.appendChild(labelSpan);
            agentRow.appendChild(valueSpan);
            agentSection.appendChild(agentRow);
        });

        body.appendChild(agentSection);
    }

    panel.style.display = '';
```

- [ ] **Step 2: Restart and verify**

```bash
cd /mnt/archie_brain && docker compose restart archie_platform
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/static/js/starbase.js
git commit -m "feat(starbase): show deployed agents in node detail panel

Phase 4: Node detail slide-out now shows deployed agents list
with display names and departments when clicking a node pin."
```

---

### Task 5: End-to-end verification

**Files:** Read-only.

- [ ] **Step 1: Verify cloud providers data**

```bash
docker exec archie_platform python3 -c "
from services.fleet_service import list_cloud_providers, get_fleet_map_data
providers = list_cloud_providers()
print(f'Cloud providers: {len(providers)}')
for p in providers:
    print(f'  {p[\"name\"]}: {p[\"status\"]} budget=\${float(p[\"monthly_budget\"]):.2f}')
data = get_fleet_map_data()
print(f'Fleet map: hub + {len(data[\"nodes\"])} nodes + {len(data[\"providers\"])} providers')
"
```

- [ ] **Step 2: Run all tests**

```bash
docker exec archie_platform python -m pytest services/tests/ -v 2>&1 | tail -30
```

- [ ] **Step 3: Verify consciousness**

```bash
docker logs --since=120s archie_platform 2>&1 | grep -iE 'embedding|analysis' | tail -5
```

---

## Summary

| Task | What | Files | Commits |
|------|------|-------|---------|
| 1 | Cloud provider CRUD API (5 endpoints) | fleet_routes.py | 1 |
| 2 | JS: loadCloudProviders + budget table + toggle (DOM-safe) | starbase.js | 1 |
| 3 | CSS: provider cards LCARS styling + rename section | starbase.css + starbase.html | 1 |
| 4 | Node detail panel: show deployed agents (DOM methods) | starbase.js | 1 |
| 5 | End-to-end verification | Read-only | 0 |

**Total: 4 commits, 4 modified files, 5 new API endpoints**

After Phase 4:
- Fleet Map tab shows cloud providers from `cloud_providers` table with map pins
- Provider cards grid with LCARS styling, budget bars, capability tags, toggle buttons
- Budget table includes cloud provider rows with usage tracking
- Node detail panels show deployed agents
- All DOM rendering uses textContent (XSS-safe)
- Existing `contractor_providers` functionality untouched (backward compatible)
