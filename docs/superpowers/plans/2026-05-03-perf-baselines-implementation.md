# P.R.O.B.E. Performance Baselines + Deploy Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire historical perf baselines + a post-deploy regression gate into P.R.O.B.E. that ties Repair Bay's existing `AutoRollbackManager` to perf regressions, with `paused_for_perf_review` for non-critical regressions.

**Architecture:** New `services/qa_baseline_service.py` exposes pure functions for baseline compute, regression check, and post-deploy evaluation. Three hooks: per-test write (qa_e2e_runner), post-deploy gate (safe_deployment_protocol), pre-claim pause check (sandbox_queue). Nightly agent_loop job refreshes baselines. Four new API endpoints surface state to the future dashboard (Task #1757). Defensive `try/except` throughout — gate must never break the platform.

**Tech Stack:** Python 3.12, Flask, pytest, pytest-mock, psycopg2, PostgreSQL with `percentile_cont`.

**Spec:** `docs/superpowers/specs/2026-05-03-perf-baselines-design.md`

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `platform_v2/database/migrations/NNN_qa_perf_baselines.sql` | NEW | 3 tables + ALTER constraint |
| `platform_v2/services/qa_baseline_service.py` | NEW · ~250 LOC | Pure functions: compute_baseline, recompute_all_baselines, check_regression, decide_action, evaluate_post_deploy |
| `platform_v2/services/qa_e2e_runner.py` | MODIFY · +~10 LOC | Call check_regression after each test, INSERT qa_perf_regressions on trip |
| `platform_v2/services/qa_spec_runner.py` | MODIFY · +~10 LOC | Parse `critical` and `baseline_ms_override` from YAML test entries |
| `platform_v2/tools/repair_bay/services/safe_deployment_protocol.py` | MODIFY · +~30 LOC | Post-deploy: call evaluate_post_deploy + dispatch action |
| `platform_v2/tools/repair_bay/services/sandbox_queue.py` | MODIFY · +~5 LOC | Check pause flag before claiming approved proposal |
| `platform_v2/ai_bridge/agent_loop.py` | MODIFY · +~15 LOC | Register `recompute_perf_baselines` nightly job (03:00 UTC) |
| `platform_v2/services/qa_routes.py` | MODIFY · +~80 LOC | 4 new endpoints |
| `platform_v2/tests/test_qa_baseline_service.py` | NEW · ~250 LOC | 15 unit tests |
| `platform_v2/tests/test_perf_gate_integration.py` | NEW · ~180 LOC | 6 integration tests with mocked AutoRollbackManager |
| `platform_v2/tests/test_qa_baseline_routes.py` | NEW · ~120 LOC | 4 API endpoint tests |

**Migration file numbering:** Find the highest existing migration number under `platform_v2/database/migrations/` and increment. Reference value seen mid-2026: ~368. Use the actual highest at implementation time.

---

## Test runner reminder

Tests run inside the Docker container `archie_platform`. The container mounts the main checkout at `/app`, so tests are at `tests/test_<name>.py` from inside the container. Use:

```bash
docker exec archie_platform pytest tests/test_qa_baseline_service.py -v
```

If working in a worktree (not main checkout), the container does NOT see worktree changes. Either work in main checkout, or use the file-swap pattern documented in `.claude/rules/repair-bay.md` test-runner workaround.

---

## Phase 1 — Foundation (Schema + Helper)

### Task 1: Database migration

**Files:**
- Create: `platform_v2/database/migrations/NNN_qa_perf_baselines.sql`

- [ ] **Step 1: Find next migration number**

```bash
ls platform_v2/database/migrations/ | grep -oE '^[0-9]+' | sort -n | tail -1
```

Use the next integer (e.g., if highest is `368`, use `369`).

- [ ] **Step 2: Create migration file**

Create `platform_v2/database/migrations/369_qa_perf_baselines.sql` (substitute `369` with your actual number):

```sql
-- Migration: P.R.O.B.E. performance baselines + deploy gate
-- Spec: docs/superpowers/specs/2026-05-03-perf-baselines-design.md
-- Task: #1755 (Project #239)

BEGIN;

CREATE TABLE IF NOT EXISTS qa_perf_baselines (
    id              SERIAL PRIMARY KEY,
    suite_id        INTEGER NOT NULL REFERENCES qa_test_suites(id) ON DELETE CASCADE,
    test_name       TEXT NOT NULL,
    baseline_p95_ms INTEGER NOT NULL,
    sample_count    INTEGER NOT NULL,
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(suite_id, test_name)
);

CREATE TABLE IF NOT EXISTS qa_perf_regressions (
    id              SERIAL PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES qa_test_runs(id) ON DELETE CASCADE,
    suite_id        INTEGER NOT NULL,
    test_name       TEXT NOT NULL,
    baseline_ms     INTEGER NOT NULL,
    observed_ms     INTEGER NOT NULL,
    pct_over        INTEGER NOT NULL,
    is_critical     BOOLEAN NOT NULL DEFAULT FALSE,
    action_taken    TEXT,
    proposal_id     INTEGER REFERENCES improvement_proposals(id) ON DELETE SET NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'cleared', 'accepted')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cleared_at      TIMESTAMPTZ,
    cleared_by      TEXT,
    UNIQUE(run_id, test_name)
);

CREATE INDEX IF NOT EXISTS qa_perf_regressions_pending
    ON qa_perf_regressions(status) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS qa_perf_acceptances (
    id          SERIAL PRIMARY KEY,
    suite_id    INTEGER NOT NULL,
    test_name   TEXT NOT NULL,
    accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accepted_by TEXT,
    UNIQUE(suite_id, test_name)
);

-- Extend improvement_proposals.status to include paused_for_perf_review
ALTER TABLE improvement_proposals
    DROP CONSTRAINT IF EXISTS improvement_proposals_status_check;
ALTER TABLE improvement_proposals
    ADD CONSTRAINT improvement_proposals_status_check
    CHECK (status IN ('proposed', 'approved', 'sandboxed', 'deployed',
                      'regression', 'paused_for_perf_review', 'rejected'));

COMMIT;
```

- [ ] **Step 3: Apply migration**

```bash
docker exec archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/369_qa_perf_baselines.sql
```

(Or whatever migration runner the platform uses — check `.claude/rules/database.md`. If a runner script exists like `scripts/run_migration.sh`, use that.)

- [ ] **Step 4: Verify tables exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt qa_perf_*"
```

Expected: 3 tables listed (`qa_perf_baselines`, `qa_perf_regressions`, `qa_perf_acceptances`).

```bash
docker exec archie_database psql -U archie -d archie -c "\d improvement_proposals" | grep status
```

Expected: status column has CHECK constraint that includes `paused_for_perf_review`.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/database/migrations/369_qa_perf_baselines.sql
git commit -m "feat(qa): migration — qa_perf_baselines + regressions + acceptances tables"
```

---

### Task 2: nav_baseline_service — compute_baseline (TDD)

**Files:**
- Create: `platform_v2/services/qa_baseline_service.py`
- Test: `platform_v2/tests/test_qa_baseline_service.py`

- [ ] **Step 1: Write the failing tests**

Create `platform_v2/tests/test_qa_baseline_service.py`:

```python
"""Unit tests for qa_baseline_service."""
import pytest
from services import qa_baseline_service


def test_compute_baseline_returns_none_when_below_min_samples(monkeypatch):
    """Below 10 successful runs → no baseline (returns None, 0)."""
    fake_history = [120, 130, 125]  # only 3 samples
    monkeypatch.setattr(
        qa_baseline_service,
        "_fetch_recent_response_times",
        lambda suite_id, test_name, limit: fake_history,
    )
    p95, count = qa_baseline_service.compute_baseline(suite_id=1, test_name="x")
    assert p95 is None
    assert count == 3


def test_compute_baseline_returns_p95_at_or_above_min_samples(monkeypatch):
    """At ≥10 samples → returns p95 of the window."""
    # 30 samples; p95 = 95th percentile
    fake_history = list(range(100, 130))  # [100..129]
    monkeypatch.setattr(
        qa_baseline_service,
        "_fetch_recent_response_times",
        lambda suite_id, test_name, limit: fake_history,
    )
    p95, count = qa_baseline_service.compute_baseline(suite_id=1, test_name="x")
    assert count == 30
    # p95 of [100..129]: ~127 (numpy.percentile linear interpolation)
    assert 125 <= p95 <= 129


def test_compute_baseline_uses_max_30_window(monkeypatch):
    """Window is capped at 30 most recent samples."""
    captured = {}

    def fake_fetch(suite_id, test_name, limit):
        captured["limit"] = limit
        return list(range(100, 200))[:limit]

    monkeypatch.setattr(
        qa_baseline_service, "_fetch_recent_response_times", fake_fetch
    )
    qa_baseline_service.compute_baseline(suite_id=1, test_name="x")
    assert captured["limit"] == 30
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform pytest tests/test_qa_baseline_service.py -v
```

Expected: 3 tests FAIL with `ModuleNotFoundError: No module named 'services.qa_baseline_service'`.

- [ ] **Step 3: Write minimal implementation**

Create `platform_v2/services/qa_baseline_service.py`:

```python
"""P.R.O.B.E. performance baseline + regression detection.

Pure functions. No Flask import so unit tests run without app context.
Defensive: every public function must never raise into callers (logs + safe default).
"""
from __future__ import annotations

import logging
import statistics
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

MIN_SAMPLES = 10
WINDOW_SIZE = 30


def _fetch_recent_response_times(suite_id: int, test_name: str, limit: int) -> list[int]:
    """Read recent successful response_time_ms for a test from qa_test_results.

    Filters out runs that predate any qa_perf_acceptances.accepted_at for this test.
    Returns [] if database access fails (defensive).
    """
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT r.response_time_ms
                FROM qa_test_results r
                JOIN qa_test_runs tr ON r.run_id = tr.id
                LEFT JOIN qa_perf_acceptances a
                    ON a.suite_id = tr.suite_id AND a.test_name = r.test_name
                WHERE tr.suite_id = %s
                  AND r.test_name = %s
                  AND r.success = TRUE
                  AND r.response_time_ms IS NOT NULL
                  AND (a.accepted_at IS NULL OR r.created_at > a.accepted_at)
                ORDER BY r.created_at DESC
                LIMIT %s
                """,
                (suite_id, test_name, limit),
            )
            return [row[0] for row in cur.fetchall()]
    except Exception as exc:
        logger.warning("_fetch_recent_response_times failed for %s/%s: %s",
                       suite_id, test_name, exc)
        return []


def compute_baseline(
    suite_id: int, test_name: str
) -> Tuple[Optional[int], int]:
    """Compute p95 baseline over most recent successful runs.

    Returns (p95_ms, sample_count). p95_ms is None when sample_count < MIN_SAMPLES.
    """
    samples = _fetch_recent_response_times(suite_id, test_name, WINDOW_SIZE)
    count = len(samples)
    if count < MIN_SAMPLES:
        return None, count
    # statistics.quantiles uses linear interpolation; method="exclusive" matches numpy.percentile default
    quantiles = statistics.quantiles(samples, n=100, method="exclusive")
    p95 = int(round(quantiles[94]))  # quantiles[94] is the 95th percentile
    return p95, count
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec archie_platform pytest tests/test_qa_baseline_service.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/qa_baseline_service.py platform_v2/tests/test_qa_baseline_service.py
git commit -m "feat(qa): qa_baseline_service.compute_baseline with min-sample floor"
```

---

### Task 3: check_regression with YAML override priority (TDD)

**Files:**
- Modify: `platform_v2/services/qa_baseline_service.py`
- Test: `platform_v2/tests/test_qa_baseline_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_qa_baseline_service.py`:

```python
def test_check_regression_returns_false_when_no_baseline(monkeypatch):
    """If baseline doesn't exist (or below min_samples) → no regression."""
    monkeypatch.setattr(
        qa_baseline_service,
        "_get_baseline_record",
        lambda suite_id, test_name: None,
    )
    assert (
        qa_baseline_service.check_regression(
            suite_id=1, test_name="x", observed_ms=99999, override_ms=None
        )
        is False
    )


def test_check_regression_trips_at_2x_baseline(monkeypatch):
    """observed > 2× baseline → regression."""
    monkeypatch.setattr(
        qa_baseline_service,
        "_get_baseline_record",
        lambda suite_id, test_name: {"baseline_p95_ms": 100, "sample_count": 30},
    )
    assert qa_baseline_service.check_regression(1, "x", 250, override_ms=None) is True
    assert qa_baseline_service.check_regression(1, "x", 199, override_ms=None) is False
    assert qa_baseline_service.check_regression(1, "x", 200, override_ms=None) is False


def test_check_regression_uses_override_when_set(monkeypatch):
    """override_ms wins over auto-baseline."""
    # Even if auto-baseline is permissive, override pins the limit
    monkeypatch.setattr(
        qa_baseline_service,
        "_get_baseline_record",
        lambda suite_id, test_name: {"baseline_p95_ms": 100, "sample_count": 30},
    )
    # observed below override threshold → no regression
    assert qa_baseline_service.check_regression(1, "x", 5000, override_ms=10000) is False
    # observed above override threshold → regression (regardless of auto-baseline)
    assert qa_baseline_service.check_regression(1, "x", 11000, override_ms=10000) is True


def test_check_regression_swallows_exceptions(monkeypatch):
    """If anything inside throws, return False — never propagate."""
    def boom(*args, **kwargs):
        raise RuntimeError("db down")
    monkeypatch.setattr(qa_baseline_service, "_get_baseline_record", boom)
    assert qa_baseline_service.check_regression(1, "x", 200, override_ms=None) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform pytest tests/test_qa_baseline_service.py -v
```

Expected: 4 new tests fail (no `check_regression`, no `_get_baseline_record`).

- [ ] **Step 3: Implement check_regression**

Append to `platform_v2/services/qa_baseline_service.py`:

```python
TRIP_THRESHOLD_PCT = 200  # observed > 2× baseline → regression


def _get_baseline_record(suite_id: int, test_name: str) -> Optional[dict]:
    """Read latest baseline row for (suite_id, test_name) from qa_perf_baselines.

    Returns dict with keys baseline_p95_ms, sample_count, or None if missing.
    """
    try:
        from database import get_db_dict_cursor

        with get_db_dict_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT baseline_p95_ms, sample_count
                FROM qa_perf_baselines
                WHERE suite_id = %s AND test_name = %s
                """,
                (suite_id, test_name),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as exc:
        logger.warning("_get_baseline_record failed for %s/%s: %s",
                       suite_id, test_name, exc)
        return None


def check_regression(
    suite_id: int, test_name: str, observed_ms: int, override_ms: Optional[int]
) -> bool:
    """Return True iff observed_ms exceeds the trip threshold.

    Override path: if override_ms is set, observed > override_ms → regression.
    Auto-baseline path: observed > (TRIP_THRESHOLD_PCT/100 × baseline_p95_ms) → regression.
    Below MIN_SAMPLES or no baseline → False (cold-start protection).
    Defensive: never raises — returns False on any internal failure.
    """
    try:
        if override_ms is not None and override_ms > 0:
            return observed_ms > override_ms

        record = _get_baseline_record(suite_id, test_name)
        if record is None:
            return False
        if record["sample_count"] < MIN_SAMPLES:
            return False
        threshold = record["baseline_p95_ms"] * TRIP_THRESHOLD_PCT / 100
        return observed_ms > threshold
    except Exception as exc:
        logger.warning(
            "check_regression failed for %s/%s observed=%s: %s",
            suite_id, test_name, observed_ms, exc,
        )
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec archie_platform pytest tests/test_qa_baseline_service.py -v
```

Expected: 7 passed (3 from Task 2 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/qa_baseline_service.py platform_v2/tests/test_qa_baseline_service.py
git commit -m "feat(qa): check_regression with override priority + cold-start floor"
```

---

### Task 4: decide_action + evaluate_post_deploy (TDD)

**Files:**
- Modify: `platform_v2/services/qa_baseline_service.py`
- Test: `platform_v2/tests/test_qa_baseline_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_qa_baseline_service.py`:

```python
def test_decide_action_critical_trips_on_first_regression():
    """Critical-tagged test → 'rollback' on first regression in window."""
    assert qa_baseline_service.decide_action(
        is_critical=True, recent_regressions_count=1
    ) == "rollback"


def test_decide_action_non_critical_flag_then_pause():
    """Non-critical: 1 regression → 'flag', 2+ in window → 'pause'."""
    assert qa_baseline_service.decide_action(
        is_critical=False, recent_regressions_count=1
    ) == "flag"
    assert qa_baseline_service.decide_action(
        is_critical=False, recent_regressions_count=2
    ) == "pause"
    assert qa_baseline_service.decide_action(
        is_critical=False, recent_regressions_count=3
    ) == "pause"


def test_evaluate_post_deploy_no_pending_returns_none(monkeypatch):
    """No pending regressions for the run → 'none'."""
    monkeypatch.setattr(
        qa_baseline_service,
        "_fetch_pending_regressions_for_run",
        lambda run_id: [],
    )
    assert qa_baseline_service.evaluate_post_deploy(run_id=1, proposal_id=1) == "none"


def test_evaluate_post_deploy_returns_strongest_action(monkeypatch):
    """Returns 'rollback' > 'pause' > 'flag' > 'none'."""
    pending = [
        {"id": 1, "suite_id": 1, "test_name": "a", "is_critical": False},
        {"id": 2, "suite_id": 1, "test_name": "b", "is_critical": True},
    ]
    monkeypatch.setattr(
        qa_baseline_service,
        "_fetch_pending_regressions_for_run",
        lambda run_id: pending,
    )
    monkeypatch.setattr(
        qa_baseline_service,
        "_count_recent_regressions",
        lambda suite_id, test_name: 1,
    )
    monkeypatch.setattr(
        qa_baseline_service,
        "_update_regression_action",
        lambda regression_id, action, proposal_id: None,
    )
    # critical 'rollback' wins over non-critical 'flag'
    assert qa_baseline_service.evaluate_post_deploy(run_id=1, proposal_id=1) == "rollback"


def test_evaluate_post_deploy_fails_open(monkeypatch):
    """Internal exception → return 'none' (fail-open)."""
    def boom(*args, **kwargs):
        raise RuntimeError("db down")
    monkeypatch.setattr(
        qa_baseline_service, "_fetch_pending_regressions_for_run", boom
    )
    assert qa_baseline_service.evaluate_post_deploy(run_id=1, proposal_id=1) == "none"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform pytest tests/test_qa_baseline_service.py -v
```

Expected: 5 new tests FAIL (no decide_action / evaluate_post_deploy yet).

- [ ] **Step 3: Implement decide_action + evaluate_post_deploy**

Append to `platform_v2/services/qa_baseline_service.py`:

```python
ACTION_PRIORITY = {"rollback": 3, "pause": 2, "flag": 1, "none": 0}
PAUSE_THRESHOLD = 2  # 2-of-3 within window
CLEAR_COOLDOWN_HOURS = 24


def decide_action(is_critical: bool, recent_regressions_count: int) -> str:
    """Decide gate action for a single regression.

    Critical → 'rollback' on first regression.
    Non-critical → 'flag' on 1st in window, 'pause' on 2nd+.
    """
    if is_critical:
        return "rollback"
    if recent_regressions_count >= PAUSE_THRESHOLD:
        return "pause"
    return "flag"


def _fetch_pending_regressions_for_run(run_id: int) -> list[dict]:
    """Return list of pending qa_perf_regressions rows for this run."""
    try:
        from database import get_db_dict_cursor
        with get_db_dict_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, suite_id, test_name, is_critical
                FROM qa_perf_regressions
                WHERE run_id = %s AND status = 'pending'
                """,
                (run_id,),
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.warning("_fetch_pending_regressions_for_run %s: %s", run_id, exc)
        return []


def _count_recent_regressions(suite_id: int, test_name: str) -> int:
    """Count regressions for (suite, test) in last 3 runs of that test.

    Excludes regressions cleared >24h ago (flap-prevention).
    """
    try:
        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                WITH last3 AS (
                    SELECT r.id, r.status, r.cleared_at
                    FROM qa_perf_regressions r
                    JOIN qa_test_runs tr ON r.run_id = tr.id
                    WHERE r.suite_id = %s AND r.test_name = %s
                    ORDER BY tr.completed_at DESC NULLS LAST, r.created_at DESC
                    LIMIT 3
                )
                SELECT COUNT(*) FROM last3
                WHERE status != 'cleared'
                   OR cleared_at > NOW() - INTERVAL '24 hours'
                """,
                (suite_id, test_name),
            )
            return cur.fetchone()[0]
    except Exception as exc:
        logger.warning("_count_recent_regressions %s/%s: %s", suite_id, test_name, exc)
        return 0


def _update_regression_action(
    regression_id: int, action: str, proposal_id: Optional[int]
) -> None:
    """UPDATE qa_perf_regressions SET action_taken=..., proposal_id=...."""
    try:
        from database import get_db_cursor
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE qa_perf_regressions
                SET action_taken = %s, proposal_id = %s
                WHERE id = %s
                """,
                (action, proposal_id, regression_id),
            )
    except Exception as exc:
        logger.warning("_update_regression_action %s: %s", regression_id, exc)


def evaluate_post_deploy(run_id: int, proposal_id: Optional[int]) -> str:
    """For each pending regression in this run, decide action and update.

    Returns the strongest action across all regressions:
    'rollback' > 'pause' > 'flag' > 'none'.

    Defensive: any internal failure → return 'none' (fail-open).
    """
    try:
        pending = _fetch_pending_regressions_for_run(run_id)
        if not pending:
            return "none"
        strongest = "none"
        for reg in pending:
            count = _count_recent_regressions(reg["suite_id"], reg["test_name"])
            action = decide_action(
                is_critical=reg["is_critical"],
                recent_regressions_count=count,
            )
            _update_regression_action(reg["id"], action, proposal_id)
            if ACTION_PRIORITY[action] > ACTION_PRIORITY[strongest]:
                strongest = action
        return strongest
    except Exception as exc:
        logger.warning("evaluate_post_deploy failed run=%s: %s", run_id, exc)
        return "none"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec archie_platform pytest tests/test_qa_baseline_service.py -v
```

Expected: 12 passed (7 from prior + 5 new).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/qa_baseline_service.py platform_v2/tests/test_qa_baseline_service.py
git commit -m "feat(qa): decide_action + evaluate_post_deploy with strongest-wins precedence"
```

---

### Task 5: recompute_all_baselines (TDD)

**Files:**
- Modify: `platform_v2/services/qa_baseline_service.py`
- Test: `platform_v2/tests/test_qa_baseline_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_qa_baseline_service.py`:

```python
def test_recompute_returns_count_of_baselines_updated(monkeypatch):
    """recompute_all_baselines returns int count."""
    fake_tests = [
        {"suite_id": 1, "test_name": "a"},
        {"suite_id": 1, "test_name": "b"},
        {"suite_id": 2, "test_name": "c"},
    ]
    monkeypatch.setattr(
        qa_baseline_service, "_fetch_distinct_tests", lambda: fake_tests
    )
    # Two tests have ≥10 samples (return p95), one doesn't (returns None)
    monkeypatch.setattr(
        qa_baseline_service,
        "compute_baseline",
        lambda sid, tn: (150, 30) if tn != "c" else (None, 5),
    )
    monkeypatch.setattr(
        qa_baseline_service,
        "_upsert_baseline",
        lambda sid, tn, p95, count: None,
    )
    count = qa_baseline_service.recompute_all_baselines()
    assert count == 2  # only "a" and "b" had baselines computed
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform pytest tests/test_qa_baseline_service.py -v
```

Expected: 1 new test FAIL (no recompute_all_baselines).

- [ ] **Step 3: Implement recompute_all_baselines**

Append to `platform_v2/services/qa_baseline_service.py`:

```python
def _fetch_distinct_tests() -> list[dict]:
    """Return list of distinct (suite_id, test_name) seen in qa_test_results."""
    try:
        from database import get_db_dict_cursor
        with get_db_dict_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT DISTINCT tr.suite_id, r.test_name
                FROM qa_test_results r
                JOIN qa_test_runs tr ON r.run_id = tr.id
                WHERE r.success = TRUE AND r.response_time_ms IS NOT NULL
                """
            )
            return [dict(row) for row in cur.fetchall()]
    except Exception as exc:
        logger.warning("_fetch_distinct_tests: %s", exc)
        return []


