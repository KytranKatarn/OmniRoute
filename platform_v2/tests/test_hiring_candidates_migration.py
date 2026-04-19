"""Schema smoke for hiring_candidates migration."""

from __future__ import annotations

import os
import psycopg2
import pytest


def _get_db_password():
    try:
        return open("/run/secrets/db_password").read().strip()
    except FileNotFoundError:
        return os.getenv("DB_PASSWORD", "")


def _conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        dbname=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def test_hiring_candidates_table_exists():
    c = _conn()
    try:
        with c.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name='hiring_candidates'
                ORDER BY ordinal_position
            """
            )
            cols = {r[0]: r[1] for r in cur.fetchall()}
    finally:
        c.close()
    assert cols, "hiring_candidates table missing"
    for name in [
        "id",
        "capability",
        "gap_reason",
        "gap_alert_id",
        "narrative",
        "shortlist",
        "proposed_at",
        "proposed_by_agent_id",
        "status",
        "chosen_agent_id",
        "decided_by_user_id",
        "decided_at",
        "decision_notes",
        "precheck_status",
        "precheck_message",
    ]:
        assert name in cols, f"hiring_candidates.{name} column missing"


def test_hiring_candidates_status_check_constraint():
    c = _conn()
    try:
        c.autocommit = False
        cur = c.cursor()
        cur.execute("SAVEPOINT sp1")
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO hiring_candidates (capability, gap_reason, status) " "VALUES ('x', 'x', 'bogus')")
        cur.execute("ROLLBACK TO SAVEPOINT sp1")
        cur.close()
        c.rollback()
    finally:
        c.close()


def test_hiring_candidates_partial_index_exists():
    c = _conn()
    try:
        with c.cursor() as cur:
            cur.execute(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE tablename='hiring_candidates' AND indexname='idx_hiring_candidates_cap_pending'
            """
            )
            row = cur.fetchone()
    finally:
        c.close()
    assert row and "WHERE" in row[0], f"expected partial index, got: {row}"
