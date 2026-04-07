# Security Network Phase 2: Code Quality & Route Splitting

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split routes.py (4,146 lines) into focused domain files following ADR-045 pattern, delete dead code, and fix endpoint conflicts.

**Architecture:** Extract route groups from routes.py into new `register_*_routes(bp, admin_required)` files following the existing pattern (see compliance_routes.py, defense_routes.py). Wire each in `__init__.py`. Delete dead code. Every endpoint must keep its exact URL — zero breaking changes.

**Tech Stack:** Python/Flask, ADR-045 route splitting pattern

**CRITICAL SAFETY:** AdGuard is the LIVE DNS server. All AdGuard routes must maintain exact backward compatibility. Test DNS tab after AdGuard route extraction.

---

## File Structure

### New files to create (8):
| File | Routes moved | Est. lines |
|------|-------------|------------|
| `adguard_routes.py` | 18 AdGuard routes (L930-L2511) | ~350 |
| `hostinger_routes.py` | 5 Hostinger routes (L2537-L2709) | ~180 |
| `surveillance_routes.py` | 8 surveillance routes (L2734-L2925) | ~200 |
| `scanner_routes.py` | 17 scanner/SSL/recon routes (L649-L3036) | ~400 |
| `domain_routes.py` | 17 domain/NPM/nginx routes (L3228-L4133) | ~450 |
| `device_registry_routes.py` | 8 device registry routes (L3806-L3954) | ~180 |
| `agent_routes.py` | 8 agent automation routes (L3062-L3205) | ~160 |
| `firewall_routes.py` | 7 firewall routes (L977-L1082) | ~120 |

### Files to modify:
- `routes.py` — remove extracted routes, keep core (~600 lines)
- `__init__.py` — register new route files
- `network_integration.py` — DELETE (dead code)

### What stays in routes.py (~28 core routes):
- `index()` — page render
- `api_stats()` — dashboard stats
- `auto_block()` and related (6 routes) — will be cleaned up
- `audit_log()` — audit log
- `network_overview()`, `security_threats()` — legacy
- `docker_security()` — Docker analysis
- `external_tools_status()` — stack health
- `health_check()` — health endpoint
- `api_ip_access_*` — IP access control (3 routes)
- `api_security_events` / `api_resolve_event` — events
- `api_dashboard_stats` — overview stats
- `api_alert_config` — alert configuration
- Helper functions: `admin_required`, `get_system_health`

---

### Task 1: Delete Dead Code

**Files:**
- Delete: `platform_v2/tools/security_network/network_integration.py`
- Modify: `platform_v2/tools/security_network/routes.py`

- [ ] **Step 1: Verify network_integration.py is not imported anywhere**

```bash
grep -r "network_integration" platform_v2/tools/security_network/ --include="*.py" | grep -v __pycache__ | grep -v "network_integration.py"
```

If nothing imports it, it's safe to delete.

- [ ] **Step 2: Delete the file**

```bash
rm platform_v2/tools/security_network/network_integration.py
rm -f platform_v2/tools/security_network/__pycache__/network_integration.cpython-*.pyc
```

- [ ] **Step 3: Remove dead auto-block stub**

In `routes.py`, find the route at line ~137:
```python
@security_network_bp.route("/api/auto-block", methods=["POST"])
```
This stub always returns `{"blocked": 0}`. Remove the entire function `auto_block()` (approximately lines 137-155). The real auto-block is at `/api/auto-block/execute`.

Also remove the duplicate `security_auto_block()` at line ~350 (the one under `/api/security/auto-block`) — it's the same dead pattern.

- [ ] **Step 4: Remove duplicate AdGuard block endpoint**

Find `adguard_block_domain()` at line ~948 (route `/api/adguard/block`). This is a legacy duplicate of the newer `/api/dns/adguard/block` at line ~2450. Remove the legacy one.

Similarly find `adguard_stats()` at line ~930 (route `/api/adguard/stats`) — duplicate of `/api/dns/adguard/stats`. Remove it.

- [ ] **Step 5: Add `@admin_required` to stacks status route**

Find the `stacks_status()` function (route `/api/stacks/status`, around line 600). It has `@login_required` but not `@admin_required`. Add `@admin_required` after `@login_required`.

