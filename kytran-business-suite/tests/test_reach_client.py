"""Tests for Hostinger Reach email marketing client -- all HTTP mocked."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def reach_client():
    from core.reach_client import ReachClient

    return ReachClient(
        api_url="https://api.hostinger.com/reach/v1",
        api_key="test-api-key",
    )


def test_list_contacts(reach_client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [{"id": 1, "email": "jane@test.com", "name": "Jane"}],
        "total": 1,
    }

    with patch("core.reach_client.requests.get", return_value=mock_resp) as mock_get:
        result = reach_client.list_contacts(page=1, per_page=10)

    assert result["total"] == 1
    assert result["data"][0]["email"] == "jane@test.com"
    # Verify auth header
    call_headers = mock_get.call_args[1]["headers"]
    assert "Bearer test-api-key" in call_headers["Authorization"]


def test_create_contact(reach_client):
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "id": 2,
        "email": "bob@test.com",
        "name": "Bob",
    }

    with patch("core.reach_client.requests.post", return_value=mock_resp):
        result = reach_client.create_contact(
            email="bob@test.com", name="Bob", fields={"company": "Acme"}
        )

    assert result["id"] == 2
    assert result["email"] == "bob@test.com"


def test_create_contact_minimal(reach_client):
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"id": 3, "email": "min@test.com"}

    with patch("core.reach_client.requests.post", return_value=mock_resp) as mock_post:
        result = reach_client.create_contact(email="min@test.com")

    assert result["id"] == 3
    posted_data = mock_post.call_args[1]["json"]
    assert posted_data == {"email": "min@test.com"}


def test_delete_contact(reach_client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b""

    with patch("core.reach_client.requests.delete", return_value=mock_resp):
        result = reach_client.delete_contact(contact_id=1)

    assert result == {}


def test_list_segments(reach_client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [{"id": 1, "name": "VIP Customers"}],
    }

    with patch("core.reach_client.requests.get", return_value=mock_resp):
        result = reach_client.list_segments()

    assert result["data"][0]["name"] == "VIP Customers"


def test_create_segment(reach_client):
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "id": 2,
        "name": "New Leads",
    }

    with patch("core.reach_client.requests.post", return_value=mock_resp):
        result = reach_client.create_segment(name="New Leads")

    assert result["id"] == 2


def test_get_segment(reach_client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "id": 1,
        "name": "VIP Customers",
        "contact_count": 50,
    }

    with patch("core.reach_client.requests.get", return_value=mock_resp):
        result = reach_client.get_segment(segment_id=1)

    assert result["contact_count"] == 50


def test_list_profiles(reach_client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [{"id": 1, "email": "noreply@kytranempowerment.com"}],
    }

    with patch("core.reach_client.requests.get", return_value=mock_resp):
        result = reach_client.list_profiles()

    assert len(result["data"]) == 1


def test_sync_crm_contacts(reach_client):
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"id": 10, "email": "sync@test.com"}

    contacts = [
        {"email": "sync1@test.com", "name": "Sync One"},
        {"email": "sync2@test.com", "name": "Sync Two"},
    ]

    with patch("core.reach_client.requests.post", return_value=mock_resp):
        result = reach_client.sync_crm_contacts(contacts)

    assert result["created"] == 2
    assert result["errors"] == 0
    assert result["total"] == 2


def test_sync_crm_contacts_with_errors(reach_client):
    contacts = [
        {"email": "ok@test.com"},
        {"email": "fail@test.com"},
    ]

    call_count = [0]

    def side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 2:
            raise Exception("API error")
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": 1, "email": "ok@test.com"}
        return mock_resp

    with patch("core.reach_client.requests.post", side_effect=side_effect):
        result = reach_client.sync_crm_contacts(contacts)

    assert result["created"] == 1
    assert result["errors"] == 1


def test_auth_error_raises(reach_client):
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.raise_for_status.side_effect = Exception("401 Unauthorized")

    with patch("core.reach_client.requests.get", return_value=mock_resp):
        with pytest.raises(Exception, match="401"):
            reach_client.list_contacts()
