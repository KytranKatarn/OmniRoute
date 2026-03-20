# Platform Stabilization — Bottom-Up Recovery

**Date:** 2026-03-20
**Status:** Approved
**Priority:** 10 (Critical)
**Type:** Bugfix / Infrastructure

---

## Problem Statement

The A.R.C.H.I.E. platform became unstable after rapid development (170 commits in 3 days) that introduced node fleet integration without sufficient verification. The Bridge dispatcher — the core system that routes all AI agent work — lost sync between hub and node agent rosters. This cascading failure disabled 10 modules and broke the self-improvement pipeline (Consciousness → Code Audit → Dev Pipeline).

### Symptoms
- Bridge dispatch unreliable — agents in roster but jobs fail or hang
- 10 SaaS modules disabled (CRM, Website Designer, Store Builder, Call Center, StockBot, Invoicing, Cost Planner, Social Media, Content Studio, Evaluation Design)
- 2 MCP tools broken (`search_mistakes`, `search_knowledge_brief`) — `column "importance" does not exist`
- Starbase Command manifest may not reflect actual cluster state
- Node fleet sync disrupted — heartbeats, agent assignments, model loading out of coherence
- MEMORY.md stale and contradictory (says "recovery mode" but health check shows healthy)
- 50 pending tasks across 10+ projects, no forward progress

### Root Causes
1. **Velocity without verification** — 170 commits/3 days, tasks reported done without browser/DB verification
2. **Broken MCP tools** — Claude can't search past mistakes, repeats them
3. **Stale MEMORY.md** — contradictory claims confuse new sessions
4. **Too many concurrent projects** — 10+ active workstreams, no focus
5. **No enforcement of verification** — feedback memories say "verify first" but nothing enforces it

---

## Design: Bottom-Up Layered Recovery

### Principle
Fix foundation layers first. Don't touch anything above until the layer below is verified working. Every fix tracked in Dev HQ with verification evidence.

### Dev HQ Tracking Protocol

**Project:** "Platform Stabilization — Bottom-Up Recovery" (priority 10, type: bugfix)

All existing tasks across Projects #139, #153, #169, #170 are **frozen** — no work until this stabilization project completes.

**Task lifecycle (mandatory for every fix):**
1. `create_task` — clear title, acceptance criteria in description
2. `start_working_on` — marks session focus
3. Execute — small, single-purpose changes only
4. **Verify with evidence** — Playwright screenshot, DB query result, API response, or code read
5. `log_decision` — if any architectural choice was made
6. `complete_task` — verification notes: what was checked, what evidence showed
7. `update_project_understanding` — after each phase completes

**Rule:** No task is marked complete without verification evidence. Not "it should work" — the actual output.

---

## Phases

### Phase 0: Housekeeping (Immediate)
**Goal:** Clean slate for Claude sessions

| Task | Details | Verify |
|------|---------|--------|
| Fix permissions | Add Read/Edit/Write/Glob/Grep/Bash/WebFetch/MCP to settings | No more permission prompts in next session |
| Clean MEMORY.md | Strip stale "recovery mode" claims, align with current reality, trim to ~80 lines | Read MEMORY.md, confirm no contradictions |
| Audit CLAUDE.md | Check rules match current codebase state | Read rules files, spot-check claims |

### Phase 1: Fix Broken MCP Tools (30 min)
**Goal:** Restore Claude's ability to search knowledge and learn from mistakes

| Task | Details | Verify |
|------|---------|--------|
| Fix `search_mistakes` | Find SQL query in MCP server, check against actual `knowledge_base` schema, fix column reference | Call `search_mistakes`, confirm results returned |
| Fix `search_knowledge_brief` | Same — fix `importance` column reference | Call `search_knowledge_brief`, confirm results returned |
| Check other MCP tools | Scan for any other tools with stale schema references | Call each tool category, confirm no errors |

**Why first:** If Claude can't search past mistakes, it will repeat them. This restores the learning loop.

### Phase 2: Bridge Dispatcher — Hub-Only Stabilization (2-4 hours)
**Goal:** All 20 hub agents can be dispatched reliably, ignoring nodes

