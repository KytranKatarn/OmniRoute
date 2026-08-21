"""A batch over N targets is N decisions — each one reports its own outcome."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.department_hq import roster_routes  # noqa: E402


class TestBulkShiftResults(unittest.TestCase):
    def test_partial_failure_is_visible_per_agent(self):
        def fake_update(agent_id, **fields):
            if agent_id == 2:
                raise ValueError("boom")

        agents = {1: {"name": "A.L.P.H.A.", "shift_state": "active"}, 2: {"name": "B.E.T.A.", "shift_state": "active"}}
        with patch.object(roster_routes, "update_agent", side_effect=fake_update), patch.object(
            roster_routes, "get_agent", side_effect=lambda i: agents.get(i)
        ):
            out = roster_routes._apply_bulk_shift([1, 2], "barracked")

        self.assertEqual(out["ok_count"], 1)
        self.assertEqual(out["failed_count"], 1)
        byid = {r["agent_id"]: r for r in out["results"]}
        self.assertTrue(byid[1]["ok"])
        self.assertEqual(byid[1]["previous"], "active")
        self.assertFalse(byid[2]["ok"])
        self.assertIn("boom", byid[2]["error"])

    def test_a_failure_does_not_abort_the_rest(self):
        """The failing agent is FIRST — later agents must still be attempted."""

        def fake_update(agent_id, **fields):
            if agent_id == 1:
                raise ValueError("boom")

        agents = {1: {"name": "A", "shift_state": "active"}, 2: {"name": "B", "shift_state": "active"}}
        with patch.object(roster_routes, "update_agent", side_effect=fake_update), patch.object(
            roster_routes, "get_agent", side_effect=lambda i: agents.get(i)
        ):
            out = roster_routes._apply_bulk_shift([1, 2], "barracked")
        self.assertEqual(out["ok_count"], 1)


if __name__ == "__main__":
    unittest.main()
