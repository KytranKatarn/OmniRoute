# Media Studio Layer 6 -- Chunk 1 (Backend) Plan Review

**Reviewer**: Senior Code Reviewer (Opus 4.6)
**Date**: 2026-03-13
**Plan**: `docs/superpowers/plans/2026-03-13-media-studio-layer6-batch.md`
**Spec**: `docs/superpowers/specs/2026-03-13-media-studio-layer6-batch-design.md`
**Scope**: Tasks 1-7 (Backend)

---

## What Was Done Well

- Task 1 migration SQL is fully idempotent (IF NOT EXISTS, DO $$ block) -- matches platform conventions.
- Task 2 validation is thorough: media type check, 50-item cap, sweep_param whitelist, auto-naming.
- Task 5 correctly identifies the exact INSERT statement and hook locations in the existing code.
- Task 6 provides all 10 spec-required API routes with complete, copy-pasteable code.
- Test commands in Tasks 2-4 are real validation tests with assertions, not just smoke tests.
- All code follows the `from database import get_db_cursor` pattern consistently.

---

## Issues (Must Fix)

### Issue 1: Task 5 -- `on_generation_failed` missing queue row SELECT

**Severity**: Critical (runtime NameError)

The plan adds a batch counter hook to `on_generation_failed()` that references `queue_entry.get("batch_id")`. However, the existing `on_generation_failed()` (line 305-315 of generation_service.py) does NOT fetch the queue row -- it just does a blind UPDATE:

```python
def on_generation_failed(queue_id: int, error: str) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE media_generation_queue SET status = 'failed', error_message = %s, completed_at = NOW() WHERE id = %s",
            (error, queue_id),
        )
```

There is no `queue_entry` variable. The hook code will crash with a `NameError`.

**Fix**: Add a SELECT before the UPDATE to fetch `batch_id`:

```python
cur.execute("SELECT batch_id FROM media_generation_queue WHERE id = %s", (queue_id,))
row = cur.fetchone()
# ... existing UPDATE ...
if row and row.get("batch_id"):
    # batch counter hook
```

### Issue 2: Task 7 -- Wrong APScheduler pattern

**Severity**: Critical (jobs will not register)

The plan uses `@scheduler.task("interval", ...)` decorator syntax, which is Flask-APScheduler. The platform uses **plain APScheduler** `BackgroundScheduler` with `scheduler.add_job()` calls, as seen in `app.py` lines 3464-3761. The actual pattern is:

```python
scheduler = BackgroundScheduler(timezone="America/Toronto")
scheduler.add_job(func, IntervalTrigger(hours=1), id="media_queue_cleanup", misfire_grace_time=300)
```

The plan also does not specify WHERE in `app.py` the new scheduler init gets called. The existing pattern is `init_consciousness_scheduler(flask_app)` called at module level in `app.py` (line 3773). Media Studio needs either:
- (A) Its own `init_media_scheduler(flask_app)` function called from `app.py`, or
- (B) Jobs added to the existing consciousness scheduler via `app.config["CONSCIOUSNESS_SCHEDULER"]`

**Fix**: Rewrite Task 7 to use `scheduler.add_job()` with `IntervalTrigger`, and add a step to modify `app.py` to call the registration function.

### Issue 3: Task 4 -- `cleanup_expired_exports` wrapper function body missing

**Severity**: Important (ImportError at runtime)

Task 7 imports `from .services.batch_service import cleanup_expired_exports`. Task 4 mentions this function wraps `export_service.cleanup_exports()`, but the plan does not include the actual function body in the code to be appended. If the implementer follows the plan literally, this function will not exist in `batch_service.py` and Task 7's import will fail.

**Fix**: Add the wrapper function explicitly in Task 4:

```python
def cleanup_expired_exports():
    """Wrapper for export_service cleanup, called by APScheduler."""
    from .export_service import cleanup_exports
    return cleanup_exports()
```

---

## Important (Should Fix)

### Issue 4: Task 5 -- Spec vs Plan conflict on `submit_generation` signature

The **spec** says: "the existing `user_id` parameter is renamed to `owner_id`." The **plan** keeps `user_id` as-is and just appends `batch_id`. The plan's approach is actually correct -- the existing code (line 77-85) already has both `user_id` AND `owner_type`/`owner_id`, so renaming would be a breaking change. But the plan should add a note: "Spec mentions renaming user_id -- ignore; the current signature already handles owner_type/owner_id alongside user_id."

### Issue 5: Task 2 -- `expand_batch` does not pass `owner_type` to `submit_generation`

The call in `expand_batch` is:
```python
result = submit_generation(
    user_id=owner_id,
    media_type=media_type,
    prompt=prompt,
    params=item_params,
    batch_id=batch_id,
)
```

This never passes `owner_type` or `owner_id` explicitly. For user batches it works (defaults to `owner_type="user"`), but for agent-owned batches (`owner_type="agent"`) the type will be wrong.

**Fix**: Add `owner_type=owner_type, owner_id=owner_id` to the call.

### Issue 6: Task 3 -- `update_batch_counters` race condition

The function reads counts and updates status in separate queries. Under concurrent completions, two workers could both calculate the same counts. Consider using a single atomic UPDATE ... FROM (SELECT COUNT...) query, or note that eventual consistency is acceptable since the next completion will self-correct.

---

## Suggestions (Nice to Have)

### Suggestion 1: Task 6 route imports

The route code uses `request`, `current_user`, `jsonify` -- all presumably imported at the top of `routes.py`. The plan says "add after the existing export routes section" which implies these exist. A one-line note confirming this would prevent confusion.

### Suggestion 2: Test cleanup

Tests in Tasks 2-4 create real DB rows but do not clean them up. Consider wrapping in a transaction rollback or adding DELETE cleanup at the end of each test script.

---

## Route Checklist (Task 6 vs Spec)

| # | Spec Route | Plan Function | Present |
|---|-----------|--------------|---------|
| 1 | POST /api/batches | api_create_batch | YES |
| 2 | GET /api/batches | api_list_batches | YES |
| 3 | GET /api/batches/<id> | api_get_batch | YES |
| 4 | POST /api/batches/<id>/cancel | api_cancel_batch | YES |
| 5 | POST /api/batches/<id>/retry | api_retry_batch | YES |
| 6 | GET /api/queue | api_queue_entries | YES |
| 7 | POST /api/queue/<id>/retry | api_retry_queue_item | YES |
| 8 | POST /api/queue/<id>/cancel | api_cancel_queue_item | YES |
| 9 | GET /api/queue/stats | api_queue_stats | YES |
| 10 | POST /api/queue/clear-completed | api_clear_completed | YES |

All 10 routes accounted for.

---

## Verdict: NEEDS_FIXES

**3 must-fix issues** before this plan is ready for implementation:
1. **Issue 1** -- `on_generation_failed` hook will crash with NameError (missing SELECT)
2. **Issue 2** -- APScheduler pattern uses wrong API (Flask-APScheduler vs plain APScheduler)
3. **Issue 3** -- `cleanup_expired_exports` function body missing from Task 4

Additionally, Issues 4-6 (should fix) will cause bugs for agent-owned batches and potential race conditions.

All fixes are straightforward -- none require architectural changes to the plan.
