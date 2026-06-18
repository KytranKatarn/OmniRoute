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
        assert result.metadata.get("status") == "deploy_pending"
        mock_execute.assert_called_once()
        # deploy_static is async — the Hostinger push is Claude's MCP job, so the
        # pipeline must NOT verify/retry a push that did not happen here (#3577).
        mock_verify.assert_not_called()

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

    def test_deploy_static_short_circuits_no_verify_no_retry(self):
        """deploy_static returns immediately after marking pending — no verify, no
        sleep, no retry — even if a live verify would fail. Prevents the 360s
        delegate-worker wedge (#3577)."""
        from services.deploy_service import run_deploy_pipeline

        mock_execute = MagicMock(return_value=True)
        mock_verify = MagicMock(return_value=False)  # would fail the pipeline if called
        mock_sleep = MagicMock()

        with (
            patch("services.deploy_service._deploy_static_hostinger", mock_execute),
            patch("services.deploy_service.verify_deploy", mock_verify),
            patch("services.deploy_service.snapshot_current", return_value=None),
            patch("services.deploy_service.time.sleep", mock_sleep),
        ):
            result = run_deploy_pipeline(
                capability="deploy_static",
                context={
                    "domain": "creed-ai.org",
                    "source_path": "/tmp/fake",
                    "changed_files": ["index.html"],
                    "verify_url": "https://creed-ai.org/index.html",
                },
            )

        assert result.success is True
        assert result.retried is False
        assert result.rolled_back is False
        assert result.metadata.get("status") == "deploy_pending"
        mock_execute.assert_called_once()
        mock_verify.assert_not_called()
        mock_sleep.assert_not_called()  # no VERIFY_WAIT / RETRY_DELAY sleeps → no wedge

    def test_retry_on_first_failure(self):
        """On first execute failure, pipeline retries once and succeeds."""
        from services.deploy_service import run_deploy_pipeline

        call_count = {"n": 0}

        def flaky_execute(*a, **kw):
            call_count["n"] += 1
            return call_count["n"] > 1  # fail first, succeed second

        # Retry applies to deploy_vps (the container CAN actually deploy + verify).
        # deploy_static short-circuits before verify/retry (#3577), so the retry
        # path is exercised here via a VPS deploy.
        with (
            patch("services.deploy_service._deploy_vps", side_effect=flaky_execute),
            patch("services.deploy_service.verify_deploy", return_value=True),
            patch("services.deploy_service.snapshot_current", return_value=None),
            patch("services.deploy_service.time.sleep"),
        ):
            result = run_deploy_pipeline(
                capability="deploy_vps",
                context={
                    "domain": "test.com",
                    "source_path": "/tmp/fake",
                    "changed_files": ["data/translations.json"],
                    "verify_url": "https://test.com/data/translations.json",
                    "container_name": "kytran_gov_watch",
                },
            )

        assert result.success is True
        assert result.retried is True
        assert call_count["n"] == 2


class TestVpsHostMap:
    """#4307 — watch products + WTF migrated to Citadel/boston-2
    (root@100.64.0.10, /opt/archie-products/<product>/). outpost-us no longer
    hosts products. These guard against a regression to the old host/dir/service.
    """

    def test_all_entries_target_citadel(self):
        from services.deploy_service import VPS_SERVICE_MAP

        assert VPS_SERVICE_MAP, "map must not be empty"
        for key, info in VPS_SERVICE_MAP.items():
            assert info.get("host") == "root@100.64.0.10", f"{key} wrong host: {info.get('host')}"
            assert info["dir"].startswith("/opt/archie-products/"), f"{key} stale dir: {info['dir']}"
            assert info["service"], f"{key} missing compose service name"

    def test_market_entry_fixed(self):
        """market-watch had a stale dir (/opt/kytran-market-watch/) + service=None."""
        from services.deploy_service import VPS_SERVICE_MAP

        m = VPS_SERVICE_MAP["kytran_market_api"]
        assert m["dir"] == "/opt/archie-products/market-watch/"
        assert m["service"] == "kytran_market_api"

    def test_deploy_vps_uses_per_product_host_and_mounted_key(self):
        """_deploy_vps must SSH/scp to the entry's Citadel host with the
        bind-mounted id_ed25519 key — never the retired outpost-us host or the
        unmounted repair_bay_deploy key — and must rebuild the correct service."""
        from services import deploy_service

        calls: list[list[str]] = []

        def fake_run(cmd, *a, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)

        # Patch VPS_KEY to the bind-mounted key so the test asserts _deploy_vps
        # LOGIC (uses the resolved key for -i) rather than the ambient container
        # env, which is only reloaded on a container recreate.
        with (
            patch.object(deploy_service, "VPS_KEY", "/root/.ssh/id_ed25519"),
            patch.object(deploy_service.subprocess, "run", side_effect=fake_run),
        ):
            ok = deploy_service._deploy_vps(
                "kytran_gov_watch",
                ["static/data/translations.json"],
                "/tmp/src",
            )

        assert ok is True
        joined = "\n".join(" ".join(c) for c in calls)
        assert "root@100.64.0.10" in joined  # host comes from the map (env-independent)
        assert "kytran@76.13.107.109" not in joined
        assert "-i /root/.ssh/id_ed25519" in joined
        assert "repair_bay_deploy" not in joined
        assert "UserKnownHostsFile=/dev/null" in joined
        # gov compose SERVICE name uses hyphens (differs from the underscore container)
        assert "kytran-gov-watch" in joined
