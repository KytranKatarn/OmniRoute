"""Receipts for entity-graph pushes, written by the RECEIVER.

2026-10-05: gov-watch's push into the shared graph failed every batch for ~17 days (61,022 failed
batches: its ENTITY_INGEST_URL pointed at the hub, where nothing listens) and nobody was told. Its own
freshness monitor could not fire: `entity_graph_push` sat in its watch list with no heartbeat writer,
because the deployed image predated the writer. A watcher inside the SENDER fails with the sender, so
this watches from the receiving side instead: every product that pushes leaves a row in
parliament.ingest_log, and drift_guard alarms through A.R.C.H.I.E. when one goes quiet — whether the
cause is a wrong URL, a dead sender, stale deployed code, or a job that stopped scheduling.

A receipt is written only for a batch that actually carried data, so a bare connectivity probe is not
proof of a working feed, and at most once per product per throttle window so a 3,000-batch catch-up
does not write 3,000 rows. The task names are literals on purpose: tests/test_drift_guard_registration
looks for them by name.
"""
import logging

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest.entity_push_receipts")

PUSH_TASKS = {
    "gov-watch": "entity_push_gov-watch",
    "legal-watch": "entity_push_legal-watch",
    "civic-watch": "entity_push_civic-watch",
    "market-watch": "entity_push_market-watch",
}

THROTTLE_MINUTES = 30

_INSERT = """
    INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted)
    SELECT :t, :seen, :saved
    WHERE NOT EXISTS (
        SELECT 1 FROM parliament.ingest_log
         WHERE task = :t AND run_at > now() - make_interval(mins => :m)
    )
"""


def record_push(conn, product, seen, saved, throttle_minutes=THROTTLE_MINUTES):
    """Record that ``product`` delivered a batch. Never raises: a receipt must not fail an ingest.

    Runs in a SAVEPOINT so a failed INSERT cannot abort the caller's transaction. Returns True when
    a row was written, False when skipped (unknown product, empty batch, throttled, or error).
    """
    task = PUSH_TASKS.get(product)
    if task is None or not (seen or saved):
        return False
    try:
        with conn.begin_nested():
            res = conn.execute(text(_INSERT), {"t": task, "seen": int(seen), "saved": int(saved),
                                               "m": int(throttle_minutes)})
        return bool(getattr(res, "rowcount", 0))
    except Exception:  # noqa: BLE001 - observability must never take the ingest down
        logger.warning("entity push receipt failed for %s", product, exc_info=True)
        return False
