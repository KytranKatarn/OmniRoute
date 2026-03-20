# Platform Stabilization — Bottom-Up Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore platform stability by fixing foundation layers bottom-up: MCP tools → Bridge hub dispatch → Node fleet → Starbase UI → Module re-enablement.

**Architecture:** Layered recovery — each phase depends on the previous. No parallel work across phases. Every fix verified with evidence and tracked in Dev HQ Project #171.

**Tech Stack:** Python/Flask, PostgreSQL, Ollama API, MCP Server, Docker

**Spec:** `docs/superpowers/specs/2026-03-20-platform-stabilization-design.md`

**Dev HQ Project:** #171 — Platform Stabilization — Bottom-Up Recovery

---

## File Structure

| File | Responsibility | Phase |
|------|---------------|-------|
| `platform_v2/mcp_server/tools/claude_tools.py` | MCP tool SQL queries (broken `importance` column) | 1 |
| `ai_bridge/bridge_dispatcher.py` | Core dispatch functions: `dispatch()` L7543, `dispatch_json()` L7585 | 2 |
| `ai_bridge/smart_router.py` | 11-tier escalation routing, `SmartRouter` class L195 | 2 |
| `platform_v2/tools/starbase/crew_routes.py` | Manifest endpoint L951, roster display | 2, 4 |
| `platform_v2/tools/starbase/node_routes.py` | Node management, approval, assignments | 3 |
| `MEMORY.md` (auto-memory) | Session context — currently 162 lines, stale | 0 |

---

## Phase 0: Housekeeping

### Task 0.1: Clean MEMORY.md

**Files:**
- Modify: `/home/kytran/.claude/projects/-mnt-archie-brain/memory/MEMORY.md`

- [ ] **Step 1: Read current MEMORY.md and identify stale claims**

Check for: "PLATFORM RECOVERY MODE" header (stale?), contradictory agent counts, project references to completed/cancelled work.

- [ ] **Step 2: Update MEMORY.md**

Remove the "CRITICAL — PLATFORM RECOVERY MODE" header. Replace with accurate current state referencing Project #171. Strip contradictory claims. Keep under 100 lines. Ensure every section reflects verified current reality, not assumptions from past sessions.

- [ ] **Step 3: Verify no contradictions remain**

Read the updated file. Cross-check agent count against DB (`SELECT count(*) FROM agents`). Cross-check project references against `mcp get_projects`.

- [ ] **Step 4: Commit**

```bash
git add -A  # memory files aren't in repo, but commit any related changes
```

**Dev HQ:** `create_task` "Clean MEMORY.md — remove stale claims" on Project #171, `complete_task` with verification notes.

---

## Phase 1: Fix Broken MCP Tools

### Task 1.1: Fix `search_mistakes` SQL Query

**Files:**
- Modify: `platform_v2/mcp_server/tools/claude_tools.py:200,204,220`

- [ ] **Step 1: Read the broken code**

```bash
# Read lines 190-245 of claude_tools.py to see the search_mistakes_handler
```

Confirm the SQL references `importance` instead of `importance_score`.

- [ ] **Step 2: Verify actual DB column name**

```bash
docker exec -it archie_database psql -U archie -d archie -c "\d knowledge_base" | grep importance
```

Expected: `importance_score` column exists, `importance` does not.

- [ ] **Step 3: Fix the SQL queries**

In `search_mistakes_handler()`:
- Line 200: Change `importance,` → `importance_score,`
- Line 204: Change `ORDER BY importance DESC` → `ORDER BY importance_score DESC`
- Line 220: Check for any other `importance` references → change to `importance_score`

- [ ] **Step 4: Verify fix**

Call `mcp search_mistakes` with query "failure". Expected: results returned, no SQL error.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/mcp_server/tools/claude_tools.py
git commit -m "fix(mcp): search_mistakes — importance → importance_score column name"
```

**Dev HQ:** `create_task` "Fix search_mistakes MCP tool — wrong column name" on Project #171. `complete_task` with the successful tool call result.

---

### Task 1.2: Fix `search_knowledge_brief` SQL Query

**Files:**
- Modify: `platform_v2/mcp_server/tools/claude_tools.py:833,836`

- [ ] **Step 1: Read the broken code**

```bash
# Read lines 825-865 of claude_tools.py
```

Confirm SQL references `importance` on lines 833 and 836.

- [ ] **Step 2: Fix the SQL queries**

- Line 833: Change `SELECT id, title, knowledge_type, importance` → `SELECT id, title, knowledge_type, importance_score`
- Line 836: Change `ORDER BY importance DESC` → `ORDER BY importance_score DESC`

- [ ] **Step 3: Verify fix**

Call `mcp search_knowledge_brief` with query "bridge dispatch". Expected: results returned with titles, no SQL error.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/mcp_server/tools/claude_tools.py
git commit -m "fix(mcp): search_knowledge_brief — importance → importance_score column name"
```

