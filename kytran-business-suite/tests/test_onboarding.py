"""Tests for onboarding wizard API."""

import json
from unittest.mock import MagicMock, patch

import pytest

from core.onboarding import (
    complete_onboarding,
    get_progress,
    get_recommendation,
    save_profile,
    select_tier,
    update_checklist,
    INDUSTRY_BUNDLES,
)


def _mock_db_ctx():
    mock_ctx = MagicMock()
    mock_cur = MagicMock()
    mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
    return mock_ctx, mock_cur


def _get_json(resp):
    if isinstance(resp, tuple):
        return resp[0].get_json(), resp[1]
    return resp.get_json(), 200


class TestOnboardingProgress:
    def test_returns_current_step(self, app):
        with app.test_request_context("/onboarding/api/progress"):
            with patch("core.onboarding.g") as mock_g:
                mock_g.tenant_id = 1
                mock_g.tenant = {
                    "id": 1, "tier": "free", "slug": "test-co",
                    "settings": {"onboarding_step": 1},
                }
                resp = get_progress.__wrapped__()

            data, status = _get_json(resp)
            assert status == 200
            assert data["current_step"] == 1
            assert data["complete"] is False


class TestSaveProfile:
    def test_saves_industry_and_advances(self, app):
        with app.test_request_context(
            "/onboarding/api/profile",
            method="POST",
            json={"business_name": "Acme Corp", "industry": "salon", "timezone": "America/Toronto"},
        ):
            mock_ctx, mock_cur = _mock_db_ctx()
            with patch("core.onboarding.get_db_cursor", mock_ctx), \
                 patch("core.onboarding.g") as mock_g:
                mock_g.tenant_id = 1
                resp = save_profile.__wrapped__()

            data, status = _get_json(resp)
            assert status == 200
            assert data["step"] == 2


class TestRecommendation:
    def test_returns_bundle_for_industry(self, app):
        with app.test_request_context("/onboarding/api/recommendation"):
            with patch("core.onboarding.g") as mock_g:
                mock_g.tenant = {"settings": {"industry": "salon"}}
                resp = get_recommendation.__wrapped__()

            data, status = _get_json(resp)
            assert status == 200
            assert data["bundle"]["name"] == "Salon Suite"
            assert "appointments" in data["bundle"]["plugins"]

    def test_unknown_industry_returns_other(self, app):
        with app.test_request_context("/onboarding/api/recommendation"):
            with patch("core.onboarding.g") as mock_g:
                mock_g.tenant = {"settings": {"industry": "space_tourism"}}
                resp = get_recommendation.__wrapped__()

            data, _ = _get_json(resp)
            assert data["bundle"]["name"] == "General Business"


class TestSelectTier:
    def test_free_tier_skips_checkout(self, app):
        with app.test_request_context(
            "/onboarding/api/select-tier",
            method="POST",
            json={"tier": "free"},
        ):
            mock_ctx, mock_cur = _mock_db_ctx()
            with patch("core.onboarding.get_db_cursor", mock_ctx), \
                 patch("core.onboarding.g") as mock_g:
                mock_g.tenant_id = 1
                resp = select_tier.__wrapped__()

            data, status = _get_json(resp)
            assert status == 200
            assert data["step"] == 5
            assert data["tier"] == "free"

    def test_business_tier_returns_checkout_url(self, app):
        with app.test_request_context(
            "/onboarding/api/select-tier",
            method="POST",
            json={"tier": "business"},
        ):
            mock_ctx, mock_cur = _mock_db_ctx()
            with patch("core.onboarding.get_db_cursor", mock_ctx), \
                 patch("core.onboarding.g") as mock_g, \
                 patch("core.onboarding.current_user") as mock_user, \
                 patch("core.stripe_checkout.create_subscription_checkout") as mock_sub:
                mock_g.tenant_id = 1
                mock_user.email = "test@example.com"
                mock_sub.return_value = {"url": "https://checkout.stripe.com/test", "session_id": "cs_test"}

                from core.onboarding import select_tier
                resp = select_tier.__wrapped__()

            data, status = _get_json(resp)
            assert status == 200
            assert data["status"] == "checkout"
            assert "checkout_url" in data


class TestChecklist:
    def test_updates_checklist_item(self, app):
        with app.test_request_context(
            "/onboarding/api/checklist",
            method="POST",
            json={"item": "import_contacts", "done": True},
        ):
            mock_ctx, mock_cur = _mock_db_ctx()
            mock_cur.fetchone.return_value = {"settings": {"onboarding_checklist": {}}}
            with patch("core.onboarding.get_db_cursor", mock_ctx), \
                 patch("core.onboarding.g") as mock_g:
                mock_g.tenant_id = 1
                resp = update_checklist.__wrapped__()

            data, status = _get_json(resp)
            assert status == 200
            assert data["checklist"]["import_contacts"] is True

    def test_missing_item_returns_400(self, app):
        with app.test_request_context(
            "/onboarding/api/checklist",
            method="POST",
            json={"done": True},
        ):
            with patch("core.onboarding.g") as mock_g:
                mock_g.tenant_id = 1
                resp = update_checklist.__wrapped__()

            _, status = _get_json(resp)
            assert status == 400


class TestCompleteOnboarding:
    def test_marks_complete(self, app):
        with app.test_request_context("/onboarding/api/complete", method="POST"):
            mock_ctx, mock_cur = _mock_db_ctx()
            with patch("core.onboarding.get_db_cursor", mock_ctx), \
                 patch("core.onboarding.g") as mock_g:
                mock_g.tenant_id = 1
                resp = complete_onboarding.__wrapped__()

            data, status = _get_json(resp)
            assert status == 200
            assert data["complete"] is True
