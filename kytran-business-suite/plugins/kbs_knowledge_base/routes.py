"""Knowledge Base plugin routes — categories, articles, public search, AI generation."""

import logging
from datetime import datetime

from flask import g, jsonify, render_template, request
from flask_login import login_required

from core.config import Config
from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)
cfg = Config()


def register_routes(bp):
    """Attach all Knowledge Base routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("knowledge-base")
    def index():
        return render_template("knowledge_base.html")

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    @bp.route("/api/categories", methods=["GET"])
    @login_required
    @require_module("knowledge-base")
    def list_categories():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, slug, description, parent_id, sort_order,
                       is_active, created_at
                FROM kb_categories
                ORDER BY sort_order, name
                """
            )
            categories = cur.fetchall()
        return jsonify({"categories": categories})

    @bp.route("/api/categories", methods=["POST"])
    @login_required
    @require_module("knowledge-base")
    def create_category():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        slug = (data.get("slug") or "").strip()
        if not name or not slug:
            return jsonify({"error": "name and slug are required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO kb_categories (name, slug, description, parent_id, sort_order)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, slug, description, parent_id, sort_order,
                          is_active, created_at
                """,
                (
                    name,
                    slug,
                    data.get("description"),
                    data.get("parent_id"),
                    data.get("sort_order", 0),
                ),
            )
            category = cur.fetchone()
        return jsonify(category), 201

    @bp.route("/api/categories/<int:category_id>", methods=["PUT"])
    @login_required
    @require_module("knowledge-base")
    def update_category(category_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM kb_categories WHERE id = %s", (category_id,))
            if not cur.fetchone():
                return jsonify({"error": "Category not found"}), 404
            cur.execute(
                """
                UPDATE kb_categories SET
                    name        = COALESCE(%s, name),
                    slug        = COALESCE(%s, slug),
                    description = COALESCE(%s, description),
                    parent_id   = COALESCE(%s, parent_id),
                    sort_order  = COALESCE(%s, sort_order),
                    is_active   = COALESCE(%s, is_active)
                WHERE id = %s
                RETURNING id, name, slug, description, parent_id, sort_order,
                          is_active, created_at
                """,
                (
                    data.get("name"),
                    data.get("slug"),
                    data.get("description"),
                    data.get("parent_id"),
                    data.get("sort_order"),
                    data.get("is_active"),
                    category_id,
                ),
            )
            category = cur.fetchone()
        return jsonify(category)

    @bp.route("/api/categories/<int:category_id>", methods=["DELETE"])
    @login_required
    @require_module("knowledge-base")
    def delete_category(category_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "DELETE FROM kb_categories WHERE id = %s RETURNING id",
                (category_id,),
            )
            deleted = cur.fetchone()
        if not deleted:
            return jsonify({"error": "Category not found"}), 404
        return jsonify({"deleted": True, "id": category_id})

    # ------------------------------------------------------------------
    # Articles
    # ------------------------------------------------------------------

    @bp.route("/api/articles", methods=["GET"])
    @login_required
    @require_module("knowledge-base")
    def list_articles():
        status = request.args.get("status")
        category_id = request.args.get("category_id")

        conditions = []
        params = []
        if status:
            conditions.append("a.status = %s")
            params.append(status)
        if category_id:
            conditions.append("a.category_id = %s")
            params.append(int(category_id))

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                SELECT a.id, a.category_id, a.title, a.slug, a.excerpt,
                       a.status, a.author, a.views, a.helpful_yes, a.helpful_no,
                       a.tags, a.published_at, a.created_at, a.updated_at,
                       c.name AS category_name
                FROM kb_articles a
                LEFT JOIN kb_categories c ON c.id = a.category_id
                {where}
                ORDER BY a.updated_at DESC
                """,
                params,
            )
            articles = cur.fetchall()

        return jsonify({"articles": articles, "total": len(articles)})

    @bp.route("/api/articles/<int:article_id>", methods=["GET"])
    @login_required
    @require_module("knowledge-base")
    def get_article(article_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            # Increment view count
            cur.execute(
                "UPDATE kb_articles SET views = views + 1 WHERE id = %s", (article_id,)
            )
            cur.execute(
                """
                SELECT a.id, a.category_id, a.title, a.slug, a.content, a.excerpt,
                       a.status, a.author, a.views, a.helpful_yes, a.helpful_no,
                       a.tags, a.metadata, a.published_at, a.created_at, a.updated_at,
                       c.name AS category_name
                FROM kb_articles a
                LEFT JOIN kb_categories c ON c.id = a.category_id
                WHERE a.id = %s
                """,
                (article_id,),
            )
            article = cur.fetchone()

        if article is None:
            return jsonify({"error": "Article not found"}), 404

        event_bus.emit(
            "article.viewed",
            {"article_id": article_id, "title": article["title"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(article)

    @bp.route("/api/articles", methods=["POST"])
    @login_required
    @require_module("knowledge-base")
    def create_article():
        data = request.get_json(force=True)
        title = (data.get("title") or "").strip()
        slug = (data.get("slug") or "").strip()
        content = (data.get("content") or "").strip()
        if not title or not slug or not content:
            return jsonify({"error": "title, slug, and content are required"}), 400

        status = data.get("status", "draft")
        published_at = datetime.utcnow() if status == "published" else None

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            from psycopg2.extras import Json

            cur.execute(
                """
                INSERT INTO kb_articles
                    (category_id, title, slug, content, excerpt, status, author,
                     tags, metadata, published_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, category_id, title, slug, content, excerpt,
                          status, author, views, helpful_yes, helpful_no,
                          tags, metadata, published_at, created_at, updated_at
                """,
                (
                    data.get("category_id"),
                    title,
                    slug,
                    content,
                    data.get("excerpt"),
                    status,
                    data.get("author"),
                    Json(data.get("tags", [])),
                    Json(data.get("metadata", {})),
                    published_at,
                ),
            )
            article = cur.fetchone()

        if status == "published":
            event_bus.emit(
                "article.published",
                {"article_id": article["id"], "title": article["title"]},
                tenant_id=g.tenant_id,
            )
        return jsonify(article), 201

    @bp.route("/api/articles/<int:article_id>", methods=["PUT"])
    @login_required
    @require_module("knowledge-base")
    def update_article(article_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id, status FROM kb_articles WHERE id = %s", (article_id,))
            existing = cur.fetchone()
            if not existing:
                return jsonify({"error": "Article not found"}), 404

            new_status = data.get("status")
            published_at_clause = ""
            if new_status == "published" and existing["status"] != "published":
                published_at_clause = ", published_at = NOW()"

            from psycopg2.extras import Json

            cur.execute(
                f"""
                UPDATE kb_articles SET
                    title       = COALESCE(%s, title),
                    slug        = COALESCE(%s, slug),
                    content     = COALESCE(%s, content),
                    excerpt     = COALESCE(%s, excerpt),
                    status      = COALESCE(%s, status),
                    category_id = COALESCE(%s, category_id),
                    author      = COALESCE(%s, author),
                    tags        = COALESCE(%s, tags),
                    updated_at  = NOW()
                    {published_at_clause}
                WHERE id = %s
                RETURNING id, category_id, title, slug, content, excerpt,
                          status, author, views, helpful_yes, helpful_no,
                          tags, metadata, published_at, created_at, updated_at
                """,
                (
                    data.get("title"),
                    data.get("slug"),
                    data.get("content"),
                    data.get("excerpt"),
                    new_status,
                    data.get("category_id"),
                    data.get("author"),
                    Json(data["tags"]) if "tags" in data else None,
                    article_id,
                ),
            )
            article = cur.fetchone()
        return jsonify(article)

    @bp.route("/api/articles/<int:article_id>", methods=["DELETE"])
    @login_required
    @require_module("knowledge-base")
    def delete_article(article_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "DELETE FROM kb_articles WHERE id = %s RETURNING id",
                (article_id,),
            )
            deleted = cur.fetchone()
        if not deleted:
            return jsonify({"error": "Article not found"}), 404
        return jsonify({"deleted": True, "id": article_id})

    @bp.route("/api/articles/<int:article_id>/helpful", methods=["POST"])
    @login_required
    @require_module("knowledge-base")
    def rate_article(article_id):
        data = request.get_json(force=True)
        helpful = data.get("helpful", True)
        col = "helpful_yes" if helpful else "helpful_no"

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"UPDATE kb_articles SET {col} = {col} + 1 WHERE id = %s"
                " RETURNING id, helpful_yes, helpful_no",
                (article_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "Article not found"}), 404
        return jsonify(row)

    # ------------------------------------------------------------------
    # Public endpoints (no login required)
    # ------------------------------------------------------------------

    @bp.route("/api/public/search", methods=["GET"])
    def public_search():
        """Public article search — no login required.

        Requires tenant_id in session (set by tenant middleware from URL).
        Only returns published articles.
        """
        q = (request.args.get("q") or "").strip()
        if not q:
            return jsonify({"articles": [], "total": 0})

        pattern = f"%{q}%"
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, title, slug, excerpt, category_id, tags, published_at
                FROM kb_articles
                WHERE status = 'published'
                  AND (title ILIKE %s OR content ILIKE %s OR excerpt ILIKE %s)
                ORDER BY views DESC
                LIMIT 20
                """,
                (pattern, pattern, pattern),
            )
            articles = cur.fetchall()
        return jsonify({"articles": articles, "total": len(articles)})

    @bp.route("/api/public/articles/<slug>", methods=["GET"])
    def public_article(slug):
        """Read a published article by slug — no login required."""
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "UPDATE kb_articles SET views = views + 1 WHERE slug = %s AND status = 'published'",
                (slug,),
            )
            cur.execute(
                """
                SELECT a.id, a.title, a.slug, a.content, a.excerpt,
                       a.tags, a.published_at, a.views,
                       c.name AS category_name
                FROM kb_articles a
                LEFT JOIN kb_categories c ON c.id = a.category_id
                WHERE a.slug = %s AND a.status = 'published'
                """,
                (slug,),
            )
            article = cur.fetchone()
        if not article:
            return jsonify({"error": "Article not found"}), 404
        return jsonify(article)

    @bp.route("/api/public/suggest", methods=["GET"])
    def public_suggest():
        """Auto-suggest articles for help desk ticket submission."""
        q = (request.args.get("q") or "").strip()
        if len(q) < 3:
            return jsonify({"suggestions": []})

        pattern = f"%{q}%"
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, title, slug, excerpt
                FROM kb_articles
                WHERE status = 'published'
                  AND (title ILIKE %s OR content ILIKE %s)
                ORDER BY views DESC
                LIMIT 5
                """,
                (pattern, pattern),
            )
            suggestions = cur.fetchall()
        return jsonify({"suggestions": suggestions})

    # ------------------------------------------------------------------
    # AI Article Generation
    # ------------------------------------------------------------------

    @bp.route("/api/articles/generate", methods=["POST"])
    @login_required
    @require_module("knowledge-base")
    def generate_article():
        """Generate a knowledge base article using the AI Bridge.

        Request body: {"topic": "...", "category_id": N (optional)}
        """
        import requests as http_requests

        data = request.get_json(force=True)
        topic = (data.get("topic") or "").strip()
        if not topic:
            return jsonify({"error": "topic is required"}), 400

        if not cfg.KBS_BRIDGE_URL:
            return jsonify({"error": "AI Bridge not configured"}), 503

        prompt = (
            f"Write a professional knowledge base article about: {topic}\n\n"
            "Format the article with:\n"
            "- A clear title\n"
            "- A brief 1-2 sentence excerpt/summary\n"
            "- Well-structured content with headers and paragraphs\n"
            "- Practical step-by-step instructions where appropriate\n\n"
            "Return JSON with keys: title, excerpt, content"
        )

        try:
            bridge_resp = http_requests.post(
                f"{cfg.KBS_BRIDGE_URL}/api/bridge",
                json={
                    "prompt": prompt,
                    "model": getattr(cfg, "KBS_BRIDGE_MODEL", "qwen2.5-coder:7b"),
                    "format": "json",
                },
                timeout=60,
            )
            bridge_resp.raise_for_status()
            result = bridge_resp.json()
            ai_text = result.get("response", "{}")

            import json as json_lib

            try:
                parsed = json_lib.loads(ai_text)
            except (json_lib.JSONDecodeError, TypeError):
                parsed = {
                    "title": topic,
                    "excerpt": "",
                    "content": ai_text,
                }

            return jsonify({
                "generated": True,
                "title": parsed.get("title", topic),
                "excerpt": parsed.get("excerpt", ""),
                "content": parsed.get("content", ai_text),
                "category_id": data.get("category_id"),
            })

        except Exception as exc:
            logger.exception("AI article generation failed: %s", exc)
            return jsonify({"error": f"AI generation failed: {str(exc)}"}), 502

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("knowledge-base")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_articles,
                    COUNT(*) FILTER (WHERE status = 'published') AS published_articles,
                    COUNT(*) FILTER (WHERE status = 'draft') AS draft_articles,
                    COALESCE(SUM(views), 0) AS total_views,
                    COALESCE(SUM(helpful_yes), 0) AS total_helpful_yes,
                    COALESCE(SUM(helpful_no), 0) AS total_helpful_no
                FROM kb_articles
                """
            )
            article_stats = cur.fetchone()

            cur.execute("SELECT COUNT(*) AS total_categories FROM kb_categories")
            cat_stats = cur.fetchone()

        return jsonify({
            **article_stats,
            "total_categories": cat_stats["total_categories"],
        })
