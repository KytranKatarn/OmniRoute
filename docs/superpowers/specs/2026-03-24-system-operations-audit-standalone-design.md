# System Operations — Audit, Refactor & Standalone Product

**Date:** 2026-03-24
**Status:** Approved
**Author:** Claude + Kyt

---

## 1. Overview

Three deliverables from one codebase:

1. **Audit + Refactor** — Fix the monolithic System Ops module to pass code health green. ADR-045 route split, template CSS/JS extraction, security review on all sensitive endpoints.
2. **Kytran Server Manager** — Standalone open-source product (`kytran-server-manager`) distributed via PyPI + Docker (`ghcr.io/kytrankatarn/kytran-server-manager`). Config-driven theming with LCARS available as a premium theme.
3. **Starship Integration** — Node health panels in Starship (per-node CPU/RAM/disk/Docker view) + host selector in System Ops for deep-dive into any machine.

## 2. Decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Standalone identity | Generic server manager, not A.R.C.H.I.E. branded |
| 2 | Internal branding | Keep LCARS sci-fi aesthetic |
| 3 | External branding | Kytran Empowerment |
| 4 | Standalone scope | All 7 domains: dashboard, hardware, storage, docker+stacks, processes+services, network, firewall |
| 5 | Security Network integration | Clean boundary — firewall+network stays in System Ops, Security Network keeps DNS/scanning/recon/surveillance |
| 6 | Starship integration | Node health panels in Starship + host selector dropdown in System Ops |
| 7 | Refactor scope | Full ADR-045 route split + template extraction |
| 8 | Theming | Config-driven `theme.json` — LCARS and Kytran themes |
| 9 | Distribution | PyPI (`pip install kytran-server-manager`) + Docker image on ghcr.io |
| 10 | Product name | `kytran-server-manager` |

## 3. Architecture

```
Internal (A.R.C.H.I.E.)              Standalone (Kytran Server Manager)
+------------------------+            +------------------------+
|  LCARS Theme            |            |  Kytran Theme           |
|  base.html extends      |            |  standalone base.html   |
|  A.R.C.H.I.E. nav      |            |  own nav + auth         |
+------------------------+            +------------------------+
|                                                               |
|              Shared Engine (kytran-server-manager)              |
|  +-------------+----------------+-------------------+          |
|  | core_routes  | docker_routes  | storage_routes    |          |
|  | network_rts  | firewall_rts   | health_routes     |          |
|  | stack_routes | host_cmd_rts   |                   |          |
|  +-------------+----------------+-------------------+          |
|  |            system_service.py                      |          |
|  |            host_command_client.py                 |          |
|  +--------------------------------------------------+          |
|  |            theme.json (config-driven)             |          |
|  +--------------------------------------------------+          |
+---------------------------------------------------------------+
```

### Integration Points

- **A.R.C.H.I.E. platform** imports the engine as a Blueprint, wraps with its own auth (`@admin_required`) and base template
- **Standalone** runs its own Flask app with built-in auth and standalone base template
- **Starship** fetches node health data via the same API endpoints running on remote nodes

### Code Sharing Strategy

The route files and service layer are **the same Python files** used in both contexts. The `kytran-server-manager` PyPI package contains the canonical source. The A.R.C.H.I.E. platform installs it as a pip dependency (`pip install kytran-server-manager`) and registers the Blueprint with its own auth wrappers.

```
A.R.C.H.I.E. platform (consumer):
  platform_v2/tools/system_operations/__init__.py
    → imports from kytran_server_manager.routes
    → wraps with platform @admin_required + @login_required
    → registers under /tools/system-operations

Standalone (self-contained):
  kytran_server_manager/app.py
    → imports from kytran_server_manager.routes
    → wraps with its own @auth_required
    → registers under /

Development workflow:
  1. Edit code in kytran-server-manager/ (canonical source)
  2. pip install -e kytran-server-manager/ (editable install)
  3. Both platform and standalone pick up changes
```

No symlinks, no copying, no drift. One source of truth.

## 4. Route Split (ADR-045)

Current `routes.py` (5,194 lines) splits into:

| File | Endpoints | ~Lines | Description |
|------|-----------|--------|-------------|
| `routes.py` | Index, overview, CPU, memory, hardware, history, audit, auth verify, health check, host command submit/status/result | ~1000 | Core monitoring + dashboard + host commands |
| `docker_routes.py` | Containers, actions, logs, health, compose editor, env editor | ~500 | Container lifecycle |
| `stack_routes.py` | List/create/delete/action stacks, compose/env per stack, stack logs, stack status | ~900 | Multi-stack orchestration |
| `storage_routes.py` | Disks, mounts, LVM extend, filesystem resize, LVM info, drives, preflight, browse, docker mounts, register mount | ~700 | Disk + LVM + file browser |
| `network_routes.py` | Interfaces, port map, bandwidth, port usage | ~400 | Network monitoring |
| `firewall_routes.py` | UFW status, rules, enable, disable, allow, deny, update, delete | ~600 | Full UFW management |
| `health_routes.py` | Alerts CRUD, health config, webhooks CRUD, system health full | ~400 | Alerting + webhooks |
| `process_routes.py` | Process list, kill process, services list, service action | ~300 | Process + systemd management |