- [ ] **Step 6: Commit**

```bash
git add -A platform_v2/tools/security_network/
git commit -m "refactor: delete dead code (network_integration.py, stub routes, duplicate endpoints)"
```

---

### Task 2: Extract AdGuard Routes

**CRITICAL: AdGuard is the live DNS server. Test DNS tab after this extraction.**

**Files:**
- Create: `platform_v2/tools/security_network/adguard_routes.py`
- Modify: `platform_v2/tools/security_network/routes.py` (remove 18 routes)
- Modify: `platform_v2/tools/security_network/__init__.py` (register)

- [ ] **Step 1: Create adguard_routes.py**

Create the file following the exact pattern from `compliance_routes.py`:

```python
"""
AdGuard DNS Routes
==================
REST endpoints for AdGuard Home DNS management.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)


def register_adguard_routes(bp, admin_required_decorator):
    """Register all AdGuard DNS endpoints on the security_network blueprint."""

    # ... paste all 18 AdGuard route functions here ...
    # Change @admin_required to @admin_required_decorator
    # Change @security_network_bp.route to @bp.route
    # Keep all other code identical
```

The 18 routes to move (all `/api/dns/adguard/*`):
- `api_dns_adguard_stats`
- `api_dns_adguard_querylog`
- `api_dns_adguard_filters_get`, `_add`, `_toggle`, `_remove`, `_refresh`
- `api_dns_adguard_rewrites_get`, `_add`, `_delete`
- `api_dns_adguard_clients`
- `api_dns_adguard_rules_get`, `_set`
- `api_dns_adguard_block`, `_unblock`
- `api_dns_adguard_protection`

Each function needs:
- `@bp.route(...)` instead of `@security_network_bp.route(...)`
- `@admin_required_decorator` instead of `@admin_required`
- Import any services used (check for `AdGuardService`, `stack_integration`, `create_security_alert`)

- [ ] **Step 2: Remove the 18 routes from routes.py**

Delete all the AdGuard route functions from routes.py. Search for each function name and remove the complete function block.

- [ ] **Step 3: Register in __init__.py**

In `__init__.py`, add after the existing imports:

```python
from .adguard_routes import register_adguard_routes
```

And add after the existing `register_*_routes` calls:

```python
register_adguard_routes(security_network_bp, _admin_required)
```

- [ ] **Step 4: Deploy and verify DNS tab**

```bash
docker compose restart archie_platform
```

Open http://192.168.1.200:3000/tools/security-network, go to DNS tab. Test ALL sub-tabs:
- Overview: stats load
- Query Log: entries display
- Filters: toggle/add works
- Rewrites: list displays
- Rules: rules display
- Clients: client list loads

