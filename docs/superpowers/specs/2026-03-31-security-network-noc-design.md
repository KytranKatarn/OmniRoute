# Security Network NOC — Design Spec

**Date:** 2026-03-31
**Project:** Security Network Module Review & Optimization
**Sub-project:** 1 of 4 (NOC → Surveillance → HA Integration → Mobile/Voice)
**Approach:** B — AdGuard + ntopng + Nagios + fail2ban + V.I.G.I.L. Agent

---

## Problem Statement

The Security Network module has 129+ routes and 9 service classes but several features are broken, stubbed, or misconfigured:
- **ntopng**: crash-looping 10,544 times (missing Redis dependency)
- **Ollama**: crash-looping 183,081 times (wrong model path) — FIXED during brainstorm
- **fail2ban**: health-check only, no management endpoints
- **DDNS**: health-check only, no management endpoints
- **Nagios**: running and healthy but not integrated into ARCHIE
- **Traffic monitoring**: referenced in code but no actual endpoints
- **Bandwidth tracking**: completely missing
- **Daily reports**: no per-device or per-user consumption reports
- **Log rotation**: was unlimited, causing 88GB syslog — FIXED during brainstorm

Additionally, there is no AI agent continuously monitoring the network. V.I.G.I.L. (Security & Compliance director) should be actively working this data via the Autonomy module.

## Decisions Made During Brainstorm

- **Approach B selected**: AdGuard (DNS intelligence) + ntopng (bandwidth/flows) + Nagios (host/service monitoring) + fail2ban (intrusion defense)
- **No new hardware required**: ntopng already deployed, Nagios already running, AdGuard already running
- **1 NIC limitation acknowledged**: ntopng sees ARCHIE's traffic only (all DNS flows since ARCHIE is the DNS server). Future managed switch + 2nd NIC upgrades to full network capture.
- **Autonomy module owns all agent jobs**: registered under Security & Compliance department (V.I.G.I.L.), not embedded in Security Network module code
- **Auto-defense with severity tiers**: auto-block high severity, alert medium, log low
- **Reports via all channels**: dashboard + Telegram + email
- **Device-to-user mapping**: group devices by person for per-user reports

## Infrastructure Fixes (Already Done)

| Fix | What | Result |
|-----|------|--------|
| Log cleanup | Deleted 4 rotated logs (syslog.1=88GB, auth.log.1=8.8GB, kern.log.1=5.1GB, ufw.log.1=830MB) | 102.7GB freed |
| Journal vacuum | Trimmed systemd journal | 1.8GB freed |
| Ollama | Fixed model path in override.conf (`/mnt/data2/` → `/mnt/llm_drive/`) | Running (was 183K restarts) |
| ntopng | Stopped crash loop, disabled auto-restart (will fix properly in Phase 1) | No longer spamming logs |
| Log rotation | Set `maxsize 1G` + `daily` + `rotate 4` in rsyslog config | Max 4GB total logs |
| Journal limit | Set `SystemMaxUse=500M` in journald config | Capped at 500MB |
| Disk | 106GB free (74%) | Was 0GB free (100% full) |

## Data Sources

| Component | Role | Current Status | Port |
|-----------|------|---------------|------|
| **AdGuard Home** | DNS intelligence — queries, blocks, filters, per-client stats | Running (Docker `network_adguard`) | 53 (DNS), 5354 (UI), 5355 (API) |
| **ntopng** | Real bandwidth — bytes in/out, protocol ID, flows, top talkers | Stopped (needs Redis) | 3001→3000 |
| **Nagios** | Host/service health — uptime, check results, performance data, alerts | Running healthy (Docker `monitoring_nagios`) | 8082→80 |
| **fail2ban** | Intrusion defense — brute force detection, IP bans, jail management | Running on host | N/A (CLI) |
| **DDNS** | IP change tracking — cron updates Hostinger A records every 5min | Cron running | N/A (script) |
| **UFW** | Firewall — inbound/outbound rules, connection logs | Running on host | N/A (CLI) |
| **nmap** | Device discovery — ARP scans for new/unknown devices | Endpoints exist | N/A (CLI) |
| **syslog/auth.log** | System logs — crash loops, auth failures, kernel events | Running (rotation fixed) | N/A (files) |

### Data Flow

```
Network devices → AdGuard (DNS queries) ──→ ARCHIE DB (network_dns_stats)
               → ntopng (traffic flows)  ──→ ARCHIE DB (network_traffic_stats)
               → Nagios (health checks)  ──→ ARCHIE DB (nagios_check_results)
Host services  → fail2ban (auth events)  ──→ ARCHIE DB (security_events)
               → syslog (system events)  ──→ ARCHIE DB (network_alerts)
               → UFW (firewall events)   ──→ ARCHIE DB (security_events)

All data ──→ V.I.G.I.L. Agent (Autonomy Module) ──→ Analysis + Response + Reports
```

