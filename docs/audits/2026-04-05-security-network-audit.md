# Security Network Module Audit
**Date**: 2026-04-05 | **Module**: `platform_v2/tools/security_network/`

---

## 1. Module File Inventory (27 Python files)

| File | Purpose |
|------|---------|
| `__init__.py` | Blueprint registration, `register_*_routes` pattern (ADR-045) |
| `routes.py` | Core routes (dashboard, DNS, devices, scanners, events, IP access) |
| `noc_routes.py` | NOC overview endpoint |
| `traffic_routes.py` | Traffic/activity endpoints |
| `defense_routes.py` | fail2ban, firewall, DDNS, connections |
| `compliance_routes.py` | Compliance scanning, evidence, CKL export, PDF reports |
| `badge_routes.py` | Public SVG compliance badges |
| `report_routes.py` | Report generation and history |
| `device_routes.py` | Device registry CRUD and DNS client view |
| `jobs.py` | 9 APScheduler background jobs |
| `agent_automation.py` | Suggestion engine + auto-execute pipeline |
| `security_alerts.py` | Alert creation -> system_notifications + Telegram |
| `stack_integration.py` | AdGuard, ntopng, scanner (nmap/nikto/nuclei/ZAP) APIs |
| `compliance_service.py` | Scan execution, evidence collection, fix application |
| `adguard_service.py` | AdGuard Home API wrapper |
| `npm_service.py` | Nginx Proxy Manager API wrapper |
| `hostinger_service.py` | Hostinger DNS API wrapper |
| `ha_surveillance_service.py` | Home Assistant camera/alarm integration |
| `device_registry_service.py` | Device discovery, registration, zone management |
| `ddns_service.py` | Dynamic DNS update service |
| `fail2ban_service.py` | fail2ban jail/ban management |
| `ntopng_service.py` | ntopng traffic analysis API |
| `nagios_service.py` | Nagios monitoring integration |
| `argus_service.py` | Argus security monitoring |
| `network_integration.py` | Network tool integration helpers |
| `security_service.py` | Security event management |
| `report_service.py` | Report generation logic |

---

## 2. jobs.py -- 9 Registered Background Jobs