| Task | Details | Verify |
|------|---------|--------|
| Audit agent states | Query `agents` table: how many active, deployed, barracked? Do states match expectations? | DB query results match MEMORY.md roster claims |
| Trace dispatch path | Read `bridge_dispatcher.py` dispatch() → smart_router.py → agent selection. Document the flow. | Written trace in task notes |
| Isolate node interference | Check if node_agents entries are polluting hub dispatch pool. If so, identify where. | DB query showing clean separation |
| Fix hub dispatch | Apply targeted fix based on trace findings | Dispatch a test job via `/api/bridge`, confirm agent receives and completes it |
| Verify Starbase manifest | Load Starbase Command, compare Active Roster display vs DB state | Playwright screenshot matching DB query |

**Key principle:** Get hub agents dispatching first. Nodes come in Phase 3.

### Phase 3: Node Fleet Re-integration (2-4 hours)
**Goal:** Node agents rejoin dispatch pool, cluster operates as designed

**Depends on:** Phase 2 complete and verified

| Task | Details | Verify |
|------|---------|--------|
| Audit node state | Check `remote_nodes`, `node_agents` tables. What does DB think fleet looks like? | DB query results documented |
| Check actual node | Query node heartbeat, Ollama /api/tags, verify node is actually running | curl to node IP, response documented |
| Reconcile DB with reality | Fix any stale entries — offline nodes marked online, ghost agents, etc. | DB queries before/after |
| Re-add node to dispatch | Update node_agents status, verify Bridge can route to node | Dispatch test job to node agent, confirm execution |
| Verify model sync | Check model_load_state table matches actual loaded models on hub + node | Compare DB vs Ollama /api/ps on both hosts |

### Phase 4: Starbase Command & Manifest Verification (1-2 hours)
**Goal:** Management UI accurately reflects cluster state, load/unload works

**Depends on:** Phase 3 complete and verified

| Task | Details | Verify |
|------|---------|--------|
| Manifest accuracy | Compare Starbase Active Roster display vs DB vs actual Ollama state | Side-by-side comparison documented |
| Load/unload test | Load a model through Starbase UI, confirm Ollama actually loads it | Playwright: click load → check /api/ps |
| Node management | View node in Starship tab, verify stats/agents/models display correctly | Playwright screenshot of node detail |
| Station panels | Check all 10 station panels show correct agents | Playwright screenshots |

### Phase 5: Downstream Module Re-enablement (1-2 hours per module)
**Goal:** Disabled modules come back online one at a time

**Depends on:** Phase 4 complete and verified

| Task | Details | Verify |
|------|---------|--------|
| Re-enable module | Remove disable flag, restart container | Module loads without errors in docker logs |
| Test core dispatch | Trigger the module's primary Bridge dispatch action | Job completes, result displayed in UI |
| Log status | Record working/broken/needs-more-work in Dev HQ | Task notes with evidence |

**Module re-enablement order** (simplest first):
1. Media Hub (already "working" — just verify)
2. Consciousness (already "working" — verify Code Health tab)
3. Dev Pipeline (scan/proposal should work if Bridge works)
4. CRM (simple dispatch)
5. Invoicing (simple dispatch)
6. Store Builder
7. Website Designer
8. Content Studio
9. Social Media
10. Call Center
11. StockBot (most complex — 5 agents, needs Modelfiles)
12. Evaluation Design

---

## Success Criteria

1. All MCP tools return valid results (no schema errors)
2. Hub agents dispatch and complete jobs reliably
3. Node agents dispatch and complete jobs on remote hardware
4. Starbase Command manifest matches DB matches reality
5. At least 8 of 10 disabled modules re-enabled and verified
6. MEMORY.md accurately reflects current state
7. Every fix has a Dev HQ task with verification evidence
8. Consciousness Code Health tab reflects current codebase state

---

## Anti-Patterns (DO NOT)

- Do NOT work on multiple phases simultaneously
- Do NOT claim a task is done without verification evidence
- Do NOT start new features until all 5 phases complete
- Do NOT use subagents for critical fixes (they produce unverified code)
- Do NOT modify code without reading it first
- Do NOT skip Dev HQ tracking for "quick fixes"
- Do NOT trust MEMORY.md claims — verify against current state

---

## Post-Stabilization

Once all 5 phases are verified:
1. Update MEMORY.md to reflect stable state
2. Unfreeze pending tasks, re-prioritize
3. Resume normal development cadence (with verification discipline)
4. Consider adding a PostToolUse hook that reminds to verify after Edit/Write operations
5. Explore Consciousness → Dev Pipeline self-improvement loop (the original vision)