**Dev HQ:** `create_task` "Fix search_knowledge_brief MCP tool — wrong column name" on Project #171. `complete_task` with the successful tool call result.

---

### Task 1.3: Scan All MCP Tools for Stale Schema References

**Files:**
- Read: `platform_v2/mcp_server/tools/claude_tools.py` (full file)

- [ ] **Step 1: Search for any remaining `importance` references (without `_score`)**

```bash
grep -n "importance" platform_v2/mcp_server/tools/claude_tools.py | grep -v "importance_score"
```

Expected: zero results after Tasks 1.1 and 1.2.

- [ ] **Step 2: Test all knowledge-related MCP tools**

Call each of these and confirm no errors:
- `mcp search_knowledge` (query: "bridge")
- `mcp search_knowledge_brief` (query: "bridge")
- `mcp search_mistakes` (query: "failure")
- `mcp get_knowledge_stats`

- [ ] **Step 3: Log results**

**Dev HQ:** `create_task` "Verify all MCP knowledge tools work" on Project #171. `complete_task` with results from each tool call.

---

## Phase 2: Bridge Dispatcher — Hub-Only Stabilization

### Task 2.1: Audit Current Agent States

**Files:**
- Read-only: database queries

- [ ] **Step 1: Query agent roster state**

```sql
-- Run via: docker exec -it archie_database psql -U archie -d archie
SELECT shift_state, count(*) FROM agents GROUP BY shift_state ORDER BY count DESC;
```

Document: how many active, deployed, barracked, off_duty?

- [ ] **Step 2: Check station assignments**

```sql
SELECT sa.station_code, a.display_name, a.shift_state, a.model_id
FROM station_assignments sa
JOIN agents a ON a.id = sa.agent_id
WHERE sa.is_active = true
ORDER BY sa.station_code;
```

Document: which agents on which stations? Any anomalies?

- [ ] **Step 3: Check node agent state**

```sql
SELECT na.*, rn.hostname, rn.status as node_status
FROM node_agents na
JOIN remote_nodes rn ON rn.id = na.node_id
ORDER BY rn.hostname;
```

Document: are node agents marked active when nodes are offline? Are hub agents incorrectly showing as deployed?

- [ ] **Step 4: Document findings**

**Dev HQ:** `create_task` "Audit agent roster state — DB snapshot" on Project #171. `complete_task` with all query results pasted in notes.

---

### Task 2.2: Trace Bridge Dispatch Path

**Files:**
- Read: `ai_bridge/bridge_dispatcher.py` (focus on L7543-7622 for dispatch/dispatch_json, then trace request_work)
- Read: `ai_bridge/smart_router.py` (L195+ SmartRouter class, escalation tiers L151-173)

- [ ] **Step 1: Read dispatch() entry point**

Read `bridge_dispatcher.py` lines 7543-7622. Document:
- What validation happens?
- How does it select an agent?
- Where does node routing enter the picture?

- [ ] **Step 2: Trace request_work()**

Find `request_work` method in `BridgeDispatcher` class. Document:
- Does it check node agents?
- What happens if a node agent is selected but the node is offline?
- Is there a fallback to hub agents?

- [ ] **Step 3: Read SmartRouter escalation**

Read `smart_router.py` L151-195. Document:
- What are the 11 tiers?
- When does it escalate to fleet/cloud?
- Does it check node health before routing to a node?

- [ ] **Step 4: Document the full dispatch flow**

Write up: prompt → validation → agent selection → model check → escalation → execution → response. Note any gaps where node integration could cause failures.

**Dev HQ:** `create_task` "Trace Bridge dispatch path — document full flow" on Project #171. `complete_task` with the written trace.

---

### Task 2.3: Test Hub-Only Dispatch

**Files:**
- May modify: `ai_bridge/bridge_dispatcher.py` if fix needed

- [ ] **Step 1: Test a simple dispatch via API**

```bash
curl -s http://192.168.1.200:3000/api/bridge \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Say hello", "capability": "general"}' | python3 -m json.tool
```

Document: does it succeed? Which agent handled it? Any errors?

- [ ] **Step 2: Check docker logs for dispatch errors**

```bash
docker logs archie_platform --tail 50 | grep -i "dispatch\|error\|bridge"
```

- [ ] **Step 3: If dispatch fails — identify the specific failure point**

Based on Task 2.2 trace, pinpoint where it breaks. Common candidates:
- Agent selection returns a deployed/offline agent
- Model not loaded (warm-boot fails)
- Node agent selected but node unreachable

- [ ] **Step 4: Apply targeted fix (if needed)**

Fix only the specific failure point identified. Do NOT refactor surrounding code.

- [ ] **Step 5: Re-test dispatch**

Same curl command as Step 1. Expected: successful response with agent name and model output.

