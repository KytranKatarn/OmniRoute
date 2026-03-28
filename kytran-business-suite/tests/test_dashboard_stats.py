"""Tests for dashboard stats API."""

from unittest.mock import MagicMock, patch

import pytest

from core.dashboard_stats import get_stats


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


class TestDashboardStats:
    def test_returns_tenant_info(self, app):
        with app.test_request_context("/api/dashboard/stats"):
            mock_ctx, mock_cur = _mock_db_ctx()
            mock_cur.fetchone.return_value = {"cnt": 0, "total": 0, "outstanding": 0, "outstanding_amount": 0, "revenue": 0}

            with patch("core.dashboard_stats.get_db_cursor", mock_ctx), \
                 patch("core.dashboard_stats.set_tenant_search_path"), \
                 patch("core.dashboard_stats.g") as mock_g, \
                 patch("core.tenant.get_enabled_modules", return_value=["crm", "invoicing"]):
                mock_g.tenant_id = 1
                mock_g.tenant = {"id": 1, "name": "Test Co", "tier": "business", "settings": {"onboarding_complete": True}}
                resp = get_stats.__wrapped__()

            data, status = _get_json(resp)
            assert status == 200
            assert data["tenant_name"] == "Test Co"
            assert data["tier"] == "business"
            assert "quick_actions" in data

    def test_quick_actions_based_on_enabled_plugins(self, app):
        with app.test_request_context("/api/dashboard/stats"):
            mock_ctx, mock_cur = _mock_db_ctx()
            mock_cur.fetchone.return_value = {"cnt": 0, "total": 0, "outstanding": 0, "outstanding_amount": 0, "revenue": 0}

            with patch("core.dashboard_stats.get_db_cursor", mock_ctx), \
                 patch("core.dashboard_stats.set_tenant_search_path"), \
                 patch("core.dashboard_stats.g") as mock_g, \
                 patch("core.tenant.get_enabled_modules", return_value=["crm"]):
                mock_g.tenant_id = 1
                mock_g.tenant = {"id": 1, "name": "Test Co", "tier": "free", "settings": {}}
                resp = get_stats.__wrapped__()

            data, _ = _get_json(resp)
            action_labels = [a["label"] for a in data["quick_actions"]]
            assert "Add Contact" in action_labels
            assert "Create Invoice" not in action_labels

    def test_onboarding_incomplete_flag(self, app):
        with app.test_request_context("/api/dashboard/stats"):
            mock_ctx, mock_cur = _mock_db_ctx()
            mock_cur.fetchone.return_value = {"cnt": 0, "total": 0, "outstanding": 0, "outstanding_amount": 0, "revenue": 0}

            with patch("core.dashboard_stats.get_db_cursor", mock_ctx), \
                 patch("core.dashboard_stats.set_tenant_search_path"), \
                 patch("core.dashboard_stats.g") as mock_g, \
                 patch("core.tenant.get_enabled_modules", return_value=[]):
                mock_g.tenant_id = 1
                mock_g.tenant = {"id": 1, "name": "New Co", "tier": "free", "settings": {}}
                resp = get_stats.__wrapped__()

            data, _ = _get_json(resp)
            assert data["onboarding_complete"] is False