**If ANY DNS functionality breaks, revert immediately.** AdGuard is the live DNS server.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/security_network/adguard_routes.py platform_v2/tools/security_network/routes.py platform_v2/tools/security_network/__init__.py
git commit -m "refactor: extract 18 AdGuard routes to adguard_routes.py (ADR-045)"
```

---

### Task 3: Extract Hostinger Routes

**Files:**
- Create: `platform_v2/tools/security_network/hostinger_routes.py`
- Modify: `platform_v2/tools/security_network/routes.py` (remove 5 routes)
- Modify: `platform_v2/tools/security_network/__init__.py` (register)

- [ ] **Step 1: Create hostinger_routes.py**

Same pattern as Task 2. Move these 5 routes:
- `api_dns_hostinger_records_get`
- `api_dns_hostinger_records_add`
- `api_dns_hostinger_records_update`
- `api_dns_hostinger_records_delete`
- `api_dns_hostinger_domains`

Check for imports: likely needs `HostingerService` from `hostinger_service.py`.

- [ ] **Step 2: Remove from routes.py, register in __init__.py**

```python
from .hostinger_routes import register_hostinger_routes
register_hostinger_routes(security_network_bp, _admin_required)
```

- [ ] **Step 3: Deploy, verify DNS > Domains sub-tab still works**

```bash
docker compose restart archie_platform
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/security_network/hostinger_routes.py platform_v2/tools/security_network/routes.py platform_v2/tools/security_network/__init__.py
git commit -m "refactor: extract 5 Hostinger routes to hostinger_routes.py (ADR-045)"
```

---

### Task 4: Extract Surveillance Routes

**Files:**
- Create: `platform_v2/tools/security_network/surveillance_routes.py`
- Modify: `platform_v2/tools/security_network/routes.py` (remove 8 routes)
- Modify: `platform_v2/tools/security_network/__init__.py` (register)

- [ ] **Step 1: Create surveillance_routes.py**

Move 8 routes (`/api/surveillance/*`):
- `api_surveillance_cameras`, `_snapshot`, `_stream`, `_stream_proxy`
- `api_surveillance_status`, `_arm`, `_disarm`, `_events`

Check imports: likely needs `HASurveillanceService` from `ha_surveillance_service.py`.

- [ ] **Step 2: Remove from routes.py, register in __init__.py**

```python
from .surveillance_routes import register_surveillance_routes
register_surveillance_routes(security_network_bp, _admin_required)
```

- [ ] **Step 3: Deploy, verify Scanners > Surveillance sub-tab**

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/security_network/surveillance_routes.py platform_v2/tools/security_network/routes.py platform_v2/tools/security_network/__init__.py
git commit -m "refactor: extract 8 surveillance routes to surveillance_routes.py (ADR-045)"
```

---

### Task 5: Extract Scanner Routes

**Files:**
- Create: `platform_v2/tools/security_network/scanner_routes.py`
- Modify: `platform_v2/tools/security_network/routes.py` (remove 17 routes)
- Modify: `platform_v2/tools/security_network/__init__.py` (register)

- [ ] **Step 1: Create scanner_routes.py**

Move 17 routes (scanners + SSL + recon):
- `run_nmap_scan`, `run_nikto_scan`, `run_nuclei_scan`, `run_ssl_scan`, `run_zap_scan`
- `scanner_status`, `list_scans`, `get_scan_result`
- `api_check_ssl`, `api_ssl_monitors`, `api_add_ssl_monitor`, `api_refresh_ssl_monitors`
- `api_recon_modules`, `api_recon_start_scan`, `api_recon_scan_status`, `api_recon_history`, `api_recon_delete_scan`

Check imports: likely needs `SecurityScannerService` from `stack_integration.py`, `get_db_cursor`, `os`, `json`.

- [ ] **Step 2: Remove from routes.py, register in __init__.py**

```python
from .scanner_routes import register_scanner_routes
register_scanner_routes(security_network_bp, _admin_required)
```

- [ ] **Step 3: Deploy, verify Scanners > Vulnerability and Reconnaissance sub-tabs**

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/security_network/scanner_routes.py platform_v2/tools/security_network/routes.py platform_v2/tools/security_network/__init__.py
git commit -m "refactor: extract 17 scanner/SSL/recon routes to scanner_routes.py (ADR-045)"
```

---

### Task 6: Extract Domain Routes

**Files:**
- Create: `platform_v2/tools/security_network/domain_routes.py`
- Modify: `platform_v2/tools/security_network/routes.py` (remove 17 routes)
- Modify: `platform_v2/tools/security_network/__init__.py` (register)

- [ ] **Step 1: Create domain_routes.py**

Move 17 routes (`/api/domains/*` + `/api/nginx/*`):
- All `api_domains_*` routes (proxy hosts, certificates, overview, quick setup, CRUD)
- All `api_nginx_*` routes (list configs, get config, test, reload)

Check imports: likely needs `NpmService` from `npm_service.py`, `HostingerService`, `get_db_cursor`.

Note: There's already a `device_routes.py` — the new file is `domain_routes.py` (domains, not devices).

- [ ] **Step 2: Remove from routes.py, register in __init__.py**

```python
from .domain_routes import register_domain_routes
register_domain_routes(security_network_bp, _admin_required)
```

- [ ] **Step 3: Deploy, verify DNS > Domains sub-tab**

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/security_network/domain_routes.py platform_v2/tools/security_network/routes.py platform_v2/tools/security_network/__init__.py
git commit -m "refactor: extract 17 domain/NPM/nginx routes to domain_routes.py (ADR-045)"
```

---

### Task 7: Extract Remaining Route Groups

Extract the last 3 groups in one task since they're smaller.

**Files:**
- Create: `platform_v2/tools/security_network/firewall_routes.py` (7 routes)
- Create: `platform_v2/tools/security_network/device_registry_routes.py` (8 routes)
- Create: `platform_v2/tools/security_network/agent_routes.py` (8 routes)
- Modify: `platform_v2/tools/security_network/routes.py`
- Modify: `platform_v2/tools/security_network/__init__.py`

- [ ] **Step 1: Create firewall_routes.py**

Move 7 routes (`/api/firewall/*`):
- `api_firewall_status`, `_rules`, `_enable`, `_disable`, `_allow`, `_deny`, `_delete`

Imports: `host_command_client`, `security_service.get_firewall_status`

- [ ] **Step 2: Create device_registry_routes.py**

Move 8 routes (`/api/devices/*` that are currently in routes.py, NOT device_routes.py):
- `api_devices_list`, `_stats`, `_unregistered`, `_get`, `_register`, `_update`, `_delete`, `_sync`, `_dns_report`

Imports: `DeviceRegistryService` from `device_registry_service.py`

- [ ] **Step 3: Create agent_routes.py**

Move 8 routes (`/api/agent/*`):
- `api_agent_config_get`, `_update`, `_suggestions`, `_approve`, `_dismiss`, `_action_history`, `_pause`, `_resume`

Imports: `agent_automation` module functions

- [ ] **Step 4: Remove all from routes.py, register all 3 in __init__.py**

```python
from .firewall_routes import register_firewall_routes
from .device_registry_routes import register_device_registry_routes
from .agent_routes import register_agent_routes

register_firewall_routes(security_network_bp, _admin_required)
register_device_registry_routes(security_network_bp, _admin_required)
register_agent_routes(security_network_bp, _admin_required)
```

- [ ] **Step 5: Deploy and verify Defense tab (firewall), Devices tab, Agent panel**

```bash
docker compose restart archie_platform
```

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/security_network/firewall_routes.py platform_v2/tools/security_network/device_registry_routes.py platform_v2/tools/security_network/agent_routes.py platform_v2/tools/security_network/routes.py platform_v2/tools/security_network/__init__.py
git commit -m "refactor: extract firewall, device registry, agent routes (ADR-045)"
```

---

### Task 8: Clean Up Core routes.py

After all extractions, routes.py should be ~600-800 lines. Clean it up.

**Files:**
- Modify: `platform_v2/tools/security_network/routes.py`

- [ ] **Step 1: Remove orphaned imports**

After route extraction, many imports in routes.py will be unused. Remove them:
- Service imports that were only used by extracted routes
- Any `try/except ImportError` blocks for services now used only in new files

- [ ] **Step 2: Remove orphaned helper functions**

Check if any helper functions in routes.py were only used by extracted routes. If so, move them to the appropriate new route file or to a shared helpers module.

- [ ] **Step 3: Verify routes.py line count**

```bash
wc -l platform_v2/tools/security_network/routes.py
```

Target: under 800 lines. If still over 600, identify what else can be extracted.

- [ ] **Step 4: Deploy and full verification**

```bash
docker compose restart archie_platform
```

Test ALL 8 tabs:
- Overview, Traffic, DNS (all 7 sub-tabs), Devices, Defense, Scanners (all 3 sub-tabs), Compliance, Reports

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/security_network/routes.py
git commit -m "refactor: clean up core routes.py after extraction (~600 lines)"
```

---

## Verification Checklist

After all tasks, verify:

- [ ] `wc -l routes.py` < 800 lines
- [ ] `network_integration.py` deleted
- [ ] All 8 new route files follow `register_*_routes(bp, admin_required)` pattern
- [ ] `__init__.py` registers all new route files
- [ ] All 8 tabs work in browser (take screenshots)
- [ ] DNS tab ALL sub-tabs work (AdGuard is live DNS — critical)
- [ ] No console errors beyond pre-existing ones
- [ ] `docker logs archie_platform 2>&1 | grep -i error | tail -20` shows no new errors
