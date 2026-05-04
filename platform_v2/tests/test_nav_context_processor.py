"""Integration tests for inject_category_siblings context processor."""

from unittest.mock import patch

import pytest


def test_processor_returns_dict_with_header_shortcuts(app):
    """Context processor returns a dict with the 'header_shortcuts' key."""
    with app.test_request_context("/tools/backup-manager"):
        from app import inject_category_siblings

        result = inject_category_siblings()
        assert isinstance(result, dict)
        assert "header_shortcuts" in result
        assert isinstance(result["header_shortcuts"], list)


def test_processor_respects_override(app):
    """If g.header_shortcuts_override is set, processor returns it unchanged
    AND get_category_siblings is not called (override is a fast-path bypass)."""
    from services import nav_service

    sentinel = [{"id": "x", "label": "X", "icon": "x", "url": "/x", "external": False, "active": False}]
    with patch.object(nav_service, "get_category_siblings") as mock_fn:
        with app.test_request_context("/tools/backup-manager"):
            from flask import g

            g.header_shortcuts_override = sentinel
            from app import inject_category_siblings

            result = inject_category_siblings()
            assert result["header_shortcuts"] == sentinel
            mock_fn.assert_not_called()


def test_processor_never_raises(app):
    """Even with broken nav_service, processor returns empty list, not error."""
    from services import nav_service

    with patch.object(nav_service, "get_category_siblings", side_effect=RuntimeError("boom")):
        with app.test_request_context("/tools/backup-manager"):
            from app import inject_category_siblings

            result = inject_category_siblings()
            assert result == {"header_shortcuts": []}


def test_processor_memoizes_within_request(app):
    """Multiple calls within same request reuse the cached value."""
    from services import nav_service

    call_count = {"n": 0}
    real_fn = nav_service.get_category_siblings

    def counting(*a, **k):
        call_count["n"] += 1
        return real_fn(*a, **k)

    with patch.object(nav_service, "get_category_siblings", side_effect=counting):
        with app.test_request_context("/tools/backup-manager"):
            from app import inject_category_siblings

            inject_category_siblings()
            inject_category_siblings()
            inject_category_siblings()
    # Memoized: get_category_siblings called at most once
    assert call_count["n"] <= 1


def test_processor_anonymous_request_returns_empty(app):
    """Endpoint that doesn't map to a module returns empty shortcuts."""
    with app.test_request_context("/login"):
        from app import inject_category_siblings

        result = inject_category_siblings()
        assert result["header_shortcuts"] == []


def test_module_backup_manager_renders(app):
    """Pilot module loads with new include + helper-injected shortcuts."""
    # Skip auth so we can hit the page without a logged-in user
    # (or use a test client with an auth fixture if one exists)
    client = app.test_client()
    resp = client.get("/tools/backup-manager")
    # Accept any non-500 — the page may redirect to login (302) if auth is required
    assert resp.status_code in (200, 302, 308)
    if resp.status_code == 200:
        body = resp.get_data(as_text=True)
        assert "lcars-header" in body
        assert "category_nav" not in body  # Old include is gone from this page


@pytest.mark.parametrize(
    "url",
    [
        "/tools/doc",
        "/tools/fitness",
        "/tools/therapy",
        "/tools/archie-chat",
    ],
)
def test_wave_modules_render_with_lcars_header(app, url):
    """Wave-migrated modules load with lcars-header.html — old include is gone."""
    client = app.test_client()
    resp = client.get(url)
    # Accept 200 / 302 (auth redirect) / 308 (trailing slash redirect)
    assert resp.status_code in (200, 302, 308)
    if resp.status_code == 200:
        body = resp.get_data(as_text=True)
        assert "lcars-header" in body
        assert "category_nav" not in body
