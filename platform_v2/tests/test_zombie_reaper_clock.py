"""The zombie reaper must time a job from CLAIM, not from ENQUEUE (#5188).

The reaper marked any `running` row whose **queued_at** was >30 min old as
"zombie: stuck running >30 min". That measures QUEUE WAIT, not RUN TIME. Since
jobs waited an average of 59 minutes to be claimed, a job was eligible for
reaping the INSTANT a worker picked it up.

Measured 2026-07-28 over the 2,183 reaped rows:

    avg wait to be claimed ........... 59.0 min   (already past the deadline)
    avg actually held (claim->reap) ... 6.2 min
    claimed AFTER the deadline ........ 1,962 / 2,183 = 89.9%

So ~90% were healthy, actively-running jobs shot mid-flight — 2,022 rows, 57% of
ALL dispatch failures. The label made it worse than the loss: it said "stuck",
so the queue looked like it was hanging when it was being killed.

Corroboration that the fix is the intended behaviour and not a preference: the
OTHER reaper (model_dispatch_service.py:1411, "reaped: stuck running > 900s")
already measures from claimed_at. Same job, correct clock, 133 rows instead of
2,022.

These tests exercise the REAL SQL against the REAL database with scratch rows,
because the bug was in a WHERE clause — a source-level assertion would not have
caught an off-by-one-column predicate.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("DB_HOST"), reason="needs the platform database")

REAPER_SQL = """
    UPDATE dispatch_pending_queue
       SET status = 'failed',
           error = 'zombie: held >30 min after claim (no result returned)'
     WHERE status = 'running'
       AND COALESCE(claimed_at, queued_at) < NOW() - INTERVAL '30 minutes'
       AND id = %s
    RETURNING id
"""

OLD_REAPER_SQL = """
    UPDATE dispatch_pending_queue
       SET status = 'failed', error = 'zombie: stuck running >30 min'
     WHERE status = 'running'
       AND queued_at < NOW() - INTERVAL '30 minutes'
       AND id = %s
    RETURNING id
"""


def _mk(cur, *, queued_min_ago, claimed_min_ago):
    """Insert a scratch 'running' row and return its id."""
    claimed = "NOW() - INTERVAL '%d minutes'" % claimed_min_ago if claimed_min_ago is not None else "NULL"
    cur.execute(
        f"""INSERT INTO dispatch_pending_queue
              (capability, model_needed, prompt, status, queued_at, claimed_at, agent_name)
            VALUES ('test_reaper','qwen2.5:1.5b','scratch','running',
                    NOW() - INTERVAL '{int(queued_min_ago)} minutes', {claimed}, 'TEST')
            RETURNING id"""
    )
    return cur.fetchone()["id"]


@pytest.fixture
def cur():
    import sys

    sys.path.insert(0, "/app")
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (_conn, c):
        made = []
        yield c, made
        if made:
            c.execute("DELETE FROM dispatch_pending_queue WHERE id = ANY(%s)", (made,))


class TestClockStartsAtClaim:
    def test_recently_claimed_job_survives(self, cur):
        """THE BUG. Queued 90 min ago, claimed 2 min ago — actively running."""
        c, made = cur
        jid = _mk(c, queued_min_ago=90, claimed_min_ago=2)
        made.append(jid)

        c.execute(REAPER_SQL, (jid,))
        assert c.fetchone() is None, "a job claimed 2 minutes ago is NOT a zombie"

        c.execute("SELECT status FROM dispatch_pending_queue WHERE id=%s", (jid,))
        assert c.fetchone()["status"] == "running"

    def test_the_old_clause_WOULD_have_killed_it(self, cur):
        """Proves the fix changes behaviour — not a no-op refactor."""
        c, made = cur
        jid = _mk(c, queued_min_ago=90, claimed_min_ago=2)
        made.append(jid)

        c.execute(OLD_REAPER_SQL, (jid,))
        assert c.fetchone() is not None, (
            "the old queued_at clause reaps a job that started 2 minutes ago — " "this is the 89.9% case"
        )

    def test_genuinely_held_job_is_still_reaped(self, cur):
        """The reaper must still do its job: claimed 45 min ago, no result."""
        c, made = cur
        jid = _mk(c, queued_min_ago=120, claimed_min_ago=45)
        made.append(jid)

        c.execute(REAPER_SQL, (jid,))
        assert c.fetchone() is not None, "45 minutes after claim with no result IS a zombie"


class TestOrphanSafetyNet:
    def test_running_row_with_no_claimed_at_falls_back_to_queued_at(self, cur):
        """A restart between claim and write leaves claimed_at NULL — still reap."""
        c, made = cur
        jid = _mk(c, queued_min_ago=90, claimed_min_ago=None)
        made.append(jid)

        c.execute(REAPER_SQL, (jid,))
        assert c.fetchone() is not None, "COALESCE must keep the orphan fallback"

    def test_fresh_unclaimed_running_row_is_not_reaped(self, cur):
        c, made = cur
        jid = _mk(c, queued_min_ago=5, claimed_min_ago=None)
        made.append(jid)

        c.execute(REAPER_SQL, (jid,))
        assert c.fetchone() is None


class TestErrorMessageContract:
    def test_message_still_starts_with_zombie(self, cur):
        """test_dispatch_cycle asserts `"zombie" in error_message` — keep that true."""
        c, made = cur
        jid = _mk(c, queued_min_ago=120, claimed_min_ago=45)
        made.append(jid)

        c.execute(REAPER_SQL, (jid,))
        c.execute("SELECT error FROM dispatch_pending_queue WHERE id=%s", (jid,))
        err = c.fetchone()["error"]
        assert "zombie" in err
        assert "stuck running" not in err, "the old wording asserted a fact that was false for ~90% of rows"
