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

_VOICE_HINTS = {
    "personal": (
        "Write in first-person as Kytran Katarn (personal LinkedIn account). "
        "Focus on Kytran as an individual — his journey, goals, personal vision, lessons learned, "
        "and what drives him as a founder and builder. This is his personal story and perspective."
    ),
    "company": (
        "Write in the voice of Kytran Empowerment Inc. (company LinkedIn page). "
        "Use 'we' and 'our team'. Focus on the company's brand, services, capabilities, "
        "and value to clients — outreach, advertising what the company does and offers."
    ),
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


def _draft_and_queue(
    announcement: str,
    post_type: str,
    tone: str,
    hashtag_override: list,
    priority: int,
    system: str | None,
) -> tuple[int, str]:
    """Draft one LinkedIn post (personal OR company) and queue for Telegram approval.

    Returns (approval_id, draft_preview).
    """
    tone_hint = _TONE_HINTS.get(tone, _TONE_HINTS["professional"])
    platform_hint = _PLATFORM_HINTS.get("linkedin", "")
    voice_hint = _VOICE_HINTS.get(post_type, _VOICE_HINTS["personal"])
    account_label = "Kytran Katarn" if post_type == "personal" else "Kytran Empowerment Inc."

    hashtag_line = (
        f"Use these hashtags: {', '.join(hashtag_override)}"
        if hashtag_override
        else "Pick 3-4 relevant hashtags from: #AI #ARCHIE #BuildingInPublic #Montreal #KytranEmpowerment"
    )
    # Step 1: S.I.G.N.A.L. writes the English draft
    prompt = (
        f"Kytran has an announcement to share on LinkedIn ({account_label} account).\n\n"
        f"Announcement:\n{announcement}\n\n"
        f"Write the post in English only — a translator will handle the French version. "
        f"{voice_hint} {tone_hint} {platform_hint}\n"
        f"Under 200 words. End with an engagement question.\n"
        f"{hashtag_line}"
    )

    from tools.department_hq.services.department_dispatcher import dispatch

    result = dispatch(
        capability="social_post_draft",
        prompt=prompt,
        system_prompt=system,
        prefer_agent="S.I.G.N.A.L.",
    )

    english_draft = (getattr(result, "response", "") or "").strip()
    if not english_draft:
        raise RuntimeError(f"S.I.G.N.A.L. returned empty draft for {post_type}")

    # Step 2: R.O.S.E.T.T.A. translates to Québécois French
    qc_draft = ""
    try:
        t_result = dispatch(
            capability="translate",
            prompt=(
                f"Translate this LinkedIn post to Québécois French "
                f"(joual/québécois dialect — NOT France French). "
                f"Keep tone, voice, hashtags, and engagement question intact.\n\n{english_draft}"
            ),
            prefer_agent="R.O.S.E.T.T.A.",
        )
        if t_result and t_result.success:
            qc_draft = (t_result.response or "").strip()
    except Exception as _te:
        log.warning("_draft_and_queue: R.O.S.E.T.T.A. translation failed: %s", _te)

    # Combine into bilingual draft
    if qc_draft:
        draft = (
            f"\U0001f1e8\U0001f1e6 English:\n{english_draft}"
            f"\n\n---\n\n"
            f"\U0001f1e8\U0001f1e6\U0001f1eb\U0001f1f7 Français québécois:\n{qc_draft}"
        )
    else:
        draft = english_draft

    import sys

    sys.path.insert(0, "/app")
    from ai_bridge.agent_loop import request_approval

    account_emoji = "👤" if post_type == "personal" else "🏢"
    approval_id = request_approval(
        action_type="linkedin_post",
        action_data={
            "content": draft,
            "hashtags": hashtag_override or [],
            "post_type": post_type,
            "browser_agent_id": 342,
            "priority": priority,
        },
        reason=f"📣 {account_emoji} {account_label} draft:\n\n{draft[:1500]}",
        tier=2,
        requested_by="Kytran (via /api/signal/announce)",
        priority=priority,
    )
    return approval_id, draft[:150]


@signal_dispatch_bp.route("/announce", methods=["POST"])
def announce():
    """Kytran → S.I.G.N.A.L. feature/announcement post trigger.

    You tell S.I.G.N.A.L. what happened. She turns it into polished
    LinkedIn posts and sends them to your Telegram for approval.

    Body:
        announcement  (str, required) — what you want to announce
        post_type     (str, optional) — "personal" | "company" | "both" (default: "both")
        tone          (str, optional) — "professional" | "casual" | "bold"
        hashtags      (list, optional) — override hashtag suggestions
        priority      (int, optional) — Telegram priority 1-10 (default 6)

    Returns: {"queued": true, "approvals": [{post_type, approval_id, preview}, ...]}
    Auth: Bearer <ARCHIE_API_KEY>
    """
    if not _check_api_key():
        return jsonify({"error": "Invalid or missing API key"}), 401

    data = request.get_json(silent=True) or {}
    announcement = (data.get("announcement") or "").strip()
    if not announcement:
        return jsonify({"error": "announcement is required"}), 400

    post_type = (data.get("post_type") or "both").strip()
    tone = (data.get("tone") or "professional").strip()
    hashtag_override = data.get("hashtags", [])
    priority = int(data.get("priority", 6))

    # Determine which accounts to draft for
    types_to_draft = ["personal", "company"] if post_type == "both" else [post_type]

    # Load S.I.G.N.A.L.'s system prompt once
    system = None
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute("SELECT system_prompt FROM agents WHERE name = %s", ("S.I.G.N.A.L.",))
            row = cur.fetchone()
            if row and row.get("system_prompt"):
                system = row["system_prompt"]
    except Exception:
        pass

    # Stagger delay between accounts so Telegram approvals don't arrive simultaneously.
    # personal → immediate, company → delayed by SIGNAL_STAGGER_MINUTES (default 180 = 3h).
    import threading

    stagger_minutes = int(os.getenv("SIGNAL_STAGGER_MINUTES", "180"))
    approvals = []

    try:
        first_type = types_to_draft[0]
        approval_id, preview = _draft_and_queue(announcement, first_type, tone, hashtag_override, priority, system)
        approvals.append({"post_type": first_type, "approval_id": approval_id, "preview": preview})
        log.info("Announcement queued now (id=%s, type=%s)", approval_id, first_type)
    except Exception as exc:
        log.error("announce: first draft failed: %s", exc)
        return jsonify({"error": str(exc)}), 500

    if len(types_to_draft) == 2:
        second_type = types_to_draft[1]
        delay_secs = stagger_minutes * 60

        # Capture locals for the background thread closure
        _ann, _tone, _hashtags, _prio, _sys = announcement, tone, hashtag_override, priority, system

        def _queue_second():
            try:
                aid, prev = _draft_and_queue(_ann, second_type, _tone, _hashtags, _prio, _sys)
                log.info("Staggered draft queued (id=%s, type=%s, delay=%dm)", aid, second_type, stagger_minutes)
            except Exception as e:
                log.error("Staggered draft failed (type=%s): %s", second_type, e)

        t = threading.Timer(delay_secs, _queue_second)
        t.daemon = True
        t.start()
        approvals.append(
            {
                "post_type": second_type,
                "approval_id": None,
                "preview": f"Drafting in ~{stagger_minutes // 60}h",
                "delayed": True,
            }
        )

    return jsonify({"queued": True, "approvals": approvals}), 202


@signal_dispatch_bp.route("/tender-alert", methods=["POST"])
def tender_alert():
    """Gov Watch → S.I.G.N.A.L. tender post trigger.

    Called by Gov Watch (VPS) when a federal tender with value > $1M is ingested.
    S.I.G.N.A.L. drafts an urgent LinkedIn post → priority-8 Telegram approval.

    Body: {title, value, agency, deadline, url, description}
    Auth: Bearer <ARCHIE_API_KEY>
    """
    if not _check_api_key():
        return jsonify({"error": "Invalid or missing API key"}), 401

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400

    tender = {
        "title": title,
        "value": data.get("value", 0),
        "agency": (data.get("agency") or "").strip(),
        "deadline": (data.get("deadline") or "").strip(),
        "url": (data.get("url") or "https://canadabuys.canada.ca").strip(),
        "description": (data.get("description") or "")[:500],
    }

    try:
        import threading
        from services.agent_jobs import signal_tender_post

        threading.Thread(
            target=signal_tender_post,
            args=(tender,),
            daemon=True,
            name="tender-post",
        ).start()

        log.info("Tender alert queued: %s ($%s)", title, tender["value"])
        return jsonify({"queued": True, "tender": title}), 202

    except Exception as exc:
        log.exception("tender_alert failed")
        return jsonify({"error": str(exc)}), 502


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


def redraft_with_suggestion(original_draft: str, suggestion: str, action_data: dict):
    """Re-dispatch to S.I.G.N.A.L. with user feedback and re-queue for Telegram approval.

    Called from telegram_gateway when user presses Suggest and sends their note.
    Returns (new_approval_id, preview_str).
    """
    system = None
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute("SELECT system_prompt FROM agents WHERE name = %s", ("S.I.G.N.A.L.",))
            row = cur.fetchone()
            if row and row.get("system_prompt"):
                system = row["system_prompt"]
    except Exception:
        pass

    prompt = (
        f"You previously wrote a LinkedIn draft. The reviewer has a suggestion.\n\n"
        f"Original draft:\n{original_draft}\n\n"
        f"Reviewer's suggestion:\n{suggestion}\n\n"
        f"Please revise the draft based on this feedback. Keep the bilingual format "
        f"(🇨🇦 English: / 🇫🇷 Français :) and the same structure. "
        f"Under 200 words per version. First-person as Kytran."
    )

    from tools.department_hq.services.department_dispatcher import dispatch

    result = dispatch(
        capability="social_post_draft",
        prompt=prompt,
        system_prompt=system,
        prefer_agent="S.I.G.N.A.L.",
    )

    revised = (getattr(result, "response", "") or "").strip()
    if not revised:
        raise RuntimeError("S.I.G.N.A.L. returned empty revision")

    post_type = action_data.get("post_type", "personal")
    hashtags = action_data.get("hashtags", [])

    import sys

    sys.path.insert(0, "/app")
    from ai_bridge.agent_loop import request_approval

    new_approval_id = request_approval(
        action_type="linkedin_post",
        action_data={
            "content": revised,
            "hashtags": hashtags,
            "post_type": post_type,
            "browser_agent_id": action_data.get("browser_agent_id", 342),
        },
        reason=f"✏️ S.I.G.N.A.L. revised draft:\n\n{revised[:1500]}",
        tier=2,
        requested_by="S.I.G.N.A.L. (revision)",
        priority=action_data.get("priority", 6),
    )

    return new_approval_id, revised[:120]
