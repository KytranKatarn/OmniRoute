"""Tests for the Website Builder plugin — projects, pages, deployments, stats."""

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

TEST_TENANT_ID = 9904
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "wbtest@example.com"
TEST_PASSWORD = "TestPass123!"
MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "migrations",
    "001_website_builder_tables.sql",
)


@pytest.fixture(scope="module")
def wb_app():
    """Create the Flask app with Website Builder plugin loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def wb_setup(wb_app):
    """Create test tenant, user, schema, tables, and enable website-builder module."""
    from werkzeug.security import generate_password_hash

    pw_hash = generate_password_hash(TEST_PASSWORD)

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))

        cur.execute(
            """
            INSERT INTO users (email, username, password_hash, is_active)
            VALUES (%s, 'WB Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'WB Test Tenant', 'wb-test-tenant', 'business', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        cur.execute(
            """
            INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
            VALUES (%s, 'website-builder', TRUE)
            ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
            """,
            (TEST_TENANT_ID,),
        )

    create_tenant_schema(TEST_TENANT_ID)
    run_migration_file(MIGRATION_PATH, schema=TEST_SCHEMA)

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id}

    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(wb_app, wb_setup):
    """Yield a logged-in test client with tenant session set."""
    with wb_app.test_client() as client:
        resp = client.post(
            "/auth/login",
            data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200), f"Login failed: {resp.status_code}"
        yield client


# ======================================================================
# Tests
# ======================================================================

BASE = "/plugins/website-builder"


class TestProjects:
    """Website project CRUD tests."""

    def test_create_project(self, authed_client):
        resp = authed_client.post(
            f"{BASE}/api/projects",
            data=json.dumps({"name": "My First Site", "domain": "first.example.com"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "My First Site"
        assert data["domain"] == "first.example.com"
        assert data["status"] == "draft"
        assert data["id"] is not None

    def test_list_projects(self, authed_client):
        authed_client.post(
            f"{BASE}/api/projects",
            data=json.dumps({"name": "List Test Site"}),
            content_type="application/json",
        )
        resp = authed_client.get(f"{BASE}/api/projects")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "projects" in data
        assert data["total"] >= 1
        names = [p["name"] for p in data["projects"]]
        assert "List Test Site" in names

    def test_create_page(self, authed_client):
        # Create a project first
        proj_resp = authed_client.post(
            f"{BASE}/api/projects",
            data=json.dumps({"name": "Page Test Site"}),
            content_type="application/json",
        )
        project_id = proj_resp.get_json()["id"]

        resp = authed_client.post(
            f"{BASE}/api/projects/{project_id}/pages",
            data=json.dumps({"title": "Home Page", "slug": "home", "page_type": "home"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["title"] == "Home Page"
        assert data["slug"] == "home"
        assert data["page_type"] == "home"
        assert data["is_published"] is False

    def test_list_pages(self, authed_client):
        proj_resp = authed_client.post(
            f"{BASE}/api/projects",
            data=json.dumps({"name": "Pages List Site"}),
            content_type="application/json",
        )
        project_id = proj_resp.get_json()["id"]

        authed_client.post(
            f"{BASE}/api/projects/{project_id}/pages",
            data=json.dumps({"title": "About", "slug": "about"}),
            content_type="application/json",
        )

        resp = authed_client.get(f"{BASE}/api/projects/{project_id}/pages")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "pages" in data
        assert data["total"] >= 1
        slugs = [p["slug"] for p in data["pages"]]
        assert "about" in slugs

    def test_update_page(self, authed_client):
        proj_resp = authed_client.post(
            f"{BASE}/api/projects",
            data=json.dumps({"name": "Update Page Site"}),
            content_type="application/json",
        )
        project_id = proj_resp.get_json()["id"]

        page_resp = authed_client.post(
            f"{BASE}/api/projects/{project_id}/pages",
            data=json.dumps({"title": "Draft Page", "slug": "draft-page"}),
            content_type="application/json",
        )
        page_id = page_resp.get_json()["id"]

        resp = authed_client.put(
            f"{BASE}/api/pages/{page_id}",
            data=json.dumps({"title": "Updated Title", "content": "<p>Hello world</p>"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["title"] == "Updated Title"
        assert data["content"] == "<p>Hello world</p>"

    def test_publish_project(self, authed_client):
        proj_resp = authed_client.post(
            f"{BASE}/api/projects",
            data=json.dumps({"name": "Publish Me"}),
            content_type="application/json",
        )
        project_id = proj_resp.get_json()["id"]

        resp = authed_client.post(f"{BASE}/api/projects/{project_id}/publish")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "published"

    def test_create_deployment(self, authed_client):
        proj_resp = authed_client.post(
            f"{BASE}/api/projects",
            data=json.dumps({"name": "Deploy Site"}),
            content_type="application/json",
        )
        project_id = proj_resp.get_json()["id"]

        resp = authed_client.post(
            f"{BASE}/api/projects/{project_id}/deploy",
            data=json.dumps({"deployment_url": "https://deploy.example.com", "provider": "github"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["project_id"] == project_id
        assert data["status"] == "pending"
        assert data["provider"] == "github"

    def test_get_stats(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_projects" in data
        assert "published_sites" in data
        assert "total_pages" in data
        assert "recent_deployments" in data
