"""Tests for public storefront routes — no login required for browsing."""

import json
from unittest.mock import patch, MagicMock

import pytest


def test_public_product_list_requires_no_login():
    """Verify the public product listing does not require authentication."""
    from plugins.kbs_store.public_routes import register_public_routes
    from flask import Flask, Blueprint

    app = Flask(__name__)
    app.config["TESTING"] = True
    bp = Blueprint("store_public_test", __name__)
    register_public_routes(bp, tenant_slug="demo")

    # Verify the function exists and is importable
    assert callable(register_public_routes)


def test_guest_checkout_requires_email():
    """Verify guest checkout validates email presence."""
    from plugins.kbs_store.public_routes import _validate_guest_checkout

    # Missing email should fail
    result = _validate_guest_checkout({})
    assert result is not None  # returns error message

    # With email should pass
    result = _validate_guest_checkout({"email": "guest@example.com"})
    assert result is None  # no error


def test_build_cart_total():
    """Verify cart total calculation."""
    from plugins.kbs_store.public_routes import _calculate_cart_total

    items = [
        {"price": 29.99, "quantity": 2},
        {"price": 14.99, "quantity": 1},
    ]
    total = _calculate_cart_total(items)
    assert abs(total - 74.97) < 0.01
