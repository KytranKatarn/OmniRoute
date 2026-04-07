# Security Network Module — Full Audit & Optimization Spec

**Date**: 2026-04-05 | **Module**: `platform_v2/tools/security_network/`
**Audited by**: Code review agents (3) + live browser testing (Playwright)

---

## 1. Module Inventory

### Files (27 Python + 5 rule packs + 2 CSS + 1 template + 1 external JS)

**Route files (8)**:
- `routes.py` — 4,042 lines (VIOLATES 600-line rule)
- `compliance_routes.py`, `defense_routes.py`, `noc_routes.py`
- `traffic_routes.py`, `device_routes.py`, `report_routes.py`, `badge_routes.py`

**Service files (14)**:
- `security_service.py` (712 lines), `compliance_service.py` (~500), `device_registry_service.py` (906)
- `report_service.py` (954), `adguard_service.py` (214), `npm_service.py` (168)
- `hostinger_service.py` (143), `ha_surveillance_service.py` (210), `fail2ban_service.py` (95)
- `nagios_service.py` (118), `ntopng_service.py` (118), `ddns_service.py` (101)
- `argus_service.py` (424), `network_integration.py` (384 — **DEAD CODE**)

**Supporting files (5)**:
- `jobs.py` — 9 APScheduler background jobs
- `agent_automation.py` — suggestion engine + auto-execute pipeline
- `security_alerts.py` — alert creation -> system_notifications + Telegram
- `stack_integration.py` — AdGuard, ntopng, scanner container APIs
- `CREDENTIALS.md` — credential reference

**Frontend**:
- `security_network.html` — 4,942 lines (3,300 inline JS)
- `security-network.js` — 761 lines, 37 functions
- `security-network.css` — 1,236 lines
- `security-network-theme-vars.css` — 17 lines

**Rule packs (5)**: 178 total rules
- `ubuntu-22.04-stig.json` (51), `cis-ubuntu-22.04.json` (40)
- `docker-stig.json` (30), `hipaa-security.json` (30), `network-stig.json` (27)

---

## 2. Live Browser Test Results (All 8 Tabs)

### Overview Tab — PARTIAL
| Feature | Status | Notes |
|---------|--------|-------|
| Hero stat cards (DNS queries, threats blocked) | WORKING | 143.7K queries, 24.4K blocked |
| Network Traffic card | BROKEN | Shows "0 B" — likely ntopng integration issue |
| Currently Banned card | WORKING | Shows 0 |
| Service Health panel | WORKING | AdGuard, ntopng, Nagios, fail2ban, DDNS all ONLINE |
| V.I.G.I.L. Activity Feed | EMPTY | All 10 entries show "-" — no activity data |
| Compliance Summary | EMPTY | All scores "--", last scan "Never" |
| Quick Actions buttons | WORKING | DNS Protection, Block Domain, Run Scan, Defense Panel |
| Security Operations panel | WORKING | NMAP SCAN, SSL CHECK, DEVICE AUDIT, DNS REPORT buttons |
| System Alert banner | BROKEN | Persistent "Loading..." that never resolves |

### Traffic Tab — WORKING
| Feature | Status | Notes |
|---------|--------|-------|
| DNS queries/blocked stats | WORKING | 5.0K queries, 5.0K blocked |
| Client Activity table | WORKING | IPs with DNS queries, blocked counts, service tags |
| Service detection | WORKING | Gaming, Google, TikTok, Microsoft, etc. |
| Bandwidth Distribution | PARTIAL | Shows "Clean: 0, Blocked: 5.0K" — no bandwidth data |

### DNS Tab — MOSTLY WORKING (7 sub-tabs)
| Sub-tab | Status | Notes |
|---------|--------|-------|
| Overview | WORKING | 4 stat cards: queries, blocked, malware, protection |
| Query Log | WORKING | Live queries with pagination (50/page), search, status filter |
| Filters | WORKING | 6 filter lists with toggle, add, refresh |
| Rewrites | WORKING | 14+ split DNS rewrites, add/delete |
| Rules | WORKING | Quick block/unblock, custom filtering rules editor |
| Clients | WORKING | 45 clients, 35 active, 43 unregistered with register/block |
| Domains | EMPTY | No content renders — broken or unimplemented |

### Devices Tab — BROKEN
| Feature | Status | Notes |
|---------|--------|-------|
| Add Device Mapping form | WORKING | MAC/IP/username/device name inputs |
| Device–User Mappings | EMPTY | "No device mappings" |
| Device Consumption | ERROR | "Error loading consumption data" — **500 server error** |
| Console error | CONFIRMED | `/api/devices/consumption` returns 500 |

