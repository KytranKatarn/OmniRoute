# AI Command Integration & Finalization — Design Spec

**Date:** 2026-04-13
**Status:** Approved
**Approach:** Hybrid (Audit → Build Hub → Polish → QA)
**Strategy:** Inside-out from Department HQ
**Priority Order:** Backend (A) → Frontend (B) → Integration + QA (C)
**Related Projects:** #241 (K.I.N. lifecycle), #249 (Dev HQ merge), #236 (P.R.O.B.E. Phase 2), #254 (Visual Regression)
**Estimated Effort:** 4-6 focused sessions

---

## Scope

Full verification, integration, and finalization of all 5 AI Command modules:
- **Department HQ** (12 tabs, 265 endpoints, 3 core services)
- **Consciousness** (6 tabs, 155 endpoints, 8 services)
- **Repair Bay** (6 tabs, 101 endpoints, 15 services)
- **Agent Academy** (5 tabs, 16 endpoints)
- **A.R.C.H.I.E. Chat** (5 tabs, 16 endpoints)

### Definition of Done
1. Every tab in every module has working frontend AND backend
2. All modules talk to each other through verified paths
3. P.R.O.B.E. QA suites prove it all works with automated tests
4. No placeholder tabs — if it exists in UI, it works; if it can't work, remove it

### Out of Scope
- Non-AI-Command modules (Admin Ops, SaaS Services, Media, Crypto, Applications)
- Fleet/Starship node deployment (no nodes online)
- New feature development — this is verification and integration of what exists

---

## Phase A — Backend Audit & Verification (1-2 sessions)

Goal: Know the truth. What works, what's broken, what's lying.

### A1: API Endpoint Sweep
- Hit every `/api/` route across all 5 modules
- Log: status code, response time, data shape
- Flag: 500s, timeouts, empty responses, missing auth
- Estimated: ~553 endpoints total

### A2: Dispatch Pipeline E2E
- Send a real request through Bridge Dispatcher
- Verify full chain: intent parse → model select → agent match → welfare check → execute → log
- Test: `dispatch()`, `dispatch_json()`, `get_dispatcher()` module-level functions
- Verify: an agent actually receives and responds to the request
- Test: escalation chain (home → capability → cross-department → fleet → cloud)

### A3: Agent Loop Job Audit
- Inventory all 90 APScheduler jobs
- Check: last run time, success/failure, next scheduled run
- Flag: jobs that haven't run in >24h, jobs with 100% fail rate, stuck jobs
- Verify: job output is meaningful (not just logging "completed" without doing work)
- Cross-reference with `autonomy_loop_log` table

### A4: Agent Lifecycle Verify (coordinates with Project #241)
- Confirm `agent_service.py` is the single writer to `agents` table
- Verify: Org Chart data == Roster data == Dispatch crew manifest
- Test: create_agent, update_agent, shift_state changes, deploy_to_node
- Verify: model assignments match actual Ollama loaded models (ghost model prevention)
- Check: skills, welfare, performance metrics all flow through agent_service

### A5: Knowledge Pipeline Verify
- Consciousness loops: embedding (every 30min), analysis (every 30min), translate
- Check: are they running? Producing results? Not erroring silently?
- Verify: `search_knowledge` returns relevant results (not garbage)
- Check: embedding coverage (currently 99.1% — is it real?)
- Verify: `store_memory`, `recall_context` work end-to-end

### A6: Repair Bay Pipeline Verify
- Test full chain: Scan → Proposal → Sandbox → Deploy
- Check: Can a scan run and produce findings?
- Check: Do proposals generate from findings?
- Check: Does sandbox_manager create and execute sandboxes?
- Verify: QA spec runner executes suites and stores results
- Audit: 307 existing proposals — are they real or ghost data?

### Output
JSON health report stored in KB. Categorized pass/fail per track. This report feeds Phase A.5 Overview design.

---

## Phase A.5 — DHQ Overview Redesign (1 session)

Goal: Build the bridge command screen using verified backend data.

### Layout: Executive Bridge + Attention Signals

**Top Row — Hero Stats (6 cards):**
| Stat | Source | Update Frequency |
|------|--------|-----------------|
| Agents Online | `agent_service` shift_state counts | Live (on page load) |
| Models Loaded | Ollama `/api/ps` | Live |
| Jobs 24h | `bridge_jobs` table count | Live |
| Success Rate | `bridge_jobs` completed vs failed | Live |
| Open Findings | `scan_results` open count | Live |
| KB Entries | `knowledge_base` count | Live |

**Middle — Attention Needed Section:**
- Aggregates alerts from all modules into priority-sorted list
- Sources: failed jobs, high-stress agents (>70%), critical scan findings, failed QA runs, stale agent loop jobs (>24h no run), low-energy agents
- Each item links to the relevant tab/module
- Color-coded: red (critical), yellow (warning), green (info)
- Max 8 items shown, "View all" link for overflow

**Bottom — Condensed Department Grid:**
- 5 floor cards (BRIDGE, OPERATIONS, ENGINEERING, CREATIVE, SERVICES)
- Each shows: agent count, active count, jobs 24h (one line per floor)
- Color-coded left border matching floor accent color
- Compact 2-3 column responsive grid (vs current full-width stat blocks)

