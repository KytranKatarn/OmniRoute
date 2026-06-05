# COORD-1..6 — K.I.N. tab ↔ ARMADA token unification (implementation spec)

**Origin:** user ask — "the 4 subtabs WELFARE / WORKLOAD / WORK SESSIONS / PERFORMANCE — do they
coordinate with all of the ones we see in A.R.M.A.D.A. as well, we even have token tracking there."
**Prereq DONE:** welfare backend is now token-based (PRs #1466+#1467, all 4 welfare writers on
`services/welfare_load.py`). This spec wires the K.I.N. *tab UI* to the same token data ARMADA shows.
KB #270619/#270621. Next-session work; ~1 focused session.

## Current state (explored 2026-06-05, work_routes.py + department-hq.js)

| K.I.N. subtab | Route | Backing table | Token-aware? |
|---|---|---|---|
| WELFARE / WORKLOAD | `/api/kin/welfare` (work_routes.py:23) | `agent_emotional_state` (token-based ✅) + workload = `COUNT(*) dispatches_1h/24h` from `task_execution_log` (lines 74-78) | ❌ workload metric is action COUNT, not tokens |
| WORK SESSIONS | `/api/work-sessions` (work_routes.py:230) | `task_execution_log` incl. `SUM(tel.tokens_used) AS tokens_used` (line 257), returned (line 306) | ✅ already token-aware (verify JS renders it) |
| PERFORMANCE | `/api/performance` (work_routes.py:321) + `/api/performance/<dept>` (391) | **`bridge_jobs`** COUNT by status (line 360) | ❌ partial table → ~53% success vs ARMADA's ~100% (task_execution_log) |
| (CREED) | `/api/creed` (work_routes.py:444) | `agent_emotional_state` | n/a |

JS renderers: `loadWelfare` (department-hq.js ~667/807), `loadWorkSessions` (~886), `loadPerformance` (~968).
ARMADA reads `task_execution_log` tokens for its Dispatch Traffic / health panels (dispatch_health
source — confirm exact endpoint in fleet_dashboard/dispatch routes during build).

## The fix (do in this order)

### COORD-1 — shared `services/agent_load_service.py` (single source of truth)
Create `get_agent_load(agent_id=None, window='1h')` → returns per-agent (or fleet) dict from
`task_execution_log`: `{tokens, duration_ms, dispatches, success, failures, success_rate, load}`
where `load = welfare_load.compute_token_load(tokens, duration_ms, token_limit_per_day)`.
Reuse `welfare_load.py` for the formula (do NOT re-derive). This is the ONE query welfare /
work-sessions / performance / `kin_workload_monitor` all call → kills the K.I.N.↔ARMADA divergence
at the source. (Optionally refactor the FIX-5 monitor's inline query to call this too.)

### COORD-2 — WELFARE/WORKLOAD route: add tokens
`/api/kin/welfare` (work_routes.py:74-78): alongside `dispatches_1h/24h` add
`SUM(tel.tokens_used) FILTER (... 1h/24h)` and emit `tokens_1h/tokens_24h` + `load` (from
agent_load_service). Keep dispatch counts for context but make **tokens the headline workload metric**
(consistent with the welfare model that now rests agents on token load, not count).

### COORD-3 — PERFORMANCE route: bridge_jobs → task_execution_log
Rewrite `/api/performance` + `/api/performance/<dept>` (work_routes.py:321-440) to source from
`task_execution_log` (COUNT, success FILTER, `SUM(tokens_used)`) grouped by department/agent — same
source as ARMADA. This fixes the ~53%→~100% success-rate divergence. Keep `bridge_jobs` only if a
specific KPI genuinely needs it (document why). Expose `tokens_used` per dept/agent.

### COORD-4 — WORK SESSIONS: surface tokens in UI
Route already returns `tokens_used`. In `loadWorkSessions` (department-hq.js ~886) render a tokens
column/figure per session row (match ARMADA's token formatting — e.g. `1.2k`/`340k`).

### COORD-5 — JS: render tokens + load in WELFARE + PERFORMANCE
`loadWelfare` (~667/807): show tokens_1h/24h + a load bar (0–1) instead of / alongside the dispatch
count. `loadPerformance` (~968): render token totals + the corrected success rate. Reuse ARMADA's
token-format + color helpers if shared (check `_mixLocalCloudColor` / token formatters in the Token
Economy tab work, PR #1394).

### COORD-6 — verify parity + deploy
Playwright (or P.R.O.B.E. `run_qa_suite`): open DHQ → K.I.N. tab, confirm all 4 subtabs show token
figures matching ARMADA's Dispatch Traffic for the same agent/window. Cross-check one agent's
`tokens_24h` in WELFARE == ARMADA tab == `SELECT SUM(tokens_used) ... WHERE agent_id=X AND created_at>NOW()-'24h'`.
Restart `archie_platform` (+ `archie_scheduler` if the shared service is imported by jobs). PR + merge.

## Gotchas
- work_routes.py runs in `archie_platform` (web). The shared service, if imported by
  `kin_workload_monitor`, also loads in `archie_scheduler` → restart BOTH.
- `task_execution_log.tokens_used` = real eval_count; `model_used='internal'` rows are legit 0-token
  (admin/orchestration) — exclude or label them, don't count as "free work".
- Flask `jsonify()` breaks on Decimal/datetime — use `Response(json.dumps(..., default=str))` (KB #269068).
- Keep `welfare_load` the ONLY fatigue formula; agent_load_service supplies data, not math.

## Files
- NEW `platform_v2/services/agent_load_service.py`
- EDIT `platform_v2/tools/department_hq/work_routes.py` (welfare + performance routes)
- EDIT `platform_v2/tools/department_hq/static/js/department-hq.js` (loadWelfare/loadWorkSessions/loadPerformance)
- (maybe) EDIT `platform_v2/tools/department_hq/jobs.py` kin_workload_monitor → call agent_load_service
