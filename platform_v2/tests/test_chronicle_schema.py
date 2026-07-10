"""Schema smoke for migration 453 — Chronicle schema (slice 02/09).

Verifies: mailbox_imports/mailbox_emails gain the source-provenance + full-body
+ embedding columns, the new mailbox_attachments table + its unique index, and
the cross-source chronicle_* layer (entity/link/story/voice) all exist.
See database/migrations/453_chronicle_schema.sql and
docs/superpowers/specs/2026-07-10-chronicle-multi-source-entity-hub-design.md.

Uses the platform's `database.get_db_cursor()` helper (respects the isolated
test-DB override wired in conftest.py — see KB #274942). This test can only
PASS once the migration has been applied to whichever database the running
container points at (prod now; archie_test after the branch merges and the
test-DB clone is refreshed, e.g. via TEST_DB_REBUILD=1).
"""

from __future__ import annotations

import pytest

from database import get_db_cursor


def _columns_for(table_name):
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table_name,),
        )
        rows = cur.fetchall()
    # RealDictCursor rows are dict-like; plain cursor rows are tuples.
    return {r["column_name"] if isinstance(r, dict) else r[0] for r in rows}


def _table_exists(table_name):
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
        row = cur.fetchone()
    val = row["to_regclass"] if isinstance(row, dict) else row[0]
    return val is not None


@pytest.mark.parametrize(
    "column_name",
    ["source_kind", "source_account_id", "is_live_source"],
)
def test_mailbox_imports_has_source_provenance_columns(column_name):
    cols = _columns_for("mailbox_imports")
    assert column_name in cols, f"mailbox_imports.{column_name} column missing"


@pytest.mark.parametrize("column_name", ["body_html", "embedding"])
def test_mailbox_emails_has_body_and_embedding_columns(column_name):
    cols = _columns_for("mailbox_emails")
    assert column_name in cols, f"mailbox_emails.{column_name} column missing"


@pytest.mark.parametrize(
    "table_name",
    [
        "mailbox_attachments",
        "chronicle_entity",
        "chronicle_entity_link",
        "chronicle_entity_story",
        "chronicle_voice_profile",
    ],
)
def test_chronicle_tables_exist(table_name):
    assert _table_exists(table_name), f"{table_name} table missing"


def test_mailbox_attachments_email_sha_unique_index_exists():
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'mailbox_attachments'
              AND indexname = 'uq_mailbox_attachments_email_sha'
            """
        )
        row = cur.fetchone()
    assert row, "uq_mailbox_attachments_email_sha index missing on mailbox_attachments"
