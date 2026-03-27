# Full System Alignment — Design Spec

**Date:** 2026-03-27
**Status:** Approved
**Scope:** Platform-wide realignment — stations to departments, C.R.E.E.D. completion, self-healing pipeline, agent work tracking
**Effort:** Multi-session (8 workstreams)
**Priority order:** 1→2→3→4→5→6→7→8

---

## Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Scope | Wide — full system alignment | Station/department dual model creates inconsistencies everywhere |
| Starbase role | Fleet/infrastructure only — no departments | Clean separation of concerns |
| Department management | New "Department HQ" module (B) | Consciousness already too large |
| Station removal | Hard cutover (A) — no legacy | Clean break, no dual-model debt |
| C.R.E.E.D. governance | Full lifecycle (C) — gate on generate AND apply | Self-modifying AI needs strongest governance |
| Telegram role | Human approval channel (A) — department-aware | Keeps phone-based approvals, reduces noise |
| Autonomy module | Stays as-is (A) — engine room for all jobs | Well-named, well-scoped infrastructure |
| Agent work tracking | Full performance portfolio (C) — sessions, KPIs, director dashboards | AI Directors own department outcomes |
| Job attribution | ALL jobs get department ownership | Every job traceable to a department |

---

## Workstream 1: Station → Department Hard Cutover

### Database changes
- Drop `station_assignments` table
- Drop `station_code` column from `agents` (or deprecate)
- Remove `idx_station_assignments_one_per_agent` constraint
- Add `department` column constraint: one of 16 valid department names
- Add `floor` column (derived): BRIDGE, OPERATIONS, ENGINEERING, CREATIVE, SERVICES

### Bridge Dispatcher (`bridge_dispatcher.py`)
- Remove `CAPABILITY_STATION_MAP` — `CAPABILITY_DEPARTMENT_MAP` is sole routing map
- Remove `STATION_TO_DEPARTMENT` / `DEPARTMENT_TO_STATION` lookups
- `_select_agent()` takes `department` instead of `station_code`
- Agent scoring uses `agents.department` directly
- `_find_fleet_agent()` queries by department

### Smart Router (`smart_router.py`)
- `_resolve_department()` is already primary — remove station fallback
- Remove station-based capacity limits, replace with department-based

### Orchestration Engine
- Station references become department references

### Agent Loop
- All station references → department
- Fleet health uses department

### Migration strategy
- Single migration SQL: add constraints, backfill department from station mapping, drop station columns
- Python code deployed simultaneously
- Rollback: keep station columns nullable for 1 session, drop in follow-up

---

## Workstream 2: Department HQ Module

### File structure
```
platform_v2/tools/department_hq/
├── __init__.py              — Blueprint registration, register_*_routes
├── routes.py                — Dashboard, org chart, floor views
├── roster_routes.py         — Agent CRUD, assignments, shift management
├── work_routes.py           — Work sessions, job tracking, performance
├── creed_routes.py          — Per-department C.R.E.E.D. compliance
├── templates/
│   └── department_hq.html   — Single-page with tabs
├── static/
│   ├── css/department-hq.css
│   └── js/department-hq.js
```

### 6 Tabs

| Tab | Content |
|-----|---------|
| Overview | Floor map, department cards, health badges, active work count |
| Org Chart | 5 floors → 16 departments → AI Director + staff tree |
| Roster | Agent list with filters, assign/reassign, shift management |
| Work Tracking | Active work sessions, job history, session drill-down |
| Performance | Per-department KPIs, AI Director dashboards, proficiency trends |
| C.R.E.E.D. | Per-department compliance score, violations, welfare alerts, audit trail |

### New DB tables

**`work_sessions`**
```sql
id SERIAL PRIMARY KEY,
agent_id INTEGER REFERENCES agents(id),
department VARCHAR NOT NULL,
session_type VARCHAR NOT NULL,  -- audit, fix, analysis, translation, etc.
title VARCHAR NOT NULL,
status VARCHAR NOT NULL DEFAULT 'active',  -- active/completed/failed/partial
started_at TIMESTAMP DEFAULT NOW(),
ended_at TIMESTAMP,
jobs_completed INTEGER DEFAULT 0,
jobs_failed INTEGER DEFAULT 0,
tokens_used INTEGER DEFAULT 0,
metadata JSONB DEFAULT '{}'
```

**`department_metrics`**
```sql
id SERIAL PRIMARY KEY,
department VARCHAR NOT NULL,
period_start TIMESTAMP NOT NULL,
period_end TIMESTAMP NOT NULL,
jobs_completed INTEGER DEFAULT 0,
jobs_failed INTEGER DEFAULT 0,
avg_response_ms INTEGER,
tokens_used INTEGER DEFAULT 0,
kpis JSONB DEFAULT '{}',  -- department-specific metrics
creed_score DECIMAL(5,2),
computed_at TIMESTAMP DEFAULT NOW()
```

### Department-specific KPIs (in `kpis` JSONB)

