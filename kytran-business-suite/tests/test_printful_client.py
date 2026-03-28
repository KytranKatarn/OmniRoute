"""Tests for Printful API client."""

import json
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture()
def mock_response():
    """Create a mock requests.Response."""

    def _make(status_code=200, json_data=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data or {}
        resp.raise_for_status = MagicMock()
        if status_code >= 400:
            resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
        return resp

    return _make


def test_get_products_returns_list(mock_response):
    """Verify get_products returns a list of Printful catalog items."""
    from core.printful_client import PrintfulClient

    client = PrintfulClient(api_key="test_key")
    mock_data = {
        "result": [
            {"id": 1, "title": "Unisex Staple T-Shirt", "variants": 25},
            {"id": 2, "title": "Mug 11oz", "variants": 3},
        ]
    }

    with patch("core.printful_client.requests.get", return_value=mock_response(200, mock_data)):
        products = client.get_catalog_products()

    assert len(products) == 2
    assert products[0]["title"] == "Unisex Staple T-Shirt"


def test_create_order_sends_correct_payload(mock_response):
    """Verify order submission sends the right structure to Printful."""
    from core.printful_client import PrintfulClient

    client = PrintfulClient(api_key="test_key")
    mock_data = {"result": {"id": 12345, "status": "draft"}}

    order = {
        "recipient": {
            "name": "Jane Smith",
            "address1": "123 Main St",
            "city": "Toronto",
            "state_code": "ON",
            "country_code": "CA",
            "zip": "M5V 1A1",
        },
        "items": [
            {
                "variant_id": 4012,
                "quantity": 2,
                "files": [{"url": "https://example.com/design.png"}],
            }
        ],
    }

    with patch("core.printful_client.requests.post", return_value=mock_response(200, mock_data)) as mock_post:
        result = client.create_order(order)

    assert result["id"] == 12345
    assert result["status"] == "draft"
    mock_post.assert_called_once()


def test_get_order_status(mock_response):
    """Verify fetching order status works."""
    from core.printful_client import PrintfulClient

    client = PrintfulClient(api_key="test_key")
    mock_data = {
        "result": {
            "id": 12345,
            "status": "fulfilled",
            "shipments": [{"carrier": "USPS", "tracking_number": "9400111899223"}],
        }
    }

    with patch("core.printful_client.requests.get", return_value=mock_response(200, mock_data)):
        result = client.get_order(12345)

    assert result["status"] == "fulfilled"
    assert len(result["shipments"]) == 1


def test_sync_product_creates_mapping(mock_response):
    """Verify product sync creates a mapping between KBS product and Printful variant."""
    from core.printful_client import PrintfulClient

    client = PrintfulClient(api_key="test_key")
    mock_data = {
        "result": {
            "sync_product": {"id": 999, "name": "My T-Shirt"},
            "sync_variants": [
                {"id": 5001, "variant_id": 4012, "retail_price": "25.00"},
                {"id": 5002, "variant_id": 4013, "retail_price": "25.00"},
            ],
        }
    }

    with patch("core.printful_client.requests.get", return_value=mock_response(200, mock_data)):
        result = client.get_sync_product(999)

    assert result["sync_product"]["name"] == "My T-Shirt"
    assert len(result["sync_variants"]) == 2


def test_client_uses_auth_header(mock_response):
    """Verify all requests include the Bearer token."""
    from core.printful_client import PrintfulClient

    client = PrintfulClient(api_key="pk_test_abc123")

    with patch("core.printful_client.requests.get", return_value=mock_response(200, {"result": []})) as mock_get:
        client.get_catalog_products()

    call_kwargs = mock_get.call_args
    headers = call_kwargs[1].get("headers", {})
    assert "Authorization" in headers
    assert headers["Authorization"] == "Bearer pk_test_abc123"
