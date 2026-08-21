"""Decommission must not silently create a capability dead-end."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import agent_lifecycle  # noqa: E402


class TestDecommissionPrecheck(unittest.TestCase):
    def _agent(self, **kw):
        base = {
            "id": 7,
            "name": "T.E.S.T.",
            "display_name": "T.E.S.T.",
            "is_department_ai": False,
            "department": "Engineering & Technology",
            "shift_state": "active",
        }
        base.update(kw)
        return base

    def test_sole_skill_holder_is_warned_and_skills_named(self):
        with patch.object(agent_lifecycle, "get_agent", return_value=self._agent()), patch.object(
            agent_lifecycle, "_skills_of", return_value=["code_review", "debug"]
        ), patch.object(
            agent_lifecycle, "_other_active_holders", side_effect=lambda s, a: 0 if s == "code_review" else 3
        ):
            out = agent_lifecycle.decommission_precheck(7)
        sole = [w for w in out["warnings"] if w["kind"] == "sole_skill_holder"]
        self.assertEqual(len(sole), 1)
        self.assertEqual(sole[0]["skills"], ["code_review"])
        self.assertNotIn("debug", sole[0]["skills"])

    def test_department_director_is_warned(self):
        with patch.object(agent_lifecycle, "get_agent", return_value=self._agent(is_department_ai=True)), patch.object(
            agent_lifecycle, "_skills_of", return_value=[]
        ), patch.object(agent_lifecycle, "_other_active_holders", return_value=5):
            out = agent_lifecycle.decommission_precheck(7)
        self.assertTrue(any(w["kind"] == "department_director" for w in out["warnings"]))

    def test_clean_agent_has_no_warnings(self):
        with patch.object(agent_lifecycle, "get_agent", return_value=self._agent()), patch.object(
            agent_lifecycle, "_skills_of", return_value=["code_review"]
        ), patch.object(agent_lifecycle, "_other_active_holders", return_value=4):
            out = agent_lifecycle.decommission_precheck(7)
        self.assertEqual(out["warnings"], [])
        self.assertFalse(out["blocking"])

    def test_missing_agent_raises(self):
        with patch.object(agent_lifecycle, "get_agent", return_value=None):
            with self.assertRaises(ValueError):
                agent_lifecycle.decommission_precheck(999)


class TestDecommissionAgent(unittest.TestCase):
    def test_refuses_when_warnings_not_acknowledged(self):
        pre = {
            "agent": {"id": 7, "shift_state": "active"},
            "warnings": [{"kind": "sole_skill_holder", "message": "x", "skills": ["code_review"]}],
            "blocking": False,
        }
        with patch.object(agent_lifecycle, "decommission_precheck", return_value=pre), patch.object(
            agent_lifecycle, "update_agent"
        ) as upd:
            out = agent_lifecycle.decommission_agent(7, acknowledge_warnings=False)
        self.assertFalse(out["ok"])
        self.assertIsNotNone(out["refused"])
        upd.assert_not_called()

    def test_proceeds_when_acknowledged(self):
        pre = {
            "agent": {"id": 7, "shift_state": "active"},
            "warnings": [{"kind": "sole_skill_holder", "message": "x", "skills": ["code_review"]}],
            "blocking": False,
        }
        with patch.object(agent_lifecycle, "decommission_precheck", return_value=pre), patch.object(
            agent_lifecycle, "update_agent"
        ) as upd:
            out = agent_lifecycle.decommission_agent(7, acknowledge_warnings=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["previous"], "active")
        upd.assert_called_once()
        self.assertEqual(upd.call_args.kwargs.get("shift_state"), "decommissioned")

    def test_no_warnings_needs_no_acknowledgement(self):
        pre = {"agent": {"id": 7, "shift_state": "active"}, "warnings": [], "blocking": False}
        with patch.object(agent_lifecycle, "decommission_precheck", return_value=pre), patch.object(
            agent_lifecycle, "update_agent"
        ) as upd:
            out = agent_lifecycle.decommission_agent(7, acknowledge_warnings=False)
        self.assertTrue(out["ok"])
        upd.assert_called_once()

    def test_never_issues_a_delete(self):
        import inspect

        src = inspect.getsource(agent_lifecycle.decommission_agent)
        self.assertNotIn("DELETE", src.upper())


if __name__ == "__main__":
    unittest.main()