def _upsert_baseline(
    suite_id: int, test_name: str, p95_ms: int, sample_count: int
) -> None:
    """UPSERT qa_perf_baselines."""
    try:
        from database import get_db_cursor
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO qa_perf_baselines
                    (suite_id, test_name, baseline_p95_ms, sample_count, last_updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (suite_id, test_name)
                DO UPDATE SET
                    baseline_p95_ms = EXCLUDED.baseline_p95_ms,
                    sample_count = EXCLUDED.sample_count,
                    last_updated_at = NOW()
                """,
                (suite_id, test_name, p95_ms, sample_count),
            )
    except Exception as exc:
        logger.warning("_upsert_baseline %s/%s: %s", suite_id, test_name, exc)


def recompute_all_baselines() -> int:
    """Walk every distinct (suite, test). Compute p95. UPSERT if ≥ MIN_SAMPLES.

    Returns count of baselines actually updated.
    """
    updated = 0
    for entry in _fetch_distinct_tests():
        suite_id = entry["suite_id"]
        test_name = entry["test_name"]
        p95, count = compute_baseline(suite_id, test_name)
        if p95 is None:
            continue
        _upsert_baseline(suite_id, test_name, p95, count)
        updated += 1
    return updated
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec archie_platform pytest tests/test_qa_baseline_service.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/qa_baseline_service.py platform_v2/tests/test_qa_baseline_service.py
git commit -m "feat(qa): recompute_all_baselines nightly batch"
```

---

## Phase 2 — Hooks

### Task 6: YAML parser extensions for `critical` + `baseline_ms_override`

**Files:**
- Modify: `platform_v2/services/qa_spec_runner.py`
- Test: `platform_v2/tests/test_qa_baseline_service.py`

- [ ] **Step 1: Find the YAML test entry parser**

```bash
grep -n "name\|type\|timeout_ms" platform_v2/services/qa_spec_runner.py | head -20
```

Find where individual test entries are read from the spec dict — likely a function that takes `test: dict` and dispatches by `test["type"]`. The two new fields will be opt-in defaults: `test.get("critical", False)` and `test.get("baseline_ms_override")` (None if missing).

- [ ] **Step 2: Write the failing test**

Append to `platform_v2/tests/test_qa_baseline_service.py`:

```python
def test_yaml_parser_extracts_critical_and_override():
    """qa_spec_runner exposes critical + baseline_ms_override on test execution."""
    from services import qa_spec_runner

    test_entry = {
        "name": "homepage",
        "type": "page_load",
        "url": "/",
        "critical": True,
        "baseline_ms_override": 5000,
    }
    # Helper exposed by qa_spec_runner returns the per-test perf flags
    flags = qa_spec_runner.extract_perf_flags(test_entry)
    assert flags["critical"] is True
    assert flags["baseline_ms_override"] == 5000


def test_yaml_parser_defaults_when_perf_flags_missing():
    """Missing fields → critical=False, override=None."""
    from services import qa_spec_runner

    test_entry = {"name": "x", "type": "page_load", "url": "/"}
    flags = qa_spec_runner.extract_perf_flags(test_entry)
    assert flags["critical"] is False
    assert flags["baseline_ms_override"] is None


def test_yaml_parser_drops_invalid_override():
    """Invalid baseline_ms_override (string, negative) → None + warning."""
    from services import qa_spec_runner

    bad_string = {"name": "x", "type": "page_load", "url": "/", "baseline_ms_override": "fast"}
    bad_negative = {"name": "x", "type": "page_load", "url": "/", "baseline_ms_override": -100}
    assert qa_spec_runner.extract_perf_flags(bad_string)["baseline_ms_override"] is None
    assert qa_spec_runner.extract_perf_flags(bad_negative)["baseline_ms_override"] is None
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
docker exec archie_platform pytest tests/test_qa_baseline_service.py -v
```

Expected: 3 new tests FAIL (no `extract_perf_flags`).

- [ ] **Step 4: Add extract_perf_flags helper**

Append to `platform_v2/services/qa_spec_runner.py` (near top, after existing helpers):

```python
def extract_perf_flags(test_entry: dict) -> dict:
    """Extract per-test perf flags (critical, baseline_ms_override) from YAML entry.

    Defaults: critical=False, baseline_ms_override=None.
    Bad override values (non-int, ≤0) → None + log warning.
    """
    import logging as _logging
    _logger = _logging.getLogger(__name__)

    critical = bool(test_entry.get("critical", False))

    raw_override = test_entry.get("baseline_ms_override")
    override = None
    if raw_override is not None:
        if isinstance(raw_override, int) and raw_override > 0:
            override = raw_override
        else:
            _logger.warning(
                "Invalid baseline_ms_override=%r in test %r — falling back to auto-baseline",
                raw_override,
                test_entry.get("name"),
            )

    return {"critical": critical, "baseline_ms_override": override}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker exec archie_platform pytest tests/test_qa_baseline_service.py -v
```

Expected: 16 passed.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/qa_spec_runner.py platform_v2/tests/test_qa_baseline_service.py
git commit -m "feat(qa): YAML extract_perf_flags — critical + baseline_ms_override with defaults"
```

---

### Task 7: Hook check_regression into qa_e2e_runner per-test write

**Files:**
- Modify: `platform_v2/services/qa_e2e_runner.py`

- [ ] **Step 1: Locate per-test result write**

```bash
grep -n "qa_test_results\|INSERT INTO qa_test" platform_v2/services/qa_e2e_runner.py | head -10
```

Find the spot where each test's result is recorded (probably an INSERT after the test function returns). The new code goes immediately after the result is written, using the same `(suite_id, test_name, response_time_ms)` already in scope.

- [ ] **Step 2: Add the hook**

After the existing per-test result write, add:

```python
# Perf gate hook — defensive: must never break a test run
try:
    from services import qa_baseline_service, qa_spec_runner

    perf_flags = qa_spec_runner.extract_perf_flags(test_entry)
    if qa_baseline_service.check_regression(
        suite_id=suite_id,
        test_name=test_name,
        observed_ms=response_time_ms,
        override_ms=perf_flags["baseline_ms_override"],
    ):
        # Compute baseline for the row; fall back to override or observed if missing
        baseline_record = qa_baseline_service._get_baseline_record(suite_id, test_name)
        baseline_ms = (
            perf_flags["baseline_ms_override"]
            or (baseline_record["baseline_p95_ms"] if baseline_record else response_time_ms)
        )
        pct_over = int(((response_time_ms - baseline_ms) / baseline_ms) * 100) if baseline_ms else 0

        from database import get_db_cursor
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO qa_perf_regressions
                    (run_id, suite_id, test_name, baseline_ms, observed_ms,
                     pct_over, is_critical, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', NOW())
                ON CONFLICT (run_id, test_name) DO NOTHING
                """,
                (
                    run_id, suite_id, test_name, baseline_ms,
                    response_time_ms, pct_over, perf_flags["critical"],
                ),
            )
