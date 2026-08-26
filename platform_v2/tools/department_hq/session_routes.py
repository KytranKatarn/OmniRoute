"""Browser session HTTP routes (Layer A Phase 1).

Two endpoints:
- POST /tools/department-hq/api/sessions/<agent>/<platform>/import-cookies
    Admin-only. Accepts Chrome-extension-format cookies, encrypts, persists.
- GET /tools/department-hq/api/sessions/<agent>/<platform>/state
    Internal-key-only. Used by archie_browser to load session state for skill execution.
"""

from __future__ import annotations

import logging

from flask import jsonify, request

logger = logging.getLogger(__name__)


# Platforms allowed for cookie-import → encrypted Playwright storage_state.
# claude/deepseek added 2026-06-02 so S.C.O.U.T. authenticated_fetch can read
# bot-protected share pages (claude.ai/share, chat.deepseek.com/share) with a
# real logged-in session — see KB #270262 / reference_scout-browser-intelligence.
_SUPPORTED_PLATFORMS = {"linkedin", "twitter", "facebook", "claude", "deepseek", "openai"}


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


def save_session_state_handler(agent_id: int, platform: str):
    """#4006 capture-to-vault: persist a storage_state pushed by the login
    sidecar right after an interactive login, so the session is vault-visible
    and health-probed immediately.

    NO auth here — must only be registered behind app.py's
    _require_internal_key (Bearer INTERNAL_API_KEY), mirroring the GET route.
    Platform is shape-validated only (not registry-checked) so the export
    keeps working even if browser_platforms is unavailable — the caller is
    trusted service-to-service infra.
    """
    from services import browser_session_service
    from services.browser_platform_service import PLATFORM_RE

    if not PLATFORM_RE.match((platform or "").lower()):
        return jsonify({"success": False, "error": "invalid platform key"}), 400
    data = request.get_json(silent=True) or {}
    state = data.get("state")
    if not isinstance(state, dict) or not state.get("cookies"):
        return jsonify({"success": False, "error": "state with cookies is required"}), 400
    try:
        result = browser_session_service.save_session(
            agent_id=agent_id,
            platform=platform.lower(),
            state=state,
            status="active",
        )
    except Exception:
        logger.exception("[browser-sessions] sidecar state save failed")
        return jsonify({"success": False, "error": "save failed"}), 500
    logger.info("[browser-sessions] sidecar captured session saved: %s/%s", agent_id, platform)
    return jsonify({"success": True, "session_id": result.get("id")}), 200


def get_session_state_handler(agent_id: int, platform: str):
    """archie_browser fetches Playwright storage_state for a (agent, platform).

    NO auth here — must only be registered behind app.py's _require_internal_key
    (Bearer INTERNAL_API_KEY), mirroring save_session_state_handler above.

    ⚠️ This was DEAD CODE until #6020. Its docstring claimed "See app.py for the
    @app.route registration", but app.py never imported it — it carried its own inline
    copy of this logic, and the two disagreed on AUTH: this one checked an
    ``X-Internal-Key`` header while app.py's decorator requires ``Authorization: Bearer``.
    Two implementations of one endpoint, and the reachable one was not the one the
    docstring pointed at. It had already misled a test — test_browser_session_routes'
    TestGetState was written against THIS handler and failed for as long as anyone looked.
    app.py now delegates here, exactly as it does for the POST.

    The self-check is gone deliberately: it read a module-level key captured at IMPORT,
    so the credential could not be rotated without a restart. app.py's decorator reads
    the environment at CALL time.
    """
    from services import browser_session_service

    state = browser_session_service.load_session(agent_id, platform)
    if state is None:
        return jsonify({"error": "no active session"}), 404
    return jsonify({"state": state}), 200
