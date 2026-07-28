"""Regression: an expired dispatch row must say WHY (#5374).

``_expire_stale_tasks`` set ``status='expired'`` and left ``error`` NULL. Only
rows with ``callback_type='delegation_result'`` got any explanation at all, so
everything else expired mute.

1,784 such rows accumulated. A terminal status with no reason is
indistinguishable from a mystery, so they were catalogued as the single largest
"unmonitored dispatch failure class" and investigated as one. They were nothing
of the kind: measured 2026-07-28, ALL 1,832 expired rows ever recorded are
``capability='warmup'`` — model warm-ups that sat queued past their deadline.
Real work has never once expired. One sentence in the row would have made that
readable without an investigation.

These tests execute the REAL ``_EXPIRE_STALE_SQL`` the service runs, not a
retyped copy: a duplicated statement drifts silently, and asserting on source
text passes on the very comment that documents the bug.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import get_db_cursor  # noqa: E402
from services.model_dispatch_service import _EXPIRE_STALE_SQL  # noqa: E402

# The statement as it was before this fix — used only to prove the assertions bite.
_OLD_SQL = """
    UPDATE dispatch_pending_queue
       SET status = 'expired', completed_at = NOW()
     WHERE status = 'queued'
       AND expires_at IS NOT NULL
       AND expires_at < NOW()
"""


def _insert_scratch(cur, capability, error=None):
    cur.execute(
        """
        INSERT INTO dispatch_pending_queue
            (capability, prompt, model_needed, status, queued_at, expires_at, error)
        VALUES (%s, %s, %s, 'queued', NOW() - INTERVAL '2 hours',
                NOW() - INTERVAL '1 hour', %s)
        RETURNING id
        """,
        (capability, "scratch row for test_expiry_records_reason", "qwen2.5:1.5b", error),
    )
    return cur.fetchone()["id"]


@pytest.fixture
def scratch_ids():
    ids = []
    yield ids
    if ids:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute("DELETE FROM dispatch_pending_queue WHERE id = ANY(%s)", (ids,))


def _fetch(cur, row_id):
    cur.execute("SELECT status, error FROM dispatch_pending_queue WHERE id = %s", (row_id,))
    return cur.fetchone()


def test_expired_row_records_a_reason(scratch_ids):
    """The defect: expired with error NULL, so the row explained nothing."""
    with get_db_cursor(commit=True) as (_conn, cur):
        row_id = _insert_scratch(cur, "warmup")
        scratch_ids.append(row_id)

        cur.execute(_EXPIRE_STALE_SQL)
        row = _fetch(cur, row_id)

    assert row["status"] == "expired"
    assert row["error"], "expired row still records NO reason — the #5374 defect"
    assert "expires_at" in row["error"]


def test_existing_error_is_not_clobbered(scratch_ids):
    """COALESCE, not assignment: whatever actually failed keeps its own message."""
    original = "HTTPConnectionPool: read timed out"
    with get_db_cursor(commit=True) as (_conn, cur):
        row_id = _insert_scratch(cur, "warmup", error=original)
        scratch_ids.append(row_id)

        cur.execute(_EXPIRE_STALE_SQL)
        row = _fetch(cur, row_id)

    assert row["error"] == original, "a real error was overwritten by the generic expiry text"


def test_rows_not_yet_due_are_untouched(scratch_ids):
    """Only rows PAST expires_at expire — the WHERE clause must not widen."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            INSERT INTO dispatch_pending_queue
                (capability, prompt, model_needed, status, queued_at, expires_at)
            VALUES ('warmup', 'scratch not-yet-due', 'qwen2.5:1.5b', 'queued',
                    NOW(), NOW() + INTERVAL '1 hour')
            RETURNING id
            """
        )
        row_id = cur.fetchone()["id"]
        scratch_ids.append(row_id)

        cur.execute(_EXPIRE_STALE_SQL)
        row = _fetch(cur, row_id)

    assert row["status"] == "queued", "a task that had not yet expired was expired"
    assert row["error"] is None


def test_old_statement_would_fail_these_checks(scratch_ids):
    """Falsifiability guard.

    Without this, the assertions above could be satisfied by any statement at
    all and the file would keep passing if the fix were reverted.
    """
    with get_db_cursor(commit=True) as (_conn, cur):
        row_id = _insert_scratch(cur, "warmup")
        scratch_ids.append(row_id)

        cur.execute(_OLD_SQL)
        row = _fetch(cur, row_id)

    assert row["status"] == "expired"
    assert row["error"] is None, "the OLD statement recorded a reason — these tests no longer discriminate"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
