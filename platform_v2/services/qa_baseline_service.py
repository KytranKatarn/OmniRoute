"""P.R.O.B.E. performance baseline + regression detection.

Pure functions. No Flask import so unit tests run without app context.
Defensive: every public function must never raise into callers (logs + safe default).

Note: qa_test_results uses status='pass'/'fail'/'error'/'skip' (not a boolean success column).
"""

from __future__ import annotations

import logging
import statistics
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

MIN_SAMPLES = 10
WINDOW_SIZE = 30
TRIP_THRESHOLD_PCT = 200  # observed > 2× baseline → regression


def _fetch_recent_response_times(suite_id: int, test_name: str, limit: int) -> list[int]:
    """Read recent successful response_time_ms for a test from qa_test_results.

    Filters to status='pass' runs only, and excludes runs that predate any
    qa_perf_acceptances.accepted_at for this test (so a manually accepted
    regression doesn't poison the new baseline window).

    The JOIN to qa_test_runs is required because test_name is NOT unique across
    suites — different suites can reuse names like "GET /api/health". We must
    filter by tr.suite_id to scope results to the correct suite.

    Returns [] if database access fails (defensive fail-open).
    """
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT r.response_time_ms
                FROM qa_test_results r
                JOIN qa_test_runs tr ON r.run_id = tr.id
                LEFT JOIN (
                    SELECT suite_id, test_name, MAX(accepted_at) AS accepted_at
                    FROM qa_perf_acceptances
                    GROUP BY suite_id, test_name
                ) a ON a.suite_id = tr.suite_id AND a.test_name = r.test_name
                WHERE tr.suite_id = %s
                  AND r.test_name = %s
                  AND r.status = 'pass'
                  AND r.response_time_ms IS NOT NULL
                  AND (a.accepted_at IS NULL OR r.created_at > a.accepted_at)
                ORDER BY r.created_at DESC
                LIMIT %s
                """,
                (suite_id, test_name, limit),
            )
            return [row[0] for row in cur.fetchall()]
    except Exception as exc:
        logger.warning(
            "_fetch_recent_response_times failed for suite=%s test=%s: %s",
            suite_id,
            test_name,
            exc,
        )
        return []


def compute_baseline(suite_id: int, test_name: str) -> Tuple[Optional[int], int]:
    """Compute p95 baseline over most recent successful runs.

    Returns (p95_ms, sample_count).
    p95_ms is None when sample_count < MIN_SAMPLES (not enough data yet).
    """
    samples = _fetch_recent_response_times(suite_id, test_name, WINDOW_SIZE)
    count = len(samples)
    if count < MIN_SAMPLES:
        return None, count
    # statistics.quantiles uses linear interpolation; method="inclusive" gives a tighter p95,
    # making the regression tripwire more sensitive (catches regressions sooner).
    quantiles = statistics.quantiles(samples, n=100, method="inclusive")
    p95 = int(round(quantiles[94]))  # quantiles[94] is the 95th percentile
    return p95, count


def _get_baseline_record(suite_id: int, test_name: str) -> Optional[dict]:
    """Read latest baseline row for (suite_id, test_name) from qa_perf_baselines.

    Returns dict with keys baseline_p95_ms, sample_count, or None if missing.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
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
        logger.warning(
            "_get_baseline_record failed for %s/%s: %s",
            suite_id,
            test_name,
            exc,
        )
        return None


def check_regression(suite_id: int, test_name: str, observed_ms: int, override_ms: Optional[int]) -> bool:
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
            suite_id,
            test_name,
            observed_ms,
            exc,
        )
        return False


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
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
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
            row = cur.fetchone()
            return row[0] if row else 0
    except Exception as exc:
        logger.warning("_count_recent_regressions %s/%s: %s", suite_id, test_name, exc)
        return 0


def _update_regression_action(regression_id: int, action: str, proposal_id: Optional[int]) -> None:
    """UPDATE qa_perf_regressions SET action_taken=..., proposal_id=..."""
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
            action_priority = ACTION_PRIORITY.get(action)
            if action_priority is None:
                logger.warning(
                    "evaluate_post_deploy got unknown action %r from decide_action; defaulting to no-op",
                    action,
                )
                continue
            if action_priority > ACTION_PRIORITY[strongest]:
                strongest = action
        return strongest
    except Exception as exc:
        logger.warning("evaluate_post_deploy failed run=%s: %s", run_id, exc)
        return "none"


def _fetch_distinct_tests() -> list[dict]:
    """Return list of distinct (suite_id, test_name) seen in qa_test_results."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT DISTINCT tr.suite_id, r.test_name
                FROM qa_test_results r
                JOIN qa_test_runs tr ON r.run_id = tr.id
                WHERE r.status = 'pass' AND r.response_time_ms IS NOT NULL
                """
            )
            return [dict(row) for row in cur.fetchall()]
    except Exception as exc:
        logger.warning("_fetch_distinct_tests: %s", exc)
        return []


def _upsert_baseline(suite_id: int, test_name: str, p95_ms: int, sample_count: int) -> None:
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
    Defensive: never raises — returns 0 on any internal failure.
    """
    try:
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
    except Exception as exc:
        logger.warning("recompute_all_baselines: %s", exc)
        return 0