| Department | KPIs |
|-----------|------|
| Engineering & Technology | proposals_deployed, code_quality_delta |
| Security & Compliance | vulns_found, vulns_patched, compliance_pass_rate |
| Research & Development | kb_entries_created, embeddings_generated |
| Documentation & Knowledge | skills_discovered, repos_indexed |
| Human Resources & Culture | welfare_alerts_resolved, avg_agent_energy |
| Communications | notifications_sent, approvals_processed |
| Analytics & Intelligence | metrics_computed, reports_generated |
| Operations & Infrastructure | uptime_percent, fleet_health_score |

Others start with generic KPIs (jobs_completed, success_rate) — specific ones added as patterns emerge.

### Registration
- `module_registry.py` — category: `AI_COMMAND`
- `rbac.py` — admin access
- Route: `/tools/department-hq`
- UI: LCARS aesthetic, DepartmentOps component, responsive 480/768/1024px

---

## Workstream 3: C.R.E.E.D. Completion + Self-Healing Governance

### Part A: IAAE → C.R.E.E.D. Rename (53 references)

**ai_bridge/ changes:**
- `orchestration_engine.py`: `_step_iaae_check()` → `_step_creed_check()`, `IAAE_CHECK` → `CREED_CHECK`
- `ethics_monitor.py`: Module docstring and class references
- `bridge_dispatcher.py`: Comments "IAAE GOVERNANCE" → "C.R.E.E.D. GOVERNANCE"
- `agent_loop.py`: Job docstrings and method names
- `mission_manager.py`, `archie_bridge.py`: All IAAE references

**No DB changes** — tables use generic names (governance_audit_log, ethics_constraints, ethics_alerts).
**Public page** — already at `/creed`.

### Part B: Self-Healing Pipeline Governance

**Gate 1 — Pre-fix generation (before Bridge dispatch):**
- Constraint: "no self-modification" — agent can't fix code in its own module
- Welfare: stress < 0.8, energy > 0.2
- Capability: agent has skill for this issue type
- Log: governance_audit_log action=fix_generation_requested
- Denied → proposal stays pending, reason logged, Telegram if security

**Gate 2 — Pre-apply (before fix deployed):**
- Scope: diff only touches target file(s)
- Director approval: AI Director of owning department reviews
- Red fixes: Tier 2 (human via Telegram)
- Yellow fixes: Tier 1 (AI Director auto-approve if diff < 50 lines)
- Log: governance_audit_log action=fix_apply_requested
- Full trail: who found, who fixed, who approved, when applied

### Part C: C.R.E.E.D. Public Transparency

`/creed` page gains Repair Transparency section:
- Issues found this period
- Fixes generated / approved / rejected / deployed
- Agents involved, department breakdown
- Gate denial reasons
- All read-only, no auth

### Part D: New governance event types
- `repair_scan_completed`
- `repair_fix_generation_approved` / `_denied`
- `repair_fix_generated`
- `repair_fix_apply_approved` / `_denied`
- `repair_fix_deployed`
- `repair_fix_rolled_back`

---

## Workstream 4: Repair Pipeline Completion

### Bug fix: File path construction
`audit_single_module` `_add_issue()` must store relative path from module root, not just filename. Fixes: `knowledge_service.py` → `services/knowledge_service.py`.

### Task 1459 (Bridge dispatch)
- Already built, needs C.R.E.E.D. Gate 1 integration
- Department-based routing post-cutover
- Fix file paths in existing proposals

### Task 1460 (Re-audit loop)
After fix deployed → `audit_single_module` on affected module → compare before/after → log `repair_fix_verified` or `repair_fix_regression`. Regression → auto-rollback + Telegram alert.

### Task 1461 (Weekly orchestrator — Job #58 expansion)
```
1. audit_single_module() on all modules
2. process_audit_findings() → create proposals (dedup)
3. C.R.E.E.D. Gate 1 per proposal
4. dispatch_audit_proposals() → Bridge routes to department agents
5. Agents generate fixes → diffs on proposals
6. C.R.E.E.D. Gate 2 → approve/deny
7. Sandbox test passing fixes
8. Deploy → re-audit → verify
9. Log cycle to governance_audit_log
10. Telegram summary
```

### Task 1462 (Dashboard integration)
- Consciousness Code Health: severity-colored badges (red/yellow/green)
- Department HQ Work Tracking: repair sessions by department
- Department HQ C.R.E.E.D.: gate approvals/denials
- C.R.E.E.D. public page: Repair Transparency section
- Autonomy: repair cycle status in job monitoring

### Pipeline flow
```
Audit → Severity Classification → Proposal Creation
  → C.R.E.E.D. Gate 1 → Bridge Dispatch → Agent Fix
    → Diff Generation → C.R.E.E.D. Gate 2
      → Sandbox Test → Deploy → Re-audit → Verify
        → Rollback + Alert  OR  Mark Green
          → governance_audit_log + Telegram summary
```

---

## Workstream 5: Consciousness Cleanup

### File splits

**`routes.py` (7764 → ~400 lines):**
- Extract `dashboard_routes.py` — Dashboard tab endpoints
- Extract `language_routes.py` — 17 translation endpoints (lines 6159-7742)
- `routes.py` remains as coordinator