### Defense Tab — PARTIAL
| Feature | Status | Notes |
|---------|--------|-------|
| fail2ban Jails | WORKING | Jail list with status |
| DDNS Status | WORKING | Public IP, started IP, IP match, last check |
| UFW Firewall | BROKEN | "Error loading firewall" + "Error loading rules" |
| Auto-Block Settings | WORKING | Enabled, threshold 5 attempts / 24h window |
| IP Access Control | WORKING | Block/whitelist form, empty lists |
| Security Events | EMPTY | "No security events" |
| Active Connections | WORKING | Long list with local/remote/status |

### Scanners Tab — PARTIAL (3 sub-tabs)
| Sub-tab | Status | Notes |
|---------|--------|-------|
| Surveillance | PARTIAL | No HA installed, but camera detection works (Blink on .253, .77) |
| Vulnerability | WORKING | 5 scanner cards (NMAP, NIKTO, NUCLEI, SSL/TLS, ZAP), SSL monitoring, no data yet |
| Reconnaissance | WORKING | 32 available modules across 6 categories, scan launcher, no history |

### Compliance Tab — WORKING
| Feature | Status | Notes |
|---------|--------|-------|
| Score rings | WORKING | 6 frameworks with circular gauges |
| Scores | WORKING | Ubuntu STIG 95.6%, Docker 100%, HIPAA 73.3%, Network 100%, CIS 100%, SOC2 92.7% |
| Findings table | WORKING | Rule IDs, descriptions, statuses with filters |
| Rule pack management | WORKING | Production, Network, Disaster Recovery packs |
| System Hardening | WORKING | Recommendations section |
| PDF/Export/Import | UNTESTED | Buttons present |

### Reports Tab — WORKING (with duplication issue)
| Feature | Status | Notes |
|---------|--------|-------|
| Generate Daily Report | WORKING | Device Report + User Report buttons |
| Report History (top) | WORKING | 11 reports (daily_user, daily_device) with View buttons |
| Generate Report (bottom) | WORKING | Report type dropdown, date range, Generate button |
| Report History (bottom) | DUPLICATE | "No reports generated yet" — second conflicting section |

---

## 3. Critical Findings — Route Audit

| # | Severity | Finding |
|---|----------|---------|
| 1 | **HIGH** | `routes.py` is 4,042 lines — 6.7x the 600-line limit. Must split into ~8 domain files |
| 2 | **MEDIUM** | Missing `time` import in routes.py — will crash `_check_fail2ban_health` and `_check_ddns_health` |
| 3 | **MEDIUM** | `POST /api/auto-block` is a dead stub — always returns `{"blocked": 0}` |
| 4 | **MEDIUM** | `POST /api/reports/generate` in report_routes.py is unreachable (shadowed by routes.py) |
| 5 | **MEDIUM** | Duplicate AdGuard block endpoints (`/api/adguard/block` vs `/api/dns/adguard/block`) |
| 6 | **MEDIUM** | `reason` parameter unused in `api_agent_dismiss_suggestion` |
| 7 | **LOW** | Missing `@admin_required` on `/api/stacks/status` (has `@login_required` only) |
| 8 | **LOW** | Hardcoded IPs and paths: `192.168.1.200`, `/mnt/archie_brain/security_scans`, `/mnt/archie_brain/host_monitor_data.json` |
| 9 | **LOW** | noc_routes.py docstring claims "no live service calls" but makes 3 live HTTP calls |
| 10 | **LOW** | badge_routes.py uses separate Blueprint, not registered via `__init__.py` pattern |
| 11 | **LOW** | No MAC address format validation in device_routes.py |
| 12 | **LOW** | Column name inconsistency between noc_routes and traffic_routes for traffic stats |
| 13 | **LOW** | `jail_name` not validated before passing to Fail2banService |

### Recommended Route Splits for routes.py

| New File | Routes to Move | Est. Lines |
|----------|---------------|------------|
| `adguard_routes.py` | All `/api/dns/adguard/*` + old `/api/adguard/*` | ~350 |
| `hostinger_routes.py` | All `/api/dns/hostinger/*` | ~200 |
| `surveillance_routes.py` | All `/api/surveillance/*` | ~250 |
| `scanner_routes.py` | All `/api/scanner/*` + `/api/scans/*` | ~250 |
| `domain_routes.py` | All `/api/domains/*` (org_domains, managed_dns, NPM, quick-setup) | ~500 |
| `device_registry_routes.py` | All `/api/devices/*` (registry, not device_routes.py) | ~200 |
| `agent_automation_routes.py` | All `/api/agent/*` | ~200 |
| `nginx_routes.py` | All `/api/nginx/*` | ~100 |

---

## 4. Critical Findings — Service Audit

### Service Health Matrix

