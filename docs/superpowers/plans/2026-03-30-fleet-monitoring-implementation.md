# Fleet Monitoring — Hybrid Nagios + ARCHIE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Nagios as a headless infrastructure monitor with ARCHIE's fleet heartbeat system, surfacing unified health data in Starship Command with Telegram/email alerting.

**Architecture:** Nagios runs check plugins for infrastructure (ping, HTTP, SMTP, disk, certs). ARCHIE's monitoring service parses Nagios `status.dat` and merges with heartbeat data. Auto-config generates Nagios host definitions when nodes register. Alerts route through existing Telegram bot (critical) and Stalwart mail (warnings).

**Tech Stack:** Nagios Core 4.5.7 (Docker), Python status.dat parser, Flask routes, Jinja templates, PostgreSQL, APScheduler

**Key paths:**
- Monitoring compose: `/mnt/stacks/monitoring/docker-compose.yml`
- Nagios config volume: `monitoring_nagios_config` → `/opt/nagios/etc`
- Nagios data volume: `monitoring_nagios_data` → `/opt/nagios/var` (contains `status.dat`)
- Nagios conf.d: `/opt/nagios/etc/conf.d/` (empty, ready for auto-config)
- Telegram alerts: `platform_v2/services/telegram_service.py` → `send_system(title, msg)`

---

## File Structure

| File | Responsibility |
|------|---------------|
| Create: `platform_v2/services/monitoring_service.py` | Parse status.dat, merge with heartbeats, auto-config Nagios, alert routing |
| Create: `platform_v2/tools/starship/health_routes.py` | Health API endpoints for Starship Command |
| Create: `database/migrations/060_monitoring_tables.sql` | `monitoring_checks` + `monitoring_alerts` tables |
| Create: `monitoring/nagios-conf.d/archie-starbase.cfg` | Hub host + service definitions |
| Create: `monitoring/nagios-conf.d/outpost_us_001.cfg` | Outpost host + service definitions |
| Create: `monitoring/nagios-templates/outpost.cfg.j2` | Jinja template for outpost-type nodes |
| Create: `monitoring/nagios-templates/starship.cfg.j2` | Jinja template for GPU nodes |
| Modify: `/mnt/stacks/monitoring/docker-compose.yml` | Add conf.d bind mount, share status.dat |
| Modify: `/mnt/archie_brain/docker-compose.yml` | Mount Nagios data volume into archie_platform |
| Modify: `platform_v2/tools/starship/__init__.py` | Register health_routes |
| Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html` | Add HEALTH tab |
| Modify: `platform_v2/static/js/starship.js` | HEALTH tab JS |
| Modify: `platform_v2/static/css/starship.css` | Health indicator styles |
| Modify: `ai_bridge/agent_loop.py` | Register monitoring alert job |

---

### Task 1: Database Migration

**Files:**
- Create: `database/migrations/060_monitoring_tables.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- 060_monitoring_tables.sql
-- Monitoring integration: Nagios check state + alert history

CREATE TABLE IF NOT EXISTS monitoring_checks (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(64) NOT NULL,
    check_name VARCHAR(128) NOT NULL,
    check_type VARCHAR(16) NOT NULL DEFAULT 'service',
    status VARCHAR(16) NOT NULL DEFAULT 'unknown',
    output TEXT,
    last_check TIMESTAMP WITH TIME ZONE,
    next_check TIMESTAMP WITH TIME ZONE,
    attempts INTEGER DEFAULT 0,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(node_id, check_name)
);
CREATE INDEX IF NOT EXISTS idx_monitoring_checks_status ON monitoring_checks(status);
CREATE INDEX IF NOT EXISTS idx_monitoring_checks_node ON monitoring_checks(node_id);

