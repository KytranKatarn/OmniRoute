"""
Tests for platform_v2/services/model_service.py
TDD: write tests first, then implement.
"""
import json
import time
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

from model_service import ModelPriority, ModelService, get_model_service


class TestCheckLoadedModels(unittest.TestCase):
    def test_check_loaded_models_returns_model_list(self):
        """Mock urlopen to return a model list; assert name + size_gb parsed."""
        svc = ModelService()
        payload = json.dumps(
            {"models": [{"name": "mistral:7b", "size": 6_442_450_944}]}
        ).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = payload
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("model_service.urllib.request.urlopen", return_value=mock_resp):
            result = svc.check_loaded_models()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "mistral:7b")
        self.assertAlmostEqual(result[0]["size_gb"], 6.0, places=0)

    def test_check_loaded_models_connection_error(self):
        """When urlopen raises, return empty list."""
        svc = ModelService()
        with patch("model_service.urllib.request.urlopen", side_effect=Exception("conn refused")):
            result = svc.check_loaded_models()
        self.assertEqual(result, [])


class TestGetAvailableRam(unittest.TestCase):
    def test_get_available_ram(self):
        """budget=100 GB, loaded 6+8=14 GB → available=86 GB."""
        svc = ModelService(ram_budget_gb=100.0)
        svc._loaded_cache = [
            {"name": "model-a:latest", "size_gb": 6.0},
            {"name": "model-b:latest", "size_gb": 8.0},
        ]
        svc._cache_time = time.time()  # fresh cache, won't re-fetch
        available = svc.get_available_ram()
        self.assertAlmostEqual(available, 86.0, places=5)


class TestGetModelPriority(unittest.TestCase):
    def test_get_model_priority_active_job_is_protected(self):
        """Model with an active job → PROTECTED priority."""
        svc = ModelService()
        svc._active_jobs = {"mistral:7b": [123]}
        priority = svc.get_model_priority("mistral:7b")
        self.assertEqual(priority, ModelPriority.PROTECTED)

    def test_get_model_priority_idle_is_low(self):
        """No active jobs, no recent usage → LOW priority."""
        svc = ModelService()
        svc._active_jobs = {}
        svc._last_used = {}
        priority = svc.get_model_priority("some-idle-model:latest")
        self.assertEqual(priority, ModelPriority.LOW)


class TestSingleton(unittest.TestCase):
    def test_get_model_service_returns_same_instance(self):
        """get_model_service() is a singleton."""
        a = get_model_service()
        b = get_model_service()
        self.assertIs(a, b)


if __name__ == "__main__":
    unittest.main()
