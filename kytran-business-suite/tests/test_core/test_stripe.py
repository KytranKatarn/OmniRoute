"""Tests for core.stripe_billing — tier management, module activation, webhook."""

import json
import os

import pytest

# Ensure test DB env vars are set before importing project code
os.environ.setdefault("KBS_DB_HOST", "192.168.1.200")
os.environ.setdefault("KBS_DB_NAME", "archie")
os.environ.setdefault("KBS_DB_USER", "archie")
os.environ.setdefault("KBS_DB_PASSWORD", os.getenv("DB_PASSWORD", ""))

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.database import get_db_cursor
from core.stripe_billing import (
    TIER_MODULES,
    activate_module,
    deactivate_module,
    get_modules_for_tier,
    sync_tier_modules,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_TENANT_BASE = 900  # IDs 900-909 reserved for stripe billing tests


def _create_test_tenant(tenant_id: int, tier: str = "free") -> None:
    """Create a disposable tenant row for a test."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, TRUE, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET tier = EXCLUDED.tier
            """,
            (tenant_id, f"Test Tenant {tenant_id}", f"test-tenant-{tenant_id}", tier),
        )


def _cleanup_tenant(tenant_id: int) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (tenant_id,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))


def _get_module_row(tenant_id: int, module_slug: str) -> dict | None:
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            "SELECT * FROM tenant_modules WHERE tenant_id = %s AND module_slug = %s",
            (tenant_id, module_slug),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Tier definition tests (no DB needed)
# ---------------------------------------------------------------------------


class TestGetModulesForTier:
    def test_free_tier_modules(self):
        modules = get_modules_for_tier("free")
        assert modules == {"crm", "invoicing", "store", "automations"}

    def test_business_includes_free_modules(self):
        free = get_modules_for_tier("free")
        business = get_modules_for_tier("business")
        assert free.issubset(business), "business tier must include all free modules"
        assert "appointments" in business
        assert "content-studio" in business
        assert "social-media" in business
        assert "website-builder" in business
        assert "marketing" in business
        assert "help-desk" in business
        assert "accounting" in business

    def test_enterprise_includes_all_modules(self):
        business = get_modules_for_tier("business")
        enterprise = get_modules_for_tier("enterprise")
        assert business.issubset(enterprise), "enterprise tier must include all business modules"
        assert "call-center" in enterprise
        assert "automations-ui" in enterprise
        assert "contracts" in enterprise

    def test_unknown_tier_falls_back_to_free(self):
        assert get_modules_for_tier("unknown") == get_modules_for_tier("free")

    def test_tier_modules_dict_keys(self):
        assert set(TIER_MODULES.keys()) == {"free", "business", "enterprise"}


# ---------------------------------------------------------------------------
# DB tests — activate / deactivate / sync
# ---------------------------------------------------------------------------


class TestActivateModule:
    TENANT_ID = TEST_TENANT_BASE + 1

    def setup_method(self):
        _create_test_tenant(self.TENANT_ID)

    def teardown_method(self):
        _cleanup_tenant(self.TENANT_ID)

    def test_activate_creates_row(self):
        activate_module(self.TENANT_ID, "crm")
        row = _get_module_row(self.TENANT_ID, "crm")
        assert row is not None
        assert row["enabled"] is True
        assert row["module_slug"] == "crm"

    def test_activate_default_source(self):
        activate_module(self.TENANT_ID, "invoicing")
        row = _get_module_row(self.TENANT_ID, "invoicing")
        assert row["source"] == "tier_included"

    def test_activate_custom_source(self):
        activate_module(self.TENANT_ID, "call-center", source="addon_purchase")
        row = _get_module_row(self.TENANT_ID, "call-center")
        assert row["source"] == "addon_purchase"

    def test_activate_reenables_disabled_module(self):
        activate_module(self.TENANT_ID, "crm")
        deactivate_module(self.TENANT_ID, "crm")
        row = _get_module_row(self.TENANT_ID, "crm")
        assert row["enabled"] is False

        activate_module(self.TENANT_ID, "crm")
        row = _get_module_row(self.TENANT_ID, "crm")
        assert row["enabled"] is True
        assert row["deactivated_at"] is None

    def test_activate_idempotent(self):
        activate_module(self.TENANT_ID, "crm")
        activate_module(self.TENANT_ID, "crm")  # should not raise
        row = _get_module_row(self.TENANT_ID, "crm")
        assert row["enabled"] is True


class TestDeactivateModule:
    TENANT_ID = TEST_TENANT_BASE + 2

    def setup_method(self):
        _create_test_tenant(self.TENANT_ID)

    def teardown_method(self):
        _cleanup_tenant(self.TENANT_ID)

    def test_deactivate_sets_enabled_false(self):
        activate_module(self.TENANT_ID, "crm")
        deactivate_module(self.TENANT_ID, "crm")
        row = _get_module_row(self.TENANT_ID, "crm")
        assert row["enabled"] is False

    def test_deactivate_sets_deactivated_at(self):
        activate_module(self.TENANT_ID, "crm")
        deactivate_module(self.TENANT_ID, "crm")
        row = _get_module_row(self.TENANT_ID, "crm")
        assert row["deactivated_at"] is not None

    def test_deactivate_nonexistent_row_is_noop(self):
        # Should not raise even if module was never activated
        deactivate_module(self.TENANT_ID, "nonexistent-module")


class TestSyncTierModules:
    TENANT_ID = TEST_TENANT_BASE + 3

    def setup_method(self):
        _create_test_tenant(self.TENANT_ID)

    def teardown_method(self):
        _cleanup_tenant(self.TENANT_ID)

    def test_sync_free_tier_enables_all_free_modules(self):
        sync_tier_modules(self.TENANT_ID, "free")
        for slug in get_modules_for_tier("free"):
            row = _get_module_row(self.TENANT_ID, slug)
            assert row is not None, f"Module {slug} not found"
            assert row["enabled"] is True, f"Module {slug} not enabled"

    def test_sync_business_tier_enables_all_business_modules(self):
        sync_tier_modules(self.TENANT_ID, "business")
        for slug in get_modules_for_tier("business"):
            row = _get_module_row(self.TENANT_ID, slug)
            assert row is not None, f"Module {slug} not found"
            assert row["enabled"] is True

    def test_sync_enterprise_tier_enables_all_enterprise_modules(self):
        sync_tier_modules(self.TENANT_ID, "enterprise")
        for slug in get_modules_for_tier("enterprise"):
            row = _get_module_row(self.TENANT_ID, slug)
            assert row is not None, f"Module {slug} not found"
            assert row["enabled"] is True

    def test_sync_reenables_previously_disabled(self):
        sync_tier_modules(self.TENANT_ID, "free")
        deactivate_module(self.TENANT_ID, "crm")
        sync_tier_modules(self.TENANT_ID, "free")
        row = _get_module_row(self.TENANT_ID, "crm")
        assert row["enabled"] is True
