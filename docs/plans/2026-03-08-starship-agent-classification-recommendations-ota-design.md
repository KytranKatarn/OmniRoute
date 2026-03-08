# Starship Agent Classification, Recommendations & OTA Push — Design

**Date:** 2026-03-08
**Project:** #120 — Starship Agent Classification, Recommendations & OTA Push
**Status:** Approved

---

## Goal

Fix agent uniqueness (ARCHIE/Vigil/Kytran are hub-only singletons, never cloned to nodes). Build a recommendation engine that suggests agents for each node based on enabled stations, Bridge job stats, and SaaS module mapping. Enhance Starship Command Agents tab with recommendation panel and crew sync. Add remote OTA push for agent config and operational code updates.

## Context

Currently `_generate_node_crew()` clones every active Bridge agent to a node, including ARCHIE and Vigil. These are hub-only singletons that should never be duplicated. Nodes also have no guidance on which agents they actually need. And while the mesh sync infrastructure exists (mesh_sync_log, deployment_packages, update_requested), there's no UI to push changes from the hub to nodes.

## Architecture Decisions

- **Agent classification via `is_cloneable` flag** on agents table, not a separate mapping table
- **Recommendation scoring**: station match 40%, job volume 30%, success rate 20%, model efficiency 10%
- **Module-to-station mapping** as a Python dict in routes.py (not a DB table — it's config, not data)
- **OTA via existing mesh_sync_log** — two payload types: `agent_config` and `code_update`
- **No new tables** — uses existing infrastructure throughout

---

## Section 1: Agent Classification & Cleanup

**Migration 141:** Add `is_cloneable` boolean to `agents` table (default true).

Set `is_cloneable = false` for:
- ARCHIE (id 2) — hub commander, is_fixed
- Kytran — human admin
- Vigil/Sentinel (id 3) — ethics overseer, is_fixed

Clean up: DELETE from `node_agents` where `source_agent_id` IN (non-cloneable agent ids).

**Code fix:** `_generate_node_crew()` in `starship/routes.py` adds `WHERE a.is_cloneable = true` to the agent query.

---

## Section 2: Recommendation Engine

**New function:** `get_agent_recommendations(node_id)` in `starship/routes.py`

Inputs:
- Node's enabled stations (from `node_station_assignments`)
- Node's existing crew (from `node_agents`)
- Bridge job stats (from `task_execution_log`, last 30 days)

Scoring for each cloneable agent NOT already on the node:
- **Station match (40%)** — agent covers stations the node has enabled
- **Job volume (30%)** — agent's job count on hub in last 30 days (higher = more essential)
- **Success rate (20%)** — % of agent's jobs completed successfully
- **Model efficiency (10%)** — smaller model = easier to run on resource-constrained nodes

Module-to-station mapping (config dict):
```python
MODULE_STATION_MAP = {
    "store-builder": ["OPERATIONS", "ANALYTICS"],
    "media-hub": ["CREATIVE", "OPERATIONS"],
    "email-manager": ["OPERATIONS"],
    "invoicing": ["OPERATIONS", "ANALYTICS"],
    "website-studio": ["CREATIVE", "ENGINEERING"],
    "crm": ["OPERATIONS", "ANALYTICS"],
    "social-media": ["CREATIVE", "OPERATIONS"],
    "content-studio": ["CREATIVE"],
    "dev-pipeline": ["ENGINEERING", "QA"],
    "fitness": ["ANALYTICS", "OPERATIONS"],
    "therapy": ["ANALYTICS", "RESEARCH"],
    "game-studio": ["CREATIVE", "ENGINEERING"],
}
```

If enabled modules imply stations the node hasn't enabled, recommendation includes a note.

Response format:
```json
{
  "recommendations": [
    {
      "agent_id": 4,
      "name": "CodeSmith",
      "display_name": "Aria Chen (CodeSmith)",
      "title": "Lead Software Engineer",
      "model": "qwen2.5-coder:7b",
      "score": 0.87,
      "reason": "Handles 45% of ENGINEERING jobs. Your node has ENGINEERING enabled.",
      "stations": ["ENGINEERING", "COMMAND"],
      "job_count_30d": 312,
      "success_rate": 0.94
    }
  ],
  "station_suggestions": ["Consider enabling CREATIVE station - your Media Hub module needs it."]
}
```

**New endpoint:** `GET /api/starship/<node_id>/recommendations`

---

## Section 3: Starship Agents Tab Enhancement

**Top: Recommendation Panel**
- LCARS banner: "Recommended Crew for [Node Name]"
- Cards per recommended agent: name, title, model, score bar, reason, stations
- "Add to Crew" per card, "Add All Recommended" at top
- Collapses when all recommendations accepted or none exist
- Refreshes when stations toggled

**Middle: Current Crew Roster** (enhanced)
- Existing toggle switches for is_allowed
- Add model badge and station color tags
- Add "Remove from Crew" button per agent (deletes from node_agents)
- Show agent status: idle / working / unavailable

**Bottom: Sync Status**
- Last sync timestamp
- "Push Changes to Node" button (packages crew into mesh_sync_log type agent_config)
- Indicator: "In sync" / "Changes pending push" / "Node offline"

---

## Section 4: Remote Push (OTA)

**Two payload types via mesh_sync_log:**

**1. `agent_config`** — crew changes
- Payload: full crew manifest (names, models, prompts, capabilities, station_codes, is_allowed)
- Trigger: "Push Changes to Node" button in Agents tab
- Node heartbeat: GET /api/mesh/sync/<node_id>/pending
- Node applies + acks: POST /api/mesh/sync/<sync_id>/ack

**2. `code_update`** — operational code for node to function with Bridge
- Payload: version tag, changed files list, download URL from deployment_packages
- Trigger: "Push Update" button in Status tab
- Uses existing update_requested flag on remote_nodes
- Node heartbeat sees flag, pulls package, reports version via POST /api/mesh/version

**Status tab enhancement:**
- Node version vs hub version (from mesh_code_versions)
- "Push Update" button (disabled if versions match)
- Sync log history: last 10 operations with status

---

## Files Modified

| File | Change |
|------|--------|
| `database/migrations/141_agent_cloneable.sql` | Add is_cloneable, set flags, clean up bad clones |
| `platform_v2/tools/starship/routes.py` | Filter is_cloneable, recommendation engine, push endpoints |
| `platform_v2/tools/starship/templates/tools/starship/starship.html` | Agents tab (recommendations, remove, sync), Status tab (version, push, log) |

No new files. No new tables. 1 new migration. Existing mesh infrastructure reused throughout.

## Dev HQ

- Project #120, Tasks #809-815
- Decision: Hub-only singletons (ARCHIE, Vigil, Kytran) never cloned via is_cloneable flag
- Decision: Demand-driven recommendations with module-station awareness
