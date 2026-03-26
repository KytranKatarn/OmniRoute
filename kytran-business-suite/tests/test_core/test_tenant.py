"""
Tests for core/tenant.py.

Uses tenant IDs in the 9xx range (9001, 9002) for isolation.
conftest.py / test_database.py cleanup fixture drops all tenant_9* schemas,
but these tests only touch public schema tables (tenants, tenant_modules,
module_catalog), so we clean those rows directly.

Requirements: migrations 001 and 002 must have been run against the test DB
so that the tenants, tenant_modules, and module_catalog tables exist.
"""

import pytest
from flask import Flask, g

from core.database import get_db_cursor
from core.tenant import get_enabled_modules, require_module

# -----------------------------------------------------------------------
# Test tenant IDs (9xx range — safe for dev DB)
# -----------------------------------------------------------------------
TENANT_A = 9001
TENANT_B = 9002


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def cleanup_test_tenants():
    """Remove test tenant rows before and after each test."""
    _delete_test_tenants()
    yield
    _delete_test_tenants()


def _delete_test_tenants():
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM tenant_modules WHERE tenant_id IN %s",
            ((TENANT_A, TENANT_B),),
        )
        cur.execute(
            "DELETE FROM tenants WHERE id IN %s",
            ((TENANT_A, TENANT_B),),
        )


def _create_tenant(tenant_id: int, name: str = "Test Tenant") -> None:
    """Insert a minimal tenant row with a specific id."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, %s, %s, 'free', TRUE)
            ON CONFLICT (id) DO NOTHING
            """,
            (tenant_id, name, f"test-tenant-{tenant_id}"),
        )


def _enable_module(tenant_id: int, slug: str) -> None:
    """Enable a module for a tenant in tenant_modules."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO tenant_modules (tenant_id, module_slug, enabled, source)
            VALUES (%s, %s, TRUE, 'manual')
            ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
            """,
            (tenant_id, slug),
        )


@pytest.fixture()
def app():
    """Minimal Flask app for testing tenant utilities."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test-secret"
    return flask_app


# -----------------------------------------------------------------------
# get_enabled_modules tests
# -----------------------------------------------------------------------


def test_get_enabled_modules_returns_enabled_slugs(app):
    """get_enabled_modules returns the slugs of all enabled modules."""
    _create_tenant(TENANT_A)
    _enable_module(TENANT_A, "crm")
    _enable_module(TENANT_A, "invoicing")

    with app.app_context():
        g.tenant_id = TENANT_A
        modules = get_enabled_modules()

    assert set(modules) == {"crm", "invoicing"}


def test_get_enabled_modules_excludes_disabled(app):
    """get_enabled_modules does not return modules with enabled=FALSE."""
    _create_tenant(TENANT_A)
    _enable_module(TENANT_A, "crm")

    # Disable the crm module explicitly
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE tenant_modules SET enabled = FALSE WHERE tenant_id = %s AND module_slug = 'crm'",
            (TENANT_A,),
        )

    with app.app_context():
        g.tenant_id = TENANT_A
        modules = get_enabled_modules()

    assert "crm" not in modules


def test_get_enabled_modules_empty_for_new_tenant(app):
    """A brand-new tenant with no modules assigned gets an empty list."""
    _create_tenant(TENANT_A)

    with app.app_context():
        g.tenant_id = TENANT_A
        modules = get_enabled_modules()

    assert modules == []


def test_get_enabled_modules_isolated_per_tenant(app):
    """Modules enabled for tenant A are not visible to tenant B."""
    _create_tenant(TENANT_A)
    _create_tenant(TENANT_B)
    _enable_module(TENANT_A, "crm")

    with app.app_context():
        g.tenant_id = TENANT_B
        modules = get_enabled_modules()

    assert "crm" not in modules


# -----------------------------------------------------------------------
# require_module decorator tests
# -----------------------------------------------------------------------


def test_require_module_allows_access_when_enabled(app):
    """require_module passes through when the module is enabled for the tenant."""
    _create_tenant(TENANT_A)
    _enable_module(TENANT_A, "crm")

    @require_module("crm")
    def protected_view():
        return "ok"

    with app.app_context():
        g.tenant_id = TENANT_A
        result = protected_view()

    assert result == "ok"


def test_require_module_blocks_when_not_enabled(app):
    """require_module aborts with 403 when the module is not enabled."""
    _create_tenant(TENANT_A)
    # crm NOT enabled for TENANT_A

    @require_module("crm")
    def protected_view():
        return "ok"

    with app.test_request_context("/"):
        with app.app_context():
            g.tenant_id = TENANT_A
            with pytest.raises(Exception) as exc_info:
                protected_view()

    # Flask abort raises werkzeug HTTPException with code 403
    assert exc_info.value.code == 403


def test_require_module_blocks_after_module_disabled(app):
    """require_module blocks if the module was enabled then disabled."""
    _create_tenant(TENANT_A)
    _enable_module(TENANT_A, "invoicing")

    # Disable it
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE tenant_modules SET enabled = FALSE "
            "WHERE tenant_id = %s AND module_slug = 'invoicing'",
            (TENANT_A,),
        )

    @require_module("invoicing")
    def protected_view():
        return "ok"

    with app.test_request_context("/"):
        with app.app_context():
            g.tenant_id = TENANT_A
            with pytest.raises(Exception) as exc_info:
                protected_view()

    assert exc_info.value.code == 403