except Exception as _perf_exc:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "perf gate hook failed for %s/%s: %s", suite_id, test_name, _perf_exc
    )
```

(Adjust variable names to match the surrounding code — `suite_id`, `test_name`, `response_time_ms`, `run_id`, and `test_entry` should all be in scope at the per-test result write site. If they're not, hoist them or use the local equivalents.)

- [ ] **Step 3: Run all qa_baseline tests + smoke run**

```bash
docker exec archie_platform pytest tests/test_qa_baseline_service.py -v
```

Expected: 16 passed (no regressions).

```bash
docker exec archie_platform python -c "from services.qa_e2e_runner import *; print('imports OK')"
```

Expected: `imports OK` printed (no syntax/import errors).

- [ ] **Step 4: Commit**

```bash
git add platform_v2/services/qa_e2e_runner.py
git commit -m "feat(qa): hook check_regression into qa_e2e_runner per-test write"
```

---

### Task 8: Hook evaluate_post_deploy into safe_deployment_protocol

**Files:**
- Modify: `platform_v2/tools/repair_bay/services/safe_deployment_protocol.py`

- [ ] **Step 1: Locate post-deploy QA scan**

```bash
grep -n "post_deploy\|run_qa\|run_suite" platform_v2/tools/repair_bay/services/safe_deployment_protocol.py | head -20
```

Find the place where the post-deploy QA scan completes and a `run_id` (or the equivalent return value from `qa_service.run_suite`) is in scope. The new code goes immediately after that.

- [ ] **Step 2: Add the post-deploy gate hook**

After the post-deploy QA scan returns, add:

```python
# Perf gate evaluation — defensive: fail-open if the gate breaks
try:
    from services import qa_baseline_service

    perf_action = qa_baseline_service.evaluate_post_deploy(
        run_id=qa_run_id,
        proposal_id=proposal_id,
    )

    if perf_action == "rollback":
        # Critical regression — auto-rollback
        if self.rollback_manager and backup_name:
            rollback_result = self.rollback_manager.rollback_deployment(
                backup_name=backup_name,
                reason=f"Perf regression on critical test (proposal #{proposal_id})",
            )
            if rollback_result.get("success"):
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE improvement_proposals SET status = 'regression' WHERE id = %s",
                        (proposal_id,),
                    )
                _send_telegram_alert(
                    f"AUTO-ROLLBACK: critical perf regression on proposal #{proposal_id}. "
                    f"Rollback succeeded.",
                    severity="critical",
                )
            else:
                _send_telegram_alert(
                    f"MANUAL ROLLBACK REQUIRED: critical perf regression on proposal "
                    f"#{proposal_id}. Auto-rollback FAILED: {rollback_result.get('error')}",
                    severity="critical",
                )
        else:
            _send_telegram_alert(
                f"MANUAL ROLLBACK REQUIRED: critical perf regression on proposal "
                f"#{proposal_id}. AutoRollbackManager unavailable.",
                severity="critical",
            )

    elif perf_action == "pause":
        # Non-critical regression but 2-of-3 pattern — pause future deploys
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE improvement_proposals SET status = 'paused_for_perf_review' WHERE id = %s",
                (proposal_id,),
            )
            cur.execute(
                """
                INSERT INTO system_config (key, value, updated_at)
                VALUES ('deploy_paused_perf', 'true', NOW())
                ON CONFLICT (key) DO UPDATE SET value = 'true', updated_at = NOW()
                """
            )
        _send_telegram_alert(
            f"DEPLOYS PAUSED: non-critical perf regression (2-of-3) on proposal "
            f"#{proposal_id}. Clear via /api/qa/regressions/<id>/clear.",
            severity="warning",
        )

    elif perf_action == "flag":
        _send_telegram_alert(
            f"PERF FLAG: regression on proposal #{proposal_id}. "
            f"See dashboard for details.",
            severity="info",
        )
    # 'none' → no action, no alert

