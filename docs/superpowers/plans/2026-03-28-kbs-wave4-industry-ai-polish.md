# KBS Wave 4: Industry Verticals, AI Agents & Polish

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the KBS differentiators -- self-service knowledge bases per tenant, AI-powered agents for each industry vertical, public API access with webhooks for Enterprise clients, and PWA support. All 8 industry plugins already have full CRUD routes and tests; this wave adds the AI and platform polish layers on top.

**Architecture:** A new `kbs_knowledge_base` plugin provides tenant-scoped articles with a public (no-login) read endpoint. A new `core/industry_agents.py` service routes AI questions through the existing KBS Bridge (`KBS_BRIDGE_URL`) with vertical-specific system prompts. Each industry plugin gets a `POST /api/ai/ask` route that delegates to this service. API key management (`core/api_keys.py`) and webhook dispatch (`core/webhook_manager.py`) extend the event bus for Enterprise clients. PWA manifest + service worker enable install-to-homescreen.

**Tech Stack:** Flask, PostgreSQL, psycopg2, requests, hashlib, hmac, pytest

**Existing State:**
| Plugin | Routes (lines) | Tests (lines) | Status |
|--------|----------------|---------------|--------|
| kbs_industry | 838 | 394 | Complete |
| kbs_industry_salon | 672 | 417 | Complete |
| kbs_industry_construction | 665 | 394 | Complete |
| kbs_industry_electrical | 510 | 320 | Complete |
| kbs_industry_plumbing | 596 | 363 | Complete |
| kbs_industry_mechanical | 649 | 417 | Complete |
| kbs_industry_photography | 541 | 277 | Complete |
| kbs_industry_limo | 741 | 294 | Complete |

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `plugins/kbs_knowledge_base/__init__.py` | Plugin blueprint registration |
| Create | `plugins/kbs_knowledge_base/manifest.json` | Plugin manifest |
| Create | `plugins/kbs_knowledge_base/routes.py` | KB article + category CRUD, public search, AI generation |
| Create | `plugins/kbs_knowledge_base/migrations/001_knowledge_base_tables.sql` | kb_articles, kb_categories tables |
| Create | `plugins/kbs_knowledge_base/templates/knowledge_base.html` | KB dashboard template |
| Create | `plugins/kbs_knowledge_base/tests/__init__.py` | Test package |
| Create | `plugins/kbs_knowledge_base/tests/test_knowledge_base.py` | KB CRUD + public search + AI generation tests |
| Create | `core/industry_agents.py` | IndustryAgentService: vertical configs, Bridge dispatch |
| Modify | `plugins/kbs_industry/routes.py` | Add POST /api/ai/ask route |
| Modify | `plugins/kbs_industry_salon/routes.py` | Add POST /api/ai/ask route |
| Modify | `plugins/kbs_industry_construction/routes.py` | Add POST /api/ai/ask route |
| Modify | `plugins/kbs_industry_electrical/routes.py` | Add POST /api/ai/ask route |
| Modify | `plugins/kbs_industry_plumbing/routes.py` | Add POST /api/ai/ask route |
| Modify | `plugins/kbs_industry_mechanical/routes.py` | Add POST /api/ai/ask route |
| Modify | `plugins/kbs_industry_photography/routes.py` | Add POST /api/ai/ask route |
| Modify | `plugins/kbs_industry_limo/routes.py` | Add POST /api/ai/ask route |
| Create | `core/api_keys.py` | API key generation, validation, rate limiting |
| Create | `core/webhook_manager.py` | Webhook registration, event dispatch with HMAC signing |
| Create | `migrations/004_wave4_api_webhooks.sql` | api_keys, tenant_webhooks tables |
| Modify | `core/event_bus.py` | Wire webhook dispatch on emit() |
| Modify | `core/config.py` | Add KBS_BRIDGE_MODEL, KBS_WEBHOOK_TIMEOUT env vars |
| Create | `shared/static/manifest.json` | PWA manifest |
| Create | `shared/static/sw.js` | Service worker for offline caching |
| Modify | `shared/templates/base.html` | Add manifest link + SW registration script |
| Create | `tests/test_knowledge_base.py` | KB plugin integration tests |
| Create | `tests/test_industry_agents.py` | AI agent service tests (mocked Bridge) |
| Create | `tests/test_api_keys.py` | API key generation + validation tests |
| Create | `tests/test_webhooks.py` | Webhook registration + dispatch tests |
| Create | `tests/test_wave4_integration.py` | Full Wave 4 flow integration tests |

---

## Task 1: Knowledge Base Plugin — Migration + Manifest + Blueprint

**Files:**
- Create: `plugins/kbs_knowledge_base/migrations/001_knowledge_base_tables.sql`
- Create: `plugins/kbs_knowledge_base/manifest.json`
- Create: `plugins/kbs_knowledge_base/__init__.py`
- Create: `plugins/kbs_knowledge_base/templates/knowledge_base.html`

- [ ] **Step 1: Create plugin directory structure**

```bash
mkdir -p /mnt/archie_brain/kytran-business-suite/plugins/kbs_knowledge_base/{migrations,templates,tests}
touch /mnt/archie_brain/kytran-business-suite/plugins/kbs_knowledge_base/tests/__init__.py
```

- [ ] **Step 2: Write the migration SQL**

Create `plugins/kbs_knowledge_base/migrations/001_knowledge_base_tables.sql`:

```sql
-- Knowledge Base plugin tables — run inside tenant schema (no tenant_id column needed).
-- All statements are idempotent.

-- ---------------------------------------------------------------------------
-- Article categories
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_categories (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    slug        VARCHAR(255) NOT NULL,
    description TEXT,
    parent_id   INTEGER REFERENCES kb_categories(id) ON DELETE SET NULL,
    sort_order  INTEGER DEFAULT 0,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_categories_slug ON kb_categories (slug);

-- ---------------------------------------------------------------------------
-- Articles
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_articles (
    id            SERIAL PRIMARY KEY,
    category_id   INTEGER REFERENCES kb_categories(id) ON DELETE SET NULL,
    title         VARCHAR(500) NOT NULL,
    slug          VARCHAR(500) NOT NULL,
    content       TEXT NOT NULL,
    excerpt       TEXT,
    status        VARCHAR(20) DEFAULT 'draft'
                      CHECK (status IN ('draft', 'published', 'archived')),
    author        VARCHAR(255),
    views         INTEGER DEFAULT 0,
    helpful_yes   INTEGER DEFAULT 0,
    helpful_no    INTEGER DEFAULT 0,
    tags          JSONB DEFAULT '[]',
    metadata      JSONB DEFAULT '{}',
    published_at  TIMESTAMP,
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_articles_slug   ON kb_articles (slug);
CREATE INDEX IF NOT EXISTS idx_kb_articles_category      ON kb_articles (category_id);
CREATE INDEX IF NOT EXISTS idx_kb_articles_status        ON kb_articles (status);
CREATE INDEX IF NOT EXISTS idx_kb_articles_published     ON kb_articles (published_at);
```

- [ ] **Step 3: Write the manifest.json**

Create `plugins/kbs_knowledge_base/manifest.json`:

```json
{
    "slug": "knowledge-base",
    "name": "Knowledge Base",
    "version": "1.0.0",
    "description": "Self-service knowledge base — articles, categories, public help center, and AI article generation",
    "category": "productivity",
    "tier_required": "business",
    "price_monthly": null,
    "icon": "book-open",
    "dependencies": [],
    "emits": ["article.published", "article.viewed"],
    "consumes": ["ticket.created"],
    "permissions": ["knowledge-base.read", "knowledge-base.write", "knowledge-base.admin"],
    "nav": {"label": "Knowledge Base", "icon": "book-open", "order": 160}
}
```

- [ ] **Step 4: Write the __init__.py**

Create `plugins/kbs_knowledge_base/__init__.py`:

```python
from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "knowledge_base",
        __name__,
        template_folder="templates",
    )
    from plugins.kbs_knowledge_base.routes import register_routes

    register_routes(bp)
    return bp
```

- [ ] **Step 5: Write a minimal dashboard template**

Create `plugins/kbs_knowledge_base/templates/knowledge_base.html`:

```html
{% extends "base.html" %}
{% block title %}Knowledge Base — Kytran Business Suite{% endblock %}
{% block content %}
<div class="kbs-module-container" id="kb-app">
  <h1>Knowledge Base</h1>
  <p>Manage help articles for your customers.</p>
</div>
{% endblock %}
```

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_knowledge_base/
git commit -m "feat(knowledge-base): add plugin scaffold — migration, manifest, blueprint, template"
```

---

## Task 2: Knowledge Base Plugin — Routes

**Files:**
- Create: `plugins/kbs_knowledge_base/routes.py`

- [ ] **Step 1: Write the test file first (TDD)**

Create `plugins/kbs_knowledge_base/tests/test_knowledge_base.py`:

```python
"""Tests for the Knowledge Base plugin — categories, articles, public search, AI generation."""

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
TEST_TENANT_ID = 9920
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "kbtest@example.com"
TEST_PASSWORD = "TestPass123!"

MIGRATION_KB = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_knowledge_base_tables.sql"
)

BASE = "/plugins/knowledge-base"


def post_json(client, path, payload):
    return client.post(
        BASE + path,
        data=json.dumps(payload),
        content_type="application/json",
    )


