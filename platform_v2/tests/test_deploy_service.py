"""Tests for the Autonomous Deploy Pipeline (Project #292).

Run: docker exec archie_platform python -m pytest tests/test_deploy_service.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestRiskClassification:
    def test_json_only_is_auto(self):
        from services.deploy_service import classify_risk

        assert classify_risk(["data/translations.json"]) == "auto"

    def test_js_only_is_auto(self):
        from services.deploy_service import classify_risk

        assert classify_risk(["static/js/i18n.js"]) == "auto"

    def test_css_html_are_auto(self):
        from services.deploy_service import classify_risk

        assert classify_risk(["style.css", "index.html"]) == "auto"

    def test_python_file_requires_approval(self):
        from services.deploy_service import classify_risk

        assert classify_risk(["app.py"]) == "approval_required"

    def test_dockerfile_requires_approval(self):
        from services.deploy_service import classify_risk

        assert classify_risk(["Dockerfile"]) == "approval_required"

    def test_mixed_files_requires_approval(self):
        from services.deploy_service import classify_risk

        assert classify_risk(["data/translations.json", "Dockerfile"]) == "approval_required"

    def test_empty_list_is_auto(self):
        from services.deploy_service import classify_risk

        assert classify_risk([]) == "auto"

    def test_migration_sql_requires_approval(self):
        from services.deploy_service import classify_risk

        assert classify_risk(["database/migrations/173_foo.sql"]) == "approval_required"

    def test_sh_script_requires_approval(self):
        from services.deploy_service import classify_risk

        assert classify_risk(["scripts/deploy.sh"]) == "approval_required"


class TestCapabilityRouting:
    def test_deploy_static_routes_to_operations(self):
        from services.department_coordinator import (
            DepartmentCoordinator,
        )

        coord = DepartmentCoordinator.__new__(DepartmentCoordinator)
        dept = coord.resolve_department("deploy_static")
        assert dept == "Operations & Infrastructure", f"Got: {dept}"

    def test_deploy_vps_routes_to_operations(self):
        from services.department_coordinator import (
            DepartmentCoordinator,
        )

        coord = DepartmentCoordinator.__new__(DepartmentCoordinator)
        dept = coord.resolve_department("deploy_vps")
        assert dept == "Operations & Infrastructure", f"Got: {dept}"


class TestDeployPipelineSmoke:
    def test_auto_risk_static_files(self):
        """Full pipeline smoke: auto-risk path executes and returns success."""
        from services.deploy_service import run_deploy_pipeline

        mock_execute = MagicMock(return_value=True)
        mock_verify = MagicMock(return_value=True)
        mock_snapshot = MagicMock(return_value=999)

        with (
            patch("services.deploy_service._deploy_static_hostinger", mock_execute),
            patch("services.deploy_service.verify_deploy", mock_verify),
            patch("services.deploy_service.snapshot_current", mock_snapshot),
        ):
            result = run_deploy_pipeline(
                capability="deploy_static",
                context={
                    "domain": "kytranempowerment.com",
                    "source_path": "/tmp/fake",
                    "changed_files": ["data/translations.json"],
                    "verify_url": "https://kytranempowerment.com/data/translations.json",
                    "is_translation": True,
                },
            )

        assert result.success is True
        assert result.backup_id == 999
        assert result.retried is False
        assert result.rolled_back is False
        mock_execute.assert_called_once()
        mock_verify.assert_called_once()

    def test_risky_files_do_not_execute(self):
        """Dockerfile in changed_files must NOT call execute — must request approval."""
        from services.deploy_service import run_deploy_pipeline

        mock_execute = MagicMock()

        # request_approval is wrapped in try/except in deploy_service — no need to mock it
        with patch("services.deploy_service._deploy_static_hostinger", mock_execute):
            result = run_deploy_pipeline(
                capability="deploy_static",
                context={
                    "domain": "kytranempowerment.com",
                    "source_path": "/tmp/fake",
                    "changed_files": ["Dockerfile"],
                    "verify_url": "",
                },
            )

        assert result.success is False
        assert "approval" in (result.error or "").lower()
        mock_execute.assert_not_called()

    def test_retry_on_first_failure(self):
        """On first execute failure, pipeline retries once and succeeds."""
        from services.deploy_service import run_deploy_pipeline

        call_count = {"n": 0}

        def flaky_execute(*a, **kw):
            call_count["n"] += 1
            return call_count["n"] > 1  # fail first, succeed second

        with (
            patch("services.deploy_service._deploy_static_hostinger", side_effect=flaky_execute),
            patch("services.deploy_service.verify_deploy", return_value=True),
            patch("services.deploy_service.snapshot_current", return_value=None),
            patch("services.deploy_service.time.sleep"),
        ):
            result = run_deploy_pipeline(
                capability="deploy_static",
                context={
                    "domain": "test.com",
                    "source_path": "/tmp/fake",
                    "changed_files": ["data/translations.json"],
                    "verify_url": "https://test.com/data/translations.json",
                },
            )

        assert result.success is True
        assert result.retried is True
        assert call_count["n"] == 2