`__init__.py` updated to `register_*_routes(bp, admin_required)` pattern matching Starbase/Consciousness.

### Shared Helpers → `helpers.py`

Module-specific helpers move to `helpers.py`:
- `load_host_monitor_data()` — reads host monitor JSON
- `audit_log()` — audit trail logging (module-level, wraps platform audit)
- `record_metric()` — metric recording
- `require_reauth()` — re-authentication check
- `parse_compose_host_port()` — port parsing
- `find_compose_file()` — compose file discovery

**Platform-wide utilities stay where they are:**
- `admin_required()` → platform uses `rbac.py`, standalone uses its own `auth.py`
- `get_db()` → platform uses `database.py`, standalone uses its own `db.py` (SQLite for audit/alerts/webhooks)

## 5. Template Extraction

14,087-line template splits into:

| File | Content | ~Lines |
|------|---------|--------|
| `templates/tools/system_operations.html` | Pure HTML structure | ~3,000 |
| `static/css/system-operations.css` | All extracted CSS | ~2,500 |
| `static/js/system-operations.js` | All extracted JS | ~8,500 |

CSS class prefix: `sysops-` (already partially in use).

## 6. Theme System

### theme.json Schema

```json
{
  "product_name": "Kytran Server Manager",
  "product_short": "KSM",
  "logo": "/static/img/kytran-logo.svg",
  "favicon": "/static/img/kytran-favicon.ico",
  "frame_style": "modern",
  "colors": {
    "accent": "#2563eb",
    "accent_bright": "#3b82f6",
    "accent_rgb": "37, 99, 235",
    "danger": "#ef4444",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "bg_void": "#0f172a",
    "bg_primary": "#1e293b",
    "bg_secondary": "#334155",
    "bg_tertiary": "#475569",
    "text_primary": "#f8fafc",
    "text_secondary": "#cbd5e1",
    "text_muted": "#94a3b8",
    "border_default": "#334155"
  },
  "fonts": {
    "heading": "Inter",
    "body": "Inter",
    "mono": "JetBrains Mono"
  },
  "layout": {
    "border_radius": "8px",
    "nav_position": "top",
    "sidebar_width": "240px"
  },
  "custom_css": null
}
```

**Fallback behavior:** Missing keys in a theme file fall back to the default Kytran theme values. Themes are merged, not replaced — only override what you need.

### LCARS Override (internal)

```json
{
  "product_name": "System Operations",
  "product_short": "SYSOPS",
  "logo": "/static/img/archie-logo.svg",
  "frame_style": "lcars",
  "colors": {
    "accent": "#00e5ff",
    "accent_bright": "#4df0ff",
    "accent_rgb": "0, 229, 255",
    "danger": "#ef4444",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "bg_void": "#000000",
    "bg_primary": "#0a0a1a",
    "bg_secondary": "#1a1a2e",
    "bg_tertiary": "#2a2a3e",
    "text_primary": "#e0e0e0",
    "text_secondary": "#b0b0b0",
    "text_muted": "#808080",
    "border_default": "#2a2a3e"
  },
  "fonts": {
    "heading": "Orbitron",
    "body": "IBM Plex Mono",
    "mono": "IBM Plex Mono"
  },
  "layout": {
    "border_radius": "20px",
    "nav_position": "top",
    "sidebar_width": "240px"
  },
  "custom_css": "/static/css/lcars-frames.css"
}
```

### Implementation

- Template reads `theme` object from Flask context (injected via `@app.context_processor`)
- CSS variables generated from theme.json at startup, served via `/static/css/theme-vars.css`
- `frame_style` controls whether LCARS frames or modern card frames render
- Jinja2 conditionals: `{% if theme.frame_style == 'lcars' %}` for frame-specific markup
- `custom_css` allows injecting an additional stylesheet (LCARS frames, etc.)
- Theme merging: `default_theme.update(override_theme)` — partial overrides are valid

## 7. Standalone Package Structure

