# Consciousness Job System Cleanup

**Date:** 2026-05-13
**Task:** #2773 — Project Alpha
**Scope:** Stop Job #49 (analysis batch) from generating bridge_jobs failures when the server loop is disabled. Clean up stale DB records.

---

## Context

All three consciousness server loops (embedding, analysis, translate) are already disabled:
`consciousness_server_loops = {"analysis": false, "embedding": false, "translate": false}`

Job #50 (`consciousness_embedding_batch`) already checks this flag and returns early.
Job #49 (`consciousness_analysis_batch`) ignores the flag → calls `_trigger_loop_op()` → creates failed bridge_jobs → 71 failures in 7 days → false Repair Bay alerts.

Legacy bridge_dispatcher imports are already migrated. This is purely a missing guard + DB cleanup.

---

## Changes

### 1. Add disabled flag check to Job #49

**File:** `platform_v2/tools/consciousness/jobs.py`

Find `consciousness_analysis_batch()`. The function currently imports only `_trigger_loop_op`. Add `get_server_loops` to the import and add an early-return guard — identical pattern to `consciousness_embedding_batch()`:

```python
def consciousness_analysis_batch():
    """Job #49: Trigger consciousness analysis batch every 6 hours via DHQ."""
    import time as _time
    start = _time.time()
    try:
        from tools.consciousness.processing_routes import (
            get_server_loops,
            _trigger_loop_op,
        )

        loops = get_server_loops()
        if not loops.get("analysis"):
            logger.debug("[ConsciousnessAnalysis] Analysis loop disabled — skipping")
            return

        logger.info("[ConsciousnessAnalysis] Triggering scheduled analysis batch")
        _trigger_loop_op("analysis")
        _log_cycle(
            "consciousness_analysis", 1, 0,
            int((_time.time() - start) * 1000),
            department="Analytics & Intelligence",
        )
    except Exception as e:
        logger.warning(f"[ConsciousnessAnalysis] Analysis batch failed: {e}")
        _log_cycle(
            "consciousness_analysis", 0, 1,
            int((_time.time() - start) * 1000),
            error_message=str(e),
            department="Analytics & Intelligence",
        )
```

**Note:** The old docstring said "APScheduler is the sole gate — server_loops.analysis flag controls HTTP endpoint triggers only." This was incorrect — the flag is the admin's intent to pause the loop. The embedding batch already follows the correct pattern.

### 2. Clean up stale bridge_jobs failures

**One-time SQL** (run via docker exec):

```sql
DELETE FROM bridge_jobs
WHERE status = 'failed'
  AND module_source LIKE '%consciousness%'
  AND created_at < NOW() - INTERVAL '7 days';
```

### 3. Clear consciousness_loop_retries tracking

**One-time SQL** (run via docker exec):

```sql
DELETE FROM system_config
WHERE key LIKE 'consciousness_loop_retries%';
```

---

## Out of Scope

- Refactoring `_trigger_loop_op()` to dispatch to DHQ (future work)
- Removing Jobs #49 and #50 (they may be needed when loops are re-enabled)
- Moving Code Health tab to Repair Bay (separate task)
- The translate loop (0 retries, last success 2026-04-03 — no action needed)

---

## Testing

1. After deploy: verify Job #49 logs a no-op entry when `consciousness_server_loops.analysis = false`
2. Check `autonomy_loop_log` after the 6-hour cycle fires — `consciousness_analysis_batch` should complete with 0 failures
3. Confirm bridge_jobs failure count for consciousness stops growing

---

## Notes

- `get_server_loop_config()` in jobs.py reads from system_config key `consciousness_server_loops` (JSON)
- The early-return pattern is identical to what consciousness_embedding_batch already does
- Code Health tab → Repair Bay relocation will be a separate task
