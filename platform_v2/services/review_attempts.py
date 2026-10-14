"""Cross-process review ownership and cooperative cancellation; no model calls."""

import hashlib
import uuid
import time
from contextlib import contextmanager
from contextvars import ContextVar

from database import get_db_cursor

CURRENT = ContextVar("review_attempt", default=None)


class ReviewBusy(RuntimeError):
    pass


class ReviewCancelled(RuntimeError):
    pass


def lock_key(repo, number):
    return int.from_bytes(hashlib.sha256(f"review:{repo}:{number}".encode()).digest()[:8], "big", signed=True)


@contextmanager
def owned_attempt(repo, number, head_sha):
    """Hold a PostgreSQL session lock until the full review returns.

    Cancellation revokes writes immediately but does not release this lock while
    a synchronous provider call remains alive. Process death releases the lock.
    """
    if not head_sha:
        raise ReviewCancelled("missing review head identity")
    key = lock_key(repo, number)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (key,))
        if not cur.fetchone()["acquired"]:
            raise ReviewBusy("review process already owns this PR")
        token = None
        try:
            conn.commit()
            cur.execute(
                "SELECT 1 FROM dispatch_pending_queue WHERE status IN ('queued','running') "
                "AND callback_type='pr_review_result' AND callback_data->>'repo'=%s "
                "AND callback_data->>'pr_number'=%s LIMIT 1",
                (repo, str(number)),
            )
            if cur.fetchone():
                raise ReviewBusy("prior review dispatch still queued or running")
            token = CURRENT.set({"id": str(uuid.uuid4()), "repo": repo, "number": number, "head_sha": head_sha})
            yield CURRENT.get()
        finally:
            if token is not None:
                CURRENT.reset(token)
            # Roll back a failed transaction before unlocking the session. Never
            # return a pooled connection while it still owns the review lock.
            conn.rollback()
            cur.execute("SELECT pg_advisory_unlock(%s)", (key,))
            conn.commit()


def assert_active():
    attempt = CURRENT.get()
    if not attempt:
        return
    with get_db_cursor() as (_, cur):
        cur.execute(
            "SELECT 1 FROM pr_reviews WHERE repo=%s AND pr_number=%s AND state='open' "
            "AND review_status='in_progress' AND metadata->>'review_attempt_id'=%s "
            "AND metadata->>'head_sha'=%s AND metadata->>'review_cancelled' IS DISTINCT FROM 'true'",
            (attempt["repo"], attempt["number"], attempt["id"], attempt["head_sha"]),
        )
        if not cur.fetchone():
            raise ReviewCancelled("review cancelled, superseded, closed or changed head")


def write_guard():
    """SQL predicate + values for a review mutation, including legacy isolation."""
    attempt = CURRENT.get()
    if not attempt:
        return " AND NOT (COALESCE(metadata, '{}'::jsonb) ? 'review_attempt_id')", ()
    return (
        " AND state='open' AND review_status='in_progress' "
        "AND metadata->>'review_attempt_id'=%s AND metadata->>'head_sha'=%s "
        "AND metadata->>'review_cancelled' IS DISTINCT FROM 'true'",
        (attempt["id"], attempt["head_sha"]),
    )


def guarded_cursor(cursor):
    class GuardedCursor:
        def __getattr__(self, name):
            return getattr(cursor, name)

        def execute(self, query, params=None):
            if query.lstrip().upper().startswith("UPDATE PR_REVIEWS"):
                guard, values = write_guard()
                cursor.execute(query.rstrip().rstrip(";") + guard, tuple(params or ()) + values)
                if not cursor.rowcount and CURRENT.get():
                    raise ReviewCancelled("review mutation rejected: cancelled or superseded attempt")
            else:
                cursor.execute(query, params)

    return GuardedCursor()


def cancel_review(number, repo, retry=False):
    """Revoke the current attempt; expire queued work, retain running ownership.

    Running provider calls are NOT claimed to be terminated. Their callbacks and
    completion writes are fenced, and the owner stops at its next safe boundary.
    """
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute(
            "UPDATE pr_reviews SET review_status=%s, updated_at=NOW(), "
            "metadata=COALESCE(metadata,'{}'::jsonb) || "
            "jsonb_build_object('review_cancelled',true,'review_cancelled_at',NOW()) "
            "WHERE pr_number=%s AND repo=%s RETURNING metadata->>'review_attempt_id' AS attempt_id",
            ("pending" if retry else "skipped", number, repo),
        )
        row = cur.fetchone()
        if not row:
            return False
        cur.execute(
            "UPDATE dispatch_pending_queue SET status='expired', error='Review cancelled' "
            "WHERE status='queued' AND callback_type='pr_review_result' "
            "AND callback_data->>'pr_number'=%s AND callback_data->>'repo'=%s",
            (str(number), repo),
        )
        return True


def await_existing_queue(queue_id, timeout=1200):
    """Poll the original dispatch ID; never redispatch to obtain a queued result."""
    from psycopg2.extras import Json
    from services.model_dispatch_service import get_pending_queue_result

    attempt = CURRENT.get()
    if not attempt or not queue_id:
        raise ReviewCancelled("queued review has no owned dispatch identity")
    cancelled = False
    with get_db_cursor(commit=True) as (_, cur):
        # Lock review identity while linking so cancellation cannot miss a newly
        # attached queued job. A cancel that follows this transaction expires it.
        cur.execute(
            "SELECT 1 FROM pr_reviews WHERE repo=%s AND pr_number=%s "
            "AND metadata->>'review_attempt_id'=%s AND review_status='in_progress' "
            "AND metadata->>'head_sha'=%s "
            "AND metadata->>'review_cancelled' IS DISTINCT FROM 'true' FOR UPDATE",
            (attempt["repo"], attempt["number"], attempt["id"], attempt["head_sha"]),
        )
        if not cur.fetchone():
            cancelled = True
        cur.execute(
            "UPDATE dispatch_pending_queue SET callback_type='pr_review_result', callback_data=%s::jsonb "
            "WHERE id=%s",
            (
                Json(
                    {
                        "repo": attempt["repo"],
                        "pr_number": attempt["number"],
                        "attempt_id": attempt["id"],
                        "head_sha": attempt["head_sha"],
                        "pass_only": True,
                    }
                ),
                queue_id,
            ),
        )
        if not cur.rowcount:
            raise ReviewCancelled("queued dispatch disappeared")
        if cancelled:
            cur.execute(
                "UPDATE dispatch_pending_queue SET status='expired', error='Review cancelled before queue link' "
                "WHERE id=%s AND status='queued'",
                (queue_id,),
            )
    if cancelled:
        raise ReviewCancelled("attempt cancelled before queue link")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        assert_active()
        row = get_pending_queue_result(queue_id)
        if not row or row["status"] in {"failed", "expired", "cancelled"}:
            raise ReviewCancelled("queued dispatch failed, expired or cancelled")
        if row["status"] == "completed":
            return row.get("result_response")
        with get_db_cursor(commit=True) as (_, cur):
            cur = guarded_cursor(cur)
            cur.execute(
                "UPDATE pr_reviews SET updated_at=NOW() WHERE repo=%s AND pr_number=%s "
                "AND review_status='in_progress'",
                (attempt["repo"], attempt["number"]),
            )
        time.sleep(5)
    raise ReviewCancelled("queue wait timed out; outstanding dispatch retained, retry admission blocked")