| # | Job ID | Function | Schedule | What It Does |
|---|--------|----------|----------|--------------|
| 1 | `agent_network_discovery` | `discover_network_devices()` | Every 5 min | Scans network via AdGuard + ARP, alerts on new devices via Telegram |
| 2 | `agent_security_audit` | `run_security_audit()` | Sun 3 AM (weekly) | Checks SSH config, fail2ban, UFW rules, DDNS freshness, AdGuard protection |
| 3 | `agent_ssl_expiry_check` | `check_ssl_expiry()` | Every 24h | Checks NPM proxy host SSL certs, alerts if <=14 days to expiry |
| 4 | `agent_daily_dns_report` | `daily_dns_report()` | Daily 7 AM | Generates DNS stats summary (queries, blocked, top clients) and sends via Telegram |
| 5 | `agent_query_spike_detect` | `detect_query_spike()` | Every 1h | Alerts if DNS block rate exceeds 50% (possible malware/misconfiguration) |
| 6 | `agent_camera_anomaly` | `check_camera_anomaly()` | Every 1h | Alerts if cameras are unavailable/unknown via Home Assistant |
| 7 | `agent_auto_block` | `run_auto_block()` | Every 15 min | Runs suggestion engine, auto-executes critical/high SSH brute force + device vulnerability suggestions |
| 8 | `agent_compliance_scan` | `run_scheduled_compliance_scan()` | Every 6h (Job #57) | Runs STIG compliance scan, auto-collects SOC 2 evidence, notifies on score changes |
| 9 | `agent_auto_remediation` | `run_auto_remediation()` | Every 6h (Job #58) | Auto-fixes low-risk compliance failures from latest scan |

All jobs are wrapped with Flask app context via `with_ctx()`. Logging goes to `autonomy_loop_log` table under "Security & Compliance" department.

---

## 3. agent_automation.py -- Suggestion Engine

**Default config**: mode=suggest, paused=false, 5 categories (dns, camera, scanning, access, filters), all auto_enabled=false.

**DB tables used**: `security_auto_block_settings` (config), `security_agent_actions` (suggestions/actions)

### 9 Suggestion Generators

| Generator | Category | Severity | What It Detects |
|-----------|----------|----------|-----------------|
| `_suggest_filter_update` | filters | medium | AdGuard filter lists older than 7 days |
| `_suggest_new_devices` | scanning | high | Unregistered devices on network |
| `_suggest_ssl_expiry` | access | critical/high | SSL certs expiring within 14 days |
| `_suggest_query_spike` | dns | high | DNS query rate >2x normal or >50% blocked |
| `_suggest_camera_offline` | camera | high | Cameras in unavailable/unknown state |
| `_suggest_device_offline` | scanning | medium | Trusted/family devices offline >4 hours |
| `_suggest_ssh_threats` | access | critical/high | fail2ban SSH brute force bans |
| `_suggest_dns_block_recommendation` | dns | medium | Suspicious high-frequency unblocked domains |
| `_suggest_access_policy_conflict` | access | medium | IoT devices with >20 unique domains (zone mismatch) |

All suggestions have dedup via `_has_pending_suggestion()` (checks `data->>'suggestion_type'`).

### Lifecycle
- `create_suggestion()` -> status=pending
- `approve_suggestion()` -> status=approved, executed_at=NOW
- `dismiss_suggestion()` -> status=dismissed
- `log_auto_action()` -> status=executed/failed (for auto-execute path)

---

## 4. stack_integration.py -- External Service Integrations

### AdGuardLocalAPI
- Host: `network_adguard:80` (fallback: `localhost:8053`)
- Auth: `ADGUARD_USER` / `ADGUARD_PASS` env vars
- Methods: `get_status()`, `get_stats()`, `get_query_log()`, `block_domain()`, `check_health()`

### NtopngLocalAPI
- Host: `network_ntopng:3000` (fallback: `localhost:3001`)
- Auth: `NTOPNG_USER` / `NTOPNG_PASS` env vars
- Methods: `get_interface_stats()`, `get_top_hosts()`, `get_alerts()`, `check_health()`

### SecurityScannerService
- Uses Docker SDK (`docker.from_env()`) -- NOT shell commands (safe)
- Scan types: nmap (quick/full/vuln), nikto, nuclei (5 template types), SSL (testssl.sh), ZAP (spider/active/passive)
- Target validation: rejects shell metacharacters, validates with regex
- Containers expected: `security_nmap`, `security_nikto`, `security_nuclei`, `security_testssl`, `security_zap`

### `check_external_tools_status()`
- Returns health of: adguard, ntopng, zap

---

## 5. security_alerts.py -- Alert System

- **Valid alert types**: intrusion, block, ssl_expiry, dns_change, motion, scan_result, new_device
- **Priority mapping**: critical->error, high->warning, normal/low->info
- **Config**: Stored in `security_auto_block_settings` table (key: `alert_config`)
- **Defaults**: intrusion/block/ssl_expiry/motion -> Telegram enabled; dns_change/scan_result -> Telegram disabled
- **Override**: critical/high alerts ALWAYS send Telegram if caller requests it
- **Mechanism**: Inserts into `system_notifications` with `telegram_forwarded=false` so the Telegram daemon picks it up

---

## 6. Rule Packs (5 packs, 178 total rules)

| Pack | File | Rules | Severities |
|------|------|-------|------------|
| Ubuntu 22.04 STIG | `ubuntu-22.04-stig.json` | 51 | 7 high, 44 medium |
| CIS Ubuntu 22.04 | `cis-ubuntu-22.04.json` | 40 | 8 high, 28 medium, 4 low |
| Docker STIG | `docker-stig.json` | 30 | 8 high, 22 medium |
| HIPAA Security | `hipaa-security.json` | 30 | 15 high, 13 medium, 2 low |
| Network STIG | `network-stig.json` | 27 | 8 high, 19 medium |

**Total**: 178 rules across 5 frameworks. No rules have a `category` field (all default to `?`).

---

## 7. CSS Files

| File | Lines | Purpose |
|------|-------|---------|
| `security-network.css` | 1,236 | Main module styles |
| `security-network-theme-vars.css` | 17 | CSS custom properties for theming |

---

## 8. Template -- Tab Structure (4,942 lines)

The template is `security_network.html` (4,942 lines). It loads:
- External JS: `security-network.js` (761 lines, 37 functions)
- Inline `<script>`: ~3,300 lines, ~100+ functions
- Chart.js CDN for compliance history chart

### 8 Main Tabs

| Tab | ID | Subtabs | Description |
|-----|----|---------|-------------|
| **Overview** | `tab-overview` | none | NOC dashboard: V.I.G.I.L. station panel, 4 hero stat cards, service health, activity feed, compliance summary, quick actions |
| **Traffic** | `tab-traffic` | none | DNS traffic stats, bandwidth bar, per-client activity table, service detection |
| **DNS** | `tab-dns` | 7 subtabs | Full AdGuard management + Hostinger DNS + Domains |
| **Devices** | `tab-devices` | none | Device-user mappings, device consumption |
| **Defense** | `tab-defense` | none | fail2ban jails, DDNS, UFW firewall, auto-block, IP access control, security events, connections |
| **Scanners** | `tab-scanners` | 3 subtabs | Surveillance cameras, vulnerability scanners (5 tools), reconnaissance |
| **Compliance** | `tab-compliance` | none | Score rings, framework badges, findings with filters, evidence collection, scan history chart, system hardening |
| **Reports** | `tab-reports` | none | Daily report generation (device/user), report history, legacy report generator |

### DNS Tab -- 7 Subtabs

| Subtab | ID | Key Functions |
|--------|----|---------------|
| Overview | `subtab-dns-overview` | `loadDNSOverview()` -> `GET /api/dns/adguard/stats` |
| Query Log | `subtab-dns-querylog` | `loadQueryLog(offset)` -> `GET /api/dns/adguard/querylog` |
| Filters | `subtab-dns-filters` | `loadFilters()` -> `GET /api/dns/adguard/filters`; `addFilter()`, `toggleFilter()`, `removeFilter()`, `refreshAllFilters()` |
| Rewrites | `subtab-dns-rewrites` | `loadRewrites()` -> `GET /api/dns/adguard/rewrites`; `addRewrite()`, `deleteRewrite()` |
| Rules | `subtab-dns-rules` | `loadUserRules()` -> `GET /api/dns/adguard/rules`; `saveUserRules()`, `dnsBlockDomain()`, `dnsUnblockDomain()` |
| Clients | `subtab-dns-clients` | `loadDeviceClients()` -> `GET /api/devices`; zone/type filters, sync to AdGuard |
| Domains | `subtab-domains-overview` | `loadDomainsOverview()` -> unified DNS+NPM+SSL view; sub-subtabs: DNS Records, Proxy Hosts, Certs, Quick Setup |

### Scanners Tab -- 3 Subtabs

| Subtab | ID | Key Functions |
|--------|----|---------------|
| Surveillance | `subtab-scanners-surv` | `loadSurveillance()` -> `GET /api/surveillance/cameras`; arm/disarm, camera modal, auto-refresh |
| Vulnerability | `subtab-scanners-vuln` | `runVulnScan()` -> nmap/nikto/nuclei/SSL/ZAP; `loadScanResults()`; SSL monitors |
| Reconnaissance | `subtab-scanners-recon` | `loadReconModules()` -> `GET /api/recon/modules`; `startReconScan()`, `loadReconHistory()` |

### 6 LCARS Modals

| Modal | ID | Purpose |
|-------|----|---------|
| Block Domain | `block-domain-modal` | Block domain via AdGuard (red accent) |
| DNS Record Edit | `dns-edit-modal` | Edit/delete Hostinger DNS records (cyan accent) |
| Proxy Host Edit | `proxy-edit-modal` | Edit/delete NPM proxy hosts (amber accent) |
| Device Edit | `device-edit-modal` | Register/edit/delete devices with zone assignment (green accent) |
| Device DNS Report | `device-report-modal` | Per-device DNS activity report (blue accent) |
| Camera Enlarge | `camera-modal` | Enlarged camera feed with refresh (green accent) |

### Floating Agent Panel
- FAB button (bottom-right): `toggleAgentPanel()`
- Shows: mode (suggest/auto), pause control, pending suggestions, recent actions
- API calls: `GET /api/agent/config`, `GET /api/agent/suggestions`, `GET /api/agent/actions`, `POST /api/agent/suggestions/{id}/approve`, `POST /api/agent/suggestions/{id}/dismiss`

---

## 9. Complete API Endpoint Map

All endpoints are prefixed with `/tools/security-network/api`.

### Overview/NOC
| Method | Endpoint | JS Function |
|--------|----------|-------------|
| GET | `/noc/overview` | `loadNocOverview()` |
| GET | `/dashboard/stats` | `loadDashboard()` |

### DNS (AdGuard)
| Method | Endpoint | JS Function |
|--------|----------|-------------|
| GET | `/dns/adguard/stats` | `loadDNSOverview()` |
| GET | `/dns/adguard/querylog` | `loadQueryLog()` |
| GET | `/dns/adguard/filters` | `loadFilters()` |
| POST | `/dns/adguard/filters` | `addFilter()` |
| PUT | `/dns/adguard/filters/{url}` | `toggleFilter()` |
| DELETE | `/dns/adguard/filters/{url}` | `removeFilter()` |
| POST | `/dns/adguard/filters/refresh` | `refreshAllFilters()` |
| GET | `/dns/adguard/rewrites` | `loadRewrites()` |
| POST | `/dns/adguard/rewrites` | `addRewrite()` |
| DELETE | `/dns/adguard/rewrites` | `deleteRewrite()` |
| GET | `/dns/adguard/rules` | `loadUserRules()` |
| POST | `/dns/adguard/rules` | `saveUserRules()` |
| POST | `/dns/adguard/block` | `dnsBlockDomain()`, `submitBlockDomain()` |
| POST | `/dns/adguard/unblock` | `dnsUnblockDomain()` |
| POST | `/dns/adguard/protection` | `quickToggleProtection()` |

### DNS (Hostinger)
| Method | Endpoint | JS Function |
|--------|----------|-------------|
| GET | `/dns/hostinger/records` | `loadHostingerRecords()` |
| POST | `/dns/hostinger/records` | `addHostingerRecord()` |
| DELETE | `/dns/hostinger/records/{id}` | `deleteHostingerRecord()` |

### Domains (NPM + Unified)
| Method | Endpoint | JS Function |
|--------|----------|-------------|
| GET | `/domains/proxy-hosts` | `loadDomainProxyHosts()`, `seedSSLFromProxyHosts()` |
| POST | `/domains/quick-setup` | `quickSetupDomain()` (implied) |
| PUT | `/domains/proxy-hosts/{id}` | `saveProxyHost()` (implied) |
| DELETE | `/domains/proxy-hosts/{id}` | `deleteProxyHost()` (implied) |

### Devices
| Method | Endpoint | JS Function |
|--------|----------|-------------|
| GET | `/devices` | `loadDeviceClients()`, `_getDeviceMap()` |
| GET | `/devices/users` | `loadDevices()` (snApi) |
| POST | `/devices/users` | `addDeviceMapping()` (snApiPost) |
| DELETE | `/devices/users/{id}` | `deleteDeviceMapping()` |
| GET | `/devices/consumption` | `loadDevices()` (snApi) |

### Traffic
| Method | Endpoint | JS Function |
|--------|----------|-------------|
| GET | `/traffic/activity` | `loadTraffic()` (snApi) |

### Defense
| Method | Endpoint | JS Function |
|--------|----------|-------------|
| GET | `/fail2ban/jails` | `loadFail2banJails()` (snApi) |
| GET | `/ddns/status` | `loadDdnsStatus()` (snApi) |
| POST | `/ddns/update` | `triggerDdnsUpdate()` (snApiPost) |
| GET | `/firewall/rules` | `loadFirewall()` (implied) |
| POST | `/firewall/toggle` | `toggleFirewall()` (implied) |
| POST | `/firewall/rules` | `addFirewallRule()` (implied) |
| DELETE | `/firewall/rules/{num}` | `deleteFirewallRule()` (implied) |
| GET | `/auto-block/settings` | `loadAutoBlockSettings()` |
| POST | `/auto-block/settings` | `updateAutoBlock()` |
| GET | `/ip-access` | `loadIPAccess()` |
| POST | `/ip-access/block` | `blockIP()` |
| POST | `/ip-access/unblock` | `unblockIP()` |
| GET | `/events` | `loadSecurityEvents()` |
| POST | `/events/{id}/resolve` | `resolveEvent()` |
| GET | `/connections/active` | `loadConnections()` |

### Scanners
| Method | Endpoint | JS Function |
|--------|----------|-------------|
| GET | `/surveillance/status` | `loadSurveillanceStatus()` |
| GET | `/surveillance/cameras` | `loadSurveillance()` |
| GET | `/surveillance/events` | `loadSurveillanceEvents()` |
| POST | `/surveillance/system/arm` | `armSystem()` |
| POST | `/surveillance/system/disarm` | `disarmSystem()` |
| POST | `/scans/{type}` | `runVulnScan()` |
| GET | `/scans` | `loadScanResults()` |
| GET | `/scans/{filename}` | `viewScanFile()` |
| GET | `/ssl/monitors` | `loadSSLMonitors()` |
| POST | `/ssl/monitors` | `showAddSSLModal()` |
| POST | `/ssl/refresh` | `refreshSSLMonitors()` |
| GET | `/recon/modules` | `loadReconModules()` |
| GET | `/recon/history` | `loadReconHistory()` |
| POST | `/recon/scan` | `startReconScan()` |
| GET | `/recon/scan/{id}` | `viewScanResult()` |
| DELETE | `/recon/scan/{id}` | `deleteReconScan()` |

### Compliance
| Method | Endpoint | JS Function |
|--------|----------|-------------|
| GET | `/compliance/scores` | `loadDashboard()` (compliance section) |
| POST | `/compliance/scan` | `runComplianceScan()` |
| GET | `/compliance/results/{id}` | `loadComplianceResults()` |
| POST | `/compliance/fix` | hardening one-click fix (implied) |
| GET | `/compliance/evidence` | `collectEvidence()` (implied) |
| GET | `/compliance/export/ckl` | `exportCkl()` (implied) |
| GET | `/compliance/export/evidence` | `exportEvidence()` (implied) |
| GET | `/compliance/report/pdf` | `openComplianceReport()` (implied) |

### Reports
| Method | Endpoint | JS Function |
|--------|----------|-------------|
| GET | `/reports` | `loadReports()` |
| GET | `/reports/list` | `loadReportsList()` (snApi) |
| GET | `/reports/{id}` | `viewReport()`, `viewSnReport()` (snApi) |
| POST | `/reports/generate` | `generateReport()`, `generateDailyReport()` (snApiPost) |

### Agent Automation
| Method | Endpoint | JS Function |
|--------|----------|-------------|
| GET | `/agent/config` | `loadAgentConfig()` |
| GET | `/agent/suggestions` | loaded in `loadAgentConfig()` |
| GET | `/agent/actions` | loaded in `loadAgentConfig()` |
| POST | `/agent/suggestions/{id}/approve` | approve button |
| POST | `/agent/suggestions/{id}/dismiss` | dismiss button |

---

## 10. Observations and Potential Issues

### Code Duplication
- **Two API base variables**: `SN_API` in `security-network.js` and `API` in inline script. Functions are split between both with no clear boundary. Newer functions (NOC, traffic, fail2ban, DDNS, reports) use `snApi()`; older functions use raw `fetch(API + ...)`.
- **Duplicate utility functions**: `formatNum`, `setBadge`, `esc`/`snEsc`, `showLoading`/`snShowLoading`, `showEmpty`/`snShowEmpty`, `buildTable`/`snBuildTable`, `createBadge`/`snCreateBadge` all exist in both the external JS and inline script.
- **Duplicate `switchToTab`**: Defined in both files (inline one adds remap logic).
- **Duplicate `deleteReconScan`**: Defined twice in inline script (lines 2590 and 2757).

### Template Size
- At 4,942 lines with ~3,300 lines of inline JS, this is one of the largest templates. The inline script should be extracted to `security-network.js` (or a second file) per the CSS/JS extraction pattern used elsewhere.

### Missing Category Field in Rule Packs
- All 178 rules across 5 packs have no `category` field. Filtering by category in the UI will not work until rules are categorized.

### Scanner Containers Not in docker-compose
- `security_nmap`, `security_nikto`, `security_nuclei`, `security_testssl`, `security_zap` are referenced in `stack_integration.py` but may not be deployed (check docker-compose.yml).

### Broken Subtab HTML Structure
- Lines 963-964 and 1046-1047 contain `-->` comment-close markers that suggest the Vulnerability and Recon subtabs were originally inside `<div>` wrappers that got commented out. The subtab content now renders outside its `<div>` container, causing the subtab switching JS to fail for these two subtabs. The surveillance subtab works because it is still properly wrapped.

### Service Badges in Header
- 9 service badges: AdGuard, Hostinger, Cameras, NPM, SSH, fail2ban, DDNS, Argus, Agent
- Set by `loadDashboard()` via `GET /dashboard/stats` response

### Font Awesome in Compliance Tab
- The Compliance tab uses Font Awesome icons (`fas fa-*`, `far fa-*`) while the rest of the module uses Lucide icons. No Font Awesome CSS is loaded in `extra_css`, so these icons will not render.
