"""Tests for fleet_service Phase 3 write operations.

Run: docker exec archie_platform python -m pytest services/tests/test_phase3_fleet.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from database import get_db_cursor


def _cleanup_test_provider():
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM cloud_usage_log WHERE provider_id IN (SELECT id FROM cloud_providers WHERE name = 'TestProvider')"
        )
        cur.execute("DELETE FROM cloud_providers WHERE name = 'TestProvider'")


def test_register_provider():
    from services.fleet_service import register_provider

    _cleanup_test_provider()
    try:
        pid = register_provider(
            name="TestProvider",
            provider_type="cloud",
            api_key_env_var="TEST_KEY",
            tier="free",
            capabilities=["chat"],
        )
        assert isinstance(pid, int)
        assert pid > 0
    finally:
        _cleanup_test_provider()


def test_register_provider_with_location():
    from services.fleet_service import register_provider, get_cloud_provider

    _cleanup_test_provider()
    try:
        pid = register_provider(
            name="TestProvider",
            provider_type="cloud",
            api_key_env_var="TEST_KEY",
            tier="free",
            capabilities=["chat"],
            headquarters_city="Toronto",
            latitude=43.6532,
            longitude=-79.3832,
        )
        provider = get_cloud_provider(pid)
        assert provider is not None
        assert provider["name"] == "TestProvider"
        assert float(provider["latitude"]) == 43.6532
    finally:
        _cleanup_test_provider()


def test_record_cloud_usage():
    from services.fleet_service import register_provider, record_cloud_usage

    _cleanup_test_provider()
    try:
        pid = register_provider(
            name="TestProvider",
            provider_type="cloud",
            api_key_env_var="TEST_KEY",
            tier="free",
            capabilities=["chat"],
        )
        record_cloud_usage(pid, "test-model", 100, 50, 0.001, "chat")
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM cloud_usage_log WHERE provider_id = %s",
                (pid,),
            )
            assert cur.fetchone()["cnt"] == 1
    finally:
        _cleanup_test_provider()


def test_record_cloud_usage_updates_monthly():
    from services.fleet_service import (
        register_provider,
        record_cloud_usage,
        get_cloud_provider,
    )

    _cleanup_test_provider()
    try:
        pid = register_provider(
            name="TestProvider",
            provider_type="cloud",
            api_key_env_var="TEST_KEY",
            tier="free",
            capabilities=["chat"],
        )
        record_cloud_usage(pid, "test-model", 100, 50, 0.01, "chat")
        record_cloud_usage(pid, "test-model", 200, 100, 0.02, "chat")
        provider = get_cloud_provider(pid)
        assert float(provider["monthly_usage"]) == 0.03
    finally:
        _cleanup_test_provider()


def test_get_cloud_provider_not_found():
    from services.fleet_service import get_cloud_provider

    assert get_cloud_provider(-999) is None


def test_list_cloud_providers():
    from services.fleet_service import list_cloud_providers

    providers = list_cloud_providers()
    assert isinstance(providers, list)
    assert len(providers) >= 4
    names = [p["name"] for p in providers]
    assert "OpenAI" in names
    assert "Anthropic" in names
