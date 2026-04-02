"""Tests for DepartmentCoordinator — admission control and agent reservation."""
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candidate(agent_id, model="mistral:7b"):
    return {
        "id": agent_id,
        "name": f"AGENT{agent_id}",
        "display_name": f"A.G.E.N.T.{agent_id}.",
        "department": "R&D",
        "model": model,
        "shift_state": "active",
        "proficiency_level": 5,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@patch("services.department_coordinator.match_capability")
def test_request_agent_returns_assignment(mock_match):
    """Happy path: candidate found, model ready → non-queued Assignment."""
    from services.department_coordinator import DepartmentCoordinator

    mock_match.return_value = [_make_candidate(140)]

    ms = MagicMock()
    ms.ensure_ready.return_value = True
    ms.get_available_ram.return_value = 64.0
    ms.check_loaded_models.return_value = []

    coord = DepartmentCoordinator(model_service=ms)
    result = coord.request_agent("research")

    assert result.agent_id == 140
    assert result.queued is False
    ms.ensure_ready.assert_called_once()


@patch("services.department_coordinator.match_capability")
def test_request_agent_queues_when_no_capacity(mock_match):
    """When ensure_ready returns False for all candidates, result is queued."""
    from services.department_coordinator import DepartmentCoordinator

    mock_match.return_value = [_make_candidate(140)]

    ms = MagicMock()
    ms.ensure_ready.return_value = False
    ms.get_available_ram.return_value = 2.0
    ms.check_loaded_models.return_value = []

    coord = DepartmentCoordinator(model_service=ms)
    result = coord.request_agent("research")

    assert result.queued is True


@patch("services.department_coordinator.match_capability")
def test_request_agent_skips_busy_agents(mock_match):
    """Already-reserved agents are skipped; coordinator picks next candidate."""
    from services.department_coordinator import DepartmentCoordinator

    mock_match.return_value = [_make_candidate(140), _make_candidate(146)]

    ms = MagicMock()
    ms.ensure_ready.return_value = True
    ms.get_available_ram.return_value = 64.0
    ms.check_loaded_models.return_value = []

    coord = DepartmentCoordinator(model_service=ms)
    coord._reserved_agents.add(140)  # pre-mark 140 as busy

    result = coord.request_agent("research")

    assert result.agent_id == 146
    assert result.queued is False


@patch("services.department_coordinator.match_capability")
def test_release_agent_frees_reservation(mock_match):
    """release_agent removes the agent from the reserved set."""
    from services.department_coordinator import DepartmentCoordinator

    ms = MagicMock()
    ms.get_available_ram.return_value = 64.0
    ms.check_loaded_models.return_value = []

    coord = DepartmentCoordinator(model_service=ms)
    coord._reserved_agents.add(140)

    coord.release_agent(140)

    assert 140 not in coord._reserved_agents


@patch("services.department_coordinator.match_capability")
def test_request_agent_no_matching_agents(mock_match):
    """Empty candidate list → queued Assignment with descriptive reason."""
    from services.department_coordinator import DepartmentCoordinator

    mock_match.return_value = []

    ms = MagicMock()
    ms.get_available_ram.return_value = 64.0
    ms.check_loaded_models.return_value = []

    coord = DepartmentCoordinator(model_service=ms)
    result = coord.request_agent("quantum_physics")

    assert result.queued is True
    assert "no agent" in result.reason.lower()
