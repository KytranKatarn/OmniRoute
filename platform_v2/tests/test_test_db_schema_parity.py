"""The test database must be able to INSERT a row without naming `id`.

Measured 2026-09-21 (task #6821):

    archie       tables with an `id` DEFAULT nextval(...)   674
    archie_test  tables with an `id` DEFAULT nextval(...)     0
    archie_test  sequences present                          677

The sequences existed; only the column DEFAULTs were missing. pytest forces
archie_test, so **every test that inserted a row without naming `id` failed there** —
found via `tests/test_fleet_stats_node_count.py`, whose 3 tests errored at SETUP with
`NotNullViolation: null value in column "id"`. They ERRORED rather than failed, which
reads as environment noise, so they looked like coverage while never once executing.

Repaired by `scripts/repair_test_db_id_defaults.py` (prod-derived, dry-run by default,
refuses any DB not named `*_test`). This file is the guard that the drift cannot return
silently: a rebuilt test DB that loses the defaults again turns these red instead of
quietly turning a class of tests into permanent errors.

⚠️ Deliberately BEHAVIOURAL, not a catalogue count. An earlier draft asserted a
threshold ("at least N tables have a default"), which passes while the one table your
test needs is broken. Inserting and rolling back asks the only question that matters.
"""

from __future__ import annotations

import pytest

from database import get_db_cursor

# Tables real test fixtures seed. remote_nodes is the one that surfaced the defect;
# the others are frequent enough that losing them would strand whole files again.
SEEDED_TABLES = ["remote_nodes", "agents", "unified_tasks", "knowledge_base"]


@pytest.mark.parametrize("table", SEEDED_TABLES)
def test_id_has_a_sequence_default(table):
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT column_default
              FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = %s AND column_name = 'id'
            """,
            (table,),
        )
        row = cur.fetchone()
    assert row is not None, f"{table}.id not found — schema drift beyond defaults"
    default = row["column_default"] if isinstance(row, dict) else row[0]
    assert default and "nextval" in default, (
        f"{table}.id has no sequence default ({default!r}). Every INSERT that does not "
        f"name `id` will fail with NotNullViolation. Repair: "
        f"scripts/repair_test_db_id_defaults.py --apply"
    )


def test_an_insert_that_omits_id_actually_works():
    """The behavioural question. A correct catalogue row is not proof the INSERT lands.

    Rolled back, so it leaves nothing behind. `node_id` is NOT NULL-ish in practice and
    carries a UNIQUE constraint, so the value is namespaced to this test.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            INSERT INTO remote_nodes (node_id, node_name, status, deployment_mode)
            VALUES ('t_schema_parity_probe', 'Schema Parity Probe', 'offline', 'outpost')
            RETURNING id
            """
        )
        row = cur.fetchone()
        new_id = row["id"] if isinstance(row, dict) else row[0]
        conn.rollback()
    assert (
        isinstance(new_id, int) and new_id > 0
    ), "the sequence did not supply an id — see scripts/repair_test_db_id_defaults.py"