def put_json(client, path, payload):
    return client.put(
        BASE + path,
        data=json.dumps(payload),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def kb_app():
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def kb_setup(kb_app):
    from werkzeug.security import generate_password_hash

    pw_hash = generate_password_hash(TEST_PASSWORD)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))
        cur.execute(
            "INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (TEST_TENANT_ID, "KB Test Tenant", "kb-test"),
        )
        cur.execute(
            "INSERT INTO users (email, password_hash, tenant_id, is_active) VALUES (%s, %s, %s, TRUE) ON CONFLICT DO NOTHING",
            (TEST_EMAIL, pw_hash, TEST_TENANT_ID),
        )
    create_tenant_schema(TEST_TENANT_ID)
    run_migration_file(TEST_TENANT_ID, MIGRATION_KB)

    # Enable the plugin
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO tenant_plugins (tenant_id, plugin_slug, is_active) VALUES (%s, %s, TRUE) ON CONFLICT DO NOTHING",
            (TEST_TENANT_ID, "knowledge-base"),
        )

    yield TEST_TENANT_ID

    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_plugins WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(kb_app, kb_setup):
    with kb_app.test_client() as client:
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
class TestCategories:
    def test_create_category(self, authed_client):
        resp = post_json(authed_client, "/api/categories", {
            "name": "Getting Started",
            "slug": "getting-started",
            "description": "Introductory articles for new users",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Getting Started"
        assert data["slug"] == "getting-started"
        TestCategories._cat_id = data["id"]

    def test_list_categories(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/categories")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "categories" in data
        assert len(data["categories"]) >= 1

    def test_update_category(self, authed_client):
        resp = put_json(authed_client, f"/api/categories/{TestCategories._cat_id}", {
            "description": "Updated description",
        })
        assert resp.status_code == 200
        assert resp.get_json()["description"] == "Updated description"


class TestArticles:
    def test_create_article(self, authed_client):
        resp = post_json(authed_client, "/api/articles", {
            "title": "How to Create an Invoice",
            "slug": "how-to-create-invoice",
            "content": "Step 1: Go to Invoicing. Step 2: Click New Invoice.",
            "category_id": TestCategories._cat_id,
            "status": "published",
            "tags": ["invoicing", "beginner"],
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["title"] == "How to Create an Invoice"
        assert data["status"] == "published"
        TestArticles._article_id = data["id"]

    def test_list_articles(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/articles")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "articles" in data
        assert data["total"] >= 1

    def test_get_article(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/articles/{TestArticles._article_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["title"] == "How to Create an Invoice"

    def test_update_article(self, authed_client):
        resp = put_json(authed_client, f"/api/articles/{TestArticles._article_id}", {
            "content": "Updated content with more detail.",
        })
        assert resp.status_code == 200
        assert "Updated content" in resp.get_json()["content"]

    def test_delete_article(self, authed_client):
        # Create a throwaway article to delete
        resp = post_json(authed_client, "/api/articles", {
            "title": "Throwaway",
            "slug": "throwaway-delete-me",
            "content": "To be deleted.",
        })
        del_id = resp.get_json()["id"]
        resp = authed_client.delete(f"{BASE}/api/articles/{del_id}")
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] is True


class TestPublicSearch:
    def test_public_search(self, authed_client):
        # Public search doesn't require auth but we use the client for convenience
        resp = authed_client.get(f"{BASE}/api/public/search?q=invoice")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "articles" in data
        assert len(data["articles"]) >= 1
        assert data["articles"][0]["title"] == "How to Create an Invoice"


class TestStats:
    def test_stats(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_articles" in data
        assert "published_articles" in data
```

- [ ] **Step 2: Write the routes implementation**

Create `plugins/kbs_knowledge_base/routes.py`:

```python
"""Knowledge Base plugin routes — categories, articles, public search, AI generation."""

import logging
from datetime import datetime

from flask import g, jsonify, render_template, request
from flask_login import login_required

from core.config import Config
from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)
cfg = Config()


def register_routes(bp):
    """Attach all Knowledge Base routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("knowledge-base")
    def index():
        return render_template("knowledge_base.html")

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    @bp.route("/api/categories", methods=["GET"])
    @login_required
    @require_module("knowledge-base")
    def list_categories():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, slug, description, parent_id, sort_order,
                       is_active, created_at
                FROM kb_categories
                ORDER BY sort_order, name
                """
            )
            categories = cur.fetchall()
        return jsonify({"categories": categories})

    @bp.route("/api/categories", methods=["POST"])
    @login_required
    @require_module("knowledge-base")
    def create_category():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        slug = (data.get("slug") or "").strip()
        if not name or not slug:
            return jsonify({"error": "name and slug are required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO kb_categories (name, slug, description, parent_id, sort_order)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, slug, description, parent_id, sort_order,
                          is_active, created_at
                """,
                (
                    name,
                    slug,
                    data.get("description"),
                    data.get("parent_id"),
                    data.get("sort_order", 0),
                ),
            )
            category = cur.fetchone()
        return jsonify(category), 201

    @bp.route("/api/categories/<int:category_id>", methods=["PUT"])
    @login_required
    @require_module("knowledge-base")
    def update_category(category_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM kb_categories WHERE id = %s", (category_id,))
            if not cur.fetchone():
                return jsonify({"error": "Category not found"}), 404
            cur.execute(
                """
                UPDATE kb_categories SET
                    name        = COALESCE(%s, name),
                    slug        = COALESCE(%s, slug),
                    description = COALESCE(%s, description),
                    parent_id   = COALESCE(%s, parent_id),
                    sort_order  = COALESCE(%s, sort_order),
                    is_active   = COALESCE(%s, is_active)
                WHERE id = %s
                RETURNING id, name, slug, description, parent_id, sort_order,
                          is_active, created_at
                """,
                (
                    data.get("name"),
                    data.get("slug"),
                    data.get("description"),
                    data.get("parent_id"),
                    data.get("sort_order"),
                    data.get("is_active"),
                    category_id,
                ),
            )
            category = cur.fetchone()
        return jsonify(category)

    @bp.route("/api/categories/<int:category_id>", methods=["DELETE"])
    @login_required
    @require_module("knowledge-base")
    def delete_category(category_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "DELETE FROM kb_categories WHERE id = %s RETURNING id",
                (category_id,),
            )
            deleted = cur.fetchone()
        if not deleted:
            return jsonify({"error": "Category not found"}), 404
        return jsonify({"deleted": True, "id": category_id})

    # ------------------------------------------------------------------
    # Articles
    # ------------------------------------------------------------------

    @bp.route("/api/articles", methods=["GET"])
    @login_required
    @require_module("knowledge-base")
    def list_articles():
        status = request.args.get("status")
        category_id = request.args.get("category_id")

        conditions = []
        params = []
        if status:
            conditions.append("a.status = %s")
            params.append(status)
        if category_id:
            conditions.append("a.category_id = %s")
            params.append(int(category_id))

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                SELECT a.id, a.category_id, a.title, a.slug, a.excerpt,
                       a.status, a.author, a.views, a.helpful_yes, a.helpful_no,
                       a.tags, a.published_at, a.created_at, a.updated_at,
                       c.name AS category_name
                FROM kb_articles a
                LEFT JOIN kb_categories c ON c.id = a.category_id
                {where}
                ORDER BY a.updated_at DESC
                """,
                params,
            )
            articles = cur.fetchall()

        return jsonify({"articles": articles, "total": len(articles)})

    @bp.route("/api/articles/<int:article_id>", methods=["GET"])
    @login_required
    @require_module("knowledge-base")
    def get_article(article_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            # Increment view count
            cur.execute(
                "UPDATE kb_articles SET views = views + 1 WHERE id = %s", (article_id,)
            )
            cur.execute(
                """
                SELECT a.id, a.category_id, a.title, a.slug, a.content, a.excerpt,
                       a.status, a.author, a.views, a.helpful_yes, a.helpful_no,
                       a.tags, a.metadata, a.published_at, a.created_at, a.updated_at,
                       c.name AS category_name
                FROM kb_articles a
                LEFT JOIN kb_categories c ON c.id = a.category_id
                WHERE a.id = %s
                """,
                (article_id,),
            )
            article = cur.fetchone()

        if article is None:
            return jsonify({"error": "Article not found"}), 404

        event_bus.emit(
            "article.viewed",
            {"article_id": article_id, "title": article["title"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(article)

    @bp.route("/api/articles", methods=["POST"])
    @login_required
    @require_module("knowledge-base")
    def create_article():
        data = request.get_json(force=True)
        title = (data.get("title") or "").strip()
        slug = (data.get("slug") or "").strip()
        content = (data.get("content") or "").strip()
        if not title or not slug or not content:
            return jsonify({"error": "title, slug, and content are required"}), 400

        status = data.get("status", "draft")
        published_at = datetime.utcnow() if status == "published" else None

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            from psycopg2.extras import Json

            cur.execute(
                """
                INSERT INTO kb_articles
                    (category_id, title, slug, content, excerpt, status, author,
                     tags, metadata, published_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, category_id, title, slug, content, excerpt,
                          status, author, views, helpful_yes, helpful_no,
                          tags, metadata, published_at, created_at, updated_at
                """,
                (
                    data.get("category_id"),
                    title,
                    slug,
                    content,
                    data.get("excerpt"),
                    status,
                    data.get("author"),
                    Json(data.get("tags", [])),
                    Json(data.get("metadata", {})),
                    published_at,
                ),
            )
            article = cur.fetchone()

        if status == "published":
            event_bus.emit(
                "article.published",
                {"article_id": article["id"], "title": article["title"]},
                tenant_id=g.tenant_id,
            )
        return jsonify(article), 201

    @bp.route("/api/articles/<int:article_id>", methods=["PUT"])
    @login_required
    @require_module("knowledge-base")
    def update_article(article_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id, status FROM kb_articles WHERE id = %s", (article_id,))
            existing = cur.fetchone()
            if not existing:
                return jsonify({"error": "Article not found"}), 404

            new_status = data.get("status")
            published_at_clause = ""
            extra_params = []
            if new_status == "published" and existing[1] != "published":
                published_at_clause = ", published_at = NOW()"

            from psycopg2.extras import Json

            cur.execute(
                f"""
                UPDATE kb_articles SET
                    title       = COALESCE(%s, title),
                    slug        = COALESCE(%s, slug),
                    content     = COALESCE(%s, content),
                    excerpt     = COALESCE(%s, excerpt),
                    status      = COALESCE(%s, status),
                    category_id = COALESCE(%s, category_id),
                    author      = COALESCE(%s, author),
                    tags        = COALESCE(%s, tags),
                    updated_at  = NOW()
                    {published_at_clause}
                WHERE id = %s
                RETURNING id, category_id, title, slug, content, excerpt,
                          status, author, views, helpful_yes, helpful_no,
                          tags, metadata, published_at, created_at, updated_at
                """,
                (
                    data.get("title"),
                    data.get("slug"),
                    data.get("content"),
                    data.get("excerpt"),
                    new_status,
                    data.get("category_id"),
                    data.get("author"),
                    Json(data["tags"]) if "tags" in data else None,
                    article_id,
                ),
            )
            article = cur.fetchone()
        return jsonify(article)

    @bp.route("/api/articles/<int:article_id>", methods=["DELETE"])
    @login_required
    @require_module("knowledge-base")
    def delete_article(article_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "DELETE FROM kb_articles WHERE id = %s RETURNING id",
                (article_id,),
            )
            deleted = cur.fetchone()
        if not deleted:
            return jsonify({"error": "Article not found"}), 404
        return jsonify({"deleted": True, "id": article_id})

    @bp.route("/api/articles/<int:article_id>/helpful", methods=["POST"])
    @login_required
    @require_module("knowledge-base")
    def rate_article(article_id):
        data = request.get_json(force=True)
        helpful = data.get("helpful", True)
        col = "helpful_yes" if helpful else "helpful_no"

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"UPDATE kb_articles SET {col} = {col} + 1 WHERE id = %s RETURNING helpful_yes, helpful_no",
                (article_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "Article not found"}), 404
        return jsonify(row)

    # ------------------------------------------------------------------
    # Public endpoints (no login required)
    # ------------------------------------------------------------------

    @bp.route("/api/public/search", methods=["GET"])
    def public_search():
        """Public article search — no login required.

        Requires tenant_id in session (set by tenant middleware from URL).
        Only returns published articles.
        """
        q = (request.args.get("q") or "").strip()
        if not q:
            return jsonify({"articles": [], "total": 0})

        pattern = f"%{q}%"
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, title, slug, excerpt, category_id, tags, published_at
                FROM kb_articles
                WHERE status = 'published'
                  AND (title ILIKE %s OR content ILIKE %s OR excerpt ILIKE %s)
                ORDER BY views DESC
                LIMIT 20
                """,
                (pattern, pattern, pattern),
            )
            articles = cur.fetchall()
        return jsonify({"articles": articles, "total": len(articles)})

    @bp.route("/api/public/articles/<slug>", methods=["GET"])
    def public_article(slug):
        """Read a published article by slug — no login required."""
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "UPDATE kb_articles SET views = views + 1 WHERE slug = %s AND status = 'published'",
                (slug,),
            )
            cur.execute(
                """
                SELECT a.id, a.title, a.slug, a.content, a.excerpt,
                       a.tags, a.published_at, a.views,
                       c.name AS category_name
                FROM kb_articles a
                LEFT JOIN kb_categories c ON c.id = a.category_id
                WHERE a.slug = %s AND a.status = 'published'
                """,
                (slug,),
            )
            article = cur.fetchone()
        if not article:
            return jsonify({"error": "Article not found"}), 404
        return jsonify(article)

    @bp.route("/api/public/suggest", methods=["GET"])
    def public_suggest():
        """Auto-suggest articles for help desk ticket submission."""
        q = (request.args.get("q") or "").strip()
        if len(q) < 3:
            return jsonify({"suggestions": []})

        pattern = f"%{q}%"
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, title, slug, excerpt
                FROM kb_articles
                WHERE status = 'published'
                  AND (title ILIKE %s OR content ILIKE %s)
                ORDER BY views DESC
                LIMIT 5
                """,
                (pattern, pattern),
            )
            suggestions = cur.fetchall()
        return jsonify({"suggestions": suggestions})

    # ------------------------------------------------------------------
    # AI Article Generation
    # ------------------------------------------------------------------

    @bp.route("/api/articles/generate", methods=["POST"])
    @login_required
    @require_module("knowledge-base")
    def generate_article():
        """Generate a knowledge base article using the AI Bridge.

        Request body: {"topic": "...", "category_id": N (optional)}
        """
        import requests as http_requests

        data = request.get_json(force=True)
        topic = (data.get("topic") or "").strip()
        if not topic:
            return jsonify({"error": "topic is required"}), 400

        if not cfg.KBS_BRIDGE_URL:
            return jsonify({"error": "AI Bridge not configured"}), 503

        prompt = (
            f"Write a professional knowledge base article about: {topic}\n\n"
            "Format the article with:\n"
            "- A clear title\n"
            "- A brief 1-2 sentence excerpt/summary\n"
            "- Well-structured content with headers and paragraphs\n"
            "- Practical step-by-step instructions where appropriate\n\n"
            "Return JSON with keys: title, excerpt, content"
        )

        try:
            bridge_resp = http_requests.post(
                f"{cfg.KBS_BRIDGE_URL}/api/bridge",
                json={
                    "prompt": prompt,
                    "model": getattr(cfg, "KBS_BRIDGE_MODEL", "qwen2.5-coder:7b"),
                    "format": "json",
                },
                timeout=60,
            )
            bridge_resp.raise_for_status()
            result = bridge_resp.json()
            ai_text = result.get("response", "{}")

            import json as json_lib

            try:
                parsed = json_lib.loads(ai_text)
            except (json_lib.JSONDecodeError, TypeError):
                parsed = {
                    "title": topic,
                    "excerpt": "",
                    "content": ai_text,
                }

            return jsonify({
                "generated": True,
                "title": parsed.get("title", topic),
                "excerpt": parsed.get("excerpt", ""),
                "content": parsed.get("content", ai_text),
                "category_id": data.get("category_id"),
            })

        except Exception as exc:
            logger.exception("AI article generation failed: %s", exc)
            return jsonify({"error": f"AI generation failed: {str(exc)}"}), 502

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("knowledge-base")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_articles,
                    COUNT(*) FILTER (WHERE status = 'published') AS published_articles,
                    COUNT(*) FILTER (WHERE status = 'draft') AS draft_articles,
                    COALESCE(SUM(views), 0) AS total_views,
                    COALESCE(SUM(helpful_yes), 0) AS total_helpful_yes,
                    COALESCE(SUM(helpful_no), 0) AS total_helpful_no
                FROM kb_articles
                """
            )
            article_stats = cur.fetchone()

            cur.execute("SELECT COUNT(*) AS total_categories FROM kb_categories")
            cat_stats = cur.fetchone()

        return jsonify({
            **article_stats,
            "total_categories": cat_stats["total_categories"],
        })
```

- [ ] **Step 3: Run the tests**

```bash
docker exec kbs_app python -m pytest plugins/kbs_knowledge_base/tests/test_knowledge_base.py -v
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_knowledge_base/
git commit -m "feat(knowledge-base): add routes — categories, articles, public search, AI generation, stats"
```

---

## Task 3: AI Industry Agents Service

**Files:**
- Create: `core/industry_agents.py`
- Create: `tests/test_industry_agents.py`

- [ ] **Step 1: Write the test file first (TDD)**

Create `tests/test_industry_agents.py`:

```python
"""Tests for the Industry Agent Service — vertical AI agents via Bridge dispatch."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("KBS_DB_HOST", "192.168.1.200")
os.environ.setdefault("KBS_DB_NAME", "archie")
os.environ.setdefault("KBS_DB_USER", "archie")
os.environ.setdefault("KBS_DB_PASSWORD", os.getenv("DB_PASSWORD", ""))


class TestAgentConfig:
    def test_get_agent_for_known_vertical(self):
        from core.industry_agents import IndustryAgentService

        agent = IndustryAgentService.get_agent_for_vertical("salon")
        assert agent is not None
        assert "name" in agent
        assert "system_prompt" in agent
        assert "capabilities" in agent

    def test_get_agent_for_unknown_vertical(self):
        from core.industry_agents import IndustryAgentService

        agent = IndustryAgentService.get_agent_for_vertical("nonexistent")
        assert agent is None

    def test_all_verticals_have_configs(self):
        from core.industry_agents import IndustryAgentService

        expected = [
            "industry", "salon", "construction", "electrical",
            "plumbing", "mechanical", "photography", "limo",
        ]
        for slug in expected:
            agent = IndustryAgentService.get_agent_for_vertical(slug)
            assert agent is not None, f"Missing config for vertical: {slug}"
            assert len(agent["system_prompt"]) > 50, f"System prompt too short for: {slug}"


class TestAskAgent:
    @patch("core.industry_agents.requests.post")
    def test_ask_agent_success(self, mock_post):
        from core.industry_agents import IndustryAgentService

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "Based on the booking data, Tuesdays are slowest."}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = IndustryAgentService.ask_agent(
            vertical_slug="salon",
            question="What days are slowest for bookings?",
            context={"bookings_this_week": 12},
            tenant_id=1,
        )
        assert result["success"] is True
        assert "slowest" in result["response"].lower()
        assert mock_post.called

    @patch("core.industry_agents.requests.post")
    def test_ask_agent_bridge_error(self, mock_post):
        from core.industry_agents import IndustryAgentService

        mock_post.side_effect = Exception("Connection refused")

        result = IndustryAgentService.ask_agent(
            vertical_slug="salon",
            question="What products should I restock?",
            context={},
            tenant_id=1,
        )
        assert result["success"] is False
        assert "error" in result

    def test_ask_agent_unknown_vertical(self):
        from core.industry_agents import IndustryAgentService

        result = IndustryAgentService.ask_agent(
            vertical_slug="nonexistent",
            question="Hello?",
            context={},
            tenant_id=1,
        )
        assert result["success"] is False
        assert "Unknown vertical" in result["error"]
```

- [ ] **Step 2: Write the IndustryAgentService**

Create `core/industry_agents.py`:

```python
"""Industry Agent Service — vertical-specific AI agents dispatched through KBS Bridge.

Each industry vertical gets a dedicated AI agent personality with a specialized
system prompt covering domain knowledge, common tasks, and analysis capabilities.
"""

import json
import logging

import requests

from core.config import Config

logger = logging.getLogger(__name__)
cfg = Config()

# ---------------------------------------------------------------------------
# Agent configurations — one per vertical
# ---------------------------------------------------------------------------
AGENT_CONFIGS = {
    "industry": {
        "name": "Industry Advisor",
        "system_prompt": (
            "You are an expert industry business advisor for a trades/service company. "
            "You help with job management, permit tracking, and government opportunity analysis. "
            "You understand construction, electrical, plumbing, mechanical, and general contracting workflows. "
            "Provide practical, actionable advice grounded in real-world trade business operations. "
            "When analyzing data, reference specific numbers and trends."
        ),
        "capabilities": [
            "job_analysis", "permit_tracking", "opportunity_matching",
            "cost_estimation", "scheduling_optimization",
        ],
    },
    "salon": {
        "name": "Salon Business Coach",
        "system_prompt": (
            "You are an expert salon and hairdressing business coach. "
            "You specialize in rebooking strategies, service menu optimization, retail product sales, "
            "marketing for slow days, stylist commission analysis, and client retention. "
            "You understand salon booking patterns, seasonal trends, and product inventory management. "
            "When suggesting improvements, include specific actionable steps with expected revenue impact."
        ),
        "capabilities": [
            "rebooking_suggestions", "service_analysis", "slow_day_marketing",
            "retail_optimization", "stylist_performance", "client_retention",
        ],
    },
    "construction": {
        "name": "Construction Project Analyst",
        "system_prompt": (
            "You are an expert construction project management analyst. "
            "You specialize in permit deadline tracking, RFI response drafting, change order analysis, "
            "material cost estimation, subcontractor evaluation, and inspection preparation. "
            "You understand Canadian building codes, safety regulations, and project scheduling. "
            "Provide specific, data-driven recommendations referencing industry standards."
        ),
        "capabilities": [
            "permit_deadline_alerts", "rfi_responses", "material_cost_estimation",
            "subcontractor_evaluation", "inspection_prep", "schedule_analysis",
        ],
    },
    "electrical": {
        "name": "Electrical Code Analyst",
        "system_prompt": (
            "You are an expert electrical systems analyst with deep knowledge of the Canadian Electrical Code (CEC). "
            "You specialize in code compliance checks, load calculation verification, panel design review, "
            "circuit sizing validation, and material specification. "
            "You understand arc-fault, ground-fault, and dedicated circuit requirements. "
            "Always reference specific CEC sections when providing compliance guidance."
        ),
        "capabilities": [
            "code_compliance_checks", "load_calculation_verification",
            "panel_design_review", "circuit_sizing", "material_specification",
        ],
    },
    "plumbing": {
        "name": "Plumbing Service Advisor",
        "system_prompt": (
            "You are an expert plumbing service business advisor. "
            "You specialize in parts recommendations, service call prioritization, "
            "backflow testing compliance, fixture lifecycle analysis, and inventory optimization. "
            "You understand plumbing codes, water heater regulations, and drainage requirements. "
            "Prioritize safety-critical issues and provide cost-effective solutions."
        ),
        "capabilities": [
            "parts_recommendations", "service_call_prioritization",
            "backflow_compliance", "inventory_optimization", "fixture_lifecycle",
        ],
    },
    "mechanical": {
        "name": "HVAC Systems Engineer",
        "system_prompt": (
            "You are an expert HVAC and mechanical systems engineer. "
            "You specialize in maintenance scheduling optimization, energy efficiency analysis, "
            "system sizing verification, commissioning report review, and equipment lifecycle planning. "
            "You understand ASHRAE standards, energy auditing methodology, and refrigerant regulations. "
            "Provide recommendations with estimated energy savings and payback periods."
        ),
        "capabilities": [
            "maintenance_scheduling", "energy_efficiency_analysis",
            "system_sizing", "commissioning_review", "equipment_lifecycle",
        ],
    },
    "photography": {
        "name": "Photography Business Strategist",
        "system_prompt": (
            "You are an expert photography business strategist. "
            "You specialize in pricing optimization, editing workflow efficiency, "
            "package design, gallery delivery best practices, and booking conversion. "
            "You understand seasonal demand patterns, second-shooter economics, and print markup strategy. "
            "Provide specific pricing recommendations with market comparisons."
        ),
        "capabilities": [
            "pricing_optimization", "editing_workflow", "package_design",
            "booking_conversion", "gallery_strategy",
        ],
    },
    "limo": {
        "name": "Fleet Operations Analyst",
        "system_prompt": (
            "You are an expert limousine and ground transportation fleet operations analyst. "
            "You specialize in route optimization, fleet utilization analysis, driver scheduling, "
            "maintenance cost tracking, dynamic pricing strategy, and booking pattern analysis. "
            "You understand DOT compliance, chauffeur licensing, and vehicle depreciation. "
            "Provide recommendations with estimated cost savings or revenue increase."
        ),
        "capabilities": [
            "route_optimization", "fleet_utilization", "driver_scheduling",
            "maintenance_tracking", "dynamic_pricing", "booking_patterns",
        ],
    },
}


class IndustryAgentService:
    """Stateless service for vertical-specific AI agent interactions."""

    @staticmethod
    def get_agent_for_vertical(vertical_slug: str) -> dict | None:
        """Return the agent configuration for a vertical, or None if unknown."""
        return AGENT_CONFIGS.get(vertical_slug)

    @staticmethod
    def ask_agent(
        vertical_slug: str,
        question: str,
        context: dict,
        tenant_id: int,
    ) -> dict:
        """Ask the vertical's AI agent a question via KBS Bridge.

        Args:
            vertical_slug: One of the vertical keys in AGENT_CONFIGS.
            question: The user's question.
            context: Additional context data (stats, records, etc.).
            tenant_id: Tenant making the request.

        Returns:
            Dict with 'success', 'response' (on success), or 'error' (on failure).
        """
        agent_config = AGENT_CONFIGS.get(vertical_slug)
        if not agent_config:
            return {"success": False, "error": f"Unknown vertical: {vertical_slug}"}

        if not cfg.KBS_BRIDGE_URL:
            return {"success": False, "error": "AI Bridge not configured"}

        system_prompt = agent_config["system_prompt"]
        context_str = json.dumps(context, default=str) if context else "{}"

        full_prompt = (
            f"{system_prompt}\n\n"
            f"--- Context Data ---\n{context_str}\n\n"
            f"--- Question ---\n{question}"
        )

        try:
            resp = requests.post(
                f"{cfg.KBS_BRIDGE_URL}/api/bridge",
                json={
                    "prompt": full_prompt,
                    "model": getattr(cfg, "KBS_BRIDGE_MODEL", "qwen2.5-coder:7b"),
                },
                timeout=60,
            )
            resp.raise_for_status()
            result = resp.json()

            return {
                "success": True,
                "response": result.get("response", ""),
                "agent": agent_config["name"],
                "vertical": vertical_slug,
            }
        except Exception as exc:
            logger.exception(
                "AI agent dispatch failed for vertical=%s tenant=%s: %s",
                vertical_slug,
                tenant_id,
                exc,
            )
            return {"success": False, "error": str(exc)}
```

- [ ] **Step 3: Run the tests**

```bash
docker exec kbs_app python -m pytest tests/test_industry_agents.py -v
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/industry_agents.py tests/test_industry_agents.py
git commit -m "feat(ai-agents): add IndustryAgentService with 8 vertical configs and Bridge dispatch"
```

---

## Task 4: Wire AI Agent Routes into Industry Plugins

**Files:**
- Modify: all 8 industry plugin `routes.py` files

Each industry plugin gets a `POST /api/ai/ask` route that delegates to `IndustryAgentService.ask_agent()`. The pattern is identical across all 8 -- only the `vertical_slug` and `require_module` slug differ.

- [ ] **Step 1: Add AI ask route to kbs_industry (base framework)**

Add to the end of `register_routes(bp)` in `plugins/kbs_industry/routes.py`, before the event consumers section:

```python
    # ------------------------------------------------------------------
    # AI Agent
    # ------------------------------------------------------------------

    @bp.route("/api/ai/ask", methods=["POST"])
    @login_required
    @require_module("industry")
    def ask_ai():
        """Ask the Industry AI agent a question with optional context."""
        from core.industry_agents import IndustryAgentService

        data = request.get_json(force=True)
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"error": "question is required"}), 400

        result = IndustryAgentService.ask_agent(
            vertical_slug="industry",
            question=question,
            context=data.get("context", {}),
            tenant_id=g.tenant_id,
        )
        status_code = 200 if result["success"] else 502
        return jsonify(result), status_code
```

- [ ] **Step 2: Add AI ask route to kbs_industry_salon**

Add to the end of `register_routes(bp)` in `plugins/kbs_industry_salon/routes.py`, before the event consumers section:

```python
    # ------------------------------------------------------------------
    # AI Agent
    # ------------------------------------------------------------------

    @bp.route("/api/ai/ask", methods=["POST"])
    @login_required
    @require_module("industry-salon")
    def ask_ai():
        from core.industry_agents import IndustryAgentService

        data = request.get_json(force=True)
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"error": "question is required"}), 400

        result = IndustryAgentService.ask_agent(
            vertical_slug="salon",
            question=question,
            context=data.get("context", {}),
            tenant_id=g.tenant_id,
        )
        status_code = 200 if result["success"] else 502
        return jsonify(result), status_code
```

- [ ] **Step 3: Add AI ask route to kbs_industry_construction**

Same pattern in `plugins/kbs_industry_construction/routes.py` with `require_module("industry-construction")` and `vertical_slug="construction"`.

```python
    # ------------------------------------------------------------------
    # AI Agent
    # ------------------------------------------------------------------

    @bp.route("/api/ai/ask", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def ask_ai():
        from core.industry_agents import IndustryAgentService

        data = request.get_json(force=True)
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"error": "question is required"}), 400

        result = IndustryAgentService.ask_agent(
            vertical_slug="construction",
            question=question,
            context=data.get("context", {}),
            tenant_id=g.tenant_id,
        )
        status_code = 200 if result["success"] else 502
        return jsonify(result), status_code
```

- [ ] **Step 4: Add AI ask route to kbs_industry_electrical**

Same pattern with `require_module("industry-electrical")` and `vertical_slug="electrical"`.

```python
    # ------------------------------------------------------------------
    # AI Agent
    # ------------------------------------------------------------------

    @bp.route("/api/ai/ask", methods=["POST"])
    @login_required
    @require_module("industry-electrical")
    def ask_ai():
        from core.industry_agents import IndustryAgentService

        data = request.get_json(force=True)
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"error": "question is required"}), 400

        result = IndustryAgentService.ask_agent(
            vertical_slug="electrical",
            question=question,
            context=data.get("context", {}),
            tenant_id=g.tenant_id,
        )
        status_code = 200 if result["success"] else 502
        return jsonify(result), status_code
```

- [ ] **Step 5: Add AI ask route to kbs_industry_plumbing**

Same pattern with `require_module("industry-plumbing")` and `vertical_slug="plumbing"`.

```python
    # ------------------------------------------------------------------
    # AI Agent
    # ------------------------------------------------------------------

    @bp.route("/api/ai/ask", methods=["POST"])
    @login_required
    @require_module("industry-plumbing")
    def ask_ai():
        from core.industry_agents import IndustryAgentService

        data = request.get_json(force=True)
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"error": "question is required"}), 400

        result = IndustryAgentService.ask_agent(
            vertical_slug="plumbing",
            question=question,
            context=data.get("context", {}),
            tenant_id=g.tenant_id,
        )
        status_code = 200 if result["success"] else 502
        return jsonify(result), status_code
