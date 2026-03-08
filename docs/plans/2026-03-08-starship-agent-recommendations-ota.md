# Starship Agent Classification, Recommendations & OTA Push — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix agent uniqueness, build agent recommendation engine, enhance Starship Agents tab, and wire up OTA push for agent config and code updates.

**Architecture:** Migration adds `is_cloneable` flag to agents table and cleans up bad clones. Recommendation engine scores cloneable agents by station match, job volume, success rate, and model efficiency. Starship Agents tab gets a recommendation panel with Add to Crew flow. OTA push uses existing `mesh_sync_log` and `deployment_packages` infrastructure.

**Tech Stack:** Flask (starship/routes.py), PostgreSQL (agents, node_agents, task_execution_log, mesh_sync_log), Vanilla JS (starship.html embedded)

**Security Note:** All dynamic content rendered via `escHtml()` — the existing XSS-safe helper used throughout starship.html. Same pattern as existing rendering functions.

**Dev HQ:** Project #120, Tasks #809-815

---

### Task 1: Migration — is_cloneable flag + cleanup

**Files:**
- Create: `database/migrations/141_agent_cloneable.sql`

Add `is_cloneable BOOLEAN DEFAULT true` to agents table. Set false for ARCHIE (id 2), Vigil (id 3), and any agent named Kytran. Delete existing node_agents where source_agent_id is non-cloneable.

Test: Verify ARCHIE/Vigil marked non-cloneable, bad clones count = 0.

Commit: `feat(starship): add is_cloneable flag to agents, clean up hub-only clones`

---

### Task 2: Fix _generate_node_crew to filter is_cloneable

**Files:**
- Modify: `platform_v2/tools/starship/routes.py:123-137`

Add `AND a.is_cloneable = true` to the WHERE clause of the agent SELECT query in `_generate_node_crew()` at line 134.

Test: Verify ARCHIE and Vigil do NOT appear in the cloneable agent list.

Commit: `fix(starship): filter non-cloneable agents from node crew generation`

---

### Task 3: Recommendation Engine Backend

**Files:**
- Modify: `platform_v2/tools/starship/routes.py` (add MODULE_STATION_MAP constant after imports ~line 16, add functions and endpoints after line 802)

**New code to add:**

1. `MODULE_STATION_MAP` dict — maps SaaS module slugs to station codes (17 modules mapped)

2. `get_agent_recommendations(node_int_id)` function:
   - Gets node's enabled stations from `node_station_assignments`
   - Gets node's existing crew from `node_agents`
   - Gets all cloneable agents with stations from `agents` + `station_assignments`
   - Gets job stats from `task_execution_log` (last 30 days) grouped by agent_name
   - Scores each agent not already on node: station_match 40%, job_volume 30%, success_rate 20%, model_efficiency 10%
   - Uses MODEL_SIZE_HINTS dict for model efficiency scoring
   - Builds reason strings explaining each recommendation
   - Generates station_suggestions when modules imply un-enabled stations
   - Returns recommendations sorted by score (filtered > 0.1), station_suggestions, enabled_stations, existing_crew_count

3. `GET /api/starship/<int:node_id>/recommendations` endpoint — calls get_agent_recommendations, returns JSON

4. `_add_single_agent_to_node(node_int_id, node_id_str, agent_id)` helper:
   - Fetches Bridge agent (must be cloneable)
   - Checks not already on node
   - Generates unique name using same name pools and deterministic seeding as _generate_node_crew
   - Inserts into node_agents with ON CONFLICT DO NOTHING

5. `POST /api/starship/<int:node_id>/agents/add` endpoint — calls _add_single_agent_to_node

6. `DELETE /api/starship/<int:node_id>/agents/<int:agent_id>` endpoint — removes agent from node_agents

Test: Verify recommendation endpoint returns scored agents for KYTRAN-StarShip.

Commit: `feat(starship): add agent recommendation engine and add/remove crew endpoints`

---

### Task 4: Enhance Starship Agents Tab UI

