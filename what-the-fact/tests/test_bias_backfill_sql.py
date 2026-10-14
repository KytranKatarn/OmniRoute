"""Manual backfill identifier quoting and cleanup against a fake database."""

from unittest.mock import MagicMock, Mock

import pytest
from psycopg2 import sql
from ingest import backfill_bias_v2 as backfill


@pytest.fixture
def database(monkeypatch):
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    conn = Mock()
    conn.cursor.return_value = cursor
    monkeypatch.setattr(backfill.psycopg2, "connect", Mock(return_value=conn))
    monkeypatch.setenv("WTF_DATABASE_URL", "postgresql://test-invalid/test")
    # Deterministic quote rendering without a live PostgreSQL connection.
    monkeypatch.setattr("psycopg2.extensions.quote_ident", lambda value, context: '"' + value.replace('"', '""') + '"')
    return conn, cursor


def test_schema_is_one_quoted_identifier_and_update_values_stay_bound(database, monkeypatch):
    conn, cursor = database
    schema = 'custom"; DROP SCHEMA public; --'
    monkeypatch.setattr(backfill, "SCHEMA", schema)
    monkeypatch.setattr(backfill, "BATCH", 1)
    cursor.fetchall.return_value = [
        {"title": "headline", "body": "body", "score_id": 9, "heuristic_version": "v1"},
        {"heuristic_version": "v3"},
    ]
    monkeypatch.setattr(
        backfill,
        "score_bias",
        Mock(return_value={"band": "center", "score": 0, "rationale": "test rationale", "heuristic_version": "v3"}),
    )
    backfill.main()
    select, update = cursor.execute.call_args_list
    assert isinstance(select.args[0], sql.Composed) and isinstance(update.args[0], sql.Composed)
    quoted = '"custom""; DROP SCHEMA public; --"'
    assert quoted + ".articles" in select.args[0].as_string(None)
    assert quoted + ".bias_scores" in update.args[0].as_string(None)
    assert update.args[1] == ("center", 0, "test rationale", "v3", 9)
    assert conn.commit.call_count == 2 and conn.close.called


def test_database_failure_closes_cursor_and_connection(database):
    conn, cursor = database
    cursor.execute.side_effect = RuntimeError("test database failure")
    with pytest.raises(RuntimeError, match="test database failure"):
        backfill.main()
    assert cursor.__exit__.called and conn.close.called
    conn.commit.assert_not_called()