except Exception as _gate_exc:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "perf gate failed open on proposal %s: %s", proposal_id, _gate_exc
    )
    try:
        _send_telegram_alert(
            f"PERF GATE FAILED OPEN on proposal #{proposal_id}: {_gate_exc}. "
            f"Deploy proceeded without perf check.",
            severity="warning",
        )
    except Exception:
        pass  # Telegram failure must not propagate
```

(Substitute `qa_run_id` with whatever variable holds the post-deploy QA run id in the surrounding code. Substitute `_send_telegram_alert` with the existing telegram helper used in this file — find it via grep `telegram` or `notify`.)

- [ ] **Step 3: Smoke import check**

```bash
docker exec archie_platform python -c "from tools.repair_bay.services.safe_deployment_protocol import *; print('imports OK')"
```

Expected: `imports OK`.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/repair_bay/services/safe_deployment_protocol.py
git commit -m "feat(qa): post-deploy perf gate — rollback/pause/flag on regression"
```

---

### Task 9: Hook pause-flag check into sandbox_queue claim loop

**Files:**
- Modify: `platform_v2/tools/repair_bay/services/sandbox_queue.py`

- [ ] **Step 1: Locate the claim function**

```bash
grep -n "WHERE status = 'approved'\|claim\|next_proposal" platform_v2/tools/repair_bay/services/sandbox_queue.py | head -10
```

