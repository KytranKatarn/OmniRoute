"""Tests for the Content Studio plugin — documents CRUD, templates, export, stats."""

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

TEST_TENANT_ID = 9902
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "cstest@example.com"
TEST_PASSWORD = "TestPass123!"
MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_content_studio_tables.sql"
)


@pytest.fixture(scope="module")
def cs_app():
    """Create the Flask app with Content Studio plugin loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def cs_setup(cs_app):
    """Create test tenant, user, schema, Content Studio tables, and enable the module.

    Yields the tenant_id. Cleans up afterwards.
    """
    from werkzeug.security import generate_password_hash

    pw_hash = generate_password_hash(TEST_PASSWORD)

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        # Clean up any leftovers from a previous failed run
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))

        cur.execute(
            """
            INSERT INTO users (email, username, password_hash, is_active)
            VALUES (%s, 'CS Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'CS Test Tenant', 'cs-test-tenant', 'business', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        # Enable content-studio module (slug with hyphen)
        cur.execute(
            """
            INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
            VALUES (%s, 'content-studio', TRUE)
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
def authed_client(cs_app, cs_setup):
    """Yield a test client that is logged in and has the tenant session set."""
    with cs_app.test_client() as client:
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


class TestContentStudioDocuments:
    """Document CRUD, publish, export, and stats tests."""

    def test_create_document(self, authed_client):
        resp = authed_client.post(
            "/plugins/content-studio/api/documents",
            data=json.dumps(
                {
                    "title": "My First Article",
                    "content": "Hello world this is a test document.",
                    "doc_type": "article",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["title"] == "My First Article"
        assert data["id"] is not None
        assert data["word_count"] == 7  # "Hello world this is a test document."
        assert data["status"] == "draft"

    def test_list_documents(self, authed_client):
        authed_client.post(
            "/plugins/content-studio/api/documents",
            data=json.dumps({"title": "List Test Doc"}),
            content_type="application/json",
        )
        resp = authed_client.get("/plugins/content-studio/api/documents")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "documents" in data
        assert data["total"] >= 1
        titles = [d["title"] for d in data["documents"]]
        assert "List Test Doc" in titles

    def test_get_document(self, authed_client):
        create_resp = authed_client.post(
            "/plugins/content-studio/api/documents",
            data=json.dumps({"title": "Single Get Test Doc"}),
            content_type="application/json",
        )
        doc_id = create_resp.get_json()["id"]

        resp = authed_client.get(f"/plugins/content-studio/api/documents/{doc_id}")
        assert resp.status_code == 200
        assert resp.get_json()["title"] == "Single Get Test Doc"

    def test_update_document_recalculates_word_count(self, authed_client):
        create_resp = authed_client.post(
            "/plugins/content-studio/api/documents",
            data=json.dumps({"title": "Update Word Count Test", "content": "one two three"}),
            content_type="application/json",
        )
        doc_id = create_resp.get_json()["id"]
        assert create_resp.get_json()["word_count"] == 3

        resp = authed_client.put(
            f"/plugins/content-studio/api/documents/{doc_id}",
            data=json.dumps({"content": "one two three four five six"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["word_count"] == 6

    def test_publish_document(self, authed_client):
        create_resp = authed_client.post(
            "/plugins/content-studio/api/documents",
            data=json.dumps({"title": "To Be Published"}),
            content_type="application/json",
        )
        doc_id = create_resp.get_json()["id"]

        resp = authed_client.post(
            f"/plugins/content-studio/api/documents/{doc_id}/publish"
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "published"

    def test_export_document_markdown(self, authed_client):
        create_resp = authed_client.post(
            "/plugins/content-studio/api/documents",
            data=json.dumps({"title": "Export Me", "content": "Some content here."}),
            content_type="application/json",
        )
        doc_id = create_resp.get_json()["id"]

        resp = authed_client.get(
            f"/plugins/content-studio/api/documents/{doc_id}/export?format=markdown"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["format"] == "markdown"
        assert data["content"].startswith("# Export Me")
        assert "Some content here." in data["content"]

    def test_get_stats(self, authed_client):
        resp = authed_client.get("/plugins/content-studio/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_documents" in data
        assert "published_count" in data
        assert "draft_count" in data
        assert "total_words" in data
