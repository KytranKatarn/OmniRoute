---
name: admin-system-operations
description: Work on Kytran System Operations (KSO) — compliance scanning, STIG/CIS/HIPAA, firewall, disk, Docker stack monitoring
---

# System Operations (KSO) Module

**Standalone at**: `server.kytranempowerment.com` (port 8085, hub-local)
**Container**: `kytran-system-operations`
**Source**: `/mnt/archie_brain/kytran-server-manager/`
**KB Docs**: #263994 (full user + developer guide)

> NOTE: The platform module at `/tools/system-operations` is DISABLED in `module_registry.py`.
> All live work happens in the standalone at `/mnt/archie_brain/kytran-server-manager/`.

## Tabs (Standalone)
Dashboard → Compliance → History → Firewall → Storage → Stack → Settings

## Key Files (Standalone)
```
kytran-server-manager/
├── routes.py           — Main routes (1133 lines)
├── system_service.py   — Compliance scan engine (1315 lines)
├── storage_routes.py   — Disk/partition routes (858 lines)
├── firewall_routes.py  — UFW management (622 lines)
├── stack_routes.py     — Docker stack monitoring (1369 lines)
├── helpers.py          — Shared utilities
├── host_monitor.py     — RUNS ON HOST (not in container) — command bridge
```

## host_command Bridge Pattern
KSO cannot exec on the host directly. Commands go through a queue:
```python
# In container: queue a command
INSERT INTO host_commands (command, status) VALUES ('ufw allow 443', 'pending')
# On host: host_monitor.py polls and executes pending commands
```
NEVER try to run host commands directly from Flask routes.

## Compliance Rule Packs
Same JSON format as Security Network module. Active packs:
- Network STIG: **100% compliant** (KB #255611)
- Ubuntu STIG, Docker STIG, HIPAA, CIS Ubuntu

## Auth (Standalone)
- Local: email + password
- SSO: `/auth/sso` → platform OAuth → `/auth/callback`
- Client ID in platform DB: `kso`
- Login: `kytran@kytranempowerment.com` (email+password)

## Deployment (rebuild required for code changes)
```bash
# Code changes require rebuild — COPY . in Dockerfile
docker compose up -d --build kytran-system-operations
# NOT: docker compose restart (won't pick up code changes)
```

## Integration with Platform
- `/external/kso` in platform proxies to KSO standalone
- KSO → platform alerts via `POST /api/internal/notify` with `X-Internal-Key`

## QA
No dedicated QA suite yet — create one at `/tools/repair-bay` → Test Bay
Code health (platform stub): ✅ completed, 0 red issues

## Common Tasks
- **Add a compliance check**: add rule to the relevant JSON rule pack
- **Debug host command not executing**: check `host_monitor.py` is running on host + DB `host_commands` table
- **Add a new tab**: add to tab nav in template + route in routes.py
- **Check compliance score**: GET `/api/compliance/summary` on KSO standalone