Find the function that selects the next `approved` proposal to deploy.

- [ ] **Step 2: Add the pause check**

At the top of that function (before the SELECT), add:

```python
# Perf gate pause check — refuse to claim if deploys are paused for perf review
try:
    from database import get_db_cursor
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT value FROM system_config WHERE key = 'deploy_paused_perf'"
        )
        row = cur.fetchone()
        if row and row[0] == "true":
            return None  # caller treats None as "no proposals to claim"
except Exception as _exc:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "deploy_paused_perf check failed: %s", _exc
    )
    # Fail-open: continue with claim (operator override path)
```

- [ ] **Step 3: Smoke import check**

```bash
docker exec archie_platform python -c "from tools.repair_bay.services.sandbox_queue import *; print('imports OK')"
```

Expected: `imports OK`.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/repair_bay/services/sandbox_queue.py
git commit -m "feat(qa): sandbox_queue refuses claims when deploy_paused_perf flag is set"
```

---

## Phase 3 — Background + API

### Task 10: Nightly recompute job in agent_loop

**Files:**
- Modify: `platform_v2/ai_bridge/agent_loop.py`

- [ ] **Step 1: Locate scheduled-job registration pattern**

```bash
grep -n "scheduler.add_job\|cron" platform_v2/ai_bridge/agent_loop.py | head -10
```

Find an existing daily job to use as a pattern (e.g., `_run_kin_welfare_digest` runs at 02:45 UTC). The new job follows the same shape.

- [ ] **Step 2: Add the job function + registration**

Add the function (placed near other agent_loop job functions):

```python
def _run_recompute_perf_baselines():
    """Nightly: recompute qa_perf_baselines for every test with ≥10 samples.

    Logs to autonomy_loop_log via existing helper. Defensive: never raises.
    """
    try:
        from services import qa_baseline_service
        updated = qa_baseline_service.recompute_all_baselines()
        _log_loop_run(
            "recompute_perf_baselines",
            status="success",
            details={"baselines_updated": updated},
        )
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "recompute_perf_baselines job failed: %s", exc
        )
        try:
            _log_loop_run(
                "recompute_perf_baselines",
                status="error",
                error_message=str(exc)[:200],
            )
        except Exception:
            pass
