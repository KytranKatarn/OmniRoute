# Consciousness Module Health Check — Design Spec

**Date:** 2026-03-23
**Project:** #180 — Consciousness Module Health Check
**Related:** #181 — Claude Playwright Skill (future)
**Status:** Approved by user

---

## Problem Statement

The Consciousness module (111 routes, 86 JS functions, 126KB template, 9+ services and helper files) has never had a health check. Loop/job controls are scattered across tabs instead of living in the Autonomy module where they belong. No prior audit exists in the knowledge base.

**Note:** `team_routes.py` still exists on disk but was removed from `__init__.py` — Team tab was merged into Starbase Command Crew tab. The module currently renders **4 active tabs** (Dashboard, Knowledge, GitHub, Languages) plus Code Health. Actual tab count to be confirmed during browser testing.

## Goals

1. **Code review** — Find bugs, dead code, security issues, and quality problems
2. **Browser test** — Verify all 5 tabs load and function correctly
3. **Loop migration** — Move loop/job controls from Consciousness to Autonomy module
4. **UI cleanup** — Remove orphaned loop UI, simplify Consciousness
5. **Audit closure** — Update Project #180 tasks and ensure Code Health tab shows green

## Non-Goals

- No new features added to Consciousness
- No major layout/tab restructuring
- No rewrite of routes.py (surgical fixes only)
- No changes to GitHub ingest UI (stays in Consciousness)

---

## Design

### Section 1: Code Review & Health Check

**Scope:** Full audit of all Consciousness module code.

**Files to review:**
| File | Size | Focus |
|------|------|-------|
| `tools/consciousness/routes.py` | 7,592 lines | Dead routes, security, error handling |
| `tools/consciousness/knowledge_routes.py` | — | DB query safety, connection leaks |
| `tools/consciousness/github_routes.py` | 80KB | Ingestion bugs, error handling |
| `tools/consciousness/insights_routes.py` | — | Analytics correctness |
| `tools/consciousness/team_routes.py` | — | **DEAD CODE** — not imported in `__init__.py`, verify safe to remove |
| `tools/consciousness/integration_routes.py` | — | DevHQ integration health |
| `tools/consciousness/code_health_routes.py` | — | Scan accuracy |
| `tools/consciousness/processing_routes.py` | 57KB | Embedding/loop logic. **NOTE:** Nested Blueprint pattern (`consciousness_bp.register_blueprint(processing_bp)`) — different from standard `register_*_routes` pattern |
| `static/js/consciousness.js` | 3,356 lines | Memory leaks, broken API calls, orphaned functions |
| `templates/consciousness_dashboard.html` | 126KB | Dead HTML, broken references |

**Additional helper files to review (non-route, non-service):**
| File | Focus |
|------|-------|
| `collaboration_engine.py` | Business logic health |
| `claude_bridge.py` | Bridge integration |
| `dependency_scanner.py` | Scanner accuracy |
| `learning_extractor.py` | Extraction logic |
| `log_ingestor.py` | Log processing |
| `memory_service.py` | Memory management |
| `voice_pregen.py` | Voice pre-generation |

**Method:** Parallel code review agents across route files, JS, and services.

**Output:** Triaged findings list (critical / high / medium / low).

### Section 2: Browser Testing All 5 Tabs

**Target:** http://192.168.1.200:3000/tools/consciousness

**Tabs:**
1. **Dashboard** — Neural Core viz, header stats, loop monitor grid
2. **Knowledge** — Knowledge browser, embedding coverage, ingest button
3. **GitHub** — Repo list, reindex controls, semantic search
4. **Languages** — Translation coverage, scan/generate buttons
5. **Code Health** — Codebase scan, audit log, orphan detection

**Method:** Direct Playwright script (not MCP) — navigate each tab, screenshot, capture console errors, verify API responses return 200s.

**Credentials:** See `frontend.md` testing section.

**Output:** Pass/fail per tab with screenshots and error logs.

### Section 3: Loop Control Migration (Consciousness → Autonomy)

**Controls that move to Autonomy:**
| Control | Source Tab | Target |
|---------|-----------|--------|
| Server loop toggle | Dashboard | Autonomy → Active Jobs |
| Loop Monitor grid | Dashboard | Autonomy → Active Jobs |
| Embedding generation start/stop | Knowledge | Autonomy → Active Jobs |
| Code health scan trigger | Code Health | Autonomy → Active Jobs |
| Translation generation job trigger | Languages | Autonomy → Active Jobs |

