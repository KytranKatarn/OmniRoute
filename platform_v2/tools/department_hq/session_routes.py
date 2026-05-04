"""Browser session HTTP routes (Layer A Phase 1).

Two endpoints:
- POST /tools/department-hq/api/sessions/<agent>/<platform>/import-cookies
    Admin-only. Accepts Chrome-extension-format cookies, encrypts, persists.
- GET /tools/department-hq/api/sessions/<agent>/<platform>/state
    Internal-key-only. Used by archie_browser to load session state for skill execution.
"""

from __future__ import annotations

import hmac
import logging
import os

from flask import jsonify, request

logger = logging.getLogger(__name__)

_INTERNAL_KEY = os.getenv("INTERNAL_API_KEY", "")

_SUPPORTED_PLATFORMS = {"linkedin", "twitter", "facebook"}


def _cookies_to_storage_state(cookies: list) -> dict:
    """Convert Chrome-extension cookie format to Playwright storage_state."""
    storage_cookies = []
    for c in cookies:
        if not c.get("name") or "value" not in c:
            continue
        sc = {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ""),
            "path": c.get("path", "/"),
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure": bool(c.get("secure", False)),
            "sameSite": (c.get("sameSite", "Lax").capitalize() if c.get("sameSite") else "Lax"),
        }
        if "expires" in c and c["expires"] is not None:
            sc["expires"] = float(c["expires"])
        storage_cookies.append(sc)
    return {"cookies": storage_cookies, "origins": []}


def register_session_routes(bp, login_required, admin_required):
    """Register the admin import-cookies route on the Department HQ blueprint.

    The internal-key state-fetch route is registered separately in app.py at
    /api/internal/sessions/... because /tools/department-hq/* has invisible auth
    middleware redirecting all unauth requests to /dashboard.
    """

    @bp.route(
        "/api/sessions/<int:agent_id>/<platform>/import-cookies",
        methods=["POST"],
    )
    @admin_required
    def import_cookies(agent_id, platform):
        """Admin imports cookies from their browser into the agent's session."""
        from services import browser_session_service

        data = request.get_json(silent=True) or {}
        cookies = data.get("cookies") or []
        if not cookies:
            return jsonify({"success": False, "error": "cookies array is required"}), 400
        if platform not in _SUPPORTED_PLATFORMS:
            return (
                jsonify({"success": False, "error": f"unsupported platform: {platform}"}),
                400,
            )

        storage_state = _cookies_to_storage_state(cookies)
        try:
            result = browser_session_service.save_session(
                agent_id=agent_id,
                platform=platform,
                state=storage_state,
                status="active",
            )
        except Exception as exc:
            logger.exception("[browser-sessions] import-cookies failed")
            return jsonify({"success": False, "error": str(exc)}), 500

        return (
            jsonify(
                {
                    "success": True,
                    "session_id": result.get("id"),
                    "cookies_imported": len(storage_state["cookies"]),
                }
            ),
            200,
        )


def get_session_state_handler(agent_id: int, platform: str):
    """Handler shared with the app-level /api/internal/sessions/... route.

    Defined at module level (not nested inside register_session_routes) so app.py
    can import it cleanly. See app.py for the @app.route registration.
    """
    provided = request.headers.get("X-Internal-Key", "")
    if not _INTERNAL_KEY or not hmac.compare_digest(provided, _INTERNAL_KEY):
        return jsonify({"error": "unauthorized"}), 401

    from services import browser_session_service

    state = browser_session_service.load_session(agent_id, platform)
    if state is None:
        return jsonify({"error": "no active session"}), 404
    return jsonify({"state": state}), 200
