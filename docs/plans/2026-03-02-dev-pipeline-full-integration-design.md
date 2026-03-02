# Dev Pipeline Full Integration — Design Document

**Project**: #103 | **ADR**: TBD | **Date**: 2026-03-02
**Status**: Approved

## Goal

Migrate all business logic from Code Sentinel (1,555 lines), Improvements Lab (6,711 lines), and Sandbox Manager (1,899 lines) into shared services. Replace the current proxy pattern in Dev Pipeline with direct service calls. Remove old modules entirely. Add ENGINEERING station integration with Bridge Command for agent workload visibility and job progress tracking.

## Architecture

Service layer approach following the pattern established in Project #101 (knowledge_service.py, project_service.py). Route files stay thin (HTTP handling only). Station integration follows the Consciousness module pattern (checkActiveJobs, crew panel, job progress polling).

### Final File Tree

```
platform_v2/services/
├── __init__.py
├── scan_service.py           ← NEW (~600 lines, from Code Sentinel)
├── proposal_service.py       ← NEW (~1,200 lines, from Improvements Lab)
├── sandbox_service.py        ← NEW (~800 lines, from Sandbox Manager)
├── scan_pipeline.py          ← EXISTS (unchanged)
├── knowledge_service.py      ← EXISTS (unchanged)
└── project_service.py        ← EXISTS (unchanged)

platform_v2/tools/dev_pipeline/
├── __init__.py               ← EXISTS (unchanged)
├── routes.py                 ← EXISTS (minor updates)
├── scan_routes.py            ← REWRITE (proxy → service calls)
├── proposal_routes.py        ← REWRITE (proxy → service calls)
├── sandbox_routes.py         ← REWRITE (proxy → service calls)
├── deploy_routes.py          ← REWRITE (proxy → service calls)
└── station_routes.py         ← NEW (Bridge integration)

platform_v2/static/js/dev_pipeline.js  ← NEW (~1,000 lines)
platform_v2/templates/tools/dev_pipeline.html  ← EXISTS (updated)
```

## Service Layer

### scan_service.py (~600 lines)

Absorbs all business logic from Code Sentinel routes.py.

**Functions:**
- `check_ai_status()` — Ollama/Bridge availability check
- `static_analysis(code, path)` — Regex-based code analysis (Python/JS/HTML)
- `scan_file(file_path, user)` — AI + static scan, DB write, pipeline hook
- `batch_scan(file_paths, max_workers)` — Parallel static scans via ThreadPoolExecutor
- `get_stats()` — Scan/issue/fixer statistics
- `get_history(limit)` — Recent scan records
- `get_issues(status, limit)` — Issues with status filter
- `mark_fixed(issue_id, by, desc)` — Fix issue + create code_fixes record
- `get_fixes(limit)` — Fix history
- `get_file_health()` — Per-file quality scores
- `get_directory_files(path, ext)` — File browser for scan UI
- `get_review_agents(specialty)` — Team agents from Bridge for multi-agent review
- `get_review_nodes()` — Remote GPU nodes for distributed review
- `start_multi_agent_review(code, path, agents, context)` — Async review with consensus
- `get_review_status(id)` — Review results from in-memory store

**DB tables owned:** `code_scans`, `code_issues`, `code_fixes`
**External deps:** Bridge dispatcher, scan_pipeline, node_router (optional)

### proposal_service.py (~1,200 lines)

Absorbs core logic from Improvements Lab routes.py + manager.py. Only the ~15 routes currently used by Dev Pipeline proxy + agent_loop dependencies. The 79 unused routes (chat, workflow automation, discussions, API settings, contractor management) are not migrated — they can be added later if needed.

