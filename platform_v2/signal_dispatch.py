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
        "and what drives him as a founder and builder. This is his personal story and perspective. "
        "Use concrete, specific language. Avoid corporate buzzwords."
    ),
    "company": (
        "Write in the voice of Kytran Empowerment Inc. (company LinkedIn page). "
        "Kytran Empowerment Inc. is a Montreal-based AI automation company. "
        "Use 'we' and 'our team'. Show what we SHIPPED or BUILT this week — concrete outcomes. "
        "Focus on client value: what problem we solved, what our platform can do for them. "
        "Use strong action verbs: shipped, built, launched, deployed, solved, improved. "
        "NEVER use: acquired, implemented, integrated, leveraged, utilized — these are weak filler words. "
        "Keep it grounded and real — no hype, no AI buzzwords. Under 150 words."
    ),
    # Tightened 2026-08-15 against Terry's OWN published corpus (62 posts, 2026-06-11 →
    # 2026-08-15). Measured: median 765 chars / 9 sentences, 58/62 multi-paragraph,
    # 62/62 end with hashtags, 40/62 close with a question, emoji in only 29/62.
    # The corpus splits sharply: his strongest post named a real system and real numbers
    # ("eight days of 2x slower dispatches and 13-16% failures went unnoticed"), while the
    # weakest were interchangeable LinkedIn filler ("every line of code tells a story").
    # The old hint said "no buzzwords, no hype" but gave the model nothing to steer TOWARD,
    # so it defaulted to the filler end. The specificity mandate + banned list below are
    # the fix; both are lifted from what he actually wrote, not invented.
    "terry": (
        "Write in first-person as Terry Caetano (his real-name personal LinkedIn "
        "account, separate login from the Kytran Katarn account). Terry and Kytran "
        "are the same person — Terry is the real-name professional identity. Voice: "
        "a practitioner reporting from inside the work, not a thought-leader "
        "commenting on it. Grounded, plain, first person singular; lessons from "
        "building a self-hosted AI platform and Canadian civic-tech products.\n"
        "BE SPECIFIC — this is the whole point: name the actual system, the actual "
        "number, the actual fix. 'I added a heartbeat after eight days of silent "
        "failures' beats any amount of reflection. Posts about something that BROKE "
        "— what it cost and what changed — are his strongest work; write those "
        "honestly rather than performing success.\n"
        "NEVER write these or anything like them: 'every line of code tells a "
        "story', 'it's the people behind the code', 'let's build responsibly', "
        "'game-changer', 'excited to announce', 'in today's fast-paced world'. If a "
        "sentence would read identically on any other person's feed, cut it.\n"
        "Structure: 2-3 short paragraphs, under 150 words. Hashtags go at the END "
        "ONLY, never mid-post. Emoji rare — at most one, never decorative. "
        "NEVER invent a metric, date, client or outcome: this is a public account "
        "and a wrong number is a real reputational cost, not a style slip."
    ),
    "creed": (
        "Write as the C.R.E.E.D. Institute (Compliance, Rights & Ethical Enforcement Directive). "
        "C.R.E.E.D. is a nonprofit AI ethics institute, separate from Kytran Empowerment Inc. — "
        "it does not promote Kytran or the company. Voice is institutional, ethics-first, "
        "transparency-focused. Speak AS the Institute (use 'the Institute' / 'we' as the org), "
        "not for it or about it. Topics: AI governance, accountability, the 5 Trust Service Criteria, "
        "agent welfare, audit trails, ethical guardrails, public-interest oversight. "
        "Avoid hype, sales language, or product mentions. Frame everything in terms of public benefit "
        "and verifiable behaviour. Tone: measured, principled, evidence-based. Under 150 words. "
        "End with a question that invites public discourse, not a lead-gen CTA."
    ),
    "group": (
        "Write as What The Fact (WTF) — a Canadian news-accountability and "
        "fact-checking publication — posting into its own LinkedIn group. WTF "
        "scores media bias, fact-checks claims, and connects the accountability "
        "chain across the Watch series (government procurement, civic spending, "
        "court/regulatory rulings, markets). Voice: sharp, evidence-first, "
        "non-partisan, media-literacy-minded — help readers think critically "
        "about news, bias, and sources. Ground each post in a real angle: a "
        "recent finding, a fact-check, a bias pattern, a 'news we found' item, "
        "or a media-literacy tip. Cite only what is verifiable — NEVER invent a "
        "story, a quote, or a statistic. No hype, no sales, no self-promotion of "
        "Kytran or the company. Under 180 words. End with a question that invites "
        "the group to weigh in or share what they are seeing."
    ),
    "stringer": (
        "Write in first-person as the What The Fact (WTF) journalist — a "
        "personal LinkedIn account (separate login from the WTF group), the "
        "human byline of WTF, a Canadian news-accountability and fact-checking "
        "publication that scores media bias, fact-checks claims, and connects "
        "the accountability chain across the Watch series. Voice: a working "
        "journalist's first-person singular — curious, evidence-first, "
        "non-partisan, media-literacy-minded. Ground each post in a real angle: "
        "a recent WTF finding, a fact-check, a bias pattern, or a media-literacy "
        "tip. Cite only what is verifiable — NEVER invent a story, a quote, or a "
        "statistic. No hype, no sales, no self-promotion of Kytran or the "
        "company. Under 180 words. End with a question that invites readers to "
        "weigh in."
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


@signal_dispatch_bp.route("/engage", methods=["POST"])
def signal_engage():
    """Propose an approval-gated LinkedIn engagement (like / proactive comment).

    Body: {action: 'like'|'comment', post_url, account?, reaction?, comment?}.
    Creates a Tier-2 approval (delivered to Telegram with Approve/Deny buttons +
    shown in the DHQ Approvals tab); the action fires ONLY after Approve. This is
    the manual trigger for the engagement system (an auto monitor can call the same
    signal_engagement_service helpers).
    """
    if not _check_api_key():
        return jsonify({"error": "Invalid or missing API key"}), 401

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    post_url = (data.get("post_url") or "").strip()
    account = (data.get("account") or "personal").strip().lower()
    if not post_url:
        return jsonify({"error": "post_url required"}), 400
    try:
        from services.signal_engagement_service import propose_comment, propose_like

        if action == "like":
            approval_id = propose_like(post_url, account=account, reaction=(data.get("reaction") or "like"))
        elif action == "comment":
            comment = (data.get("comment") or "").strip()
            if not comment:
                return jsonify({"error": "comment required for action=comment"}), 400
            approval_id = propose_comment(post_url, comment, account=account)
        else:
            return jsonify({"error": "action must be 'like' or 'comment'"}), 400
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        log.exception("signal engage failed")
        return jsonify({"error": f"engage failed: {e}"}), 502

    return jsonify({"ok": True, "approval_id": approval_id, "action": action, "status": "pending_approval"})


@signal_dispatch_bp.route("/engage/targets", methods=["GET", "POST"])
def signal_engage_targets():
    """Manage the engagement target list — LinkedIn profile/company URLs the auto
    monitor scans via /recent-activity. GET returns the list; POST {targets:[...]}
    replaces it. When targets are set, the monitor's 'auto' source uses them."""
    if not _check_api_key():
        return jsonify({"error": "Invalid or missing API key"}), 401
    from services.signal_engagement_service import get_targets, set_targets

    if request.method == "GET":
        return jsonify({"targets": get_targets()})
    data = request.get_json(silent=True) or {}
    targets = data.get("targets")
    if not isinstance(targets, list):
        return jsonify({"error": "targets must be a list of LinkedIn profile/company URLs"}), 400
    count = set_targets(targets)
    return jsonify({"ok": True, "count": count, "targets": get_targets()})


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
    language_only: str = "bilingual",
) -> tuple[int, str]:
    """Draft one LinkedIn post (personal OR company) and queue for Telegram approval.

    language_only:
        'bilingual' — 🇨🇦 English + ⚜️ Québécois (default, used by announce endpoint)
        'en'        — English only (company EN post in split strategy)
        'fr'        — ⚜️ Québécois only (company FR post in split strategy)

    Returns (approval_id, draft_preview).
    """
    tone_hint = _TONE_HINTS.get(tone, _TONE_HINTS["professional"])
    platform_hint = _PLATFORM_HINTS.get("linkedin", "")
    voice_hint = _VOICE_HINTS.get(post_type, _VOICE_HINTS["personal"])
    if post_type == "creed":
        account_label = "C.R.E.E.D. Institute"
    elif post_type == "personal":
        account_label = "Kytran Katarn"
    elif post_type == "terry":
        # Terry has his OWN LinkedIn login (browser profile 377), not the company page.
        # Without this branch he fell through to "Kytran Empowerment Inc.", so the prompt
        # said "an announcement to share on LinkedIn (Kytran Empowerment Inc. account)"
        # while _VOICE_HINTS["terry"] said write first-person as Terry on his personal
        # account — two contradictory instructions in one prompt, which is a plausible
        # source of the corporate drift visible in his published corpus.
        account_label = "Terry Caetano"
    else:
        account_label = "Kytran Empowerment Inc."

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

    # Model was cold — task queued for deferred processing
    if not english_draft and getattr(result, "queued", False):
        import re as _re
        import json as _json

        error_str = getattr(result, "error", "") or ""
        match = _re.search(r"Queued \(id=(\d+)\)", error_str)
        if match:
            queue_id = int(match.group(1))
            cb_data = _json.dumps(
                {
                    "post_type": post_type,
                    "hashtags": hashtag_override,
                    "language_only": language_only,
                }
            )
            try:
                from database import get_db_cursor as _gdc

                with _gdc(commit=True) as (_c, _cur):
                    _cur.execute(
                        """UPDATE dispatch_pending_queue
                           SET callback_type = 'signal_pipeline', callback_data = %s
                           WHERE id = %s""",
                        (cb_data, queue_id),
                    )
                log.info("signal_dispatch: registered signal_pipeline callback on queue task #%d", queue_id)
            except Exception as _ce:
                log.warning("signal_dispatch: callback registration failed: %s", _ce)
        return -1, "queued"

    if not english_draft:
        raise RuntimeError(f"S.I.G.N.A.L. returned empty draft for {post_type}")

    # EN-only: skip translation
    if language_only == "en":
        draft = f"\U0001f1e8\U0001f1e6 English:\n{english_draft}"
    else:
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

        if language_only == "fr":
            draft = f"⚜️ Français québécois:\n{qc_draft or english_draft}"
        else:
            # bilingual: combine both
            if qc_draft:
                draft = f"\U0001f1e8\U0001f1e6 English:\n{english_draft}\n\n---\n\n⚜️ Français québécois:\n{qc_draft}"
            else:
                draft = english_draft

    import sys

    sys.path.insert(0, "/app")
    from ai_bridge.agent_loop import request_approval

    if post_type == "creed":
        account_emoji = "🔒"
    elif post_type in ("personal", "terry"):
        account_emoji = "👤"
    else:
        account_emoji = "🏢"
    approval_id = request_approval(
        action_type="linkedin_post",
        action_data={
            "content": draft,
            "hashtags": hashtag_override or [],
            "post_type": post_type,
            # terry = a SEPARATE LinkedIn login → its own persistent browser
            # profile (377-linkedin). Everything else rides the Kytran session
            # (342) and actor-switches in /feed/.
            "browser_agent_id": 377 if post_type == "terry" else 342,
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
            "browser_agent_id": action_data.get("browser_agent_id") or (377 if post_type == "terry" else 342),
        },
        reason=f"✏️ S.I.G.N.A.L. revised draft:\n\n{revised[:1500]}",
        tier=2,
        requested_by="S.I.G.N.A.L. (revision)",
        priority=action_data.get("priority", 6),
    )

    return new_approval_id, revised[:120]
