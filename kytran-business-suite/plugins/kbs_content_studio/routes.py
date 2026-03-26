"""Content Studio plugin routes — documents CRUD, templates, export, stats."""

import logging

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)


def _count_words(text: str) -> int:
    """Return the word count of a text string."""
    if not text:
        return 0
    return len(text.split())


def register_routes(bp):
    """Attach all Content Studio routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("content-studio")
    def index():
        return render_template("content_studio.html")

    # ------------------------------------------------------------------
    # Documents CRUD
    # ------------------------------------------------------------------

    @bp.route("/api/documents", methods=["GET"])
    @login_required
    @require_module("content-studio")
    def list_documents():
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 25, type=int)
        status = request.args.get("status")
        doc_type = request.args.get("doc_type")
        offset = (page - 1) * per_page

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            conditions = []
            params: list = []
            if status:
                conditions.append("status = %s")
                params.append(status)
            if doc_type:
                conditions.append("doc_type = %s")
                params.append(doc_type)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM content_documents {where}",
                params,
            )
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"""
                SELECT id, title, doc_type, status, word_count, tags, metadata,
                       created_at, updated_at
                FROM content_documents {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            documents = cur.fetchall()

        return jsonify(
            {
                "documents": documents,
                "total": total,
                "page": page,
                "per_page": per_page,
            }
        )

    @bp.route("/api/documents", methods=["POST"])
    @login_required
    @require_module("content-studio")
    def create_document():
        data = request.get_json(force=True)
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "title is required"}), 400

        content = data.get("content", "")
        word_count = _count_words(content)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO content_documents
                    (title, content, doc_type, status, word_count, tags, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, title, content, doc_type, status, word_count,
                          tags, metadata, created_at, updated_at
                """,
                (
                    title,
                    content,
                    data.get("doc_type", "article"),
                    data.get("status", "draft"),
                    word_count,
                    Json(data.get("tags", [])),
                    Json(data.get("metadata", {})),
                ),
            )
            document = cur.fetchone()

        event_bus.emit(
            "document.created",
            {"document_id": document["id"], "title": document["title"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(document), 201

    @bp.route("/api/documents/<int:doc_id>", methods=["GET"])
    @login_required
    @require_module("content-studio")
    def get_document(doc_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, title, content, doc_type, status, word_count,
                       tags, metadata, created_at, updated_at
                FROM content_documents WHERE id = %s
                """,
                (doc_id,),
            )
            document = cur.fetchone()

        if document is None:
            return jsonify({"error": "document not found"}), 404
        return jsonify(document)

    @bp.route("/api/documents/<int:doc_id>", methods=["PUT"])
    @login_required
    @require_module("content-studio")
    def update_document(doc_id):
        data = request.get_json(force=True)

        allowed = ("title", "doc_type", "status")
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])

        if "content" in data:
            sets.append("content = %s")
            sets.append("word_count = %s")
            params.append(data["content"])
            params.append(_count_words(data["content"]))

        if "tags" in data:
            sets.append("tags = %s")
            params.append(Json(data["tags"]))
        if "metadata" in data:
            sets.append("metadata = %s")
            params.append(Json(data["metadata"]))

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        sets.append("updated_at = NOW()")
        params.append(doc_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE content_documents SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, title, content, doc_type, status, word_count,
                          tags, metadata, created_at, updated_at
                """,
                params,
            )
            document = cur.fetchone()

        if document is None:
            return jsonify({"error": "document not found"}), 404

        event_bus.emit(
            "document.updated",
            {"document_id": document["id"], "title": document["title"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(document)

    @bp.route("/api/documents/<int:doc_id>", methods=["DELETE"])
    @login_required
    @require_module("content-studio")
    def delete_document(doc_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "DELETE FROM content_documents WHERE id = %s RETURNING id, title",
                (doc_id,),
            )
            deleted = cur.fetchone()

        if deleted is None:
            return jsonify({"error": "document not found"}), 404

        event_bus.emit(
            "document.deleted",
            {"document_id": deleted["id"], "title": deleted["title"]},
            tenant_id=g.tenant_id,
        )
        return jsonify({"deleted": True, "id": deleted["id"]})

    @bp.route("/api/documents/<int:doc_id>/publish", methods=["POST"])
    @login_required
    @require_module("content-studio")
    def publish_document(doc_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE content_documents
                SET status = 'published', updated_at = NOW()
                WHERE id = %s
                RETURNING id, title, content, doc_type, status, word_count,
                          tags, metadata, created_at, updated_at
                """,
                (doc_id,),
            )
            document = cur.fetchone()

        if document is None:
            return jsonify({"error": "document not found"}), 404

        event_bus.emit(
            "document.published",
            {"document_id": document["id"], "title": document["title"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(document)

    @bp.route("/api/documents/<int:doc_id>/export", methods=["GET"])
    @login_required
    @require_module("content-studio")
    def export_document(doc_id):
        fmt = request.args.get("format", "markdown").lower()
        if fmt not in ("markdown", "html"):
            return jsonify({"error": "format must be markdown or html"}), 400

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, title, content, doc_type, status FROM content_documents WHERE id = %s",
                (doc_id,),
            )
            document = cur.fetchone()

        if document is None:
            return jsonify({"error": "document not found"}), 404

        if fmt == "markdown":
            exported = f"# {document['title']}\n\n{document['content']}"
        else:
            # Simple HTML export
            content_html = document["content"].replace("\n", "<br>")
            exported = (
                f"<html><head><title>{document['title']}</title></head>"
                f"<body><h1>{document['title']}</h1><div>{content_html}</div></body></html>"
            )

        return jsonify(
            {
                "id": document["id"],
                "title": document["title"],
                "format": fmt,
                "content": exported,
            }
        )

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    @bp.route("/api/templates", methods=["GET"])
    @login_required
    @require_module("content-studio")
    def list_templates():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, description, doc_type, template_content, is_active, created_at
                FROM content_templates
                WHERE is_active = TRUE
                ORDER BY name
                """
            )
            templates = cur.fetchall()
        return jsonify({"templates": templates})

    @bp.route("/api/templates", methods=["POST"])
    @login_required
    @require_module("content-studio")
    def create_template():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO content_templates (name, description, doc_type, template_content, is_active)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, description, doc_type, template_content, is_active, created_at
                """,
                (
                    name,
                    data.get("description"),
                    data.get("doc_type"),
                    data.get("template_content", ""),
                    data.get("is_active", True),
                ),
            )
            template = cur.fetchone()

        return jsonify(template), 201

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("content-studio")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_documents,
                    COUNT(*) FILTER (WHERE status = 'published') AS published_count,
                    COUNT(*) FILTER (WHERE status = 'draft') AS draft_count,
                    COALESCE(SUM(word_count), 0) AS total_words
                FROM content_documents
                """
            )
            row = cur.fetchone()

        return jsonify(row)
