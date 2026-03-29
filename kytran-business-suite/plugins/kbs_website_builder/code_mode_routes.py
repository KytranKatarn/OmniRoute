"""Website Builder — Code Mode routes (virtual filesystem, preview assembly)."""

import base64
import logging
import mimetypes
import re

from flask import g, jsonify, request
from flask_login import login_required
from psycopg2 import errors as pg_errors

from core.database import get_db_cursor, set_tenant_search_path
from core.tenant import require_module

logger = logging.getLogger(__name__)

MODULE = "website-builder"
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

# ---------------------------------------------------------------------------
# Boilerplate seeded when a new project enters code mode with no pages
# ---------------------------------------------------------------------------
_BOILERPLATE = [
    (
        "index.html",
        "index.html",
        "text/html",
        False,
        """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>My Site</title>
    <link rel="stylesheet" href="css/style.css" />
</head>
<body>
    <h1>Welcome to My Site</h1>
    <script src="js/script.js"></script>
</body>
</html>
""",
    ),
    ("css/style.css", "style.css", "text/css", False, "/* Site styles */\nbody { font-family: sans-serif; margin: 0; padding: 2rem; }\n"),
    ("js/script.js", "script.js", "application/javascript", False, "// Site scripts\nconsole.log('Hello from My Site');\n"),
    ("images/", "images", "inode/directory", True, None),
]