## Dashboard Design — 8 Tabs

### Tab 1: Overview (NOC Command View)
- Hero stats: Network Status (SECURE/WARNING/CRITICAL), Devices Online, Threats Blocked (24h), Traffic Today
- Service health panel: status of AdGuard, ntopng, Nagios, fail2ban, DDNS, UFW, Ollama
- V.I.G.I.L. activity feed: recent auto-blocks, new devices, anomalies, reports generated
- Top bandwidth consumers bar chart (per device, 24h)

### Tab 2: Traffic
- Real-time bandwidth graph (ntopng data, 5-min intervals)
- Per-device throughput table with sort/filter
- Protocol breakdown pie chart (streaming, web, download, IoT, other)
- Top domains by traffic volume
- Flow table with source/dest/protocol/bytes

### Tab 3: DNS (AdGuard Control)
- Full AdGuard management: query log, filter lists (add/toggle/remove/refresh)
- Custom blocking/allow rules editor
- DNS rewrites management
- Client settings (per-device DNS policy)
- Protection toggle (enable/disable)
- Query stats: total, blocked, block rate, top queried domains, top blocked domains
- All 18 existing AdGuard endpoints surfaced in UI

### Tab 4: Devices
- Network inventory: all discovered devices with MAC, IP, hostname, manufacturer, first/last seen
- Device-to-user mapping: assign devices to named users (for per-user reports)
- Unknown device alerts: flag new/unregistered devices
- Device types: auto-classify (phone, laptop, TV, IoT, server, camera)
- Online/offline status with last-seen timestamp

### Tab 5: Defense
- **fail2ban**: list jails, view active bans, ban/unban IPs, configure jail rules
- **UFW firewall**: view rules, add/remove rules
- **IP access control**: whitelist/blacklist management (existing endpoints)
- **Auto-block settings**: configure severity thresholds, review auto-blocked IPs
- **DDNS**: current public IP, IP change history, manual trigger update, last update timestamp
- **Nagios alerts**: host/service problems, acknowledgements

### Tab 6: Scanners
- Existing scanner tools: nmap, nikto, nuclei, SSL, OWASP ZAP
- Already built — UI polish only
- Scan history and results viewer

### Tab 7: Compliance
- Existing compliance engine: STIG, SOC2, CIS, HIPAA scans
- Badge dashboard with live scores
- Evidence collection and CKL export
- Already built — no changes needed

### Tab 8: Reports
- Daily device report: per-device bandwidth, DNS queries, blocked requests, top domains
- Daily user report: per-user (grouped devices) total consumption, activity summary
- Weekly network report: trends, top consumers, threat summary, compliance scores
- Threat reports: auto-generated on high-severity events
- On-demand report generator: custom date range, device/user filter, PDF export
- Report delivery log: what was sent via which channel

## Database Schema

### New Tables

```sql
-- Hourly bandwidth aggregates from ntopng
CREATE TABLE network_traffic_stats (
    id SERIAL PRIMARY KEY,
    device_mac VARCHAR(17),
    device_ip VARCHAR(45),
    bytes_in BIGINT DEFAULT 0,
    bytes_out BIGINT DEFAULT 0,
    protocol VARCHAR(50),
    hour_bucket TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_traffic_stats_hour ON network_traffic_stats(hour_bucket);
CREATE INDEX idx_traffic_stats_device ON network_traffic_stats(device_mac);

-- Device-to-user mapping
CREATE TABLE network_device_users (
    id SERIAL PRIMARY KEY,
    mac_address VARCHAR(17) UNIQUE NOT NULL,
    user_name VARCHAR(100) NOT NULL,
    device_label VARCHAR(200),
    device_type VARCHAR(50) DEFAULT 'unknown',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Hourly DNS query aggregates from AdGuard
CREATE TABLE network_dns_stats (
    id SERIAL PRIMARY KEY,
    client_ip VARCHAR(45),
    total_queries INTEGER DEFAULT 0,
    blocked_queries INTEGER DEFAULT 0,
    top_domains JSONB DEFAULT '[]',
    hour_bucket TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_dns_stats_hour ON network_dns_stats(hour_bucket);
CREATE INDEX idx_dns_stats_client ON network_dns_stats(client_ip);

-- Generated reports
CREATE TABLE network_daily_reports (
    id SERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    report_type VARCHAR(50) NOT NULL,
    data_json JSONB NOT NULL,
    pdf_path VARCHAR(500),
    delivered_via JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW()
);

-- DDNS IP change history
CREATE TABLE network_ip_history (
    id SERIAL PRIMARY KEY,
    old_ip VARCHAR(45),
    new_ip VARCHAR(45) NOT NULL,
    changed_at TIMESTAMP DEFAULT NOW(),
    dns_updated BOOLEAN DEFAULT FALSE,
    subdomains_updated JSONB DEFAULT '[]'
);

-- NOC alerts
CREATE TABLE network_alerts (
    id SERIAL PRIMARY KEY,
    alert_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    source VARCHAR(50) NOT NULL,
    title VARCHAR(300) NOT NULL,
    details JSONB DEFAULT '{}',
    auto_action_taken VARCHAR(200),
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by VARCHAR(100),
    acknowledged_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_alerts_severity ON network_alerts(severity);
CREATE INDEX idx_alerts_created ON network_alerts(created_at);

-- Cached Nagios check results
CREATE TABLE nagios_check_results (
    id SERIAL PRIMARY KEY,
    host_name VARCHAR(200) NOT NULL,
    service_description VARCHAR(200),
    status VARCHAR(20) NOT NULL,
    output TEXT,
    performance_data TEXT,
    last_check TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_nagios_host_service ON nagios_check_results(host_name, service_description);
```