| File | Lines | Status | Quality | External Deps |
|------|-------|--------|---------|---------------|
| security_service.py | 712 | Functional | Good | host_command, Docker, psutil |
| compliance_service.py | ~500 | Functional | Excellent | host_command, /proc |
| adguard_service.py | 214 | Functional | Good | AdGuard API |
| npm_service.py | 168 | Functional | Good | NPM API (needs token refresh) |
| hostinger_service.py | 143 | Functional | Good | Hostinger API |
| ha_surveillance_service.py | 210 | Functional | Good | Home Assistant API |
| device_registry_service.py | 906 | Functional | Excellent | AdGuard, host_command |
| fail2ban_service.py | 95 | Functional | Excellent | host_command |
| nagios_service.py | 118 | Functional | Good | Nagios CGI API |
| ntopng_service.py | 118 | Functional | Good | ntopng API |
| ddns_service.py | 101 | Functional | Fair | ipify.org, shell script |
| argus_service.py | 424 | Functional | Fair | Docker containers, various |
| report_service.py | 954 | Functional | Good | AdGuard, filesystem |
| **network_integration.py** | **384** | **DEAD CODE** | **Poor** | All (wrong IPs: 192.168.1.250) |

### Key Service Issues

| # | Severity | Finding |
|---|----------|---------|
| 1 | **HIGH** | `network_integration.py` is dead code — all IPs hardcoded to 192.168.1.250 (wrong), superseded by individual service files. Should be deleted. |
| 2 | **MEDIUM** | `ha_surveillance_service.py` — HA token embedded in URL query params (leaked in logs/browser history) |
| 3 | **LOW** | `ddns_service.py` — relies on shell script at `/mnt/archie_brain/scripts/ddns_updater.sh`, quality is Fair |
| 4 | **LOW** | `argus_service.py` — quality Fair, mixed patterns |
| 5 | **LOW** | `npm_service.py` — needs token refresh mechanism |

---

## 5. Critical Findings — Template & Frontend

| # | Severity | Finding |
|---|----------|---------|
| 1 | **HIGH** | Template is 4,942 lines with ~3,300 inline JS — must extract to external JS files |
| 2 | **HIGH** | Duplicate utility functions between `security-network.js` and inline script (formatNum, setBadge, esc, showLoading, showEmpty, buildTable, createBadge, switchToTab) |
| 3 | **MEDIUM** | `deleteReconScan()` defined TWICE in inline script |
| 4 | **MEDIUM** | Font Awesome icons in Compliance tab but no Font Awesome CSS loaded |
| 5 | **MEDIUM** | Broken HTML structure in Vulnerability/Recon subtabs (`-->` comment markers left from disabled wrappers) |
| 6 | **MEDIUM** | Two API base variables (`SN_API` in external JS, `API` in inline) with no clear boundary |
| 7 | **LOW** | Persistent "System Alert - Loading..." banner never resolves |
| 8 | **LOW** | Duplicate "Report History" section in Reports tab |

---

## 6. Critical Findings — Background Jobs & Automation

### 9 Background Jobs (all functional)

| Job | Schedule | Status |
|-----|----------|--------|
| Network discovery | Every 5 min | Working |
| Security audit | Weekly Sun 3 AM | Working |
| SSL expiry check | Every 24h | Working |
| Daily DNS report | Daily 7 AM | Working |
| Query spike detection | Every 1h | Working |
| Camera anomaly | Every 1h | Needs HA |
| Auto-block | Every 15 min | Working |
| Compliance scan | Every 6h | Working |
| Auto-remediation | Every 6h | Working |

### 9 Suggestion Generators (all functional)

Filter update, new devices, SSL expiry, query spike, camera offline, device offline, SSH threats, DNS block recommendation, access policy conflict.

### Rule Packs Issue
- 178 rules across 5 packs have NO `category` field — category filtering in UI will not work

---

## 7. External Service Status

| Service | Container | Status | Port | Used By |
|---------|-----------|--------|------|---------|
| AdGuard DNS | network_adguard | UP (healthy) | 53, 5354, 5355 | DNS tab, Traffic tab, Overview |
| ntopng | network_ntopng | UP | 3000 (internal) | Traffic tab, NOC |
| Nagios | monitoring_nagios | UP (healthy) | 8082 | NOC, service health |
| NPM | nginx-proxy-manager | UP | 80, 443, 81 | Domains, SSL monitors |
| ZAP | security_zap | UP (healthy) | 8090 | Vulnerability scanner |
| fail2ban | host process | Running | N/A | Defense tab, auto-block |
| Home Assistant | NOT INSTALLED | DOWN | 8123 | Surveillance tab |
| DDNS updater | host script | Running | N/A | Defense tab |

### Missing Scanner Containers
These are referenced in `stack_integration.py` but NOT in docker-compose:
- `security_nmap`
- `security_nikto`
- `security_nuclei`
- `security_testssl`

Only `security_zap` is running.