**`github_routes.py` (2679 → ~3 files):**
- `github_repo_routes.py` — Repo indexing, file browsing, status
- `github_skill_routes.py` — Skill discovery, analysis, pipeline
- `github_insights_routes.py` — Dependencies, competitors, stats

**Leave for now:** `processing_routes.py` (1472), `knowledge_routes.py` (955) — focused, manageable.

### Job updates
- Job #41 (GitHub skill analysis): dispatch by department
- Job #51 (Code health digest): department-aware summary
- All other Consciousness jobs: add department attribution to cycle logs

---

## Workstream 6: Starbase Refocus

### Remove from Starbase
- 10 station panels (StationOps components)
- Agent roster / crew manifest
- Agent profile modals
- Station commands and actions
- Shift management UI

### Keep in Starbase
- Fleet overview — hub, nodes, hardware
- Node management — connect/disconnect, setup
- Model management — load/unload, VRAM/RAM, tiers
- OTA/Sync — updates, model pulls
- Fleet health — heartbeat, uptime, resources

### File changes
- Remove: `station_routes.py`, `agent_routes.py`
- Rename: `crew_routes.py` → `model_routes.py` (keep model-control, strip agent roster)
- Keep: `routes.py`, `node_routes.py`, `mesh_routes.py`
- Deprecate: `station-ops.js` / `station-ops.css` → replaced by DepartmentOps in Department HQ

---

## Workstream 7: Telegram Realignment

### Escalation chain rewrite
```
Old: home station → capability → cross-station → fleet → cloud
New: home department → same-floor → cross-floor → fleet → cloud
```

### Message format — department-aware
```
[DEPARTMENT] Alert Type — Details
Agent: NAME (Department)
Severity / C.R.E.E.D. status
Action needed
[Approve] [Deny] [Defer]
```

### Alert routing by department

| Alert | Owner | Tier |
|-------|-------|------|
| Security vuln found | Security & Compliance | 2 (human) |
| Red fix deploy | Engineering & Technology | 2 (human) |
| Yellow fix deploy | Engineering & Technology | 1 (AI Director) |
| C.R.E.E.D. violation | Executive Office | 2 (human) |
| Welfare critical | Human Resources & Culture | 1 (AI Director) |
| Cloud escalation (cost) | Executive Office | 2 (human) |
| Repair cycle summary | Engineering & Technology | Info |
| Daily department digest | All departments | Info |

### Daily digest format
Department-by-department summary: jobs run, fixes deployed, pending reviews, welfare status, C.R.E.E.D. score.

---

## Workstream 8: Agent Work Tracking + Performance Portfolios

### Work sessions
Every meaningful work unit creates a session grouping related Bridge jobs.

**Lifecycle:** Created → Active → Completed / Failed / Partial

**Created by:**
- `dispatch_proposal_fix()` → fix session
- `dispatch_audit_proposals()` → batch audit session
- `_automated_module_audit()` → weekly cycle session
- Any Bridge dispatch with `job_id` → auto-creates/appends

### Performance metrics

**New Job #59: Department metrics rollup** (daily 2:00 AM, owned by S.P.E.C.T.R.A.)

Per department for 24h / 7d / 30d:
- jobs_completed, jobs_failed, success_rate
- avg_response_ms, tokens_used
- sessions_completed, creed_score

### All 64 jobs — department attribution

| Department | Jobs owned |
|-----------|-----------|
| Operations & Infrastructure (B.A.S.E.) | Fleet health, model state, heartbeat, backup, monitoring |
| Engineering & Technology (F.O.R.G.E.) | Code health audit, repair pipeline, proactive scan, pattern compliance, sandbox |
| Security & Compliance (V.I.G.I.L.) | Compliance scans, DNS, SSL, security scanning |
| Research & Development (D.A.R.W.I.N.) | Knowledge dedup, conversation indexing, consciousness analysis, embeddings, git tracking |
| Documentation & Knowledge (C.O.D.E.X.) | GitHub skill analysis, skill sync, competitor scanning, repo indexing |
| Marketing & Communications (S.I.G.N.A.L.) | Telegram notifications, daily digests, alert routing |
| Analytics & Intelligence (S.P.E.C.T.R.A.) | Code metrics snapshots, department metrics, performance rollups |
| Human Resources & Culture (K.I.N.) | Welfare recovery, training ticks, shift management, rest cycles |
| Executive Office (A.R.C.H.I.E.) | Approval queue, escalation management |
| Creative & Design (M.U.S.E.) | Translation jobs, content generation |

**`agent_loop_cycles` table:** Add `department` column, auto-populated from `JOB_DEPARTMENT_MAP`.

### AI Director accountability
Each Director's profile shows: department led, staff count, aggregate performance, C.R.E.E.D. compliance, active sessions. All department work rolls up to their dashboard.

---

## What's NOT in scope
- Agent creation/deletion (collaborative, not automated)
- New agent acronyms or departments beyond the 16
- Cloud provider changes
- Subscription/billing changes
- Mobile app
- Node hardware changes
