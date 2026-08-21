"""One filter definition, used by both the list and the count (spec A §8)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agent_service import _agent_filter_sql  # noqa: E402


class TestAgentFilterSql(unittest.TestCase):
    def test_worker_type_is_filterable(self):
        where, params = _agent_filter_sql(worker_type="ai")
        self.assertIn("a.worker_type = %s", where)
        self.assertIn("ai", params)

    def test_search_covers_title_acronym_and_department(self):
        where, params = _agent_filter_sql(search="forge")
        for col in ("a.name", "a.display_name", "a.title", "a.acronym", "a.department"):
            self.assertIn(col, where)
        self.assertEqual(params.count("%forge%"), 5)

    def test_status_defaults_to_active(self):
        where, params = _agent_filter_sql()
        self.assertIn("a.status = %s", where)
        self.assertIn("active", params)

    def test_no_filters_still_returns_a_usable_where(self):
        where, _ = _agent_filter_sql(status=None)
        self.assertFalse(where.strip().endswith("AND"))

    def test_no_shift_state_excludes_decommissioned(self):
        """This branch's widest-blast-radius change (affects every list_agents
        caller) had no test at all. Bug #5706: a decommissioned agent with
        status='active' was leaking through the roster/dispatch/org-chart."""
        where, params = _agent_filter_sql()
        self.assertIn("a.shift_state <> 'decommissioned'", where)
        self.assertNotIn("decommissioned", params)

    def test_explicit_decommissioned_shift_state_still_filters(self):
        """An explicit shift_state='decommissioned' request (e.g. admin audit
        tooling) must still work — the exclusion is only the no-filter default."""
        where, params = _agent_filter_sql(shift_state="decommissioned")
        self.assertIn("a.shift_state = %s", where)
        self.assertIn("decommissioned", params)
        self.assertNotIn("a.shift_state <> 'decommissioned'", where)


class TestCountSharesThePredicate(unittest.TestCase):
    def test_count_agents_uses_the_same_builder(self):
        import inspect

        from services import agent_service

        src = inspect.getsource(agent_service.count_agents)
        self.assertIn("_agent_filter_sql", src)

    def test_roster_route_no_longer_hand_builds_a_count(self):
        from pathlib import Path

        src = Path(__file__).resolve().parents[1] / "tools/department_hq/roster_routes.py"
        text = src.read_text()
        self.assertNotIn("count_conditions", text)
        self.assertIn("count_agents", text)


if __name__ == "__main__":
    unittest.main()
