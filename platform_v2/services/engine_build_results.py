"""Record A.R.C.H.I.E. engine build/test runs into qa_test_runs + qa_test_results
so the Repair Bay Test Bay + QA tabs surface engine-driven builds (#4261).

The engine builds + tests in its OWN isolated /workspace and POSTs the RESULT
here — the platform never executes the engine's code on the web container
(project #380 decision: build in isolation, report back). One run header per
build + one result row per test; the engine's build metadata (branch, PR, task)
rides on each result row's `assertions` JSONB so the QA tab can link back.
"""

import json

from database import get_db_cursor

ENGINE_SUITE_NAME = "A.R.C.H.I.E. Engine Builds"
_RESULT_STATES = ("pass", "fail", "error", "skip")


def _engine_suite_id(cur):
    """Get-or-create the persistent internal QA suite engine runs are filed under.

    Lazy create avoids a migration/seed step and keeps qa_test_runs.suite_id (FK)
    satisfied. Idempotent — returns the existing row's id on every later call."""
    cur.execute(
        "SELECT id FROM qa_test_suites WHERE name = %s ORDER BY id LIMIT 1",
        (ENGINE_SUITE_NAME,),
    )
    row = cur.fetchone()
    if row:
        return row["id"]
    # spec is NOT NULL — engine runs are REPORTED (not executed from a spec), so a
    # minimal descriptor satisfies the column without implying executable steps.
    spec = json.dumps({"type": "engine_reported", "tests": []})
    cur.execute(
        "INSERT INTO qa_test_suites (name, description, suite_type, spec, is_active) "
        "VALUES (%s, %s, 'internal', %s, TRUE) RETURNING id",
        (
            ENGINE_SUITE_NAME,
            "Build/test runs reported by the A.R.C.H.I.E. build engine (#4261).",
            spec,
        ),
    )
    return cur.fetchone()["id"]


def _norm_status(s):
    """Normalize an engine-reported test status to the qa_test_results vocabulary."""
    s = (s or "").strip().lower()
    if s in _RESULT_STATES:
        return s
    if s in ("passed", "ok", "success", "green", "true"):
        return "pass"
    if s in ("skipped", "xfail"):
        return "skip"
    return "fail"


def record_build_result(payload: dict) -> dict:
    """Persist one engine build run. Returns {success, run_id, status, totals}.

    payload: {task?, branch?, pr_url?, pr_number?, files_changed?, status?,
              duration_ms?, output?, tests: [{name, status, output?, duration_ms?}]}
    """
    tests = payload.get("tests") or []
    norm = [
        {
            "name": (t.get("name") or "test")[:255],
            "status": _norm_status(t.get("status")),
            "output": t.get("output") or "",
            "duration_ms": int(t.get("duration_ms") or 0),
        }
        for t in tests
    ]
    passed = sum(1 for t in norm if t["status"] == "pass")
    failed = sum(1 for t in norm if t["status"] == "fail")
    errors = sum(1 for t in norm if t["status"] == "error")

    overall = (payload.get("status") or "").strip().lower()
    if overall not in ("completed", "failed"):
        overall = "failed" if (failed or errors) else "completed"
    total = len(norm)
    duration_ms = int(payload.get("duration_ms") or sum(t["duration_ms"] for t in norm))

    meta = json.dumps(
        {
            "source": "archie_engine",
            "branch": payload.get("branch"),
            "pr_url": payload.get("pr_url"),
            "pr_number": payload.get("pr_number"),
            "task": payload.get("task"),
            "files_changed": payload.get("files_changed"),
        }
    )

    with get_db_cursor(commit=True) as (conn, cur):
        suite_id = _engine_suite_id(cur)
        cur.execute(
            "INSERT INTO qa_test_runs "
            "(suite_id, triggered_by, status, total_tests, passed, failed, errors, duration_ms, started_at, completed_at) "
            "VALUES (%s, 'archie-code-engine', %s, %s, %s, %s, %s, %s, NOW(), NOW()) RETURNING id",
            (suite_id, overall, total, passed, failed, errors, duration_ms),
        )
        run_id = cur.fetchone()["id"]

        rows = norm or [
            {
                "name": "engine build",
                "status": "pass" if overall == "completed" else "fail",
                "output": payload.get("output") or "",
                "duration_ms": duration_ms,
            }
        ]
        for t in rows:
            cur.execute(
                "INSERT INTO qa_test_results "
                "(run_id, test_name, test_type, status, response_time_ms, error_message, assertions) "
                "VALUES (%s, %s, 'e2e', %s, %s, %s, %s)",
                (
                    run_id,
                    t["name"],
                    t["status"],
                    t["duration_ms"],
                    (t["output"][:2000] if t["status"] != "pass" else None),
                    meta,
                ),
            )

    return {
        "success": True,
        "run_id": run_id,
        "status": overall,
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
    }