- [ ] **Step 6: Commit fix (if changes made)**

```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "fix(bridge): [describe specific fix]"
```

**Dev HQ:** `create_task` "Test and fix hub-only Bridge dispatch" on Project #171. `complete_task` with curl response output.

---

### Task 2.4: Verify Starbase Manifest Matches DB

**Files:**
- Read: `platform_v2/tools/starbase/crew_routes.py` L951-1050

- [ ] **Step 1: Hit the manifest API endpoint**

```bash
curl -s http://192.168.1.200:3000/tools/starbase/api/bridge/crew/manifest \
  -b "session=<admin_session_cookie>" | python3 -m json.tool | head -100
```

(Get session cookie by logging in via Playwright first if needed)

- [ ] **Step 2: Compare manifest response vs DB query from Task 2.1**

Check: agent count matches, shift states match, station assignments match. Document any discrepancies.

- [ ] **Step 3: If discrepancies found — trace the manifest endpoint code**

Read `crew_routes.py` L951+. Find where it builds the manifest. Identify why it differs from raw DB.

- [ ] **Step 4: Fix discrepancies (if any)**

- [ ] **Step 5: Verify via Playwright**

Navigate to Starbase Command, take screenshot of Active Roster. Compare to DB.

**Dev HQ:** `create_task` "Verify Starbase manifest matches DB state" on Project #171. `complete_task` with screenshot + comparison notes.

---

## Phase 3: Node Fleet Re-integration

### Task 3.1: Audit Node Fleet State

**Files:**
- Read-only: database queries, node API

- [ ] **Step 1: Query remote_nodes table**

```sql
SELECT id, hostname, display_name, status, deployment_mode,
       last_heartbeat, created_at
FROM remote_nodes ORDER BY id;
```

- [ ] **Step 2: Query node_agents table**

```sql
SELECT na.id, na.hub_agent_id, a.display_name, na.status,
       na.node_id, rn.hostname
FROM node_agents na
JOIN agents a ON a.id = na.hub_agent_id
JOIN remote_nodes rn ON rn.id = na.node_id;
```

- [ ] **Step 3: Check actual node health**

```bash
curl -s http://192.168.1.246:5000/api/status 2>/dev/null || echo "Node unreachable"
curl -s http://192.168.1.246:11434/api/tags 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{len(d.get(\"models\",[]))} models loaded')" || echo "Ollama unreachable"
```

- [ ] **Step 4: Document discrepancies**

Compare: DB thinks node is [status] with [N] agents, but reality is [actual state].

**Dev HQ:** `create_task` "Audit node fleet — DB vs reality" on Project #171. `complete_task` with all query results.

---

### Task 3.2: Reconcile Node State

**Files:**
- May modify: database records via SQL

- [ ] **Step 1: Fix stale node entries**

If node is offline but DB says online → update status. If ghost agents exist → deactivate.

```sql
-- Example: mark offline node
UPDATE remote_nodes SET status = 'offline' WHERE hostname = '192.168.1.245' AND status != 'offline';
-- Example: deactivate ghost node agents
UPDATE node_agents SET status = 'inactive' WHERE node_id = (SELECT id FROM remote_nodes WHERE status = 'offline');
```

- [ ] **Step 2: Return deployed agents to hub**

If agents are marked 'deployed' but their node is offline:

```sql
UPDATE agents SET shift_state = 'barracked'
WHERE shift_state = 'deployed'
AND id IN (SELECT hub_agent_id FROM node_agents na JOIN remote_nodes rn ON rn.id = na.node_id WHERE rn.status = 'offline');
```

- [ ] **Step 3: Verify reconciliation**

Re-run queries from Task 3.1. Confirm DB matches reality.

**Dev HQ:** `create_task` "Reconcile node fleet — fix stale DB entries" on Project #171. `complete_task` with before/after query results.

---

### Task 3.3: Re-integrate Online Node

**Files:**
- May modify: `ai_bridge/bridge_dispatcher.py`, node agent records

- [ ] **Step 1: Verify node .246 is actually online**

```bash
curl -s http://192.168.1.246:5000/api/status | python3 -m json.tool
```

If offline → skip this task, document in Dev HQ, move to Phase 4.

- [ ] **Step 2: Activate node agents in DB**

```sql
UPDATE node_agents SET status = 'active'
WHERE node_id = (SELECT id FROM remote_nodes WHERE hostname = '192.168.1.246')
AND status = 'inactive';
```

- [ ] **Step 3: Update corresponding hub agents to 'deployed'**

```sql
UPDATE agents SET shift_state = 'deployed'
WHERE id IN (SELECT hub_agent_id FROM node_agents WHERE status = 'active' AND node_id = (SELECT id FROM remote_nodes WHERE hostname = '192.168.1.246'));
```

- [ ] **Step 4: Test dispatch to node agent**