**Controls that stay in Consciousness:**
- GitHub REINDEX ALL / INDEX SELECTIVE (knowledge-centric)
- All read-only status indicators (embedding %, coverage bars, scan results)
- Knowledge browser, search, graph

**Autonomy module changes:**
- Active Jobs tab gets per-job start/stop/status cards
- Each card shows: job name, status, last run, next run, start/stop button
- Existing APScheduler integration already reads jobs — add UI controls per job
- New API endpoints: `POST /api/ops-active-jobs/<job_id>/toggle` for per-job control

**Server-side migration (critical):**
- Migrate `startup_resume_loops()` from Consciousness `__init__.py` to Autonomy startup path — without this, loops won't auto-resume after `docker compose restart`
- `processing_routes.py` uses nested Blueprint pattern — migration must account for URL prefix changes (consumers of `/api/processing/*` endpoints need updating)
- Update `action_registry` entries for migrated controls (`consciousness.analysis.start`, `consciousness.embeddings.generate`) to point at new Autonomy endpoints

**Consciousness JS cleanup:**
- Remove: `_startLoopMonitor()`, `_stopLoopMonitor()`, `_syncServerLoop()`, `_loadLoopState()`, `_saveLoopState()`
- Remove: scattered `setInterval` polling timers for job status
- Keep: read-only status fetches (lightweight, no controls)

**Autonomy DB note:** `ops_routes.py` defines its own local `get_db()` — new endpoints should use the shared `database.py` pattern instead.

### Section 4: UI Cleanup

**Per-tab changes:**
1. **Dashboard** — Remove Loop Monitor grid section. Neural Core + header stats get more space.
2. **Knowledge** — Remove INGEST start/stop button. Keep read-only embedding coverage bar.
3. **Languages** — Remove GENERATE/SCAN AND SEED buttons. Keep coverage display.
4. **Code Health** — Remove SCAN CODEBASE/BACKFILL buttons. Keep results display.
5. **GitHub** — No changes.

**No new tabs. No layout restructuring. Just removing controls that now live in Autonomy.**

### Section 5: Audit Closure & Verification

**After all changes:**
1. Re-run Playwright browser test — all 5 tabs must pass
2. Run Code Health scan from Autonomy — verify Consciousness shows green
3. Complete Project #180 tasks with verification notes via MCP
4. Log architectural decision for loop migration via MCP
5. Store any mistakes learned during the process

---

## Execution Order

| Step | Action | Commit |
|------|--------|--------|
| 1 | Code review (parallel agents) | No commit — findings only |
| 2 | Triage findings, decide fixes | No commit — decision |
| 3 | Browser test 5 tabs | No commit — evidence |
| 4 | Fix critical/high bugs found | Commit per fix |
| 5 | Loop migration: extract from Consciousness | Commit |
| 6 | Loop migration: wire into Autonomy | Commit |
| 7 | UI cleanup: remove orphaned loop UI | Commit |
| 8 | Verify: re-run browser test + code health scan | No commit — evidence |
| 9 | Audit closure: complete tasks, log decisions | MCP calls |

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| `routes.py` is 7,592 lines — easy to break | Surgical edits only, no rewrites |
| 126KB template — large blast radius | Test after every change |
| Loop migration may break Autonomy | Test both modules after wiring |
| Blueprint template path gotcha (ADR-021) | Keep `template_folder="templates"` — never remove |
| `processing_routes.py` nested Blueprint pattern | Account for URL prefix changes during migration |
| `startup_resume_loops()` must move with loop controls | Relocate to Autonomy startup path |

## Rollback Plan

If migration fails verification at Step 8, revert commits from Steps 5-7 via `git revert`. The original Consciousness controls remain functional until the migration commits land successfully.

## Known Constraints

- Blueprint template path gotcha (ADR-021) — Consciousness has its own `templates/` subdir, must keep `template_folder="templates"` set in Blueprint constructor.
- `team_routes.py` is dead code (not imported) — candidate for removal during code review.
- `processing_routes.py` uses nested Blueprint — different migration approach than standard route files.
