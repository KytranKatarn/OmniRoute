"""Sandbox SQL safety with mocked resources: no DDL, Docker or production mutation."""

from unittest.mock import MagicMock, patch

import pytest
from psycopg2 import sql

from tools.repair_bay.services.sandbox_sql import drop_sandbox_schema_statement
from tools.repair_bay.services import cleanup_orphaned_sandboxes as cleanup
from tools.repair_bay.services import sandbox_manager


@pytest.mark.parametrize("name", ["sandbox", "sandbox_123", "sandbox_email_manager"])
def test_drop_quotes_one_identifier(name):
    statement = drop_sandbox_schema_statement(name)
    assert isinstance(statement, sql.Composed)
    assert list(statement) == [sql.SQL("DROP SCHEMA IF EXISTS "), sql.Identifier(name), sql.SQL(" CASCADE")]


@pytest.mark.parametrize(
    "name",
    [
        None,
        123,
        "",
        "public",
        "archie",
        "sandboxevil",
        "sandbox; DROP SCHEMA public CASCADE;--",
        'sandbox_";--',
        "sandbox_foo.bar",
        "sandbox_foo\n",
        "sandbox_" + "a" * 60,
    ],
)
def test_non_sandbox_or_hostile_names_are_rejected(name):
    with pytest.raises(ValueError):
        drop_sandbox_schema_statement(name)


def test_cleanup_preserves_active_and_refuses_hostile_identifiers():
    conn = MagicMock()
    cur = conn.cursor.return_value
    cur.fetchall.side_effect = [
        [("sandbox_active",), ("sandbox_orphan",), ("sandbox; DROP SCHEMA public CASCADE;--",)],
        [("sandbox_active",)],
    ]
    with patch.object(cleanup, "get_db", return_value=conn):
        cleanup.cleanup_orphaned_schemas()
    statements = [call.args[0] for call in cur.execute.call_args_list]
    assert len(statements) == 3  # Two reads and exactly one safe DDL, not hostile DDL.
    assert statements[-1] == drop_sandbox_schema_statement("sandbox_orphan")
    conn.commit.assert_called_once()
    conn.rollback.assert_called_once()
    cur.close.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.parametrize(
    "name,success",
    [("sandbox_email_manager", True), ("public", False), ("sandbox; DROP SCHEMA public CASCADE;--", False)],
)
def test_module_destroy_uses_safe_ddl_or_rolls_back(name, success):
    manager = sandbox_manager.SandboxManager.__new__(sandbox_manager.SandboxManager)
    conn = MagicMock()
    cur = conn.cursor.return_value
    cur.fetchone.return_value = {"sandbox_type": "schema", "schema_name": name}
    manager.get_db = MagicMock(return_value=conn)
    with patch.object(sandbox_manager, "DOCKER_AVAILABLE", False), patch.object(sandbox_manager.subprocess, "run"):
        result = manager.destroy_module_sandbox("email_manager")
    assert result["success"] is success
    statements = [call.args[0] for call in cur.execute.call_args_list]
    if success:
        assert statements[1] == drop_sandbox_schema_statement(name)
        conn.commit.assert_called_once()
    else:
        assert len(statements) == 1  # Select only; rejected name never reaches execute.
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()