```

(Use the existing `_log_loop_run` helper — look for its signature in the file. Adapt parameter names if the existing helper differs.)

In the scheduler registration block, add:

```python
scheduler.add_job(
    _run_recompute_perf_baselines,
    trigger="cron",
    hour=3,
    minute=0,
    id="recompute_perf_baselines",
    name="Recompute P.R.O.B.E. perf baselines",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
)
```

- [ ] **Step 3: Smoke import check**

```bash
docker exec archie_platform python -c "from ai_bridge.agent_loop import _run_recompute_perf_baselines; print('OK')"
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/ai_bridge/agent_loop.py
git commit -m "feat(qa): nightly recompute_perf_baselines job at 03:00 UTC"
```

---

### Task 11: Four new API endpoints (TDD)

**Files:**
- Modify: `platform_v2/services/qa_routes.py` (or wherever existing QA endpoints live — find via grep)
- Test: `platform_v2/tests/test_qa_baseline_routes.py`

- [ ] **Step 1: Locate existing QA route file**

```bash
grep -rn "@.*\.route.*api/qa" platform_v2/ | head -5
```

The new endpoints should live alongside existing `/api/qa/*` routes for consistency.

- [ ] **Step 2: Write the failing tests**

Create `platform_v2/tests/test_qa_baseline_routes.py`:

```python
"""API tests for qa baseline + regression endpoints."""
from unittest.mock import patch

import pytest


@pytest.fixture
def client(app):
    return app.test_client()


def test_get_baselines_returns_list(app, client, login_admin):
    """GET /api/qa/baselines returns a list."""
    resp = client.get("/api/qa/baselines")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "baselines" in data
    assert isinstance(data["baselines"], list)


def test_get_pending_regressions(app, client, login_admin):
    """GET /api/qa/regressions?status=pending returns only pending."""
    resp = client.get("/api/qa/regressions?status=pending")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "regressions" in data
    for row in data["regressions"]:
        assert row["status"] == "pending"


def test_clear_regression_marks_cleared(app, client, login_admin):
    """POST /api/qa/regressions/<id>/clear marks the row cleared."""
    # Insert a fixture regression row
    from database import get_db_cursor
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO qa_perf_regressions
                (run_id, suite_id, test_name, baseline_ms, observed_ms,
                 pct_over, is_critical, status)
            VALUES (1, 1, 'fixture_test_clear', 100, 250, 150, FALSE, 'pending')
            RETURNING id
            """
        )
        regression_id = cur.fetchone()[0]
    resp = client.post(f"/api/qa/regressions/{regression_id}/clear")
    assert resp.status_code == 200
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT status, cleared_at FROM qa_perf_regressions WHERE id = %s",
            (regression_id,),
        )
        row = cur.fetchone()
        assert row[0] == "cleared"
        assert row[1] is not None


def test_accept_regression_inserts_acceptance(app, client, login_admin):
    """POST /api/qa/regressions/<id>/accept records qa_perf_acceptances."""
    from database import get_db_cursor
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO qa_perf_regressions
                (run_id, suite_id, test_name, baseline_ms, observed_ms,
                 pct_over, is_critical, status)
            VALUES (1, 99, 'fixture_test_accept', 100, 350, 250, FALSE, 'pending')
            RETURNING id
            """
        )
        regression_id = cur.fetchone()[0]
    resp = client.post(f"/api/qa/regressions/{regression_id}/accept")
    assert resp.status_code == 200
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT status FROM qa_perf_regressions WHERE id = %s",
            (regression_id,),
        )
        assert cur.fetchone()[0] == "accepted"
        cur.execute(
            "SELECT 1 FROM qa_perf_acceptances WHERE suite_id = 99 AND test_name = 'fixture_test_accept'"
        )
        assert cur.fetchone() is not None
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
docker exec archie_platform pytest tests/test_qa_baseline_routes.py -v
```

Expected: 4 tests FAIL (404 — endpoints don't exist).

- [ ] **Step 4: Add the endpoints**

In the QA routes file (substitute the actual file path from Step 1), add:

```python
@app.route("/api/qa/baselines", methods=["GET"])
@admin_required
def api_qa_baselines():
    """List all qa_perf_baselines."""
    from database import get_db_dict_cursor
    with get_db_dict_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT b.id, b.suite_id, s.name AS suite_name, b.test_name,
                   b.baseline_p95_ms, b.sample_count, b.last_updated_at
            FROM qa_perf_baselines b
            LEFT JOIN qa_test_suites s ON s.id = b.suite_id
            ORDER BY s.name, b.test_name
            """
        )
        rows = [dict(r) for r in cur.fetchall()]
    return {"baselines": rows}


@app.route("/api/qa/regressions", methods=["GET"])
@admin_required
def api_qa_regressions():
    """List qa_perf_regressions, filterable by ?status=pending|cleared|accepted."""
    from flask import request
    from database import get_db_dict_cursor

    status = request.args.get("status")
    sql = """
        SELECT r.id, r.run_id, r.suite_id, s.name AS suite_name, r.test_name,
               r.baseline_ms, r.observed_ms, r.pct_over, r.is_critical,
               r.action_taken, r.proposal_id, r.status,
               r.created_at, r.cleared_at, r.cleared_by
        FROM qa_perf_regressions r
        LEFT JOIN qa_test_suites s ON s.id = r.suite_id
    """
    params = ()
    if status:
        sql += " WHERE r.status = %s"
        params = (status,)
    sql += " ORDER BY r.created_at DESC LIMIT 200"

    with get_db_dict_cursor() as (conn, cur):
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
    return {"regressions": rows}


@app.route("/api/qa/regressions/<int:regression_id>/clear", methods=["POST"])
@admin_required
def api_qa_regression_clear(regression_id: int):
    """Mark regression cleared. Flip pause flag iff no other pending."""
    from flask import g
    from database import get_db_cursor

    user = getattr(g, "current_user", None)
    cleared_by = user.username if user else "system"

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE qa_perf_regressions
            SET status = 'cleared', cleared_at = NOW(), cleared_by = %s
            WHERE id = %s
            """,
            (cleared_by, regression_id),
        )
        # If no other pending regressions remain, lift the pause
        cur.execute(
            "SELECT COUNT(*) FROM qa_perf_regressions WHERE status = 'pending'"
        )
        if cur.fetchone()[0] == 0:
            cur.execute(
                """
                INSERT INTO system_config (key, value, updated_at)
                VALUES ('deploy_paused_perf', 'false', NOW())
                ON CONFLICT (key) DO UPDATE SET value = 'false', updated_at = NOW()
                """
            )
    return {"success": True, "regression_id": regression_id}


@app.route("/api/qa/regressions/<int:regression_id>/accept", methods=["POST"])
@admin_required
def api_qa_regression_accept(regression_id: int):
    """Mark regression accepted as new normal. Insert qa_perf_acceptances."""
    from flask import g
    from database import get_db_cursor
    from services import qa_baseline_service

    user = getattr(g, "current_user", None)
    accepted_by = user.username if user else "system"

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE qa_perf_regressions SET status = 'accepted' WHERE id = %s "
            "RETURNING suite_id, test_name",
            (regression_id,),
        )
        row = cur.fetchone()
        if row is None:
            return {"success": False, "error": "regression not found"}, 404
        suite_id, test_name = row
        cur.execute(
            """
            INSERT INTO qa_perf_acceptances (suite_id, test_name, accepted_at, accepted_by)
            VALUES (%s, %s, NOW(), %s)
            ON CONFLICT (suite_id, test_name) DO UPDATE
                SET accepted_at = NOW(), accepted_by = EXCLUDED.accepted_by
            """,
            (suite_id, test_name, accepted_by),
        )

    # Recompute baseline immediately (post-accept window)
    p95, count = qa_baseline_service.compute_baseline(suite_id, test_name)
    if p95 is not None:
        qa_baseline_service._upsert_baseline(suite_id, test_name, p95, count)

    return {"success": True, "regression_id": regression_id}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker exec archie_platform pytest tests/test_qa_baseline_routes.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/qa_routes.py platform_v2/tests/test_qa_baseline_routes.py
git commit -m "feat(qa): 4 API endpoints for baselines + regression mgmt"
```

---

## Phase 4 — Integration tests + close

### Task 12: Integration tests for full deploy flow

**Files:**
- Test: `platform_v2/tests/test_perf_gate_integration.py`

- [ ] **Step 1: Write the integration tests**

Create `platform_v2/tests/test_perf_gate_integration.py`:

```python
"""Integration tests for perf gate end-to-end flow."""
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def client(app):
    return app.test_client()


def _insert_regression(suite_id, test_name, is_critical, status="pending", run_id=1):
    """Test fixture — insert a qa_perf_regressions row."""
    from database import get_db_cursor
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO qa_perf_regressions
                (run_id, suite_id, test_name, baseline_ms, observed_ms,
                 pct_over, is_critical, status)
            VALUES (%s, %s, %s, 100, 250, 150, %s, %s)
            RETURNING id
            """,
            (run_id, suite_id, test_name, is_critical, status),
        )
        return cur.fetchone()[0]


def test_critical_regression_returns_rollback(app):
    """evaluate_post_deploy returns 'rollback' when a critical regression is pending."""
    from services import qa_baseline_service
    reg_id = _insert_regression(suite_id=999, test_name="t_critical", is_critical=True, run_id=999)
    try:
        action = qa_baseline_service.evaluate_post_deploy(run_id=999, proposal_id=None)
        assert action == "rollback"
    finally:
        from database import get_db_cursor
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM qa_perf_regressions WHERE id = %s", (reg_id,))


def test_non_critical_first_regression_returns_flag(app):
    """Non-critical, first occurrence in window → 'flag'."""
    from services import qa_baseline_service
    reg_id = _insert_regression(
        suite_id=998, test_name="t_first_only", is_critical=False, run_id=998
    )
    try:
        action = qa_baseline_service.evaluate_post_deploy(run_id=998, proposal_id=None)
        assert action == "flag"
    finally:
        from database import get_db_cursor
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM qa_perf_regressions WHERE id = %s", (reg_id,))


def test_clear_endpoint_lifts_pause_flag_when_no_pending(app, client, login_admin):
    """POST /clear lifts pause flag iff no other pending regressions."""
    from database import get_db_cursor

    # Set the pause flag
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO system_config (key, value, updated_at)
            VALUES ('deploy_paused_perf', 'true', NOW())
            ON CONFLICT (key) DO UPDATE SET value = 'true', updated_at = NOW()
            """
        )
    # Insert one pending regression
    reg_id = _insert_regression(
        suite_id=997, test_name="t_clear_single", is_critical=False, run_id=997
    )
    try:
        # Clear it via API
        resp = client.post(f"/api/qa/regressions/{reg_id}/clear")
        assert resp.status_code == 200
        # Pause flag should now be false (no other pending)
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT value FROM system_config WHERE key = 'deploy_paused_perf'")
            assert cur.fetchone()[0] == "false"
    finally:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM qa_perf_regressions WHERE id = %s", (reg_id,))


def test_sandbox_queue_refuses_claim_when_paused(app):
    """sandbox_queue.claim_next() returns None when deploy_paused_perf=true."""
    from database import get_db_cursor
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO system_config (key, value, updated_at)
            VALUES ('deploy_paused_perf', 'true', NOW())
            ON CONFLICT (key) DO UPDATE SET value = 'true', updated_at = NOW()
            """
        )
    try:
        # Find the actual claim function in sandbox_queue
        from tools.repair_bay.services import sandbox_queue
        # Try common names; substitute the real one if different
        claim_fn = (
            getattr(sandbox_queue, "claim_next_proposal", None)
            or getattr(sandbox_queue, "claim_next", None)
            or getattr(sandbox_queue, "next_proposal", None)
        )
        assert claim_fn is not None, "could not find claim function in sandbox_queue"
        result = claim_fn()
        assert result is None
    finally:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE system_config SET value = 'false' WHERE key = 'deploy_paused_perf'"
            )
```

- [ ] **Step 2: Run all tests together**

```bash
docker exec archie_platform pytest tests/test_qa_baseline_service.py tests/test_qa_baseline_routes.py tests/test_perf_gate_integration.py -v
```

Expected: 24+ passed.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tests/test_perf_gate_integration.py
git commit -m "test(qa): integration tests for perf gate full flow"
```

---

### Task 13: Open PR + closeout

**Files:**
- None (PR + MCP calls only)

- [ ] **Step 1: Push branch**

```bash
git push -u origin feat/perf-baselines
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "feat(qa): P.R.O.B.E. performance baselines + deploy gate" --body "$(cat <<'EOF'
## Summary

Task #1755 (Project #239 — P.R.O.B.E. Phase 3). Wires historical perf baselines + a post-deploy regression gate into P.R.O.B.E. Critical regressions → AutoRollbackManager. Non-critical 2-of-3 regressions → paused_for_perf_review + sandbox_queue refuses new claims.

Spec: docs/superpowers/specs/2026-05-03-perf-baselines-design.md

## What this ships

- New service `services/qa_baseline_service.py` (~250 LOC)
- 3 new tables (qa_perf_baselines, qa_perf_regressions, qa_perf_acceptances) + status check extension
- 3 hook integrations (qa_e2e_runner per-test write, safe_deployment_protocol post-deploy, sandbox_queue claim)
- 1 nightly agent_loop job (recompute_perf_baselines @ 03:00 UTC)
- 4 new API endpoints
- YAML extensions: critical, baseline_ms_override (opt-in)
- 25+ tests

## Verification

- All unit + API + integration tests green
- 30-day soak built in: no test has 10 baseline samples on day 1, gate is dormant during ramp

## Test plan

- [x] Unit tests pass
- [x] API tests pass
- [x] Integration tests pass
- [ ] Post-merge: nightly recompute job runs without error
- [ ] Post-merge: /archie-scan on a real module — no false-positive regressions

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Wait for review + self-merge**

Per `feedback_pr-management.md`: pause until user reviews. After approval, run `gh pr merge --squash --delete-branch`.

- [ ] **Step 4: MCP closeout (after merge)**

```python
# log_decision
mcp__archie__log_decision(
    title="P.R.O.B.E. perf baselines + deploy gate",
    decision="...",
    project_id=239,
    task_id=1755,
)
# complete_task
mcp__archie__complete_task(task_id=1755, notes="...")
# update_project_status if all #239 tasks complete
```

---

## Self-Review Checklist

- [ ] Spec coverage: every section of `2026-05-03-perf-baselines-design.md` maps to a task
- [ ] Placeholder scan: zero `TBD`/`TODO`/`add appropriate ...`
- [ ] Type consistency: `compute_baseline` returns `Tuple[Optional[int], int]` everywhere; `evaluate_post_deploy` returns one of `'rollback'|'pause'|'flag'|'none'` everywhere
- [ ] Constants consistent: `MIN_SAMPLES = 10`, `WINDOW_SIZE = 30`, `TRIP_THRESHOLD_PCT = 200`, `PAUSE_THRESHOLD = 2`, `CLEAR_COOLDOWN_HOURS = 24`
- [ ] Branch naming: `feat/perf-baselines`
- [ ] Commit message scope: `feat(qa)` for code, `test(qa)` for test-only commits

---

## Total Effort Estimate

| Phase | Tasks | Approx. Sessions |
|---|---|---|
| Phase 1 (foundation) | 1-5 | 1 session (~2-3h) |
| Phase 2 (hooks) | 6-9 | 1 session (~2h) |
| Phase 3 (background + API) | 10-11 | 1 session (~1.5h) |
| Phase 4 (integration + close) | 12-13 | 0.5 session |
| **Total** | **13 tasks** | **~3-4 sessions** |
