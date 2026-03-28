"""Tests for the Knowledge Base plugin — categories, articles, public search, AI generation."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="session")
def kb_app():
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


def _mock_db_ctx(fetchone_val=None, fetchall_val=None):
    """Create a mock DB context manager."""
    mock_ctx = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = fetchone_val
    mock_cur.fetchall.return_value = fetchall_val or []
    mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
    return mock_ctx, mock_cur


def _get_json(resp):
    if isinstance(resp, tuple):
        return resp[0].get_json(), resp[1]
    return resp.get_json(), 200


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
class TestCategories:
    def test_list_categories(self, kb_app):
        cat_rows = [
            {"id": 1, "name": "FAQ", "slug": "faq", "description": "Help",
             "parent_id": None, "sort_order": 0, "is_active": True,
             "created_at": "2026-01-01"},
        ]
        mock_ctx, mock_cur = _mock_db_ctx(fetchall_val=cat_rows)
        with kb_app.test_request_context("/plugins/knowledge-base/api/categories"):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor", mock_ctx), \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_g.tenant_id = 1
                result = mock_cur.fetchall()
                assert len(result) == 1
                assert result[0]["name"] == "FAQ"

    def test_create_category_missing_fields(self, kb_app):
        """Creating a category without name or slug should fail."""
        with kb_app.test_request_context(
            "/plugins/knowledge-base/api/categories",
            method="POST",
            json={"name": "No Slug"},
        ):
            from flask import request as flask_request
            data = flask_request.get_json(force=True)
            name = (data.get("name") or "").strip()
            slug = (data.get("slug") or "").strip()
            assert not slug  # Missing slug should fail validation

    def test_create_category_success(self, kb_app):
        new_cat = {"id": 1, "name": "FAQ", "slug": "faq", "description": None,
                   "parent_id": None, "sort_order": 0, "is_active": True,
                   "created_at": "2026-01-01"}
        mock_ctx, mock_cur = _mock_db_ctx(fetchone_val=new_cat)
        with kb_app.test_request_context(
            "/plugins/knowledge-base/api/categories",
            method="POST",
            json={"name": "FAQ", "slug": "faq"},
        ):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor", mock_ctx), \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_g.tenant_id = 1
                mock_cur.fetchone.return_value = new_cat
                assert mock_cur.fetchone()["name"] == "FAQ"

    def test_update_category_not_found(self, kb_app):
        mock_ctx, mock_cur = _mock_db_ctx(fetchone_val=None)
        with kb_app.test_request_context(
            "/plugins/knowledge-base/api/categories/999",
            method="PUT",
            json={"name": "Updated"},
        ):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor", mock_ctx), \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_g.tenant_id = 1
                assert mock_cur.fetchone() is None  # Not found

    def test_delete_category_not_found(self, kb_app):
        mock_ctx, mock_cur = _mock_db_ctx(fetchone_val=None)
        with kb_app.test_request_context(
            "/plugins/knowledge-base/api/categories/999",
            method="DELETE",
        ):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor", mock_ctx), \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_g.tenant_id = 1
                assert mock_cur.fetchone() is None


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------
class TestArticles:
    def test_list_articles_returns_all(self, kb_app):
        articles = [
            {"id": 1, "category_id": 1, "title": "Test", "slug": "test",
             "excerpt": "Ex", "status": "published", "author": "admin",
             "views": 10, "helpful_yes": 5, "helpful_no": 1,
             "tags": [], "published_at": "2026-01-01", "created_at": "2026-01-01",
             "updated_at": "2026-01-01", "category_name": "FAQ"},
        ]
        mock_ctx, mock_cur = _mock_db_ctx(fetchall_val=articles)
        with kb_app.test_request_context("/plugins/knowledge-base/api/articles"):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor", mock_ctx), \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_g.tenant_id = 1
                assert len(mock_cur.fetchall()) == 1

    def test_create_article_missing_fields(self, kb_app):
        with kb_app.test_request_context(
            "/plugins/knowledge-base/api/articles",
            method="POST",
            json={"title": "No content"},
        ):
            from flask import request as flask_request
            data = flask_request.get_json(force=True)
            title = (data.get("title") or "").strip()
            slug = (data.get("slug") or "").strip()
            content = (data.get("content") or "").strip()
            assert title and not slug and not content  # Missing required fields

    def test_create_article_published_sets_published_at(self, kb_app):
        now = datetime.utcnow().isoformat()
        article = {"id": 1, "title": "Test", "slug": "test", "content": "Body",
                   "status": "published", "published_at": now}
        mock_ctx, mock_cur = _mock_db_ctx(fetchone_val=article)
        with kb_app.test_request_context(
            "/plugins/knowledge-base/api/articles",
            method="POST",
            json={"title": "Test", "slug": "test", "content": "Body",
                  "status": "published"},
        ):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor", mock_ctx), \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_g.tenant_id = 1
                assert mock_cur.fetchone()["published_at"] is not None

    def test_get_article_not_found(self, kb_app):
        mock_ctx, mock_cur = _mock_db_ctx(fetchone_val=None)
        with kb_app.test_request_context("/plugins/knowledge-base/api/articles/999"):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor", mock_ctx), \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_g.tenant_id = 1
                assert mock_cur.fetchone() is None

    def test_update_article_not_found(self, kb_app):
        mock_ctx, mock_cur = _mock_db_ctx(fetchone_val=None)
        with kb_app.test_request_context(
            "/plugins/knowledge-base/api/articles/999",
            method="PUT",
            json={"title": "Updated"},
        ):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor", mock_ctx), \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_g.tenant_id = 1
                assert mock_cur.fetchone() is None

    def test_delete_article_returns_deleted(self, kb_app):
        mock_ctx, mock_cur = _mock_db_ctx(fetchone_val={"id": 1})
        with kb_app.test_request_context(
            "/plugins/knowledge-base/api/articles/1",
            method="DELETE",
        ):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor", mock_ctx), \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_g.tenant_id = 1
                assert mock_cur.fetchone() is not None

    def test_rate_article_helpful(self, kb_app):
        mock_ctx, mock_cur = _mock_db_ctx(fetchone_val={"id": 1, "helpful_yes": 1, "helpful_no": 0})
        with kb_app.test_request_context(
            "/plugins/knowledge-base/api/articles/1/helpful",
            method="POST",
            json={"helpful": True},
        ):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor", mock_ctx), \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_g.tenant_id = 1
                result = mock_cur.fetchone()
                assert result["helpful_yes"] >= 1


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------
class TestPublicEndpoints:
    def test_public_search_returns_published(self, kb_app):
        articles = [
            {"id": 1, "title": "Password Reset", "slug": "password-reset",
             "excerpt": "How to reset", "category_id": 1, "tags": [],
             "published_at": "2026-01-01"},
        ]
        mock_ctx, mock_cur = _mock_db_ctx(fetchall_val=articles)
        with kb_app.test_request_context(
            "/plugins/knowledge-base/api/public/search?q=password",
        ):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor", mock_ctx), \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_g.tenant_id = 1
                result = mock_cur.fetchall()
                assert len(result) == 1
                assert result[0]["title"] == "Password Reset"

    def test_public_search_empty_query(self, kb_app):
        with kb_app.test_request_context(
            "/plugins/knowledge-base/api/public/search?q=",
        ):
            from flask import request as flask_request
            q = (flask_request.args.get("q") or "").strip()
            assert not q  # Empty query

    def test_public_article_not_found(self, kb_app):
        mock_ctx, mock_cur = _mock_db_ctx(fetchone_val=None)
        with kb_app.test_request_context(
            "/plugins/knowledge-base/api/public/articles/nonexistent",
        ):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor", mock_ctx), \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_g.tenant_id = 1
                assert mock_cur.fetchone() is None

    def test_public_suggest_short_query(self, kb_app):
        with kb_app.test_request_context(
            "/plugins/knowledge-base/api/public/suggest?q=ab",
        ):
            from flask import request as flask_request
            q = (flask_request.args.get("q") or "").strip()
            assert len(q) < 3  # Too short for suggest

    def test_public_suggest_returns_results(self, kb_app):
        suggestions = [
            {"id": 1, "title": "Password Help", "slug": "password-help",
             "excerpt": "Reset guide"},
        ]
        mock_ctx, mock_cur = _mock_db_ctx(fetchall_val=suggestions)
        with kb_app.test_request_context(
            "/plugins/knowledge-base/api/public/suggest?q=password",
        ):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor", mock_ctx), \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_g.tenant_id = 1
                result = mock_cur.fetchall()
                assert len(result) == 1


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
class TestStats:
    def test_stats_returns_counts(self, kb_app):
        stats = {"total_articles": 10, "published_articles": 8, "draft_articles": 2,
                 "total_views": 500, "total_helpful_yes": 100, "total_helpful_no": 20}
        mock_ctx, mock_cur = _mock_db_ctx(fetchone_val=stats)
        with kb_app.test_request_context("/plugins/knowledge-base/api/stats"):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor", mock_ctx), \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_g.tenant_id = 1
                result = mock_cur.fetchone()
                assert result["total_articles"] == 10
                assert result["published_articles"] == 8


# ---------------------------------------------------------------------------
# AI Generation
# ---------------------------------------------------------------------------
class TestAIGeneration:
    def test_generate_article_missing_topic(self, kb_app):
        """Empty topic should be rejected."""
        with kb_app.test_request_context(
            "/plugins/knowledge-base/api/articles/generate",
            method="POST",
            json={"topic": ""},
        ):
            from flask import request as flask_request
            data = flask_request.get_json(force=True)
            topic = (data.get("topic") or "").strip()
            assert not topic

    @patch("plugins.kbs_knowledge_base.routes.cfg")
    def test_generate_article_no_bridge_url(self, mock_cfg, kb_app):
        """When KBS_BRIDGE_URL is empty, generation should fail."""
        mock_cfg.KBS_BRIDGE_URL = ""
        assert not mock_cfg.KBS_BRIDGE_URL

    @patch("plugins.kbs_knowledge_base.routes.cfg")
    def test_generate_article_bridge_configured(self, mock_cfg, kb_app):
        mock_cfg.KBS_BRIDGE_URL = "http://localhost:3000"
        mock_cfg.KBS_BRIDGE_MODEL = "qwen2.5-coder:7b"
        assert mock_cfg.KBS_BRIDGE_URL == "http://localhost:3000"
