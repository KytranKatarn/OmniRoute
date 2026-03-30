# Fleet Monitoring Strategy — Hybrid Nagios + ARCHIE

**Date**: 2026-03-30
**Task**: #1499
**Status**: Design approved

---

## Context

The A.R.C.H.I.E. platform has a growing fleet (hub + US outpost + future GPU nodes) but no unified monitoring or alerting. Nagios is running (`monitoring_nagios` container on `:8082`) with default sample config only. ARCHIE has a heartbeat system that tracks node liveness and CPU/MEM, but no service-level checks or alerting beyond UI status changes.

Home IP (142.169.21.199) is Spamhaus-blocked, making the outpost relay critical infrastructure that must be monitored.

## Decision

**Hybrid approach (Option C)**: Nagios as a headless check engine for infrastructure monitoring. ARCHIE handles fleet-specific monitoring (heartbeats, agents, models, dispatch). A new monitoring service merges both into a unified view in Starship Command. Auto-config generates Nagios host definitions when nodes register.

## Architecture

```
ARCHIE Platform
  Starship Command  <--  Monitoring Service  -->  Alert Router
  (unified view)         (Nagios + heartbeats)     (Telegram + Email)
                              |
              +---------------+---------------+
              |                               |
     Nagios (headless)              ARCHIE Heartbeats
     - check_ping                   - node alive/offline
     - check_http                   - agent shift status
     - check_smtp                   - model loaded/cold
     - check_disk                   - dispatch health
     - check_ssl                    - job completion
     - check_docker                 - queue depth
```

## Component 1: Nagios Configuration

### Headless mode
- Disable Apache web UI (not needed — ARCHIE surfaces everything)
- Keep `status.dat` file updated (Nagios does this by default every 10 seconds)
- ARCHIE reads `status.dat` via volume mount for check results

### Check templates by node type

**Starbase (hub — 192.168.1.200):**
| Check | Command | Warning | Critical |
|-------|---------|---------|----------|
| Host alive | check_ping | 100ms,20% | 500ms,60% |
| Platform HTTP | check_http -p 3000 | - | timeout 10s |
| PostgreSQL | check_tcp -p 5432 | - | refused |
| Ollama API | check_http -p 11434 /api/tags | - | timeout 10s |
| Stalwart SMTP | check_smtp -p 587 | - | refused |
| Stalwart IMAP | check_tcp -p 993 | - | refused |
| ComfyUI | check_http -p 8188 | - | timeout 10s |
| Headscale | check_tcp -p 8080 | - | refused |
| Disk / | check_disk -w 20% -c 10% | 80% | 90% |
| Disk /mnt/archie_brain | check_disk -w 20% -c 10% | 80% | 90% |
| Disk /mnt/llm_drive | check_disk -w 15% -c 5% | 85% | 95% |
| Disk /mnt/data2 | check_disk -w 20% -c 10% | 80% | 90% |
| CPU | check_load | 8,6,4 | 12,10,8 |
| RAM | check_mem | 90% | 95% |
| SSL cert | check_http --ssl -C 30,14 | 30 days | 14 days |

**Outpost (76.13.107.109):**
| Check | Command | Warning | Critical |
|-------|---------|---------|----------|
| Host alive | check_ping | 100ms,20% | 500ms,60% |
| SMTP relay | check_smtp -H 76.13.107.109 -p 25 | - | refused |
| Caddy HTTP | check_http -H 76.13.107.109 -p 80 | - | timeout |
| Caddy HTTPS | check_http -H 76.13.107.109 -p 443 --ssl | - | timeout |
| Node API | check_http -H 76.13.107.109 -p 3001 /health | - | timeout |
| Disk | check_by_ssh or NRPE | 80% | 90% |
| CPU | check_by_ssh or NRPE | 80% | 90% |

**Starship (GPU node — template):**
| Check | Command | Warning | Critical |
|-------|---------|---------|----------|
| Host alive | check_ping | 100ms,20% | 500ms,60% |
| Ollama API | check_http -p 11434 /api/tags | - | timeout |
| Node API | check_http -p 3001 /health | - | timeout |
| Disk | check_by_ssh or NRPE | 80% | 90% |
| CPU | check_load | 80% | 90% |

### Check intervals
- Host alive: every 1 minute
- Services: every 3 minutes
- Disk/certs: every 15 minutes
- Retry before alerting: 3 attempts, 30 seconds apart

### Remote checks
- Hub services: checked locally from Nagios container (same host)
- Outpost/nodes: `check_http` and `check_tcp` over network (no agent needed for port checks)
- Disk/CPU on remote nodes: via ARCHIE heartbeat data (already sent), not NRPE. Monitoring service checks heartbeat metrics against thresholds.

## Component 2: Monitoring Service

**File**: `platform_v2/services/monitoring_service.py`

### Functions
```python
get_unified_health()           # Merged Nagios + heartbeat status for all hosts
get_host_checks(node_id)       # All Nagios checks for one host
get_check_history(node_id, check_name, hours=24)  # Historical data

generate_node_config(node)     # Write Nagios .cfg from template
remove_node_config(node_id)    # Delete .cfg and reload Nagios
reload_nagios()                # Validate config then SIGHUP

process_alerts()               # Compare current vs last state, route alerts
```

### status.dat parsing
- Nagios writes `/opt/nagios/var/status.dat` every 10 seconds
- Mount this file into `archie_platform` container as read-only volume
- Parse `hoststatus` and `servicestatus` blocks
- Cache parsed results for 15 seconds (avoid re-parsing on every request)

