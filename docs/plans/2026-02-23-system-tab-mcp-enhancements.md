# System Tab & MCP Enhancements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enhance Dev HQ System tab with MCP tool usage analytics, health check history, quick admin actions, tool auto-registration, health probes, and routing hints.

**Architecture:** Six features added to existing Dev HQ module. Backend endpoints in `routes.py`, one new DB migration for health history, startup sync logic in `app.py`, and frontend rendering in `devhq.js`. All features build on existing `mcp_tool_definitions`, `mcp_tool_usage`, and `v_mcp_tool_usage_summary` infrastructure.

**Tech Stack:** Flask/psycopg2 backend, vanilla JS frontend, PostgreSQL, APScheduler for periodic health probes.

**Security note:** Frontend rendering uses innerHTML for system-generated data only (health status, tool stats from own API). DOMPurify is already vendored in the project for any user-supplied content.

---

## Context

### Current State
- System tab has 3 collapsible sections: Integrations, Schema, API Docs
- Integrations shows: health cards, MCP servers panel, MCP tool registry, Claude config
- `mcp_tool_usage` table exists but has a query bug (`executed_at` should be `created_at`)
- `v_mcp_tool_usage_summary` view exists but is not used in the UI
- `.mcp.json` defines 2 servers (archie: 78 tools, design-systems: 5 tools) but `mcp_tool_definitions` only has 12 rows
- Health checks are point-in-time snapshots with no history

### Key Files
- **Backend**: `/mnt/archie_brain/platform_v2/tools/dev_hq/routes.py` (routes, lines 703-793 for MCP, 1108-1184 for health)
- **Frontend JS**: `/mnt/archie_brain/platform_v2/static/js/devhq.js` (lines 1304-1430 for System tab)
- **Template**: `/mnt/archie_brain/platform_v2/templates/dev_hq.html` (lines 1216-1290 for System panel)
- **Migration dir**: `/mnt/archie_brain/database/migrations/`
- **MCP config**: `/mnt/archie_brain/.mcp.json`
- **App startup**: `/mnt/archie_brain/platform_v2/app.py`
- **MCP schema**: `/mnt/archie_brain/database/migrations/050_mcp_server.sql`

### Existing Bug
- `routes.py` line ~734: `MAX(executed_at)` should be `MAX(created_at)` (column doesn't exist in mcp_tool_usage table)

---

## Task 1: DB Migration — Health History Table

**Files:**
- Create: `database/migrations/120_service_health_history.sql`

Create table, run migration, verify, commit.

---

## Task 2: Backend — Fix Bug + New Endpoints

**Files:**
- Modify: `platform_v2/tools/dev_hq/routes.py`

1. Fix `executed_at` to `created_at` in MCP usage query
2. Add `GET /api/integrations/mcp/usage` — tool stats from v_mcp_tool_usage_summary, daily volume, errors
3. Add `GET /api/integrations/health/history` — 24h health check data grouped by service
4. Add `POST /api/integrations/health/check` — manual health check trigger
5. Add `POST /api/system/actions/clear-cache` — clear old bridge conversations
6. Add `POST /api/system/actions/warmup` — trigger Ollama model warmup
7. Add `POST /api/system/actions/reindex-embeddings` — report missing embeddings count
8. Add `POST /api/system/actions/sync-mcp-tools` — sync registry from .mcp.json
9. Add `PUT /api/integrations/mcp/tools/<id>/hints` — update routing hints metadata
10. Add `_run_and_store_health_check()` internal function for scheduler + manual use
11. Add `sync_mcp_tool_registry()` function for startup + manual use
12. Include `id` and `tags` in existing MCP tool definitions SELECT

---

## Task 3: Startup Integration

**Files:**
- Modify: `platform_v2/app.py`

1. Import and call `sync_mcp_tool_registry()` on startup
2. Import and call `_run_and_store_health_check()` on startup
3. Add APScheduler job `health_probe` running every 15 minutes

---

## Task 4: Frontend — System Tab UI Enhancements

**Files:**
- Modify: `platform_v2/templates/dev_hq.html`
- Modify: `platform_v2/static/js/devhq.js`

### HTML additions:
1. Health history sparkline row (`#healthHistoryRow`, `#healthSparklines`)
2. MCP usage analytics panel (`#mcpUsagePanel`)
3. Quick actions card with 5 buttons (`#systemQuickActions`, `#quickActionsGrid`)

### JS additions:
1. `loadHealthHistory()` — fetch 24h data, render status bar sparklines per service
2. `loadMcpUsage()` — fetch tool stats, render ranked bar chart with error rates
3. `runQuickAction(action)` — POST to action endpoints, show result feedback

---

## Task 5: Integration Testing

**Files:**
- Create: `platform_v2/tests/test-system-enhancements.mjs`

Playwright tests: health sparklines visible, usage panel visible, quick actions work, API endpoints return 200.

---

## Task 6: Visual QA + Push

Take System tab screenshots at 374/717/1280px, fix responsive issues, push, update Dev HQ tracking.

---

## Feature Summary

| Feature | Backend Endpoint | Frontend Element |
|---------|-----------------|-----------------|
| Bug fix (executed_at) | `/api/integrations/mcp` | — |
| Usage Analytics | `GET /api/integrations/mcp/usage` | `#mcpUsagePanel` |
| Health History | `GET /api/integrations/health/history` | `#healthSparklines` |
| Health Probes | APScheduler (15 min) + `POST /health/check` | — |
| Quick Actions | `POST /api/system/actions/{action}` | `#quickActionsGrid` |
| Tool Auto-Reg | Startup sync + `POST /sync-mcp-tools` | Sync button |
| Routing Hints | `PUT /api/mcp/tools/<id>/hints` | Tags in tool registry |

**New table**: `service_health_history` (migration 120)
**New scheduler job**: `health_probe` (every 15 minutes)
**New startup task**: `sync_mcp_tool_registry()` + initial health check
