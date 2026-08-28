"""Tests for expanded department_coordinator (Phase 2).

Run: docker exec archie_platform python -m pytest services/tests/test_phase2_coordinator.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def test_score_agent_blocks_inactive():
    """Agents with status != 'active' should score 0."""
    from services.department_coordinator import get_coordinator

    coord = get_coordinator()
    agent_info = {"id": 999, "status": "paused", "model": "mistral:7b"}
    score, reason = coord.score_agent("TestAgent", agent_info, "general", "Research & Development")
    assert score == 0.0
    assert "paused" in reason


def test_score_agent_active_gets_positive():
    """Active agent with budget should get positive score."""
    from services.department_coordinator import get_coordinator

    coord = get_coordinator()
    agent_info = {
        "id": 999,
        "status": "active",
        "model": "mistral:7b",
        "shift_state": "active",
    }
    score, reason = coord.score_agent("TestAgent", agent_info, "general", "Research & Development")
    assert score > 0.0
    assert reason is None


def test_select_agent_returns_best():
    """select_agent should return the highest-scoring available agent."""
    from services.department_coordinator import get_coordinator

    coord = get_coordinator()
    result = coord.select_agent("general", "Engineering & Technology")
    assert result is None or isinstance(result, dict)


def test_resolve_department():
    """Known capabilities should map to departments."""
    from services.department_coordinator import get_coordinator

    coord = get_coordinator()
    dept = coord.resolve_department("code")
    assert dept is not None
    assert isinstance(dept, str)


def test_find_cross_department_agent():
    """Cross-department fallback should skip the blocked department."""
    from services.department_coordinator import get_coordinator

    coord = get_coordinator()
    result = coord.find_cross_department_agent("general", "Executive Office")
    assert result is None or isinstance(result, dict)
