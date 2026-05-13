# Consciousness Job System Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `consciousness_analysis_batch()` from generating failed bridge_jobs when the analysis server loop is disabled, and purge the 71 stale failure records.

**Architecture:** Single function replacement in `jobs.py` — add `get_server_loops()` guard identical to the embedding batch job. Two one-time SQL deletes clean up stale DB state. No schema changes, no new files.

**Tech Stack:** Python (consciousness/jobs.py), PostgreSQL (bridge_jobs, system_config).

---

## File Map

| File | Action |
|------|--------|
| `platform_v2/tools/consciousness/jobs.py` | Replace `consciousness_analysis_batch()` — add disabled flag guard |
| PostgreSQL (via docker exec) | Delete stale bridge_jobs + system_config retry tracking |

---

## Task 1: Add Disabled Flag Guard to Job #49

**Files:**
- Modify: `platform_v2/tools/consciousness/jobs.py` (line 223 — `consciousness_analysis_batch`)

- [ ] **Step 1: Confirm current state**

```bash
grep -n "def consciousness_analysis_batch\|get_server_loops\|analysis" \
  platform_v2/tools/consciousness/jobs.py | head -10
```

Expected: `consciousness_analysis_batch` at line ~223, no `get_server_loops` import inside it.

- [ ] **Step 2: Replace the function**

Find the entire `consciousness_analysis_batch()` function. It currently looks like:

```python
def consciousness_analysis_batch():
    """Job #49: Trigger consciousness analysis batch every 6 hours via DHQ.

    APScheduler is the sole gate — server_loops.analysis flag controls HTTP
    endpoint triggers only (UI buttons). This job always runs on schedule.
    Dispatches to Analytics & Intelligence (W.A.T.C.H.) via knowledge_analyzer.
    """
    import time as _time

    start = _time.time()
    try:
        from tools.consciousness.processing_routes import _trigger_loop_op

        logger.info("[ConsciousnessAnalysis] Triggering scheduled analysis batch")
        _trigger_loop_op("analysis")
        _log_cycle(
            "consciousness_analysis",
            1,
            0,
            int((_time.time() - start) * 1000),
            department="Analytics & Intelligence",
        )
    except Exception as e:
        logger.warning(f"[ConsciousnessAnalysis] Analysis batch failed: {e}")
        _log_cycle(
            "consciousness_analysis",
            0,
            1,
            int((_time.time() - start) * 1000),
            error_message=str(e),
            department="Analytics & Intelligence",
        )
```

Replace it with:

```python
def consciousness_analysis_batch():
    """Job #49: Trigger consciousness analysis batch every 6 hours.

    Only runs if the analysis server loop is enabled in system_config.
    Uses _trigger_loop_op() from processing_routes which handles item
    selection, job creation, and background threading.
    """
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
            "consciousness_analysis",
            1,
            0,
            int((_time.time() - start) * 1000),
            department="Analytics & Intelligence",
        )
    except Exception as e:
        logger.warning(f"[ConsciousnessAnalysis] Analysis batch failed: {e}")
        _log_cycle(
            "consciousness_analysis",
            0,
            1,
            int((_time.time() - start) * 1000),
            error_message=str(e),
            department="Analytics & Intelligence",
        )
```

- [ ] **Step 3: Verify embedding batch for reference (pattern match)**

```bash
grep -n -A20 "def consciousness_embedding_batch" platform_v2/tools/consciousness/jobs.py | head -22
```

The `if not loops.get("embedding"):` guard should match the new `if not loops.get("analysis"):` pattern structurally.

- [ ] **Step 4: Syntax check**

```bash
python3 -m py_compile platform_v2/tools/consciousness/jobs.py && echo "SYNTAX OK"
```

Expected: `SYNTAX OK`

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/consciousness/jobs.py
git commit -m "fix(consciousness): add disabled flag guard to analysis_batch — stops false bridge_job failures"
```

---

## Task 2: DB Cleanup

**No files changed — SQL only (run via docker exec)**

- [ ] **Step 1: Check bridge_jobs failure count before cleanup**

```bash
docker exec archie_database psql -U archie -d archie -t -c "
SELECT status, COUNT(*) FROM bridge_jobs
WHERE module_source LIKE '%consciousness%'
GROUP BY status ORDER BY COUNT(*) DESC;
"
```

Note the current count for comparison.

- [ ] **Step 2: Delete stale failed bridge_jobs**

```bash
docker exec archie_database psql -U archie -d archie -c "
DELETE FROM bridge_jobs
WHERE status = 'failed'
  AND module_source LIKE '%consciousness%'
  AND created_at < NOW() - INTERVAL '7 days';
