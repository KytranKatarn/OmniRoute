"""Tests for the Photography Studio plugin — packages, shoots, galleries, editing queue, stats."""

import json
import os

import pytest

os.environ.setdefault("KBS_DB_HOST", "192.168.1.200")
os.environ.setdefault("KBS_DB_NAME", "archie")
os.environ.setdefault("KBS_DB_USER", "archie")
os.environ.setdefault("KBS_DB_PASSWORD", os.getenv("DB_PASSWORD", ""))

from core.database import (
    create_tenant_schema,
    drop_tenant_schema,
    get_db_cursor,
    run_migration_file,
    set_tenant_search_path,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TEST_TENANT_ID = 9917
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "phototest@example.com"
TEST_PASSWORD = "TestPass123!"

MIGRATION_CRM = os.path.join(
    os.path.dirname(__file__), "..", "..", "kbs_crm", "migrations", "001_crm_tables.sql"
)
MIGRATION_INDUSTRY = os.path.join(
    os.path.dirname(__file__), "..", "..", "kbs_industry", "migrations", "001_industry_tables.sql"
)
MIGRATION_PHOTOGRAPHY = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_photography_tables.sql"
)


@pytest.fixture(scope="module")
def photography_app():
    """Create the Flask app with Photography plugin loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def photography_setup(photography_app):
    """Create test tenant, user, schema, tables, and enable required modules."""
    from werkzeug.security import generate_password_hash

    pw_hash = generate_password_hash(TEST_PASSWORD)

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        # Clean up leftovers from a previous failed run
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))

        cur.execute(
            """
            INSERT INTO users (email, username, password_hash, is_active)
            VALUES (%s, 'Photo Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'Photography Test Tenant', 'photography-test-tenant', 'business', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        # Ensure required slugs exist in module_catalog
        for slug, name, category in [
            ("crm", "CRM", "ecommerce"),
            ("industry", "Industry Framework", "ecommerce"),
            ("industry-photography", "Photography Studio", "ecommerce"),
        ]:
            cur.execute(
                """
                INSERT INTO module_catalog (slug, name, tier_required, category)
                VALUES (%s, %s, 'business', %s)
                ON CONFLICT (slug) DO NOTHING
                """,
                (slug, name, category),
            )

        for slug in ("crm", "industry", "industry-photography"):
            cur.execute(
                """
                INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
                """,
                (TEST_TENANT_ID, slug),
            )

    # Create tenant schema and run migrations in dependency order
    create_tenant_schema(TEST_TENANT_ID)
    if os.path.exists(MIGRATION_CRM):
        run_migration_file(MIGRATION_CRM, schema=TEST_SCHEMA)
    if os.path.exists(MIGRATION_INDUSTRY):
        run_migration_file(MIGRATION_INDUSTRY, schema=TEST_SCHEMA)
    run_migration_file(MIGRATION_PHOTOGRAPHY, schema=TEST_SCHEMA)

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(photography_app, photography_setup):
    """Yield a logged-in test client with the tenant session set."""
    with photography_app.test_client() as client:
        resp = client.post(
            "/auth/login",
            data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200), f"Login failed: {resp.status_code}"
        yield client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def post_json(client, path, payload):
    return client.post(
        "/plugins/industry-photography" + path,
        data=json.dumps(payload),
        content_type="application/json",
    )


def put_json(client, path, payload):
    return client.put(
        "/plugins/industry-photography" + path,
        data=json.dumps(payload),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPackages:
    def test_create_package(self, authed_client):
        resp = post_json(authed_client, "/api/packages", {
            "name": "Wedding Full Day",
            "description": "8 hours, 2 photographers, 400+ edited images",
            "includes": ["8 hours coverage", "2 photographers", "online gallery", "USB drive"],
            "price": 2800.00,
            "duration_hours": 8.0,
            "max_images": 400,
            "digital_delivery": True,
            "print_included": False,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["name"] == "Wedding Full Day"
        assert float(data["price"]) == 2800.00
        TestPackages._package_id = data["id"]

    def test_list_packages(self, authed_client):
        resp = authed_client.get("/plugins/industry-photography/api/packages")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "packages" in data
        assert len(data["packages"]) >= 1


class TestShoots:
    def test_book_shoot(self, authed_client):
        resp = post_json(authed_client, "/api/shoots", {
            "shoot_type": "wedding",
            "shoot_date": "2026-06-15",
            "location": "Niagara Falls, ON",
            "duration_hours": 8.0,
            "package_id": TestPackages._package_id,
            "total_images": 400,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["shoot_type"] == "wedding"
        assert data["status"] == "booked"
        TestShoots._shoot_id = data["id"]

    def test_update_shoot_status(self, authed_client):
        resp = put_json(authed_client, f"/api/shoots/{TestShoots._shoot_id}", {
            "status": "confirmed",
        })
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "confirmed"

    def test_create_gallery(self, authed_client):
        resp = post_json(authed_client, f"/api/shoots/{TestShoots._shoot_id}/galleries", {
            "name": "Jones Wedding — Preview Gallery",
            "url": "https://gallery.example.com/jones-wedding",
            "password": "jones2026",
            "is_public": False,
            "download_enabled": True,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["name"] == "Jones Wedding — Preview Gallery"
        TestShoots._gallery_id = data["id"]

    def test_add_to_editing_queue(self, authed_client):
        resp = post_json(authed_client, f"/api/shoots/{TestShoots._shoot_id}/editing", {
            "editor": "Sarah Chen",
            "total_images": 800,
            "edited_images": 0,
            "style_preset": "light_airy",
            "due_date": "2026-06-29",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["editor"] == "Sarah Chen"
        assert data["status"] == "pending"
        TestShoots._edit_id = data["id"]

    def test_update_editing_progress(self, authed_client):
        resp = put_json(authed_client, f"/api/editing/{TestShoots._edit_id}", {
            "status": "in_progress",
            "edited_images": 350,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "in_progress"
        assert data["edited_images"] == 350

    def test_mark_shoot_delivered(self, authed_client):
        resp = authed_client.post(
            f"/plugins/industry-photography/api/shoots/{TestShoots._shoot_id}/deliver"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "delivered"


class TestStats:
    def test_stats(self, authed_client):
        resp = authed_client.get("/plugins/industry-photography/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "shoots_this_month" in data
        assert "pending_edits" in data
        assert "galleries_live" in data
        assert "revenue" in data
        assert data["galleries_live"] >= 1
