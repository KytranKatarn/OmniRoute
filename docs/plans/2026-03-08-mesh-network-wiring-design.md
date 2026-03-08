# Bridge Network Tab — Mesh Wiring + Agent Lending Design

**Date:** 2026-03-08
**Project:** Bridge Command — Network Tab Mesh Integration
**Status:** Approved

---

## Goal

Wire up the Bridge Network tab's existing mesh accordion panels (Agent Mesh Pool, Learning Patterns) to their backend APIs, add mesh summary stats to the header, and implement a "Request Help" flow that lets admins borrow idle agents from other nodes.

## Context

The Bridge Network tab manages the fleet of connected nodes. The backend APIs and DB tables for mesh operations (agent loans, learning patterns, cluster overview) are fully implemented but the frontend JS to fetch and render that data was never wired up. Starship Command lets users register personal nodes with cloned crews and privacy controls. The mesh layer enables cross-node cooperation — agents can be loaned between nodes when idle.

## Architecture Decisions

- **Privacy-first agent lending:** LLM inference by default, full station tasks only if node operator opts in via `privacy_settings`
- **Demand-driven loans:** Admin notices an overloaded node → clicks "Request Help" → picks from available idle agents across the mesh
- **Display in existing accordions:** No structural changes to the Network tab — mesh loans and learning patterns render inside the existing collapsible panels
- **Approach B (Smart Wiring):** One new endpoint for agent-level availability, rest uses existing APIs

## Backend

### New Endpoint: `GET /api/mesh/available-agents`

Joins `node_agents` + `remote_nodes` to find lendable agents:
- Node: `approved`, `online`, `bridge_enabled = true`
- Node capacity: `current_load < max_concurrent`
- Agent: `is_allowed = true`, `status = 'active'`
- Excludes agents in active `mesh_agent_loans`
- Excludes nodes with `privacy_settings->>'local_data_only' = 'true'`

Response:
```json
{
  "available_agents": [
    {
      "agent_id": 5,
      "node_agent_id": 12,
      "display_name": "Kai Tanaka",
      "title": "Security Analyst",
      "model": "qwen2.5:7b",
      "capabilities": ["code_review", "security"],
      "station_codes": ["SECURITY", "ENGINEERING"],
      "source_node_id": "starship_abc123",
      "source_node_name": "Kai's Workstation",
      "node_load": 1,
      "node_capacity": 4,
      "privacy_level": "full"
    }
  ],
  "summary": {
    "total_available": 8,
    "nodes_with_capacity": 3,
    "active_loans": 2
  }
}
```

### Existing Endpoints Used (no changes)

- `GET /api/mesh/agents/loans` — active + recent loans
- `GET /api/mesh/learning` — learning patterns feed
- `POST /api/mesh/agents/lend` — initiate a loan
- `POST /api/mesh/agents/return` — return a borrowed agent

## Frontend — Network Tab

### Mesh Summary Stats (Header Bar)

Three new stat badges next to online/offline/pending counts:
- `Mesh Loans: X` (active)
- `Available: Y` (lendable agents)
- `Learnings: Z` (total patterns)

### Agent Mesh Pool Accordion

- Header: `Active Loans: X | Available Agents: Y`
- Body: loans table — Agent, Source Node → Target Node, Status, Duration, Actions
- Active loans show "Return" button
- Empty state message when no loans

### Learning Patterns Accordion

- Header: `Patterns: X`
- Body: feed of pattern cards with type badge (color-coded), category, insight, metric, timestamp
- Empty state message when no patterns

### Request Help Button

- Added to each approved node card (next to TEST / DETAIL / REMOVE)
- Only shown when `current_load > 0`

### Request Help Modal

1. Shows target node's current load/capacity and active stations
2. Fetches `/api/mesh/available-agents`
3. Displays agents grouped by source node with checkboxes
4. Each agent shows: display name, title, model, station codes
5. Optional task description textarea
6. "Send Request" → POST `/api/mesh/agents/lend` per selected agent
7. Privacy indicators: shield icon for restricted nodes
8. Return flow: "Return" button in loans table → POST `/api/mesh/agents/return`

### Polling

- Mesh loans + available agents: 30s interval (matches node polling)
- Learning patterns: 60s interval (matches model polling)

## Files Modified

| File | Change |
|------|--------|
| `platform_v2/tools/bridge/routes.py` | Add `GET /api/mesh/available-agents` endpoint |
| `platform_v2/templates/tools/bridge.html` | JS render functions for mesh loans, learning patterns, available agents modal, Request Help button, polling, mesh stats |

No new files. No CSS changes (existing mesh styles sufficient). No DB migrations (all tables exist).
