"""Website Builder plugin routes — projects, pages, deployments, stats."""

import logging

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)

MODULE = "website-builder"


def register_routes(bp):
    """Attach all Website Builder routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module(MODULE)
    def index():
        return render_template("website_builder.html")

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    @bp.route("/api/projects", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def list_projects():
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 25, type=int)
        status = request.args.get("status")
        offset = (page - 1) * per_page

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            where = ""
            params: list = []
            if status:
                where = "WHERE status = %s"
                params.append(status)

            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM website_projects {where}",
                params,
            )
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"""
                SELECT id, name, description, domain, status, template,
                       settings, created_at, updated_at
                FROM website_projects {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            projects = cur.fetchall()

        return jsonify(
            {
                "projects": projects,
                "total": total,
                "page": page,
                "per_page": per_page,
            }
        )

    @bp.route("/api/projects", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def create_project():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO website_projects (name, description, domain, template, settings)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, description, domain, status, template, settings, created_at, updated_at
                """,
                (
                    name,
                    data.get("description"),
                    data.get("domain"),
                    data.get("template"),
                    Json(data.get("settings", {})),
                ),
            )
            project = cur.fetchone()

        event_bus.emit(
            "site.created",
            {"project_id": project["id"], "name": project["name"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(project), 201

    @bp.route("/api/projects/<int:project_id>", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def get_project(project_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, description, domain, status, template,
                       settings, created_at, updated_at
                FROM website_projects WHERE id = %s
                """,
                (project_id,),
            )
            project = cur.fetchone()

            if project is None:
                return jsonify({"error": "project not found"}), 404

            cur.execute(
                """
                SELECT id, project_id, title, slug, page_type, sort_order,
                       is_published, seo_title, seo_description, metadata,
                       created_at, updated_at
                FROM website_pages
                WHERE project_id = %s
                ORDER BY sort_order, created_at
                """,
                (project_id,),
            )
            project["pages"] = cur.fetchall()

        return jsonify(project)

    @bp.route("/api/projects/<int:project_id>", methods=["PUT"])
    @login_required
    @require_module(MODULE)
    def update_project(project_id):
        data = request.get_json(force=True)

        allowed = ("name", "description", "domain", "template", "status")
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])
        if "settings" in data:
            sets.append("settings = %s")
            params.append(Json(data["settings"]))

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        sets.append("updated_at = NOW()")
        params.append(project_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE website_projects SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, name, description, domain, status, template,
                          settings, created_at, updated_at
                """,
                params,
            )
            project = cur.fetchone()

        if project is None:
            return jsonify({"error": "project not found"}), 404

        event_bus.emit(
            "site.updated",
            {"project_id": project["id"], "name": project["name"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(project)

    @bp.route("/api/projects/<int:project_id>", methods=["DELETE"])
    @login_required
    @require_module(MODULE)
    def delete_project(project_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, status FROM website_projects WHERE id = %s",
                (project_id,),
            )
            project = cur.fetchone()

            if project is None:
                return jsonify({"error": "project not found"}), 404

            if project["status"] != "draft":
                return jsonify({"error": "only draft projects can be deleted"}), 409

            cur.execute(
                "DELETE FROM website_projects WHERE id = %s RETURNING id",
                (project_id,),
            )

        return jsonify({"deleted": True, "id": project_id})

    @bp.route("/api/projects/<int:project_id>/publish", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def publish_project(project_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE website_projects
                SET status = 'published', updated_at = NOW()
                WHERE id = %s
                RETURNING id, name, status, updated_at
                """,
                (project_id,),
            )
            project = cur.fetchone()

        if project is None:
            return jsonify({"error": "project not found"}), 404

        event_bus.emit(
            "site.published",
            {"project_id": project["id"], "name": project["name"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(project)

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    @bp.route("/api/projects/<int:project_id>/pages", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def list_pages(project_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                "SELECT id FROM website_projects WHERE id = %s",
                (project_id,),
            )
            if cur.fetchone() is None:
                return jsonify({"error": "project not found"}), 404

            cur.execute(
                """
                SELECT id, project_id, title, slug, page_type, sort_order,
                       is_published, seo_title, seo_description, metadata,
                       created_at, updated_at
                FROM website_pages
                WHERE project_id = %s
                ORDER BY sort_order, created_at
                """,
                (project_id,),
            )
            pages = cur.fetchall()

        return jsonify({"pages": pages, "total": len(pages)})

    @bp.route("/api/projects/<int:project_id>/pages", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def create_page(project_id):
        data = request.get_json(force=True)
        title = (data.get("title") or "").strip()
        slug = (data.get("slug") or "").strip()

        if not title:
            return jsonify({"error": "title is required"}), 400
        if not slug:
            return jsonify({"error": "slug is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                "SELECT id FROM website_projects WHERE id = %s",
                (project_id,),
            )
            if cur.fetchone() is None:
                return jsonify({"error": "project not found"}), 404

            cur.execute(
                """
                INSERT INTO website_pages
                    (project_id, title, slug, content, page_type, sort_order,
                     seo_title, seo_description, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, project_id, title, slug, content, page_type,
                          sort_order, is_published, seo_title, seo_description,
                          metadata, created_at, updated_at
                """,
                (
                    project_id,
                    title,
                    slug,
                    data.get("content", ""),
                    data.get("page_type", "page"),
                    data.get("sort_order", 0),
                    data.get("seo_title"),
                    data.get("seo_description"),
                    Json(data.get("metadata", {})),
                ),
            )
            page = cur.fetchone()

        event_bus.emit(
            "page.created",
            {"page_id": page["id"], "title": page["title"], "project_id": project_id},
            tenant_id=g.tenant_id,
        )
        return jsonify(page), 201

    @bp.route("/api/pages/<int:page_id>", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def get_page(page_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, project_id, title, slug, content, page_type,
                       sort_order, is_published, seo_title, seo_description,
                       metadata, created_at, updated_at
                FROM website_pages WHERE id = %s
                """,
                (page_id,),
            )
            page = cur.fetchone()

        if page is None:
            return jsonify({"error": "page not found"}), 404
        return jsonify(page)

    @bp.route("/api/pages/<int:page_id>", methods=["PUT"])
    @login_required
    @require_module(MODULE)
    def update_page(page_id):
        data = request.get_json(force=True)

        allowed = ("title", "slug", "content", "page_type", "sort_order",
                   "is_published", "seo_title", "seo_description")
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
        params.append(page_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE website_pages SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, project_id, title, slug, content, page_type,
                          sort_order, is_published, seo_title, seo_description,
                          metadata, created_at, updated_at
                """,
                params,
            )
            page = cur.fetchone()

        if page is None:
            return jsonify({"error": "page not found"}), 404

        event_bus.emit(
            "page.updated",
            {"page_id": page["id"], "title": page["title"], "project_id": page["project_id"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(page)

    @bp.route("/api/pages/<int:page_id>", methods=["DELETE"])
    @login_required
    @require_module(MODULE)
    def delete_page(page_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "DELETE FROM website_pages WHERE id = %s RETURNING id, title",
                (page_id,),
            )
            deleted = cur.fetchone()

        if deleted is None:
            return jsonify({"error": "page not found"}), 404

        return jsonify({"deleted": True, "id": deleted["id"]})

    @bp.route("/api/pages/<int:page_id>/publish", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def publish_page(page_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE website_pages
                SET is_published = TRUE, updated_at = NOW()
                WHERE id = %s
                RETURNING id, title, slug, is_published, project_id, updated_at
                """,
                (page_id,),
            )
            page = cur.fetchone()

        if page is None:
            return jsonify({"error": "page not found"}), 404

        return jsonify(page)

    # ------------------------------------------------------------------
    # Deployments
    # ------------------------------------------------------------------

    @bp.route("/api/projects/<int:project_id>/deployments", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def list_deployments(project_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id FROM website_projects WHERE id = %s",
                (project_id,),
            )
            if cur.fetchone() is None:
                return jsonify({"error": "project not found"}), 404

            cur.execute(
                """
                SELECT id, project_id, deployment_url, status, provider,
                       deploy_log, created_at, completed_at
                FROM website_deployments
                WHERE project_id = %s
                ORDER BY created_at DESC
                """,
                (project_id,),
            )
            deployments = cur.fetchall()

        return jsonify({"deployments": deployments, "total": len(deployments)})

    @bp.route("/api/projects/<int:project_id>/deploy", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def create_deployment(project_id):
        data = request.get_json(force=True) or {}

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, name FROM website_projects WHERE id = %s",
                (project_id,),
            )
            project = cur.fetchone()
            if project is None:
                return jsonify({"error": "project not found"}), 404

            cur.execute(
                """
                INSERT INTO website_deployments (project_id, deployment_url, provider)
                VALUES (%s, %s, %s)
                RETURNING id, project_id, deployment_url, status, provider,
                          deploy_log, created_at, completed_at
                """,
                (
                    project_id,
                    data.get("deployment_url"),
                    data.get("provider", "github"),
                ),
            )
            deployment = cur.fetchone()

        return jsonify(deployment), 201

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_projects,
                    COUNT(*) FILTER (WHERE status = 'published') AS published_sites,
                    COUNT(*) FILTER (WHERE status = 'draft') AS draft_projects
                FROM website_projects
                """
            )
            project_stats = cur.fetchone()

            cur.execute("SELECT COUNT(*) AS total_pages FROM website_pages")
            page_stats = cur.fetchone()

            cur.execute(
                """
                SELECT COUNT(*) AS recent_deployments
                FROM website_deployments
                WHERE created_at >= NOW() - INTERVAL '7 days'
                """
            )
            deploy_stats = cur.fetchone()

        return jsonify(
            {
                "total_projects": project_stats["total_projects"],
                "published_sites": project_stats["published_sites"],
                "draft_projects": project_stats["draft_projects"],
                "total_pages": page_stats["total_pages"],
                "recent_deployments": deploy_stats["recent_deployments"],
            }
        )
