# Repair Bay — Full Module Review

**Reviewer**: Lead synthesis (8-dimension structured review)
**Date**: 2026-05-29
**Module**: `platform_v2/tools/repair_bay/` (133 endpoints, 11 route files, ~51 service files / ~22,000 LOC)
**Scope**: Every tab + PR Review / Diagnose / Test / Ship / Push workflows, P.R.O.B.E./QA, scheduled jobs, sandbox/deploy pipeline, and a dedicated audit of LLM/agent dispatch cluster-routing compliance.

---

## 1. Executive Summary

- **Overall health verdict: AMBER — operational but with several silent failures.** The module's structure is sound (ADR-013 dispatch discipline, route registration, auth coverage, XSS hygiene all good), but multiple pipelines are dormant or crash-on-call due to schema drift, broken import paths, and dead code that *looks* live.
- **Dispatch & cluster routing: PASS (with hygiene caveats).** Every LLM call routes through the canonical DHQ `department_dispatcher`. Zero direct-Ollama, zero deprecated `ai_bridge.bridge_dispatcher` imports, zero model-pinning. The only gap is **4 unmapped capability strings** that floor-fall to Engineering — one of which (`code_fix`) routes with a skill penalty on every run.
- **Two confirmed runtime crashes**: `code_metrics_snapshots.module_name` does not exist (Reviews tab `/api/module-review/data` always 500s), and `pr_reviews.metadata` column is missing (every merge-tier write fails, worker no-ops).
- **P.R.O.B.E. functional QA is healthy** (74 suites, 3,097 runs, 100% recent pass) but the **performance-baseline gate is completely dormant** — all 3 perf tables are at 0 rows despite the nightly job running daily. The post-deploy regression gate is a no-op.
- **PR Review hardening fixes (#1276/#1277/#1278) are all intact**, but a **verdict token mismatch (`APPROVE` vs `APPROVED`) silently disables auto-merge and Tier-1 classification** — 333 reviews but only 12 merged.
- **3 of 7 scheduled jobs have never run** (broken import path `tools.dev_pipeline` does not exist; missing log calls). The `repair_proposals` table does not exist, breaking the Scan→Proposal half of the self-heal pipeline.
- **Deploy safety net is largely dead code**: `DeploymentMonitor`/`SafeDeploymentProtocol` (~1,200 LOC) have zero live callers; health checks hard-code unreachable `localhost:3000`; two monitoring checks are permanent `return True` stubs.
- **~7,500 lines of dead/orphaned code** identified (workflow cluster, cursor IDE integration, collaborative reporting), plus a **duplicate `sandbox_routes` registration** causing a silent route-conflict bug.

---

## 2. Dispatch & Cluster Routing Verdict  ⭐ (Owner's Main Ask)

**VERDICT: PASS** — All inference is routed through Department HQ + cluster exactly like other agent requests. No bypass, no direct Ollama, no public-hostname inter-cluster violations. The remaining work is capability-string hygiene, not architectural violation.

### Inference Call Site → Capability → Department Mapping

| # | Call site | Capability | Mapped department | Status |
|---|-----------|-----------|-------------------|--------|
| 1 | `pr_diff_analyzer.review_pr()` | `code_review` | Engineering & Technology (F.O.R.G.E.) | ✅ OK (in MAP) |
| 2 | `nl_code_generator.py:387` | `code` | Engineering & Technology (F.O.R.G.E./P.R.O.B.E.) | ✅ OK (in MAP) |
| 3 | scan/analysis path | `code_analysis` | Engineering & Technology | ✅ OK (in MAP) |
| 4 | `sandbox_ai_integration.py:232` | `debug` | Engineering (F.O.R.G.E./P.R.O.B.E. have skill) | ⚠️ FLOOR-FALLBACK (map key is `debugging`; works by coincidence) |
| 5 | `improvement_engine.py:556` | `research` | (unmapped) → Engineering, then cross-dept rescue to R&D (D.A.R.W.I.N.) | ⚠️ FLOOR-FALLBACK (rescued by #2217) |
| 6 | `sandbox_queue.py:58` | `documentation` | (unmapped) → Engineering, then cross-dept rescue to C.O.D.E.X. | ⚠️ FLOOR-FALLBACK (rescued by #2217) |
| 7 | `forge_triage.py:91` | `code_fix` | (unmapped AND no agent_skills row) → Engineering w/ **-1.0 skill penalty** | ❌ FLOOR-FALLBACK + skill penalty (worst case) |

### Violation Checks

| Check | Result |
|-------|--------|
| Direct Ollama / `:11434` inference calls | ✅ **NONE** (the `:11434`/ollama greps in `deploy_routes.py:48-66` are the ADR-013 *scanner text*, not calls) |
| Deprecated `ai_bridge.bridge_dispatcher` imports | ✅ **NONE** |
| Per-call model pinning into `dispatch()` | ✅ **NONE** (`nl_code_generator.self.model` is computed but never passed — dead state, not a violation) |
| Public-hostname inter-cluster traffic | ✅ **NONE** — the `http://192.168.1.200:3000` self-calls in `station_routes.py:37/87/121` are the **hub talking to itself** (not VPS→hub), so the mesh rule does not apply. Still a hard-coded-IP smell. |

**Bottom line for Kytran**: Repair Bay is compliant — agent work flows through DHQ + cluster like everything else. The fix is to add 4 capability keys to `CAPABILITY_DEPARTMENT_MAP` (`code_fix`, `documentation`, `research`, `debug`-alias) so routing is deterministic rather than rescued-by-fallback. The single most important one is `code_fix` (finding H-1 below).

---

## 3. Tab-by-Tab Status

| Tab | Wired end-to-end? | Backend endpoint | Issues |
|-----|-------------------|------------------|--------|
| **Reviews** (Code Reviews) | ⚠️ Partial | `/api/forge/prs` + `/api/module-review/data` | `/api/module-review/data` **always 500s** (`code_metrics_snapshots.module_name` missing). Tab pulls raw GitHub PRs, easily confused with PR Review tab. MODULE_CATEGORIES lists decommissioned modules. |
| **Diagnose / Scan** | ✅ Yes | `/api/scan/*` (17), `/api/repair/*` (6) | `scan_status` missing `@admin_required`; `repair_routes` missing `@login_required`. |
| **PR Review** | ⚠️ Yes but fragile | `/api/forge/pr-reviews/*` | **Verdict token mismatch silently disables auto-merge** (§4). `window.loadPRReviews` defined twice — HTML version wins, ~340 LOC dead in JS. |
| **Proposals** | ✅ Yes | `/api/proposals/*` (15) | `repair_proposals` table does not exist → proactive-scan proposals silently discarded (§6). |
| **Test Bay / Sandbox** | ⚠️ Yes (degraded) | `/api/sandbox/*` (31) | **Duplicate `sandbox_routes` registration** (silent route conflict). Docker SDK swallows ImportError → Docker sandboxes no-op silently. SSE uses blocking `time.sleep(1)`. |
| **Ship / Deploy** | ⚠️ Yes (misleading) | `/api/deploy/*` (10), `/api/forge/stats` | Website-deploy correctly delegates to MCP skill, but reports `success` before any bytes pushed. F.O.R.G.E. stats sub-panel **always blank** (`agent_loop_cycles` relation missing). Pre-deploy ADR-013 gate skipped in `deploy_execute`. |
| **QA** | ✅ Yes | `/api/qa/*` (16) | Perf gate dormant (§5). Duplicate load triggers re-fetch on every tab visit. No aggregate `/api/qa/reports`. |
| **Pushes** | ⚠️ Partial | `/api/pushes/summary` (1) | Missing from `switchTab()` dispatcher; works only via special-case hash check + click listener. Missing `@login_required`. |
| **Module Review (Reviews)** | ❌ Broken | `/api/module-review/data` | Missing from `switchTab()` — hash nav never loads data. Backend endpoint 500s (see Reviews). |
| **Station panel** | ⚠️ Yes | `/api/station/*` (3) | Hard-coded hub LAN IP; deferred per-call `import requests`; swallows all errors silently. |

---

## 4. PR Review Pipeline Status

**Recent hardening fixes — ALL INTACT and verified in git history:**

| Fix | Commit | Status |
|-----|--------|--------|
| Diff-grounded reviews (real unified diff into prompt, never `diff_url` as text) | #1277 | ✅ Present (`pr_diff_analyzer._fetch_diff` → `_build_prompt`) |
| `merge_pr()` returns a `merged` key in all paths | #1278 | ✅ Present (`github_service.py:361-370`) |
| `sync_closed_prs()` finalizes stale `pending`/`in_progress` rows to `skipped` | #1276 | ✅ Present (live DB shows 0 stuck rows) |
| PR size columns (`additions`/`deletions`/`changed_files`) populated via `_enrich()` | #1277 | ✅ Present |

**But three live defects remain:**

- **🔴 HIGH — Verdict token mismatch.** Prompt emits `VERDICT: APPROVE` (`pr_diff_analyzer.py:179`) but auto-merge gate (`pr_review_service.py:201`) and `classify_pr_tier` (`:313`) require `APPROVED`. The regex/substring never matches the documented format → **F.O.R.G.E.-approved PRs are never auto-merged, small PRs never classify Tier 1.** Live evidence: 333 reviewed rows, only 12 merged, 0 organic auto-merges.
- **🟠 MEDIUM — `sync_closed_prs()` never runs on a schedule.** Only the manual Poll button invokes it; Job #61 (`_run_forge_pr_poll`, every 4h) calls `poll_open_prs` but not `sync_closed_prs`. The #3449 safety net is manual-only.
- **🟡 LOW — Auto-merge success gated on `sha` not `merged`.** `mark_review_done()` (`:208`) requires `result.get('sha')`; should consult `result.get('merged')` (the key #1278 added for exactly this).

---

## 5. P.R.O.B.E. / QA Status — Is P.R.O.B.E. Working?

**Functional QA: YES, working.** Live evidence: 74 suites (66 active), 3,097 runs, 36,186 results, 55 visual baselines. Most recent runs (2026-05-27) completed at 100% pass.

**Performance-baseline gate: NO, completely dormant.** This is the critical finding:

- All three perf tables — `qa_perf_baselines`, `qa_perf_regressions`, `qa_perf_acceptances` — are at **0 rows**.
- Nightly Job #59 (`recompute_perf_baselines`, 03:45 EDT) has run every day since ≥2026-05-20 logging `items_processed=0` each time, despite **28,751 passing results with timing data** existing.
- Suspected cause: `archie_scheduler` sidecar has a different DB view/import path than `archie_platform` (cf. KB #263303 volume-mount drift).
- Consequence: `evaluate_post_deploy()` (`proposal_service.py:344`) always evaluates against an empty baseline → `check_regression()` always False → **rollback/pause/flag gate never fires**. The gate is correctly plumbed but a no-op.
- Secondary bug: the inline perf hook (`qa_service.py:254`) requires `perf_flags is not None`, only set by `qa_spec_runner` — so e2e/UX/tab-interaction runs never trigger the gate even if baselines existed.

**Other QA gaps:** No autonomous scheduled suite execution (all runs manual/Claude-triggered; latest is 2 days stale). No aggregate `/api/qa/reports` trend endpoint.

---

## 6. Scheduled Jobs Health (Live Evidence)

| Job | Schedule | Live status |
|-----|----------|-------------|
| `forge_pr_poll` (#61) | every 4h | ✅ Runs (but omits `sync_closed_prs`) |
| `forge_pr_diff_analysis` | every 10 min | ✅ Runs |
| `archie_pr_review_worker` | every 10 min | ⚠️ Runs but `items_processed=0` on all 1035 runs (blocked by missing `metadata` column) |
| `agent_proactive_scan` | every 6h | ⚠️ Runs (25 scans, 375 issues) but **no `autonomy_loop_log` entry** + proposals discarded (no `repair_proposals` table) |
| `forge_dep_drift` | daily | ⚠️ Runs but always `requirements_count=0` (cannot find requirements.txt in container) |
| `forge_repo_health_check` | daily 06:00 | ❌ **NEVER run** (0 log rows; no `_log_autonomy_action` call) |
| `forge_github_presence_audit` | weekly Sun 03:00 | ❌ **NEVER run** (0 log rows) |
| `dependabot_scan` (#59) | every 6h | ❌ **NEVER run** — imports `tools.dev_pipeline.services.*` which **does not exist** (correct path is `tools.repair_bay.services.*`) |

**`repair_proposals` table does not exist** → the Scan→Proposal half of the self-heal pipeline is broken; every proactive scan silently discards proposals via a bare `except`. **`repair_queue` has 12 dependabot rows stuck `failed`/`attempts=0` since March 2026** (orphaned by the broken dependabot import).

---

## 7. Sandbox / Ship / Deploy Pipeline Status

- **✅ Confirmed good**: The broken Hostinger REST deploy path (KB #261679) is **not** called anywhere. `_deploy_static_hostinger` correctly delegates to the `/deploy-website` MCP skill. `HOSTINGER_API_BASE` (`deploy_service.py:47`) is dead constant.
- **🔴 HIGH — Health checks hit unreachable `localhost:3000`.** `deployment_monitor.py:228` and `safe_deployment_protocol.py:546` run `curl http://localhost:3000/health` — inside Docker port 3000 is not bound to localhost. Connection refused → false rollback signal.
- **🔴 HIGH — `DeploymentMonitor` & `SafeDeploymentProtocol` are dead code** (~1,200 LOC, only callers in `_deprecated/`). The live deploy path (`proposal_service.py`) never invokes the monitoring window, health gate, or auto-rollback from these classes.
- **🟠 MEDIUM — Permanent-True stubs**: `_check_error_rate` and `_check_response_time` (`deployment_monitor.py:250`) return `True` unconditionally — false confidence.
- **🟠 MEDIUM — `auto_rollback` depends on `rollback.sh` existing in each backup dir** with no fallback; fails silently to a DB row (no Telegram alert).
- **🟠 MEDIUM — Ship tab reports `success` before deploy happens** (async via MCP skill; `verify_deploy` snapshots pre-deploy content).
- **🟠 MEDIUM — Pre-deploy ADR-013 gate is advisory-only and skipped entirely in `deploy_execute`** (`deploy_routes.py:278`).
- **🟠 MEDIUM — Docker sandbox silently degrades** when Docker SDK missing; `docker_available` never surfaced in any status endpoint.

---

## 8. Prioritized Issue List

### 🔴 CRITICAL
| ID | Issue | File:line | Fix |
|----|-------|-----------|-----|
| C-1 | `code_metrics_snapshots.module_name` missing → Reviews tab always 500 | `module_review_routes.py:156` | Rewrite query to `jsonb_each(per_module)` unnest |
| C-2 | `pr_reviews.metadata` column missing → merge-tier writes crash, worker no-ops | `pr_review_service.py:329` | `ALTER TABLE pr_reviews ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'` (add migration) |
| C-3 | Perf-baseline recompute computes 0 every night → post-deploy gate dormant | `jobs.py:500` / `qa_baseline_service.py` | Verify scheduler-container DB view; run `recompute_all_baselines()` manually to isolate |
| C-4 | `dependabot_scan` never runs — `tools.dev_pipeline` does not exist | `agent_loop.py:3817-3821` | Fix import to `tools.repair_bay.services.dependabot_service` / `.forge_triage` |
| C-5 | `repair_proposals` table missing → Scan→Proposal pipeline broken | `agent_loop.py:4060` | Create table from `audit_pipeline.py` expected schema + migration |

### 🟠 HIGH
| ID | Issue | File:line | Fix |
|----|-------|-----------|-----|
| H-1 | `code_fix` unmapped + no skill → floor-fall to F.O.R.G.E. w/ -1.0 penalty every run | `forge_triage.py:91-92` | Change capability to `code`, OR add to MAP + seed `agent_skills` |
| H-2 | Verdict token mismatch (`APPROVE` vs `APPROVED`) disables auto-merge/Tier-1 | `pr_diff_analyzer.py:179` vs `pr_review_service.py:201,313` | Single shared `parse_verdict()` helper; align tokens |
| H-3 | `/api/forge/stats` queries non-existent `agent_loop_cycles` → F.O.R.G.E. Ship sub-panel blank | `github_routes.py:179` | Point query at correct scheduler table |
| H-4 | `forge_repo_health_check` + `forge_github_presence_audit` never run | `agent_loop.py:722` | Add `_log_autonomy_action`; verify imports resolve in container |
| H-5 | Health checks curl unreachable `localhost:3000` | `deployment_monitor.py:228`, `safe_deployment_protocol.py:546` | Use `http://archie_platform:3000/health` via env var |
| H-6 | `DeploymentMonitor`/`SafeDeploymentProtocol` dead (~1,200 LOC, false safety) | `deployment_monitor.py:1` | Wire into `proposal_service.deploy_proposal` OR delete + document |
| H-7 | `/api/forge/webhook` returns 500 (not 401) when secret unset — leaks config state | `github_routes.py:276` | Return 401; ensure `GITHUB_WEBHOOK_SECRET` set |
| H-8 | Duplicate `sandbox_routes` registration → silent route conflict | `sandbox_routes.py:1` + `services/sandbox_routes.py:1` | Remove top-level file + its `__init__.py` registration |
| H-9 | `window.loadPRReviews`/`_startPRReviewPoll` defined twice (~340 LOC dead JS) | `repair-bay-main.js:1112` | Delete dead JS defs + 4 orphan helpers |
| H-10 | 5 connection leaks (no try/finally) — live code path | `improvement_engine.py:59,95,411,478,571,607` | Use `with get_db_cursor(commit=True)` |
| H-11 | Dead workflow cluster + cursor + collaborative reporting (~4,600 LOC) | `services/workflow_*.py`, `cursor_*.py`, etc. | Delete (see §9) |

### 🟡 MEDIUM
| ID | Issue | File:line | Fix |
|----|-------|-----------|-----|
| M-1 | `documentation` capability unmapped → cross-dept rescue fragility | `sandbox_queue.py:58` | Add `"documentation": "Documentation & Knowledge"` to MAP |
| M-2 | `research` capability unmapped | `improvement_engine.py:556` | Add `"research": "Research & Development"` to MAP |
| M-3 | `perf_flags is not None` gate skips non-spec-runner results | `qa_service.py:254` | Treat all timed passing results as candidates |
| M-4 | `sync_closed_prs()` not in Job #61 loop | `jobs.py:~815` | Add `sync_closed_prs(repo=repo)` after `poll_open_prs` |
| M-5 | `forge_dep_drift` always `requirements_count=0` | `dep_drift_service.py` | Use absolute path to requirements.txt |
| M-6 | Permanent-True monitoring stubs | `deployment_monitor.py:250` | Implement or remove |
| M-7 | `auto_rollback` no fallback when `rollback.sh` absent; no Telegram alert | `auto_rollback.py:208` | Add file-copy fallback + `send_system()` |
| M-8 | Ship tab reports `success` before deploy | `deploy_routes.py:393` | Status `pending_mcp_skill`; skip verify for `deploy_static` |
| M-9 | Pre-deploy ADR-013 gate skipped in `deploy_execute` | `deploy_routes.py:278` | Call gate + block on violation |
| M-10 | Docker sandbox degrades silently | `sandbox_manager.py:26` | Expose `docker_available` in `/api/sandbox/config` |
| M-11 | `repair_routes`/`pushes_summary` missing `@login_required` | `repair_routes.py:13`, `pending_push_routes.py:14` | Add `@login_required` |
| M-12 | `scan_status` missing `@admin_required` | `scan_routes.py:~85` | Add decorator |
| M-13 | Station routes hard-code hub LAN IP | `station_routes.py:37` | Use `os.getenv('ARCHIE_HUB_URL', 'http://100.64.0.4:3000')` |
| M-14 | `pushes`/`module-review` missing from `switchTab()` | `repair_bay.html:3834` | Add cases |
| M-15 | 4 connection leaks in `deployment_monitor.py` | `:96,240,305,377` | try/finally |
| M-16 | `debug` capability uses non-map key (works by coincidence) | `sandbox_ai_integration.py:232` | Use `debugging` or add alias |

### 🟢 LOW
- `forge_pr_review_merge` duplicates GitHub API instead of `github_service.merge_pr` (`github_routes.py:840`).
- MODULE_CATEGORIES references decommissioned modules (`module_review_routes.py:61`).
- `merge_pr` `merged` defaults to `True` for absent key — should default `False` (`github_service.py:365`).
- `loadStats()` fetches `?limit=700` for a header badge (`repair_bay.html:2316`).
- QA tab duplicate load triggers / no refresh on stale session.
- Blocking SSE `time.sleep(1)` holds worker up to 3 min (`sandbox_routes.py:233`).
- `team_assignment_engine` import silently fails → `auto_assign_team` is a no-op (`improvement_engine.py:350`).

---

## 9. Optimization & Dead-Code Cleanup

**Confirmed dead code (~7,500 LOC) — recommended deletions, in priority order:**

1. **Workflow cluster (1,753 LOC)** — `workflow_automator.py`, `workflow_orchestrator.py`, `workflow_state_machine.py`, `workflow_sse_manager.py`. Zero live callers; proposal lifecycle is handled by `proposal_service.py` + `improvement_proposals.status`.
2. **Cursor IDE integration (1,469 LOC)** — `cursor_api.py`, `cursor_context_generator.py`, `background_workflow_runner.py`. `cursor_bp` is registered (`app.py:2458`) but uses `sys.path`-mangled imports into the dead workflow cluster. **Confirm intent with Kytran** before deleting.
3. **Duplicate `sandbox_routes.py` (424 LOC)** — remove top-level file + `__init__.py:23,35`; keep `services/sandbox_routes.py` (eliminates silent route conflict).
4. **Collaborative reporting (1,946 LOC)** — `collaborative_report_generator.py`, `team_consensus_orchestrator.py`, `improvement_learning.py`. Self-referential / deprecated-only.
5. **Misc orphans (1,285 LOC)** — `content_matcher.py`, `nl_code_generator.py` (duplicates `capability='code'`), `db_schema_helper.py`. **Wire `shield_gate.validate_fix()` into the dependabot merge path before deleting `shield_gate.py`** — it implements a genuinely useful 3-check security gate.

**Other optimizations:**

- Add 4 capability keys (`code_fix`, `documentation`, `research`, `debug`-alias) to `CAPABILITY_DEPARTMENT_MAP` — converts fragile fallbacks into deterministic routing. **Lowest effort, highest value.**
- Extend the `deploy_routes.py` ADR-013 scanner to also assert every `dispatch(capability=X)` uses a mapped/skilled capability — turns this audit into an automated regression guard.
- Extract a shared `parse_verdict()` helper (4 call sites currently disagree).
- Add an APScheduler job to run high-priority suites daily (proactive regression detection).
- Add a single health-check decorator that calls `_log_autonomy_action` on entry/exit for all Repair Bay jobs (3 of 7 are currently invisible to monitoring).
- Replace `import requests` inside station route bodies with module-level import; propagate non-timeout errors.
- Remove dead `workflow_orchestrator` fallback branch in `proposal_service.py:645-660`.
- Fix CLAUDE.md `rules/repair-bay.md`: states `SandboxManager` is at `platform_v2/sandbox_manager.py` (does not exist) — canonical is `tools/repair_bay/services/sandbox_manager.py:59`.

---

*End of review. No findings invented — all citations drawn from the 8 dimension reports.*