CREATE TABLE IF NOT EXISTS monitoring_alerts (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(64) NOT NULL,
    check_name VARCHAR(128) NOT NULL,
    old_status VARCHAR(16),
    new_status VARCHAR(16) NOT NULL,
    alerted_via VARCHAR(16) NOT NULL,
    message TEXT,
    alerted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    cooldown_until TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_monitoring_alerts_node ON monitoring_alerts(node_id, check_name);
CREATE INDEX IF NOT EXISTS idx_monitoring_alerts_time ON monitoring_alerts(alerted_at DESC);
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie -f /dev/stdin < database/migrations/060_monitoring_tables.sql
```
Expected: `CREATE TABLE` x2, `CREATE INDEX` x4

- [ ] **Step 3: Verify tables exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt monitoring_*"
```

- [ ] **Step 4: Commit**

```bash
git add database/migrations/060_monitoring_tables.sql
git commit -m "feat(monitoring): create monitoring_checks and monitoring_alerts tables"
```

---

### Task 2: Nagios Host & Service Configurations

**Files:**
- Create: `monitoring/nagios-conf.d/archie-starbase.cfg`
- Create: `monitoring/nagios-conf.d/outpost_us_001.cfg`

- [ ] **Step 1: Create directories**

```bash
mkdir -p /mnt/archie_brain/monitoring/nagios-conf.d
mkdir -p /mnt/archie_brain/monitoring/nagios-templates
```

- [ ] **Step 2: Write hub (Starbase) host definition**

Create `monitoring/nagios-conf.d/archie-starbase.cfg`:
```cfg
# A.R.C.H.I.E. Starbase Hub
# Auto-managed by ARCHIE monitoring service

define host {
    use                     linux-server
    host_name               archie-starbase
    alias                   A.R.C.H.I.E. Starbase Hub
    address                 192.168.1.200
    max_check_attempts      3
    check_interval          1
    retry_interval          0.5
    notification_interval   30
    notification_period     24x7
}

define hostgroup {
    hostgroup_name  archie-fleet
    alias           A.R.C.H.I.E. Fleet Nodes
    members         archie-starbase
}

define service {
    use                     generic-service
    host_name               archie-starbase
    service_description     Platform HTTP
    check_command           check_http!-p 3000 -u /health -s "ok"
    check_interval          3
    retry_interval          0.5
    max_check_attempts      3
}

define service {
    use                     generic-service
    host_name               archie-starbase
    service_description     PostgreSQL
    check_command           check_tcp!5432
    check_interval          3
    retry_interval          0.5
    max_check_attempts      3
}

define service {
    use                     generic-service
    host_name               archie-starbase
    service_description     Ollama API
    check_command           check_http!-p 11434 -u /api/tags -e "200"
    check_interval          3
    retry_interval          0.5
    max_check_attempts      3
}

define service {
    use                     generic-service
    host_name               archie-starbase
    service_description     Stalwart SMTP
    check_command           check_smtp!-p 587
    check_interval          3
    retry_interval          0.5
    max_check_attempts      3
}

define service {
    use                     generic-service
    host_name               archie-starbase
    service_description     Stalwart IMAP
    check_command           check_tcp!993
    check_interval          3
    retry_interval          0.5
    max_check_attempts      3
}

define service {
    use                     generic-service
    host_name               archie-starbase
    service_description     ComfyUI
    check_command           check_http!-p 8188 -e "200"
    check_interval          5
    retry_interval          1
    max_check_attempts      3
}
```

- [ ] **Step 3: Write outpost host definition**

Create `monitoring/nagios-conf.d/outpost_us_001.cfg`:
```cfg
# US Outpost — relay and proxy node
# Auto-managed by ARCHIE monitoring service

define host {
    use                     linux-server
    host_name               outpost_us_001
    alias                   US Outpost (76.13.107.109)
    address                 76.13.107.109
    max_check_attempts      3
    check_interval          1
    retry_interval          0.5
    notification_interval   30
    notification_period     24x7
    hostgroups              archie-fleet
}

define service {
    use                     generic-service
    host_name               outpost_us_001
    service_description     SMTP Relay
    check_command           check_smtp!-p 25
    check_interval          3
    retry_interval          0.5
    max_check_attempts      3
}

define service {
    use                     generic-service
    host_name               outpost_us_001
    service_description     Caddy HTTP
    check_command           check_http!-p 80 -e "200,301,302,308"
    check_interval          3
    retry_interval          0.5
    max_check_attempts      3
}

define service {
    use                     generic-service
    host_name               outpost_us_001
    service_description     Node API
    check_command           check_http!-p 3001 -u /health -e "200"
    check_interval          3
    retry_interval          0.5
    max_check_attempts      3
}
```

- [ ] **Step 4: Copy configs and validate**

```bash
docker cp monitoring/nagios-conf.d/archie-starbase.cfg monitoring_nagios:/opt/nagios/etc/conf.d/
docker cp monitoring/nagios-conf.d/outpost_us_001.cfg monitoring_nagios:/opt/nagios/etc/conf.d/
docker exec monitoring_nagios /opt/nagios/bin/nagios -v /opt/nagios/etc/nagios.cfg
```
Expected: `Total Warnings: 0`, `Total Errors: 0`, `Things look okay`

- [ ] **Step 5: Reload Nagios and verify**

```bash
docker exec monitoring_nagios kill -HUP 1
sleep 30
docker exec monitoring_nagios grep "host_name=archie-starbase" /opt/nagios/var/status.dat | head -3
```

- [ ] **Step 6: Commit**

```bash
git add monitoring/nagios-conf.d/
git commit -m "feat(monitoring): add Nagios host definitions for hub and outpost"
```

---

### Task 3: Docker Volume Sharing

**Files:**
- Modify: `/mnt/stacks/monitoring/docker-compose.yml` (not in git)
- Modify: `/mnt/archie_brain/docker-compose.yml`

- [ ] **Step 1: Add conf.d bind mount to Nagios**

Edit `/mnt/stacks/monitoring/docker-compose.yml`, add to nagios service volumes:
```yaml
      - /mnt/archie_brain/monitoring/nagios-conf.d:/opt/nagios/etc/conf.d:ro
```

- [ ] **Step 2: Mount Nagios data volume into ARCHIE platform**

Edit `/mnt/archie_brain/docker-compose.yml`, add to archie_platform volumes:
```yaml
      - monitoring_nagios_data:/opt/nagios-data:ro
```

Add to top-level volumes:
```yaml
  monitoring_nagios_data:
    external: true
```

- [ ] **Step 3: Recreate containers**

```bash
cd /mnt/stacks/monitoring && docker compose up -d nagios
cd /mnt/archie_brain && docker compose up -d archie_platform
```

- [ ] **Step 4: Verify mounts**

```bash
docker exec archie_platform ls /opt/nagios-data/status.dat
docker exec monitoring_nagios ls /opt/nagios/etc/conf.d/archie-starbase.cfg
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain && git add docker-compose.yml
git commit -m "feat(monitoring): mount Nagios data volume into ARCHIE platform"
```

---

### Task 4: Monitoring Service

**Files:**
- Create: `platform_v2/services/monitoring_service.py`

- [ ] **Step 1: Write the monitoring service**

Create `platform_v2/services/monitoring_service.py` with these functions:

1. `parse_status_dat()` — reads `/opt/nagios-data/status.dat`, parses `hoststatus` and `servicestatus` blocks into dicts, caches for 15 seconds
2. `get_unified_health()` — merges Nagios checks into per-host view with summary (ok/warning/critical)
3. `get_host_checks(node_id)` — returns checks for one host
4. `sync_checks_to_db()` — upserts Nagios check states into `monitoring_checks` table, returns list of state changes
5. `process_alerts(changes)` — routes state changes: critical/recovery to Telegram via `send_system()`, warnings to email record
6. `_is_in_cooldown()` / `_record_alert()` — dedup helpers using `monitoring_alerts` table
7. `generate_node_config(node)` — renders Jinja template to `monitoring/nagios-conf.d/{node_id}.cfg`
8. `remove_node_config(node_id)` — deletes config file
9. `reload_nagios()` — validates config via `docker exec`, sends SIGHUP

Key implementation details:
- `parse_status_dat()` uses regex to find `hoststatus { ... }` and `servicestatus { ... }` blocks
- Status mapping: Nagios `current_state` 0=ok, 1=warning, 2=critical, 3=unknown
- Alert cooldowns: critical=5min, warning=60min
- Template dir: `monitoring/nagios-templates/`
- Config output dir: `monitoring/nagios-conf.d/`
- Use `from services.telegram_service import send_system` for Telegram alerts
- Use DOM-safe text rendering (textContent) in all JS — no innerHTML with untrusted content

- [ ] **Step 2: Verify module loads**

```bash
docker compose restart archie_platform
docker exec archie_platform python3 -c "from services.monitoring_service import parse_status_dat; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/services/monitoring_service.py
git commit -m "feat(monitoring): add monitoring service with status.dat parser and alert routing"
```

---

### Task 5: Health API Routes

**Files:**
- Create: `platform_v2/tools/starship/health_routes.py`
- Modify: `platform_v2/tools/starship/__init__.py`

- [ ] **Step 1: Write health routes**

Create `platform_v2/tools/starship/health_routes.py` with `register_health_routes(bp, auth_decorator)`:

1. `GET /api/health-status` — returns `{ success, summary: {total, ok, warning, critical}, hosts: [{node_id, summary, host_status, services: [{name, status, output, last_check}]}] }`
2. `GET /api/health-status/<node_id>` — returns checks for one host

Both call `monitoring_service.get_unified_health()` / `get_host_checks()`.

- [ ] **Step 2: Register in __init__.py**

Add after existing `register_*_routes` calls:
```python
from .health_routes import register_health_routes
register_health_routes(starship_bp, login_required)
```

- [ ] **Step 3: Verify and commit**

```bash
docker compose restart archie_platform
git add platform_v2/tools/starship/health_routes.py platform_v2/tools/starship/__init__.py
git commit -m "feat(monitoring): add health API routes to Starship Command"
```

---

### Task 6: Agent Loop Job

**Files:**
- Modify: `ai_bridge/agent_loop.py`

- [ ] **Step 1: Register monitoring job**

Find the job registration section (near line 667 where `agent_fleet_health` is). Add:
```python
self.scheduler.add_job(
    with_app_context(self._process_monitoring_alerts),
    "interval", seconds=60,
    id="agent_monitoring_alerts",
    name="Monitoring Alert Processor",
    replace_existing=True,
)
```

- [ ] **Step 2: Add job method**

```python
def _process_monitoring_alerts(self):
    """Sync Nagios check states to DB and route alerts."""
    try:
        from services.monitoring_service import sync_checks_to_db, process_alerts
        changes = sync_checks_to_db()
        if changes:
            process_alerts(changes)
            logger.info("[AgentLoop] Monitoring: %d state changes", len(changes))
    except Exception as e:
        logger.error("[AgentLoop] Monitoring alerts failed: %s", e)
```

- [ ] **Step 3: Add department mapping**

Add to the job department mapping:
```python
"monitoring_alerts": "Operations & Infrastructure",
```

- [ ] **Step 4: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(monitoring): add agent loop job for Nagios alert processing"
```

---

### Task 7: Starship Command HEALTH Tab

**Files:**
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html`
- Modify: `platform_v2/static/js/starship.js`
- Modify: `platform_v2/static/css/starship.css`

- [ ] **Step 1: Add HEALTH tab button in HTML**

Find the FLEET tab button. Add after it:
```html
<button class="sc-page-tab" data-page-tab="health" onclick="switchPageTab('health')">HEALTH</button>
```

- [ ] **Step 2: Add HEALTH page panel in HTML**

After `</div><!-- /page-fleet -->`, add:
```html
<div class="sc-page-panel" id="page-health">
    <div class="sc-health-summary" id="health-summary">
        <span class="sc-health-badge ok" id="health-ok">0 OK</span>
        <span class="sc-health-badge warning" id="health-warn">0 WARNING</span>
        <span class="sc-health-badge critical" id="health-crit">0 CRITICAL</span>
    </div>
    <div class="sc-health-hosts" id="health-hosts">
        <p class="sc-static">Loading health checks...</p>
    </div>
</div>
```

- [ ] **Step 3: Add CSS for health tab**

Add to `starship.css`:
- `.sc-health-summary` — flex row of badge counts
- `.sc-health-badge.ok/warning/critical` — colored count badges
- `.sc-health-host` — per-host accordion card
- `.sc-health-check` — individual check row with status dot, name, output, timestamp
- `.sc-health-dot.ok/warning/critical/unknown` — 8px colored dots (critical pulses)

- [ ] **Step 4: Add JS for health tab**

Add `loadHealthStatus()` function to `starship.js`:
- Fetches `/tools/starship/api/health-status`
- Updates summary badge counts
- Builds per-host accordion with service checks using DOM methods (createElement, textContent — no innerHTML)
- Each host header is clickable to expand/collapse checks

Hook into `switchPageTab()`:
```javascript
if (tab === 'health') { loadHealthStatus(); }
```

Add 30-second auto-refresh when health tab is active.

- [ ] **Step 5: Add health dots to docked fleet strip**

In `loadDockedFleetStats()`, add a secondary fetch to `/api/health-status` that overlays critical/warning indicators on node dots.

- [ ] **Step 6: Deploy and verify**

```bash
docker compose restart archie_platform
```
Browse to Starship Command, click HEALTH tab. Verify check results display.

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/starship/templates/tools/starship/starship.html \
        platform_v2/static/js/starship.js \
        platform_v2/static/css/starship.css
git commit -m "feat(monitoring): add HEALTH tab to Starship Command"
```

---

### Task 8: Auto-Config Templates

**Files:**
- Create: `monitoring/nagios-templates/outpost.cfg.j2`
- Create: `monitoring/nagios-templates/starship.cfg.j2`
- Modify: `platform_v2/services/monitoring_service.py`

- [ ] **Step 1: Create outpost template**

`monitoring/nagios-templates/outpost.cfg.j2` — host definition + SMTP, HTTP, Node API checks using Jinja vars `{{ node_id }}`, `{{ node_name }}`, `{{ hostname }}`

- [ ] **Step 2: Create starship template**

`monitoring/nagios-templates/starship.cfg.j2` — host definition + Ollama API, Node API checks

- [ ] **Step 3: Add auto-config functions to monitoring_service.py**

Add `generate_node_config(node)`, `remove_node_config(node_id)`, `reload_nagios()`:
- `generate_node_config` uses Jinja2 `Environment(loader=FileSystemLoader)` to render template
- Selects template by `node["deployment_mode"]`
- Writes to `monitoring/nagios-conf.d/{node_id}.cfg`
- `reload_nagios()` validates via `docker exec monitoring_nagios nagios -v`, then sends SIGHUP

- [ ] **Step 4: Commit**

```bash
git add monitoring/nagios-templates/ platform_v2/services/monitoring_service.py
git commit -m "feat(monitoring): add Nagios auto-config templates and generator"
```

---

## Notes

- **Email digest:** Alert records with `alerted_via='email'` are stored but batch email sending is a follow-up task. Telegram covers all critical alerts immediately.
- **SSL cert check:** Hub only for now (Stalwart on :8443). Outpost certs checked via Caddy HTTPS check.
- **Disk checks on remote nodes:** Uses ARCHIE heartbeat data (already sent), not Nagios NRPE. Monitoring service can threshold-check heartbeat `memory_usage` and flag in the unified view.
