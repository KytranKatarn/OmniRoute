"""Tests for Hostinger static site deployment service."""

import io
import zipfile

import pytest
from unittest.mock import patch, MagicMock


def test_build_site_zip_creates_valid_zip():
    from core.hostinger_deploy import build_site_zip

    pages = [
        {"slug": "index", "content": "<html><body><h1>Home</h1></body></html>"},
        {"slug": "about", "content": "<html><body><h1>About</h1></body></html>"},
    ]

    zip_bytes = build_site_zip(pages)

    assert isinstance(zip_bytes, bytes)
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = zf.namelist()
    assert "index.html" in names
    assert "about.html" in names
    assert len(names) == 2

    content = zf.read("index.html").decode("utf-8")
    assert "<h1>Home</h1>" in content


def test_build_site_zip_empty_pages():
    from core.hostinger_deploy import build_site_zip

    zip_bytes = build_site_zip([])
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    assert len(zf.namelist()) == 0


def test_deploy_to_hostinger_success():
    from core.hostinger_deploy import deploy_to_hostinger

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "url": "https://example.kytranempowerment.com",
        "status": "deployed",
    }

    with patch("core.hostinger_deploy.requests.post", return_value=mock_resp):
        result = deploy_to_hostinger(
            zip_bytes=b"fake-zip-data",
            domain="example.kytranempowerment.com",
            hostinger_api_key="test-key",
        )

    assert result["status"] == "deployed"
    assert "url" in result


def test_deploy_to_hostinger_failure():
    from core.hostinger_deploy import DeploymentError, deploy_to_hostinger

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Server Error"
    mock_resp.raise_for_status.side_effect = Exception("500")

    with patch("core.hostinger_deploy.requests.post", return_value=mock_resp):
        with pytest.raises(DeploymentError):
            deploy_to_hostinger(
                zip_bytes=b"fake-zip-data",
                domain="example.kytranempowerment.com",
                hostinger_api_key="test-key",
            )


def test_deploy_to_hostinger_stub_mode():
    """When no API key is configured, use stub mode that records the deployment."""
    from core.hostinger_deploy import deploy_to_hostinger

    result = deploy_to_hostinger(
        zip_bytes=b"fake-zip-data",
        domain="example.kytranempowerment.com",
        hostinger_api_key="",
    )

    assert result["status"] == "pending_manual"
    assert "url" in result
