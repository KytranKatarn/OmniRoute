---
name: admin-security-network
description: Work on Security Network module — DNS, devices, compliance scanning, NOC, sinkhole, supervision schedules, AdGuard, threat intel
---

# Security Network Module

**Path**: `platform_v2/tools/security_network/` | **URL**: `/tools/security-network`
**KB Docs**: #263992 (full user + developer guide)

## Tabs
Overview → Devices → DNS → Compliance → SSL → NOC → Threat Intel → Sinkhole → Supervision → Cameras → Reports

## Key Files
| File | Responsibility |
|------|---------------|
| `routes.py` | Main tab routes (1170 lines) |
| `compliance_service.py` | JSON rule pack engine (3577 lines) |
| `security_service.py` | Core scanning (625 lines) |
| `noc_routes.py` | NOC charts + bandwidth (862 lines) |
| `sinkhole_routes.py` | DNS sinkhole (656 lines) |
| `scanner_routes.py` | Recon scans (1263 lines) |
| `supervision_service.py` | AdGuard schedule enforcement |
| `threat_intel_routes.py` | IOC feed management |
| `device_routes.py` | Device discovery + registry |
| `domain_npm_routes.py` | DNS + NPM proxy management |
| `agent_automation.py` | Agent loop job glue (863 lines) |
| `jobs.py` | 23 scheduled jobs (1966 lines) |

## SQL Safety Rule
All dynamic SQL uses string concatenation — NOT f-strings (PR #551):
```python
# Correct pattern:
cur.execute("SELECT ... WHERE " + where_clause + " ORDER BY ...", params)
# NEVER:
cur.execute(f"SELECT ... WHERE {where_clause}", params)
```

## Compliance Rule Packs (5 active)
- `ubuntu-stig`: 51 rules | `docker-stig`: 30 | `hipaa`: 30 | `network-stig`: 27 | `cis-ubuntu`: 40
- Rule format: `{rule_id, severity, check_type, fix, soc2_mapping}`
- Packs are JSON in `rule_packs/` — add rules without code changes

## Supervision Schedules
```python
# Schedule format:
{"weekday": {"start": "22:00", "end": "07:00"}, "weekend": {"start": "23:00", "end": "09:00"}}
# Blocked categories: ["social", "gaming", "streaming", "adult"]
# Enforced every 5min via SupervisionService.enforce_schedules()
# AdGuard client ID: f"supervision-{mac.replace(':', '-')}"
```

## AdGuard Integration
- `AdGuardService._request(method, endpoint, data)` — REST wrapper
- Client update: `POST clients/update` → fallback to `POST clients/add`
- Device discovery: ARP sweep + AdGuard query log (every 5min)

## Agent Loop Jobs (23 jobs — all in jobs.py)
Key jobs: `device_discovery` (5min), `supervision_enforcement` (5min),
`compliance_scan_job` (6h), `ssl_cert_check` (24h), `check_fleet_health` (30s)

## QA Suites
- #5 Scanner E2E: **6/6** | #6 Core Tabs: **8/8** | #8 Advanced Tabs: **7/7** = **21/21 passed** (2026-05-06)
- Code health: ✅ completed, 0 red issues

## Common Tasks
- **Add a compliance rule**: edit the JSON file in `rule_packs/`
- **Add a blocked category**: update `CATEGORY_DOMAINS` in `supervision_service.py`
- **Add a NOC chart**: add route in `noc_routes.py` + chart in template
- **Debug device not appearing**: check AdGuard container + ARP scan logs in `agent_automation.py`
