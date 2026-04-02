"""Integration test: consciousness loops dispatch through coordinator."""
import sys

sys.path.insert(0, "platform_v2")
from unittest.mock import MagicMock, patch


def _make_mock_model():
    """Return a plain MagicMock standing in for ModelService."""
    ms = MagicMock()
    ms.ensure_ready.return_value = True
    ms.register_job.return_value = None
    ms.get_available_ram.return_value = 64.0
    ms.check_loaded_models.return_value = []
    return ms


def test_embedding_loop_uses_coordinator():
    """Verify coordinator can assign an agent for embedding capability."""
    with patch("services.department_coordinator.match_capability") as mock_match:
        mock_match.return_value = [
            {
                "id": 137,
                "name": "SPECTRA",
                "display_name": "SPECTRA",
                "model": "qwen2.5:7b",
                "shift_state": "active",
                "proficiency_level": 4,
                "department": "Analytics & Intelligence",
            },
        ]

        from services.department_coordinator import DepartmentCoordinator

        coord = DepartmentCoordinator(model_service=_make_mock_model())
        result = coord.request_agent("embedding", "consciousness")

        assert result.agent_id == 137
        assert result.queued is False


def test_coordinator_prevents_double_booking():
    """Same agent can't be assigned to two jobs simultaneously."""
    with patch("services.department_coordinator.match_capability") as mock_match:
        mock_match.return_value = [
            {
                "id": 140,
                "name": "DARWIN",
                "display_name": "DARWIN",
                "model": "mistral:7b",
                "shift_state": "active",
                "proficiency_level": 5,
                "department": "Research & Development",
            },
        ]

        from services.department_coordinator import DepartmentCoordinator

        coord = DepartmentCoordinator(model_service=_make_mock_model())

        # First assignment — DARWIN free
        r1 = coord.request_agent("knowledge_analysis", "consciousness")
        assert r1.agent_id == 140
        assert r1.queued is False

        # Second — DARWIN is now reserved, no other candidates
        r2 = coord.request_agent("knowledge_analysis", "consciousness")
        assert r2.queued is True

        # Release DARWIN
        coord.release_agent(140)

        # Third — DARWIN free again
        r3 = coord.request_agent("knowledge_analysis", "consciousness")
        assert r3.agent_id == 140
        assert r3.queued is False
