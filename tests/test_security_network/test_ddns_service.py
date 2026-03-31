# tests/test_security_network/test_ddns_service.py
"""Tests for DDNS service."""
import sys
from unittest.mock import patch, MagicMock, Mock

# Stub out heavy platform dependencies before any platform_v2 imports
for _mod in [
    "database",
    "flask",
    "flask_login",
    "services.action_registry",
    "services.auth_service",
]:
    if _mod not in sys.modules:
        sys.modules[_mod] = Mock()

import pytest


class TestDdnsService:
    @patch("builtins.open", create=True)
    def test_get_current_ip_reads_file(self, mock_open):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read = MagicMock(return_value="142.169.21.199\n")
        from platform_v2.tools.security_network.ddns_service import DdnsService

        svc = DdnsService()
        ip = svc.get_current_public_ip()
        assert ip == "142.169.21.199"

    @patch("subprocess.run")
    def test_trigger_update_runs_script(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="IP updated\n")
        from platform_v2.tools.security_network.ddns_service import DdnsService

        svc = DdnsService()
        with patch("os.path.exists", return_value=True):
            result = svc.trigger_update()
        assert result["success"] is True

    def test_get_ip_history_returns_list(self):
        from platform_v2.tools.security_network.ddns_service import DdnsService

        svc = DdnsService()
        with patch.object(svc, "_query_db") as mock_db:
            mock_db.return_value = [
                {"old_ip": "1.1.1.1", "new_ip": "2.2.2.2", "changed_at": "2026-03-30"}
            ]
            history = svc.get_ip_history(limit=10)
            assert len(history) == 1
            assert history[0]["new_ip"] == "2.2.2.2"
