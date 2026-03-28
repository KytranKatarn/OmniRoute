"""Tests for team management API."""

from unittest.mock import MagicMock, patch

import pytest

from core.team_management import (
    change_role,
    invite_member,
    list_members,
    remove_member,
    VALID_ROLES,
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


def _make_session_mock(role="owner"):
    """Create a session mock that returns the correct role."""
    mock_s = MagicMock()
    mock_s.get = MagicMock(side_effect=lambda k, default="": role if k == "tenant_role" else default)
    return mock_s


class TestInviteMember:
    def test_creates_invite(self, app):
        with app.test_request_context(
            "/api/team/invite", method="POST",
            json={"email": "new@example.com", "role": "member"},
        ):
            mock_ctx, mock_cur = _mock_db_ctx()
            mock_cur.fetchone.side_effect = [None, None, (42,)]

            with patch("core.team_management.get_db_cursor", mock_ctx), \
                 patch("core.team_management.g") as mock_g, \
                 patch("core.team_management.session", _make_session_mock("owner")), \
                 patch("core.team_management.current_user") as mock_u:
                mock_g.tenant_id = 1
                mock_u.id = 1
                resp = invite_member.__wrapped__()

            data, status = _get_json(resp)
            assert status == 200
            assert data["status"] == "invited"
            assert data["email"] == "new@example.com"
            assert "invite_url" in data

    def test_invalid_role_returns_400(self, app):
        with app.test_request_context(
            "/api/team/invite", method="POST",
            json={"email": "new@example.com", "role": "superadmin"},
        ):
            with patch("core.team_management.session", _make_session_mock("owner")):
                resp = invite_member.__wrapped__()

            _, status = _get_json(resp)
            assert status == 400

    def test_missing_email_returns_400(self, app):
        with app.test_request_context(
            "/api/team/invite", method="POST",
            json={"role": "member"},
        ):
            with patch("core.team_management.session", _make_session_mock("owner")):
                resp = invite_member.__wrapped__()

            _, status = _get_json(resp)
            assert status == 400

    def test_non_admin_returns_403(self, app):
        with app.test_request_context(
            "/api/team/invite", method="POST",
            json={"email": "new@example.com", "role": "member"},
        ):
            with patch("core.team_management.session", _make_session_mock("viewer")):
                resp = invite_member.__wrapped__()

            _, status = _get_json(resp)
            assert status == 403


class TestListMembers:
    def test_returns_members_and_invites(self, app):
        with app.test_request_context("/api/team"):
            mock_ctx, mock_cur = _mock_db_ctx()
            mock_cur.fetchall.side_effect = [
                [{"id": 1, "email": "owner@example.com", "name": "Owner", "role": "owner", "last_login": None, "created_at": None}],
                [],
            ]

            with patch("core.team_management.get_db_cursor", mock_ctx), \
                 patch("core.team_management.g") as mock_g:
                mock_g.tenant_id = 1
                resp = list_members.__wrapped__()

            data, status = _get_json(resp)
            assert status == 200
            assert len(data["members"]) == 1
            assert data["members"][0]["role"] == "owner"


class TestChangeRole:
    def test_owner_changes_role(self, app):
        with app.test_request_context(
            "/api/team/2/role", method="PUT",
            json={"role": "admin"},
        ):
            mock_ctx, mock_cur = _mock_db_ctx()
            mock_cur.fetchone.return_value = (2,)

            with patch("core.team_management.get_db_cursor", mock_ctx), \
                 patch("core.team_management.g") as mock_g, \
                 patch("core.team_management.session", _make_session_mock("owner")), \
                 patch("core.team_management.current_user") as mock_u:
                mock_g.tenant_id = 1
                mock_u.id = 1
                resp = change_role.__wrapped__(2)

            data, status = _get_json(resp)
            assert status == 200
            assert data["role"] == "admin"

    def test_cannot_change_own_role(self, app):
        with app.test_request_context(
            "/api/team/1/role", method="PUT",
            json={"role": "viewer"},
        ):
            with patch("core.team_management.session", _make_session_mock("owner")), \
                 patch("core.team_management.current_user") as mock_u:
                mock_u.id = 1
                resp = change_role.__wrapped__(1)

            _, status = _get_json(resp)
            assert status == 400

    def test_non_owner_cannot_change_role(self, app):
        with app.test_request_context(
            "/api/team/2/role", method="PUT",
            json={"role": "admin"},
        ):
            with patch("core.team_management.session", _make_session_mock("member")):
                resp = change_role.__wrapped__(2)

            _, status = _get_json(resp)
            assert status == 403


class TestRemoveMember:
    def test_removes_non_owner(self, app):
        with app.test_request_context("/api/team/2", method="DELETE"):
            mock_ctx, mock_cur = _mock_db_ctx()
            mock_cur.fetchone.return_value = (2,)

            with patch("core.team_management.get_db_cursor", mock_ctx), \
                 patch("core.team_management.g") as mock_g, \
                 patch("core.team_management.session", _make_session_mock("owner")), \
                 patch("core.team_management.current_user") as mock_u:
                mock_g.tenant_id = 1
                mock_u.id = 1
                resp = remove_member.__wrapped__(2)

            data, status = _get_json(resp)
            assert status == 200
            assert data["status"] == "removed"

    def test_cannot_remove_self(self, app):
        with app.test_request_context("/api/team/1", method="DELETE"):
            with patch("core.team_management.session", _make_session_mock("owner")), \
                 patch("core.team_management.current_user") as mock_u:
                mock_u.id = 1
                resp = remove_member.__wrapped__(1)

            _, status = _get_json(resp)
            assert status == 400
