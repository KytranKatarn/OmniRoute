# Review Batch 2 — K.I.N./Scheduling + Tracking (2026-06-08)

Two audits run solo in a 2-agent batch (after the 24-agent fan-out failed). These CORRECT two
assumptions from the recovered batch-1 audits + my solo doc.

---

## Subsystem: K.I.N. + Scheduling

**Correction to "nothing keeps warm sets resident":** a proactive, demand+welfare+rest-aware
warm-set keeper ALREADY EXISTS — `platform_v2/services/fleet_jobs.py:319 _kin_fleet_warmth_policy()`,
run by `warmup_fleet_models()` every 20 min (`fleet_jobs.py:1103`, id=`fleet_model_warmup`).
It enqueues K.I.N.-attributed `kin_warmth` rows (priority=1, 5-min TTL, pinned `preferred_node_id`),
audited to `governance_audit_log` as `fleet_warmth_policy`. `node_provisioning.recommend()` is a
wizard helper, NOT read at runtime.

### [CRITICAL/broken] kin_warmth keeper expires before it's claimed — proactive warming ~50% non-functional
- Detail: warmth rows are priority=1 (lowest) + 5-min TTL; `_claim_preferred_node_tasks(limit=2)`
  (`model_dispatch_service.py:439`) claims only 2 pinned/cycle, competing with real preferred work.
- Evidence: 6h totals **33 done / 20 expired / 10 failed (48% miss)**; last cycle all 7 rows expired,
  `claimed_at=NULL`. Cadence irregular (10–80 min gaps).
- Fix: bump warmth priority above floor; dedicated/uncapped warm-claim path; TTL ≥10 min.

### [CRITICAL/broken] Synchronous hub warmup blocks behind the global lock — 89s avg / 399s max
- Detail: `warmup_fleet_models` fires 9 capability pings; heavy hub models (gemma3:12b, deepseek-16b)
  cold-load under the global `_MODEL_LOAD_LOCK`, stalling the cycle + every other warm-boot.
- Evidence: TEL 2h `fleet_warmup` avg_ms=89338 max_ms=399762 n=13. `model_service.py:31` comment.
- Fix: per-host lock; drop the synchronous hub-ping loop, warm the hub via the same kin_warmth queue.

### [HIGH/broken] current_load re-inflating — used as ORDER BY sort key
- Live: Outpost-US current_load=96, UK 49, LT 21 while real load ~0. `model_dispatch_service.py:74,126`
  `ORDER BY bridge_priority DESC, current_load ASC` → mis-routes away from idle CPU outposts.
- Fix: recompute from live `task_execution_log`/queue running-count in `check_fleet_health`, or drop as sort key.

### [MEDIUM/optimization] KEEP_ALIVE (10m nodes) vs warmup interval (20m) → guaranteed 10-min cold gap
- Fix: drive cadence off KEEP_ALIVE headroom (~7-min, or "model idle >8m"), not a fixed 20 min.

### [RISK/medium] K.I.N. welfare/workload monitor output is informational-only — doesn't feed warm/route
- `kin_workload_monitor` (jobs.py:1799, 5min) recomputes welfare + node token-load but takes no
  warm/route action (intentional after spam KB #270619). Fix: feed its live per-node demand into the
  warmth TOP_K selection (it already computes the same 6h window).

**Owner verdict:** `_kin_fleet_warmth_policy` is the correct owner. Welfare gating does NOT conflict
(rest only suppresses warming idle nodes). Minimal fix set: reliable warmth drain + per-host lock +
KEEP_ALIVE-aware cadence + current_load fix + demand-driven TOP_K.

---

## Subsystem: Dispatch + Token Tracking

**VERDICT: ISSUES — a real (PRE-EXISTING) gap, but NOT caused by this session's PRs.**

- The MAIN `dispatch()` path is fully tracked: `BridgeDispatcher._log_execution()`
  (`department_dispatcher.py:3746`, INSERT :3822) writes `task_execution_log` (TEL) with real
  prompt/completion tokens. Live: 17,915 rows / 4.34M tokens / 24h, correct per-node attribution.
- **The QUEUE-drain path bypasses it.** `model_dispatch_service._execute_task` calls
  `disp._dispatch_to_node()` / `disp._execute_llm()` DIRECTLY — those only *return* token dicts; they
  do NOT call `_log_execution`. The worker writes tokens only to `dispatch_pending_queue.result_tokens`
  (`_mark_done`, :480), which **no dashboard reads**.
- Token Economy (`code_health_routes.py:221`) and ARMADA dispatch feed (`dispatch_routes.py:472…`)
  both read TEL only. So queue-drained dispatches are **invisible** in Token Economy + ARMADA.
- The 199 healthy 7B successes I cited earlier are in TEL because they came via `wtf_dhq_*` →
  `dispatch()` directly, NOT via the queue worker. (My earlier "tracking INTACT" was right for the
  main path, wrong for the queue path.)

### [HIGH/tracking-gap] Queue-drained dispatches never reach task_execution_log
- Evidence: TEL rows `module_source ILIKE '%model_dispatch%'` = **0 ever**; yet
  `dispatch_pending_queue` = 1,384 done / 209,001 tokens / 24h (incl. 7B node rows, e.g. id 46469
  qwen2.5:7b node 115 → 296 tok). ~7% of dispatch volume silently uncounted.
- Fix: after a successful `_dispatch_to_node`/`_execute_llm` in `_execute_task`, build a DispatchResult
  and call `disp._log_execution(...)` (module_id=source_product, node_used_id=node_id) — OR add a TEL
  INSERT in `_mark_done`.

### [INFO/no-regression] #1516/#1517/#1518 did NOT alter tracking
- The PRs change readiness/routing, not logging. `_dispatch_to_node` already returned
  prompt/completion tokens pre-PR. The only token line (`node_tokens`, :885) writes `result_tokens`
  (was hardcoded 0 — an improvement). The gap PREDATES these PRs.

### [MEDIUM/display-corruption] Broken current_load corrupts the ARMADA node-load gauge
- Displayed `fleet_dashboard_routes.py:2060` (`"load": current_load`), aggregated
  `fleet_node_routes.py:746` (SUM total_load). Does NOT corrupt token/welfare (those read TEL/task counts).
- Fix: reconcile from queue running-count (pattern exists in `reconcile_task_counters`).

### [MEDIUM/observability-gap] Cold-load / warm-boot events are not tracked
- `_requeue_cold` only `log.warning`s — no DB row. Cold-load frequency is not queryable in any dashboard.
- Fix: `dispatch_pending_queue.metadata.requeue_count` and/or a TEL `task_type='cold_requeue'` row.
