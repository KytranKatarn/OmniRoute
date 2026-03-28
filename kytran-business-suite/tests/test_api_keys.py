"""Tests for API key generation, validation, and rate limiting."""

import hashlib
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest


def _mock_db_ctx(fetchone_val=None, fetchall_val=None):
    """Create a mock that works with `with get_db_cursor(...) as (conn, cur):`."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = fetchone_val
    mock_cur.fetchall.return_value = fetchall_val or []
    mock_conn = MagicMock()

    @contextmanager
    def ctx_mgr(*args, **kwargs):
        yield mock_conn, mock_cur

    return ctx_mgr, mock_cur


class TestApiKeyGeneration:
    @patch("core.api_keys.get_db_cursor")
    def test_generate_key_returns_raw_key(self, mock_db):
        from core.api_keys import generate_api_key

        db_row = {
            "id": 1, "tenant_id": 1, "key_prefix": "kbs_abc",
            "name": "Test Key", "permissions": ["read", "write"],
            "rate_limit": 100, "created_at": "2026-01-01",
        }
        ctx, cur = _mock_db_ctx(fetchone_val=db_row)
        mock_db.side_effect = ctx

        key_data = generate_api_key(
            tenant_id=1, name="Test Key",
            permissions=["read", "write"], rate_limit=100,
        )
        assert "key" in key_data
        assert key_data["key"].startswith("kbs_")
        assert len(key_data["key"]) >= 40
        assert key_data["name"] == "Test Key"

    @patch("core.api_keys.get_db_cursor")
    def test_key_is_unique(self, mock_db):
        from core.api_keys import generate_api_key

        db_row = {
            "id": 1, "tenant_id": 1, "key_prefix": "kbs_abc",
            "name": "Key", "permissions": ["read"],
            "rate_limit": 1000, "created_at": "2026-01-01",
        }
        ctx, cur = _mock_db_ctx(fetchone_val=db_row)
        mock_db.side_effect = ctx

        key1 = generate_api_key(tenant_id=1, name="Key A")
        key2 = generate_api_key(tenant_id=1, name="Key B")
        assert key1["key"] != key2["key"]

    def test_hash_key_is_sha256(self):
        from core.api_keys import _hash_key

        result = _hash_key("test_key")
        expected = hashlib.sha256(b"test_key").hexdigest()
        assert result == expected
        assert len(result) == 64


class TestApiKeyValidation:
    @patch("core.api_keys.get_db_cursor")
    def test_validate_valid_key(self, mock_db):
        from core.api_keys import validate_api_key

        db_row = {
            "id": 1, "tenant_id": 1, "name": "Test",
            "permissions": ["read"], "rate_limit": 1000,
        }
        ctx, cur = _mock_db_ctx(fetchone_val=db_row)
        mock_db.side_effect = ctx

        result = validate_api_key("kbs_some_valid_key")
        assert result is not None
        assert result["tenant_id"] == 1

    @patch("core.api_keys.get_db_cursor")
    def test_validate_invalid_key(self, mock_db):
        from core.api_keys import validate_api_key

        ctx, cur = _mock_db_ctx(fetchone_val=None)
        mock_db.side_effect = ctx

        result = validate_api_key("kbs_invalid_key")
        assert result is None

    @patch("core.api_keys.get_db_cursor")
    def test_validate_updates_last_used(self, mock_db):
        from core.api_keys import validate_api_key

        db_row = {
            "id": 5, "tenant_id": 1, "name": "Test",
            "permissions": ["read"], "rate_limit": 1000,
        }
        ctx, cur = _mock_db_ctx(fetchone_val=db_row)
        mock_db.side_effect = ctx

        validate_api_key("kbs_test_key")
        calls = cur.execute.call_args_list
        assert len(calls) >= 2
        assert "last_used_at" in str(calls[1])


class TestRevokeKey:
    @patch("core.api_keys.get_db_cursor")
    def test_revoke_existing_key(self, mock_db):
        from core.api_keys import revoke_api_key

        ctx, cur = _mock_db_ctx()
        mock_db.side_effect = ctx
        cur.fetchone.return_value = (1,)

        result = revoke_api_key(key_id=1)
        assert result is True

    @patch("core.api_keys.get_db_cursor")
    def test_revoke_nonexistent_key(self, mock_db):
        from core.api_keys import revoke_api_key

        ctx, cur = _mock_db_ctx(fetchone_val=None)
        mock_db.side_effect = ctx

        result = revoke_api_key(key_id=99999)
        assert result is False


class TestListKeys:
    @patch("core.api_keys.get_db_cursor")
    def test_list_returns_keys(self, mock_db):
        from core.api_keys import list_api_keys

        keys = [
            {"id": 1, "key_prefix": "kbs_abc", "name": "Key 1",
             "permissions": ["read"], "rate_limit": 1000,
             "is_active": True, "last_used_at": None, "created_at": "2026-01-01"},
        ]
        ctx, cur = _mock_db_ctx(fetchall_val=keys)
        mock_db.side_effect = ctx

        result = list_api_keys(tenant_id=1)
        assert len(result) == 1
        assert result[0]["name"] == "Key 1"


class TestRateLimiting:
    @patch("core.api_keys.get_db_cursor")
    def test_check_rate_limit_under_limit(self, mock_db):
        from core.api_keys import check_rate_limit

        ctx, cur = _mock_db_ctx(fetchone_val={"count": 5})
        mock_db.side_effect = ctx

        result = check_rate_limit(key_id=1, rate_limit=100)
        assert result["allowed"] is True
        assert result["remaining"] == 95

    @patch("core.api_keys.get_db_cursor")
    def test_check_rate_limit_at_limit(self, mock_db):
        from core.api_keys import check_rate_limit

        ctx, cur = _mock_db_ctx(fetchone_val={"count": 101})
        mock_db.side_effect = ctx

        result = check_rate_limit(key_id=1, rate_limit=100)
        assert result["allowed"] is False
        assert result["remaining"] == 0

    @patch("core.api_keys.get_db_cursor")
    def test_check_rate_limit_returns_limit(self, mock_db):
        from core.api_keys import check_rate_limit

        ctx, cur = _mock_db_ctx(fetchone_val={"count": 50})
        mock_db.side_effect = ctx

        result = check_rate_limit(key_id=1, rate_limit=100)
        assert result["limit"] == 100