```

- [ ] **Step 6: Add AI ask route to kbs_industry_mechanical**

Same pattern with `require_module(MODULE_SLUG)` (already defined as `"industry-mechanical"`) and `vertical_slug="mechanical"`.

```python
    # ------------------------------------------------------------------
    # AI Agent
    # ------------------------------------------------------------------

    @bp.route("/api/ai/ask", methods=["POST"])
    @login_required
    @require_module(MODULE_SLUG)
    def ask_ai():
        from core.industry_agents import IndustryAgentService

        data = request.get_json(force=True)
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"error": "question is required"}), 400

        result = IndustryAgentService.ask_agent(
            vertical_slug="mechanical",
            question=question,
            context=data.get("context", {}),
            tenant_id=g.tenant_id,
        )
        status_code = 200 if result["success"] else 502
        return jsonify(result), status_code
```

- [ ] **Step 7: Add AI ask route to kbs_industry_photography**

Same pattern with `require_module("industry-photography")` and `vertical_slug="photography"`.

```python
    # ------------------------------------------------------------------
    # AI Agent
    # ------------------------------------------------------------------

    @bp.route("/api/ai/ask", methods=["POST"])
    @login_required
    @require_module("industry-photography")
    def ask_ai():
        from core.industry_agents import IndustryAgentService

        data = request.get_json(force=True)
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"error": "question is required"}), 400

        result = IndustryAgentService.ask_agent(
            vertical_slug="photography",
            question=question,
            context=data.get("context", {}),
            tenant_id=g.tenant_id,
        )
        status_code = 200 if result["success"] else 502
        return jsonify(result), status_code
