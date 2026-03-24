import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from archie_engine.hub.connector import HubConnector
from archie_engine.hub.auth import HubAuth


def _mock_response(status=200, json_data=None):
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


@pytest.fixture
def connector(tmp_path):
    auth = HubAuth(key_file=tmp_path / ".key")
    auth.store_key("test-key")
    return HubConnector(hub_url="http://localhost:3000", auth=auth, timeout=5)


@pytest.mark.asyncio
async def test_get_success(connector):
    mock_resp = _mock_response(200, {"status": "ok"})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        result = await connector.get("/api/health")
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_post_success(connector):
    mock_resp = _mock_response(200, {"result": "done"})
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await connector.post("/api/action", data={"key": "val"})
    assert result["result"] == "done"


@pytest.mark.asyncio
async def test_auth_failure_returns_error(connector):
    mock_resp = _mock_response(401, {"error": "unauthorized"})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        result = await connector.get("/api/health")
    assert "error" in result
    assert result["status"] == 401


@pytest.mark.asyncio
async def test_connection_error_returns_error(connector):
    with patch("aiohttp.ClientSession.get", side_effect=Exception("Connection refused")):
        result = await connector.get("/api/health")
    assert "error" in result
    assert result["status"] == 0


@pytest.mark.asyncio
async def test_server_error_returns_error(connector):
    mock_resp = _mock_response(500, {"error": "internal"})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        result = await connector.get("/api/health")
    assert "error" in result
    assert result["status"] == 500
