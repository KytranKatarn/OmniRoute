"""Tests for S.H.I.E.L.D. compliance gate."""
import pytest
from unittest.mock import patch, MagicMock


class TestValidateFix:
    def test_passes_clean_fix(self):
        from tools.dev_pipeline.services.shield_gate import validate_fix
        fix_report = {
            "repair_item_id": 1,
            "pr_number": 42,
            "package_name": "requests",
            "old_version": "2.31.0",
            "new_version": "2.33.0",
            "test_passed": True,
            "files_changed": ["requirements.txt"],
            "diff_lines": 2,
        }
        result = validate_fix(fix_report)
        assert result["approved"] is True

    def test_rejects_failing_tests(self):
        from tools.dev_pipeline.services.shield_gate import validate_fix
        fix_report = {
            "repair_item_id": 1,
            "pr_number": 42,
            "package_name": "requests",
            "old_version": "2.31.0",
            "new_version": "2.33.0",
            "test_passed": False,
            "files_changed": ["requirements.txt"],
            "diff_lines": 2,
        }
        result = validate_fix(fix_report)
        assert result["approved"] is False
        assert "test" in result["reason"].lower()

    def test_rejects_suspicious_diff(self):
        from tools.dev_pipeline.services.shield_gate import validate_fix
        fix_report = {
            "repair_item_id": 1,
            "pr_number": 42,
            "package_name": "requests",
            "old_version": "2.31.0",
            "new_version": "2.33.0",
            "test_passed": True,
            "files_changed": ["requirements.txt", ".env", "secrets.json"],
            "diff_lines": 50,
        }
        result = validate_fix(fix_report)
        assert result["approved"] is False
