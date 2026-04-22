"""Maven dispatch endpoint — hub-side HTTP surface for the Media Hub
standalone's conversational skill (task #2251 / phase 2 of #2237).

Contract:

    POST /api/maven/dispatch
    Authorization: Bearer <kytran access_token>
    Content-Type: application/json

    {
        "capability": "library_curation",         # required
        "prompt":     "...",                       # required
        "system":     "...",                       # optional override
        "model":      "llama3.2:3b"                # optional override
    }

Returns:

    {
        "response":   "...",                       # model output
        "agent":      "M.A.V.E.N.",                # which agent served
        "tier":       "home",                      # dispatcher tier
        "cost":       0.0                          # USD; 0 for local
    }

Token validation mirrors /oauth/userinfo: HS256 JWT against the app's
SECRET_KEY, subject = user id, user must be active. No additional role
gating — any signed-in Kytran user can hit M.A.V.E.N. (family-access
pattern matches the standalone's KYTRAN_AUTH_ENFORCE_ENTITLEMENT=false
choice).

Dispatcher call path (per ADR in .claude/rules/ai-bridge.md):
    from tools.department_hq.services.department_dispatcher import dispatch
    result = dispatch(capability, prompt)

All LLM inference flows through the Bridge, so welfare-gating + cost
tracking + GPU placement are honoured automatically — the standalone's
allowlist entry in scripts/check_agent_single_writer.py can be removed
once MAVEN_CHAT_USE_BRIDGE=1 is the default and maven/chat.py no longer
has a direct Ollama call path.
"""

from __future__ import annotations

import logging

import jwt
from flask import Blueprint, current_app, jsonify, request

from database import get_db_cursor

log = logging.getLogger("platform.maven_dispatch")

maven_dispatch_bp = Blueprint("maven_dispatch", __name__, url_prefix="/api/maven")


def _resolve_user_from_bearer() -> tuple[int | None, dict | str]:
    """Return (user_id, user_row_or_err_message). user_id is None on failure
    and the second element carries the error string. Mirrors the userinfo
    endpoint's validation path."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, "Bearer token required"
    token = auth_header[7:]

    secret = current_app.config.get("SECRET_KEY", "fallback-secret")
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None, "Token expired"
    except jwt.InvalidTokenError:
        return None, "Invalid token"

    user_id = payload.get("sub")
    if not user_id:
        return None, "Invalid token payload"

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, username, role FROM users WHERE id = %s AND is_active = TRUE",
            (user_id,),
        )
        user = cur.fetchone()
    if not user:
        return None, "User not found"
    return int(user["id"]), user


@maven_dispatch_bp.route("/dispatch", methods=["POST"])
def dispatch_maven():
    user_id, user_or_err = _resolve_user_from_bearer()
    if user_id is None:
        return jsonify({"error": user_or_err}), 401
    user = user_or_err

    data = request.get_json(silent=True) or {}
    capability = (data.get("capability") or "").strip()
    prompt = (data.get("prompt") or "").strip()
    if not capability or not prompt:
        return jsonify({"error": "capability + prompt required"}), 400

    # Truncate defensively so a rogue standalone can't pin the dispatcher.
    prompt = prompt[:16000]
    system = (data.get("system") or "").strip()[:4000] or None
    model = (data.get("model") or "").strip() or None

    try:
        # Lazy import: guardrail scripts/check_agent_single_writer.py expects
        # the dispatcher imports to live under tools.department_hq.services.
        from tools.department_hq.services.department_dispatcher import dispatch

        # model arg comes through from the standalone but the dispatcher
        # picks the model off the selected agent (M.A.V.E.N.'s qwen2.5:7b).
        # We keep the standalone's `model` field in the request for future
        # agent-aware overrides, but don't forward it here — V.I.G.I.L.
        # guardrail rejects unknown dispatch kwargs.
        _ = model  # noqa: F841 — reserved for phase 3
        result = dispatch(
            capability=capability,
            prompt=prompt,
            system_prompt=system,
        )
    except Exception as e:
        log.exception("maven dispatch failed for user %s", user_id)
        return jsonify({"error": f"dispatch failed: {e}"}), 502

    if not getattr(result, "success", False):
        return (
            jsonify(
                {
                    "error": getattr(result, "error", "dispatch returned non-success"),
                    "tier": getattr(result, "tier", None),
                }
            ),
            502,
        )

    return (
        jsonify(
            {
                "response": getattr(result, "response", ""),
                "agent": getattr(result, "agent", None),
                "tier": getattr(result, "tier", None),
                "cost": float(getattr(result, "cost", 0.0) or 0.0),
                "user": user["username"],
            }
        ),
        200,
    )
