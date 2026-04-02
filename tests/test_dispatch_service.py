"""
Tests for dispatch_service.py

Run:
    cd /mnt/archie_brain && PYTHONPATH=platform_v2 python -m pytest tests/test_dispatch_service.py -v
"""

import json
import sys
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub out heavy platform imports before loading the module under test
# ---------------------------------------------------------------------------

# Stub services.department_coordinator so the singleton import doesn't fail
mock_coordinator_module = MagicMock()
mock_coordinator_module.get_coordinator = MagicMock()
sys.modules.setdefault("services.department_coordinator", mock_coordinator_module)

# Stub services.agent_service (imported transitively)
sys.modules.setdefault("services.agent_service", MagicMock())
sys.modules.setdefault("services.model_service", MagicMock())

from services.dispatch_service import DispatchResult, DispatchService  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_assignment(**kwargs):
    """Return a lightweight Assignment-like object."""
    obj = MagicMock()
    obj.agent_id = kwargs.get("agent_id", 1)
    obj.agent_name = kwargs.get("agent_name", "TEST")
    obj.model = kwargs.get("model", "mistral:7b")
    obj.host = kwargs.get("host", "http://host.docker.internal:11434")
    obj.department = kwargs.get("department", "RESEARCH")
    return obj


def _fake_urlopen_response(data: dict):
    """Return a context-manager mock that yields the JSON-encoded data."""
    raw = json.dumps(data).encode("utf-8")
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=raw)))
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDispatchService(unittest.TestCase):

    def _make_service(self):
        coordinator = MagicMock()
        return DispatchService(coordinator=coordinator), coordinator

    # ------------------------------------------------------------------
    # Test 1: successful call → correct result + agent released
    # ------------------------------------------------------------------

    @patch("urllib.request.urlopen")
    def test_dispatch_calls_ollama_and_releases_agent(self, mock_urlopen):
        mock_urlopen.return_value = _fake_urlopen_response(
            {"response": "test output", "eval_count": 10, "prompt_eval_count": 20}
        )

        svc, coordinator = self._make_service()
        assignment = _make_assignment(
            agent_id=140,
            agent_name="DARWIN",
            model="mistral:7b",
            host="http://host.docker.internal:11434",
        )

        result = svc.dispatch(assignment, prompt="Hello", job_id=99)

        # Correct result fields
        self.assertTrue(result.success)
        self.assertEqual(result.response, "test output")
        self.assertEqual(result.completion_tokens, 10)
        self.assertEqual(result.prompt_tokens, 20)
        self.assertEqual(result.model_used, "mistral:7b")
        self.assertEqual(result.error, "")

        # Agent released
        coordinator.release_agent.assert_called_once_with(140, 99)

        # Ollama was called with correct URL
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        self.assertIn("/api/generate", req.full_url)

    # ------------------------------------------------------------------
    # Test 2: timeout → success=False, error contains "timed out", agent released
    # ------------------------------------------------------------------

    @patch("urllib.request.urlopen")
    def test_dispatch_handles_timeout(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Read timed out")

        svc, coordinator = self._make_service()
        assignment = _make_assignment(agent_id=140, agent_name="DARWIN")

        result = svc.dispatch(assignment, prompt="Hello")

        self.assertFalse(result.success)
        self.assertIn("timed out", result.error)

        # Agent must ALWAYS be released even on error
        coordinator.release_agent.assert_called_once_with(140, None)


if __name__ == "__main__":
    unittest.main()