**Functions:**
- `list_proposals(status, limit)` — List with optional status filter
- `get_proposal(id)` — Single proposal detail with date serialization
- `create_proposal(title, category, description, code_changes, rationale, priority, risk_level)` — Create + auto-evaluate
- `delete_proposal(id)` — Delete (only for safe statuses)
- `approve_proposal(id, user)` — Approve + trigger auto-execution
- `reject_proposal(id, user, reason)` — Reject + log
- `execute_proposal(id)` — Workflow: backup → execute → test
- `regenerate_plan(id)` — AI code generation via code_generation_engine
- `retry_proposal(id)` — Retry with escalation
- `escalate_proposal(id)` — Escalate to senior tier
- `archive_proposal(id)` — Archive proposal
- `restore_proposal(id)` — Restore from backup
- `get_backups(id)` — List deployment backups
- `deploy_to_production(id)` — Deploy tested proposal
- `get_stats()` — Status count breakdown
- `get_stuck()` — Proposals stuck >48h
- `auto_execute(id)` — Background thread: code_gen → sandbox → test → notify
- `get_deploy_history()` — Deployment history (deployed/implemented)
- `get_deploy_ready()` — Proposals ready to deploy (status=tested)

**DB tables owned:** `improvement_proposals`, `improvement_deployments`
**External deps:** Bridge dispatcher, code_generation_engine, workflow_orchestrator, backup_manager

### sandbox_service.py (~800 lines)

Absorbs all business logic from Sandbox Manager routes.py.

**Functions:**
- `list_sandboxes()` — All module sandboxes with status
- `get_sandbox(module_id)` — Single sandbox detail
- `create_sandbox(module_id, proposal_id)` — Create/activate sandbox
- `destroy_sandbox(module_id)` — Destroy sandbox
- `get_status(module_id)` — Detailed status with access URL
- `run_module_tests(module_id, suite)` — Run tests in sandbox
- `reset_sandbox(module_id)` — Destroy + recreate
- `get_config()` / `update_config(data)` — Sandbox configuration CRUD
- `apply_from_scan(issue_id)` — Apply Code Sentinel fix to sandbox
- `apply_from_proposal(proposal_id)` — Apply improvement proposal
- `deploy_to_production(proposal_id)` — 6-step deploy pipeline with backup
- `get_module_status()` — Manager status summary
- `discover_tests()` — Find test files (Python/JS/Shell)
- `get_test_suites()` / `create_suite()` / `update_suite()` / `delete_suite()` — CRUD
- `run_tests(type, target)` — Execute tests in background thread
- `get_run_status(id)` / `cancel_run(id)` — Test run control
- `get_test_results(limit)` — Recent test results
- `get_test_history(limit, offset)` — Paginated history
- `get_run_details(id)` — Detailed results
- `get_trends(days)` — Daily trend aggregation
- `get_deployments(limit)` — Deployment history
- `run_benchmark(type, target, iterations)` — Performance benchmarks

**DB tables owned:** `module_sandboxes`, `sandbox_config`, `sandbox_test_suites`, `sandbox_test_results`, `test_runs`
**External deps:** SandboxManager class, backup_manager, subprocess

## Station Integration

### Bridge Connection

Module ties to **ENGINEERING** station. Follows Consciousness pattern:

- `station_routes.py` provides `/api/station/crew`, `/api/station/jobs`, `/api/station/job/<id>`
- These proxy Bridge APIs filtered to `module_source="dev_pipeline"` and station `ENGINEERING`
- Frontend polls every 5s when jobs are active

### Job Types

| Job Type | Capability | Tab | Triggered By |
|----------|-----------|-----|-------------|
| `scan_code` | `code_analysis` | Scan | Single/batch scan with AI |
| `propose_fix` | `improvement` | Proposals | scan_pipeline auto-creation |
| `sandbox_test` | `testing` | Sandbox | Test execution |
| `deploy_changes` | `deployment` | Deploy | Deploy to production |

### UI Components

**Station Crew Panel** — Shows ENGINEERING agents, busy/idle status, current job
**Job Progress Bars** — Real-time progress with step count and percentage
**Loop Buttons** — Continuous-run toggles per tab (∞ SCAN, ∞ PROCESS, ∞ TEST)

### External JS

`static/js/dev_pipeline.js` (~1,000 lines) extracted from template inline JS:

- Core: `api()`, `switchTab()`, `switchSubTab()`, `loadStats()`
- Station: `checkActiveJobs()`, `renderOpsAgents()`, `pollJobStatus()`
- Scan: `loadScanFiles()`, `scanSelected()`, `scanAll()`, `loadIssues()`, `loadScanHistory()`
- Proposals: `loadProposals()`, `filterProposals()`, `showProposalDetail()`, `proposalAction()`
- Sandbox: `loadSandboxes()`, `loadTestRuns()`, `loadTestSuites()`, `runNewTest()`
- Deploy: `loadDeployReady()`, `loadDeployHistory()`
- Loops: `toggleLoop()`, `loopNext()`, continuous run state

