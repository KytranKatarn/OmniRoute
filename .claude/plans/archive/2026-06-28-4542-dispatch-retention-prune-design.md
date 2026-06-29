# #4542 — bridge_jobs + dispatch_pending_queue retention/prune job

**Date:** 2026-06-28 | **Author:** Claude (Opus) | **Task:** #4542

## Problem
- `bridge_jobs`: **558,265 rows**, Feb 19→now. 89% (496k) are terminal & >7d old. Unbounded growth; slows DISPATCH-subtab history endpoints (~4s).
- `dispatch_pending_queue` (dpq): **104,012 rows**, May 1→now. ~104k terminal.

## Live schema facts (verified via psql)
- **bridge_jobs.status** present: `completed`(401k) `failed`(157k) `cancelled`(58) `running`(3 active).
  - Terminal allowlist (prune): `completed, failed, cancelled, error, expired, timeout, rejected`.
  - Never prune: `running, pending, pending_approval, interrupted` (+ any unknown/new) — **allowlist, not denylist**.
  - Age column: `created_at` (indexed `idx_bridge_jobs_created`).
  - FKs IN: `task_execution_log.job_id` + `media_generation_queue.bridge_job_id` → both **ON DELETE SET NULL** (safe, no cascade/block). `replay_of` = plain int, 0 live replay targets → no orphan risk.
- **dpq.status** present: `done`(36k) `failed`(60k) `expired`(8k).
  - Terminal allowlist: `done, failed, expired, cancelled, completed, error`.
  - Never prune: `queued, running, claimed, pending` (+ unknown).
  - Age column: `queued_at` (NO index → migration adds `idx_dpq_queued`).

## Read-window safety (retention must exceed largest read window)
| Reader | window | effect of prune |
|---|---|---|
| `dispatch_health_service.dispatch_health()` | 24h (caller-set) | unaffected |
| `fleet_dispatch_routes.py` metrics | 1h / 24h | unaffected |
| `user_profile/routes.py:822` dashboard | **30 days** ← largest bounded | retention 45d keeps it intact |
| `approvals_routes`, `fleet_mission_routes` | unbounded | only lose old terminal history (intended) |
| `job_recovery_service` | `running`/`interrupted` only | unaffected (non-terminal preserved) |
| `model_dispatch_service` (dpq) | non-terminal only | unaffected |
| `fleet_dashboard/fleet_orchestration` (dpq) | unbounded | only lose old terminal history (intended) |

## Design

### Defaults (TUNABLE via `platform_settings`, no deploy to change — merge pattern)
- `retention:enabled` = `true`
- `retention:bridge_jobs:keep_days` = **45** (> 30d dashboard window)
- `retention:dpq:keep_days` = **30**
- `retention:batch_size` = **5000**
- After each run, write `retention:last_run` (ts + per-table deleted counts) for visibility.

### New files
1. **`platform_v2/services/dispatch_retention_service.py`** — pure, testable:
   - `TERMINAL_BRIDGE`, `TERMINAL_DPQ` allowlists (constants).
   - `_load_config(cur)` → merges platform_settings over defaults.
   - `prune_table(cur, table, status_col_vals, age_col, keep_days, batch_size, dry_run)` → batched `DELETE ... WHERE id IN (SELECT id ... WHERE status = ANY(%s) AND <age_col> < NOW()-(%s||' days')::interval ORDER BY id LIMIT %s)`, commit per batch, loop until <batch_size, return count. `dry_run` → COUNT only, no delete.
   - `run_retention(dry_run=False)` → opens DB, loads config, prunes both tables, writes `retention:last_run`, logs counts, returns dict.

### New migration
2. **`database/migrations/NNN_dpq_queued_index.sql`** — `CREATE INDEX IF NOT EXISTS idx_dpq_queued ON dispatch_pending_queue (queued_at);` (idempotent).

### Job registration
3. **`platform_v2/tools/department_hq/jobs.py`** — register `dispatch_retention_prune` alongside `job_recovery_reaper`:
   `CronTrigger(hour=3, minute=15, timezone="America/Toronto")` (nightly, after zombie_reaper/job_recovery have reclassified stale `running`). `max_instances=1, coalesce=True, replace_existing=True`. Guards on `retention:enabled`. Also add the key to `work_control_service` so it shows in the Autonomy → Backlog & Jobs Control Center toggle.

### Tests
4. **`platform_v2/tests/test_dispatch_retention.py`** — mirror `test_delegation_fail_fast.py` style:
   - non-terminal rows (`running`/`queued`/`interrupted`) NEVER selected even when old.
   - age boundary: row at `keep_days` kept, older pruned.
   - batch loop terminates; returns correct count.
   - `dry_run=True` deletes nothing.
   - config merge: platform_settings overrides defaults; cap≤0 / disabled = no-op.

## Initial big cleanup (deploy step, manual + observed)
First nightly run will batch-delete ~490k bridge_jobs rows (≈100 batches × 5k, committing each → no long lock). To reclaim disk + refresh planner stats (what actually speeds the DISPATCH endpoints), run once manually after first prune:
`docker exec archie_database psql -U archie -d archie -c "VACUUM (ANALYZE) bridge_jobs; VACUUM (ANALYZE) dispatch_pending_queue;"`
(VACUUM can't run inside the job's txn — manual deploy step.)

## Out of scope / not doing
- No LLM/dispatch (pure DB maintenance — module-work-pattern compliant, like `reap_stale_pending_approvals`).
- No change to any read query, status vocabulary, or the existing reapers.
- `#4542` only covers retention; the ~4s DISPATCH history endpoints get faster as a side effect of the smaller table + VACUUM ANALYZE (no endpoint rewrite here).

## Ship sequence
branch `fix/4542-dispatch-retention-prune` → migration + service + job + tests → run tests → deploy (restart `archie_platform` + `archie_scheduler`) → first prune + VACUUM ANALYZE → verify row counts + endpoint latency → PR → F.O.R.G.E. review → merge → Dev HQ complete_task + log_decision + KB doc.
