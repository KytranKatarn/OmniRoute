"""Tests for Nagios CGI API client."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Load nagios_service directly without triggering the security_network __init__
# (which imports Flask routes and requires a DB connection)
_SERVICE_PATH = (
    Path(__file__).parent.parent.parent
    / "platform_v2"
    / "tools"
    / "security_network"
    / "nagios_service.py"
)
_spec = importlib.util.spec_from_file_location("nagios_service", _SERVICE_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["nagios_service"] = _module
_spec.loader.exec_module(_module)
NagiosService = _module.NagiosService


class TestNagiosService:
    @patch("requests.Session.get")
    def test_get_host_status(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": {
                    "hostlist": {
                        "archie": {
                            "status": 2,
                            "plugin_output": "PING OK",
                            "last_check": 1711900000,
                        }
                    }
                }
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()
        svc = NagiosService(host="192.168.1.200", port=8082, user="admin", password="test")
        hosts = svc.get_host_status()
        assert "archie" in hosts
        assert hosts["archie"]["plugin_output"] == "PING OK"

    @patch("requests.Session.get")
    def test_get_service_status(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": {
                    "servicelist": {
                        "archie": {
                            "SSH": {"status": 2, "plugin_output": "SSH OK"},
                            "HTTP": {"status": 2, "plugin_output": "HTTP OK"},
                        }
                    }
                }
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()
        svc = NagiosService(host="192.168.1.200", port=8082, user="admin", password="test")
        services = svc.get_service_status()
        assert "archie" in services
        assert "SSH" in services["archie"]

    @patch("requests.Session.get")
    def test_is_healthy_returns_true(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        svc = NagiosService(host="192.168.1.200", port=8082, user="admin", password="test")
        assert svc.is_healthy() is True

    @patch("requests.Session.get")
    def test_connection_error_returns_empty(self, mock_get):
        mock_get.side_effect = Exception("Connection refused")
        svc = NagiosService(host="192.168.1.200", port=8082, user="admin", password="test")
        hosts = svc.get_host_status()
        assert hosts == {}

    def test_status_text_host(self):
        assert NagiosService._status_text(2, is_host=True) == "UP"
        assert NagiosService._status_text(4, is_host=True) == "DOWN"

    def test_status_text_service(self):
        assert NagiosService._status_text(2, is_host=False) == "OK"
        assert NagiosService._status_text(16, is_host=False) == "CRITICAL"
