# Starship Command Refactor — Design Spec

**Date:** 2026-03-12
**Status:** Approved
**Approach:** B — Full Route Cleanup

## Context

Starship Command is the fleet node management module for A.R.C.H.I.E. It currently has 26 endpoints and 6 tabs, several of which duplicate data available in Bridge Command and System Operations. The module also has 6 bugs including a broken install endpoint, column reference errors, and missing ownership checks.

ARCHIE (192.168.1.200) is the Starbase/hub, not a node. It should be presented as the command center, with fleet nodes listed below it.

## Landing Page

### Starbase Card (Top)
- Header: "A.R.C.H.I.E. STARBASE" with online status badge
- Live stats pulled from existing APIs (not new endpoints):
  - Agent count + active jobs (Bridge crew manifest / dispatcher)
  - Model count + loaded count (Ollama `/api/tags` + `/api/ps` via hub)
  - Hardware summary: CPU, RAM, GPU (Bridge `_get_cached_hw_capacity()`)
  - Station count (10 stations)
- Not clickable — the hub is not a manageable node
- Auto-refreshes on interval

### Fleet Nodes (Bottom)
- Cards for each remote node from `remote_nodes` table
- Each card: name, status badge (online/offline), hardware summary, agent count, last heartbeat
- Click → opens detail panel with 3 tabs
- "+Add Node" button in top-right → onboarding modal

## Node Detail — 3 Tabs

### STATUS Tab (kept, enhanced)
- Node health: heartbeat status, uptime, latency
- Hardware gauges: CPU, RAM, GPU usage (from heartbeat data)
- Version info: current version, OTA update available badge
- Deployment mode + priority (inline editable — replaces Profile tab)
- Fleet summary: active stations count, agent count, model count

### OTA / SYNC Tab (new, consolidates existing functionality)
- Push Update button — triggers OTA `code_update` sync
- Pull Model control — select from model catalog, push `model_pull` sync
- Push Agent Config button — resync crew manifest via `agent_config` sync
- Sync log table — recent `mesh_sync_log` entries (type, status, timestamp)
- Sync status indicators (last sync time, pending count)

### CREW Tab (slimmed from AGENTS)
- Read-only agent cards: name, model, station, status
- Job stats per agent: total jobs, success rate, last active
- No edit forms, no add/remove UI
- Recommendation section: "Suggested crew for this node" with scoring rationale

## Deleted Tabs
- **STATIONS** — Bridge Command handles station management
- **MODELS** — Merged into OTA/SYNC (pull model) and STATUS (model count)
- **PRIVACY** — Removed entirely (revisit when multi-tenant is a real need)
- **PROFILE** — Node name/priority moved to inline fields on STATUS tab

## Route Cleanup

### Routes to Delete (~400 lines)

| Route | Purpose | Reason |
|-------|---------|--------|
| `POST /api/nodes/<node_id>/profile` | Update node name/priority/mode | Replaced by `PUT /api/nodes/<node_id>/settings` (see kept routes) |
| `GET/POST /api/nodes/<node_id>/privacy` (lines 643 AND 671) | Privacy settings CRUD (two overlapping routes) | Privacy tab removed — both routes deleted |
| `POST /api/nodes/<node_id>/agent-access` | Toggle agent dispatch access | Part of privacy controls, removed |
| `POST /api/nodes/<node_id>/station-toggle` | Enable/disable station on node | Stations tab removed |
| `GET /api/nodes/<node_id>/stations-live` | Live crew roster per station | Stations tab removed |

