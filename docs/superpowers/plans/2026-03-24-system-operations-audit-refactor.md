# System Operations — Audit & Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the monolithic System Operations module into ADR-045 split routes, extract template CSS/JS, audit all 75 endpoints for security, and pass code health green.

**Architecture:** Split `routes.py` (5,194 lines) into 8 route files following the Starbase pattern (`register_*_routes(bp, admin_required)`). Extract 14,087-line template into HTML + external CSS + external JS. All endpoints keep the same URL paths — this is a pure internal restructure.

**Tech Stack:** Flask Blueprints, psycopg2, Playwright (browser tests), existing LCARS design system

**Spec:** `docs/superpowers/specs/2026-03-24-system-operations-audit-standalone-design.md`

**Scope:** This plan covers Phases 1-3 of the spec (Audit, Route Split, Template Extraction). Phases 4-8 (Theme System, Standalone Package, Starship Integration, Firewall Cleanup, Final Verification) will be separate plans that build on this foundation.

---

## File Map

### Files to Create

| File | Responsibility |
|------|---------------|
| `tools/system_operations/helpers.py` | Shared helpers: `load_host_monitor_data`, `get_db`, `audit_log`, `record_metric`, `require_reauth`, `parse_compose_host_port`, `find_compose_file` (NOT `admin_required` — that lives in `__init__.py` per Starbase pattern) |
| `tools/system_operations/docker_routes.py` | Docker container lifecycle: list, action, logs, health, compose exec, web-ui ports |
| `tools/system_operations/stack_routes.py` | Stack management: CRUD, compose/env editing, logs, status |
| `tools/system_operations/storage_routes.py` | Disks, mounts, LVM, file browser, preflight |
| `tools/system_operations/network_routes.py` | Network interfaces, port map, bandwidth, port usage |
| `tools/system_operations/firewall_routes.py` | UFW: status, rules, enable, disable, allow, deny, update, delete |
| `tools/system_operations/health_routes.py` | Alerts CRUD, config, webhooks, system health full |
| `tools/system_operations/process_routes.py` | Process list, kill, services list, service action |
| `static/css/system-operations.css` | All CSS extracted from template |
| `static/js/system-operations.js` | All JS extracted from template |
| `tests/test-sysops-routes.mjs` | Playwright endpoint + visual regression tests |

### Files to Modify

| File | Changes |
|------|---------|
| `tools/system_operations/__init__.py` | ADR-045 pattern: import + register all route files |
| `tools/system_operations/routes.py` | Slim to ~800 lines: core routes only (index, overview, CPU, memory, hardware, history, audit, host commands, health check) |
| `templates/tools/system_operations.html` | Remove inline `<style>` and `<script>`, add `<link>` and `<script src>` |

---

## Task 1: Create `helpers.py` — Extract Shared Functions

**Files:**
- Create: `platform_v2/tools/system_operations/helpers.py`
- Modify: `platform_v2/tools/system_operations/routes.py` (lines 31-220)

- [ ] **Step 1: Create `helpers.py` with all shared functions**

Extract these functions from `routes.py` into `helpers.py`:
- `load_host_monitor_data()` (lines 31-47)
- `get_db()` (lines 69-78)
- `audit_log()` (lines 80-120)
- `record_metric()` (lines 122-151)
- `require_reauth()` (lines 153-171)
- `parse_compose_host_port()` (lines 173-197)
- `find_compose_file()` (lines 199-215)

**NOTE:** `admin_required` does NOT go in helpers. It is defined once in `__init__.py` (using `require_permission(Permission.ADMIN_ACCESS)`) and passed as a parameter to each `register_*_routes()` function — matching the Starbase pattern exactly. This is a deliberate upgrade from the hand-rolled decorator in the current `routes.py` (which checks `current_user.is_admin` with redirect logic). The `require_permission` approach is the platform standard.

Include all needed imports. The file should be self-contained.

```python
"""
System Operations — Shared Helpers
Used by all route files in this module.
"""

from flask import jsonify, request
from flask_login import current_user
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
from datetime import datetime

BASE_DIR = os.environ.get("ARCHIE_BASE_DIR", "/mnt/archie_brain")
HOST_DATA_FILE = os.path.join(BASE_DIR, "host_monitor_data.json")

def load_host_monitor_data():
    # ... copy exact implementation from routes.py lines 31-47

def get_db():
    # ... copy exact implementation from routes.py lines 69-78

def audit_log(action, details=None, ...):
    # ... copy exact implementation from routes.py lines 80-120

def record_metric(metric_type, value, details=None):
    # ... copy exact implementation from routes.py lines 122-151

def require_reauth():
    # ... copy exact implementation from routes.py lines 153-171

def parse_compose_host_port(port_entry):
    # ... copy exact implementation from routes.py lines 173-197

def find_compose_file(compose_dir):
    # ... copy exact implementation from routes.py lines 199-215
```