### Existing Tables (No Changes)
- `security_events` — threat events
- `security_ip_access` — IP whitelist/blacklist
- `security_scan_results` — scanner output
- `security_recon_scans` — scan metadata
- `security_reports` — existing reports
- `network_devices` — device inventory (add FK to `network_device_users`)
- `audit_log` — admin action logging
- `governance_audit_log` — V.I.G.I.L. autonomy actions

### Data Retention
- `network_traffic_stats`: 90 days, then aggregate to monthly summary
- `network_dns_stats`: 90 days
- `network_alerts`: 1 year
- `network_daily_reports`: indefinite (PDFs on disk)
- `nagios_check_results`: 30 days (Nagios keeps own history)

## V.I.G.I.L. Agent Integration (Autonomy Module)

All jobs registered under **Security & Compliance department** in the Autonomy module. V.I.G.I.L. is the AI Director. Jobs are visible, toggleable, and governed through the Autonomy module UI.

### Agent Loop Jobs

| Job | Frequency | Action | Autonomy Tier |
|-----|-----------|--------|---------------|
| **Network Health Monitor** | 60s | Poll AdGuard/ntopng/Nagios/fail2ban/DDNS/UFW. Detect service down, crash loops, disk fill. | Tier 1 (auto-restart, alert if fails) |
| **Threat Responder** | 30s | Check fail2ban bans, AdGuard malware queries, ntopng suspicious flows, Nagios critical alerts. | Tier 1 (auto-block high), Tier 2 (alert medium) |
| **Device Watcher** | 5min | ARP scan + AdGuard clients + ntopng hosts. Detect new/unknown devices. | Tier 2 (alert + optional quarantine) |
| **DNS Anomaly Detector** | 5min | Analyze AdGuard query patterns. Detect DNS tunneling, tracking spikes, unusual TLDs. | Tier 1 (auto-block known-bad), Tier 2 (alert suspicious) |
| **Traffic Aggregator** | 5min | Pull ntopng + AdGuard stats, write to `network_traffic_stats` and `network_dns_stats`. | Tier 1 (auto, data collection) |
| **Nagios Sync** | 2min | Pull Nagios check results via API, cache in `nagios_check_results`. | Tier 1 (auto, data collection) |
| **Bandwidth Reporter** | Daily 06:00 | Aggregate traffic + DNS data into daily reports. Generate PDF. Deliver via Telegram + email. | Tier 1 (auto-generate + deliver) |
| **Log Health Monitor** | 15min | Check log file sizes. Detect spam patterns (like the 88GB syslog). Alert if any log > 500MB. | Tier 1 (alert), Tier 2 (force rotate if critical) |

### Autonomy Tiers
- **Tier 1 (auto):** Service restarts, IP blocks on known-bad, DDNS updates, data collection, log rotation, report generation
- **Tier 2 (alert + auto):** Unknown device quarantine, DNS rule additions, firewall changes, new Nagios host registration
- **Tier 3 (human approval via Telegram):** Network-wide policy changes, disabling protection, whitelisting blocked IPs

## Implementation Phases

### Phase 1 — Fix & Stabilize (Foundation)
- Fix ntopng: add Redis sidecar container, proper docker-compose entry, network config
- Enable full AdGuard: push DNS to all devices via router DHCP config
- Add fail2ban management endpoints: list jails, view/add/remove bans, configure rules
- Add DDNS management endpoints: view IP history, trigger manual update, change log
- Integrate Nagios REST API: pull host/service status, check results, performance data
- Create `network_device_users` table and device-to-user mapping UI
- Create `network_ip_history` table
- Audit all 129 existing routes — verify each works or remove dead code
- Create docker-compose entry for ntopng + redis in the network-tools stack

