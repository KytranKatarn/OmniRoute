"""Integration tests for SIGNAL Phase 4 action endpoints (retry + abandon)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def admin_app():
    """Mini Flask app with the social_routes blueprint mounted under admin user."""
    from flask import Flask, Blueprint
    from flask_login import LoginManager, UserMixin

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-key"

    login_manager = LoginManager()
    login_manager.init_app(app)

    class _AdminUser(UserMixin):
        id = 1
        is_admin = True

    @login_manager.user_loader
    def _load_user(uid):
        return _AdminUser()

    @login_manager.request_loader
    def _request_loader(_request):
        return _AdminUser()

    from tools.department_hq.social_routes import register_social_routes

    bp = Blueprint("signal_test", __name__, url_prefix="/tools/department-hq")
    register_social_routes(bp, lambda f: f)  # bypass admin_required for test
    app.register_blueprint(bp)

    return app


@pytest.fixture
def client(admin_app):
    return admin_app.test_client()


class TestRetryEndpoint:
    def test_retry_resets_executed_row_to_approved(self, client):
        """Retry of a failed (status='executed') row should reset to 'approved'
        with execution_result and executed_at cleared so the worker re-picks it up."""
        with patch("database.get_db_cursor") as mock_cur:
            cur = MagicMock()
            cur.fetchone.return_value = {"id": 99}
            ctx = MagicMock()
            ctx.__enter__.return_value = (MagicMock(), cur)
            mock_cur.return_value = ctx

            r = client.post("/tools/department-hq/api/signal/posts/99/retry")
            assert r.status_code == 200
            body = r.get_json()
            assert body["success"] is True
            assert body["approval_id"] == 99

            # Verify the SQL UPDATE: status->'approved', execution_result->NULL, executed_at->NULL
            executed_sql = cur.execute.call_args[0][0]
            assert "UPDATE autonomy_approval_queue" in executed_sql
            assert "status = 'approved'" in executed_sql
            assert "execution_result = NULL" in executed_sql
            assert "executed_at = NULL" in executed_sql
            assert "WHERE id = " in executed_sql
            # Phase 4 fix: retry must only match FAILED rows, not successful ones
            assert "execution_result" in executed_sql
            assert "success" in executed_sql.lower()

    def test_retry_404_when_row_not_found(self, client):
        """If the row doesn't exist or isn't in 'executed' status, return 404."""
        with patch("database.get_db_cursor") as mock_cur:
            cur = MagicMock()
            cur.fetchone.return_value = None
            ctx = MagicMock()
            ctx.__enter__.return_value = (MagicMock(), cur)
            mock_cur.return_value = ctx

            r = client.post("/tools/department-hq/api/signal/posts/9999/retry")
            assert r.status_code == 404

    def test_retry_404_when_post_was_successful(self, client):
        """Retry must NOT re-fire a successfully-posted row.
        The new SQL guard checks execution_result.success — when the row matches
        success=true, fetchone returns None (no row matches the failure clause)."""
        with patch("database.get_db_cursor") as mock_cur:
            cur = MagicMock()
            cur.fetchone.return_value = None  # successful post → no row matches retry's failure-only WHERE
            ctx = MagicMock()
            ctx.__enter__.return_value = (MagicMock(), cur)
            mock_cur.return_value = ctx

            r = client.post("/tools/department-hq/api/signal/posts/99/retry")
            assert r.status_code == 404
            body = r.get_json()
            assert "failed state" in (body.get("error") or "").lower()


class TestAbandonEndpoint:
    def test_abandon_sets_status_abandoned(self, client):
        """Abandon should set status='abandoned' on a non-terminal row."""
        with patch("database.get_db_cursor") as mock_cur:
            cur = MagicMock()
            cur.fetchone.return_value = {"id": 99}
            ctx = MagicMock()
            ctx.__enter__.return_value = (MagicMock(), cur)
            mock_cur.return_value = ctx

            r = client.post("/tools/department-hq/api/signal/posts/99/abandon")
            assert r.status_code == 200
            body = r.get_json()
            assert body["success"] is True
            assert body["approval_id"] == 99

            executed_sql = cur.execute.call_args[0][0]
            assert "UPDATE autonomy_approval_queue" in executed_sql
            assert "status = 'abandoned'" in executed_sql
            assert "WHERE id = " in executed_sql

    def test_abandon_404_when_row_not_found(self, client):
        with patch("database.get_db_cursor") as mock_cur:
            cur = MagicMock()
            cur.fetchone.return_value = None
            ctx = MagicMock()
            ctx.__enter__.return_value = (MagicMock(), cur)
            mock_cur.return_value = ctx

            r = client.post("/tools/department-hq/api/signal/posts/9999/abandon")
            assert r.status_code == 404