---

## 8. Optimization Plan — Prioritized

### Phase 1: Fix Broken Features (Blocking)

| # | Task | Severity | Effort |
|---|------|----------|--------|
| 1 | Fix `/api/devices/consumption` 500 error | HIGH | Small |
| 2 | Fix UFW firewall loading errors in Defense tab | HIGH | Small |
| 3 | Fix DNS Domains sub-tab (empty content) | MEDIUM | Small |
| 4 | Fix "System Alert - Loading..." banner that never resolves | MEDIUM | Small |
| 5 | Add missing `time` import to routes.py | MEDIUM | Tiny |
| 6 | Fix broken HTML in Vulnerability/Recon subtab wrappers | MEDIUM | Small |
| 7 | Load Font Awesome CSS for Compliance tab icons | MEDIUM | Tiny |
| 8 | Fix duplicate Report History sections in Reports tab | LOW | Small |

### Phase 2: Code Quality & Splitting (Architecture)

| # | Task | Severity | Effort |
|---|------|----------|--------|
| 1 | Split routes.py (4,042 lines) into ~8 domain route files | HIGH | Large |
| 2 | Extract 3,300 lines inline JS from template to external file(s) | HIGH | Large |
| 3 | Consolidate duplicate utility functions (JS) | HIGH | Medium |
| 4 | Delete `network_integration.py` dead code | HIGH | Tiny |
| 5 | Unify API base variables (SN_API vs API) | MEDIUM | Medium |
| 6 | Remove dead stub `POST /api/auto-block` | MEDIUM | Tiny |
| 7 | Fix shadowed `/api/reports/generate` endpoint | MEDIUM | Small |
| 8 | Remove duplicate AdGuard block endpoints | MEDIUM | Small |
| 9 | Add `@admin_required` to `/api/stacks/status` | LOW | Tiny |
| 10 | Add MAC address validation in device_routes.py | LOW | Tiny |
| 11 | Add jail_name validation in defense_routes.py | LOW | Tiny |

### Phase 3: Security Hardening

| # | Task | Severity | Effort |
|---|------|----------|--------|
| 1 | Fix HA token exposure in surveillance URLs | MEDIUM | Small |
| 2 | Replace hardcoded IPs with env vars/config | LOW | Medium |
| 3 | Replace hardcoded file paths with config | LOW | Medium |
| 4 | Add input validation for scanner targets | LOW | Small |

### Phase 4: Feature Enhancements

| # | Task | Priority | Effort |
|---|------|----------|--------|
| 1 | Populate V.I.G.I.L. Activity Feed with real data | HIGH | Medium |
| 2 | Fix network traffic card (ntopng bandwidth integration) | HIGH | Medium |
| 3 | Add category field to all 178 rule pack rules | MEDIUM | Medium |
| 4 | Deploy missing scanner containers (nmap, nikto, nuclei, testssl) | MEDIUM | Medium |
| 5 | Install Home Assistant for surveillance integration | LOW | Large |
| 6 | Add compliance history chart data | LOW | Medium |
| 7 | Add LCARS responsive breakpoints (480/768/1024px) | LOW | Medium |

---

## 9. What Works Well (Keep)

- **DNS management** is comprehensive — full AdGuard control with 7 sub-tabs
- **Compliance scanning** is mature — 5 rule packs, 178 rules, scoring, badges, evidence
- **Reconnaissance** module is impressive — 32 scan types across 6 categories
- **Report generation** is automated — daily device/user reports running since Mar 31
- **Background jobs** are well-structured — 9 jobs with proper Flask context
- **Suggestion engine** is sophisticated — 9 generators with dedup and auto-execute
- **Service health monitoring** works reliably — all 5 checks passing
- **DNS Clients** tab provides full network visibility — 45 devices with vendor detection
- **Split DNS rewrites** are properly configured for all internal services

---

## 10. What to Remove

| Item | Reason |
|------|--------|
| `network_integration.py` (384 lines) | Dead code, wrong IPs (192.168.1.250), fully replaced by individual services |
| `POST /api/auto-block` stub | Always returns `{"blocked": 0}`, misleading |
| Duplicate `deleteReconScan()` function | Defined twice in inline JS |
| Duplicate utility functions (8+) | Consolidate into single JS file |
| Second "Report History" section | Duplicate of the one above it |

---

## Appendix: Full API Endpoint Map

See `/mnt/archie_brain/docs/audits/2026-04-05-security-network-audit.md` section 9 for the complete endpoint map (~80 endpoints across all route files).

See `/mnt/archie_brain/platform_v2/tools/security_network/ROUTE_AUDIT.md` for per-route-file details.

See `/mnt/archie_brain/platform_v2/tools/security_network/SERVICE_AUDIT_REPORT.md` for per-service details.
