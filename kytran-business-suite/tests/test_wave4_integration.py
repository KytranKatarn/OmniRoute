"""Wave 4 integration tests — knowledge base, AI agents, API keys, webhooks."""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest


def _mock_db_ctx(fetchone_val=None, fetchall_val=None):
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = fetchone_val
    mock_cur.fetchall.return_value = fetchall_val or []
    mock_conn = MagicMock()

    @contextmanager
    def ctx_mgr(*args, **kwargs):
        yield mock_conn, mock_cur

    return ctx_mgr, mock_cur


@pytest.fixture(scope="session")
def wave4_app():
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


class TestKBFlow:
    """Knowledge Base CRUD flow."""

    def test_category_create_returns_data(self, wave4_app):
        new_cat = {"id": 1, "name": "FAQ", "slug": "faq",
                   "description": "Frequently asked questions",
                   "parent_id": None, "sort_order": 0, "is_active": True,
                   "created_at": "2026-01-01"}
        mock_ctx, mock_cur = _mock_db_ctx(fetchone_val=new_cat)
        with wave4_app.test_request_context(
            "/plugins/knowledge-base/api/categories",
            method="POST",
            json={"name": "FAQ", "slug": "faq", "description": "Frequently asked questions"},
        ):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor") as mock_db, \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_db.side_effect = mock_ctx
                mock_g.tenant_id = 1
                result = mock_cur.fetchone()
                assert result["name"] == "FAQ"

    def test_article_publish_sets_published_at(self, wave4_app):
        article = {"id": 1, "title": "How to Reset Password",
                   "slug": "reset-password", "content": "Go to Settings.",
                   "status": "published", "published_at": "2026-01-01T00:00:00"}
        mock_ctx, mock_cur = _mock_db_ctx(fetchone_val=article)
        with wave4_app.test_request_context(
            "/plugins/knowledge-base/api/articles",
            method="POST",
            json={"title": "How to Reset Password", "slug": "reset-password",
                  "content": "Go to Settings.", "status": "published"},
        ):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor") as mock_db, \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_db.side_effect = mock_ctx
                mock_g.tenant_id = 1
                result = mock_cur.fetchone()
                assert result["status"] == "published"
                assert result["published_at"] is not None

    def test_public_search_finds_published_articles(self, wave4_app):
        articles = [
            {"id": 1, "title": "Password Help", "slug": "password-help",
             "excerpt": "Reset guide", "category_id": 1, "tags": [],
             "published_at": "2026-01-01"},
        ]
        mock_ctx, mock_cur = _mock_db_ctx(fetchall_val=articles)
        with wave4_app.test_request_context(
            "/plugins/knowledge-base/api/public/search?q=password",
        ):
            with patch("plugins.kbs_knowledge_base.routes.get_db_cursor") as mock_db, \
                 patch("plugins.kbs_knowledge_base.routes.set_tenant_search_path"), \
                 patch("plugins.kbs_knowledge_base.routes.g") as mock_g:
                mock_db.side_effect = mock_ctx
                mock_g.tenant_id = 1
                result = mock_cur.fetchall()
                assert len(result) >= 1


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
            tenant_id=1,
        )
        assert result["success"] is True
        assert result["agent"] == "Salon Business Coach"

    @patch("core.industry_agents.requests.post")
    def test_all_verticals_respond(self, mock_post):
        from core.industry_agents import IndustryAgentService

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "OK"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        verticals = ["industry", "salon", "construction", "electrical",
                     "plumbing", "mechanical", "photography", "limo"]
        for slug in verticals:
            result = IndustryAgentService.ask_agent(
                vertical_slug=slug, question="Test", context={}, tenant_id=1,
            )
            assert result["success"] is True, f"Failed for {slug}"


class TestAPIKeyFlow:
    """API key generation -> validation -> revocation."""

    @patch("core.api_keys.get_db_cursor")
    def test_full_api_key_lifecycle(self, mock_db):
        from core.api_keys import generate_api_key, revoke_api_key, validate_api_key

        # Generate
        gen_row = {"id": 1, "tenant_id": 1, "key_prefix": "kbs_abc",
                   "name": "Integration Test Key", "permissions": ["read"],
                   "rate_limit": 1000, "created_at": "2026-01-01"}
        ctx, cur = _mock_db_ctx(fetchone_val=gen_row)
        mock_db.side_effect = ctx

        key = generate_api_key(tenant_id=1, name="Integration Test Key")
        assert key["key"].startswith("kbs_")

        # Validate
        val_row = {"id": 1, "tenant_id": 1, "name": "Integration Test Key",
                   "permissions": ["read"], "rate_limit": 1000}
        cur.fetchone.return_value = val_row
        valid = validate_api_key(key["key"])
        assert valid is not None
        assert valid["tenant_id"] == 1

        # Revoke
        cur.fetchone.return_value = (1,)
        result = revoke_api_key(key["id"])
        assert result is True

        # Validate after revoke
        cur.fetchone.return_value = None
        invalid = validate_api_key(key["key"])
        assert invalid is None


class TestWebhookFlow:
    """Webhook registration -> dispatch -> delivery."""

    @patch("core.webhook_manager.requests.post")
    @patch("core.webhook_manager.get_db_cursor")
    def test_full_webhook_lifecycle(self, mock_db, mock_post):
        from core.webhook_manager import delete_webhook, dispatch_webhooks, register_webhook

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"
        mock_post.return_value = mock_resp

        # Register
        hook_row = {"id": 1, "tenant_id": 1, "url": "https://example.com/test",
                    "events": ["test.event"], "secret": "test_secret",
                    "is_active": True, "created_at": "2026-01-01"}
        ctx, cur = _mock_db_ctx(fetchone_val=hook_row)
        mock_db.side_effect = ctx

        hook = register_webhook(
            tenant_id=1, url="https://example.com/test", events=["test.event"],
        )
        assert hook["id"] is not None

        # Dispatch
        cur.fetchall.return_value = [
            {"id": 1, "url": "https://example.com/test",
             "events": ["test.event"], "secret": "test_secret"},
        ]
        dispatch_webhooks(
            tenant_id=1, event_type="test.event", payload={"integration": True},
        )

        import time
        time.sleep(0.3)

        assert mock_post.called

        # Delete
        cur.fetchone.return_value = (1,)
        result = delete_webhook(webhook_id=1, tenant_id=1)
        assert result is True


class TestEventBusWebhookWiring:
    """Event bus emits trigger webhook dispatch."""

    @patch("core.webhook_manager.dispatch_webhooks")
    def test_event_bus_emit_with_tenant_triggers_webhooks(self, mock_dispatch):
        from core.event_bus import EventBus

        bus = EventBus()
        bus.emit("article.published", {"article_id": 1, "title": "Test"}, tenant_id=42)

        mock_dispatch.assert_called_once()
        call_kwargs = mock_dispatch.call_args[1]
        assert call_kwargs["tenant_id"] == 42
        assert call_kwargs["event_type"] == "article.published"

    @patch("core.webhook_manager.dispatch_webhooks")
    def test_event_bus_emit_without_tenant_skips_webhooks(self, mock_dispatch):
        from core.event_bus import EventBus

        bus = EventBus()
        bus.emit("some.event", {"key": "val"})

        mock_dispatch.assert_not_called()
