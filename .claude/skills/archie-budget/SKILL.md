---
name: archie-budget
description: Audit and fix A.R.C.H.I.E. agent budget counters — check drift, show blocked agents, manually trigger reconciliation, query bridge_jobs in-flight, inspect system_notifications for overcommit alerts. Invoke when an agent is unexpectedly missing from dispatch, when the user asks about budget/overcommit, or as part of platform triage.
---

# A.R.C.H.I.E. Agent Budget Audit

Operational skill for the post-2026-04-18 counter decrement pattern. See KB `vault_note` #256952 for the full design.

## Current invariant (after migration + decrement fix)

- `agent_budgets.current_task_count` increments when a dispatch starts
- Decrements when the dispatch finishes (`complete_job()` for job-tracked, in-line for immediate)
- `fleet_jobs.budget_reconciliation` runs hourly as a safety net
- Counter should track real-time in-flight `bridge_jobs` count almost exactly

## Check drift (one query does it all)

```sql
WITH real_inflight AS (
  SELECT agent_name, COUNT(*) AS actual
  FROM bridge_jobs
  WHERE status NOT IN ('completed', 'failed', 'cancelled')
  GROUP BY agent_name
)
SELECT a.name, ab.current_task_count AS counter, ab.task_queue_limit AS limit,
       COALESCE(r.actual, 0) AS actually_inflight,
       ab.current_task_count - COALESCE(r.actual, 0) AS drift,
       CASE WHEN ab.current_task_count >= ab.task_queue_limit THEN 'BLOCKED' ELSE 'ok' END AS dispatch_state
FROM agents a
JOIN agent_budgets ab ON ab.agent_id = a.id
WHERE ab.current_task_count > 0
ORDER BY drift DESC, ab.current_task_count DESC;
```

**Normal**: `drift = 0` across the board.
**Mild drift**: +1 or +2 on a few agents — tolerable, reconciler catches hourly.
**Serious drift**: any agent with `drift >= 5` OR `dispatch_state = BLOCKED` — investigate.

## Manually trigger reconciliation

```python
from services.agent_service import reconcile_task_counters
corrected = reconcile_task_counters()
# Returns {agent_name: {new_count, drift_corrected}} for each corrected row
```

Or, via the fleet job (same effect):
```python
from services.fleet_jobs import budget_reconciliation
budget_reconciliation()
```

## Why is agent X blocked?

Walk this checklist:

1. **Is the drift real?** — run the drift query. If drift is high and actual in-flight is 0, it's counter drift. Reconcile and watch.
2. **Is there actual load?** — if `actual_inflight > 0`, those jobs are real. Show them:
   ```sql
   SELECT id, status, description, created_at, agent_name
   FROM bridge_jobs
   WHERE agent_name = '<agent>' AND status NOT IN ('completed','failed','cancelled')
   ORDER BY created_at DESC;
   ```
3. **Is `task_queue_limit` too low?** — check against agent's role. Director agents may warrant 20 instead of 10. Default is 10; change via:
   ```sql
   UPDATE agent_budgets SET task_queue_limit = 20 WHERE agent_id = (SELECT id FROM agents WHERE name = '<agent>');
   ```
4. **Is decrement broken for a new code path?** — if drift climbs continuously, something is incrementing without a paired decrement. Search:
   ```bash
   grep -rn "increment_budget\|_increment_agent_budget" platform_v2/ ai_bridge/
   grep -rn "decrement_budget" platform_v2/ ai_bridge/
   # Every increment site needs a decrement in the same logical flow.
   ```

## Check recent reconciliation runs

```sql
SELECT created_at, status, items_processed, items_failed, details
FROM autonomy_loop_log
WHERE job_name = 'budget_reconciliation'
ORDER BY created_at DESC LIMIT 5;
```

- `items_processed` = agents whose counter was corrected
- `items_failed` = agents still blocked after reconciliation (actual overcommit, not drift)

## Check overcommit alerts (Dept HQ / K.I.N. notifications)

```sql
SELECT created_at, priority, title, LEFT(message, 200) AS msg
FROM system_notifications
WHERE source = 'budget_reconcile'
ORDER BY created_at DESC LIMIT 10;
```

Any rows = reconciler found agents genuinely over their queue limit. Needs investigation:
- Is load real? Look at recent `bridge_jobs` for that agent
- Is the limit too low for their role? Raise `task_queue_limit`
- Are they the only agent with that capability? Consider a peer hire (see `/archie-agent`)

## Emergency manual reset

If a wrong fix broke the decrement and counters are racing away:

```sql
-- Nuclear option: reset everyone's counter to match actual in-flight.
WITH real_inflight AS (
  SELECT agent_name, COUNT(*) AS actual
  FROM bridge_jobs WHERE status NOT IN ('completed','failed','cancelled')
  GROUP BY agent_name
)
UPDATE agent_budgets ab
SET current_task_count = COALESCE(r.actual, 0), updated_at = NOW()
FROM agents a
LEFT JOIN real_inflight r ON r.agent_name = a.name
WHERE ab.agent_id = a.id;
```

Reversible, safe, no data lost.

## Related

- `/archie-status` — platform-wide view that includes budget drift section
- `/archie-agent` — inspect per-agent welfare + propose peer hire if chronic overcommit
- `/archie-patterns` — increment/decrement pair rules (mandatory for new dispatch code)

## Rules

- **Counter drift is a bug** — if you see persistent drift, find the missing decrement. Don't just repeatedly reset.
- **Raising `task_queue_limit` is a last resort** — first verify load is real, THEN consider if a peer hire is the better answer.
- **Don't run the reconciler in a tight loop** — it's hourly by design. Manual run is fine for debugging; looping it is cargo-culting.
