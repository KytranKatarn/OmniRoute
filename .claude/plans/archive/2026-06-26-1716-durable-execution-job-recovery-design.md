# Durable Execution — Interrupted-Job Recovery (Task #1716, slice 1)

**Date:** 2026-06-26
**Task:** #1716 (project #234 "Competitive Feature Gaps") — LangGraph durable-execution / checkpointing parity
**Status:** Approved design — ready for implementation plan
**Scope decision:** Slice 1 — crash-recovery + replay for `bridge_jobs` (additive, off the synchronous dispatch hot path).

---

## 1. Motivation & discovery

LangGraph's killer feature is durable execution: long-running agent workflows checkpoint, resume on crash/restart, and replay from the last checkpoint. #1716 asks for parity in the bridge dispatch pipeline.

**Discovery (what already exists — verify-before-build):**
- State IS persisted: `orchestration_sessions` + `orchestration_steps` record each of the 8 engine steps; `bridge_jobs` tracks `total_steps`/`completed_steps`/`failed_steps`/`status` + a `metadata` JSONB. A `workflow_*` subsystem also exists.
- **The gap is recovery, not persistence:** nothing reads that state back to resume/replay. On restart, `app.py:2996` **force-fails** in-flight jobs (`status='failed', error_message='Cleared on restart'`) — interrupted work is silently marked failed.
- `bridge_jobs` has **no status CHECK constraint** → `interrupted` is free to introduce.
- `bridge_jobs` is a **542K-row hot table** (388K completed / 154K failed / 4 running) → migrations must be nullable ALTERs (no rewrite).
- There is **no generic job-runner**: jobs are executed inline by their callers, so generic "replay execution" is impossible — replay is job-type-specific.

## 2. Goal & non-goals

**Goal:** Crash-orphaned and stale `bridge_jobs` are marked `interrupted` (not silently failed) with a checkpoint, surfaced via API, and replayable — re-entrant dispatcher jobs re-execute; other job_types clone to `pending` and are flagged for a handler (honest, no fake re-run).

**Non-goals (this slice):**
- Per-job-type resume handlers / true mid-step resume (follow-up).
- Mid-pipeline checkpointing inside `orchestration_engine` (slice 2).
- Time-travel / replay-from-arbitrary-checkpoint, human-in-loop interrupts.
- A DHQ UI tab (endpoints only this slice).

## 3. Architecture

Four additive units; the only edit to existing hot code is swapping one restart-cleanup call.

### 3.1 Migration `NNN_job_recovery.sql`
- `ALTER TABLE bridge_jobs ADD COLUMN IF NOT EXISTS replay_of INTEGER` (self-reference to the original job id; no FK constraint to avoid lock on the hot table).
- `ADD COLUMN IF NOT EXISTS replayed_at TIMESTAMPTZ`.
- `ADD COLUMN IF NOT EXISTS checkpoint JSONB`.
- `CREATE INDEX IF NOT EXISTS idx_bridge_jobs_status_updated ON bridge_jobs (status, updated_at)` (powers the stale reaper).
- All nullable, no defaults → no table rewrite on 542K rows. `interrupted` is a new status string (no constraint to alter).

### 3.2 `services/job_recovery_service.py` (new, isolated, unit-testable)
Pure-ish functions taking a DB cursor (mockable):
- `mark_interrupted_on_restart(cur) -> int` — `UPDATE bridge_jobs SET status='interrupted', checkpoint=jsonb_build_object('completed_steps',completed_steps,'total_steps',total_steps,'reason','restart'), updated_at=NOW() WHERE status='running'`. Returns rows affected.
- `reap_stale_running(cur, max_age_min=20) -> int` — same transition for `status='running' AND updated_at < NOW() - interval`. For orphans without a full restart.
- `list_interrupted(cur, limit=50) -> list[dict]` — interrupted jobs with id/job_type/module_source/checkpoint/created_at.
- `replay_job(cur, job_id) -> dict` — load the interrupted/failed job; INSERT a new `bridge_jobs` row copying `job_type/module_source/description/metadata`, `status='pending'`, `replay_of=job_id`, `checkpoint` carried forward; stamp `replayed_at` on the original. If `job_type` is a known re-entrant dispatcher capability → call `department_dispatcher.dispatch(...)` to actually re-run; else set `metadata.replay_needs_handler=true` and leave the clone `pending` (NOT executed). Returns `{new_job_id, executed: bool, needs_handler: bool}`.

`RE_ENTRANT_JOB_TYPES` = a small allowlist (start with the dispatcher capability job types) so we never auto-execute something side-effectful we don't understand.

### 3.3 Wire-in
- `app.py` restart path (~line 2996): replace the blanket force-fail with `mark_interrupted_on_restart(cur)`. (Truly unrecoverable rows still age out via the reaper / can be failed manually.)
- New APScheduler job `job_recovery_reaper` (every 10 min, `timezone="America/Toronto"`) → `reap_stale_running(cur, 20)`. Registered like the existing `reap_stale_pending_approvals`.

### 3.4 Routes (`dispatch_routes.py`)
- `GET /api/dispatch/interrupted-jobs` → `list_interrupted`.
- `POST /api/dispatch/replay-job/<int:job_id>` → `replay_job`; returns the new job id + whether it executed or needs a handler.

## 4. Testing
`platform_v2/tests/test_job_recovery_service.py` with a fake/stub cursor (no live DB writes):
1. `mark_interrupted_on_restart` issues the running→interrupted UPDATE and returns the rowcount.
2. `reap_stale_running` includes the `updated_at` age predicate.
3. `replay_job` on a re-entrant job_type → inserts a `pending` clone with `replay_of` + carried `checkpoint`, stamps `replayed_at`, and dispatches (dispatch mocked).
4. `replay_job` on a non-re-entrant job_type → clone is `pending` + `metadata.replay_needs_handler=true`, dispatch NOT called.

## 5. Risks & mitigations
- **Hot-table migration:** nullable ALTERs + `IF NOT EXISTS` index → no rewrite, no lock storm. Verify on a count first.
- **Changing restart behavior:** the swap is one call; interrupted jobs are recoverable, and the reaper + manual-fail still drain unrecoverable ones. No job is lost vs today (today they're force-failed; now they're interrupted = strictly more recoverable).
- **Accidental re-execution of side-effectful jobs:** `RE_ENTRANT_JOB_TYPES` allowlist — anything not on it is cloned-pending + flagged, never auto-run.
- **Off the hot path:** no change to the synchronous `dispatch()` execution path; recovery runs in a reaper + on restart only.

## 6. Out-of-scope follow-ups (file after slice 1)
1. Per-job-type resume handlers (true mid-step resume) — register handlers keyed by `job_type` that read `checkpoint` and resume.
2. Slice 2 — mid-pipeline checkpointing in `orchestration_engine` (resume an interrupted 8-step session from the last step).
3. DHQ Autonomy/Dispatch UI: interrupted-jobs panel + replay button.
4. Time-travel / replay-from-arbitrary-checkpoint; human-in-loop interrupts.