```bash
curl -s http://192.168.1.200:3000/api/bridge \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Say hello from node", "capability": "general", "prefer_node": true}' | python3 -m json.tool
```

- [ ] **Step 5: Verify in Starbase**

Check that the node shows as online with active agents in the Starship tab.

- [ ] **Step 6: Commit any code changes**

**Dev HQ:** `create_task` "Re-integrate node .246 into dispatch pool" on Project #171. `complete_task` with dispatch test result + Starbase screenshot.

---

## Phase 4: Starbase Command & Manifest Verification

### Task 4.1: Full UI Verification

**Files:**
- Read: `platform_v2/tools/starbase/` (various routes)
- Playwright for browser verification

- [ ] **Step 1: Navigate to Starbase Command**

Open `http://192.168.1.200:3000/tools/starbase` in Playwright. Take screenshot.

- [ ] **Step 2: Check Active Roster / Manifest tab**

Verify: agent count, shift states, station assignments all match DB (from Task 2.1 results).

- [ ] **Step 3: Check each station panel**

Click through all 10 stations. Verify each shows 2 primary agents. Take screenshots.

- [ ] **Step 4: Test model load/unload**

Pick a barracked agent. Click "Load Model" in Starbase. Verify:
```bash
curl -s http://192.168.1.200:11434/api/ps | python3 -m json.tool
```
Model appears in running list.

- [ ] **Step 5: Check Starship tab (if node online)**

Verify node .246 shows with correct status, agents, models.

- [ ] **Step 6: Document all findings**

**Dev HQ:** `create_task` "Full Starbase Command UI verification" on Project #171. `complete_task` with screenshots and comparison notes.

---

## Phase 5: Downstream Module Re-enablement

### Task 5.1: Verify Already-Working Modules

**Files:**
- Playwright for browser verification

- [ ] **Step 1: Test Consciousness module**

Navigate to `/tools/consciousness`. Verify:
- Dashboard tab loads
- Knowledge tab shows entries
- Code Health tab shows metrics
- Team tab shows agents

- [ ] **Step 2: Test Dev HQ module**

Navigate to `/dev-hq`. Verify:
- Projects list loads
- Tasks display correctly
- Knowledge search works

- [ ] **Step 3: Test Media Hub**

Navigate to `/tools/media-hub`. Verify it loads without errors.

- [ ] **Step 4: Test Dev Pipeline**

Navigate to `/tools/dev-pipeline`. Verify:
- Scan tab can trigger a scan
- Proposals tab loads existing proposals
- Engineering station panel shows agents

**Dev HQ:** `create_task` "Verify working modules — Consciousness, Dev HQ, Media Hub, Dev Pipeline" on Project #171.

---

### Task 5.2: Re-enable Modules One at a Time

For EACH module in order: CRM → Invoicing → Store Builder → Website Designer → Content Studio → Social Media → Call Center → StockBot → Cost Planner → Evaluation Design

- [ ] **Step 1: Check module code for dispatch dependencies**

Read the module's main route file. Does it call `dispatch()` or `dispatch_json()`? With what capability?

- [ ] **Step 2: Navigate to the module in browser**

Does the page load? Any errors in docker logs?

- [ ] **Step 3: Test core dispatch action (if Bridge working)**

Trigger the module's primary AI action. Does it return a result?

- [ ] **Step 4: Record status**

For each module, record: WORKING / PARTIAL (loads but dispatch fails) / BROKEN (won't load)

- [ ] **Step 5: Create follow-up tasks for broken modules**

Any module that needs deeper work gets its own task in Project #171.

**Dev HQ:** `create_task` per module: "Re-enable and verify [module name]" on Project #171. `complete_task` with status and evidence.

---

## Phase 6: Post-Stabilization Cleanup

### Task 6.1: Update All Documentation

- [ ] **Step 1: Update MEMORY.md to reflect stable state**

Remove recovery language. Update module status. Confirm accurate agent counts. Reference Project #171 as completed.

- [ ] **Step 2: Update CLAUDE.md if any rules changed**

- [ ] **Step 3: Log final project understanding**

```
mcp update_project_understanding for Project #171
```

- [ ] **Step 4: Unfreeze pending tasks**

Review the 50 pending tasks. Close any that are now irrelevant. Re-prioritize the rest.

**Dev HQ:** `complete_task` for Project #171 with full summary of what was fixed, what's working, what needs follow-up.

---

## Execution Notes

- **Phase 0** can be done in this session
- **Phase 1** can be done in this session (it's a 4-line SQL fix)
- **Phases 2-5** should each be their own session for focus
- **Never skip Dev HQ tracking** — that's the whole point of this plan
- **If a phase reveals unexpected problems** — create a new task, don't scope-creep the current one
- **If 3 attempts at the same fix fail** — stop, document what was tried, ask for guidance
