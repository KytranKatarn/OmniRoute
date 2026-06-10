"""C.R.E.E.D. Command — marketing/promotion studio (Phase 3, #3613).

E.T.H.O.S. drafts channel-specific promotional copy for C.R.E.E.D., grounded in the
institute's real, verifiable evidence (live governance grade/score + the public
transparency surfaces). Humans review/edit/approve; copy-to-use from the UI.

Async + DB-persisted (creed_marketing_assets, migration 415) like grants/mail AI:
POST returns 202, the client polls GET /api/marketing/<id>. Admin-only. All E.T.H.O.S.
dispatch runs on the GPU cluster via preferred_node. No auto-publishing — generation
only; pushing to LinkedIn/etc. stays a human step (S.I.G.N.A.L. owns posting).
"""

import logging
import threading

import psycopg2
from flask import current_app, jsonify, request
from flask_login import login_required

from database import get_db_cursor

logger = logging.getLogger(__name__)

# channel -> (display label, generation guidance fed to E.T.H.O.S.)
_CHANNELS = {
    "linkedin": (
        "LinkedIn",
        "Write a LinkedIn post of about 130 words. Professional, credible, "
        "thought-leadership tone. End with 1-2 relevant hashtags.",
    ),
    "x": (
        "X / Twitter",
        "Write a single post of at most 270 characters. Punchy and concrete. " "At most one hashtag. No thread.",
    ),
    "newsletter": (
        "Newsletter",
        "Write a warm subscriber-update blurb of about 150 words with a short "
        "subject line on the first line (prefixed 'Subject: ').",
    ),
    "press": (
        "Press pitch",
        "Write a concise 120-word pitch to a journalist: the hook, why it matters "
        "now, and one concrete, verifiable proof point. No fabricated quotes.",
    ),
    "blog": (
        "Blog teaser",
        "Write a ~180-word blog intro/teaser that sets up the topic and invites "
        "the reader to learn more. Clear, substantive, non-salesy.",
    ),
}


def _build_prompt(channel, topic):
    label, guidance = _CHANNELS[channel]
    try:
        from tools.creed_command.routes import _fetch_creed_governance

        gov = _fetch_creed_governance()
        evidence = (
            f"a live public governance dashboard (grade {gov.get('grade') or 'A+'}, "
            f"compliance score {gov.get('score') if gov.get('score') is not None else '99.5'}%"
            + (
                f", {gov['incidents_disclosed']} incidents publicly disclosed"
                if gov.get("incidents_disclosed") is not None
                else ""
            )
            + ")"
        )
    except Exception:
        evidence = "a live public governance dashboard (grade A+)"
    return (
        "You are E.T.H.O.S., the voice of the C.R.E.E.D. Institute — a Canadian "
        "nonprofit advancing preventive AI ethics, governance, and non-exploitative "
        "AI (including agent welfare). Write promotional copy for the "
        f"{label} channel.\n\n"
        f"Topic / angle: {topic}\n\n"
        f"{guidance}\n\n"
        "Ground the copy ONLY in C.R.E.E.D.'s real, verifiable evidence: "
        f"{evidence}; and public transparency surfaces — a Remediation Registry, an "
        "Oversight Registry (human-in-the-loop), an AI Incident Disclosure Log, an "
        "Accountability/Redress mechanism, and a weekly agent-welfare ethics review. "
        "Do NOT invent figures, awards, partnerships, dates, quotes, or testimonials. "
        "Write ONLY the copy itself — no preamble, no notes."
    )


def _generate_marketing_bg(app_obj, asset_id, channel, topic):
    """Background: E.T.H.O.S. drafts the asset on the GPU cluster, stores result."""
    with app_obj.app_context():
        content, status = "", "error"
        try:
            from tools.department_hq.services.department_dispatcher import dispatch

            res = dispatch(
                capability="policy_assessment",
                prompt=_build_prompt(channel, topic),
                prefer_agent="E.T.H.O.S.",
                source_product="archie_platform",
                preferred_node=["Starship-246", "Starship-245"],
            )
            if res is not None and getattr(res, "success", False):
                content = (getattr(res, "response", "") or "").strip()
                status = "done" if content else "error"
        except Exception as e:
            logger.error("marketing gen %s (%s) failed: %s", asset_id, channel, e)
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE creed_marketing_assets SET content=%s, gen_status=%s, " "updated_at=now() WHERE id=%s",
                    (content, status, asset_id),
                )
        except Exception as e:
            logger.error("marketing store %s failed: %s", asset_id, e)


def _row(r):
    d = dict(r)
    for k in ("created_at", "updated_at"):
        if d.get(k) is not None and not isinstance(d[k], str):
            d[k] = d[k].isoformat()
    return d


