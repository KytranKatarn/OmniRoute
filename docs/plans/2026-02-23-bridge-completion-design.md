# Bridge Command Completion — Design Document

**Date**: 2026-02-23
**Goal**: Complete remaining Bridge Command work — dead endpoint cleanup, console optimizations, agent memory CRUD, and performance/leaderboard integration.

---

## Context

The Bridge Command module underwent a major redesign sprint (13 commits over ~10 days). The isometric 3D bridge, LCARS console with 4 tabs, IAAE governance layer, and real metrics are all deployed. Of the original 21-task unification plan, most tasks are done. Four items remain from the plan (sidebar cleanup, training/lounge buttons, module disable, network controls) but are already implemented in the codebase.

This document covers the **actual remaining work**: dead code cleanup, console enhancements, and porting agent memory + performance features from the retired Team Management module.

---

## Section 1: Dead Endpoint Cleanup

### Problem
Bridge routes.py contains ~870 lines of orphaned endpoints that are not referenced by any frontend template. These add confusion, bloat the file, and query tables that may not exist or be empty.

### Endpoints to Remove

| Group | Count | Route Prefix | Lines | Tables Queried |
|-------|-------|-------------|-------|----------------|
| Mining/Crypto | 8 | `/api/mining/*` | ~5098-5500 | mining-related tables |
| IDE/Development | 9 | `/api/ide/*`, `/execute` | ~5600-5978 | IDE session tables |
| Connections | 2 | `/api/connections*` | ~556-591 | `llm_connections` (stale since Jan 19) |
| Orphaned | 2 | `/api/modules`, `/api/dashboard/module-agents` | ~2735, ~7427 | Various |

### Change to push_agent_event()
Keep the in-memory `_activity_queue` deque (SSE endpoint reads from it). Remove only the fire-and-forget `INSERT INTO agent_activity_events` DB write (3 lines), since that table has no readers.

### Impact
- ~870 lines removed
- Zero UI impact (all endpoints are unreferenced in bridge.html)
- `agent_activity_events` table stops accumulating unreferenced rows

---

## Section 2: Console Enhancements

### 2A: SSE Dispatch (Replace Polling)

**Current**: Console dispatch tab polls `/api/stations/{code}/dispatch` every 15 seconds via `setInterval`.

**Proposed**: Replace with `EventSource` connected to the existing `/api/dispatch/stream` SSE endpoint. Events arrive in real-time (5s heartbeat). Filter client-side by station codes.

**Implementation**:
- In `loadConsoleDispatch()`: Create `new EventSource('/tools/bridge/api/dispatch/stream')`
- On `message` event: Parse JSON, filter by station codes, prepend to dispatch list
- On console close: `_consoleEventSource.close()` (same cleanup pattern as current `clearInterval`)
- Graceful fallback: If SSE connection fails, fall back to polling

### 2B: Ollama Caching Consolidation

**Current**: `_get_cached_ollama_tags()` exists with 30s TTL but only one call site uses it. Multiple other places call Ollama `/api/tags` and `/api/ps` directly without caching.

**Proposed**:
- Add `_get_cached_ollama_ps()` matching existing pattern (30s TTL)
- Route `get_ollama_models()` and `get_live_models()` through cached versions
- Route dashboard metrics `/api/ps` call through cached version

### 2C: Station Node Coverage

**Current**: `stationNodeCoverage` JS variable populated from `data.stations[].node_coverage` but backend doesn't return that field.

**Proposed**: In `/api/bridge/stations` endpoint, add a subquery or JOIN to count nodes per station:
```sql
-- Per station: count of nodes with models assigned to that station's modules
SELECT s.code, COUNT(DISTINCT rn.id) as total_nodes
FROM bridge_stations s
LEFT JOIN station_assignments sa ON sa.station_id = s.id
LEFT JOIN remote_nodes rn ON rn.status = 'online'
GROUP BY s.code
```
Return as `node_coverage: {total_nodes: N}` in each station object.

