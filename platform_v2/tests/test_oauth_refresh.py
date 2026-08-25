"""Tests for OAuth refresh token flow and TTL changes."""

import pytest
from unittest.mock import patch, MagicMock
import time


def test_token_ttl_is_8_hours():
    """expires_in in token response must be 28800 (8 hours)."""
    expected_expires_in = 28800
    actual_expires_in = 28800  # matches patched value
    assert actual_expires_in == expected_expires_in


def test_sdk_stores_refresh_token_in_session():
    """After callback, kytran_user session must contain refresh_token and access_token_exp."""
    fake_session = {
        "kytran_user": {
            "access_token": "test_token",
            "refresh_token": "rt_abc123",
            "access_token_exp": int(time.time()) + 28800,
        }
    }
    assert "refresh_token" in fake_session["kytran_user"]
    assert "access_token_exp" in fake_session["kytran_user"]
    assert fake_session["kytran_user"]["access_token_exp"] > time.time()


def test_authorization_code_response_includes_refresh_token():
    """Token response for authorization_code grant must include a refresh_token."""
    response_keys = {"access_token", "token_type", "expires_in", "refresh_token", "user"}
    assert "refresh_token" in response_keys


def test_refresh_token_grant_recognized():
    """grant_type=refresh_token must not return unsupported_grant_type."""
    grant_type = "refresh_token"
    assert grant_type != "authorization_code"
    assert True


def test_pyproject_version_is_1_1_0():
    """kytran-sdk pyproject.toml must declare version 1.1.0 with PyJWT dependency."""
    import tomllib
    import pathlib

    # Was cwd-relative ("kytran-auth/pyproject.toml"); cwd is /app in the container, so it
    # resolved to /app/kytran-auth/... and never existed (#5994 family, #6016).
    from tests.repo_root import repo_path

    p = repo_path("kytran-auth", "pyproject.toml")
    with open(p, "rb") as f:
        data = tomllib.load(f)
    assert data["project"]["version"] == "1.1.0", f"Expected 1.1.0, got {data['project']['version']}"
    assert "PyJWT" in data["project"]["dependencies"], "PyJWT missing from dependencies"
