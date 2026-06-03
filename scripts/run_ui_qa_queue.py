#!/usr/bin/env python3
"""Host-side Playwright UI-QA runner (#371, 2026-06-03).

The archie_platform container has NO chromium — Playwright UI tests run on the
HOST. This drains `ui_qa_queue` (populated in-container by
delegate_task(capability='run_qa_suite', args={'module': '<m>'})), runs
`pytest qa/tests/modules/<m>.py` on the host, records pass/fail in the queue
row + `qa_test_results`, and posts the result back to the originating
unified_tasks row (work_notes) so P.R.O.B.E. "comes back with results".

Run via host cron (every 2 min) or on demand:  python3 scripts/run_ui_qa_queue.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

import psycopg2
import psycopg2.extras

PLATFORM = "/mnt/archie_brain/platform_v2"
BASE_URL = os.getenv("BASE_URL", "http://192.168.1.200:3000")
MAX_JOBS = 5  # drain at most N queued jobs per invocation


def _env_from_dotenv(path="/mnt/archie_brain/.env") -> dict:
    env = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def _db():
    e = _env_from_dotenv()
    # This is a HOST process: .env DB_HOST=archie_database is the container-internal
    # name (unresolvable here). Postgres is published on the host at 192.168.1.200:5432.
    return psycopg2.connect(
        host=os.getenv("UI_QA_DB_HOST", "192.168.1.200"),
        port=int(os.getenv("DB_PORT", e.get("DB_PORT", "5432"))),
        dbname=e.get("DB_NAME", "archie"),
        user=e.get("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", e.get("DB_PASSWORD", "")),
    )


def _run_pytest(module: str) -> tuple[int, int, str]:
    """Run the module's Playwright suite on the host; return (passed, failed, summary)."""
    test_file = f"qa/tests/modules/{module}.py"
    if not os.path.isfile(os.path.join(PLATFORM, test_file)):
        return 0, 1, f"no pytest module '{module}' at {test_file}"
    e = _env_from_dotenv()
    # conftest reads PROBE_* (PROBE_BASE_URL / PROBE_TEST_USER / PROBE_TEST_PASS);
    # defaults (admin / Kyt$13ran2025) are already correct, these allow overrides.
    run_env = {
        **os.environ,
        "PROBE_BASE_URL": BASE_URL,
        "PROBE_TEST_USER": os.getenv("PROBE_TEST_USER", e.get("QA_TEST_USER", "admin")),
        "PROBE_TEST_PASS": os.getenv("PROBE_TEST_PASS", e.get("QA_TEST_PASS", "Kyt$13ran2025")),
    }
    try:
        proc = subprocess.run(
            ["python3", "-m", "pytest", test_file, "-p", "no:cacheprovider", "--tb=line", "-q"],
            cwd=PLATFORM,
            capture_output=True,
            text=True,
            timeout=600,
            env=run_env,
        )
        out = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return 0, 1, f"pytest '{module}' timed out (600s)"
    passed = int((re.search(r"(\d+) passed", out) or [0, 0])[1]) if re.search(r"(\d+) passed", out) else 0
    failed = sum(int(m.group(1)) for m in re.finditer(r"(\d+) (?:failed|error)", out))
    fails = re.findall(r"FAILED (\S+)", out)[:8]
    tail = out.strip().splitlines()[-1] if out.strip() else "(no output)"
    summary = f"UI QA '{module}': passed={passed} failed={failed} | {tail}"
    if fails:
        summary += " | failing: " + ", ".join(f.split("::")[-1] for f in fails)
    return passed, failed, summary[:1000]


def _post_to_task(cur, task_id: int, summary: str, ok: bool):
    cur.execute(
        "INSERT INTO work_notes (task_id, note_type, content, metadata) VALUES (%s, %s, %s, %s)",
        (task_id, "qa_result", f"[P.R.O.B.E. host Playwright] {summary}", psycopg2.extras.Json({"source": "ui_qa_queue"})),
    )
    cur.execute(
        "UPDATE unified_tasks SET status=%s, updated_at=NOW() WHERE id=%s",
        ("completed" if ok else "blocked", task_id),
    )


def main():
    conn = _db()
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    done = 0
    for _ in range(MAX_JOBS):
        cur.execute(
            "UPDATE ui_qa_queue SET status='running', started_at=NOW() "
            "WHERE id = (SELECT id FROM ui_qa_queue WHERE status='queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED) "
            "RETURNING id, module, task_id"
        )
        job = cur.fetchone()
        if not job:
            break
        print(f"[ui_qa] job {job['id']}: pytest module '{job['module']}' (task {job['task_id']})")
        passed, failed, summary = _run_pytest(job["module"])
        cur.execute(
            "UPDATE ui_qa_queue SET status=%s, finished_at=NOW(), passed=%s, failed=%s, summary=%s WHERE id=%s",
            ("done" if failed == 0 else "error", passed, failed, summary, job["id"]),
        )
        if job["task_id"]:
            try:
                _post_to_task(cur, job["task_id"], summary, failed == 0)
            except Exception as exc:  # never let task-posting break the runner
                print(f"[ui_qa] WARN: could not post to task {job['task_id']}: {exc}")
        print(f"[ui_qa] {summary}")
        done += 1
    if done == 0:
        print("[ui_qa] no queued jobs")
    cur.close()
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