```

- [ ] **Step 8: Add AI ask route to kbs_industry_limo**

Same pattern with `require_module("industry-limo")` and `vertical_slug="limo"`.

```python
    # ------------------------------------------------------------------
    # AI Agent
    # ------------------------------------------------------------------

    @bp.route("/api/ai/ask", methods=["POST"])
    @login_required
    @require_module("industry-limo")
    def ask_ai():
        from core.industry_agents import IndustryAgentService

        data = request.get_json(force=True)
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"error": "question is required"}), 400

        result = IndustryAgentService.ask_agent(
            vertical_slug="limo",
            question=question,
            context=data.get("context", {}),
            tenant_id=g.tenant_id,
        )
        status_code = 200 if result["success"] else 502
        return jsonify(result), status_code
```

- [ ] **Step 9: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_industry/routes.py \
       plugins/kbs_industry_salon/routes.py \
       plugins/kbs_industry_construction/routes.py \
       plugins/kbs_industry_electrical/routes.py \
       plugins/kbs_industry_plumbing/routes.py \
       plugins/kbs_industry_mechanical/routes.py \
       plugins/kbs_industry_photography/routes.py \
       plugins/kbs_industry_limo/routes.py
git commit -m "feat(industry): add POST /api/ai/ask route to all 8 industry plugins"
```

