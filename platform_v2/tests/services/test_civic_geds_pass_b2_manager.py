from unittest.mock import MagicMock
from services.civic_geds_pass_b2_manager import resolve_managers


def test_resolve_managers_runs_self_join_update():
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    fake_cur.rowcount = 7

    n = resolve_managers(fake_conn)
    assert n == 7

    sql = fake_cur.execute.call_args.args[0]
    sql_lower = sql.lower()
    # Must be an UPDATE that joins federal_employees on itself by manager_dn = source_dn
    assert "update" in sql_lower
    assert "federal_employees" in sql_lower
    assert "manager_dn" in sql_lower
    assert "manager_id" in sql_lower
    assert "source_dn" in sql_lower

    # Must commit the transaction
    fake_conn.commit.assert_called_once()


def test_resolve_managers_returns_zero_when_nothing_to_update():
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    fake_cur.rowcount = 0

    n = resolve_managers(fake_conn)
    assert n == 0
