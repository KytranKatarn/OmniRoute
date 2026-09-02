"""Guards for geo throughput measurement (#6263, migration 073).

`/activity` showed a geo burn-down computed from `geo_confidence`, a column that
does not exist. The whole analytics SELECT shared one try/except, so the WORKING
`llm_hr` metric died with it — the LLM pipeline ran at 103.5/hr while the public
page reported zero.

The obvious repair (count `province_code IS NOT NULL` over recently PUBLISHED
articles) is measured-wrong: the backlog is 3,552 articles of which 1,905 (54%)
were published over 30 days ago, so a rate taken from the last 6 hours of
publications yields an ETA of 4.6 days for a queue that has not moved in a month.
The fix is to measure when geocoding ACTUALLY happened.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sql(rel: str) -> str:
    return (ROOT / rel).read_text()


# --------------------------------------------------------------------------
# Both write sites must stamp — an article leaves the pending set either way
# --------------------------------------------------------------------------

def test_ingest_time_geo_write_stamps_the_timestamp():
    """persist.save_geo() — the path taken when geo is resolved at ingest."""
    src = _sql("ingest/persist.py")
    assert "geo_processed_at = NOW()" in src


def test_backlog_worker_stamps_the_timestamp():
    """geo_backlog_worker._persist() — the path that drains the backlog."""
    src = _sql("ingest/geo_backlog_worker.py")
    assert "geo_processed_at = NOW()" in src


def test_backlog_worker_stamps_on_the_SAME_update_as_geo_scope():
    """The stamp must ride the existing UPDATE, not a second statement.

    A separate UPDATE could fail independently and leave an article geocoded but
    unstamped — invisible to the metric while looking processed, which is the
    class of bug this whole task is about.
    """
    src = _sql("ingest/geo_backlog_worker.py")
    stmt = src[src.index("UPDATE {schema}.articles") : src.index("WHERE id")]
    assert "geo_scope" in stmt and "geo_processed_at" in stmt


def test_unmappable_is_also_a_stamped_outcome():
    """`unmappable` is terminal — L.O.C.A.L. tried and gave up. It removes the
    article from `province_code IS NULL AND geo_scope <> 'unmappable'` just as a
    success does. Counting only successes understates the drain rate and
    reproduces the too-optimistic ETA this replaces.

    The worker writes ONE update for both outcomes (geo_scope is a bound
    parameter), so a single unconditional stamp covers both — asserted by the
    absence of any conditional wrapping around it.
    """
    src = _sql("ingest/geo_backlog_worker.py")
    assert "geo_processed_at = NOW()," in src
    assert "CASE" not in src[src.index("geo_processed_at") : src.index("geo_processed_at") + 60]


# --------------------------------------------------------------------------
# The migration
# --------------------------------------------------------------------------

def test_migration_exists_and_is_idempotent():
    m = _sql("migrations/073_geo_processed_at.sql")
    assert "ADD COLUMN IF NOT EXISTS geo_processed_at" in m
    assert "CREATE INDEX IF NOT EXISTS" in m


def test_migration_does_NOT_backfill():
    """Deriving a timestamp from published_at would fabricate a history that
    never happened. The metric is a FORWARD rate; it needs one real interval,
    not a synthesised past. Expect 0/hr until the first cycle after deploy."""
    m = _sql("migrations/073_geo_processed_at.sql")
    assert "UPDATE wtf.articles" not in m
    assert "SET geo_processed_at" not in m


def test_migration_grants_to_wtfuser():
    """New wtf objects must be granted or the app cannot use them — apps do not
    connect as the owner (the migration-047 lesson)."""
    m = _sql("migrations/073_geo_processed_at.sql")
    assert "wtfuser" in m


def test_the_dead_column_is_not_reintroduced_AS_A_COLUMN():
    """`geo_confidence` never existed. If it reappears in a QUERY the analytics
    block starts throwing again and takes llm_hr down with it.

    Deliberately checks for USE (a comparison, assignment or NULL test), not for
    the mere string: the migration names it in prose to explain what went wrong,
    and a test that forbids documenting a bug pushes the explanation out of the
    code. The first version of this test did exactly that and failed on its own
    migration.
    """
    import re

    use = re.compile(r"geo_confidence\s*(=|>|<|IS\b|,)", re.I)
    for rel in ("ingest/persist.py", "ingest/geo_backlog_worker.py",
                "migrations/073_geo_processed_at.sql"):
        assert not use.search(_sql(rel)), rel
