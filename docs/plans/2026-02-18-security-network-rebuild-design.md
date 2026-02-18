# Security & Network Module Rebuild — Full Design

**Date**: 2026-02-18
**Project**: Platform UI Overhaul (Project #94, Task #630)
**Module**: `security_network` (`/platform_v2/tools/security_network/`)
**Status**: Design Approved

---

## 1. Overview

Full rebuild of the Security & Network module from a basic single-page layout into a comprehensive 7-tab security operations center. Integrates AdGuard DNS management, Hostinger public DNS, Blink camera surveillance via Home Assistant, Argus reconnaissance toolkit, vulnerability scanners, and AI agent automation with suggest-only defaults.

### Goals

- Centralize all security and network operations in one module
- Provide full AdGuard DNS management (replacing need for AdGuard's own UI)
- Integrate Blink security cameras via Home Assistant REST API
- Wrap Argus reconnaissance toolkit with a web UI for the top ~25 modules
- Enhance existing vulnerability scanner integration (nmap, nikto, nuclei, ZAP)
- Add AI agent automation layer with suggest-only default, toggleable auto-mode
- Optional Meraki/Telus WiFi integration (tiered based on API access)
- Align with Platform UI Overhaul design standards (LCARS-inspired, responsive)

---

## 2. Architecture

### 2.1 Tab Structure (7 Tabs)

| # | Tab | Icon | Purpose |
|---|-----|------|---------|
| 1 | Dashboard | `layout-dashboard` | Unified security health, threat score, agent activity, camera grid, alerts |
| 2 | DNS Management | `globe` | AdGuard (local) + Hostinger (public) DNS management |
| 3 | Surveillance | `camera` | Blink camera feeds, motion events, arm/disarm via HA API |
| 4 | Reconnaissance | `radar` | Argus toolkit wrapper — curated modules, scan execution, results |
| 5 | Vulnerability Scanning | `shield-alert` | nmap, nikto, nuclei, ZAP — existing + enhanced UI |
| 6 | Access Control | `lock` | IP/domain blocking, auto-block rules, firewall integration |
| 7 | Reports | `file-chart-line` | Generated reports, export, historical trends |

### 2.2 Data Sources

| Source | Connection | Auth |
|--------|-----------|------|
| AdGuard Home | REST API via `http://network_adguard:80` (container network) or `http://192.168.1.200:5355` (host) | Basic auth (ADGUARD_USER/ADGUARD_PASS) |
| Hostinger | REST API `https://developers.hostinger.com` | Bearer token (HOSTINGER_API_KEY) |
| Home Assistant | REST API `http://192.168.1.200:8123/api/` | Long-Lived Access Token (HA_API_TOKEN) |
| Argus | CLI `python -m argus` installed in platform container | None (local execution) |
| Scanner containers | Docker exec / API | Container network access |
| Meraki (optional) | REST API `https://api.meraki.com/api/v1` | API key (MERAKI_API_KEY) — tiered |
| PostgreSQL | Direct connection via `database.py` | Existing DB config |

### 2.3 Agent Automation Layer

- **Default mode: Suggest-only** — Agent monitors all sources, creates actionable suggestions in a queue
- **Auto-mode toggle** — Per-category granular control (DNS, cameras, scanning)
- **Pause button** — Instantly stops all autonomous agent actions
- **Activity log** — Every agent action (suggested or executed) logged with timestamp, reasoning, result
- **Agent station**: SECURITY (bridge assignment)

#### Agent Capabilities

| Category | Suggest-Only | Auto-Mode |
|----------|-------------|-----------|
| DNS | "Domain X has high query volume, consider blocking" | Auto-block known malware domains |
| Cameras | "Motion detected at Driveway at 2:30 AM" | Arm all cameras on schedule |
| Scanning | "Port 8080 open on unknown device" | Auto-scan new devices on network |
| Access | "IP 1.2.3.4 has 50 failed logins" | Auto-block after threshold |
| Filters | "New filter list available for ad blocking" | Auto-update filter lists |

---

## 3. Tab Specifications

### 3.1 Dashboard Tab

**Stats Grid (top)**:
- Threat Score (computed from all sources)
- DNS Queries Today / Blocked %
- Active Cameras / Motion Events (24h)
- Open Vulnerabilities
- Blocked IPs / Domains
- Agent Actions (suggested / auto-executed)

**Camera Quick View**:
- 2x3 grid of latest camera snapshots (Driveway, Front Yard, Backyard, Porch, Doorbell, +1)
- Click to expand in Surveillance tab
- Motion indicator overlay

**Recent Activity Feed**:
- Unified timeline: DNS blocks, motion events, scan results, agent suggestions
- Filterable by category
- Actionable items (approve/dismiss agent suggestions)

**Agent Status Card**:
- Current mode (suggest-only / auto)
- Toggle switch
- Recent actions count
- Pause button

**Optional: Network Infrastructure Card** (Meraki):
- Tier 1: Connected devices count, online/offline from HA
- Tier 2: Client list, traffic stats, SSID status (if API key available)

### 3.2 DNS Management Tab

**6 Subtabs:**

#### 3.2.1 Query Log (AdGuard)
- Real-time DNS query table
- Columns: Timestamp, Domain, Client IP, Type, Response, Status (allowed/blocked)
- Search/filter by domain, client, status
- Quick-block button per row
- Auto-refresh toggle (SSE or polling)
- AdGuard API: `GET /control/querylog`

#### 3.2.2 Filters (AdGuard)
- Active filter lists with rule counts
- Enable/disable toggle per filter
- Add new filter list (URL + name)
- Update all filters button
- Custom user rules editor (textarea)
- AdGuard API: `GET/POST /control/filtering/status`, `POST /control/filtering/add_url`, `POST /control/filtering/remove_url`, `POST /control/filtering/set_rules`

#### 3.2.3 Local DNS (AdGuard Rewrites)
- Table of DNS rewrites (domain → IP)
- Add/edit/delete rewrites
- Current entries: `archie.kytranempowerment.com → 192.168.1.200`
- AdGuard API: `GET /control/rewrite/list`, `POST /control/rewrite/add`, `POST /control/rewrite/delete`

#### 3.2.4 Public DNS (Hostinger)
- DNS records for `kytranempowerment.com`
- Columns: Type, Name, Value, TTL
- Add/edit/delete records
- Validation before apply
- Sync indicator: show when local and public DNS differ
- Hostinger API: Domain DNS endpoints with Bearer token

#### 3.2.5 Clients (AdGuard)
- Per-client query stats
- Client identification (IP → hostname/device name)
- Group assignment (future: per-group filtering policies)
- AdGuard API: `GET /control/clients`

#### 3.2.6 Statistics (Both Sources)
- Total queries over time (chart)
- Blocked vs allowed ratio
- Top queried domains
- Top blocked domains
- Top clients by query volume
- AdGuard API: `GET /control/stats`

### 3.3 Surveillance Tab

**Data Source**: Home Assistant REST API (`/api/states`, `/api/camera_proxy/`)

**Blink Cameras (6 devices)**:

| Entity | Location | Features |
|--------|----------|----------|
| `camera.driveway` | Driveway | Snapshot, motion, battery |
| `camera.front_yard` | Front Yard | Snapshot, motion, battery |
| `camera.backyard` | Backyard | Snapshot, motion, battery |
| `camera.porch_camera` | Porch | Snapshot, motion, battery |
| `camera.doorbell` | Porch | Snapshot, motion, battery, doorbell press |
| `alarm_control_panel.blink_home` | — | System arm/disarm |

**Layout**:
- Camera grid: 2x3 or 3x2 depending on viewport
- Each card: Latest snapshot, camera name, location, battery %, armed status
- Click to expand: larger image, motion event timeline, arm/disarm toggle
- Refresh interval configurable (Blink default scan: 300s)

**Motion Events**:
- Timeline of motion detections
- Filter by camera
- Thumbnail from event
- Link to video clip (if available via Blink cloud)

**Controls**:
- Arm/disarm individual cameras
- Arm/disarm entire system via alarm control panel
- Refresh snapshot on demand

**HA API Endpoints Used**:
- `GET /api/states/camera.{name}` — Camera state + attributes
- `GET /api/camera_proxy/camera.{name}` — Latest snapshot image
- `POST /api/services/alarm_control_panel/alarm_arm_away` — Arm system
- `POST /api/services/alarm_control_panel/alarm_disarm` — Disarm system
- `POST /api/services/blink/trigger_camera` — Force snapshot refresh
- `GET /api/states/binary_sensor.{name}_motion_detected` — Motion state

### 3.4 Reconnaissance Tab (Argus)

**Installation**: Argus installed via `pip install argus-recon` in the platform Docker container.

**Curated Modules (~25 from 135)**:

| Category | Modules | Purpose |
|----------|---------|---------|
| Network | DNS lookup, WHOIS, Port scan, Traceroute, Reverse DNS, DNSSEC check | Network infrastructure recon |
| Web | Technology fingerprint, Header analysis, SSL/TLS check, Subdomain enum | Web app analysis |
| Threat Intel | VirusTotal lookup, Shodan search, HIBP breach check, IP reputation | Threat intelligence |
| Discovery | Crawler, Directory brute, robots.txt, sitemap parse | Content discovery |

**UI Layout**:
- Module selector (categorized dropdown or card grid)
- Target input (domain/IP/URL)
- Options panel (per-module configurable options)
- Run button / Schedule button
- Results panel: formatted output, exportable (JSON/CSV)
- History: past scans with results

**API Keys** (optional, enhance results):
- `VIRUSTOTAL_API_KEY`
- `SHODAN_API_KEY`
- `CENSYS_API_KEY`
- `HIBP_API_KEY`

**Agent Integration**:
- Agent can trigger scans based on detected threats
- Scan results feed into threat score calculation
- Agent suggests follow-up scans based on findings

### 3.5 Vulnerability Scanning Tab

**Existing Infrastructure** (already running as Docker containers):
- `security_nmap` — Network port scanning
- `security_nikto` — Web server scanning
- `security_nuclei` — Template-based vulnerability scanning
- `security_testssl` — SSL/TLS testing
- `security_zap` — OWASP ZAP web app scanner

**Enhanced UI**:
- Scanner status cards (running/idle/last scan)
- Quick scan: select scanner + target, execute
- Scheduled scans: cron-based recurring scans
- Results viewer: severity-colored findings table
- Export to PDF/JSON
- Compare scans: diff between two scan results

**Existing Code**: `stack_integration.py` `SecurityScannerService` class — keep and extend.

### 3.6 Access Control Tab

**IP Access Control** (existing DB tables):
- Blocked IPs table with reason, timestamp, expiry
- Whitelisted IPs
- Add/remove/edit entries
- Auto-block rules configuration (threshold, duration)
- Integration with AdGuard client blocking

**Domain Blocking** (AdGuard integration):
- Blocked domains list
- Add domains manually or from scan results
- Whitelist domains
- Bulk import/export

**Firewall Integration**:
- Quick view of UFW rules (read from System Operations API)
- Suggest firewall rules based on detected threats
- Link to System Operations Firewall tab for full management

### 3.7 Reports Tab

**Report Types**:
- Daily Security Summary
- DNS Analytics Report
- Vulnerability Assessment Report
- Camera Activity Report
- Agent Action Report

**Features**:
- Generate on demand or schedule
- Date range selection
- Export: PDF, JSON, CSV
- Historical report archive
- Trend charts: threats over time, blocked domains over time

---

## 4. Database Schema Changes

### New Tables

```sql
-- Agent automation suggestions and actions
CREATE TABLE security_agent_actions (
    id SERIAL PRIMARY KEY,
    action_type VARCHAR(50) NOT NULL,        -- 'suggest', 'auto_execute'
    category VARCHAR(50) NOT NULL,           -- 'dns', 'camera', 'scan', 'access'
    title VARCHAR(200) NOT NULL,
    description TEXT,
    reasoning TEXT,                          -- AI reasoning for the action
    status VARCHAR(20) DEFAULT 'pending',    -- 'pending', 'approved', 'dismissed', 'executed', 'failed'
    data JSONB,                              -- Action-specific data
    executed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Argus scan history
CREATE TABLE security_recon_scans (
    id SERIAL PRIMARY KEY,
    module_name VARCHAR(100) NOT NULL,
    target VARCHAR(500) NOT NULL,
    options JSONB,
    status VARCHAR(20) DEFAULT 'running',    -- 'running', 'completed', 'failed'
    results JSONB,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    triggered_by VARCHAR(50) DEFAULT 'user'  -- 'user', 'agent', 'schedule'
);

-- Vulnerability scan results (enhanced)
CREATE TABLE security_scan_results (
    id SERIAL PRIMARY KEY,
    scanner VARCHAR(50) NOT NULL,            -- 'nmap', 'nikto', 'nuclei', 'zap', 'testssl'
    target VARCHAR(500) NOT NULL,
    severity VARCHAR(20),                    -- 'critical', 'high', 'medium', 'low', 'info'
    finding VARCHAR(500),
    details JSONB,
    scan_id INTEGER REFERENCES security_recon_scans(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Camera motion events (cached from HA)
CREATE TABLE security_camera_events (
    id SERIAL PRIMARY KEY,
    camera_entity VARCHAR(100) NOT NULL,
    event_type VARCHAR(50) NOT NULL,         -- 'motion', 'doorbell', 'arm', 'disarm'
    location VARCHAR(100),
    thumbnail_url TEXT,
    data JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- DNS management audit trail
CREATE TABLE security_dns_changes (
    id SERIAL PRIMARY KEY,
    source VARCHAR(20) NOT NULL,             -- 'adguard', 'hostinger'
    action VARCHAR(50) NOT NULL,             -- 'add_rewrite', 'delete_rewrite', 'block_domain', 'add_record', etc.
    domain VARCHAR(500),
    details JSONB,
    changed_by VARCHAR(50) DEFAULT 'user',   -- 'user', 'agent'
    created_at TIMESTAMP DEFAULT NOW()
);

-- Generated security reports
CREATE TABLE security_reports (
    id SERIAL PRIMARY KEY,
    report_type VARCHAR(50) NOT NULL,
    title VARCHAR(200) NOT NULL,
    date_range_start TIMESTAMP,
    date_range_end TIMESTAMP,
    content JSONB,
    format VARCHAR(10) DEFAULT 'json',       -- 'json', 'pdf', 'csv'
    file_path TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Indexes

```sql
CREATE INDEX idx_agent_actions_status ON security_agent_actions(status);
CREATE INDEX idx_agent_actions_category ON security_agent_actions(category);
CREATE INDEX idx_agent_actions_created ON security_agent_actions(created_at);
CREATE INDEX idx_recon_scans_status ON security_recon_scans(status);
CREATE INDEX idx_scan_results_severity ON security_scan_results(severity);
CREATE INDEX idx_camera_events_camera ON security_camera_events(camera_entity);
CREATE INDEX idx_camera_events_type ON security_camera_events(event_type);
CREATE INDEX idx_camera_events_created ON security_camera_events(created_at);
CREATE INDEX idx_dns_changes_source ON security_dns_changes(source);
CREATE INDEX idx_dns_changes_created ON security_dns_changes(created_at);
```

---

## 5. Environment Variables

Add to both root `.env` and `platform_v2/.env`:

```env
# AdGuard Home
ADGUARD_URL=http://network_adguard:80
ADGUARD_USER=archie_admin
ADGUARD_PASS=<existing password>

# Hostinger DNS API
HOSTINGER_API_KEY=<bearer token from hostinger.com>

# Home Assistant
HA_URL=http://192.168.1.200:8123
HA_API_TOKEN=<long-lived access token from HA>

# Argus Recon (optional API keys for enhanced results)
VIRUSTOTAL_API_KEY=
SHODAN_API_KEY=
CENSYS_API_KEY=
HIBP_API_KEY=

# Meraki (optional - tiered integration)
MERAKI_API_KEY=
MERAKI_ORG_ID=
MERAKI_NETWORK_ID=
```

---

## 6. File Structure

```
platform_v2/tools/security_network/
├── __init__.py                          # Blueprint init (existing, update)
├── routes.py                            # Main routes (existing, major update)
├── stack_integration.py                 # API clients (existing, extend)
├── security_service.py                  # Security logic (existing, extend)
├── adguard_service.py                   # NEW: Full AdGuard API client
├── hostinger_service.py                 # NEW: Hostinger DNS API client
├── ha_surveillance_service.py           # NEW: Home Assistant camera integration
├── argus_service.py                     # NEW: Argus CLI wrapper
├── meraki_service.py                    # NEW: Optional Meraki API client
├── agent_automation.py                  # NEW: Agent suggest/auto-execute logic
└── report_generator.py                  # NEW: Report generation

platform_v2/templates/tools/
└── security_network.html                # Full template rebuild (7 tabs)

database/migrations/
└── 082_security_network_rebuild.sql     # New tables + indexes
```

---

## 7. API Endpoints (New/Updated)

### DNS Management
- `GET /api/dns/adguard/querylog` — Query log with pagination/filtering
- `GET /api/dns/adguard/filters` — List filter lists
- `POST /api/dns/adguard/filters` — Add filter list
- `PUT /api/dns/adguard/filters/<id>` — Toggle filter
- `DELETE /api/dns/adguard/filters/<id>` — Remove filter
- `GET /api/dns/adguard/rewrites` — List DNS rewrites
- `POST /api/dns/adguard/rewrites` — Add rewrite
- `DELETE /api/dns/adguard/rewrites` — Delete rewrite
- `GET /api/dns/adguard/clients` — Client stats
- `GET /api/dns/adguard/stats` — Statistics
- `POST /api/dns/adguard/rules` — Set custom user rules
- `GET /api/dns/hostinger/records` — List public DNS records
- `POST /api/dns/hostinger/records` — Add DNS record
- `PUT /api/dns/hostinger/records/<id>` — Update DNS record
- `DELETE /api/dns/hostinger/records/<id>` — Delete DNS record

### Surveillance
- `GET /api/surveillance/cameras` — All camera states + snapshots
- `GET /api/surveillance/cameras/<entity>/snapshot` — Proxy latest snapshot
- `POST /api/surveillance/cameras/<entity>/refresh` — Force snapshot
- `POST /api/surveillance/cameras/<entity>/arm` — Arm camera
- `POST /api/surveillance/cameras/<entity>/disarm` — Disarm camera
- `POST /api/surveillance/system/arm` — Arm all
- `POST /api/surveillance/system/disarm` — Disarm all
- `GET /api/surveillance/events` — Motion event history
- `GET /api/surveillance/events/recent` — Last 24h events

### Reconnaissance
- `GET /api/recon/modules` — List available Argus modules
- `POST /api/recon/scan` — Start a scan
- `GET /api/recon/scan/<id>` — Get scan status/results
- `GET /api/recon/history` — Scan history
- `DELETE /api/recon/scan/<id>` — Delete scan result

### Agent Automation
- `GET /api/agent/suggestions` — Pending suggestions
- `POST /api/agent/suggestions/<id>/approve` — Approve suggestion
- `POST /api/agent/suggestions/<id>/dismiss` — Dismiss suggestion
- `GET /api/agent/actions` — Action history
- `GET /api/agent/config` — Current agent config
- `PUT /api/agent/config` — Update agent config (mode, per-category toggles)
- `POST /api/agent/pause` — Pause all agent actions
- `POST /api/agent/resume` — Resume agent actions

### Reports
- `POST /api/reports/generate` — Generate report
- `GET /api/reports` — List reports
- `GET /api/reports/<id>` — Get report
- `GET /api/reports/<id>/download` — Download report file

---

## 8. Meraki Integration (Optional/Tiered)

### Tier 1: Via Home Assistant (No Meraki API Key)
- Device tracking: connected clients via HA Meraki integration
- Online/offline device status
- Basic device info (MAC, IP, hostname)

### Tier 2: Direct Meraki API (With API Key)
- Full client list with traffic stats
- SSID management (enable/disable/rename)
- Client blocking/unblocking
- Traffic shaping policies
- Network health metrics
- Meraki Python SDK: `pip install meraki`

### Configuration
- Auto-detect: check if MERAKI_API_KEY is set
- UI shows available features based on tier
- Settings page to configure/test API connection

---

## 9. Design Standards

- Follow Platform UI Overhaul guidelines (Project #94)
- LCARS-inspired design system with `--archie-*` CSS variables
- Responsive breakpoints: 374px (mobile), 717px (tablet), 1280px (desktop)
- Tab navigation consistent with System Operations pattern
- Subtab pattern consistent with existing Network/Docker subtabs
- Lazy-loading for tab content
- Cards with subtle glassmorphism, consistent with existing modules
- Red accent color for security theme (existing convention)

---

## 10. Implementation Priority

### Phase 1: Foundation
1. Database migration (new tables)
2. Tab structure + Dashboard skeleton
3. AdGuard service + DNS Management tab (all 6 subtabs)
4. Agent automation framework (suggest-only)

### Phase 2: Surveillance + Recon
5. HA surveillance service + Surveillance tab
6. Argus installation + Reconnaissance tab
7. Enhanced Vulnerability Scanning tab

### Phase 3: Polish + Integration
8. Access Control tab (consolidate existing)
9. Reports tab
10. Meraki integration (optional)
11. Agent auto-mode implementation
12. Responsive design pass + Playwright testing

---

## 11. Sources & References

- [AdGuard Home API](https://github.com/AdguardTeam/AdGuardHome/wiki/API) — REST API documentation
- [Hostinger API](https://developers.hostinger.com/) — Domain/DNS management
- [Hostinger MCP Server](https://github.com/hostinger/api-mcp-server) — MCP integration
- [Home Assistant REST API](https://developers.home-assistant.io/docs/api/rest/) — Camera/device access
- [Argus Toolkit](https://github.com/jasonxtn/Argus) — 135-module recon framework
- [Meraki Dashboard API](https://developer.cisco.com/meraki/api-v1/) — Network management
- [Meraki Python SDK](https://github.com/meraki/dashboard-api-python) — Official Python library
