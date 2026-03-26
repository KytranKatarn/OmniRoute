"""Tests for the Social Media plugin — accounts, posts, campaigns, analytics."""

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

TEST_TENANT_ID = 9903
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "smtest@example.com"
TEST_PASSWORD = "TestPass123!"
CRM_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "kbs_crm", "migrations", "001_crm_tables.sql"
)
SM_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_social_media_tables.sql"
)


@pytest.fixture(scope="module")
def sm_app():
    """Create the Flask app with social-media + crm plugins loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def sm_setup(sm_app):
    """Create test tenant, user, schema, tables, and enable required modules.

    Yields a dict with tenant_id and user_id. Cleans up afterwards.
    """
    from werkzeug.security import generate_password_hash

    pw_hash = generate_password_hash(TEST_PASSWORD)

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        # Clean up any leftovers from a previous failed run
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))

        # Create user
        cur.execute(
            """
            INSERT INTO users (email, username, password_hash, is_active)
            VALUES (%s, 'SM Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        # Create tenant
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'SM Test Tenant', 'sm-test-tenant', 'business', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        # Link user to tenant
        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        # Enable crm module (dependency)
        cur.execute(
            """
            INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
            VALUES (%s, 'crm', TRUE)
            ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
            """,
            (TEST_TENANT_ID,),
        )

        # Enable social-media module
        cur.execute(
            """
            INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
            VALUES (%s, 'social-media', TRUE)
            ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
            """,
            (TEST_TENANT_ID,),
        )

    # Create tenant schema and run migrations
    create_tenant_schema(TEST_TENANT_ID)
    run_migration_file(CRM_MIGRATION_PATH, schema=TEST_SCHEMA)
    run_migration_file(SM_MIGRATION_PATH, schema=TEST_SCHEMA)

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(sm_app, sm_setup):
    """Yield a test client that is logged in and has the tenant session set."""
    with sm_app.test_client() as client:
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


class TestSocialAccounts:
    def test_create_account(self, authed_client):
        resp = authed_client.post(
            "/plugins/social-media/api/accounts",
            data=json.dumps({"platform": "instagram", "account_name": "@testbrand"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["platform"] == "instagram"
        assert data["account_name"] == "@testbrand"
        assert data["id"] is not None

    def test_list_accounts(self, authed_client):
        # Ensure at least one account exists
        authed_client.post(
            "/plugins/social-media/api/accounts",
            data=json.dumps({"platform": "twitter", "account_name": "@listtest"}),
            content_type="application/json",
        )
        resp = authed_client.get("/plugins/social-media/api/accounts")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "accounts" in data
        assert len(data["accounts"]) >= 1


class TestSocialPosts:
    def test_create_post(self, authed_client):
        resp = authed_client.post(
            "/plugins/social-media/api/posts",
            data=json.dumps({"content": "Hello from KBS Social Media!"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["content"] == "Hello from KBS Social Media!"
        assert data["status"] == "draft"
        assert data["id"] is not None

    def test_list_posts(self, authed_client):
        authed_client.post(
            "/plugins/social-media/api/posts",
            data=json.dumps({"content": "A post for listing"}),
            content_type="application/json",
        )
        resp = authed_client.get("/plugins/social-media/api/posts")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "posts" in data
        assert data["total"] >= 1

    def test_schedule_post(self, authed_client):
        create_resp = authed_client.post(
            "/plugins/social-media/api/posts",
            data=json.dumps({"content": "Scheduled post content"}),
            content_type="application/json",
        )
        post_id = create_resp.get_json()["id"]

        resp = authed_client.post(
            f"/plugins/social-media/api/posts/{post_id}/schedule",
            data=json.dumps({"scheduled_at": "2026-04-01T12:00:00"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "scheduled"

    def test_publish_post(self, authed_client):
        create_resp = authed_client.post(
            "/plugins/social-media/api/posts",
            data=json.dumps({"content": "Post to publish now"}),
            content_type="application/json",
        )
        post_id = create_resp.get_json()["id"]

        resp = authed_client.post(
            f"/plugins/social-media/api/posts/{post_id}/publish",
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "published"
        assert data["published_at"] is not None


class TestSocialCampaigns:
    def test_create_campaign(self, authed_client):
        resp = authed_client.post(
            "/plugins/social-media/api/campaigns",
            data=json.dumps({"name": "Spring Launch", "description": "Spring 2026 product launch"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Spring Launch"
        assert data["status"] == "draft"
        assert data["id"] is not None

    def test_add_post_to_campaign(self, authed_client):
        campaign_resp = authed_client.post(
            "/plugins/social-media/api/campaigns",
            data=json.dumps({"name": "Campaign With Posts"}),
            content_type="application/json",
        )
        campaign_id = campaign_resp.get_json()["id"]

        post_resp = authed_client.post(
            "/plugins/social-media/api/posts",
            data=json.dumps({"content": "Campaign post content"}),
            content_type="application/json",
        )
        post_id = post_resp.get_json()["id"]

        resp = authed_client.post(
            f"/plugins/social-media/api/campaigns/{campaign_id}/posts",
            data=json.dumps({"post_id": post_id}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["campaign_id"] == campaign_id
        assert data["post_id"] == post_id

    def test_start_campaign(self, authed_client):
        campaign_resp = authed_client.post(
            "/plugins/social-media/api/campaigns",
            data=json.dumps({"name": "Campaign To Start"}),
            content_type="application/json",
        )
        campaign_id = campaign_resp.get_json()["id"]

        resp = authed_client.post(
            f"/plugins/social-media/api/campaigns/{campaign_id}/start",
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "active"


class TestSocialStats:
    def test_stats(self, authed_client):
        resp = authed_client.get("/plugins/social-media/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_accounts" in data
        assert "total_posts" in data
        assert "scheduled_posts" in data
        assert "active_campaigns" in data
