"""Unit tests for agent_service.propose_hire (#2124).

Scope: validation guards + approval-queue action_data contract. DB
touched for name-collision lookup (via get_db_cursor) — uses a mock
psycopg2 cursor to avoid needing a real archie_test DB for this layer.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# Stub ``ai_bridge.agent_loop`` in sys.modules so ``propose_hire``'s deferred
# ``from ai_bridge.agent_loop import request_approval`` resolves without
# loading the real agent_loop (which pulls a ``db`` sibling not on test
# sys.path). Individual tests replace ``request_approval`` via patch().
_stub_pkg = sys.modules.setdefault("ai_bridge", types.ModuleType("ai_bridge"))
_stub_agent_loop = types.ModuleType("ai_bridge.agent_loop")
_stub_agent_loop.request_approval = MagicMock(return_value=None)
# PEP 562 catch-all — see #5665. This stub replaces ai_bridge.agent_loop for the WHOLE
# session, so any name a later-collected module needs must resolve or collection aborts
# for all 3,332 tests. test_media_drain_welfare_gate does `al.AgentLoop` and died here,
# even though the real ai_bridge/agent_loop.py DOES define it (line 523).
# The explicit request_approval mock above still wins.
_stub_agent_loop.__getattr__ = lambda _n: MagicMock()
sys.modules["ai_bridge.agent_loop"] = _stub_agent_loop
_stub_pkg.agent_loop = _stub_agent_loop

from services import agent_service  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_cursor(name_exists=False, existing_row=None):
    """Build a mocked ``get_db_cursor`` context manager.

    ``agent_service.propose_hire`` opens one cursor to look up the
    would-be name. Returning ``None`` means no collision; a row dict
    triggers the collision path.
    """
    cur = MagicMock()
    if name_exists:
        # 'name' is part of the row since #5272 — find_name_collision selects
        # id, name, shift_state so the caller can say WHICH name was collided
        # with (a dots/case twin is not obvious from the proposed name alone).
        cur.fetchone.return_value = existing_row or {
            "id": 99,
            "name": BASE_ARGS["name"],
            "shift_state": "decommissioned",
        }
    else:
        cur.fetchone.return_value = None
    conn = MagicMock()

    class _CM:
        def __enter__(self):
            return (conn, cur)

        def __exit__(self, *args):
            return False

    return _CM()


BASE_ARGS = {
    "name": "QUILL_TEST",
    "display_name": "Quill Test",
    "department": "Research & Development",
    "model": "mistral:7b",
    "capability": "translate",
    "reason": "Second translator to break ARCHIE bottleneck",
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestProposeHireValidation:
    @pytest.mark.parametrize(
        "missing",
        ["name", "display_name", "department", "model", "capability", "reason"],
    )
    def test_missing_required_field_rejected(self, missing):
        args = dict(BASE_ARGS)
        args[missing] = ""
        result = agent_service.propose_hire(**args, requested_by="t")
        assert result["success"] is False
        assert missing in result["error"]

    def test_blank_whitespace_rejected(self):
        args = dict(BASE_ARGS, reason="   ")
        result = agent_service.propose_hire(**args)
        assert result["success"] is False
        assert "reason" in result["error"]

    def test_invalid_department_rejected(self):
        args = dict(BASE_ARGS, department="Not A Real Dept")
        result = agent_service.propose_hire(**args)
        assert result["success"] is False
        assert "Invalid department" in result["error"]
        # Error should surface valid options to aid the caller
        assert "Research & Development" in result["error"]


# ---------------------------------------------------------------------------
# Name-collision guard
# ---------------------------------------------------------------------------


class TestNameCollision:
    def test_existing_name_blocks_hire(self):
        with patch.object(agent_service, "get_db_cursor", return_value=_mock_cursor(name_exists=True)):
            result = agent_service.propose_hire(**BASE_ARGS)
        assert result["success"] is False
        assert "already exists" in result["error"]
        # Should hint at the reactivation path for decommissioned matches
        assert "propose_reactivation" in result["error"]


# ---------------------------------------------------------------------------
# Approval-queue submission — the contract consumed by
# BridgeDispatcher._create_agent_from_approval at department_dispatcher.py:3930.
# ---------------------------------------------------------------------------


class TestApprovalSubmission:
    def test_happy_path_passes_action_data_shape(self):
        """approval_data must match the keys _create_agent_from_approval reads."""
        with patch.object(agent_service, "get_db_cursor", return_value=_mock_cursor(name_exists=False)), patch(
            "ai_bridge.agent_loop.request_approval", return_value=12345
        ) as request_approval:
            result = agent_service.propose_hire(**BASE_ARGS, requested_by="test_runner")

        assert result["success"] is True
        assert result["approval_id"] == 12345

        # Inspect the action_data handed to request_approval
        kwargs = request_approval.call_args.kwargs
        assert kwargs["action_type"] == "create_agent"
        assert kwargs["tier"] == 2
        assert kwargs["requested_by"] == "test_runner"
        data = kwargs["action_data"]
        assert data["suggested_name"] == BASE_ARGS["name"]
        assert data["suggested_model"] == BASE_ARGS["model"]
        assert data["department"] == BASE_ARGS["department"]
        assert data["capability"] == BASE_ARGS["capability"]
        # Default: suggested_skills falls back to [capability]
        assert data["suggested_skills"] == [BASE_ARGS["capability"]]
        assert BASE_ARGS["reason"] in data["reason"] or data["reason"] == BASE_ARGS["reason"]

    def test_custom_skills_passed_through(self):
        with patch.object(agent_service, "get_db_cursor", return_value=_mock_cursor(name_exists=False)), patch(
            "ai_bridge.agent_loop.request_approval", return_value=12346
        ) as request_approval:
            agent_service.propose_hire(
                **BASE_ARGS,
                suggested_skills=["translate", "summarize", "glossary_priming"],
            )
        data = request_approval.call_args.kwargs["action_data"]
        assert data["suggested_skills"] == ["translate", "summarize", "glossary_priming"]

    def test_dedup_collision_surfaces_helpful_error(self):
        with patch.object(agent_service, "get_db_cursor", return_value=_mock_cursor(name_exists=False)), patch(
            "ai_bridge.agent_loop.request_approval", return_value=None
        ):
            result = agent_service.propose_hire(**BASE_ARGS)
        assert result["success"] is False
        assert "dedup" in result["error"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