- [ ] **Step 2: Update `routes.py` — replace local functions with imports**

At the top of `routes.py`, replace the local function definitions with:

```python
from .helpers import (
    load_host_monitor_data,
    get_db,
    audit_log,
    record_metric,
    require_reauth,
    parse_compose_host_port,
    find_compose_file,
    BASE_DIR,
    HOST_DATA_FILE,
)
```

The `admin_required` decorator will come from the `__init__.py` via the `register_*_routes` pattern for the split route files. For the core routes that remain in `routes.py`, import it from the package init: `from . import admin_required` — but only after Task 9 wires `__init__.py`. Until then, keep the local `admin_required` in `routes.py` and delete it in Task 9.

Delete the other original function definitions (lines 31-47, 69-215). Keep `admin_required` temporarily. Keep the Flask/system imports needed by the remaining routes.

- [ ] **Step 3: Verify the app still starts**

Run: `docker compose restart archie_platform && sleep 3 && docker logs --tail 20 archie_platform`
Expected: No import errors, app boots clean.

- [ ] **Step 4: Verify a few endpoints still work**

Run browser test or curl:
```bash
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3000/tools/system-operations/api/overview -b "session=<cookie>"
```
Expected: 200

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/system_operations/helpers.py platform_v2/tools/system_operations/routes.py
git commit -m "refactor(sysops): extract shared helpers — ADR-045 prep"
```

---

## Task 2: Extract `process_routes.py`

**Files:**
- Create: `platform_v2/tools/system_operations/process_routes.py`
- Modify: `platform_v2/tools/system_operations/routes.py` (remove lines 744-813, 1422-1505)

- [ ] **Step 1: Create `process_routes.py`**

Extract these endpoints:
- `api_processes()` — line 747 (`/api/processes`)
- `api_services()` — line 799 (`/api/services`)
- `api_kill_process(pid)` — line 1425 (`/api/process/<int:pid>/kill`)
- `api_service_action(service_name)` — line 1466 (`/api/service/<service_name>/action`)

File structure:
```python
"""Process & Service Management Routes"""
from flask import jsonify, request
from flask_login import login_required, current_user
from .helpers import get_db, audit_log
from .system_service import get_system_service
from psycopg2.extras import RealDictCursor


