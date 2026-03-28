"""Tests for subdomain provisioning (mocked Hostinger API)."""

import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("KBS_HOSTINGER_API_KEY", "test-api-key")
    monkeypatch.setenv("KBS_BASE_DOMAIN", "kytranempowerment.com")
    monkeypatch.setenv("KBS_SUBDOMAIN_TARGET", "192.168.1.200")


class TestProvisionSubdomain:
    def test_creates_dns_record(self):
        from core.subdomain_manager import provision_subdomain

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch("core.subdomain_manager.requests.put", return_value=mock_resp) as mock_put:
            result = provision_subdomain("acme-corp")

        assert result["subdomain"] == "acme-corp"
        assert result["fqdn"] == "acme-corp.kytranempowerment.com"
        assert result["status"] == "provisioned"
        mock_put.assert_called_once()

    def test_empty_slug_raises(self):
        from core.subdomain_manager import provision_subdomain

        with pytest.raises(ValueError, match="Slug is required"):
            provision_subdomain("")

    def test_no_api_key_skips(self, monkeypatch):
        monkeypatch.setenv("KBS_HOSTINGER_API_KEY", "")
        from core.subdomain_manager import provision_subdomain

        result = provision_subdomain("test-co")
        assert result["status"] == "skipped"

    def test_api_failure_raises(self):
        from core.subdomain_manager import provision_subdomain
        import requests as req_lib

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req_lib.RequestException("DNS API error")

        with patch("core.subdomain_manager.requests.put", return_value=mock_resp):
            with pytest.raises(req_lib.RequestException):
                provision_subdomain("fail-co")


class TestProvisionCustomDomain:
    def test_records_custom_domain(self):
        from core.subdomain_manager import provision_custom_domain

        with patch("core.subdomain_manager.get_db_cursor") as mock_ctx:
            mock_cur = MagicMock()
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = provision_custom_domain("app.acme.com", tenant_id=1)

        assert result["domain"] == "app.acme.com"
        assert result["status"] == "registered"
        assert "instructions" in result

    def test_empty_domain_raises(self):
        from core.subdomain_manager import provision_custom_domain

        with pytest.raises(ValueError, match="Domain is required"):
            provision_custom_domain("", tenant_id=1)


class TestSubdomainHealth:
    def test_resolves_correctly(self):
        from core.subdomain_manager import check_subdomain_health

        with patch("core.subdomain_manager.socket.gethostbyname", return_value="192.168.1.200"):
            result = check_subdomain_health("acme-corp")

        assert result["resolves"] is True
        assert result["correct"] is True
        assert result["ip"] == "192.168.1.200"

    def test_does_not_resolve(self):
        from core.subdomain_manager import check_subdomain_health
        import socket

        with patch("core.subdomain_manager.socket.gethostbyname", side_effect=socket.gaierror):
            result = check_subdomain_health("nonexistent")

        assert result["resolves"] is False
        assert result["correct"] is False

    def test_resolves_wrong_ip(self):
        from core.subdomain_manager import check_subdomain_health

        with patch("core.subdomain_manager.socket.gethostbyname", return_value="1.2.3.4"):
            result = check_subdomain_health("wrong-ip")

        assert result["resolves"] is True
        assert result["correct"] is False


class TestCustomDomainHealth:
    def test_resolves_correctly(self):
        from core.subdomain_manager import check_custom_domain_health

        with patch("core.subdomain_manager.socket.gethostbyname", return_value="192.168.1.200"):
            result = check_custom_domain_health("app.acme.com")

        assert result["resolves"] is True
        assert result["correct"] is True
