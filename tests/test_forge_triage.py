"""Tests for F.O.R.G.E. triage logic."""
import pytest
from unittest.mock import patch, MagicMock


class TestDetermineFixStrategy:
    def test_simple_bump(self):
        from tools.dev_pipeline.services.forge_triage import determine_fix_strategy
        alert = {
            "package_name": "requests",
            "fix_version": "2.33.0",
            "vulnerable_range": "< 2.33.0",
            "severity": "medium",
            "manifest_path": "requirements.txt",
        }
        strategy = determine_fix_strategy(alert)
        assert strategy["action"] == "version_bump"
        assert strategy["target_version"] == "2.33.0"

    def test_no_fix_available(self):
        from tools.dev_pipeline.services.forge_triage import determine_fix_strategy
        alert = {
            "package_name": "legacy-lib",
            "fix_version": None,
            "vulnerable_range": ">= 0",
            "severity": "high",
            "manifest_path": "requirements.txt",
        }
        strategy = determine_fix_strategy(alert)
        assert strategy["action"] == "no_fix"

    def test_major_version_escalates(self):
        from tools.dev_pipeline.services.forge_triage import determine_fix_strategy
        alert = {
            "package_name": "flask",
            "fix_version": "4.0.0",
            "vulnerable_range": "< 4.0.0",
            "severity": "high",
            "manifest_path": "requirements.txt",
        }
        with patch(
            "tools.dev_pipeline.services.forge_triage._get_current_version",
            return_value="3.1.0",
        ):
            strategy = determine_fix_strategy(alert)
            assert strategy["action"] == "major_upgrade"


class TestTriageAlert:
    def test_creates_repair_entry_and_dispatches(self):
        from tools.dev_pipeline.services.forge_triage import triage_alert
        alert = {
            "id": 1,
            "package_name": "requests",
            "fix_version": "2.33.0",
            "vulnerable_range": "< 2.33.0",
            "severity": "medium",
            "manifest_path": "requirements.txt",
        }
        with patch(
            "tools.dev_pipeline.services.forge_triage.update_repair_item"
        ) as mock_update, patch(
            "tools.dev_pipeline.services.forge_triage._dispatch_fix"
        ) as mock_dispatch:
            mock_dispatch.return_value = {"success": True}
            result = triage_alert(alert)
            assert result["success"] is True
            assert mock_update.called
            assert mock_dispatch.called
