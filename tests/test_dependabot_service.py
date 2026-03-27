"""Tests for Dependabot API functions in github_service."""
import importlib.util
import sys
import os
import pytest
from unittest.mock import patch

# Import github_service directly by file path to avoid triggering the
# dev_pipeline __init__.py which tries to connect to the database at load time.
_SERVICE_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "platform_v2",
    "tools",
    "dev_pipeline",
    "services",
    "github_service.py",
)

spec = importlib.util.spec_from_file_location("github_service", _SERVICE_PATH)
github_service = importlib.util.module_from_spec(spec)
sys.modules["github_service"] = github_service
spec.loader.exec_module(github_service)

get_dependabot_alerts = github_service.get_dependabot_alerts
dismiss_dependabot_alert = github_service.dismiss_dependabot_alert
get_coderabbit_reviews = github_service.get_coderabbit_reviews


def _mock_api_get(success_data):
    return patch.object(github_service, "_api_get", return_value=(True, success_data))


class TestGetDependabotAlerts:
    def test_returns_open_alerts(self):
        mock_alerts = [
            {
                "number": 81,
                "security_vulnerability": {
                    "severity": "medium",
                    "package": {"name": "requests", "ecosystem": "pip"},
                    "vulnerable_version_range": "< 2.33.0",
                    "first_patched_version": {"identifier": "2.33.0"},
                },
                "security_advisory": {
                    "summary": "Insecure Temp File Reuse",
                    "ghsa_id": "GHSA-xxxx-yyyy",
                },
                "dependency": {"manifest_path": "requirements.txt"},
                "state": "open",
            }
        ]
        with _mock_api_get(mock_alerts):
            result = get_dependabot_alerts(state="open")
            assert result["success"] is True
            assert len(result["alerts"]) == 1
            assert result["alerts"][0]["number"] == 81

    def test_handles_api_failure(self):
        with patch.object(github_service, "_api_get", return_value=(False, {"error": "rate limited"})):
            result = get_dependabot_alerts()
            assert result["success"] is False


class TestDismissDependabotAlert:
    def test_dismisses_alert(self):
        with patch.object(github_service, "_api_patch", return_value=(True, {"state": "dismissed"})):
            result = dismiss_dependabot_alert(81, "fix_started")
            assert result["success"] is True


class TestGetCoderabbitReviews:
    def test_returns_review_comments(self):
        mock_comments = [
            {"user": {"login": "coderabbitai[bot]"}, "body": "Fix: use parameterized query"},
            {"user": {"login": "someone"}, "body": "LGTM"},
        ]
        with _mock_api_get(mock_comments):
            result = get_coderabbit_reviews(42)
            assert result["success"] is True
            assert len(result["reviews"]) == 1
            assert "parameterized" in result["reviews"][0]["body"]
