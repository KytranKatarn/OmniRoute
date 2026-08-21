"""Pending hires must be visible, and the age must be computed in SQL."""

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.department_hq import hiring_routes  # noqa: E402


class TestHiringPending(unittest.TestCase):
    def test_only_pending_is_selected(self):
        sql = hiring_routes.PENDING_SQL
        self.assertIn("status = 'pending'", sql)

    def test_age_is_computed_in_sql_not_python(self):
        """proposed_at may be naive; Python arithmetic on it raises TypeError."""
        self.assertIn("EXTRACT(EPOCH", hiring_routes.PENDING_SQL)
        src = inspect.getsource(hiring_routes)
        self.assertNotIn("now_utc() -", src)

    def test_uses_proposed_at_not_created_at(self):
        """hiring_candidates has NO created_at column."""
        self.assertIn("proposed_at", hiring_routes.PENDING_SQL)
        self.assertNotIn("created_at", hiring_routes.PENDING_SQL)

    def test_query_is_bounded(self):
        self.assertIn("LIMIT", hiring_routes.PENDING_SQL)


if __name__ == "__main__":
    unittest.main()
