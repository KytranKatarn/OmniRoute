# Mesh Network Wiring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire the Bridge Network tab's mesh accordion panels to their backend APIs, add mesh summary stats, and implement a demand-driven "Request Help" agent lending flow.

**Architecture:** One new backend endpoint (`GET /api/mesh/available-agents`) in mesh_routes.py returns lendable agents with privacy awareness. Frontend JS render functions populate the existing mesh HTML containers, add a "Request Help" button to node cards, and a modal for selecting idle agents to borrow. All mesh data polls on 30-60s intervals alongside existing node/model polling.

**Tech Stack:** Flask API (mesh_routes.py), PostgreSQL (node_agents, remote_nodes, mesh_agent_loans, mesh_learning_patterns), Vanilla JS (bridge.html embedded)

**Security Note:** All dynamic content rendered via `escapeHtml()` — the existing XSS-safe pattern used throughout bridge.html. DOM string building follows the same approach as `renderNodeCard()`, `renderLocalModels()`, `renderRemoteModels()`, and `showAddNodeModal()`.

**Dev HQ:** Project TBD, Tasks TBD

---

### Task 1: Backend — Available Agents Endpoint

**Files:**
- Modify: `platform_v2/tools/bridge/mesh_routes.py`

**Step 1: Add the available-agents endpoint**

Add inside `register_mesh_routes(bridge_bp)`, after the cluster overview endpoint (~line 634). Follow the existing pattern: `@bridge_bp.route`, `@login_required`, `get_db_cursor`, consistent JSON response.

The endpoint joins `node_agents` + `remote_nodes` to find lendable agents:
- Node must be online, approved, bridge_enabled, active
- Node must have capacity (current_load < max_concurrent)
- Privacy: exclude nodes with local_data_only = true
- Agent must be allowed, active, not currently on active loan
- Computes privacy_level from privacy_settings JSONB
- Returns available_agents array + summary stats (total_available, nodes_with_capacity, active_loans)

**Step 2: Test endpoint**

```bash
docker compose restart archie_platform
docker exec archie_platform python3 -c "
from database import get_db_cursor
with get_db_cursor(commit=False) as (conn, cur):
    cur.execute('SELECT count(*) FROM node_agents')
    print('node_agents:', cur.fetchone())
    cur.execute('SELECT count(*) FROM remote_nodes WHERE status = %s AND approval_status = %s', ('online', 'approved'))
    print('online approved nodes:', cur.fetchone())
"
```

**Step 3: Commit**

```bash
git add platform_v2/tools/bridge/mesh_routes.py
git commit -m "feat(bridge): add available-agents mesh endpoint for agent lending"
```

---

### Task 2: JS — Mesh Data Loading Functions

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Step 1: Add mesh loading functions**

Add after the `toggleMeshSection` function (~line 16867) and before the `DOMContentLoaded` event listener (~line 16874). Three async functions:
- `loadMeshLoans()` — fetches `/tools/bridge/api/mesh/agents/loans`, calls `renderMeshLoans()`
- `loadMeshLearning()` — fetches `/tools/bridge/api/mesh/learning`, calls `renderMeshLearning()`
- `loadMeshAvailableAgents()` — fetches `/tools/bridge/api/mesh/available-agents`, stores in `window._meshAvailableAgents` and `window._meshSummary`, calls `updateMeshHeaderStats()`

**Step 2: Add to polling in DOMContentLoaded**

In the existing `DOMContentLoaded` block (~line 16874), add the mesh calls and intervals:
- `loadMeshLoans()` + `setInterval(loadMeshLoans, 30000)`
- `loadMeshLearning()` + `setInterval(loadMeshLearning, 60000)`
- `loadMeshAvailableAgents()` + `setInterval(loadMeshAvailableAgents, 30000)`

Also update the `switchBridgeTab` network case (~line 10052) to trigger all mesh loads.

**Step 3: Test polling works**

```bash
docker compose restart archie_platform
# Open http://192.168.1.200:3000/tools/bridge, Network tab
# Check browser console for fetch calls to mesh endpoints (no errors)
```

**Step 4: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): add mesh data loading functions and polling"
```

---

### Task 3: JS — Render Mesh Loans Table

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Step 1: Add renderMeshLoans and returnMeshAgent functions**

`renderMeshLoans(loans)`:
- Updates `#mesh-loans-container` with a table: Agent, Source to Target, Status, Duration, Actions
- Active loans show "Return" button calling `returnMeshAgent(loanId)`
- Updates accordion header text with active count and available count
- Empty state: "No agent loans recorded. Use Request Help on a node card to borrow an idle agent."
- All dynamic values passed through `escapeHtml()` for XSS safety

`returnMeshAgent(loanId)`:
- Confirms with user
- POST to `/tools/bridge/api/mesh/agents/return` with `{ loan_id: loanId }`
- Refreshes loans and available agents on success