def register_code_mode_routes(bp):
    """Attach Code Mode routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Helper — verify project belongs to tenant and return it
    # ------------------------------------------------------------------
    def _get_project(cur, project_id):
        cur.execute(
            "SELECT id, name, editor_mode FROM website_projects WHERE id = %s",
            (project_id,),
        )
        return cur.fetchone()

    # ------------------------------------------------------------------
    # GET /api/projects/<id>/mode
    # ------------------------------------------------------------------
    @bp.route("/api/projects/<int:project_id>/mode", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def get_editor_mode(project_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            project = _get_project(cur, project_id)
            if not project:
                return jsonify({"error": "Project not found"}), 404
            return jsonify({"editor_mode": project["editor_mode"] or "visual"})

    # ------------------------------------------------------------------
    # POST /api/projects/<id>/enter-code-mode
    # ------------------------------------------------------------------
    @bp.route("/api/projects/<int:project_id>/enter-code-mode", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def enter_code_mode(project_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            project = _get_project(cur, project_id)
            if not project:
                return jsonify({"error": "Project not found"}), 404

            # Already in code mode — just return file count
            if project["editor_mode"] == "code":
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM website_files WHERE project_id = %s AND is_directory = FALSE",
                    (project_id,),
                )
                count = cur.fetchone()["cnt"]
                return jsonify({"editor_mode": "code", "files_created": count, "already_in_code_mode": True})

            # Check for existing pages
            cur.execute(
                "SELECT id, slug, content FROM website_pages WHERE project_id = %s ORDER BY id",
                (project_id,),
            )
            pages = cur.fetchall()

            files_created = 0

            if pages:
                # Convert each page to {slug}.html
                for page in pages:
                    slug = page["slug"] or f"page-{page['id']}"
                    path = f"{slug}.html"
                    html_content = page["content"] or f"<!DOCTYPE html>\n<html><head><title>{slug}</title></head><body></body></html>\n"
                    cur.execute(
                        """
                        INSERT INTO website_files (project_id, path, filename, content, mime_type, file_size, is_directory)
                        VALUES (%s, %s, %s, %s, 'text/html', %s, FALSE)
                        ON CONFLICT (project_id, path) DO NOTHING
                        """,
                        (project_id, path, f"{slug}.html", html_content, len(html_content.encode())),
                    )
                    if cur.rowcount:
                        files_created += 1
            else:
                # Seed boilerplate
                for path, filename, mime, is_dir, content in _BOILERPLATE:
                    size = len(content.encode()) if content else 0
                    cur.execute(
                        """
                        INSERT INTO website_files (project_id, path, filename, content, mime_type, file_size, is_directory)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (project_id, path) DO NOTHING
                        """,
                        (project_id, path, filename, content, mime, size, is_dir),
                    )
                    if cur.rowcount:
                        files_created += 1

            # Update project mode
            cur.execute(
                "UPDATE website_projects SET editor_mode = 'code' WHERE id = %s",
                (project_id,),
            )

        return jsonify({"editor_mode": "code", "files_created": files_created})

    # ------------------------------------------------------------------
    # GET /api/projects/<id>/files
    # ------------------------------------------------------------------
    @bp.route("/api/projects/<int:project_id>/files", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def list_files(project_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if not _get_project(cur, project_id):
                return jsonify({"error": "Project not found"}), 404

            cur.execute(
                """
                SELECT id, path, filename, mime_type, file_size, is_directory, created_at, updated_at
                FROM website_files
                WHERE project_id = %s
                ORDER BY path
                """,
                (project_id,),
            )
            files = cur.fetchall()

        return jsonify({"files": [dict(f) for f in files], "total": len(files)})

    # ------------------------------------------------------------------
    # GET /api/projects/<id>/files/<file_id>
    # ------------------------------------------------------------------
    @bp.route("/api/projects/<int:project_id>/files/<int:file_id>", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def get_file(project_id, file_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if not _get_project(cur, project_id):
                return jsonify({"error": "Project not found"}), 404

            cur.execute(
                "SELECT * FROM website_files WHERE id = %s AND project_id = %s",
                (file_id, project_id),
            )
            f = cur.fetchone()
            if not f:
                return jsonify({"error": "File not found"}), 404

        return jsonify(dict(f))

    # ------------------------------------------------------------------
    # POST /api/projects/<id>/files  — create file or directory
    # ------------------------------------------------------------------
    @bp.route("/api/projects/<int:project_id>/files", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def create_file(project_id):
        data = request.get_json(silent=True) or {}
        path = (data.get("path") or "").strip()
        filename = (data.get("filename") or "").strip()
        content = data.get("content", "")
        mime_type = data.get("mime_type", "text/plain")
        is_directory = bool(data.get("is_directory", False))

        if not path:
            return jsonify({"error": "path is required"}), 400
        if not filename:
            # derive from path
            filename = path.rstrip("/").split("/")[-1]

        if not is_directory and content and len(content.encode()) > MAX_FILE_SIZE:
            return jsonify({"error": "File exceeds 5 MB limit"}), 413

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if not _get_project(cur, project_id):
                return jsonify({"error": "Project not found"}), 404

            # Auto-create parent directories
            parts = path.strip("/").split("/")
            for i in range(1, len(parts)):
                parent_path = "/".join(parts[:i]) + "/"
                parent_name = parts[i - 1]
                cur.execute(
                    """
                    INSERT INTO website_files (project_id, path, filename, content, mime_type, file_size, is_directory)
                    VALUES (%s, %s, %s, NULL, 'inode/directory', 0, TRUE)
                    ON CONFLICT (project_id, path) DO NOTHING
                    """,
                    (project_id, parent_path, parent_name),
                )

            file_size = len(content.encode()) if content else 0
            try:
                cur.execute(
                    """
                    INSERT INTO website_files (project_id, path, filename, content, mime_type, file_size, is_directory)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (project_id, path, filename, content if not is_directory else None, mime_type, file_size, is_directory),
                )
                new_file = cur.fetchone()
            except pg_errors.UniqueViolation:
                return jsonify({"error": "File already exists at that path"}), 409

        return jsonify(dict(new_file)), 201

    # ------------------------------------------------------------------
    # PUT /api/projects/<id>/files/<file_id>  — update content
    # ------------------------------------------------------------------
    @bp.route("/api/projects/<int:project_id>/files/<int:file_id>", methods=["PUT"])
    @login_required
    @require_module(MODULE)
    def update_file(project_id, file_id):
        data = request.get_json(silent=True) or {}
        content = data.get("content", "")

        if content and len(content.encode()) > MAX_FILE_SIZE:
            return jsonify({"error": "File exceeds 5 MB limit"}), 413

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if not _get_project(cur, project_id):
                return jsonify({"error": "Project not found"}), 404

            cur.execute(
                """
                UPDATE website_files
                SET content = %s, file_size = %s, updated_at = NOW()
                WHERE id = %s AND project_id = %s
                RETURNING *
                """,
                (content, len(content.encode()), file_id, project_id),
            )
            f = cur.fetchone()
            if not f:
                return jsonify({"error": "File not found"}), 404

        return jsonify(dict(f))

    # ------------------------------------------------------------------
    # PATCH /api/projects/<id>/files/<file_id>  — rename/move
    # ------------------------------------------------------------------
    @bp.route("/api/projects/<int:project_id>/files/<int:file_id>", methods=["PATCH"])
    @login_required
    @require_module(MODULE)
    def rename_file(project_id, file_id):
        data = request.get_json(silent=True) or {}
        new_path = (data.get("path") or "").strip()
        new_filename = (data.get("filename") or "").strip()

        if not new_path and not new_filename:
            return jsonify({"error": "path or filename is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if not _get_project(cur, project_id):
                return jsonify({"error": "Project not found"}), 404

            cur.execute(
                "SELECT * FROM website_files WHERE id = %s AND project_id = %s",
                (file_id, project_id),
            )
            f = cur.fetchone()
            if not f:
                return jsonify({"error": "File not found"}), 404

            update_path = new_path if new_path else f["path"]
            update_filename = new_filename if new_filename else f["filename"]

            cur.execute(
                """
                UPDATE website_files
                SET path = %s, filename = %s, updated_at = NOW()
                WHERE id = %s AND project_id = %s
                RETURNING *
                """,
                (update_path, update_filename, file_id, project_id),
            )
            updated = cur.fetchone()

        return jsonify(dict(updated))

    # ------------------------------------------------------------------
    # DELETE /api/projects/<id>/files/<file_id>
    # ------------------------------------------------------------------
    @bp.route("/api/projects/<int:project_id>/files/<int:file_id>", methods=["DELETE"])
    @login_required
    @require_module(MODULE)
    def delete_file(project_id, file_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if not _get_project(cur, project_id):
                return jsonify({"error": "Project not found"}), 404

            cur.execute(
                "DELETE FROM website_files WHERE id = %s AND project_id = %s RETURNING id",
                (file_id, project_id),
            )
            if not cur.fetchone():
                return jsonify({"error": "File not found"}), 404

            # If no files left, revert to visual mode
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM website_files WHERE project_id = %s",
                (project_id,),
            )
            remaining = cur.fetchone()["cnt"]
            if remaining == 0:
                cur.execute(
                    "UPDATE website_projects SET editor_mode = 'visual' WHERE id = %s",
                    (project_id,),
                )

        return jsonify({"deleted": True, "reverted_to_visual": remaining == 0})

    # ------------------------------------------------------------------
    # POST /api/projects/<id>/files/upload  — multipart upload
    # ------------------------------------------------------------------
    @bp.route("/api/projects/<int:project_id>/files/upload", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def upload_file(project_id):
        if "file" not in request.files:
            return jsonify({"error": "No file in request"}), 400

        upload = request.files["file"]
        raw = upload.read()

        if len(raw) > MAX_FILE_SIZE:
            return jsonify({"error": "File exceeds 5 MB limit"}), 413

        filename = upload.filename or "upload"
        path = request.form.get("path", filename)
        mime_type = upload.mimetype or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        content = base64.b64encode(raw).decode("ascii")

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if not _get_project(cur, project_id):
                return jsonify({"error": "Project not found"}), 404

            try:
                cur.execute(
                    """
                    INSERT INTO website_files (project_id, path, filename, content, mime_type, file_size, is_directory)
                    VALUES (%s, %s, %s, %s, %s, %s, FALSE)
                    RETURNING *
                    """,
                    (project_id, path, filename, content, mime_type, len(raw)),
                )
                new_file = cur.fetchone()
            except pg_errors.UniqueViolation:
                return jsonify({"error": "File already exists at that path"}), 409

        return jsonify(dict(new_file)), 201

    # ------------------------------------------------------------------
    # GET /api/projects/<id>/preview  — assemble all files into single HTML
    # ------------------------------------------------------------------
    @bp.route("/api/projects/<int:project_id>/preview", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def preview_project(project_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if not _get_project(cur, project_id):
                return jsonify({"error": "Project not found"}), 404

            # Load index.html
            cur.execute(
                "SELECT content FROM website_files WHERE project_id = %s AND path = 'index.html'",
                (project_id,),
            )
            row = cur.fetchone()
            if not row or not row["content"]:
                return jsonify({"error": "No index.html found"}), 404

            html = row["content"]

            # Load all non-directory files for inlining
            cur.execute(
                "SELECT path, content, mime_type FROM website_files WHERE project_id = %s AND is_directory = FALSE AND path != 'index.html'",
                (project_id,),
            )
            assets = {r["path"]: (r["content"], r["mime_type"]) for r in cur.fetchall()}

        # Inline CSS <link> tags
        def _inline_css(m):
            href = m.group(1)
            if href in assets:
                css_content, _ = assets[href]
                return f"<style>{css_content}</style>"
            return m.group(0)

        html = re.sub(r'<link[^>]+rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)["\'][^>]*/?\s*>', _inline_css, html)
        html = re.sub(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']stylesheet["\'][^>]*/?\s*>', _inline_css, html)

        # Inline JS <script src="..."> tags
        def _inline_js(m):
            src = m.group(1)
            if src in assets:
                js_content, _ = assets[src]
                return f"<script>{js_content}</script>"
            return m.group(0)

        html = re.sub(r'<script[^>]+src=["\']([^"\']+)["\'][^>]*></script>', _inline_js, html)

        # Inline images as base64 data URIs
        def _inline_img(m):
            src = m.group(1)
            if src in assets:
                content, mime = assets[src]
                return f'src="data:{mime};base64,{content}"'
            return m.group(0)

        html = re.sub(r'src=["\']([^"\']+)["\']', _inline_img, html)

        return html, 200, {"Content-Type": "text/html; charset=utf-8"}
