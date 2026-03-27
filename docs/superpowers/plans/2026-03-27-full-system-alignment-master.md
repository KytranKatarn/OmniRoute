# Full System Alignment — Master Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the 10-station model, fully adopt 16 departments, complete C.R.E.E.D. governance, wire the self-healing repair pipeline, and add agent work tracking with performance portfolios.

**Architecture:** 8 sequential workstreams, each producing a deployable increment. Each workstream has its own detailed plan written just before execution (to reflect codebase state at that point).

**Tech Stack:** Python/Flask, PostgreSQL, LCARS CSS, vanilla JS, Bridge dispatcher, APScheduler agent loop

---

## Workstream Sequence

| # | Workstream | Depends on | Sessions est. | Detailed plan |
|---|-----------|------------|---------------|---------------|
| 1 | Station → Department Hard Cutover | None (foundation) | 2-3 | `2026-03-27-ws1-department-cutover.md` |
| 2 | Department HQ Module | WS1 | 2-3 | Written after WS1 |
| 3 | C.R.E.E.D. Completion | WS1 | 1-2 | Written after WS2 |
| 4 | Repair Pipeline Completion | WS1, WS3 | 1-2 | Written after WS3 |
| 5 | Consciousness Cleanup | WS1 | 1-2 | Written after WS4 |
| 6 | Starbase Refocus | WS1, WS2 | 1 | Written after WS5 |
| 7 | Telegram Realignment | WS1 | 1 | Written after WS6 |
| 8 | Agent Work Tracking | WS1, WS2 | 2-3 | Written after WS7 |

## Completion criteria per workstream

**WS1:** All station references removed from dispatch path. Agents route by department only. DB migration applied. Platform restarts cleanly.

**WS2:** Department HQ module at `/tools/department-hq` with 6 tabs. Registered in module_registry + rbac. DepartmentOps component replaces StationOps. New DB tables (work_sessions, department_metrics) created.

**WS3:** Zero IAAE references in ai_bridge/. Orchestration uses `_step_creed_check()`. Self-healing Gate 1 + Gate 2 implemented. `/creed` page shows repair transparency.

**WS4:** File path bug fixed. Tasks 1459-1462 complete. Full pipeline: audit → propose → Gate 1 → dispatch → fix → Gate 2 → sandbox → deploy → re-audit. Weekly orchestrator running.

**WS5:** `routes.py` split (7764 → ~400 lines). `github_routes.py` split (2679 → 3 files). All Consciousness jobs department-attributed.

**WS6:** Station panels, agent roster, StationOps removed from Starbase. `crew_routes.py` → `model_routes.py`. Starbase is fleet/hardware only.

**WS7:** Escalation chain uses department→floor→cross-floor→fleet→cloud. Messages department-formatted. Daily digest department-aware.

**WS8:** Work sessions created for all Bridge dispatches. Job #59 (metrics rollup) running. Department KPIs computed. AI Director dashboards showing data. `agent_loop_cycles` has department column.

## Dev HQ project

All workstreams tracked under **Project #199** (expanded scope) or a new umbrella project. Each workstream creates tasks via MCP at start, completes them as work finishes.