---

## Task 5: API Key Management

**Files:**
- Create: `core/api_keys.py`
- Create: `tests/test_api_keys.py`

- [ ] **Step 1: Write the test file first (TDD)**

Create `tests/test_api_keys.py`:

```python
"""Tests for API key generation, validation, and rate limiting."""

import os
import time

import pytest

os.environ.setdefault("KBS_DB_HOST", "192.168.1.200")
os.environ.setdefault("KBS_DB_NAME", "archie")
os.environ.setdefault("KBS_DB_USER", "archie")
os.environ.setdefault("KBS_DB_PASSWORD", os.getenv("DB_PASSWORD", ""))

from core.database import get_db_cursor


class TestApiKeyGeneration:
    def test_generate_key(self):
        from core.api_keys import generate_api_key

        key_data = generate_api_key(
            tenant_id=1,
            name="Test Key",
            permissions=["read", "write"],
            rate_limit=100,
        )
        assert "key" in key_data
        assert key_data["key"].startswith("kbs_")
        assert len(key_data["key"]) >= 40
        assert key_data["name"] == "Test Key"

    def test_key_is_unique(self):
        from core.api_keys import generate_api_key

        key1 = generate_api_key(tenant_id=1, name="Key A")
        key2 = generate_api_key(tenant_id=1, name="Key B")
        assert key1["key"] != key2["key"]


class TestApiKeyValidation:
    def test_validate_valid_key(self):
        from core.api_keys import generate_api_key, validate_api_key

        key_data = generate_api_key(
            tenant_id=1,
            name="Validate Test",
            permissions=["read"],
        )
        result = validate_api_key(key_data["key"])
        assert result is not None
        assert result["tenant_id"] == 1
        assert result["name"] == "Validate Test"

    def test_validate_invalid_key(self):
        from core.api_keys import validate_api_key

        result = validate_api_key("kbs_invalid_key_doesnt_exist")
        assert result is None

    def test_validate_revoked_key(self):
        from core.api_keys import generate_api_key, revoke_api_key, validate_api_key

        key_data = generate_api_key(tenant_id=1, name="Revoke Test")
        revoke_api_key(key_data["id"])
        result = validate_api_key(key_data["key"])
        assert result is None


class TestRateLimiting:
    def test_check_rate_limit_under_limit(self):
        from core.api_keys import check_rate_limit

        # Fresh key should be under limit
        result = check_rate_limit(key_id=99999, rate_limit=100)
        assert result["allowed"] is True

    def test_check_rate_limit_returns_remaining(self):
        from core.api_keys import check_rate_limit

        result = check_rate_limit(key_id=99998, rate_limit=100)
        assert "remaining" in result
        assert result["remaining"] <= 100
```