### Auto-config flow
1. Node registers via heartbeat endpoint (already exists)
2. After first successful heartbeat, monitoring service calls `generate_node_config(node)`
3. Template selected by `deployment_mode`: starbase, outpost, starship
4. Config written to `/opt/nagios/etc/conf.d/{node_id}.cfg`
5. `reload_nagios()` validates and sends SIGHUP
6. Node deregisters (disconnect) -> config file removed, reload

## Component 3: Alert Router

### Agent loop job (#59) — runs every 60 seconds
1. Parse `status.dat` for current check states
2. Query `monitoring_checks` table for previous states
3. On state change: determine severity and route

### Alert routing

| Condition | Channel | Timing |
|-----------|---------|--------|
| Host DOWN | Telegram | Immediate |
| Service CRITICAL | Telegram | Immediate |
| Recovery (was critical, now OK) | Telegram | Immediate |
| Service WARNING | Email | Batched hourly |
| Disk >80% | Email | Once per day |
| Cert expires <14 days | Telegram | Once per day |
| Cert expires <30 days | Email | Once per week |

### Deduplication
- Don't re-alert for the same problem within cooldown window
- Critical: 5 minute cooldown (re-alert if still down after 5 min)
- Warning: 1 hour cooldown
- Stored in `monitoring_alerts` table

### Telegram integration
- Uses existing `TELEGRAM_BOT_TOKEN` from platform
- Alert format: `[CRITICAL] Hub: Stalwart SMTP down since 14:32 UTC`
- Recovery format: `[RECOVERED] Hub: Stalwart SMTP back online (was down 8 min)`

### Email integration
- Uses Stalwart via ARCHIE's existing SMTP config
- Daily summary: all warnings from last 24 hours
- Weekly report: cert expiry status, disk trends, uptime stats

## Component 4: Starship Command Integration

### New "HEALTH" tab on Starship Command page
- Top: summary badges — `12 OK | 1 WARNING | 0 CRITICAL`
- Per-host accordion sections: Hub, Outpost, each fleet node
- Each host shows: check name, status dot (green/amber/red), last check time, output text
- Auto-refreshes every 30 seconds (same interval as fleet data)

### Docked fleet strip enhancement
- Add small health indicator to each node card
- Green circle: all checks pass
- Amber circle: one or more warnings
- Red circle: any critical check
- Uses CSS class on existing node dot or a second indicator

### Node detail modal
- Add "HEALTH" sub-tab alongside STATUS, DIAG, OTA, STATIONS, CREW
- Shows all Nagios checks for that specific node
- Check history sparkline (last 24h pass/fail)

## Component 5: Database

### `monitoring_checks` — latest state per check
```sql
CREATE TABLE monitoring_checks (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(64) NOT NULL,
    check_name VARCHAR(128) NOT NULL,
    check_type VARCHAR(16) NOT NULL DEFAULT 'service',  -- host or service
    status VARCHAR(16) NOT NULL DEFAULT 'unknown',       -- ok, warning, critical, unknown
    output TEXT,
    last_check TIMESTAMP WITH TIME ZONE,
    next_check TIMESTAMP WITH TIME ZONE,
    attempts INTEGER DEFAULT 0,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(node_id, check_name)
);
CREATE INDEX idx_monitoring_checks_status ON monitoring_checks(status);
```

### `monitoring_alerts` — alert history and dedup
```sql
CREATE TABLE monitoring_alerts (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(64) NOT NULL,
    check_name VARCHAR(128) NOT NULL,
    old_status VARCHAR(16),
    new_status VARCHAR(16) NOT NULL,
    alerted_via VARCHAR(16) NOT NULL,  -- telegram, email
    message TEXT,
    alerted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    cooldown_until TIMESTAMP WITH TIME ZONE
);
CREATE INDEX idx_monitoring_alerts_node ON monitoring_alerts(node_id, check_name);
CREATE INDEX idx_monitoring_alerts_time ON monitoring_alerts(alerted_at DESC);
```

## Docker Changes

### Nagios container updates (`monitoring/docker-compose.yml`)
- Disable Apache: set `NAGIOS_WEB=false` or remove port mapping
- Add volume mount for config auto-generation: `./nagios-conf.d:/opt/nagios/etc/conf.d`
- Share `status.dat` with ARCHIE: mount Nagios data volume into `archie_platform`

### ARCHIE platform container
- Add read-only volume mount: `monitoring_nagios_data:/opt/nagios-data:ro`
- Monitoring service reads `/opt/nagios-data/status.dat`

## Implementation Order

1. **Database migration** — create `monitoring_checks` and `monitoring_alerts` tables
2. **Nagios config** — write hub + outpost host definitions, configure real checks
3. **status.dat parser** — monitoring service reads and caches Nagios output
4. **Auto-config generator** — template-based .cfg generation for new nodes
5. **Alert router** — agent loop job for state change detection + Telegram/email routing
6. **Starship Command HEALTH tab** — unified view in the UI
7. **Fleet strip health indicators** — small health dot on node cards

## Verification

- Nagios checks running: `docker exec monitoring_nagios /opt/nagios/bin/nagios -v /opt/nagios/etc/nagios.cfg`
- status.dat accessible: `docker exec archie_platform cat /opt/nagios-data/status.dat | head`
- Unified health API: `GET /tools/starship/api/health-status` returns merged Nagios + heartbeat data
- Alert test: stop a service, verify Telegram alert within 3 minutes
- Auto-config: register a new node, verify Nagios config generated and checks start
- Starship HEALTH tab: shows all checks with correct status colors