def register_process_routes(bp, admin_required_decorator):
    @bp.route("/api/processes")
    @login_required
    @admin_required_decorator
    def api_processes():
        # ... exact code from routes.py

    @bp.route("/api/services")
    @login_required
    @admin_required_decorator
    def api_services():
        # ... exact code from routes.py

    @bp.route("/api/process/<int:pid>/kill", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_kill_process(pid):
        # ... exact code from routes.py

    @bp.route("/api/service/<service_name>/action", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_service_action(service_name):
        # ... exact code from routes.py
```

- [ ] **Step 2: Remove those functions from `routes.py`**

Delete the 4 endpoint functions and their decorators from `routes.py`.

- [ ] **Step 3: Restart and verify**

```bash
docker compose restart archie_platform && sleep 3
curl -s http://192.168.1.200:3000/tools/system-operations/api/processes -b "session=..." | head -c 200
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/system_operations/process_routes.py platform_v2/tools/system_operations/routes.py
git commit -m "refactor(sysops): extract process_routes.py — ADR-045 step 1"
```

---

## Task 3: Extract `docker_routes.py`

**Files:**
- Create: `platform_v2/tools/system_operations/docker_routes.py`
- Modify: `platform_v2/tools/system_operations/routes.py` (remove lines ~811-830, 1111-1257, 1504-1647)

- [ ] **Step 1: Create `docker_routes.py`**

Extract these endpoints:
- `api_docker()` — line 814 (`/api/docker`)
- `api_docker_health()` — line 1114 (`/api/docker/health`)
- `api_update_web_ui_ports(stack_name)` — line 1179 (`/api/stacks/<stack_name>/web-ui-ports`)
- `api_docker_action(container_id)` — line 1507 (`/api/docker/<container_id>/action`)
- `api_docker_compose()` — line 1548 (`/api/docker/compose`)
- `api_docker_logs(container_id)` — line 1617 (`/api/docker/<container_id>/logs`)

Same `register_docker_routes(bp, admin_required_decorator)` pattern.

- [ ] **Step 2: Remove from `routes.py`**
- [ ] **Step 3: Restart and verify**
- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(sysops): extract docker_routes.py — ADR-045 step 2"
```

---

## Task 4: Extract `stack_routes.py`

**Files:**
- Create: `platform_v2/tools/system_operations/stack_routes.py`
- Modify: `platform_v2/tools/system_operations/routes.py`

- [ ] **Step 1: Create `stack_routes.py`**

Extract these endpoints (the largest group, ~900 lines):
- `api_get_compose()` — line 1648 (`/api/stack/compose` GET)
- `api_save_compose()` — line 1712 (`/api/stack/compose` PUT)
- `api_get_env()` — line 1775 (`/api/stack/env` GET)
- `api_save_env()` — line 1815 (`/api/stack/env` PUT)
- `api_list_stacks()` — line 1873 (`/api/stacks` GET)
- `api_create_stack()` — line 1978 (`/api/stacks` POST)
- `api_get_stack(stack_name)` — line 2136 (`/api/stacks/<stack_name>` GET)
- `api_delete_stack(stack_name)` — line 2222 (`/api/stacks/<stack_name>` DELETE)
- `api_stack_action(stack_name)` — line 2340 (`/api/stacks/<stack_name>/action`)
- `api_get_stack_compose(stack_name)` — line 2473 (`/api/stacks/<stack_name>/compose` GET)
- `api_save_stack_compose(stack_name)` — line 2574 (`/api/stacks/<stack_name>/compose` PUT)
- `api_get_stack_env(stack_name)` — line 2655 (`/api/stacks/<stack_name>/env` GET)
- `api_save_stack_env(stack_name)` — line 2729 (`/api/stacks/<stack_name>/env` PUT)
- `api_stack_logs(stack_name)` — line 2821 (`/api/stacks/<stack_name>/logs`)
- `api_stacks_status()` — line 5050 (`/api/stacks/status`) **WARNING: This endpoint is ~2,200 lines away from the other stack routes (near end of file). Search the entire file for it, don't just take the contiguous block.**

This file needs `find_compose_file` and `parse_compose_host_port` from helpers.

- [ ] **Step 2: Remove from `routes.py`**
- [ ] **Step 3: Restart and verify**
- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(sysops): extract stack_routes.py — ADR-045 step 3"
```

---

## Task 5: Extract `storage_routes.py`

**Files:**
- Create: `platform_v2/tools/system_operations/storage_routes.py`
- Modify: `platform_v2/tools/system_operations/routes.py`

- [ ] **Step 1: Create `storage_routes.py`**

Extract these endpoints:
- `api_mount_disk(device)` — line 2883 (`/api/disk/<device>/mount`)
- `api_unmount_disk(device)` — line 2956 (`/api/disk/<device>/unmount`)
- `api_extend_lvm(vg_name, lv_name)` — line 3032 (`/api/lvm/<vg_name>/<lv_name>/extend`)
- `api_filesystem_resize()` — line 3125 (`/api/filesystem/resize`)
- `api_lvm_info()` — line 3190 (`/api/lvm/info`)
- `api_storage_drives()` — line 3352 (`/api/storage/drives`)
- `api_storage_mounts()` — line 3423 (`/api/storage/mounts`)
- `api_register_storage_mount()` — line 3460 (`/api/storage/mounts/register`)
- `api_storage_browse()` — line 3520 (`/api/storage/browse`)
- `api_storage_docker_mounts()` — line 3586 (`/api/storage/docker-mounts`)
- `api_storage_preflight()` — line 3694 (`/api/storage/preflight`)

This file needs `submit_and_wait`, `HostCommandTimeout`, `HostCommandQueueUnavailable` from host_command_client.

- [ ] **Step 2: Remove from `routes.py`**
- [ ] **Step 3: Restart and verify**
- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(sysops): extract storage_routes.py — ADR-045 step 4"
```

---

## Task 6: Extract `network_routes.py`

**Files:**
- Create: `platform_v2/tools/system_operations/network_routes.py`
- Modify: `platform_v2/tools/system_operations/routes.py`

- [ ] **Step 1: Create `network_routes.py`**

Extract these endpoints:
- `api_network()` — line 827 (`/api/network`)
- `api_network_port_map()` — line 921 (`/api/network/port-map`)
- `api_network_bandwidth()` — line 1026 (`/api/network/bandwidth`)
- `api_port_usage()` — line 1065 (`/api/network/port-usage`)

- [ ] **Step 2: Remove from `routes.py`**
- [ ] **Step 3: Restart and verify**
- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(sysops): extract network_routes.py — ADR-045 step 5"
```

---

## Task 7: Extract `firewall_routes.py`

**Files:**
- Create: `platform_v2/tools/system_operations/firewall_routes.py`
- Modify: `platform_v2/tools/system_operations/routes.py`

- [ ] **Step 1: Create `firewall_routes.py`**

Extract these endpoints:
- `parse_ufw_rules(output)` — line 4436 (helper function, goes in this file not helpers.py since only firewall uses it)
- `api_firewall_status()` — line 4477 (`/api/firewall/status`)
- `api_firewall_rules()` — line 4519 (`/api/firewall/rules`)
- `api_firewall_enable()` — line 4572 (`/api/firewall/enable`)
- `api_firewall_disable()` — line 4627 (`/api/firewall/disable`)
- `api_firewall_allow()` — line 4682 (`/api/firewall/allow`)
- `api_firewall_deny()` — line 4764 (`/api/firewall/deny`)
- `api_firewall_update()` — line 4846 (`/api/firewall/update`)
- `api_firewall_delete()` — line 4962 (`/api/firewall/delete`)

All firewall endpoints use `submit_and_wait` from host_command_client.

- [ ] **Step 2: Remove from `routes.py`**
- [ ] **Step 3: Restart and verify**
- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(sysops): extract firewall_routes.py — ADR-045 step 6"
```

---

## Task 8: Extract `health_routes.py`

**Files:**
- Create: `platform_v2/tools/system_operations/health_routes.py`
- Modify: `platform_v2/tools/system_operations/routes.py`

- [ ] **Step 1: Create `health_routes.py`**

Extract these endpoints:
- `get_health_alerts()` — line 4024 (`/api/health/alerts`)
- `acknowledge_health_alert(alert_id)` — line 4092 (`/api/health/alerts/<id>/acknowledge`)
- `resolve_health_alert(alert_id)` — line 4138 (`/api/health/alerts/<id>/resolve`)
- `get_health_config()` — line 4178 (`/api/health/config`)
- `update_health_config()` — line 4208 (`/api/health/config` PUT)
- `get_health_webhooks()` — line 4265 (`/api/health/webhooks`)
- `create_health_webhook()` — line 4295 (`/api/health/webhooks` POST)
- `delete_health_webhook(webhook_id)` — line 4339 (`/api/health/webhooks/<id>` DELETE)
- `test_health_webhook(webhook_id)` — line 4369 (`/api/health/webhooks/<id>/test`)
- `api_system_health_full()` — line 5175 (`/api/system-health-full`)

- [ ] **Step 2: Remove from `routes.py`**
- [ ] **Step 3: Restart and verify**
- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(sysops): extract health_routes.py — ADR-045 step 7"
```

---

## Task 9: Update `__init__.py` — ADR-045 Registration

**Files:**
- Modify: `platform_v2/tools/system_operations/__init__.py`

- [ ] **Step 1: Rewrite `__init__.py` to match Starbase pattern**

```python
"""
System Operations Module
========================
Host machine administration interface for CPU, RAM, disk,
process, service, Docker, and network management.

Provides real-time monitoring and control of the A.R.C.H.I.E. host server.
"""

from flask import Blueprint

system_operations_bp = Blueprint(
    "system_operations", __name__, url_prefix="/tools/system-operations"
)

from . import routes  # noqa: F401, E402
from flask_login import login_required  # noqa: F401, E402
from rbac import require_permission, Permission  # noqa: E402

# Define admin_required HERE (Starbase pattern) — replaces the hand-rolled
# decorator from old routes.py. This is a deliberate upgrade to the platform
# standard. Passed as parameter to all register_*_routes() functions.
admin_required = require_permission(Permission.ADMIN_ACCESS)

from .process_routes import register_process_routes  # noqa: E402
from .docker_routes import register_docker_routes  # noqa: E402
from .stack_routes import register_stack_routes  # noqa: E402
from .storage_routes import register_storage_routes  # noqa: E402
from .network_routes import register_network_routes  # noqa: E402
from .firewall_routes import register_firewall_routes  # noqa: E402
from .health_routes import register_health_routes  # noqa: E402

register_process_routes(system_operations_bp, admin_required)
register_docker_routes(system_operations_bp, admin_required)
register_stack_routes(system_operations_bp, admin_required)
register_storage_routes(system_operations_bp, admin_required)
register_network_routes(system_operations_bp, admin_required)
register_firewall_routes(system_operations_bp, admin_required)
register_health_routes(system_operations_bp, admin_required)

__all__ = ["system_operations_bp"]
```

- [ ] **Step 2: Verify `routes.py` only has core routes left**

After all extractions, `routes.py` should contain:
- `index()` — main page
- `api_overview()` — dashboard overview
- `api_cpu()` — CPU info
- `api_memory()` — memory info
- `api_memory_hardware()` — memory hardware
- `api_hardware()` — hardware info + upgrade helpers (`_compute_upgrade_summary`, `_get_cpu_upgrade_info`, `_get_gpu_slot_info`, `_analyze_memory_config`) **NOTE: These 4 private helpers (lines 458-730) stay in routes.py with their only consumer — do NOT extract to helpers.py**
- `api_disks()` — disk info (read-only, distinct from storage management)
- `api_history()` — metric history
- `api_history_multi()` — multi-metric history
- `api_auth_verify()` — re-auth verification
- `api_audit_log()` — audit log viewer
- `api_host_data()` — host monitor data
- `api_host_command_status()` — host command queue status
- `api_host_command_submit()` — submit host command
- `api_host_command_result(command_id)` — get command result
- `health_check()` — health endpoint

Expected: ~800-1000 lines.

- [ ] **Step 3: Full restart and test all tabs**

```bash
docker compose restart archie_platform && sleep 5
```

Open http://192.168.1.200:3000/tools/system-operations and click through all tabs:
Dashboard, Storage, Hardware, Memory, Processes, Docker, Network, Firewall, Health, Stacks

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/system_operations/__init__.py platform_v2/tools/system_operations/routes.py
git commit -m "refactor(sysops): ADR-045 init registration — all 8 route files wired"
```

---

## Task 10: Extract Template CSS to `system-operations.css`

**Files:**
- Create: `platform_v2/static/css/system-operations.css`
- Modify: `platform_v2/templates/tools/system_operations.html`

- [ ] **Step 1: Extract all CSS from `<style>` blocks in template**

The template has a large `<style>` block inside `{% block styles %}`. Extract everything between `<style>` and `</style>` into `static/css/system-operations.css`.

Keep the `{% block styles %}` block but replace content with a `<link>` tag:

```html
{% block styles %}
<link rel="stylesheet" href="/static/css/lcars-frames.css">
<link rel="stylesheet" href="/static/css/system-operations.css">
{% endblock %}
```

- [ ] **Step 2: Verify CSS loads correctly**

```bash
docker compose restart archie_platform
```

Open http://192.168.1.200:3000/tools/system-operations — verify all tabs render correctly with proper styling.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/static/css/system-operations.css platform_v2/templates/tools/system_operations.html
git commit -m "refactor(sysops): extract CSS to system-operations.css"
```

---

## Task 11: Extract Template JS to `system-operations.js`

**Files:**
- Create: `platform_v2/static/js/system-operations.js`
- Modify: `platform_v2/templates/tools/system_operations.html`

- [ ] **Step 1: Extract all JS from `<script>` blocks in template**

The template has a large `<script>` block inside `{% block scripts %}` (or at the bottom). Extract all JavaScript into `static/js/system-operations.js`.

Replace the inline script with:

```html
{% block scripts %}
<script src="/static/js/system-operations.js"></script>
{% endblock %}
```

**Watch for Jinja2 variables in JS.** The current template has been verified to have NO `{{` or `{%` inside `<script>` blocks — the JS uses API paths directly. However, if any are found during extraction, pass those values as data attributes or a config object:

```html
<div id="sysops-app" data-api-base="/tools/system-operations/api"></div>
<script src="/static/js/system-operations.js"></script>
```

- [ ] **Step 2: Verify JS loads and all interactive features work**

Test each tab's interactive features:
- Dashboard: auto-refresh, gauges
- Docker: container actions (start/stop)
- Stacks: stack creation wizard, compose editor
- Firewall: rule add/delete
- Processes: kill process
- Storage: mount/unmount, LVM extend, file browser

- [ ] **Step 3: Commit**

```bash
git add platform_v2/static/js/system-operations.js platform_v2/templates/tools/system_operations.html
git commit -m "refactor(sysops): extract JS to system-operations.js"
```

---

## Task 12: Security Audit — Review All Endpoints

**Files:**
- Modify: Various route files as needed for fixes

This task is a review pass, not extraction. Read each route file and check:

- [ ] **Step 1: Auth decorators — verify every endpoint has `@login_required` + `@admin_required`**

```bash
# Find any endpoint missing auth decorators
grep -n '@bp.route\|@system_operations_bp.route' platform_v2/tools/system_operations/*.py | while read line; do
    file=$(echo "$line" | cut -d: -f1)
    lineno=$(echo "$line" | cut -d: -f2)
    # Check if preceding 2 lines have login_required and admin_required
    sed -n "$((lineno-2)),$((lineno))p" "$file"
    echo "---"
done
```

- [ ] **Step 2: Input validation on destructive endpoints**

Check these critical endpoints:
- `api_kill_process(pid)` — PID must be int > 2, not in protected list [1, 2]
- `api_extend_lvm(vg_name, lv_name)` — names must match `[a-zA-Z0-9_-]+`
- `api_firewall_allow/deny()` — port must be 1-65535, IP must be valid format
- `api_create_stack()` — stack name must match `[a-zA-Z0-9_-]+`
- `api_delete_stack()` — must not delete system stacks
- `api_storage_browse()` — path must not contain `../`, must be under allowed root

- [ ] **Step 3: Path traversal on file operations**

Check these endpoints accept file paths:
- `api_get_compose()` / `api_save_compose()` — compose_directory must be validated
- `api_get_env()` / `api_save_env()` — env file path must not escape compose directory
- `api_storage_browse()` — must jail to allowed directories
- `api_get_stack_compose()` / `api_save_stack_compose()` — stack directory must exist in DB

For each, verify there's a `os.path.realpath()` check that the resolved path starts with the allowed root.

- [ ] **Step 4: Fix any issues found, document in commit message**

```bash
git commit -m "security(sysops): input validation + path traversal fixes

- Added PID protection in kill_process (reject pid <= 2)
- Added regex validation on LVM vg/lv names
- Added realpath jail on compose/env file operations
- Added port range validation on firewall rules
- Added stack name validation on CRUD operations
[list actual fixes]"
```

---

## Task 13: Playwright Endpoint Verification Test

**Files:**
- Create: `platform_v2/tests/test-sysops-routes.mjs`

- [ ] **Step 1: Write Playwright test that hits every API endpoint**

```javascript
/**
 * System Operations — Route Split Verification
 * Ensures all endpoints still respond after ADR-045 refactor.
 */
import { chromium } from 'playwright';

const BASE = process.env.ARCHIE_URL || 'http://192.168.1.200:3000';
const CREDS = {
  username: process.env.ARCHIE_TEST_USER || 'admin',
  password: process.env.ARCHIE_TEST_PASS || 'Kyt$13ran2025',
};

const ENDPOINTS = [
  // Core
  { path: '/tools/system-operations', expect: 200, name: 'index' },
  { path: '/tools/system-operations/api/overview', expect: 200, name: 'overview' },
  { path: '/tools/system-operations/api/cpu', expect: 200, name: 'cpu' },
  { path: '/tools/system-operations/api/memory', expect: 200, name: 'memory' },
  { path: '/tools/system-operations/api/memory-hardware', expect: 200, name: 'memory-hw' },
  { path: '/tools/system-operations/api/hardware', expect: 200, name: 'hardware' },
  { path: '/tools/system-operations/api/disks', expect: 200, name: 'disks' },
  { path: '/tools/system-operations/api/host-data', expect: 200, name: 'host-data' },
  { path: '/tools/system-operations/health', expect: 200, name: 'health' },
  // Process
  { path: '/tools/system-operations/api/processes', expect: 200, name: 'processes' },
  { path: '/tools/system-operations/api/services', expect: 200, name: 'services' },
  // Docker
  { path: '/tools/system-operations/api/docker', expect: 200, name: 'docker' },
  { path: '/tools/system-operations/api/docker/health', expect: 200, name: 'docker-health' },
  // Network
  { path: '/tools/system-operations/api/network', expect: 200, name: 'network' },
  { path: '/tools/system-operations/api/network/port-map', expect: 200, name: 'port-map' },
  { path: '/tools/system-operations/api/network/bandwidth', expect: 200, name: 'bandwidth' },
  { path: '/tools/system-operations/api/network/port-usage', expect: 200, name: 'port-usage' },
  // Firewall
  { path: '/tools/system-operations/api/firewall/status', expect: 200, name: 'fw-status' },
  { path: '/tools/system-operations/api/firewall/rules', expect: 200, name: 'fw-rules' },
  // Stacks
  { path: '/tools/system-operations/api/stacks', expect: 200, name: 'stacks' },
  { path: '/tools/system-operations/api/stacks/status', expect: 200, name: 'stacks-status' },
  // Storage
  { path: '/tools/system-operations/api/storage/drives', expect: 200, name: 'drives' },
  { path: '/tools/system-operations/api/storage/mounts', expect: 200, name: 'mounts' },
  { path: '/tools/system-operations/api/lvm/info', expect: 200, name: 'lvm-info' },
  // Health
  { path: '/tools/system-operations/api/health/alerts', expect: 200, name: 'alerts' },
  { path: '/tools/system-operations/api/health/config', expect: 200, name: 'health-config' },
  { path: '/tools/system-operations/api/health/webhooks', expect: 200, name: 'webhooks' },
  { path: '/tools/system-operations/api/system-health-full', expect: 200, name: 'full-health' },
];

async function run() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();

  // Login
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle', timeout: 15000 });
  await page.fill('#username', CREDS.username);
  await page.fill('#password', CREDS.password);
  await page.click('#loginBtn');
  await page.waitForURL(url => !url.pathname.startsWith('/login'), { timeout: 10000 });

  let passed = 0, failed = 0;
  for (const ep of ENDPOINTS) {
    try {
      const resp = await page.request.get(`${BASE}${ep.path}`);
      if (resp.status() === ep.expect) {
        console.log(`  PASS  ${ep.name} (${resp.status()})`);
        passed++;
      } else {
        console.log(`  FAIL  ${ep.name} expected ${ep.expect} got ${resp.status()}`);
        failed++;
      }
    } catch (e) {
      console.log(`  FAIL  ${ep.name}: ${e.message}`);
      failed++;
    }
  }

  console.log(`\n${passed} passed, ${failed} failed out of ${ENDPOINTS.length}`);
  await browser.close();
  process.exit(failed > 0 ? 1 : 0);
}

run().catch(console.error);
```

- [ ] **Step 2: Run the test**

```bash
cd /mnt/archie_brain/platform_v2/tests && node test-sysops-routes.mjs
```

Expected: All endpoints pass (200).

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tests/test-sysops-routes.mjs
git commit -m "test(sysops): endpoint verification after ADR-045 split"
```

---

## Task 14: Code Health Verification

- [ ] **Step 1: Verify line counts**

```bash
wc -l platform_v2/tools/system_operations/*.py
# Expected: routes.py < 1000, each other file < 900

wc -l platform_v2/templates/tools/system_operations.html
# Expected: < 3500 (after CSS+JS extraction)

wc -l platform_v2/static/css/system-operations.css platform_v2/static/js/system-operations.js
# Expected: CSS ~2500, JS ~8500
```

- [ ] **Step 2: Verify no inline CSS/JS remains in template**

```bash
grep -c '<style>' platform_v2/templates/tools/system_operations.html
# Expected: 0

grep -c '<script>' platform_v2/templates/tools/system_operations.html
# Expected: 1 (the src= reference only)
```

- [ ] **Step 3: Run code health scanner if available**

```bash
# From inside the platform, trigger a code health scan
curl -X POST http://192.168.1.200:3000/tools/dev-hq/api/code-health/scan -b "session=..."
```

- [ ] **Step 4: Final browser test — all tabs, all features**

Navigate through every tab and verify interactive features work. Take screenshots for proof.

- [ ] **Step 5: Final commit with summary**

```bash
git commit --allow-empty -m "milestone(sysops): ADR-045 refactor complete — code health green

Route split: 1 file (5194 lines) → 8 files (max ~1000 lines each)
Template: 14087 lines → ~3000 HTML + 2500 CSS + 8500 JS
Security: 17-point audit complete
All endpoints verified via Playwright"
```
