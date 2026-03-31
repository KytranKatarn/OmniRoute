# tests/test_security_network/test_fail2ban_service.py
"""Tests for fail2ban service — CLI wrapper for jail management."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Load fail2ban_service directly without triggering the security_network __init__
# (which imports Flask routes and requires a DB connection)
_SERVICE_PATH = (
    Path(__file__).parent.parent.parent
    / "platform_v2"
    / "tools"
    / "security_network"
    / "fail2ban_service.py"
)
_spec = importlib.util.spec_from_file_location(
    "fail2ban_service", _SERVICE_PATH
)
_module = importlib.util.module_from_spec(_spec)
sys.modules["fail2ban_service"] = _module
_spec.loader.exec_module(_module)
Fail2banService = _module.Fail2banService


class TestFail2banService:
    @patch("subprocess.run")
    def test_get_jails_parses_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Status\n|- Number of jail:\t3\n`- Jail list:\tsshd, nginx-http-auth, recidive\n",
        )
        svc = Fail2banService()
        jails = svc.get_jails()
        assert jails == ["sshd", "nginx-http-auth", "recidive"]

    @patch("subprocess.run")
    def test_get_jail_status_parses_banned(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "Status for the jail: sshd\n"
                "|- Filter\n"
                "|  |- Currently failed:\t5\n"
                "|  |- Total failed:\t120\n"
                "|  `- File list:\t/var/log/auth.log\n"
                "`- Actions\n"
                "   |- Currently banned:\t2\n"
                "   |- Total banned:\t15\n"
                "   `- Banned IP list:\t192.168.1.50 10.0.0.5\n"
            ),
        )
        svc = Fail2banService()
        status = svc.get_jail_status("sshd")
        assert status["currently_banned"] == 2
        assert status["total_banned"] == 15
        assert "192.168.1.50" in status["banned_ips"]
        assert status["currently_failed"] == 5

    @patch("subprocess.run")
    def test_ban_ip_calls_correct_command(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="1\n")
        svc = Fail2banService()
        result = svc.ban_ip("sshd", "10.0.0.99")
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "fail2ban-client" in cmd
        assert "banip" in cmd
        assert "10.0.0.99" in cmd

    @patch("subprocess.run")
    def test_unban_ip_calls_correct_command(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="1\n")
        svc = Fail2banService()
        result = svc.unban_ip("sshd", "10.0.0.99")
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "unbanip" in cmd

    def test_validate_ip_rejects_invalid(self):
        svc = Fail2banService()
        assert svc._validate_ip("192.168.1.1") is True
        assert svc._validate_ip("not-an-ip") is False
        assert svc._validate_ip("'; DROP TABLE users; --") is False