### Routes to Keep
- `GET /` — Dashboard (landing page)
- `GET /api/nodes` — List all nodes (fleet cards)
- `GET /api/nodes/<node_id>/status` — Full node detail (STATUS tab)
- `GET /api/nodes/<node_id>/crew-manifest` — Agent list (CREW tab)
- `GET /api/nodes/<node_id>/agents/<agent_id>/profile` — Agent detail (CREW tab click)
- `GET /api/nodes/<node_id>/recommendations` — Crew suggestions (CREW tab)
- `GET /api/nodes/<node_id>/agent-form-context` — Dropdown data (kept for future use)
- `PUT /api/nodes/<node_id>/agents/<agent_id>` — Update agent (kept, add ownership check)
- `POST /api/nodes/<node_id>/agents/add` — Clone agent (kept)
- `DELETE /api/nodes/<node_id>/agents/<agent_id>` — Remove agent (kept)
- `POST /api/nodes/<node_id>/push-config` — OTA agent sync (OTA/SYNC tab)
- `POST /api/nodes/<node_id>/pull-model` — OTA model pull (OTA/SYNC tab)
- `POST /api/nodes/<node_id>/push-update` — OTA code update (OTA/SYNC tab)
- `GET /api/nodes/<node_id>/sync-log` — Sync history (OTA/SYNC tab)
- `GET /api/nodes/<node_id>/sync-status` — Sync state (OTA/SYNC tab)
- `POST /api/request-node` — Pre-register node (Add Node flow)
- `GET /api/setup-instructions/<node_id>` — Config JSON (Add Node flow)
- `GET /download/node-package` — Docker tar.gz download
- `POST /api/nodes/<node_id>/request-update` — Flag node for update
- `GET /api/model-catalog` — Model catalog (OTA/SYNC pull model dropdown)
- `PUT /api/nodes/<node_id>/settings` — **NEW** inline edit node name, deployment mode, priority (replaces deleted POST /profile)
- `GET /install` — **NEW** token-based install script endpoint

### Estimated Result
- routes.py: ~2,071 → ~1,600 lines

## New Endpoint: `/starship/install`

```
GET /starship/install?token=<setup_token>
```

- No login required — token authenticates the request
- Validates token against `remote_nodes.setup_token`
- Detects OS from User-Agent header:
  - PowerShell request → returns `deploy-node.ps1` with credentials injected (NODE_ID, HUB_URL, HUB_API_KEY)
  - Bash/curl request → returns `install.sh` with credentials injected
- Invalid/expired token → returns plain text error message (not HTML)
- Token is single-use or time-limited

## Bug Fixes

### Bug 1: Missing install endpoint
- Create `GET /starship/install?token=` as described above

### Bug 2: Hub URL default
- Keep `https://archie.kytranempowerment.com` as default (domain works on LAN with valid Let's Encrypt cert via Nginx Proxy Manager)
- Read from `STARSHIP_HUB_URL` env var for override
- Future: Cloudflare Tunnel will make this work externally

### Bug 3: `user_id` column in bridge/routes.py
- `get_starship_node_for_user()` at ~line 370 references nonexistent `user_id` column
- Change to `registered_by` (same fix already applied in starship/routes.py)

### Bug 4: `registered_by IS NULL` privacy hole
- Nodes with `registered_by IS NULL` visible to all authenticated users
- Fix: On first access, atomically claim the orphan node:
  ```sql
  UPDATE remote_nodes SET registered_by = %s
  WHERE node_id = %s AND registered_by IS NULL
  ```
- Check affected row count — if 0, another user already claimed it
- After claim, standard ownership check applies

### Bug 5: Agent update missing ownership check
- `api_update_node_agent()` doesn't verify node ownership
- Add `_get_node_for_user()` call at start of all write endpoints:
  - `PUT /api/nodes/<node_id>/agents/<agent_id>`
  - `DELETE /api/nodes/<node_id>/agents/<agent_id>`
  - `POST /api/nodes/<node_id>/agents/add`
  - `POST /api/nodes/<node_id>/push-config`
  - `POST /api/nodes/<node_id>/pull-model`
  - `POST /api/nodes/<node_id>/push-update`

### Bug 6: NULL model catalog descriptions
- Add `COALESCE(description, '')` in catalog query
- Frontend already handles empty strings

## Out of Scope
- Cloudflare Tunnel setup (separate task — needed for external node connectivity)
- Multi-tenant privacy controls (revisit when external users exist)
- Route file splitting (only if module grows significantly)
- New DB tables or migrations (all data already exists)
