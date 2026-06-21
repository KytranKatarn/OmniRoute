"""Guard tests: the suite MUST run against the isolated test DB, never prod.

Backstop for KB #274942 — a mock-dispatch test once wrote "mock" into 1,166
live translation rows because the suite silently connected to production.
"""

import os

from database import get_db_cursor


def _current_db():
    with get_db_cursor() as (_c, cur):
        cur.execute("SELECT current_database() AS db")
        row = cur.fetchone()
    return row["db"] if isinstance(row, dict) else row[0]


def test_connected_to_test_db_not_prod():
    live = _current_db()
    assert live != "archie", "tests must NEVER run against production 'archie'"
    assert live == os.environ.get("TEST_DB_NAME", "archie_test")


def test_pytest_flag_is_set():
    # The flag that makes database._get_pool() refuse the prod DB.
    assert os.environ.get("ARCHIE_PYTEST") == "1"
