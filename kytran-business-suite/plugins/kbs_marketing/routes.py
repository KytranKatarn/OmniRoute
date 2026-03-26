"""Marketing Dashboard plugin routes — campaigns, leads, funnel, cross-plugin analytics."""

import logging

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_routes(bp):
    """Attach all Marketing routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("marketing")
    def index():
        return render_template("marketing.html")

    # ------------------------------------------------------------------
    # Overview — aggregated cross-plugin metrics
    # ------------------------------------------------------------------

    @bp.route("/api/overview")
    @login_required
    @require_module("marketing")
    def overview():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            # CRM contacts (required dependency)
            try:
                cur.execute("SELECT COUNT(*) FROM crm_customers")
                total_contacts = cur.fetchone()["count"]
            except Exception:
                conn.rollback()
                total_contacts = 0

            # Social posts (optional — social plugin may not be enabled)
            try:
                cur.execute("SELECT COUNT(*) FROM social_posts")
                total_posts = cur.fetchone()["count"]
            except Exception:
                conn.rollback()
                total_posts = 0

            # Content documents (optional — content studio may not be enabled)
            try:
                cur.execute("SELECT COUNT(*) FROM content_documents")
                total_documents = cur.fetchone()["count"]
            except Exception:
                conn.rollback()
                total_documents = 0

            # Leads by stage
            try:
                cur.execute(
                    """
                    SELECT stage, COUNT(*) AS cnt
                    FROM marketing_leads
                    GROUP BY stage
                    """
                )
                rows = cur.fetchall()
                leads_by_stage = {r["stage"]: r["cnt"] for r in rows}
            except Exception:
                conn.rollback()
                leads_by_stage = {}

            # Active campaigns
            try:
                cur.execute(
                    "SELECT COUNT(*) FROM marketing_campaigns WHERE status = 'active'"
                )
                active_campaigns = cur.fetchone()["count"]
            except Exception:
                conn.rollback()
                active_campaigns = 0

        return jsonify(
            {
                "total_contacts": total_contacts,
                "total_posts": total_posts,
                "total_documents": total_documents,
                "leads_by_stage": leads_by_stage,
                "active_campaigns": active_campaigns,
            }
        )

    # ------------------------------------------------------------------
    # Funnel
    # ------------------------------------------------------------------

    @bp.route("/api/funnel")
    @login_required
    @require_module("marketing")
    def funnel():
        stages = ["new", "contacted", "qualified", "proposal", "won", "lost"]
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT stage, COUNT(*) AS cnt
                FROM marketing_leads
                GROUP BY stage
                """
            )
            rows = cur.fetchall()

        counts = {r["stage"]: r["cnt"] for r in rows}
        funnel_data = [{"stage": s, "count": counts.get(s, 0)} for s in stages]
        return jsonify({"funnel": funnel_data})

    # ------------------------------------------------------------------
    # Campaigns CRUD
    # ------------------------------------------------------------------

    @bp.route("/api/campaigns", methods=["GET"])
    @login_required
    @require_module("marketing")
    def list_campaigns():
        status = request.args.get("status")
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            where = ""
            params: list = []
            if status:
                where = "WHERE status = %s"
                params.append(status)
            cur.execute(
                f"""
                SELECT id, name, description, status, channel,
                       start_date, end_date, budget, spend,
                       goal_type, goal_value, metadata, created_at, updated_at
                FROM marketing_campaigns {where}
                ORDER BY created_at DESC
                """,
                params,
            )
            campaigns = cur.fetchall()
        return jsonify({"campaigns": campaigns})

    @bp.route("/api/campaigns", methods=["POST"])
    @login_required
    @require_module("marketing")
    def create_campaign():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO marketing_campaigns
                    (name, description, status, channel, start_date, end_date,
                     budget, spend, goal_type, goal_value, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, name, description, status, channel,
                          start_date, end_date, budget, spend,
                          goal_type, goal_value, metadata, created_at, updated_at
                """,
                (
                    name,
                    data.get("description"),
                    data.get("status", "draft"),
                    data.get("channel"),
                    data.get("start_date"),
                    data.get("end_date"),
                    data.get("budget"),
                    data.get("spend", 0),
                    data.get("goal_type"),
                    data.get("goal_value"),
                    Json(data.get("metadata", {})),
                ),
            )
            campaign = cur.fetchone()

        return jsonify(campaign), 201

    @bp.route("/api/campaigns/<int:campaign_id>", methods=["GET"])
    @login_required
    @require_module("marketing")
    def get_campaign(campaign_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, description, status, channel,
                       start_date, end_date, budget, spend,
                       goal_type, goal_value, metadata, created_at, updated_at
                FROM marketing_campaigns WHERE id = %s
                """,
                (campaign_id,),
            )
            campaign = cur.fetchone()

        if campaign is None:
            return jsonify({"error": "campaign not found"}), 404
        return jsonify(campaign)

    @bp.route("/api/campaigns/<int:campaign_id>", methods=["PUT"])
    @login_required
    @require_module("marketing")
    def update_campaign(campaign_id):
        data = request.get_json(force=True)

        allowed = (
            "name", "description", "status", "channel",
            "start_date", "end_date", "budget", "spend",
            "goal_type", "goal_value",
        )
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])
        if "metadata" in data:
            sets.append("metadata = %s")
            params.append(Json(data["metadata"]))

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        sets.append("updated_at = NOW()")
        params.append(campaign_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE marketing_campaigns SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, name, description, status, channel,
                          start_date, end_date, budget, spend,
                          goal_type, goal_value, metadata, created_at, updated_at
                """,
                params,
            )
            campaign = cur.fetchone()

        if campaign is None:
            return jsonify({"error": "campaign not found"}), 404
        return jsonify(campaign)

    # ------------------------------------------------------------------
    # Leads CRUD
    # ------------------------------------------------------------------

    @bp.route("/api/leads", methods=["GET"])
    @login_required
    @require_module("marketing")
    def list_leads():
        stage = request.args.get("stage")
        min_score = request.args.get("min_score", type=int)

        where_parts = []
        params: list = []
        if stage:
            where_parts.append("stage = %s")
            params.append(stage)
        if min_score is not None:
            where_parts.append("score >= %s")
            params.append(min_score)

        where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                SELECT id, customer_id, source, score, stage,
                       notes, metadata, created_at, updated_at
                FROM marketing_leads {where}
                ORDER BY score DESC, created_at DESC
                """,
                params,
            )
            leads = cur.fetchall()

        return jsonify({"leads": leads})

    @bp.route("/api/leads", methods=["POST"])
    @login_required
    @require_module("marketing")
    def create_lead():
        data = request.get_json(force=True)
        customer_id = data.get("customer_id")
        source = (data.get("source") or "").strip() or None

        if not customer_id and not source:
            return jsonify({"error": "customer_id or source is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO marketing_leads
                    (customer_id, source, score, stage, notes, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, customer_id, source, score, stage,
                          notes, metadata, created_at, updated_at
                """,
                (
                    customer_id,
                    source,
                    data.get("score", 0),
                    data.get("stage", "new"),
                    data.get("notes"),
                    Json(data.get("metadata", {})),
                ),
            )
            lead = cur.fetchone()

        return jsonify(lead), 201

    @bp.route("/api/leads/<int:lead_id>", methods=["PUT"])
    @login_required
    @require_module("marketing")
    def update_lead(lead_id):
        data = request.get_json(force=True)

        allowed = ("stage", "score", "notes", "source", "customer_id")
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])
        if "metadata" in data:
            sets.append("metadata = %s")
            params.append(Json(data["metadata"]))

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        sets.append("updated_at = NOW()")
        params.append(lead_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE marketing_leads SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, customer_id, source, score, stage,
                          notes, metadata, created_at, updated_at
                """,
                params,
            )
            lead = cur.fetchone()

        if lead is None:
            return jsonify({"error": "lead not found"}), 404
        return jsonify(lead)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats")
    @login_required
    @require_module("marketing")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_leads,
                    COUNT(*) FILTER (WHERE stage = 'won') AS won_leads,
                    COALESCE(AVG(score), 0) AS avg_score
                FROM marketing_leads
                """
            )
            lead_row = cur.fetchone()

            cur.execute(
                "SELECT COUNT(*) AS active_campaigns FROM marketing_campaigns WHERE status = 'active'"
            )
            campaign_row = cur.fetchone()

        total_leads = lead_row["total_leads"]
        won_leads = lead_row["won_leads"]
        conversion_rate = round(won_leads / total_leads * 100, 2) if total_leads else 0.0

        return jsonify(
            {
                "total_leads": total_leads,
                "conversion_rate": conversion_rate,
                "avg_lead_score": round(float(lead_row["avg_score"]), 2),
                "active_campaigns": campaign_row["active_campaigns"],
            }
        )


# ----------------------------------------------------------------------
# Event consumers (module-level, not route handlers)
# ----------------------------------------------------------------------


def on_contact_created(data):
    """Auto-create a lead with source='crm' when a CRM contact is created."""
    customer_id = data.get("customer_id")
    tenant_id = data.get("_tenant_id")
    if not customer_id or not tenant_id:
        return
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            cur.execute(
                """
                INSERT INTO marketing_leads (customer_id, source, stage)
                VALUES (%s, 'crm', 'new')
                """,
                (customer_id,),
            )
    except Exception:
        logger.exception("Failed to auto-create lead for customer %s", customer_id)


def on_post_published(data):
    """No-op placeholder — consumed for future analytics."""
    pass


def on_document_published(data):
    """No-op placeholder — consumed for future analytics."""
    pass