```
kytran-server-manager/
├── kytran_server_manager/
│   ├── __init__.py              # Package init, version
│   ├── app.py                   # Standalone Flask app (own auth, own nav)
│   ├── config.py                # Settings, host config, theme loading
│   ├── auth.py                  # Simple auth (local users, API keys)
│   ├── routes/
│   │   ├── __init__.py          # register_*_routes pattern
│   │   ├── core_routes.py       # Dashboard, overview, CPU, memory, hardware
│   │   ├── docker_routes.py     # Container lifecycle
│   │   ├── stack_routes.py      # Multi-stack orchestration
│   │   ├── storage_routes.py    # Disk, LVM, file browser
│   │   ├── network_routes.py    # Interfaces, ports, bandwidth
│   │   ├── firewall_routes.py   # UFW management
│   │   ├── health_routes.py     # Alerts, webhooks
│   │   └── process_routes.py    # Process + systemd management
│   ├── services/
│   │   ├── system_service.py    # Core system data collection
│   │   └── host_command_client.py
│   ├── templates/
│   │   ├── base.html            # Standalone base (no A.R.C.H.I.E. nav)
│   │   └── dashboard.html       # Main dashboard
│   ├── static/
│   │   ├── css/
│   │   │   ├── system-operations.css
│   │   │   └── theme-vars.css   # Generated from theme.json
│   │   ├── js/
│   │   │   └── system-operations.js
│   │   └── img/
│   │       └── kytran-logo.svg
│   └── themes/
│       ├── kytran.json          # Default clean professional theme
│       └── lcars.json           # Premium sci-fi theme
├── host_monitor/
│   └── host_monitor.py          # Host-side daemon (runs as root)
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── README.md
└── LICENSE                      # Apache 2.0
```

### Standalone Auth

`auth.py` provides two auth modes:

1. **Local users** — stored in SQLite (`~/.kytran-server-manager/data.db`). Bcrypt-hashed passwords. First-run setup wizard creates admin account. Session-based with Flask-Login.
2. **API keys** — stored in same SQLite DB. Scoped: `read-only` (monitoring) or `admin` (full access). Passed via `X-API-Key` header. Used by Starship node health polling and automation.

No external auth dependencies. Self-contained.

### Standalone Storage

The standalone product uses SQLite (`~/.kytran-server-manager/data.db`) for:
- User accounts and API keys
- Audit log entries
- Health alert history
- Webhook configurations
- Health check thresholds

No PostgreSQL dependency. The A.R.C.H.I.E. platform version uses its own PostgreSQL tables instead — the route files accept a `db_adapter` interface that abstracts this.

### Distribution

| Channel | Command |
|---------|---------|
| PyPI | `pip install kytran-server-manager` |
| Docker | `docker pull ghcr.io/kytrankatarn/kytran-server-manager:latest` |
| Docker run | `docker run -d -p 8080:8080 -v /var/run/docker.sock:/var/run/docker.sock ghcr.io/kytrankatarn/kytran-server-manager` |

## 8. Starship Integration

### Node Health Panel

When clicking a node in Starship, a panel shows:
- CPU usage (gauge)
- RAM usage (gauge)
- Disk usage (top 3 mounts)
- Docker containers (running/stopped count)
- Last heartbeat timestamp

**Data flow:**
1. Node agent runs `kytran-server-manager` in agent mode (lightweight, read-only subset)
2. Node exposes `/api/overview` endpoint
3. Starship fetches via existing node communication (heartbeat already sends basic hw info)
4. Enhanced heartbeat payload includes System Ops overview data

### System Ops Host Selector

- Dropdown in System Ops header, populated from `remote_nodes` table
- Default: hub (192.168.1.200)
- Selecting a node: all API calls proxy through hub to `http://{node_ip}:{agent_port}/api/*`
- Proxy endpoint: `/tools/system-operations/api/proxy/<node_id>/<path:endpoint>`

**Proxy Security:**
- **Auth signing:** HMAC-SHA256 using a shared secret stored in `remote_nodes.auth_token`. Hub signs `timestamp + node_id + endpoint` and sends as `X-Hub-Signature` header. Node verifies signature and rejects if >60s stale.
- **Endpoint allowlist:** Proxy only forwards to a hardcoded set of read-only endpoints: `overview`, `cpu`, `memory`, `disks`, `docker`, `network`, `processes`, `services`. Write operations (kill, firewall, LVM, compose) are NOT proxied — they require direct node access or explicit per-node admin auth.
- **Response limits:** Proxy enforces 5MB max response size, 30s timeout.
- **Rate limiting:** 60 requests/minute per node per session to prevent abuse.
- **No path traversal:** `endpoint` parameter validated against allowlist, not passed as raw path.

## 9. Security Audit Checklist