- [ ] **Step 2: Write the migration SQL**

Create `migrations/004_wave4_api_webhooks.sql`:

```sql
-- Wave 4: API keys and webhooks — run in public schema.

-- ---------------------------------------------------------------------------
-- API Keys (per-tenant)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_keys (
    id           SERIAL PRIMARY KEY,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key_hash     VARCHAR(128) NOT NULL UNIQUE,
    key_prefix   VARCHAR(12) NOT NULL,
    name         VARCHAR(255) NOT NULL,
    permissions  JSONB DEFAULT '["read"]',
    rate_limit   INTEGER DEFAULT 1000,
    is_active    BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMP,
    created_at   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_tenant   ON api_keys (tenant_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash     ON api_keys (key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_active   ON api_keys (is_active) WHERE is_active = TRUE;

-- Rate limit tracking (sliding window)
CREATE TABLE IF NOT EXISTS api_rate_limits (
    id         SERIAL PRIMARY KEY,
    key_id     INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    window_key VARCHAR(20) NOT NULL,
    count      INTEGER DEFAULT 1,
    UNIQUE (key_id, window_key)
);

-- ---------------------------------------------------------------------------
-- Tenant Webhooks
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_webhooks (
    id         SERIAL PRIMARY KEY,
    tenant_id  INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    url        TEXT NOT NULL,
    events     JSONB NOT NULL DEFAULT '["*"]',
    secret     VARCHAR(128) NOT NULL,
    is_active  BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhooks_tenant ON tenant_webhooks (tenant_id);
CREATE INDEX IF NOT EXISTS idx_webhooks_active ON tenant_webhooks (is_active) WHERE is_active = TRUE;

-- Webhook delivery log
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id           SERIAL PRIMARY KEY,
    webhook_id   INTEGER NOT NULL REFERENCES tenant_webhooks(id) ON DELETE CASCADE,
    event_type   VARCHAR(100) NOT NULL,
    payload      JSONB NOT NULL,
    response_code INTEGER,
    response_body TEXT,
    delivered_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_webhook ON webhook_deliveries (webhook_id);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_date    ON webhook_deliveries (delivered_at);
```

- [ ] **Step 3: Write the api_keys module**

Create `core/api_keys.py`:

```python
"""API key generation, validation, and rate limiting for Enterprise tenants.

Keys are stored as SHA-256 hashes. The raw key is returned only once on creation.
Rate limiting uses a sliding-window counter per minute.
"""

import hashlib
import logging
import secrets
from datetime import datetime

from core.database import get_db_cursor

logger = logging.getLogger(__name__)


def _hash_key(raw_key: str) -> str:
    """SHA-256 hash of the raw API key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key(
    tenant_id: int,
    name: str,
    permissions: list | None = None,
    rate_limit: int = 1000,
) -> dict:
    """Generate a new API key for a tenant.

    Returns:
        Dict with 'id', 'key' (raw, shown once), 'name', 'permissions', 'rate_limit'.
    """
    from psycopg2.extras import Json

    raw_key = f"kbs_{secrets.token_urlsafe(32)}"
    key_hash = _hash_key(raw_key)
    key_prefix = raw_key[:12]
    perms = permissions or ["read"]

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO api_keys (tenant_id, key_hash, key_prefix, name, permissions, rate_limit)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, tenant_id, key_prefix, name, permissions, rate_limit, created_at
            """,
            (tenant_id, key_hash, key_prefix, name, Json(perms), rate_limit),
        )
        row = cur.fetchone()

    return {**row, "key": raw_key}


def validate_api_key(raw_key: str) -> dict | None:
    """Validate an API key. Returns key metadata if valid, None if invalid/revoked."""
    key_hash = _hash_key(raw_key)

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT id, tenant_id, name, permissions, rate_limit
            FROM api_keys
            WHERE key_hash = %s AND is_active = TRUE
            """,
            (key_hash,),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE api_keys SET last_used_at = NOW() WHERE id = %s",
                (row["id"],),
            )
    return row


def revoke_api_key(key_id: int) -> bool:
    """Revoke an API key by setting is_active = FALSE."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE api_keys SET is_active = FALSE WHERE id = %s RETURNING id",
            (key_id,),
        )
        return cur.fetchone() is not None


def list_api_keys(tenant_id: int) -> list:
    """List all API keys for a tenant (prefix only, no raw key)."""
    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT id, key_prefix, name, permissions, rate_limit,
                   is_active, last_used_at, created_at
            FROM api_keys
            WHERE tenant_id = %s
            ORDER BY created_at DESC
            """,
            (tenant_id,),
        )
        return cur.fetchall()


def check_rate_limit(key_id: int, rate_limit: int) -> dict:
    """Check and increment the rate limit counter for this minute.

    Returns:
        Dict with 'allowed' (bool) and 'remaining' (int).
    """
    window_key = datetime.utcnow().strftime("%Y%m%d%H%M")

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO api_rate_limits (key_id, window_key, count)
            VALUES (%s, %s, 1)
            ON CONFLICT (key_id, window_key)
            DO UPDATE SET count = api_rate_limits.count + 1
            RETURNING count
            """,
            (key_id, window_key),
        )
        row = cur.fetchone()
        current_count = row["count"]

    remaining = max(0, rate_limit - current_count)
    return {
        "allowed": current_count <= rate_limit,
        "remaining": remaining,
        "limit": rate_limit,
    }
```

- [ ] **Step 4: Run the tests**

```bash
docker exec kbs_app python -m pytest tests/test_api_keys.py -v
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/api_keys.py migrations/004_wave4_api_webhooks.sql tests/test_api_keys.py
git commit -m "feat(api-keys): add API key generation, validation, rate limiting with migration"
```

---

## Task 6: Webhook Manager

**Files:**
- Create: `core/webhook_manager.py`
- Modify: `core/event_bus.py`
- Create: `tests/test_webhooks.py`

- [ ] **Step 1: Write the test file first (TDD)**

Create `tests/test_webhooks.py`:

```python
"""Tests for webhook registration, dispatch, and HMAC signing."""

import hashlib
import hmac
import json
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("KBS_DB_HOST", "192.168.1.200")
os.environ.setdefault("KBS_DB_NAME", "archie")
os.environ.setdefault("KBS_DB_USER", "archie")
os.environ.setdefault("KBS_DB_PASSWORD", os.getenv("DB_PASSWORD", ""))


class TestWebhookRegistration:
    def test_register_webhook(self):
        from core.webhook_manager import register_webhook

        webhook = register_webhook(
            tenant_id=1,
            url="https://example.com/webhook",
            events=["invoice.created", "invoice.paid"],
        )
        assert webhook["id"] is not None
        assert webhook["url"] == "https://example.com/webhook"
        assert "invoice.created" in webhook["events"]
        assert len(webhook["secret"]) > 20

    def test_list_webhooks(self):
        from core.webhook_manager import list_webhooks, register_webhook

        register_webhook(
            tenant_id=1,
            url="https://example.com/hook2",
            events=["*"],
        )
        hooks = list_webhooks(tenant_id=1)
        assert len(hooks) >= 1

    def test_delete_webhook(self):
        from core.webhook_manager import delete_webhook, register_webhook

        webhook = register_webhook(
            tenant_id=1,
            url="https://example.com/delete-me",
            events=["test.event"],
        )
        result = delete_webhook(webhook["id"], tenant_id=1)
        assert result is True


class TestWebhookDispatch:
    @patch("core.webhook_manager.requests.post")
    def test_dispatch_to_matching_webhook(self, mock_post):
        from core.webhook_manager import dispatch_webhooks, register_webhook

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"
        mock_post.return_value = mock_resp

        webhook = register_webhook(
            tenant_id=1,
            url="https://example.com/dispatch-test",
            events=["order.created"],
        )

        dispatch_webhooks(
            tenant_id=1,
            event_type="order.created",
            payload={"order_id": 42},
        )
        assert mock_post.called

    @patch("core.webhook_manager.requests.post")
    def test_dispatch_wildcard_webhook(self, mock_post):
        from core.webhook_manager import dispatch_webhooks, register_webhook

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"
        mock_post.return_value = mock_resp

        register_webhook(
            tenant_id=1,
            url="https://example.com/wildcard-test",
            events=["*"],
        )

        dispatch_webhooks(
            tenant_id=1,
            event_type="anything.happened",
            payload={"data": "test"},
        )
        assert mock_post.called


class TestHMACSigning:
    def test_signature_header(self):
        from core.webhook_manager import _compute_signature

        payload = json.dumps({"test": True})
        secret = "test_secret_123"
        sig = _compute_signature(payload, secret)
        expected = hmac.new(
            secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        assert sig == expected
```

