"""Tests for marketplace API endpoints."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from core.marketplace import (
    activate_plugin,
    deactivate_plugin,
    list_plugins,
    start_trial,
)


def _mock_db_ctx():
    """Helper to create a mock DB context manager."""
    mock_ctx = MagicMock()
    mock_cur = MagicMock()
    mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
    return mock_ctx, mock_cur


def _get_json(resp):
    """Extract JSON + status from a view function return."""
    if isinstance(resp, tuple):
        return resp[0].get_json(), resp[1]
    return resp.get_json(), 200


class TestListPlugins:
    def test_returns_all_catalog_entries(self, app):
        catalog = [
            {
                "slug": "crm", "name": "CRM", "description": "Contact management",
                "category": "core", "tier_required": "free", "icon": "users",
                "price_monthly": None, "features": ["contacts"], "version": "1.0.0",
            },
        ]
        enabled = [{"module_slug": "crm", "source": "tier_included", "activated_at": None, "trial_ends_at": None}]

        with app.test_request_context("/marketplace/api/plugins"):
            mock_ctx, mock_cur = _mock_db_ctx()
            mock_cur.fetchall.side_effect = [catalog, enabled]

            with patch("core.marketplace.get_db_cursor", mock_ctx), \
                 patch("core.marketplace.g") as mock_g:
                mock_g.tenant_id = 1
                mock_g.tenant = {"id": 1, "tier": "free", "slug": "test-co"}
                # Skip @login_required via __wrapped__
                resp = list_plugins.__wrapped__()

            data, status = _get_json(resp)
            assert status == 200
            assert "plugins" in data
            assert data["current_tier"] == "free"
            assert len(data["plugins"]) == 1
            assert data["plugins"][0]["slug"] == "crm"


class TestActivatePlugin:
    def test_tier_included_activates_immediately(self, app):
        with app.test_request_context("/marketplace/api/plugins/crm/activate", method="POST"):
            mock_ctx, mock_cur = _mock_db_ctx()
            mock_cur.fetchone.return_value = {"slug": "crm", "tier_required": "free"}

            with patch("core.marketplace.get_db_cursor", mock_ctx), \
                 patch("core.marketplace.g") as mock_g, \
                 patch("core.marketplace.activate_module") as mock_act, \
                 patch("core.marketplace.get_modules_for_tier", return_value={"crm", "invoicing"}):
                mock_g.tenant_id = 1
                mock_g.tenant = {"id": 1, "tier": "free"}
                resp = activate_plugin.__wrapped__("crm")

            data, status = _get_json(resp)
            assert status == 200
            assert data["status"] == "activated"
            mock_act.assert_called_once_with(1, "crm", source="tier_included")

    def test_upgrade_required_returns_402(self, app):
        with app.test_request_context("/marketplace/api/plugins/appointments/activate", method="POST"):
            mock_ctx, mock_cur = _mock_db_ctx()
            mock_cur.fetchone.return_value = {"slug": "appointments", "tier_required": "business"}

            with patch("core.marketplace.get_db_cursor", mock_ctx), \
                 patch("core.marketplace.g") as mock_g, \
                 patch("core.marketplace.get_modules_for_tier", return_value={"crm", "invoicing"}):
                mock_g.tenant_id = 1
                mock_g.tenant = {"id": 1, "tier": "free"}
                resp = activate_plugin.__wrapped__("appointments")

            _, status = _get_json(resp)
            assert status == 402


class TestStartTrial:
    def test_trial_starts_successfully(self, app):
        with app.test_request_context("/marketplace/api/plugins/appointments/trial", method="POST"):
            mock_ctx, mock_cur = _mock_db_ctx()
            mock_cur.fetchone.side_effect = [
                {"slug": "appointments"},
                None,
            ]

            with patch("core.marketplace.get_db_cursor", mock_ctx), \
                 patch("core.marketplace.g") as mock_g:
                mock_g.tenant_id = 1
                resp = start_trial.__wrapped__("appointments")

            data, status = _get_json(resp)
            assert status == 200
            assert data["status"] == "trial_started"
            assert "trial_ends_at" in data

    def test_duplicate_trial_returns_409(self, app):
        with app.test_request_context("/marketplace/api/plugins/appointments/trial", method="POST"):
            mock_ctx, mock_cur = _mock_db_ctx()
            mock_cur.fetchone.side_effect = [
                {"slug": "appointments"},
                {"module_slug": "appointments", "source": "trial", "trial_ends_at": None},
            ]

            with patch("core.marketplace.get_db_cursor", mock_ctx), \
                 patch("core.marketplace.g") as mock_g:
                mock_g.tenant_id = 1
                resp = start_trial.__wrapped__("appointments")

            _, status = _get_json(resp)
            assert status == 409


class TestDeactivatePlugin:
    def test_addon_deactivates(self, app):
        with app.test_request_context("/marketplace/api/plugins/salon/deactivate", method="POST"):
            with patch("core.marketplace.g") as mock_g, \
                 patch("core.marketplace.get_modules_for_tier", return_value={"crm"}), \
                 patch("core.marketplace.deactivate_module") as mock_deact:
                mock_g.tenant_id = 1
                mock_g.tenant = {"id": 1, "tier": "free"}
                resp = deactivate_plugin.__wrapped__("salon")

            data, status = _get_json(resp)
            assert status == 200
            assert data["status"] == "deactivated"
            mock_deact.assert_called_once()

    def test_tier_included_cannot_deactivate(self, app):
        with app.test_request_context("/marketplace/api/plugins/crm/deactivate", method="POST"):
            with patch("core.marketplace.g") as mock_g, \
                 patch("core.marketplace.get_modules_for_tier", return_value={"crm", "invoicing"}):
                mock_g.tenant_id = 1
                mock_g.tenant = {"id": 1, "tier": "free"}
                resp = deactivate_plugin.__wrapped__("crm")

            _, status = _get_json(resp)
            assert status == 400
