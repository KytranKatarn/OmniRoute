"""
Snapshot lifecycle and diff engine.

Two-snapshot phantom-departure rule: an employee is marked departed_at only
when their last_seen falls ON OR BEFORE the run_finished_at of the previous
snapshot. This means a transient parse failure in a single nightly run does
not mass-departure everyone — the row only flips after a SECOND consecutive
miss.
"""

import logging
from typing import Dict, Optional

log = logging.getLogger(__name__)

OPEN_SQL = """
INSERT INTO civic_transparency.geds_snapshots (status)
VALUES ('running')
RETURNING id
"""

CLOSE_SQL = """
UPDATE civic_transparency.geds_snapshots
   SET run_finished_at = now(),
       status = %s,
       org_units_seen = %s,
       employees_seen = %s,
       employees_new = %s,
       employees_departed = %s,
       employees_changed = %s,
       error_message = %s
 WHERE id = %s
"""


def open_snapshot(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(OPEN_SQL)
        snap_id = cur.fetchone()[0]
    conn.commit()
    return snap_id


def close_snapshot(
    conn,
    snap_id: int,
    *,
    status: str = "completed",
    org_units_seen: int = 0,
    employees_seen: int = 0,
    employees_new: int = 0,
    employees_departed: int = 0,
    employees_changed: int = 0,
    error_message: Optional[str] = None,
):
    with conn.cursor() as cur:
        cur.execute(
            CLOSE_SQL,
            (
                status,
                org_units_seen,
                employees_seen,
                employees_new,
                employees_departed,
                employees_changed,
                error_message,
                snap_id,
            ),
        )
    conn.commit()


def detect_movements(conn, snapshot_id: int) -> Dict[str, int]:
    """
    Compare federal_employees as of THIS snapshot vs the most recent prior
    snapshot with status='completed'. Insert geds_movements rows. Return
    aggregate counts. On first run (no prior), returns all zeros.
    """
    out = {
        "new": 0,
        "departed": 0,
        "title_changed": 0,
        "org_changed": 0,
        "classification_changed": 0,
    }

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM civic_transparency.geds_snapshots
             WHERE id < %s AND status = 'completed'
             ORDER BY id DESC LIMIT 1
            """,
            (snapshot_id,),
        )
        row = cur.fetchone()
    if row is None:
        log.info("No prior snapshot — first run, no movements emitted.")
        return out
    prior_id = row[0]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_finished_at FROM civic_transparency.geds_snapshots WHERE id=%s",
            (prior_id,),
        )
        prior_finished = cur.fetchone()[0]

        # NEW: employees first_seen after prior snapshot's finish
        cur.execute(
            """
            INSERT INTO civic_transparency.geds_movements
              (snapshot_id, employee_id, movement_type, before_value, after_value)
            SELECT %s, e.id, 'new', NULL,
                   jsonb_build_object('surname', e.surname, 'title_en', e.title_en,
                                      'org_unit_id', e.org_unit_id)
              FROM civic_transparency.federal_employees e
             WHERE e.first_seen > %s
            """,
            (snapshot_id, prior_finished),
        )
        out["new"] = cur.rowcount

        # DEPARTED: still active but missed in BOTH this run and prior.
        # Two-snapshot rule: last_seen <= prior_finished means they were missed
        # in the prior run too. Only then do we set departed_at.
        cur.execute(
            "SELECT run_started_at FROM civic_transparency.geds_snapshots WHERE id=%s",
            (snapshot_id,),
        )
        this_started = cur.fetchone()[0]

        cur.execute(
            """
            WITH dep AS (
                UPDATE civic_transparency.federal_employees e
                   SET departed_at = %s
                 WHERE departed_at IS NULL
                   AND last_seen < %s
                   AND last_seen <= %s
                RETURNING e.id, e.surname, e.title_en, e.org_unit_id
            )
            INSERT INTO civic_transparency.geds_movements
              (snapshot_id, employee_id, movement_type, before_value, after_value)
            SELECT %s, dep.id, 'departed',
                   jsonb_build_object('surname', dep.surname, 'title_en', dep.title_en,
                                      'org_unit_id', dep.org_unit_id),
                   NULL
              FROM dep
            """,
            (this_started, this_started, prior_finished, snapshot_id),
        )
        out["departed"] = cur.rowcount

    conn.commit()
    log.info("Movements detected: %s", out)
    return out