- [ ] **Step 2: Write the webhook_manager module**

Create `core/webhook_manager.py`:

```python
"""Webhook manager — register tenant webhooks, dispatch events with HMAC signing.

Webhooks are dispatched asynchronously in a background thread to avoid blocking
the event bus. Each delivery is logged to webhook_deliveries for debugging.
"""

import hashlib
import hmac
import json
import logging
import secrets
import threading

import requests

from core.database import get_db_cursor

logger = logging.getLogger(__name__)


def _compute_signature(payload_str: str, secret: str) -> str:
    """Compute HMAC-SHA256 signature for a webhook payload."""
    return hmac.new(secret.encode(), payload_str.encode(), hashlib.sha256).hexdigest()


def register_webhook(
    tenant_id: int,
    url: str,
    events: list,
) -> dict:
    """Register a new webhook for a tenant.

    Returns:
        Dict with webhook metadata including the generated secret.
    """
    from psycopg2.extras import Json

    secret = secrets.token_urlsafe(32)

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO tenant_webhooks (tenant_id, url, events, secret)
            VALUES (%s, %s, %s, %s)
            RETURNING id, tenant_id, url, events, secret, is_active, created_at
            """,
            (tenant_id, url, Json(events), secret),
        )
        webhook = cur.fetchone()
    return webhook


def list_webhooks(tenant_id: int) -> list:
    """List all webhooks for a tenant."""
    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT id, url, events, is_active, created_at
            FROM tenant_webhooks
            WHERE tenant_id = %s
            ORDER BY created_at DESC
            """,
            (tenant_id,),
        )
        return cur.fetchall()


def delete_webhook(webhook_id: int, tenant_id: int) -> bool:
    """Delete a webhook (hard delete)."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM tenant_webhooks WHERE id = %s AND tenant_id = %s RETURNING id",
            (webhook_id, tenant_id),
        )
        return cur.fetchone() is not None


def dispatch_webhooks(tenant_id: int, event_type: str, payload: dict) -> None:
    """Find matching webhooks for a tenant + event and dispatch in background.

    Matches on exact event_type or wildcard ("*").
    """
    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT id, url, events, secret
            FROM tenant_webhooks
            WHERE tenant_id = %s AND is_active = TRUE
            """,
            (tenant_id,),
        )
        webhooks = cur.fetchall()

    for webhook in webhooks:
        events = webhook["events"]
        if "*" in events or event_type in events:
            # Dispatch in background thread to avoid blocking
            thread = threading.Thread(
                target=_deliver_webhook,
                args=(webhook, event_type, payload),
                daemon=True,
            )
            thread.start()


def _deliver_webhook(webhook: dict, event_type: str, payload: dict) -> None:
    """Deliver a single webhook with HMAC signature and log the result."""
    delivery_payload = {
        "event": event_type,
        "data": payload,
    }
    payload_str = json.dumps(delivery_payload, default=str)
    signature = _compute_signature(payload_str, webhook["secret"])

    response_code = None
    response_body = None

    try:
        resp = requests.post(
            webhook["url"],
            data=payload_str,
            headers={
                "Content-Type": "application/json",
                "X-KBS-Signature": signature,
                "X-KBS-Event": event_type,
            },
            timeout=10,
        )
        response_code = resp.status_code
        response_body = resp.text[:1000]
    except Exception as exc:
        logger.warning("Webhook delivery failed for %s: %s", webhook["url"], exc)
        response_code = 0
        response_body = str(exc)[:1000]

    # Log delivery
    try:
        from psycopg2.extras import Json

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO webhook_deliveries
                    (webhook_id, event_type, payload, response_code, response_body)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (webhook["id"], event_type, Json(delivery_payload), response_code, response_body),
            )
    except Exception:
        logger.exception("Failed to log webhook delivery")
```

- [ ] **Step 3: Wire webhook dispatch into event_bus.py**

Read `core/event_bus.py` and add webhook dispatch at the end of the `emit()` method. Add after the handler loop, before the method ends:

```python
        # Dispatch to registered webhooks (if tenant_id is present)
        if tenant_id is not None:
            try:
                from core.webhook_manager import dispatch_webhooks

                dispatch_webhooks(
                    tenant_id=tenant_id,
                    event_type=event_type,
                    payload=data,
                )
            except Exception:
                logger.exception("Webhook dispatch failed for event %r", event_type)
```

- [ ] **Step 4: Run the tests**

```bash
docker exec kbs_app python -m pytest tests/test_webhooks.py -v
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/webhook_manager.py core/event_bus.py tests/test_webhooks.py
git commit -m "feat(webhooks): add webhook manager with HMAC signing, event bus integration"
```

---

## Task 7: API Key + Webhook Settings Routes

**Files:**
- Modify: `core/app.py` (or appropriate route file)
- Create: `core/settings_api_routes.py`

- [ ] **Step 1: Create settings API routes**

Create `core/settings_api_routes.py`:

```python
"""Settings routes for API keys and webhooks — tenant-scoped."""

import logging

from flask import Blueprint, g, jsonify, request
from flask_login import login_required

from core.api_keys import check_rate_limit, generate_api_key, list_api_keys, revoke_api_key
from core.webhook_manager import delete_webhook, list_webhooks, register_webhook

logger = logging.getLogger(__name__)

settings_api_bp = Blueprint("settings_api", __name__, url_prefix="/api/settings")


@settings_api_bp.route("/api-keys", methods=["GET"])
@login_required
def get_api_keys():
    keys = list_api_keys(g.tenant_id)
    return jsonify({"api_keys": keys})


@settings_api_bp.route("/api-keys", methods=["POST"])
@login_required
def create_api_key():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    key_data = generate_api_key(
        tenant_id=g.tenant_id,
        name=name,
        permissions=data.get("permissions", ["read"]),
        rate_limit=data.get("rate_limit", 1000),
    )
    return jsonify(key_data), 201


@settings_api_bp.route("/api-keys/<int:key_id>/revoke", methods=["POST"])
@login_required
def revoke_key(key_id):
    # Verify the key belongs to this tenant
    keys = list_api_keys(g.tenant_id)
    if not any(k["id"] == key_id for k in keys):
        return jsonify({"error": "Key not found"}), 404

    revoke_api_key(key_id)
    return jsonify({"revoked": True, "id": key_id})


@settings_api_bp.route("/webhooks", methods=["GET"])
@login_required
def get_webhooks():
    hooks = list_webhooks(g.tenant_id)
    return jsonify({"webhooks": hooks})


@settings_api_bp.route("/webhooks", methods=["POST"])
@login_required
def create_webhook():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    events = data.get("events", ["*"])
    if not url:
        return jsonify({"error": "url is required"}), 400

    webhook = register_webhook(
        tenant_id=g.tenant_id,
        url=url,
        events=events,
    )
    return jsonify(webhook), 201


@settings_api_bp.route("/webhooks/<int:webhook_id>", methods=["DELETE"])
@login_required
def remove_webhook(webhook_id):
    result = delete_webhook(webhook_id, tenant_id=g.tenant_id)
    if not result:
        return jsonify({"error": "Webhook not found"}), 404
    return jsonify({"deleted": True, "id": webhook_id})
```

- [ ] **Step 2: Register the blueprint in app.py**

Read `core/app.py` and find where other blueprints are registered. Add:

```python
    from core.settings_api_routes import settings_api_bp
    app.register_blueprint(settings_api_bp)
```

- [ ] **Step 3: Run the migration**

```bash
docker exec kbs_app python -c "
from core.database import get_db_cursor
with get_db_cursor(commit=True) as (conn, cur):
    with open('migrations/004_wave4_api_webhooks.sql') as f:
        cur.execute(f.read())
print('Migration applied successfully')
"
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/settings_api_routes.py core/app.py
git commit -m "feat(settings): add API key + webhook management routes"
```

---

## Task 8: PWA Support — Manifest + Service Worker

**Files:**
- Create: `shared/static/manifest.json`
- Create: `shared/static/sw.js`
- Modify: `shared/templates/base.html`

- [ ] **Step 1: Create PWA manifest**

Create `shared/static/manifest.json`:

```json
{
    "name": "Kytran Business Suite",
    "short_name": "KBS",
    "description": "All-in-one business management platform",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#0d0d1a",
    "theme_color": "#00e5ff",
    "orientation": "any",
    "icons": [
        {
            "src": "/static/icons/icon-192.png",
            "sizes": "192x192",
            "type": "image/png"
        },
        {
            "src": "/static/icons/icon-512.png",
            "sizes": "512x512",
            "type": "image/png"
        }
    ]
}
```

- [ ] **Step 2: Create service worker**

Create `shared/static/sw.js`:

