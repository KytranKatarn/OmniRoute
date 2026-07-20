"""Tests for scan_service.get_issues(auto_fixable=...) — #5000.

The A.R.C.H.I.E. Engine build loop picks the HIGHEST-SEVERITY in-scope open
issue. Measured 2026-07-19 against 2,230 open issues, 96% of the open
`security/high` bucket was "Potential SQL injection vulnerability" — the same
class audit_pipeline already refuses to auto-fix (fix-gen produced 100% garbage,
KB #282665). So without a fixability filter the engine draws that class almost
every cycle.

These tests pin the SQL shape rather than hitting the database: the point is
that (a) the default is byte-identical to the old behaviour, and (b) opting in
adds exclusions without dropping the status filter.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(**kwargs):
    """Call get_issues with a mocked cursor; return (sql, params)."""
    from services import scan_service

    cur = MagicMock()
    cur.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch.object(scan_service, "_get_db", return_value=conn):
        scan_service.get_issues(**kwargs)

    assert cur.execute.called, "get_issues never executed a query"
    sql, params = cur.execute.call_args[0]
    return " ".join(sql.split()), params


class TestDefaultUnchanged:
    """The default path must not change for existing callers (UI, Repair Bay)."""

    def test_default_has_no_exclusions(self):
        sql, params = _run(status="open", limit=50)
        assert "NOT LIKE" not in sql
        assert "SQL injection" not in str(params)
        assert params == ("open", 50)

    def test_status_all_default_is_bare(self):
        sql, params = _run(status="all", limit=25)
        assert "WHERE" not in sql
        assert params == (25,)

    def test_auto_fixable_defaults_to_false(self):
        """Omitting the kwarg entirely must behave like the old signature."""
        sql, params = _run(status="open", limit=10)
        assert "NOT LIKE" not in sql
        assert params == ("open", 10)


class TestAutoFixableFilter:
    def test_excludes_sql_injection(self):
        sql, params = _run(status="open", limit=50, auto_fixable=True)
        assert "NOT LIKE" in sql
        assert "%SQL injection%" in params

    def test_excludes_hardcoded_secret_only_in_test_paths(self):
        """Secret findings survive in real source; only the test-file context is dropped."""
        sql, params = _run(status="open", limit=50, auto_fixable=True)
        assert "%hardcoded secret%" in params
        assert "%test%" in params
        # the pairing must be an AND inside a NOT(...) — not two blanket excludes
        assert "NOT (COALESCE(i.message, '') LIKE %s AND COALESCE(i.file_path, '') LIKE %s)" in sql

    def test_status_filter_still_applied(self):
        """Opting in must not silently widen the status scope."""
        sql, params = _run(status="open", limit=50, auto_fixable=True)
        assert "i.status = %s" in sql
        assert params[0] == "open"

    def test_limit_is_last_param(self):
        """Ordering matters — LIMIT %s is appended after every WHERE param."""
        _sql, params = _run(status="open", limit=77, auto_fixable=True)
        assert params[-1] == 77

    def test_status_all_with_auto_fixable_still_filters(self):
        """status='all' + auto_fixable must still produce a WHERE clause."""
        sql, params = _run(status="all", limit=50, auto_fixable=True)
        assert "WHERE" in sql
        assert "i.status" not in sql
        assert params[-1] == 50

    def test_null_safe(self):
        """NULL message/file_path must not silently drop rows (COALESCE guards)."""
        sql, _params = _run(status="open", limit=50, auto_fixable=True)
        assert sql.count("COALESCE(i.message, '')") >= 2
        assert "COALESCE(i.file_path, '')" in sql


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
