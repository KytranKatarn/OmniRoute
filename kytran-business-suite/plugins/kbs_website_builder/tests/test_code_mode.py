"""Tests for Website Builder Code Mode — file CRUD, upload, preview assembly."""

import io
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

TEST_TENANT_ID = 9905
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "cmtest@example.com"
TEST_PASSWORD = "TestPass123!"

_MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "migrations")
_MIGRATION_FILES = [
    os.path.join(_MIGRATIONS_DIR, "001_website_builder_tables.sql"),
    os.path.join(_MIGRATIONS_DIR, "002_website_templates.sql"),
    os.path.join(_MIGRATIONS_DIR, "003_chat_history.sql"),
    os.path.join(_MIGRATIONS_DIR, "004_archie_templates.sql"),
    os.path.join(_MIGRATIONS_DIR, "005_code_mode.sql"),
]

BASE = "/plugins/website-builder"


@pytest.fixture(scope="module")
def cm_app():
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def cm_setup(cm_app):
    """Create test tenant, user, schema, run all 5 migrations, create test project."""
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
            VALUES (%s, 'CM Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'CM Test Tenant', 'cm-test-tenant', 'business', TRUE)
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
    for migration in _MIGRATION_FILES:
        run_migration_file(migration, schema=TEST_SCHEMA)

    # Create a test project in the tenant schema
    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, TEST_TENANT_ID)
        cur.execute(
            """
            INSERT INTO website_projects (name, status)
            VALUES ('Code Mode Test Project', 'draft')
            RETURNING id
            """,
        )
        project_id = cur.fetchone()["id"]

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id, "project_id": project_id}

    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(cm_app, cm_setup):
    """Yield a logged-in test client."""
    with cm_app.test_client() as client:
        resp = client.post(
            "/auth/login",
            data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200), f"Login failed: {resp.status_code}"
        yield client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCodeMode:
    def test_get_mode_default_visual(self, authed_client, cm_setup):
        pid = cm_setup["project_id"]
        resp = authed_client.get(f"{BASE}/api/projects/{pid}/mode")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["editor_mode"] == "visual"

    def test_enter_code_mode(self, authed_client, cm_setup):
        pid = cm_setup["project_id"]
        resp = authed_client.post(f"{BASE}/api/projects/{pid}/enter-code-mode")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["editor_mode"] == "code"
        assert data["files_created"] >= 1

    def test_list_files(self, authed_client, cm_setup):
        pid = cm_setup["project_id"]
        resp = authed_client.get(f"{BASE}/api/projects/{pid}/files")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "files" in data
        assert data["total"] >= 1

    def test_create_file(self, authed_client, cm_setup):
        pid = cm_setup["project_id"]
        resp = authed_client.post(
            f"{BASE}/api/projects/{pid}/files",
            data=json.dumps({"path": "about.html", "filename": "about.html", "content": "<h1>About</h1>", "mime_type": "text/html"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["path"] == "about.html"
        assert data["filename"] == "about.html"

    def test_create_directory(self, authed_client, cm_setup):
        pid = cm_setup["project_id"]
        resp = authed_client.post(
            f"{BASE}/api/projects/{pid}/files",
            data=json.dumps({"path": "assets/", "filename": "assets", "is_directory": True}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["is_directory"] is True

    def test_get_file_content(self, authed_client, cm_setup):
        pid = cm_setup["project_id"]
        # Create a file to retrieve
        create_resp = authed_client.post(
            f"{BASE}/api/projects/{pid}/files",
            data=json.dumps({"path": "contact.html", "filename": "contact.html", "content": "<h1>Contact</h1>"}),
            content_type="application/json",
        )
        assert create_resp.status_code == 201
        file_id = create_resp.get_json()["id"]

        resp = authed_client.get(f"{BASE}/api/projects/{pid}/files/{file_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["content"] == "<h1>Contact</h1>"

    def test_update_file(self, authed_client, cm_setup):
        pid = cm_setup["project_id"]
        create_resp = authed_client.post(
            f"{BASE}/api/projects/{pid}/files",
            data=json.dumps({"path": "editable.html", "filename": "editable.html", "content": "original"}),
            content_type="application/json",
        )
        assert create_resp.status_code == 201
        file_id = create_resp.get_json()["id"]

        resp = authed_client.put(
            f"{BASE}/api/projects/{pid}/files/{file_id}",
            data=json.dumps({"content": "updated content"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["content"] == "updated content"

    def test_rename_file(self, authed_client, cm_setup):
        pid = cm_setup["project_id"]
        create_resp = authed_client.post(
            f"{BASE}/api/projects/{pid}/files",
            data=json.dumps({"path": "old-name.html", "filename": "old-name.html", "content": ""}),
            content_type="application/json",
        )
        assert create_resp.status_code == 201
        file_id = create_resp.get_json()["id"]

        resp = authed_client.patch(
            f"{BASE}/api/projects/{pid}/files/{file_id}",
            data=json.dumps({"path": "new-name.html", "filename": "new-name.html"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["path"] == "new-name.html"
        assert data["filename"] == "new-name.html"

    def test_delete_file(self, authed_client, cm_setup):
        pid = cm_setup["project_id"]
        # Create a standalone project so deletion can empty it
        proj_resp = authed_client.post(
            f"{BASE}/api/projects",
            data=json.dumps({"name": "Delete Test Project"}),
            content_type="application/json",
        )
        assert proj_resp.status_code == 201
        del_pid = proj_resp.get_json()["id"]

        # Enter code mode (seeds files)
        authed_client.post(f"{BASE}/api/projects/{del_pid}/enter-code-mode")

        # List files and delete the first one
        list_resp = authed_client.get(f"{BASE}/api/projects/{del_pid}/files")
        files = list_resp.get_json()["files"]
        assert len(files) > 0
        fid = files[0]["id"]

        resp = authed_client.delete(f"{BASE}/api/projects/{del_pid}/files/{fid}")
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] is True

    def test_create_duplicate_path_fails(self, authed_client, cm_setup):
        pid = cm_setup["project_id"]
        payload = json.dumps({"path": "duplicate.html", "filename": "duplicate.html", "content": "first"})
        r1 = authed_client.post(f"{BASE}/api/projects/{pid}/files", data=payload, content_type="application/json")
        assert r1.status_code == 201

        r2 = authed_client.post(f"{BASE}/api/projects/{pid}/files", data=payload, content_type="application/json")
        assert r2.status_code == 409

    def test_file_size_limit(self, authed_client, cm_setup):
        pid = cm_setup["project_id"]
        big_content = "x" * (5 * 1024 * 1024 + 1)
        resp = authed_client.post(
            f"{BASE}/api/projects/{pid}/files",
            data=json.dumps({"path": "huge.txt", "filename": "huge.txt", "content": big_content}),
            content_type="application/json",
        )
        assert resp.status_code == 413

    def test_preview_assembly(self, authed_client, cm_setup):
        pid = cm_setup["project_id"]
        # The project already entered code mode and has index.html from boilerplate
        resp = authed_client.get(f"{BASE}/api/projects/{pid}/preview")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert "<html" in body.lower()
