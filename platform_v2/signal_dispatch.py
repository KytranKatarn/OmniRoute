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
import os

from flask import Blueprint, jsonify, request

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


def _check_api_key() -> bool:
    """Validate Bearer API key against ARCHIE_API_KEY env var."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        auth = auth[7:]
    valid = os.getenv("ARCHIE_API_KEY", "dev-api-key-change-in-production")
    return auth == valid


@signal_dispatch_bp.route("/dispatch", methods=["POST"])
def dispatch_signal():
    if not _check_api_key():
        return jsonify({"error": "Invalid or missing API key"}), 401

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
        log.exception("signal dispatch failed")
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
                "source": "kbs",
            }
        ),
        200,
    )


@signal_dispatch_bp.route("/draft-notify", methods=["POST"])
def draft_notify():
    """Send a social draft to Telegram for quick approve/discard.

    Called by KBS after generating and saving a draft post.
    Sends the content as a Telegram message with inline buttons.

    Body: {content, platform, account_name, draft_id, tenant_id}
    """
    if not _check_api_key():
        return jsonify({"error": "Invalid or missing API key"}), 401

    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()[:1000]
    platform = (data.get("platform") or "social").strip()
    account_name = (data.get("account_name") or "").strip()
    draft_id = data.get("draft_id")
    tenant_id = data.get("tenant_id")

    if not content or draft_id is None or tenant_id is None:
        return jsonify({"error": "content, draft_id, tenant_id required"}), 400

    platform_label = {"linkedin": "LinkedIn", "twitter": "Twitter / X", "both": "LinkedIn + Twitter"}.get(
        platform, platform.title()
    )
    preview = content[:280] + ("…" if len(content) > 280 else "")

    title = f"✨ S.I.G.N.A.L. Draft — {platform_label}"
    if account_name:
        title += f" ({account_name})"

    message = f"{preview}"

    buttons = [
        {"text": "✅ Post Now", "callback_data": f"social_pub_{draft_id}_{tenant_id}"},
        {"text": "🗑 Discard", "callback_data": f"social_dis_{draft_id}_{tenant_id}"},
    ]

    try:
        from services.telegram_service import send_with_buttons

        send_with_buttons(
            category="social_draft",
            title=title,
            message=message,
            buttons=buttons,
        )
        return jsonify({"sent": True, "draft_id": draft_id}), 200
    except Exception as e:
        log.exception("draft_notify send failed")
        return jsonify({"error": str(e)}), 502
