"""S.I.G.N.A.L. dispatch endpoint — hub-side HTTP surface for KBS social
media content generation (Project #286).

Mirror of procure_dispatch.py — same JWT HS256 bearer auth, same Bridge
dispatch path. KBS calls this endpoint for all social content generation
so welfare-gating + cost tracking + GPU placement are honoured through
Department HQ (ADR-518).

Contract:

    POST /api/signal/dispatch
    Authorization: Bearer <kytran access_token>
    Content-Type: application/json

    {
        "capability": "social_content",   # required — social_content |
                                           # social_media | social_scheduling
        "prompt":     "...",              # required — topic / context
        "platform":   "linkedin",         # optional — linkedin | twitter | both
        "tone":       "professional"      # optional — professional | casual | bold
    }

Returns:

    {
        "response": "S.I.G.N.A.L. here. ...",
        "agent":    "S.I.G.N.A.L.",
        "tier":     "home",
        "cost":     0.0,
        "user":     "<username>"
    }

Supported capabilities (seeded in migration 353):
    social_content, social_media, social_scheduling
"""

from __future__ import annotations

import logging

import jwt
from flask import Blueprint, current_app, jsonify, request

from database import get_db_cursor

log = logging.getLogger("platform.signal_dispatch")

signal_dispatch_bp = Blueprint("signal_dispatch", __name__, url_prefix="/api/signal")

_PLATFORM_HINTS = {
    "linkedin": "Write in a professional, insight-driven tone suitable for LinkedIn. Use line breaks for readability. Include 2-3 relevant hashtags at the end.",
    "twitter": "Write a concise, punchy tweet under 280 characters. Direct and engaging. One or two relevant hashtags max.",
    "both": "Write two versions: one for LinkedIn (professional, 150-200 words) and one for Twitter (under 280 characters). Label each clearly.",
}

_TONE_HINTS = {
    "professional": "Maintain a professional, authoritative tone.",
    "casual": "Use a friendly, conversational tone. Approachable and relatable.",
    "bold": "Be bold and confident. Make a strong statement. Stand out.",
}


def _resolve_user_from_bearer() -> tuple[int | None, dict | str]:
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


@signal_dispatch_bp.route("/dispatch", methods=["POST"])
def dispatch_signal():
    user_id, user_or_err = _resolve_user_from_bearer()
    if user_id is None:
        return jsonify({"error": user_or_err}), 401
    user = user_or_err

    data = request.get_json(silent=True) or {}
    capability = (data.get("capability") or "social_content").strip()
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt required"}), 400

    prompt = prompt[:8000]
    platform = (data.get("platform") or "").strip().lower()
    tone = (data.get("tone") or "professional").strip().lower()

    platform_hint = _PLATFORM_HINTS.get(platform, "")
    tone_hint = _TONE_HINTS.get(tone, _TONE_HINTS["professional"])

    full_prompt = prompt
    if platform_hint or tone_hint:
        full_prompt = f"{prompt}\n\n[Instructions: {tone_hint} {platform_hint}]".strip()

    system = None
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT system_prompt FROM agents WHERE name = %s",
                ("S.I.G.N.A.L.",),
            )
            row = cur.fetchone()
            if row and row.get("system_prompt"):
                system = row["system_prompt"]
    except Exception:
        log.exception("failed to load S.I.G.N.A.L. system_prompt; continuing without")

    try:
        from tools.department_hq.services.department_dispatcher import dispatch

        result = dispatch(
            capability=capability,
            prompt=full_prompt,
            system_prompt=system,
        )
    except Exception as e:
        log.exception("signal dispatch failed for user %s", user_id)
        return jsonify({"error": f"dispatch failed: {e}"}), 502

    if not getattr(result, "success", False):
        return (
            jsonify(
                {
                    "error": getattr(result, "error", "dispatch returned non-success"),
                    "department": getattr(result, "department", None),
                }
            ),
            502,
        )

    meta = getattr(result, "metadata", None) or {}
    cost = float(meta.get("cost", 0.0) or 0.0)
    agent_id = getattr(result, "agent_id", None)
    agent_label = getattr(result, "agent_name", None)
    if agent_id:
        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    "SELECT name FROM agents WHERE id = %s",
                    (agent_id,),
                )
                row = cur.fetchone()
                if row:
                    agent_label = row.get("name") or agent_label
        except Exception:
            log.exception("agent name lookup failed for id=%s", agent_id)

    return (
        jsonify(
            {
                "response": getattr(result, "response", ""),
                "agent": agent_label,
                "agent_id": agent_id,
                "model": getattr(result, "model_used", None),
                "department": meta.get("agent_department") or getattr(result, "department", None),
                "duration_ms": int(getattr(result, "duration_ms", 0) or 0),
                "cost": cost,
                "user": user["username"],
            }
        ),
        200,
    )