### New API Endpoint
`GET /api/overview-stats` — single aggregation endpoint that collects:
- Agent shift state counts from agent_service
- Bridge job stats from bridge_jobs table
- Scan findings count from scan_results
- QA latest run status from qa_test_runs
- Agent welfare alerts from agent_emotional_state
- Agent loop job health from autonomy_loop_log
- Knowledge stats from knowledge_base

This endpoint is the integration test — if it returns complete data, all source modules are working.

---

## Phase B — Frontend Polish (1-2 sessions)

Goal: Every tab loads, every button works, no placeholders.

### Department HQ (12 tabs)
- **Overview**: Redesigned in Phase A.5
- **Org Chart + Roster**: Verify same data source (agent_service), profile modal fixed (done today)
- **Work Tracking**: Enrich with more session detail, verify data loads
- **Performance**: Verify metrics are real (not all zeros)
- **C.R.E.E.D.**: Verify governance events load, welfare data accurate
- **Social**: Check if social feed works or needs wiring
- **Devices**: Verify device registry loads
- **Dispatch**: Verify job list, Ollama stats, active jobs display
- **Fleet**: Verify map loads, node status accurate
- **Contractors**: Verify provider list, enable/disable works
- **Approvals**: Verify approval workflow end-to-end

### Consciousness (6 tabs)
- **Dashboard**: HoloSphere renders, stats accurate
- **Dev HQ**: Complete merge from Project #249 if not done
- **Knowledge**: Browser, Categories, Embeddings, Graph all load
- **GitHub**: Repo indexing works, skill extraction functional
- **Languages**: Translation pipeline status accurate
- **Code Health**: Scanner results current, module coverage accurate

### Repair Bay (6 tabs)
- **Reviews**: Overview stats match actual data
- **Repairs/Proposals**: List loads, approve/reject works
- **Diagnose/Scan**: Scanner runs, file browser loads, severity badges accurate
- **Test Bay/Sandbox**: Sandbox creation works, test runner executes
- **Ship/Deploy**: Deployment history loads, ready-to-deploy queue works
- **QA**: Suite selector works, Run Now executes, results display, PDF report generates

### Agent Academy (5 tabs)
- **Benchmarks**: Can run a benchmark against a real agent
- **Training**: Skill assignment works, skill gaps calculate correctly
- **Models**: Agent model cards display, department filter works
- **A/B Testing**: Can run a comparison between two models
- **Knowledge**: System prompts display correctly per department

### A.R.C.H.I.E. Chat (5 tabs)
- **Chat**: Dispatch works, response streams, conversation persists
- **History/Collaboration/Claude TTY/Settings**: Decision — wire up or remove placeholder tabs. If core chat works well, placeholders can stay as roadmap markers. If they confuse users, remove.

---

## Phase C — Integration & QA Seal (1 session)

Goal: Cross-module flows verified. P.R.O.B.E. proves it. The system watches itself.

### Cross-Module Integration Paths

| Path | What to Verify |
|------|---------------|
| DHQ → Repair Bay | Overview shows open findings count, links to Diagnose tab |
| DHQ → Consciousness | Overview shows KB health, Code Health grade |
| DHQ → Academy | Roster skill levels match Academy training records |
| DHQ → Chat | Chat dispatches through Bridge, results logged in Dispatch tab |
| Repair Bay → Consciousness | Scan findings stored as KB entries, mistake_learned on fix |
| Academy → DHQ Dispatch | Benchmark scores influence capability routing in smart_router |
| Agent Loop → All | 90 scheduled jobs verified running, logged, monitored |
| Consciousness → Repair Bay | Code Health findings feed into Repair Bay scan sources |

### P.R.O.B.E. QA Suites (1 per module)
- **DHQ Critical Paths**: Overview loads, tabs switch, agent profile opens, dispatch endpoint responds
- **Consciousness Critical Paths**: Dashboard stats load, knowledge search works, embedding loop status
- **Repair Bay Critical Paths**: Scan runs, proposals list, sandbox creates, QA executes
- **Academy Critical Paths**: Benchmark runs, training assigns, model cards load
- **Chat Critical Paths**: Message sends, response received, conversation persists

### Automation
- Suites run on schedule via agent loop
- Failures alert via Telegram
- Results visible in Repair Bay QA tab
- Pass/fail history tracked for regression detection

---

## Coordination with Existing Projects

| Project | How It Fits |
|---------|------------|
| #241 Agent + Model Lifecycle (K.I.N.) | Phase A4 verifies single-writer. Complete remaining 44% of tasks during Phase A. |
| #249 Dev HQ → Consciousness Merge | Phase B Consciousness sweep completes remaining 14%. |
| #236 P.R.O.B.E. Phase 2 | Phase C builds QA suites. Advances this project. |
| #254 P.R.O.B.E. Visual Regression | Phase C stretch goal. Automated screenshot comparison. |
| #251 LCARS Header Standardization | Already done (shared nav). Mark complete. |
| #252 LCARS Content Frame Audit | Completed today. Mark complete. |

---

## Success Criteria

1. Backend health report shows >95% of endpoints passing
2. DHQ Overview loads with real data from all 5 connected systems
3. Every tab in every AI Command module loads without errors
4. Every button/action in every tab does something meaningful
5. 5 P.R.O.B.E. QA suites running on schedule with >90% pass rate
6. Cross-module integration paths all verified with evidence
7. A.R.C.H.I.E. CLI can dispatch work and get results through the full pipeline
