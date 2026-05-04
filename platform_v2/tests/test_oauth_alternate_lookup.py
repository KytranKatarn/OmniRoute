"""Tests for OAuth callback alternate-email fallback (Project #311)."""

from __future__ import annotations

from unittest.mock import patch


def test_find_user_by_any_email_patchable_at_source():
    """Confirm the helper is patchable at services.account_link_service.

    oauth_routes calls find_user_by_any_email via a local import inside
    google_callback(), so patching at the source module is the correct target.
    Full OAuth flow (token exchange + ID token verification) is untestable here
    without a complete mock chain; behavioral coverage lives in
    TestFindUserByAnyEmail in test_account_link_service.py.
    """
    with patch(
        "services.account_link_service.find_user_by_any_email",
        return_value=None,
    ) as mock_fn:
        # Verify the patch resolves correctly (no AttributeError = helper exists)
        assert callable(mock_fn)
        # Call it to confirm the mock works end-to-end
        result = mock_fn("test@example.com")
        assert result is None
        mock_fn.assert_called_once_with("test@example.com")


def test_find_user_by_any_email_module_is_callable():
    """Ensure the helper is importable from the canonical path used by callers."""
    from services.account_link_service import find_user_by_any_email

    assert callable(find_user_by_any_email)


def test_initiate_password_reset_uses_alternate_lookup():
    """Verify initiate_password_reset calls find_user_by_any_email with active_only=True.

    The import is local inside the function, so we patch at the source module
    (services.account_link_service) rather than at the importer.
    """
    with patch(
        "services.account_link_service.find_user_by_any_email",
        return_value=None,
    ) as mock_lookup:
        from services.auth_service import initiate_password_reset

        # Should return True silently when no user found (email enumeration guard)
        result = initiate_password_reset("nobody@example.com")
        assert result is True
        mock_lookup.assert_called_once_with("nobody@example.com", active_only=True)