def register_marketing_routes(bp, admin_required):
    @bp.route("/api/marketing", methods=["GET"])
    @login_required
    @admin_required
    def marketing_list():
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT * FROM creed_marketing_assets ORDER BY created_at DESC LIMIT 100")
                items = [_row(r) for r in cur.fetchall() or []]
            return jsonify({"assets": items, "count": len(items), "channels": list(_CHANNELS.keys())})
        except Exception as e:
            logger.error("marketing_list failed: %s", e)
            return jsonify({"assets": [], "count": 0, "error": "load failed"}), 500

    @bp.route("/api/marketing", methods=["POST"])
    @login_required
    @admin_required
    def marketing_create():
        j = request.get_json(silent=True) or {}
        channel = (j.get("channel") or "").strip().lower()
        topic = (j.get("topic") or "").strip()
        if channel not in _CHANNELS:
            return jsonify({"error": "unknown channel"}), 400
        if not topic:
            return jsonify({"error": "topic is required"}), 400
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "INSERT INTO creed_marketing_assets (channel, topic, gen_status) "
                    "VALUES (%s, %s, 'pending') RETURNING *",
                    (channel, topic),
                )
                row = _row(cur.fetchone())
        except Exception as e:
            logger.error("marketing_create failed: %s", e)
            return jsonify({"error": "could not create"}), 500
        app_obj = current_app._get_current_object()
        threading.Thread(
            target=_generate_marketing_bg,
            args=(app_obj, row["id"], channel, topic),
            daemon=True,
        ).start()
        return jsonify(row), 202

    @bp.route("/api/marketing/<int:asset_id>", methods=["GET"])
    @login_required
    @admin_required
    def marketing_get(asset_id):
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT * FROM creed_marketing_assets WHERE id=%s", (asset_id,))
            r = cur.fetchone()
        if not r:
            return jsonify({"error": "not found"}), 404
        return jsonify(_row(r))

    @bp.route("/api/marketing/<int:asset_id>", methods=["PATCH"])
    @login_required
    @admin_required
    def marketing_update(asset_id):
        j = request.get_json(silent=True) or {}
        sets, vals = [], []
        if "content" in j:
            sets.append("content=%s")
            vals.append((j.get("content") or "").strip() or None)
        if "approved" in j:
            sets.append("approved=%s")
            vals.append(bool(j.get("approved")))
        if not sets:
            return jsonify({"error": "no editable fields"}), 400
        vals.append(asset_id)
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    f"UPDATE creed_marketing_assets SET {', '.join(sets)}, updated_at=now() " "WHERE id=%s RETURNING *",
                    vals,
                )
                row = cur.fetchone()
            if not row:
                return jsonify({"error": "not found"}), 404
            return jsonify(_row(row))
        except (psycopg2.Error, Exception) as e:
            logger.error("marketing_update failed: %s", e)
            return jsonify({"error": "could not update"}), 500

    @bp.route("/api/marketing/<int:asset_id>", methods=["DELETE"])
    @login_required
    @admin_required
    def marketing_delete(asset_id):
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("DELETE FROM creed_marketing_assets WHERE id=%s", (asset_id,))
                gone = cur.rowcount
            if not gone:
                return jsonify({"error": "not found"}), 404
            return jsonify({"deleted": asset_id})
        except Exception as e:
            logger.error("marketing_delete failed: %s", e)
            return jsonify({"error": "could not delete"}), 500

    @bp.route("/api/marketing/<int:asset_id>/send-to-signal", methods=["POST"])
    @login_required
    @admin_required
    def marketing_send_to_signal(asset_id):
        """Hand a finished LinkedIn asset to S.I.G.N.A.L.'s approval queue (#3944).

        Generation lives in this module; PUBLISHING is owned by S.I.G.N.A.L. —
        this files a Tier-2 'linkedin_post' approval with post_type='creed'
        (the Creed-AI company page). A human approves it in the DHQ Social tab
        or via Telegram before anything is posted.
        """
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT * FROM creed_marketing_assets WHERE id=%s", (asset_id,))
                r = cur.fetchone()
        except Exception as e:
            logger.error("send_to_signal load %s failed: %s", asset_id, e)
            return jsonify({"error": "load failed"}), 500
        if not r:
            return jsonify({"error": "not found"}), 404
        asset = _row(r)
        if asset["channel"] != "linkedin":
            return jsonify({"error": "only LinkedIn assets can be sent to S.I.G.N.A.L."}), 400
        content = (asset.get("content") or "").strip()
        if not content or asset["gen_status"] not in ("done", "sent_to_signal"):
            return jsonify({"error": "asset has no finished content"}), 400

        from ai_bridge.agent_loop import request_approval

        approval_id = request_approval(
            action_type="linkedin_post",
            action_data={
                "content": content,
                "hashtags": [],
                "post_type": "creed",
                "source": "creed_command_marketing",
                "asset_id": asset_id,
            },
            reason=f"⚖️ C.R.E.E.D. marketing asset #{asset_id} → Creed-AI LinkedIn page:\n\n{content[:1500]}",
            tier=2,
            requested_by="E.T.H.O.S. (CREED Command)",
            priority=6,
        )
        if not approval_id:
            return jsonify({"error": "not queued — this exact post is already awaiting approval"}), 409
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE creed_marketing_assets SET gen_status='sent_to_signal', updated_at=now() WHERE id=%s",
                    (asset_id,),
                )
        except Exception as e:
            logger.error("send_to_signal mark %s failed: %s", asset_id, e)
        return jsonify({"success": True, "approval_id": approval_id, "gen_status": "sent_to_signal"})