**Step 2: Test loans render**

```bash
docker compose restart archie_platform
# Open Network tab, expand Agent Mesh Pool accordion
# Should show empty state message (or table if loans exist)
```

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): render mesh agent loans table with return action"
```

---

### Task 4: JS — Render Learning Patterns Feed

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Step 1: Add renderMeshLearning and updateMeshHeaderStats functions**

`renderMeshLearning(patterns)`:
- Updates `#mesh-learnings-container` with pattern cards
- Each card: type badge (color-coded by pattern_type), category, insight text, metric, relative timestamp
- Type colors: optimization=green, error_pattern=red, performance=cyan, security=orange
- Updates accordion header text with pattern count
- Empty state: "No learning patterns shared yet."
- All dynamic values passed through `escapeHtml()` for XSS safety

`updateMeshHeaderStats(summary)`:
- Updates `#mesh-loans-count`, `#mesh-available-count`, `#mesh-learning-count` via textContent

**Step 2: Add "Available" stat to header HTML**

Find the `mesh-header-stats` div (~line 8605-8608) and add an "Available" badge between Loans and Learnings:
- `<span class="stat"><span id="mesh-available-count">0</span> Available</span>`

**Step 3: Test learning patterns render**

```bash
docker compose restart archie_platform
# Open Network tab, expand Learning Patterns accordion
# Verify header stats update with all three counters
```

**Step 4: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): render mesh learning patterns feed and header stats"
```

---

### Task 5: JS — Request Help Button on Node Cards

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Step 1: Add Request Help button to renderNodeCard**

Find the approved-node action buttons in `renderNodeCard` (~line 15598-15607). Add a purple "HELP" button between TEST and DETAIL, only shown when `currentLoad > 0`:
- Style: purple background (rgba(139,92,246,0.2)), #a78bfa text, matching border
- onClick: `showRequestHelpModal(node.node_id, node.node_name, currentLoad, maxConcurrent)`

**Step 2: Test button appears**

```bash
docker compose restart archie_platform
# Nodes with current_load > 0 should show purple "HELP" button
# Idle nodes (load = 0) should NOT show the button
```

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): add Request Help button to busy node cards"
```

---

### Task 6: JS — Request Help Modal

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Step 1: Add showRequestHelpModal and submitHelpRequest functions**

`showRequestHelpModal(targetNodeId, targetNodeName, currentLoad, maxConcurrent)`:
- Reads `window._meshAvailableAgents` (cached from polling)
- Groups agents by source node, excludes agents from the target node itself
- Creates modal using `.node-modal-overlay` + `.node-modal` pattern (same as `showAddNodeModal`)
- Modal shows: target node load info, agents grouped by source node with checkboxes, task description textarea
- Each agent row: checkbox, display_name, title, model, station codes
- Privacy indicator: shield icon for nodes with restricted privacy_level
- Empty state if no agents available
- Cancel and Send Request buttons
- All dynamic values passed through `escapeHtml()` for XSS safety
- Re-initializes lucide icons after DOM insertion

`submitHelpRequest(targetNodeId)`:
- Collects checked agents
- Validates at least one selected
- Loops through selected, POST to `/tools/bridge/api/mesh/agents/lend` for each with agent_id, source_node_id, target_node_id, task_description
- Closes modal, refreshes mesh data
- Shows success/failure summary alert

**Step 2: Test the full flow**

```bash
docker compose restart archie_platform
# Click "HELP" on a busy node
# Modal opens with available agents (or empty state)
# Select agents, add description, click Send Request
# Verify loan appears in Mesh Pool accordion
```

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): add Request Help modal with agent selection and lending"
```

---

### Task 7: Deploy and Integration Test

**Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

**Step 2: Full integration test checklist**

- Open Bridge > Network tab
- Verify node cards still render (TEST, DETAIL, REMOVE buttons)
- Verify mesh header stats show: Loans, Available, Learnings counts
- Expand Agent Mesh Pool accordion — shows loans table or empty state
- Expand Learning Patterns accordion — shows pattern feed or empty state
- Node with current_load > 0 shows purple "HELP" button
- Click HELP — modal opens with target node info
- Modal shows available agents grouped by source node (or empty state if none)
- Select agent(s), add description, click Send Request
- Loan appears in Agent Mesh Pool table
- Click Return on active loan — agent freed
- Verify 30s polling refreshes mesh data automatically
- Test with no online nodes — mesh panels show empty states gracefully
- Browser console: no JS errors

**Step 3: Final commit if needed**

```bash
git add -A
git commit -m "feat(bridge): complete mesh network wiring in Network tab"
```

**Step 4: Update Dev HQ**

- Create project and tasks via MCP
- Complete tasks as implemented
- Log architectural decision: "Mesh agent lending is demand-driven (admin-initiated) with privacy controls, not automated"
- Store vault note with mesh architecture summary