### Phase 2 — Traffic Intelligence (New Capabilities)
- ntopng REST API integration: poll bandwidth, flows, protocol data
- Build `network_traffic_stats` table + Traffic Aggregator polling job
- AdGuard stats aggregation: hourly DNS summaries per device into `network_dns_stats`
- Build `nagios_check_results` table + Nagios Sync polling job
- Device inventory enhancement: auto-discover via ARP + AdGuard + ntopng + Nagios host list
- Build `network_alerts` table + alert ingestion from all sources

### Phase 3 — Dashboard & UI (Visibility)
- Build 8-tab UI: Overview, Traffic, DNS, Devices, Defense, Scanners, Compliance, Reports
- Overview: NOC command view with hero stats, service health, V.I.G.I.L. feed, top consumers
- Traffic: real-time bandwidth graphs, per-device throughput, protocol breakdown
- DNS: full AdGuard control panel (all 18 endpoints surfaced)
- Devices: inventory with user mapping, unknown device flagging
- Defense: fail2ban + DDNS + UFW management panels, Nagios alerts
- Polish existing Scanners and Compliance tabs

### Phase 4 — V.I.G.I.L. Agent & Reports (Intelligence)
- Register all 8 agent loop jobs in Autonomy module under Security & Compliance department
- Build report generation engine: daily device, daily user, weekly network, threat reports
- Telegram + email delivery integration (using existing Stalwart mail + Telegram bot)
- DNS anomaly detection: tunneling, tracking spikes, unusual TLDs
- Log health monitoring: size alerts, spam detection
- Auto-response actions: block, quarantine, restart, alert — all logged to governance_audit_log
- Nagios alert → V.I.G.I.L. threat response pipeline

## Network Configuration

### AdGuard DHCP Push
- Log into Telus router at 192.168.1.254
- Set primary DNS to 192.168.1.200 (AdGuard)
- Set secondary DNS to 1.1.1.1 (fallback if ARCHIE is down)
- All devices will automatically use AdGuard within DHCP lease renewal

### ntopng Docker Config
```yaml
# In network-tools docker-compose
network_redis:
  image: redis:7-alpine
  container_name: network_redis
  restart: unless-stopped
  ports:
    - "127.0.0.1:6379:6379"
  volumes:
    - network_redis_data:/data
  networks:
    - network_tools_network

network_ntopng:
  image: ntop/ntopng:v6-pinned
  container_name: network_ntopng
  restart: unless-stopped
  network_mode: host
  environment:
    - NTOPNG_HTTP_PORT=3001
  command: --redis 127.0.0.1:6379 -i eth0 -w 3001
  volumes:
    - network_ntopng_data:/var/lib/ntopng
```

Note: `network_mode: host` lets ntopng see all traffic on the host's eth0 interface. Since ntopng uses host networking, it can't use Docker DNS to reach Redis. Instead, Redis exposes port 6379 on localhost (127.0.0.1) and ntopng connects via `127.0.0.1:6379`. The `depends_on` directive is removed because host-mode containers can't use it — startup ordering will be handled by the compose file order + ntopng's built-in Redis retry logic.

### Nagios API Access
- URL: http://192.168.1.200:8082
- API: Nagios CGI endpoints (`/nagios/cgi-bin/statusjson.cgi`, etc.)
- Credentials: stored in `.env` as `NAGIOS_USER` / `NAGIOS_PASS`

### Credentials (All in .env)
- `ADGUARD_USER` / `ADGUARD_PASS` — AdGuard admin
- `NAGIOS_USER` / `NAGIOS_PASS` — Nagios API access
- `NTOPNG_ADMIN_PASSWORD` — ntopng web UI (currently: see container env)
- `HOSTINGER_API_KEY` — DNS API for DDNS updates

## Future Sub-Projects (Not This Spec)

| # | Sub-Project | Dependency |
|---|-------------|-----------|
| 2 | Surveillance System — camera motion detection, recording, playback, alerts | HA integration |
| 3 | Home Assistant Deep Integration — full HA device control in ARCHIE | HA Docker config |
| 4 | Mobile & Voice Access — Android app, Wear OS, Google Assistant | HA + ARCHIE API |

## Success Criteria

- All 5 data sources (AdGuard, ntopng, Nagios, fail2ban, DDNS) feeding data into ARCHIE
- No crash-looping services
- Per-device and per-user daily consumption reports generated and delivered
- V.I.G.I.L. auto-blocking high-severity threats within 30 seconds
- Unknown devices detected and alerted within 5 minutes
- 8-tab dashboard fully functional with live data
- All agent loop jobs visible and toggleable in Autonomy module
