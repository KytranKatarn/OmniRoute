"""Social Media plugin routes — accounts, posts, campaigns, analytics."""

import logging

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)

VALID_PLATFORMS = {"instagram", "tiktok", "facebook", "twitter", "linkedin", "youtube"}
VALID_POST_STATUSES = {"draft", "scheduled", "published", "failed"}
VALID_CAMPAIGN_STATUSES = {"draft", "active", "paused", "completed"}


def register_routes(bp):
    """Attach all Social Media routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("social-media")
    def index():
        return render_template("social_media.html")

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------

    @bp.route("/api/accounts", methods=["GET"])
    @login_required
    @require_module("social-media")
    def list_accounts():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, platform, account_name, account_id, is_active,
                       token_expires_at, metadata, created_at
                FROM social_accounts
                ORDER BY platform, account_name
                """
            )
            accounts = cur.fetchall()
        return jsonify({"accounts": accounts})

    @bp.route("/api/accounts", methods=["POST"])
    @login_required
    @require_module("social-media")
    def create_account():
        data = request.get_json(force=True)
        platform = (data.get("platform") or "").strip().lower()
        account_name = (data.get("account_name") or "").strip()

        if not platform:
            return jsonify({"error": "platform is required"}), 400
        if platform not in VALID_PLATFORMS:
            return jsonify({"error": f"platform must be one of: {', '.join(sorted(VALID_PLATFORMS))}"}), 400
        if not account_name:
            return jsonify({"error": "account_name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO social_accounts
                    (platform, account_name, account_id, access_token, refresh_token,
                     token_expires_at, is_active, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, platform, account_name, account_id, is_active,
                          token_expires_at, metadata, created_at
                """,
                (
                    platform,
                    account_name,
                    data.get("account_id"),
                    data.get("access_token"),
                    data.get("refresh_token"),
                    data.get("token_expires_at"),
                    data.get("is_active", True),
                    Json(data.get("metadata", {})),
                ),
            )
            account = cur.fetchone()

        return jsonify(account), 201

    @bp.route("/api/accounts/<int:account_id>", methods=["DELETE"])
    @login_required
    @require_module("social-media")
    def delete_account(account_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "DELETE FROM social_accounts WHERE id = %s RETURNING id, account_name",
                (account_id,),
            )
            deleted = cur.fetchone()

        if deleted is None:
            return jsonify({"error": "account not found"}), 404
        return jsonify({"deleted": True, "id": deleted["id"]})

    # ------------------------------------------------------------------
    # Posts
    # ------------------------------------------------------------------

    @bp.route("/api/posts", methods=["GET"])
    @login_required
    @require_module("social-media")
    def list_posts():
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 25, type=int)
        account_id = request.args.get("account_id", type=int)
        status = request.args.get("status")
        offset = (page - 1) * per_page

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            conditions = []
            params: list = []
            if account_id:
                conditions.append("account_id = %s")
                params.append(account_id)
            if status:
                conditions.append("status = %s")
                params.append(status)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            cur.execute(f"SELECT COUNT(*) AS cnt FROM social_posts {where}", params)
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"""
                SELECT id, account_id, content, media_urls, status,
                       scheduled_at, published_at, platform_post_id,
                       engagement, tags, created_at, updated_at
                FROM social_posts {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            posts = cur.fetchall()

        return jsonify({"posts": posts, "total": total, "page": page, "per_page": per_page})

    @bp.route("/api/posts", methods=["POST"])
    @login_required
    @require_module("social-media")
    def create_post():
        data = request.get_json(force=True)
        content = (data.get("content") or "").strip()
        if not content:
            return jsonify({"error": "content is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO social_posts
                    (account_id, content, media_urls, status, scheduled_at, tags)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, account_id, content, media_urls, status,
                          scheduled_at, published_at, platform_post_id,
                          engagement, tags, created_at, updated_at
                """,
                (
                    data.get("account_id"),
                    content,
                    Json(data.get("media_urls", [])),
                    data.get("status", "draft"),
                    data.get("scheduled_at"),
                    Json(data.get("tags", [])),
                ),
            )
            post = cur.fetchone()

        event_bus.emit(
            "post.created",
            {"post_id": post["id"], "account_id": post["account_id"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(post), 201

    @bp.route("/api/posts/<int:post_id>", methods=["GET"])
    @login_required
    @require_module("social-media")
    def get_post(post_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, account_id, content, media_urls, status,
                       scheduled_at, published_at, platform_post_id,
                       engagement, tags, created_at, updated_at
                FROM social_posts WHERE id = %s
                """,
                (post_id,),
            )
            post = cur.fetchone()

        if post is None:
            return jsonify({"error": "post not found"}), 404
        return jsonify(post)

    @bp.route("/api/posts/<int:post_id>", methods=["PUT"])
    @login_required
    @require_module("social-media")
    def update_post(post_id):
        data = request.get_json(force=True)

        allowed = ("content", "status", "scheduled_at", "platform_post_id")
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])
        for json_field in ("media_urls", "tags", "engagement"):
            if json_field in data:
                sets.append(f"{json_field} = %s")
                params.append(Json(data[json_field]))

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        sets.append("updated_at = NOW()")
        params.append(post_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE social_posts SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, account_id, content, media_urls, status,
                          scheduled_at, published_at, platform_post_id,
                          engagement, tags, created_at, updated_at
                """,
                params,
            )
            post = cur.fetchone()

        if post is None:
            return jsonify({"error": "post not found"}), 404
        return jsonify(post)

    @bp.route("/api/posts/<int:post_id>", methods=["DELETE"])
    @login_required
    @require_module("social-media")
    def delete_post(post_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "DELETE FROM social_posts WHERE id = %s RETURNING id",
                (post_id,),
            )
            deleted = cur.fetchone()

        if deleted is None:
            return jsonify({"error": "post not found"}), 404
        return jsonify({"deleted": True, "id": deleted["id"]})

    @bp.route("/api/posts/<int:post_id>/schedule", methods=["POST"])
    @login_required
    @require_module("social-media")
    def schedule_post(post_id):
        data = request.get_json(force=True)
        scheduled_at = data.get("scheduled_at")
        if not scheduled_at:
            return jsonify({"error": "scheduled_at is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE social_posts
                SET status = 'scheduled', scheduled_at = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING id, account_id, content, status, scheduled_at, updated_at
                """,
                (scheduled_at, post_id),
            )
            post = cur.fetchone()

        if post is None:
            return jsonify({"error": "post not found"}), 404

        event_bus.emit(
            "post.scheduled",
            {"post_id": post["id"], "scheduled_at": str(post["scheduled_at"])},
            tenant_id=g.tenant_id,
        )
        return jsonify(post)

    @bp.route("/api/posts/<int:post_id>/publish", methods=["POST"])
    @login_required
    @require_module("social-media")
    def publish_post(post_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE social_posts
                SET status = 'published', published_at = NOW(), updated_at = NOW()
                WHERE id = %s
                RETURNING id, account_id, content, status, published_at, updated_at
                """,
                (post_id,),
            )
            post = cur.fetchone()

        if post is None:
            return jsonify({"error": "post not found"}), 404

        event_bus.emit(
            "post.published",
            {"post_id": post["id"], "published_at": str(post["published_at"])},
            tenant_id=g.tenant_id,
        )
        return jsonify(post)

    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------

    @bp.route("/api/campaigns", methods=["GET"])
    @login_required
    @require_module("social-media")
    def list_campaigns():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, description, status, start_date, end_date,
                       budget, metadata, created_at
                FROM social_campaigns
                ORDER BY created_at DESC
                """
            )
            campaigns = cur.fetchall()
        return jsonify({"campaigns": campaigns})

    @bp.route("/api/campaigns", methods=["POST"])
    @login_required
    @require_module("social-media")
    def create_campaign():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO social_campaigns
                    (name, description, status, start_date, end_date, budget, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, name, description, status, start_date, end_date,
                          budget, metadata, created_at
                """,
                (
                    name,
                    data.get("description"),
                    data.get("status", "draft"),
                    data.get("start_date"),
                    data.get("end_date"),
                    data.get("budget"),
                    Json(data.get("metadata", {})),
                ),
            )
            campaign = cur.fetchone()

        event_bus.emit(
            "campaign.created",
            {"campaign_id": campaign["id"], "name": campaign["name"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(campaign), 201

    @bp.route("/api/campaigns/<int:campaign_id>", methods=["GET"])
    @login_required
    @require_module("social-media")
    def get_campaign(campaign_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, description, status, start_date, end_date,
                       budget, metadata, created_at
                FROM social_campaigns WHERE id = %s
                """,
                (campaign_id,),
            )
            campaign = cur.fetchone()

            if campaign is None:
                return jsonify({"error": "campaign not found"}), 404

            # Fetch associated posts
            cur.execute(
                """
                SELECT p.id, p.account_id, p.content, p.status,
                       p.scheduled_at, p.published_at, p.tags, p.created_at
                FROM social_posts p
                JOIN social_campaign_posts cp ON cp.post_id = p.id
                WHERE cp.campaign_id = %s
                ORDER BY p.created_at DESC
                """,
                (campaign_id,),
            )
            posts = cur.fetchall()

        campaign["posts"] = posts
        return jsonify(campaign)

    @bp.route("/api/campaigns/<int:campaign_id>", methods=["PUT"])
    @login_required
    @require_module("social-media")
    def update_campaign(campaign_id):
        data = request.get_json(force=True)

        allowed = ("name", "description", "status", "start_date", "end_date", "budget")
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

        params.append(campaign_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE social_campaigns SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, name, description, status, start_date, end_date,
                          budget, metadata, created_at
                """,
                params,
            )
            campaign = cur.fetchone()

        if campaign is None:
            return jsonify({"error": "campaign not found"}), 404
        return jsonify(campaign)

    @bp.route("/api/campaigns/<int:campaign_id>/start", methods=["POST"])
    @login_required
    @require_module("social-media")
    def start_campaign(campaign_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE social_campaigns SET status = 'active'
                WHERE id = %s
                RETURNING id, name, status
                """,
                (campaign_id,),
            )
            campaign = cur.fetchone()

        if campaign is None:
            return jsonify({"error": "campaign not found"}), 404

        event_bus.emit(
            "campaign.started",
            {"campaign_id": campaign["id"], "name": campaign["name"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(campaign)

    @bp.route("/api/campaigns/<int:campaign_id>/posts", methods=["POST"])
    @login_required
    @require_module("social-media")
    def add_post_to_campaign(campaign_id):
        data = request.get_json(force=True)
        post_id = data.get("post_id")
        if not post_id:
            return jsonify({"error": "post_id is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            # Verify campaign exists
            cur.execute("SELECT id FROM social_campaigns WHERE id = %s", (campaign_id,))
            if cur.fetchone() is None:
                return jsonify({"error": "campaign not found"}), 404

            # Verify post exists
            cur.execute("SELECT id FROM social_posts WHERE id = %s", (post_id,))
            if cur.fetchone() is None:
                return jsonify({"error": "post not found"}), 404

            cur.execute(
                """
                INSERT INTO social_campaign_posts (campaign_id, post_id)
                VALUES (%s, %s)
                ON CONFLICT (campaign_id, post_id) DO NOTHING
                RETURNING id, campaign_id, post_id
                """,
                (campaign_id, post_id),
            )
            link = cur.fetchone()

        if link is None:
            return jsonify({"message": "post already in campaign", "campaign_id": campaign_id, "post_id": post_id})
        return jsonify(link), 201

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    @bp.route("/api/analytics", methods=["GET"])
    @login_required
    @require_module("social-media")
    def get_analytics():
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            conditions = []
            params: list = []
            if date_from:
                conditions.append("date >= %s")
                params.append(date_from)
            if date_to:
                conditions.append("date <= %s")
                params.append(date_to)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            cur.execute(
                f"""
                SELECT
                    date,
                    SUM(followers) AS followers,
                    SUM(impressions) AS impressions,
                    SUM(engagements) AS engagements,
                    SUM(clicks) AS clicks
                FROM social_analytics {where}
                GROUP BY date
                ORDER BY date DESC
                LIMIT 90
                """,
                params,
            )
            rows = cur.fetchall()

        return jsonify({"analytics": rows})

    @bp.route("/api/analytics/<int:account_id>", methods=["GET"])
    @login_required
    @require_module("social-media")
    def get_account_analytics(account_id):
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            conditions = ["account_id = %s"]
            params: list = [account_id]
            if date_from:
                conditions.append("date >= %s")
                params.append(date_from)
            if date_to:
                conditions.append("date <= %s")
                params.append(date_to)

            where = "WHERE " + " AND ".join(conditions)

            cur.execute(
                f"""
                SELECT id, account_id, date, followers, impressions,
                       engagements, clicks, metadata
                FROM social_analytics {where}
                ORDER BY date DESC
                LIMIT 90
                """,
                params,
            )
            rows = cur.fetchall()

        return jsonify({"analytics": rows, "account_id": account_id})

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("social-media")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM social_accounts WHERE is_active = TRUE) AS total_accounts,
                    (SELECT COUNT(*) FROM social_posts) AS total_posts,
                    (SELECT COUNT(*) FROM social_posts WHERE status = 'scheduled') AS scheduled_posts,
                    (SELECT COUNT(*) FROM social_campaigns WHERE status = 'active') AS active_campaigns
                """
            )
            row = cur.fetchone()

        return jsonify(row)


# ----------------------------------------------------------------------
# Event consumers (module-level, not route handlers)
# ----------------------------------------------------------------------


def on_contact_created(data):
    """Placeholder — future: auto-suggest social post when a new contact is created."""
    pass


def on_document_published(data):
    """Placeholder — future: auto-create social post from published content."""
    pass
