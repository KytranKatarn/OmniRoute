"""
End-to-end orchestrator for a single GEDS refresh.

Sequence:
  open_snapshot
  Pass A   (walk org tree)
  Pass B   (sweep people)
  Pass B-2 (resolve managers)
  Pass C   (enrich quick lists)
  detect_movements
  close_snapshot
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import psycopg2

from services.civic_geds_client import GedsClient
from services.civic_geds_pass_a import OrgUnitWriter, walk_org_tree
from services.civic_geds_pass_b import EmployeeWriter, sweep_people
from services.civic_geds_pass_b2_manager import resolve_managers
from services.civic_geds_pass_c import enrich_quick_lists
from services.civic_geds_snapshot import (
    close_snapshot,
    detect_movements,
    open_snapshot,
)

log = logging.getLogger(__name__)


def _get_db_password() -> str:
    secret = Path("/run/secrets/db_password")
    if secret.exists():
        return secret.read_text().strip()
    return os.getenv("DB_PASSWORD", "")


def _db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "192.168.1.200"),
        dbname=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


async def run_geds_refresh(rate_per_sec: float = 2.0, max_depth: int = 5):
    conn = _db()
    snap = open_snapshot(conn)
    log.info("GEDS refresh: snapshot %d started", snap)

    employees_seen = 0
    org_units_seen = 0
    status = "completed"
    err: Optional[str] = None
    movements = {
        "new": 0,
        "departed": 0,
        "title_changed": 0,
        "org_changed": 0,
        "classification_changed": 0,
    }

    try:
        async with GedsClient(rate_per_sec=rate_per_sec) as client:
            org_units_seen = await walk_org_tree(client, OrgUnitWriter(conn), max_depth=max_depth)

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, dn_b64
                      FROM civic_transparency.org_units
                     WHERE last_seen > now() - INTERVAL '24 hours'
                    """
                )
                leaf_units = [{"id": r[0], "dn_b64": r[1]} for r in cur.fetchall()]

            employees_seen = await sweep_people(client, leaf_units, EmployeeWriter(conn))
            resolve_managers(conn)
            await enrich_quick_lists(client, conn)
        movements = detect_movements(conn, snap)
    except Exception as e:
        status = "failed"
        err = str(e)[:1000]
        log.exception("GEDS refresh failed")
    finally:
        close_snapshot(
            conn,
            snap,
            status=status,
            org_units_seen=org_units_seen,
            employees_seen=employees_seen,
            employees_new=movements["new"],
            employees_departed=movements["departed"],
            employees_changed=(
                movements["title_changed"] + movements["org_changed"] + movements["classification_changed"]
            ),
            error_message=err,
        )
        conn.close()
    log.info(
        "GEDS refresh: snapshot %d %s — %d depts, %d people",
        snap,
        status,
        org_units_seen,
        employees_seen,
    )


def run_geds_refresh_sync():
    """Sync entry-point for APScheduler (which doesn't await)."""
    asyncio.run(run_geds_refresh())