| # | Area | Check | Risk |
|---|------|-------|------|
| 1 | Auth on all endpoints | Every endpoint has `@admin_required` + `@login_required` | High |
| 2 | Process kill | Validate PID is integer, reject system PIDs (1, 2, init) | High |
| 3 | Firewall rules | Validate port ranges (1-65535), IP format, protocol enum | High |
| 4 | Compose editor | Path traversal protection — jail to allowed compose directories | Critical |
| 5 | Env editor | Path traversal protection, never expose full secrets in GET responses | Critical |
| 6 | File browser | Jail to allowed directories, reject `../` traversal | Critical |
| 7 | LVM operations | Validate VG/LV names against `[a-zA-Z0-9_-]` regex, prevent shell injection | Critical |
| 8 | Host commands | Verify whitelist enforcement in host_monitor.py | High |
| 9 | Stack names | Validate against `[a-zA-Z0-9_-]` regex, prevent directory traversal | High |
| 10 | Docker actions | Validate action enum (start/stop/restart/remove), container ID format | Medium |
| 11 | Service actions | Validate action enum (start/stop/restart/enable/disable), service name format | Medium |
| 12 | Network data | No write operations exposed (read-only monitoring) — verify | Low |
| 13 | Bandwidth data | Rate limit to prevent DoS from polling | Low |
| 14 | Re-auth for destructive ops | `require_reauth()` on kill, LVM extend, firewall changes, stack delete | High |
| 15 | Node proxy | Endpoint allowlist (read-only only), HMAC-SHA256 signing, 5MB response limit, 30s timeout, 60req/min rate limit | Critical |
| 16 | Host command whitelist | Whitelist defined in `host_monitor.py` config: `lvm_extend`, `filesystem_resize`, `mount`, `unmount`, `ufw_*`. Standalone ships with same whitelist in `host_monitor/config.json`. Users can add custom commands but must explicitly opt-in. | High |
| 17 | Docker socket exposure | Standalone Docker image mounts `/var/run/docker.sock` — document container escape risk. Recommend running with `--read-only` flag and dropping capabilities where possible. | Medium |

## 10. Firewall Boundary Cleanup

| Feature | System Ops (owns) | Security Network (owns) |
|---------|-------------------|------------------------|
| UFW rules CRUD | Yes | No — remove `get_firewall_status` import |
| Network interfaces | Yes | No |
| Port mapping | Yes | No |
| Bandwidth monitoring | Yes | No |
| Port scanning (Nmap) | No | Yes |
| Vulnerability scanning (Nikto/Nuclei/ZAP) | No | Yes |
| DNS management (AdGuard) | No | Yes |
| Recon/surveillance | No | Yes |
| SSL scanning | No | Yes |
| Security reports | No | Yes |

Security Network's existing redirect to System Ops stack status (`/tools/system-operations/api/stacks/status`) remains — that's a clean cross-module API call, not duplication.

## 11. Code Health Targets

| Metric | Current | Target | Green Threshold |
|--------|---------|--------|-----------------|
| Route file max lines | 5,194 | < 900 | < 1,000 |
| Template max lines | 14,087 | < 3,500 | < 4,000 |
| Inline CSS lines | ~2,500 | 0 | 0 |
| Inline JS lines | ~8,500 | 0 | 0 |
| Static CSS extracted | No | Yes | Required |
| Static JS extracted | No | Yes | Required |
| ADR-045 route split | No | Yes (8 files: core + 7 domain) | Required |
| Health check endpoint | Yes | Yes | Required |
| Service layer | Yes (1,314 lines) | Yes (unchanged) | < 1,500 |

## 12. Implementation Phases

### Phase 1: Audit + Security Review
- Deep code audit of all 75 endpoints
- Verify auth decorators on every route
- Input validation on all destructive operations
- Path traversal checks on file/compose/env operations
- Document all findings

### Phase 2: Route Split (ADR-045)
- Create `helpers.py` for shared functions
- Split `routes.py` into 8 route files
- Update `__init__.py` with `register_*_routes` pattern
- Verify all endpoints still work (browser test)

### Phase 3: Template Extraction
- Extract CSS to `static/css/system-operations.css`
- Extract JS to `static/js/system-operations.js`
- Update template to reference external files
- Browser test all 7 tabs

### Phase 4: Theme System
- Create `theme.json` schema and loader
- Implement `theme-vars.css` generation
- Add `frame_style` conditional rendering
- Create Kytran theme + LCARS theme
- Context processor for template access

### Phase 5: Standalone Package
- Create `kytran-server-manager/` package structure
- Extract shared engine from platform module
- Build standalone Flask app with own auth
- Create Dockerfile + docker-compose.yml
- PyPI packaging (pyproject.toml)
- GitHub Actions for CI + Docker build

### Phase 6: Starship Integration
- Enhance node heartbeat with system overview data
- Build node health panel component in Starship
- Add host selector dropdown to System Ops
- Implement proxy endpoint for node API calls
- **Security review of proxy endpoint** — verify HMAC signing, endpoint allowlist, response limits, rate limiting before merge

### Phase 7: Firewall Boundary Cleanup
- Remove `get_firewall_status` import from Security Network
- Verify Security Network still functions independently
- Update module documentation

### Phase 8: Code Health Verification
- Run code health scanner
- Verify all metrics green
- Browser test all tabs on all themes
- Final commit + deploy