**Files:**
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html`

**HTML changes (Agents tab panel, ~line 437-449):**

1. Before `#d-agents-list`, insert recommendation panel:
   - `#agent-recommendations` container (hidden by default)
   - Section header "Recommended Crew" with "Add All" button
   - `#recommendation-cards` container for agent cards
   - `#station-suggestions` container for tips

2. After `#d-agents-list`, insert sync status:
   - `#agent-sync-status` bar with sync indicator text and "Push Changes to Node" button

**JS functions to add (after agent rendering ~line 879):**

1. `loadRecommendations(nodeId)` — fetches `/api/starship/{nodeId}/recommendations`, calls renderRecommendations
2. `renderRecommendations(data)` — builds recommendation cards with score bars, station badges, Add buttons. Uses `escHtml()` for all dynamic values. Uses `document.createElement` + textContent for text, element construction for structure.
3. `addRecommendedAgent(agentId)` — POST to add endpoint, reloads agents and recommendations
4. `addAllRecommended()` — clicks Add on each recommendation sequentially
5. `removeAgentFromNode(nodeAgentId)` — DELETE to remove endpoint, reloads agents and recommendations
6. `pushAgentConfig()` — POST to push-config endpoint, updates sync indicator

**Existing code changes:**
- Add Remove button to each agent row in the agent list rendering loop (~line 841-879)
- Wire `loadRecommendations(nodeId)` into node selection handler alongside existing loadNodeStatus

Commit: `feat(starship): add recommendation panel, crew management, and sync UI to Agents tab`

---

### Task 5: OTA Push — Agent Config via mesh_sync_log

**Files:**
- Modify: `platform_v2/tools/starship/routes.py`

Add `POST /api/starship/<int:node_id>/push-config` endpoint:
- Gets node's string node_id from remote_nodes
- Builds crew manifest from node_agents (name, display_name, title, model, system_prompt, capabilities, station_codes, is_allowed, status)
- Inserts into mesh_sync_log with sync_type='agent_config', payload=JSON manifest, status='sent'
- Returns sync_id and agent count

Commit: `feat(starship): add OTA push for agent config via mesh_sync_log`

---

### Task 6: OTA Push — Code Update + Sync Log Display

**Files:**
- Modify: `platform_v2/tools/starship/routes.py`
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html`

**Backend:**

1. `POST /api/starship/<int:node_id>/push-update` endpoint:
   - Gets latest deployment_packages entry
   - Sets update_requested=true on remote_nodes
   - Inserts mesh_sync_log with sync_type='code_update', package version in payload
   - Returns sync_id and version

2. `GET /api/starship/<int:node_id>/sync-log` endpoint:
   - Returns last 10 mesh_sync_log entries for node (id, sync_type, status, sent_at, acknowledged_at, error_message)
   - Converts datetimes to ISO format

**Frontend (Status tab):**

1. HTML: Add OTA update section after version row in panel-status (~line 370-408):
   - "Remote Updates" header with "Push Update" button
   - `#sync-log-list` container

2. JS functions:
   - `pushCodeUpdate()` — POST to push-update, confirms first, reloads sync log
   - `loadSyncLog(nodeId)` — fetches sync-log endpoint, calls renderSyncLog
   - `renderSyncLog(logs)` — renders log entries with type, status (color-coded), timestamp. Uses escHtml() and document.createElement for all dynamic content.

3. Wire `loadSyncLog(nodeId)` into node selection handler

Commit: `feat(starship): add OTA code update push and sync log display`

---

### Task 7: Deploy and Integration Test

1. Run migration 141
2. Restart platform
3. Integration test checklist:
   - ARCHIE/Vigil not in node_agents (cleaned up)
   - is_cloneable = false for ARCHIE, Vigil, Kytran
   - Starship > select node > Agents tab shows recommendation panel
   - Add agent works, Remove agent works
   - Push Changes to Node creates sync log entry
   - Status tab shows OTA section with Push Update and sync log
   - No JS errors
4. Push to origin/main
5. Update Dev HQ: complete tasks #809-815, log decisions