## Migration Phases

### Phase 1: Scan Service + Routes
- Create `services/scan_service.py` from Code Sentinel business logic
- Rewrite `dev_pipeline/scan_routes.py` to call scan_service
- Update `agent_loop.py:1755` import path
- Verify scan tab end-to-end

### Phase 2: Proposal Service + Routes
- Create `services/proposal_service.py` from Improvements Lab core logic + manager
- Rewrite `dev_pipeline/proposal_routes.py` to call proposal_service
- Update `agent_loop.py:1651` import path
- Audit 79 unused Improvements Lab routes

### Phase 3: Sandbox Service + Routes
- Create `services/sandbox_service.py` from Sandbox Manager logic
- Rewrite `dev_pipeline/sandbox_routes.py` to call sandbox_service
- Update `safe_deployment_protocol.py` import

### Phase 4: Deploy Tab + Station Integration
- Rewrite `dev_pipeline/deploy_routes.py` to use proposal_service + sandbox_service
- Create `dev_pipeline/station_routes.py` for Bridge integration
- Extract JS to `static/js/dev_pipeline.js`
- Add station crew panel, job progress, loop buttons to template

### Phase 5: Cleanup & Removal
- Delete old route files (code_sentinel/routes.py, improvements/routes.py, sandbox_manager/routes.py)
- Keep thin __init__.py redirect stubs
- Remove blueprint registrations from app.py
- Remove/disable old module_registry entries
- Delete old templates
- Final smoke test: scan → propose → test → deploy

## External Import Updates

| File | Old Import | New Import |
|------|-----------|-----------|
| `agent_loop.py:1651` | `tools.improvements.routes._auto_execute_proposal` | `services.proposal_service.auto_execute` |
| `agent_loop.py:1755` | `tools.code_sentinel.routes.basic_static_analysis` | `services.scan_service.static_analysis` |
| `safe_deployment_protocol.py:27` | `sandbox_manager.SandboxManager` | `services.sandbox_service` (graceful fallback) |

## Deletions

| Item | Lines | Action |
|------|-------|--------|
| `tools/code_sentinel/routes.py` | 1,555 | Delete |
| `tools/improvements/routes.py` | 6,264 | Delete |
| `tools/improvements/manager.py` | 447 | Delete |
| `tools/sandbox_manager/routes.py` | 1,877 | Delete |
| `templates/tools/code_sentinel.html` | ~500 | Delete |
| `templates/tools/improvements.html` | ~800 | Delete |
| `templates/tools/improvements_chat.html` | ~400 | Delete |
| `templates/tools/improvements_lab.html` | ~300 | Delete |
| `templates/tools/sandbox_manager.html` | ~600 | Delete |
| `static/js/improvements_lab/` | ~? | Delete if exists |

## Survivors

| Item | Reason |
|------|--------|
| `tools/code_sentinel/__init__.py` | Redirect stub for bookmarks |
| `tools/improvements/__init__.py` | Redirect stub |
| `tools/improvements/improvements_routes.py` | Already redirects to Dev Pipeline |
| `tools/sandbox_manager/__init__.py` | Redirect stub |
| All DB tables | Unchanged — services query directly |

## Constraints

- ENGINEERING station agents handle all pipeline jobs
- Bridge dispatcher is required for AI-powered scans (static analysis fallback without it)
- SandboxManager class dependency must be resolved (either absorbed or kept as utility)
- `scan_pipeline.py` metadata tags reference `code_sentinel` — DB data stays, no code change needed
- Black pre-commit hook — always re-stage after format failures

## Success Criteria

1. All 4 Dev Pipeline tabs work without importing from old modules
2. `agent_loop.py` imports from services layer, not old modules
3. Old module directories contain only redirect stubs
4. Station crew panel shows ENGINEERING agents with job activity
5. Job progress bars update in real-time for scans, tests, deployments
6. Full pipeline works: scan file → auto-propose fix → test in sandbox → deploy
