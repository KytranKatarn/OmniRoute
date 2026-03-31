"""Tests for ntopng REST API client."""
import sys
import importlib
import pytest
from unittest.mock import patch, MagicMock


def _load_ntopng_service():
    """Load NtopngService directly from file, bypassing the package __init__ (Flask/DB unavailable outside Docker)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "ntopng_service",
        "/mnt/archie_brain/platform_v2/tools/security_network/ntopng_service.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.NtopngService


class TestNtopngService:
    @patch("requests.Session.get")
    def test_get_interfaces(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"rc": 0, "rsp": [{"ifid": 0, "ifname": "eth0"}]},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        NtopngService = _load_ntopng_service()
        svc = NtopngService(host="127.0.0.1", port=3001, user="admin", password="test")
        interfaces = svc.get_interfaces()
        assert len(interfaces) == 1
        assert interfaces[0]["ifname"] == "eth0"

    @patch("requests.Session.get")
    def test_get_hosts_returns_host_list(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "rc": 0,
                "rsp": [
                    {
                        "ip": "192.168.1.100",
                        "mac": "AA:BB:CC:DD:EE:FF",
                        "bytes.sent": 1000,
                        "bytes.rcvd": 2000,
                        "name": "laptop",
                    }
                ],
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()
        NtopngService = _load_ntopng_service()
        svc = NtopngService(host="127.0.0.1", port=3001, user="admin", password="test")
        hosts = svc.get_hosts()
        assert len(hosts) == 1
        assert hosts[0]["ip"] == "192.168.1.100"

    @patch("requests.Session.get")
    def test_get_interface_stats(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"rc": 0, "rsp": {"bytes": 50000, "packets": 300}},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        NtopngService = _load_ntopng_service()
        svc = NtopngService(host="127.0.0.1", port=3001, user="admin", password="test")
        stats = svc.get_interface_stats(ifid=0)
        assert stats["bytes"] == 50000

    @patch("requests.Session.get")
    def test_connection_error_returns_empty(self, mock_get):
        mock_get.side_effect = Exception("Connection refused")
        NtopngService = _load_ntopng_service()
        svc = NtopngService(host="127.0.0.1", port=3001, user="admin", password="test")
        hosts = svc.get_hosts()
        assert hosts == []
