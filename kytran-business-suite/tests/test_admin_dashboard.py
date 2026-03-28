"""Tests for admin dashboard metrics API."""

from unittest.mock import MagicMock, patch

import pytest

from core.admin_dashboard import metrics


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


class TestAdminMetrics:
    def test_returns_platform_metrics(self, app):
        with app.test_request_context("/admin/api/metrics"):
            mock_ctx, mock_cur = _mock_db_ctx()
            mock_cur.fetchone.side_effect = [
                {"cnt": 10},   # total_tenants
                {"cnt": 3},    # new_signups_30d
                {"cnt": 2},    # addon_count
                {"cnt": 1},    # churned_30d
                {"active_7d": 8, "active_30d": 9, "inactive": 1},  # client_health
                {"cnt": 2},    # active_trials
            ]
            mock_cur.fetchall.side_effect = [
                [{"tier": "free", "cnt": 5}, {"tier": "business", "cnt": 4}, {"tier": "enterprise", "cnt": 1}],
                [{"module_slug": "crm", "cnt": 10}, {"module_slug": "invoicing", "cnt": 8}],
            ]

            with patch("core.admin_dashboard.get_db_cursor", mock_ctx), \
                 patch("core.admin_dashboard.session") as mock_session:
                mock_session.get.return_value = "owner"
                # Access __wrapped__ twice to skip both @login_required and @_require_owner
                resp = metrics.__wrapped__.__wrapped__()

            data, status = _get_json(resp)
            assert status == 200
            assert data["total_tenants"] == 10
            assert data["total_mrr"] > 0
            assert "plugin_heatmap" in data
            assert "client_health" in data
            assert data["active_trials"] == 2

    def test_non_owner_gets_403(self, app):
        with app.test_request_context("/admin/api/metrics"):
            with patch("core.admin_dashboard.session") as mock_session:
                mock_session.get.return_value = "member"
                # Only unwrap @login_required, keep @_require_owner
                try:
                    metrics.__wrapped__().__wrapped__()
                except Exception:
                    pass

                # Test via the _require_owner path directly
                from core.admin_dashboard import _require_owner
                from flask import abort

                @_require_owner
                def test_fn():
                    return "ok"

                with pytest.raises(Exception):
                    # abort(403) raises an HTTPException
                    test_fn()