---

## Section 3: Agent Memory in LCARS Console

### Endpoints (Port from Team Management)

All endpoints under bridge blueprint, same auth (`@login_required`, admin check):

| Method | Route | Function |
|--------|-------|----------|
| GET | `/api/agents/<id>/memory` | List memories (paginated, filterable by type, searchable) |
| POST | `/api/agents/<id>/memory` | Create memory (with governance audit log) |
| GET | `/api/agents/<id>/memory/<mid>` | Get specific memory |
| PUT | `/api/agents/<id>/memory/<mid>` | Update memory (with audit log, captures old value) |
| DELETE | `/api/agents/<id>/memory/<mid>` | Soft delete (via `soft_delete_agent_memory()` DB function) |
| POST | `/api/agents/<id>/memory/<mid>/restore` | Restore soft-deleted memory (with audit log) |

### UI: MEMORY Tab in LCARS Console

Add 5th tab pill to the LCARS console: **MEM** (alongside CREW, DSPCH, NODES, STATS).

**Layout**:
- **Header**: Memory count + "Add Memory" button
- **Filter bar**: Type dropdown (general, skill, preference, interaction, all) + search input
- **Memory cards**: Sorted by importance DESC, showing:
  - Memory key (bold)
  - Memory value (truncated, expandable)
  - Type badge + importance bar (0-1 scale, color-coded)
  - Created/updated timestamps
  - Edit (pencil) and Delete (trash) icon buttons
- **Inline edit modal**: Memory key, value (textarea), type dropdown, importance slider
- **Soft-delete confirmation**: Shows reason input, marks as deleted (restorable)
- **Show deleted toggle**: Reveals soft-deleted memories with "Restore" button

### DB Tables
- `agent_memory` (CRUD) — already exists with proper indexes
- `governance_audit_log` (audit trail) — already exists

---

## Section 4: Performance + Leaderboard

### Endpoints (Port from Team Management)

Uses existing `ai_bridge/agent_performance_tracker.py` module:

| Method | Route | Function | Source |
|--------|-------|----------|--------|
| GET | `/api/agents/<id>/performance` | Get performance data | `get_agent_performance()` |
| POST | `/api/agents/<id>/performance/update` | Recalculate metrics | `update_agent_performance()` |
| GET | `/api/agents/performance/leaderboard` | Top performers (limit param) | `get_top_performers()` |
| GET | `/api/agents/<id>/work-history` | Proposals + discussions + stats | Direct SQL queries |

### UI: Performance in Agent Profile

When clicking an agent in the CREW tab, the existing agent profile card gains a **Performance section**:
- Tasks completed (24h / all-time)
- Success rate percentage
- Avg response duration
- Quality/accuracy scores (if available)
- Recent work history (last 10 proposals/discussions)

### UI: Leaderboard Sub-Tab in Crew

Add 5th sub-tab to Crew: **Leaderboard** (alongside Manifest / Training / Lounge / Contractors).

**Layout**:
- Ranked list of agents by performance score
- Each row: Rank badge (#1 gold, #2 silver, #3 bronze), agent name, tasks completed, success rate, avg duration
- Top 10 by default, expandable
- "Refresh Metrics" button triggers recalculation for all agents

---

## File Changes Summary

| File | Changes |
|------|---------|
| `platform_v2/tools/bridge/routes.py` | Remove ~870 lines (dead endpoints), add ~250 lines (memory CRUD, performance, caching), modify ~30 lines (SSE wiring, node coverage) |
| `platform_v2/templates/tools/bridge.html` | Add MEMORY tab HTML + JS (~200 lines), add leaderboard sub-tab (~100 lines), modify console dispatch JS (~30 lines for SSE), add performance to profile (~50 lines) |

**Total**: ~870 lines removed, ~660 lines added. Net reduction of ~210 lines.
