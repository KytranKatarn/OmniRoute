"""
Media Hub Auth Layer
====================
Blueprint-wide login gate + SSO stub endpoint.

Part of Project #273 task #2150 (PR 1/2). This PR installs the
enforcement mechanism + the SSO stub; PR 2 adds a standalone users
table and login page.

Design:
- Inside the ARCHIE platform, `current_user` is populated by the
  platform's Flask-Login. This gate double-checks rather than relies
  on perimeter auth — before this file Media Hub routes had ZERO
  auth decorators (audit finding, KB 256971).
- In a future standalone container, the same gate keeps working
  against a standalone Flask-Login-backed user table. Only the
  login page / user model swaps.
- `/auth/sso` returns HTTP 501 today. The real Kytran SSO wiring is
  tracked as a Tier 2 item in .claude/rules/standalone-extraction.md.
"""

from functools import wraps

from flask import abort, current_app, jsonify, request
from flask_login import current_user


_EXEMPT_ENDPOINT_SUFFIXES = {"sso_stub", "static"}


def _is_api_request() -> bool:
    path = request.path or ""
    return "/api/" in path or path.endswith(".json") or request.is_json


def _require_login():
    """Blueprint before_request hook: gate every route except exemptions."""
    endpoint = request.endpoint or ""
    suffix = endpoint.rsplit(".", 1)[-1] if "." in endpoint else endpoint
    if suffix in _EXEMPT_ENDPOINT_SUFFIXES:
        return None
    if current_user.is_authenticated:
        return None
    if _is_api_request():
        return jsonify({"error": "Authentication required"}), 401
    return current_app.login_manager.unauthorized()


def sso_stub():
    """Placeholder for Kytran SSO — Tier 2 extraction item."""
    return (
        jsonify(
            {
                "status": "not_implemented",
                "message": (
                    "Kytran SSO is not wired yet. Tracked in Project #273 "
                    "Tier 2 (see .claude/rules/standalone-extraction.md). "
                    "Use the local login for now."
                ),
                "provider_hint": request.args.get("provider"),
            }
        ),
        501,
    )


def install_auth(bp):
    """Attach the login gate and register /auth/sso on the given blueprint.

    Call once, after routes are imported, from the module __init__.
    """
    bp.add_url_rule("/auth/sso", endpoint="sso_stub", view_func=sso_stub, methods=["GET"])
    bp.before_request(_require_login)


def media_hub_login_required(fn):
    """Per-route decorator variant — useful for routes that need the check
    but live outside the main Media Hub blueprint (e.g. future sub-blueprints)."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_user.is_authenticated:
            return fn(*args, **kwargs)
        if _is_api_request():
            return jsonify({"error": "Authentication required"}), 401
        return current_app.login_manager.unauthorized()

    return wrapper


def media_hub_admin_required(fn):
    """Per-route ADMIN gate for privileged mutations (service config, deletes).

    Login is already enforced blueprint-wide by ``_require_login``; this adds the
    ``is_admin`` check so a non-admin family member (a viewer, or an SSO user the
    IdP did not issue an admin role to) cannot rewrite service credentials or
    delete downloads/requests. Returns JSON 403 for API requests — consistent
    with the JSON 401 the login gate returns — and an HTML 403 otherwise.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            if _is_api_request():
                return jsonify({"error": "Authentication required"}), 401
            return current_app.login_manager.unauthorized()
        if not getattr(current_user, "is_admin", False):
            if _is_api_request():
                return jsonify({"error": "Admin privileges required"}), 403
            abort(403)
        return fn(*args, **kwargs)

    return wrapper
