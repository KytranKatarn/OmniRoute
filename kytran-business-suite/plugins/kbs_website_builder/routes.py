"""Website Builder plugin routes — projects, pages, deployments, stats, templates, AI generation, preview, chat editing."""

import json as _json
import logging
import os
import re

import requests as http_requests
from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.hostinger_deploy import DeploymentError, build_site_zip, deploy_to_hostinger
from core.site_generator import SiteGenerationError, generate_site, refine_site
from core.tenant import require_module

logger = logging.getLogger(__name__)

MODULE = "website-builder"

_BRIDGE_URL = os.environ.get("KBS_BRIDGE_URL", "")
_BRIDGE_API_KEY = os.environ.get("KBS_BRIDGE_API_KEY", "")


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
                "SELECT id, name, domain FROM website_projects WHERE id = %s",
                (project_id,),
            )
            project = cur.fetchone()
            if project is None:
                return jsonify({"error": "project not found"}), 404

            # Gather all pages with content
            cur.execute(
                """
                SELECT slug, content FROM website_pages
                WHERE project_id = %s AND content IS NOT NULL AND content != ''
                ORDER BY sort_order, created_at
                """,
                (project_id,),
            )
            pages = cur.fetchall()

            if not pages:
                return jsonify({"error": "no pages with content to deploy"}), 400

            # Build the ZIP
            zip_bytes = build_site_zip(pages)

            # Determine domain
            domain = (
                data.get("domain")
                or project["domain"]
                or f"{project['name'].lower().replace(' ', '-')}.kytranempowerment.com"
            )

            # Create deployment record (pending)
            cur.execute(
                """
                INSERT INTO website_deployments (project_id, deployment_url, provider, status)
                VALUES (%s, %s, 'hostinger', 'building')
                RETURNING id
                """,
                (project_id, f"https://{domain}"),
            )
            deployment_id = cur.fetchone()["id"]

            # Deploy to Hostinger
            hostinger_api_key = os.environ.get("HOSTINGER_API_KEY", "")
            try:
                result = deploy_to_hostinger(
                    zip_bytes=zip_bytes,
                    domain=domain,
                    hostinger_api_key=hostinger_api_key,
                )
            except DeploymentError as exc:
                logger.error(
                    "Deployment failed for project %d: %s", project_id, exc
                )
                cur.execute(
                    """
                    UPDATE website_deployments
                    SET status = 'failed', deploy_log = %s, completed_at = NOW()
                    WHERE id = %s
                    """,
                    (str(exc), deployment_id),
                )
                return jsonify({"error": f"Deployment failed: {exc}"}), 502

            # Update deployment record with result
            deploy_status = (
                "deployed" if result["status"] == "deployed" else "pending"
            )
            cur.execute(
                """
                UPDATE website_deployments
                SET status = %s, deployment_url = %s,
                    deploy_log = %s, completed_at = NOW()
                WHERE id = %s
                RETURNING id, project_id, deployment_url, status, provider,
                          deploy_log, created_at, completed_at
                """,
                (
                    deploy_status,
                    result["url"],
                    result.get("message", ""),
                    deployment_id,
                ),
            )
            deployment = cur.fetchone()

            # Update project status to published
            cur.execute(
                "UPDATE website_projects SET status = 'published', domain = %s, updated_at = NOW() WHERE id = %s",
                (domain, project_id),
            )

        event_bus.emit(
            "site.deployed",
            {
                "project_id": project_id,
                "name": project["name"],
                "url": result["url"],
            },
            tenant_id=g.tenant_id,
        )

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

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    @bp.route("/api/templates", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def list_templates():
        category = request.args.get("category")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            where = "WHERE is_active = TRUE"
            params: list = []
            if category:
                where += " AND category = %s"
                params.append(category)

            cur.execute(
                f"""
                SELECT id, name, slug, category, description, thumbnail_url,
                       base_prompt, created_at
                FROM website_templates {where}
                ORDER BY category, name
                """,
                params,
            )
            templates = cur.fetchall()

        return jsonify({"templates": templates, "total": len(templates)})

    @bp.route("/api/templates/<slug>", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def get_template(slug):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, slug, category, description, thumbnail_url,
                       base_prompt, base_html, base_css, settings, created_at
                FROM website_templates
                WHERE slug = %s AND is_active = TRUE
                """,
                (slug,),
            )
            template = cur.fetchone()

        if template is None:
            return jsonify({"error": "template not found"}), 404
        return jsonify(template)

    # ------------------------------------------------------------------
    # AI Generation
    # ------------------------------------------------------------------

    @bp.route("/api/projects/<int:project_id>/generate", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def generate_site_route(project_id):
        data = request.get_json(force=True)
        prompt = (data.get("prompt") or "").strip()
        template_slug = data.get("template_slug")

        if not prompt:
            return jsonify({"error": "prompt is required"}), 400

        bridge_url = os.environ.get("KBS_BRIDGE_URL", "")
        bridge_api_key = os.environ.get("KBS_BRIDGE_API_KEY", "")
        if not bridge_url:
            return jsonify({"error": "AI Bridge not configured"}), 503

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            # Verify project exists
            cur.execute(
                "SELECT id, name FROM website_projects WHERE id = %s",
                (project_id,),
            )
            project = cur.fetchone()
            if project is None:
                return jsonify({"error": "project not found"}), 404

            # Fetch template context if requested
            template_context = None
            if template_slug:
                cur.execute(
                    """
                    SELECT base_prompt, base_html, base_css
                    FROM website_templates
                    WHERE slug = %s AND is_active = TRUE
                    """,
                    (template_slug,),
                )
                template_context = cur.fetchone()

            try:
                result = generate_site(
                    prompt=prompt,
                    business_name=project["name"],
                    bridge_url=bridge_url,
                    bridge_api_key=bridge_api_key,
                    template_context=(
                        dict(template_context) if template_context else None
                    ),
                )
            except SiteGenerationError as exc:
                logger.error(
                    "Site generation failed for project %d: %s", project_id, exc
                )
                return jsonify({"error": f"Generation failed: {exc}"}), 502

            # Save generated HTML as the home page (upsert)
            cur.execute(
                """
                INSERT INTO website_pages (project_id, title, slug, content, page_type, sort_order)
                VALUES (%s, 'Home', 'index', %s, 'home', 0)
                ON CONFLICT (project_id, slug) DO UPDATE SET
                    content = EXCLUDED.content,
                    updated_at = NOW()
                RETURNING id
                """,
                (project_id, result["html"]),
            )
            page = cur.fetchone()

            # Update project status to building
            cur.execute(
                "UPDATE website_projects SET status = 'building', updated_at = NOW() WHERE id = %s",
                (project_id,),
            )

        event_bus.emit(
            "site.generated",
            {
                "project_id": project_id,
                "name": project["name"],
                "template": template_slug,
            },
            tenant_id=g.tenant_id,
        )

        return jsonify(
            {
                "html": result["html"],
                "page_id": page["id"],
                "project_id": project_id,
            }
        )

    # ------------------------------------------------------------------
    # AI Refinement
    # ------------------------------------------------------------------

    @bp.route("/api/projects/<int:project_id>/refine", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def refine_site_route(project_id):
        data = request.get_json(force=True)
        prompt = (data.get("prompt") or "").strip()
        current_html = (data.get("current_html") or "").strip()

        if not prompt:
            return jsonify({"error": "prompt is required"}), 400
        if not current_html:
            return jsonify({"error": "current_html is required"}), 400

        bridge_url = os.environ.get("KBS_BRIDGE_URL", "")
        bridge_api_key = os.environ.get("KBS_BRIDGE_API_KEY", "")
        if not bridge_url:
            return jsonify({"error": "AI Bridge not configured"}), 503

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                "SELECT id, name FROM website_projects WHERE id = %s",
                (project_id,),
            )
            project = cur.fetchone()
            if project is None:
                return jsonify({"error": "project not found"}), 404

            try:
                result = refine_site(
                    refinement_prompt=prompt,
                    current_html=current_html,
                    bridge_url=bridge_url,
                    bridge_api_key=bridge_api_key,
                )
            except SiteGenerationError as exc:
                logger.error(
                    "Site refinement failed for project %d: %s", project_id, exc
                )
                return jsonify({"error": f"Refinement failed: {exc}"}), 502

            # Update the home page content
            cur.execute(
                """
                UPDATE website_pages SET content = %s, updated_at = NOW()
                WHERE project_id = %s AND slug = 'index'
                RETURNING id
                """,
                (result["html"], project_id),
            )
            page = cur.fetchone()
            page_id = page["id"] if page else None

        event_bus.emit(
            "site.refined",
            {"project_id": project_id, "name": project["name"]},
            tenant_id=g.tenant_id,
        )

        return jsonify(
            {
                "html": result["html"],
                "page_id": page_id,
                "project_id": project_id,
            }
        )

    # ------------------------------------------------------------------
    # Live Preview
    # ------------------------------------------------------------------

    @bp.route("/api/projects/<int:project_id>/preview", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def preview_project(project_id):
        """Return the generated HTML for iframe preview rendering."""
        page_slug = request.args.get("page", "index")

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
                SELECT content FROM website_pages
                WHERE project_id = %s AND slug = %s
                """,
                (project_id, page_slug),
            )
            page = cur.fetchone()

        if page is None or not page["content"]:
            return (
                "<html><body style='display:flex;align-items:center;justify-content:center;"
                "height:100vh;font-family:sans-serif;color:#666;background:#f5f5f5'>"
                "<p>No content generated yet. Use the AI generator to create your site.</p>"
                "</body></html>",
                200,
                {"Content-Type": "text/html; charset=utf-8"},
            )

        return page["content"], 200, {"Content-Type": "text/html; charset=utf-8"}

    @bp.route("/api/projects/<int:project_id>/preview/pages", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def preview_pages_list(project_id):
        """Return list of pages available for preview."""
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
                SELECT slug, title, page_type,
                       (content IS NOT NULL AND content != '') AS has_content
                FROM website_pages
                WHERE project_id = %s
                ORDER BY sort_order, created_at
                """,
                (project_id,),
            )
            pages = cur.fetchall()

        return jsonify({"pages": pages})

    # ------------------------------------------------------------------
    # Onboarding Wizard
    # ------------------------------------------------------------------

    @bp.route("/api/onboarding", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def onboarding_wizard():
        """Create a project from onboarding wizard data.

        Accepts business name, industry, description, optional template slug.
        Creates the project, optionally triggers AI generation if auto_generate is true.
        """
        data = request.get_json(force=True)
        business_name = (data.get("business_name") or "").strip()
        industry = (data.get("industry") or "").strip()
        description = (data.get("description") or "").strip()
        template_slug = data.get("template_slug")
        auto_generate = data.get("auto_generate", False)

        if not business_name:
            return jsonify({"error": "business_name is required"}), 400
        if not industry:
            return jsonify({"error": "industry is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            # Create the project
            cur.execute(
                """
                INSERT INTO website_projects (name, description, template, settings)
                VALUES (%s, %s, %s, %s)
                RETURNING id, name, description, domain, status, template,
                          settings, created_at, updated_at
                """,
                (
                    business_name,
                    description or f"{industry} website for {business_name}",
                    template_slug,
                    Json({"industry": industry, "onboarded": True}),
                ),
            )
            project = cur.fetchone()

            result_html = None
            page_id = None

            # Auto-generate if requested and Bridge is configured
            if auto_generate:
                bridge_url = os.environ.get("KBS_BRIDGE_URL", "")
                bridge_api_key = os.environ.get("KBS_BRIDGE_API_KEY", "")

                if bridge_url:
                    # Fetch template if specified
                    template_context = None
                    if template_slug:
                        cur.execute(
                            "SELECT base_prompt, base_html, base_css FROM website_templates WHERE slug = %s AND is_active = TRUE",
                            (template_slug,),
                        )
                        template_context = cur.fetchone()

                    prompt = (
                        description
                        or f"Create a {industry} website for {business_name}"
                    )
                    try:
                        gen_result = generate_site(
                            prompt=prompt,
                            business_name=business_name,
                            bridge_url=bridge_url,
                            bridge_api_key=bridge_api_key,
                            template_context=(
                                dict(template_context)
                                if template_context
                                else None
                            ),
                        )
                        result_html = gen_result["html"]

                        # Save as home page
                        cur.execute(
                            """
                            INSERT INTO website_pages (project_id, title, slug, content, page_type, sort_order)
                            VALUES (%s, 'Home', 'index', %s, 'home', 0)
                            RETURNING id
                            """,
                            (project["id"], result_html),
                        )
                        page_id = cur.fetchone()["id"]

                        cur.execute(
                            "UPDATE website_projects SET status = 'building', updated_at = NOW() WHERE id = %s",
                            (project["id"],),
                        )
                        project["status"] = "building"
                    except SiteGenerationError as exc:
                        logger.warning(
                            "Auto-generate failed during onboarding: %s", exc
                        )
                        # Don't fail onboarding — project is still created

        event_bus.emit(
            "site.created",
            {
                "project_id": project["id"],
                "name": project["name"],
                "onboarded": True,
            },
            tenant_id=g.tenant_id,
        )

        response = {
            "project": project,
            "generated": result_html is not None,
        }
        if result_html:
            response["html"] = result_html
            response["page_id"] = page_id

        return jsonify(response), 201

    # ------------------------------------------------------------------
    # AI Assistant (ported from ARCHIE Website Studio)
    # ------------------------------------------------------------------

    @bp.route("/api/ai/suggest-design", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def ai_suggest_design():
        """AI-powered design suggestions based on business type and description."""
        data = request.get_json(force=True)
        description = (data.get("description") or "").strip()
        website_type = (data.get("website_type") or "business").strip()

        if not description:
            return jsonify({"error": "description is required"}), 400

        prompt = (
            f"You are a professional web designer. Suggest a website design for: {description}\n"
            f"Website type: {website_type}\n\n"
            "Respond with JSON containing:\n"
            '- "layout": recommended layout style\n'
            '- "color_scheme": primary, secondary, accent colors\n'
            '- "typography": heading and body font suggestions\n'
            '- "sections": recommended page sections in order\n'
            '- "style_notes": brief design direction notes'
        )

        result = _bridge_request(prompt)
        if result is None:
            return jsonify(_fallback_design_suggestions(website_type))
        return jsonify({"suggestion": result})

    @bp.route("/api/ai/generate-content", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def ai_generate_content():
        """Generate page content with tone control."""
        data = request.get_json(force=True)
        page_name = (data.get("page_name") or "").strip()
        business_description = (data.get("description") or "").strip()
        business_name = (data.get("business_name") or "").strip()
        tone = data.get("tone", "professional")

        if not page_name:
            return jsonify({"error": "page_name is required"}), 400

        prompt = (
            f"Generate website content for a '{page_name}' page.\n"
            f"Business: {business_name or 'a company'}\n"
            f"Description: {business_description or 'No description provided'}\n"
            f"Tone: {tone}\n\n"
            "Respond with clean HTML content for this page section. "
            "Include headings, paragraphs, and any relevant structure. "
            "Do not include <html>, <head>, or <body> tags — only the inner content."
        )

        result = _bridge_request(prompt)
        if result is None:
            return jsonify({"content": f"<h1>{page_name}</h1>\n<p>Content for {business_name or 'your business'} coming soon.</p>"})
        return jsonify({"content": result})

    @bp.route("/api/ai/improve-seo", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def ai_improve_seo():
        """Generate SEO title, description, and keywords for a page."""
        data = request.get_json(force=True)
        page_content = (data.get("content") or "").strip()
        page_title = (data.get("title") or "").strip()

        if not page_content and not page_title:
            return jsonify({"error": "content or title is required"}), 400

        prompt = (
            "You are an SEO expert. Analyze this page and suggest improvements.\n\n"
            f"Page title: {page_title}\n"
            f"Page content (first 500 chars): {page_content[:500]}\n\n"
            "Respond with JSON containing:\n"
            '- "seo_title": optimized page title (max 60 chars)\n'
            '- "seo_description": meta description (max 160 chars)\n'
            '- "keywords": array of 5-8 relevant keywords\n'
            '- "suggestions": array of 3-5 actionable SEO improvement tips'
        )

        result = _bridge_request(prompt)
        if result is None:
            return jsonify({
                "seo_title": page_title or "Untitled Page",
                "seo_description": page_content[:155] + "..." if len(page_content) > 155 else page_content,
                "keywords": [],
                "suggestions": ["Add a meta description", "Use heading tags", "Add alt text to images"],
            })
        return jsonify({"seo": result})

    @bp.route("/api/ai/generate-styles", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def ai_generate_styles():
        """Generate CSS for a design style."""
        data = request.get_json(force=True)
        style = (data.get("style") or "modern").strip()
        colors = data.get("colors", {})

        prompt = (
            f"Generate a CSS stylesheet for a {style} website design.\n"
            f"Color preferences: {_json.dumps(colors) if colors else 'designer choice'}\n\n"
            "Include styles for: body, headings (h1-h3), paragraphs, links, buttons, "
            "navigation, hero section, cards, and footer.\n"
            "Use CSS variables for colors. Make it responsive with media queries.\n"
            "Return ONLY the CSS code, no explanations."
        )

        result = _bridge_request(prompt)
        if result is None:
            return jsonify({"css": _fallback_css(style)})
        return jsonify({"css": result})

    # ------------------------------------------------------------------
    # Chat-Based Editing (ported from ARCHIE Phase 7)
    # ------------------------------------------------------------------

    @bp.route("/api/projects/<int:project_id>/chat", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def chat_edit(project_id):
        """Natural language website editing via chat."""
        data = request.get_json(force=True)
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"error": "message is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            # Get project + pages
            cur.execute(
                "SELECT id, name, description, settings FROM website_projects WHERE id = %s",
                (project_id,),
            )
            project = cur.fetchone()
            if project is None:
                return jsonify({"error": "project not found"}), 404

            cur.execute(
                "SELECT id, title, slug, content, page_type FROM website_pages WHERE project_id = %s ORDER BY sort_order",
                (project_id,),
            )
            pages = cur.fetchall()

            # Build context
            role = _detect_task_role(message)
            site_context = "\n".join(
                f"--- {p['slug']}.html ---\n{(p['content'] or '')[:2000]}" for p in pages
            )

            system_prompt = (
                f"You are a {role} expert helping edit a website called '{project['name']}'.\n"
                f"The site currently has {len(pages)} page(s).\n\n"
                f"Current site content:\n{site_context}\n\n"
                "When the user asks for changes, respond with:\n"
                "1. A brief explanation of what you'll change\n"
                "2. The updated HTML wrapped in <page slug=\"SLUG\">...HTML...</page> tags\n"
                "If no page changes are needed, just respond conversationally."
            )

            # Call Bridge
            ai_response = _bridge_chat(system_prompt, message)
            if ai_response is None:
                ai_response = "I'm sorry, the AI assistant is currently unavailable. Please try again later."

            # Parse page changes from response
            changes = _parse_page_changes(ai_response)
            pages_updated = []

            for slug, new_content in changes.items():
                cur.execute(
                    """
                    UPDATE website_pages SET content = %s, updated_at = NOW()
                    WHERE project_id = %s AND slug = %s
                    RETURNING id, slug, title
                    """,
                    (new_content, project_id, slug),
                )
                updated = cur.fetchone()
                if updated:
                    pages_updated.append(updated["slug"])

            # Save to chat history (last 50 messages)
            cur.execute(
                "SELECT chat_history FROM website_projects WHERE id = %s",
                (project_id,),
            )
            row = cur.fetchone()
            history = row.get("chat_history") or []
            if isinstance(history, str):
                history = _json.loads(history)

            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": ai_response})
            history = history[-100:]  # Keep last 50 exchanges

            cur.execute(
                "UPDATE website_projects SET chat_history = %s, updated_at = NOW() WHERE id = %s",
                (Json(history), project_id),
            )

        if pages_updated:
            event_bus.emit(
                "site.chat_edited",
                {"project_id": project_id, "pages_updated": pages_updated},
                tenant_id=g.tenant_id,
            )

        return jsonify({
            "response": ai_response,
            "pages_updated": pages_updated,
            "role_detected": role,
        })

    @bp.route("/api/projects/<int:project_id>/chat/history", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def get_chat_history(project_id):
        """Retrieve chat history for a project."""
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT chat_history FROM website_projects WHERE id = %s",
                (project_id,),
            )
            row = cur.fetchone()

        if row is None:
            return jsonify({"error": "project not found"}), 404

        history = row.get("chat_history") or []
        if isinstance(history, str):
            history = _json.loads(history)

        return jsonify({"history": history, "total": len(history)})

    @bp.route("/api/projects/<int:project_id>/chat/history", methods=["DELETE"])
    @login_required
    @require_module(MODULE)
    def clear_chat_history(project_id):
        """Clear chat history for a project."""
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "UPDATE website_projects SET chat_history = '[]'::jsonb, updated_at = NOW() WHERE id = %s RETURNING id",
                (project_id,),
            )
            row = cur.fetchone()

        if row is None:
            return jsonify({"error": "project not found"}), 404
        return jsonify({"cleared": True})

    # ------------------------------------------------------------------
    # Multi-Provider Deployment
    # ------------------------------------------------------------------

    @bp.route("/api/deploy/providers", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def list_deploy_providers():
        """List available deployment providers and their connection status."""
        providers = [
            {"id": "hostinger", "name": "Hostinger", "builtin": True, "connected": bool(os.environ.get("HOSTINGER_API_KEY"))},
        ]

        # Check tenant integrations for additional providers
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT service, status FROM tenant_integrations WHERE service IN ('github', 'vercel', 'netlify') AND status = 'active'"
            )
            connected = {r["service"]: True for r in cur.fetchall()}

        for provider_id, name in [("github", "GitHub Pages"), ("vercel", "Vercel"), ("netlify", "Netlify")]:
            providers.append({
                "id": provider_id,
                "name": name,
                "builtin": False,
                "connected": connected.get(provider_id, False),
            })

        return jsonify({"providers": providers})

    @bp.route("/api/deploy/test/<provider>", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def test_deploy_provider(provider):
        """Test provider credentials."""
        if provider not in ("github", "vercel", "netlify"):
            return jsonify({"error": "unsupported provider"}), 400

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT credentials FROM tenant_integrations WHERE service = %s AND status = 'active'",
                (provider,),
            )
            row = cur.fetchone()

        if not row:
            return jsonify({"error": f"{provider} not configured", "connected": False}), 400

        creds = row["credentials"]
        if isinstance(creds, str):
            creds = _json.loads(creds)

        # Test the connection
        try:
            if provider == "github":
                resp = http_requests.get(
                    "https://api.github.com/user",
                    headers={"Authorization": f"token {creds.get('token', '')}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    return jsonify({"connected": True, "user": resp.json().get("login")})
                return jsonify({"connected": False, "error": "Invalid GitHub token"}), 400

            elif provider == "vercel":
                resp = http_requests.get(
                    "https://api.vercel.com/v2/user",
                    headers={"Authorization": f"Bearer {creds.get('token', '')}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    return jsonify({"connected": True, "user": resp.json().get("user", {}).get("username")})
                return jsonify({"connected": False, "error": "Invalid Vercel token"}), 400

            elif provider == "netlify":
                resp = http_requests.get(
                    "https://api.netlify.com/api/v1/user",
                    headers={"Authorization": f"Bearer {creds.get('token', '')}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    return jsonify({"connected": True, "user": resp.json().get("email")})
                return jsonify({"connected": False, "error": "Invalid Netlify token"}), 400

        except Exception as exc:
            return jsonify({"connected": False, "error": str(exc)}), 502

        return jsonify({"connected": False}), 400


# ----------------------------------------------------------------------
# Helper functions (module-level)
# ----------------------------------------------------------------------


def _bridge_request(prompt):
    """Send a single prompt to the Bridge API. Returns response text or None."""
    if not _BRIDGE_URL:
        return None
    try:
        resp = http_requests.post(
            f"{_BRIDGE_URL}/api/chat",
            json={"message": prompt, "model": "auto"},
            headers={"Authorization": f"Bearer {_BRIDGE_API_KEY}"} if _BRIDGE_API_KEY else {},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("response") or data.get("message") or data.get("content")
    except Exception:
        logger.warning("Bridge API request failed")
    return None


def _bridge_chat(system_prompt, user_message):
    """Send a chat message with system prompt to Bridge. Returns response text or None."""
    if not _BRIDGE_URL:
        return None
    try:
        resp = http_requests.post(
            f"{_BRIDGE_URL}/api/chat",
            json={
                "message": user_message,
                "system_prompt": system_prompt,
                "model": "auto",
            },
            headers={"Authorization": f"Bearer {_BRIDGE_API_KEY}"} if _BRIDGE_API_KEY else {},
            timeout=60,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("response") or data.get("message") or data.get("content")
    except Exception:
        logger.warning("Bridge chat request failed")
    return None


def _detect_task_role(message):
    """Classify a chat message into a task role for prompt specialization."""
    msg = message.lower()
    design_words = {"color", "font", "layout", "style", "theme", "design", "look", "visual", "css", "spacing", "align"}
    content_words = {"text", "write", "heading", "paragraph", "copy", "title", "description", "content", "word"}
    deploy_words = {"deploy", "publish", "launch", "host", "domain", "live", "upload"}

    words = set(re.findall(r'\w+', msg))
    scores = {
        "design": len(words & design_words),
        "content": len(words & content_words),
        "deployment": len(words & deploy_words),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "web development"


def _parse_page_changes(ai_response):
    """Parse <page slug="...">HTML</page> tags from AI response."""
    changes = {}
    pattern = re.compile(r'<page\s+slug="([^"]+)">(.*?)</page>', re.DOTALL)
    for match in pattern.finditer(ai_response):
        slug = match.group(1).strip()
        html = match.group(2).strip()
        if slug and html:
            changes[slug] = html
    return changes


def _fallback_design_suggestions(website_type):
    """Fallback design suggestions when AI is unavailable."""
    defaults = {
        "business": {
            "layout": "hero + services grid + testimonials + CTA",
            "color_scheme": {"primary": "#1a365d", "secondary": "#2d3748", "accent": "#3182ce"},
            "typography": {"heading": "Inter", "body": "Open Sans"},
            "sections": ["Hero", "Services", "About", "Testimonials", "Contact"],
            "style_notes": "Clean, professional look with strong call-to-action",
        },
        "portfolio": {
            "layout": "full-width hero + masonry grid + about + contact",
            "color_scheme": {"primary": "#1a1a2e", "secondary": "#16213e", "accent": "#e94560"},
            "typography": {"heading": "Playfair Display", "body": "Lato"},
            "sections": ["Hero", "Portfolio Grid", "About Me", "Skills", "Contact"],
            "style_notes": "Minimal, image-focused with subtle animations",
        },
        "ecommerce": {
            "layout": "nav + featured products + categories + newsletter",
            "color_scheme": {"primary": "#1a1a1a", "secondary": "#333333", "accent": "#ff6b35"},
            "typography": {"heading": "Montserrat", "body": "Roboto"},
            "sections": ["Navigation", "Featured Products", "Categories", "Reviews", "Newsletter"],
            "style_notes": "Product-focused with clear CTAs and trust signals",
        },
    }
    return {"suggestion": defaults.get(website_type, defaults["business"])}


def _fallback_css(style):
    """Fallback CSS when AI is unavailable."""
    return (
        ":root {\n"
        "  --primary: #1a365d;\n"
        "  --secondary: #2d3748;\n"
        "  --accent: #3182ce;\n"
        "  --text: #e2e8f0;\n"
        "  --bg: #0a0a1a;\n"
        "}\n\n"
        "body { font-family: 'Open Sans', sans-serif; background: var(--bg); color: var(--text); margin: 0; }\n"
        "h1, h2, h3 { font-family: 'Inter', sans-serif; color: var(--accent); }\n"
        "a { color: var(--accent); text-decoration: none; }\n"
        ".btn { background: var(--accent); color: #fff; padding: 0.75rem 1.5rem; border-radius: 6px; border: none; cursor: pointer; }\n"
        ".hero { min-height: 60vh; display: flex; align-items: center; justify-content: center; text-align: center; }\n"
        ".container { max-width: 1200px; margin: 0 auto; padding: 2rem; }\n"
        "@media (max-width: 768px) { .container { padding: 1rem; } }\n"
    )
