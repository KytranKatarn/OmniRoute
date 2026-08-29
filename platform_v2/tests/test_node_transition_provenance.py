"""Node deploy/return shift flips go through the logged single-writer (#5829).

The task's four stranded agents sat on a bench with NO rotation row and NO
shift_state_history — because ``deploy_to_node`` and ``return_from_node``
flipped ``agents.shift_state`` with raw UPDATEs. These tests pin the
conversion: both paths must route through ``transition_shift_state`` with
the caller's open cursor (``_cur``) so the flip stays atomic with the
node_agents write. Pure mocks — no DB.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import services.agent_service as agent_service  # noqa: E402


def _cursor_ctx(cur):
    """A get_db_cursor(commit=True) stand-in yielding (conn, cur)."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=(MagicMock(), cur))
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


# ── transition_shift_state honours a shared cursor ───────────────────────────


def test_transition_with_cur_never_opens_its_own_transaction():
    cur = MagicMock()
    cur.fetchone.return_value = {
        "id": 1,
        "name": "T.E.S.T.",
        "department": "Engineering & Technology",
        "shift_state": "active",
    }
    with patch.object(agent_service, "get_db_cursor", side_effect=AssertionError("opened a second transaction")):
        out = agent_service.transition_shift_state(1, "barracked", reason="r", changed_by="t", _cur=cur)
    assert out["success"] is True
    executed = " ".join(str(c.args[0]) for c in cur.execute.call_args_list)
    assert "UPDATE agents SET shift_state" in executed
    assert "shift_state_history" in executed


def test_transition_without_cur_still_works():
    cur = MagicMock()
    cur.fetchone.return_value = {
        "id": 1,
        "name": "T.E.S.T.",
        "department": "Engineering & Technology",
        "shift_state": "active",
    }
    with patch.object(agent_service, "get_db_cursor", return_value=_cursor_ctx(cur)):
        out = agent_service.transition_shift_state(1, "off_duty", reason="r", changed_by="t")
    assert out["success"] is True


# ── deploy_to_node ───────────────────────────────────────────────────────────


def test_deploy_to_node_routes_through_the_logged_writer():
    cur = MagicMock()
    cur.fetchone.return_value = {
        "name": "T.E.S.T.",
        "display_name": "Test",
        "department": "Engineering & Technology",
        "model": "qwen2.5:1.5b",
    }
    with patch.object(agent_service, "get_db_cursor", return_value=_cursor_ctx(cur)), patch.object(
        agent_service, "transition_shift_state", return_value={"success": True}
    ) as tr:
        assert agent_service.deploy_to_node(7, 3) is True
    tr.assert_called_once()
    args, kwargs = tr.call_args
    assert args[0] == 7 and args[1] == "deployed"
    assert kwargs.get("_cur") is cur  # atomic with the node_agents upsert
    # The raw fallback must NOT have fired on a successful transition.
    executed = " ".join(str(c.args[0]) for c in cur.execute.call_args_list)
    assert "UPDATE agents SET shift_state" not in executed


# ── return_from_node ─────────────────────────────────────────────────────────


def test_return_from_node_benches_a_deployed_agent_via_the_logged_writer():
    cur = MagicMock()
    cur.fetchone.return_value = {"shift_state": "deployed"}
    with patch.object(agent_service, "get_db_cursor", return_value=_cursor_ctx(cur)), patch.object(
        agent_service, "transition_shift_state", return_value={"success": True}
    ) as tr:
        assert agent_service.return_from_node(7) is True
    args, kwargs = tr.call_args
    assert args[0] == 7 and args[1] == "barracked"
    assert kwargs.get("_cur") is cur


def test_return_from_node_preserves_the_deployed_only_guard():
    """The old raw UPDATE carried WHERE shift_state='deployed' — an active or
    benched agent must never be yanked into barracks by a node return."""
    cur = MagicMock()
    cur.fetchone.return_value = {"shift_state": "active"}
    with patch.object(agent_service, "get_db_cursor", return_value=_cursor_ctx(cur)), patch.object(
        agent_service, "transition_shift_state"
    ) as tr:
        assert agent_service.return_from_node(7) is True
    tr.assert_not_called()
    # node_agents deactivation still happens regardless of shift state.
    executed = " ".join(str(c.args[0]) for c in cur.execute.call_args_list)
    assert "UPDATE node_agents SET status = 'inactive'" in executed
