"""Email campaign CRUD, send, and stats routes."""

import logging

from flask import g, jsonify, request
from flask_login import login_required

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_campaign_routes(bp):
    """Attach email campaign routes to the blueprint."""

    @bp.route("/api/campaigns", methods=["GET"])
    @login_required
    @require_module("communications")
    def campaign_list():
        """List email campaigns with pagination."""
        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(100, max(1, request.args.get("per_page", 25, type=int)))
        offset = (page - 1) * per_page
        status = request.args.get("status")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            where = ["1=1"]
            params = []
            if status:
                where.append("ec.status = %s")
                params.append(status)

            cur.execute(
                f"""
                SELECT ec.id, ec.name, ec.subject, ec.status,
                       ec.scheduled_at, ec.sent_at, ec.created_at, ec.updated_at,
                       ecs.total_sent, ecs.delivered, ecs.opened,
                       ecs.clicked, ecs.bounced, ecs.unsubscribed
                FROM email_campaigns ec
                LEFT JOIN email_campaign_stats ecs ON ecs.campaign_id = ec.id
                WHERE {' AND '.join(where)}
                ORDER BY ec.created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            campaigns = cur.fetchall()

            cur.execute(
                f"SELECT COUNT(*) AS total FROM email_campaigns ec WHERE {' AND '.join(where)}",
                params,
            )
            total = cur.fetchone()["total"]

        return jsonify(
            {
                "campaigns": campaigns,
                "total": total,
                "page": page,
                "per_page": per_page,
            }
        )

    @bp.route("/api/campaigns", methods=["POST"])
    @login_required
    @require_module("communications")
    def campaign_create():
        """Create a new email campaign (draft)."""
        data = request.get_json(force=True)
        name = data.get("name", "").strip()
        subject = data.get("subject", "").strip()

        if not name or not subject:
            return jsonify({"error": "name and subject are required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO email_campaigns
                    (name, subject, html_content, text_content, segment_id, status)
                VALUES (%s, %s, %s, %s, %s, 'draft')
                RETURNING id, name, subject, status, created_at
                """,
                (
                    name,
                    subject,
                    data.get("html_content", ""),
                    data.get("text_content", ""),
                    data.get("segment_id"),
                ),
            )
            campaign = dict(cur.fetchone())

            # Create empty stats row
            cur.execute(
                "INSERT INTO email_campaign_stats (campaign_id) VALUES (%s)",
                (campaign["id"],),
            )

        event_bus.emit(
            "campaign.created",
            {"campaign_id": campaign["id"], "name": name},
            tenant_id=g.tenant_id,
        )

        return jsonify(campaign), 201

    @bp.route("/api/campaigns/<int:campaign_id>", methods=["GET"])
    @login_required
    @require_module("communications")
    def campaign_detail(campaign_id):
        """Get full campaign details with stats."""
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT ec.*, ecs.total_sent, ecs.delivered, ecs.opened,
                       ecs.clicked, ecs.bounced, ecs.unsubscribed
                FROM email_campaigns ec
                LEFT JOIN email_campaign_stats ecs ON ecs.campaign_id = ec.id
                WHERE ec.id = %s
                """,
                (campaign_id,),
            )
            campaign = cur.fetchone()

        if not campaign:
            return jsonify({"error": "Campaign not found"}), 404

        return jsonify(dict(campaign))

    @bp.route("/api/campaigns/<int:campaign_id>", methods=["PUT"])
    @login_required
    @require_module("communications")
    def campaign_update(campaign_id):
        """Update a draft campaign."""
        data = request.get_json(force=True)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            # Only allow updates on draft campaigns
            cur.execute(
                "SELECT status FROM email_campaigns WHERE id = %s",
                (campaign_id,),
            )
            existing = cur.fetchone()
            if not existing:
                return jsonify({"error": "Campaign not found"}), 404
            if existing["status"] != "draft":
                return jsonify({"error": "Only draft campaigns can be updated"}), 400

            cur.execute(
                """
                UPDATE email_campaigns
                SET name = COALESCE(%s, name),
                    subject = COALESCE(%s, subject),
                    html_content = COALESCE(%s, html_content),
                    text_content = COALESCE(%s, text_content),
                    segment_id = COALESCE(%s, segment_id),
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id, name, subject, status, updated_at
                """,
                (
                    data.get("name"),
                    data.get("subject"),
                    data.get("html_content"),
                    data.get("text_content"),
                    data.get("segment_id"),
                    campaign_id,
                ),
            )
            campaign = dict(cur.fetchone())

        return jsonify(campaign)

    @bp.route("/api/campaigns/<int:campaign_id>/send", methods=["POST"])
    @login_required
    @require_module("communications")
    def campaign_send(campaign_id):
        """Queue a campaign for sending via Hostinger Reach."""
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                "SELECT id, status, name FROM email_campaigns WHERE id = %s",
                (campaign_id,),
            )
            campaign = cur.fetchone()
            if not campaign:
                return jsonify({"error": "Campaign not found"}), 404
            if campaign["status"] not in ("draft", "scheduled"):
                return (
                    jsonify({"error": "Campaign already sent or cancelled"}),
                    400,
                )

            cur.execute(
                """
                UPDATE email_campaigns
                SET status = 'sending', sent_at = NOW(), updated_at = NOW()
                WHERE id = %s
                RETURNING id, status, sent_at
                """,
                (campaign_id,),
            )
            result = dict(cur.fetchone())

        event_bus.emit(
            "campaign.sent",
            {"campaign_id": campaign_id, "name": campaign["name"]},
            tenant_id=g.tenant_id,
        )

        return jsonify(result)

    @bp.route("/api/campaigns/<int:campaign_id>/stats", methods=["GET"])
    @login_required
    @require_module("communications")
    def campaign_stats(campaign_id):
        """Get delivery stats for a campaign."""
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT ecs.*, ec.name, ec.subject, ec.status AS campaign_status
                FROM email_campaign_stats ecs
                JOIN email_campaigns ec ON ec.id = ecs.campaign_id
                WHERE ecs.campaign_id = %s
                """,
                (campaign_id,),
            )
            stats = cur.fetchone()

        if not stats:
            return jsonify({"error": "Stats not found"}), 404

        return jsonify(dict(stats))