"
```

Expected: `DELETE N` where N ≥ 71.

- [ ] **Step 3: Clear consciousness_loop_retries tracking**

```bash
docker exec archie_database psql -U archie -d archie -c "
DELETE FROM system_config
WHERE key LIKE 'consciousness_loop_retries%';
"
```

Expected: `DELETE 2` (embedding + analysis retry rows).

- [ ] **Step 4: Verify bridge_jobs count dropped**

```bash
docker exec archie_database psql -U archie -d archie -t -c "
SELECT status, COUNT(*) FROM bridge_jobs
WHERE module_source LIKE '%consciousness%'
GROUP BY status ORDER BY COUNT(*) DESC;
"
```

Expected: the `failed` row is gone or much smaller (only recent failures).

No commit needed — DB only.

---

## Task 3: Deploy, Verify, PR

- [ ] **Step 1: Restart scheduler**

```bash
docker compose restart archie_scheduler
sleep 12
docker logs archie_scheduler 2>&1 | grep -iE "consciousness|error" | tail -10
```

Expected: no errors. 74 jobs registered.

- [ ] **Step 2: Verify analysis batch skips when disabled**

Trigger the job manually to confirm the skip path:

```bash
docker exec archie_scheduler python3 -c "
import sys; sys.path.insert(0, '/mnt/archie_brain/platform_v2')
from tools.consciousness.jobs import consciousness_analysis_batch
consciousness_analysis_batch()
print('Done — check logs above for [ConsciousnessAnalysis] Analysis loop disabled')
" 2>&1 | grep -E "ConsciousnessAnalysis|Done"
```

Expected: `[ConsciousnessAnalysis] Analysis loop disabled — skipping`

- [ ] **Step 3: Confirm autonomy_loop_log shows 0 failures**

```bash
docker exec archie_database psql -U archie -d archie -t -c "
SELECT job_name, status, items_failed, created_at
FROM autonomy_loop_log
WHERE job_name = 'consciousness_analysis'
ORDER BY created_at DESC LIMIT 5;
"
```

Expected: recent rows show `items_failed=0`.

- [ ] **Step 4: Create feature branch and push**

```bash
git checkout -b fix/consciousness-analysis-job-flag-guard
git push -u origin fix/consciousness-analysis-job-flag-guard
```

- [ ] **Step 5: Open PR**

```bash
gh pr create \
  --title "fix(consciousness): analysis_batch disabled flag guard — stops 71 bridge_job failures/week" \
  --body "$(cat <<'EOF'
## Summary
- `consciousness_analysis_batch()` (Job #49) ignored the `consciousness_server_loops.analysis = false` system_config flag, calling `_trigger_loop_op("analysis")` unconditionally → 71 failed bridge_jobs in 7 days
- Fixed by adding `get_server_loops()` guard identical to `consciousness_embedding_batch()` (Job #50)
- Purged stale failed bridge_jobs and consciousness_loop_retries tracking rows from DB

## Files changed
- `platform_v2/tools/consciousness/jobs.py` — replaced `consciousness_analysis_batch()` with guarded version

## Test plan
- [ ] Manual trigger of analysis batch shows "Analysis loop disabled — skipping" in logs
- [ ] No new failed bridge_jobs generated for consciousness after restart
- [ ] autonomy_loop_log shows items_failed=0 for consciousness_analysis

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- Add disabled flag check to Job #49: Task 1 ✅
- Use `get_server_loops()` from processing_routes: Task 1 Step 2 ✅
- Pattern matches embedding batch: Task 1 Step 3 ✅
- Delete stale bridge_jobs: Task 2 Step 2 ✅
- Clear consciousness_loop_retries: Task 2 Step 3 ✅

**Placeholder scan:** No TBD, no TODO. Full function replacement shown. SQL commands exact.

**Type consistency:** `get_server_loops()` used consistently throughout. `loops.get("analysis")` matches key used in system_config `consciousness_server_loops.analysis`. `_log_cycle` signature unchanged.
