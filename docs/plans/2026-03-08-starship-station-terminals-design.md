# Starship Station Terminals Design

**Date:** 2026-03-08
**Status:** Approved

---

## Goal

Replace Starship Command's simple station toggle grid with two full StationOps terminals (OPERATIONS + ENGINEERING) matching the Consciousness module's visual style. Show the node's local crew with mesh-loaned agents in auxiliary slots. No command buttons for now.

## Context

Consciousness module uses the reusable `StationOps` class (station-ops.js/css) to render LCARS terminals with crew roster, job progress, and commands. Starship currently has a basic toggle grid. Nodes should have proper station terminals that show their local crew working and mesh assists arriving.

## Design

### Station Terminals Layout

- Two terminals side-by-side (flexbox, wrap on mobile)
- OPERATIONS terminal (left) + ENGINEERING terminal (right)
- Teal accent (#00e5ff) matching Starship theme
- Each shows: crew roster (local agents), active jobs, no commands
- Reuses existing StationOps class — 2 instances with different config
- Replaces the current toggle grid; nodes always get OPERATIONS + ENGINEERING
- node_station_assignments pre-populated via migration

### Data Flow — Node's Local Crew

StationOps normally fetches from Bridge API (hub crew). For Starship, add a custom data URL:

New endpoint: `GET /api/nodes/<node_id>/stations-live`

Returns crew in StationOps-compatible format:
- Primary/secondary agents from node_agents filtered by station_codes
- Auxiliary slot from mesh_agent_loans (target_node = this node, status = active) — mesh-loaned agents show as "HELPING"
- Jobs from bridge_jobs for this node (empty for now)

StationOps enhancement: optional `dataUrl` config param. If set, fetches from custom URL instead of default Bridge API.

### Files Modified

| File | Change |
|------|--------|
| `platform_v2/static/js/station-ops.js` | Add optional `dataUrl` config param |
| `platform_v2/tools/starship/routes.py` | Add `GET /api/nodes/<node_id>/stations-live` endpoint |
| `platform_v2/tools/starship/templates/tools/starship/starship.html` | Replace Stations tab with 2 StationOps terminals, include CSS/JS |
| `database/migrations/142_starship_default_stations.sql` | Pre-populate OPERATIONS + ENGINEERING for approved starship nodes |

No new files. No new components. 1 migration.