```javascript
/* KBS Service Worker — offline caching for static assets. */

const CACHE_NAME = "kbs-v1";
const STATIC_ASSETS = [
    "/static/lcars.css",
    "/static/manifest.json",
];

/* Install — pre-cache critical static assets */
self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

/* Activate — clean old caches */
self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(
                keys
                    .filter((key) => key !== CACHE_NAME)
                    .map((key) => caches.delete(key))
            )
        )
    );
    self.clients.claim();
});

/* Fetch — network-first for API, cache-first for static */
self.addEventListener("fetch", (event) => {
    const url = new URL(event.request.url);

    /* Always go to network for API calls and auth */
    if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/auth/")) {
        return;
    }

    /* Cache-first for static assets */
    if (url.pathname.startsWith("/static/")) {
        event.respondWith(
            caches.match(event.request).then(
                (cached) => cached || fetch(event.request).then((resp) => {
                    const clone = resp.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
                    return resp;
                })
            )
        );
        return;
    }

    /* Network-first for everything else */
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request))
    );
});
```

- [ ] **Step 3: Update base.html to include manifest and SW registration**

Read `shared/templates/base.html`. Add to `<head>` section (after the existing `<meta>` tags):

```html
  <link rel="manifest" href="{{ url_for('static', filename='manifest.json') }}" />
  <meta name="theme-color" content="#00e5ff" />
```

Add before `</body>`:

```html
  <script>
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/static/sw.js").catch(function(err) {
        console.log("SW registration failed:", err);
      });
    }
  </script>
```

- [ ] **Step 4: Create placeholder icons directory**

```bash
mkdir -p /mnt/archie_brain/kytran-business-suite/shared/static/icons
# Create a simple placeholder (replace with real icons later)
echo "placeholder" > /mnt/archie_brain/kytran-business-suite/shared/static/icons/.gitkeep
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add shared/static/manifest.json shared/static/sw.js shared/static/icons/.gitkeep shared/templates/base.html
git commit -m "feat(pwa): add PWA manifest, service worker, and base.html integration"
```

---

## Task 9: Config Updates

**Files:**
- Modify: `core/config.py`

- [ ] **Step 1: Add Wave 4 config vars**

Read `core/config.py` and add after the existing Bridge config line (line ~27):

```python
        self.KBS_BRIDGE_MODEL = os.getenv("KBS_BRIDGE_MODEL", "qwen2.5-coder:7b")
        self.KBS_WEBHOOK_TIMEOUT = int(os.getenv("KBS_WEBHOOK_TIMEOUT", "10"))
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/config.py
git commit -m "feat(config): add KBS_BRIDGE_MODEL and KBS_WEBHOOK_TIMEOUT env vars"
```

---

## Task 10: Integration Tests

**Files:**
- Create: `tests/test_wave4_integration.py`

- [ ] **Step 1: Write the integration test file**

Create `tests/test_wave4_integration.py`:

```python
"""Wave 4 integration tests — knowledge base, AI agents, API keys, webhooks."""

import json
import os
from unittest.mock import MagicMock, patch

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

TEST_TENANT_ID = 9930
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "wave4test@example.com"
TEST_PASSWORD = "TestPass123!"

MIGRATION_KB = os.path.join(
    os.path.dirname(__file__), "..", "plugins", "kbs_knowledge_base",
    "migrations", "001_knowledge_base_tables.sql"
)
MIGRATION_API = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "004_wave4_api_webhooks.sql"
)


@pytest.fixture(scope="module")
def wave4_app():
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def wave4_setup(wave4_app):
    from werkzeug.security import generate_password_hash

    pw_hash = generate_password_hash(TEST_PASSWORD)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))
        cur.execute(
            "INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (TEST_TENANT_ID, "Wave4 Test", "wave4-test"),
        )
        cur.execute(
            "INSERT INTO users (email, password_hash, tenant_id, is_active) VALUES (%s, %s, %s, TRUE) ON CONFLICT DO NOTHING",
            (TEST_EMAIL, pw_hash, TEST_TENANT_ID),
        )
        # Run public schema migration
        with open(MIGRATION_API) as f:
            cur.execute(f.read())

    create_tenant_schema(TEST_TENANT_ID)
    run_migration_file(TEST_TENANT_ID, MIGRATION_KB)

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO tenant_plugins (tenant_id, plugin_slug, is_active) VALUES (%s, %s, TRUE) ON CONFLICT DO NOTHING",
            (TEST_TENANT_ID, "knowledge-base"),
        )

    yield TEST_TENANT_ID

    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM webhook_deliveries WHERE webhook_id IN (SELECT id FROM tenant_webhooks WHERE tenant_id = %s)", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM api_rate_limits WHERE key_id IN (SELECT id FROM api_keys WHERE tenant_id = %s)", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM api_keys WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_webhooks WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_plugins WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(wave4_app, wave4_setup):
    with wave4_app.test_client() as client:
        resp = client.post(
            "/auth/login",
            data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)
        yield client


class TestKnowledgeBaseFlow:
    """End-to-end: create category -> create article -> public search."""

    def test_full_kb_flow(self, authed_client):
        # Create category
        resp = authed_client.post(
            "/plugins/knowledge-base/api/categories",
            data=json.dumps({"name": "FAQ", "slug": "faq", "description": "Frequently asked questions"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        cat_id = resp.get_json()["id"]

        # Create published article
        resp = authed_client.post(
            "/plugins/knowledge-base/api/articles",
            data=json.dumps({
                "title": "How to Reset Password",
                "slug": "reset-password",
                "content": "Go to Settings > Security > Reset Password.",
                "category_id": cat_id,
                "status": "published",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201

        # Public search
        resp = authed_client.get("/plugins/knowledge-base/api/public/search?q=password")
        assert resp.status_code == 200
        results = resp.get_json()
        assert len(results["articles"]) >= 1


class TestAIAgentFlow:
    """AI agent ask flow with mocked Bridge."""

    @patch("core.industry_agents.requests.post")
    def test_agent_ask_via_service(self, mock_post):
        from core.industry_agents import IndustryAgentService

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "Consider offering Tuesday discounts."}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = IndustryAgentService.ask_agent(
            vertical_slug="salon",
            question="How can I fill slow Tuesdays?",
            context={"avg_tuesday_bookings": 3, "avg_saturday_bookings": 15},
            tenant_id=TEST_TENANT_ID,
        )
        assert result["success"] is True
        assert result["agent"] == "Salon Business Coach"


class TestAPIKeyFlow:
    """API key generation -> validation -> revocation."""

    def test_full_api_key_lifecycle(self):
        from core.api_keys import generate_api_key, revoke_api_key, validate_api_key

        # Generate
        key = generate_api_key(tenant_id=TEST_TENANT_ID, name="Integration Test Key")
        assert key["key"].startswith("kbs_")

        # Validate
        valid = validate_api_key(key["key"])
        assert valid is not None
        assert valid["tenant_id"] == TEST_TENANT_ID

        # Revoke
        revoke_api_key(key["id"])
        invalid = validate_api_key(key["key"])
        assert invalid is None


class TestWebhookFlow:
    """Webhook registration -> dispatch -> delivery."""

    @patch("core.webhook_manager.requests.post")
    def test_full_webhook_lifecycle(self, mock_post):
        from core.webhook_manager import delete_webhook, dispatch_webhooks, register_webhook

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"
        mock_post.return_value = mock_resp

        # Register
        hook = register_webhook(
            tenant_id=TEST_TENANT_ID,
            url="https://example.com/integration-test",
            events=["test.event"],
        )
        assert hook["id"] is not None

        # Dispatch
        dispatch_webhooks(
            tenant_id=TEST_TENANT_ID,
            event_type="test.event",
            payload={"integration": True},
        )

        # Give background thread a moment
        import time
        time.sleep(0.5)

        assert mock_post.called

        # Cleanup
        delete_webhook(hook["id"], tenant_id=TEST_TENANT_ID)
```

- [ ] **Step 2: Run all Wave 4 tests**

```bash
docker exec kbs_app python -m pytest \
    plugins/kbs_knowledge_base/tests/test_knowledge_base.py \
    tests/test_industry_agents.py \
    tests/test_api_keys.py \
    tests/test_webhooks.py \
    tests/test_wave4_integration.py \
    -v
```

- [ ] **Step 3: Run the full test suite**

```bash
docker exec kbs_app python -m pytest -v --tb=short 2>&1 | tail -30
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add tests/test_wave4_integration.py
git commit -m "test(wave4): add integration tests for KB, AI agents, API keys, webhooks"
```

---

## Summary

| Task | What | New Files | Modified Files |
|------|------|-----------|---------------|
| 1 | Knowledge Base scaffold | 5 | 0 |
| 2 | Knowledge Base routes + tests | 2 | 0 |
| 3 | AI Industry Agents service | 2 | 0 |
| 4 | Wire AI routes into 8 plugins | 0 | 8 |
| 5 | API key management | 3 | 0 |
| 6 | Webhook manager + event bus | 2 | 1 |
| 7 | Settings API routes | 1 | 1 |
| 8 | PWA manifest + service worker | 3 | 1 |
| 9 | Config updates | 0 | 1 |
| 10 | Integration tests | 1 | 0 |
| **Total** | | **19 new** | **12 modified** |

**Test command (all Wave 4):**
```bash
docker exec kbs_app python -m pytest \
    plugins/kbs_knowledge_base/tests/ \
    tests/test_industry_agents.py \
    tests/test_api_keys.py \
    tests/test_webhooks.py \
    tests/test_wave4_integration.py \
    -v
```

**Estimated commits:** 10 (one per task)
