"""C.R.E.E.D. Command — document library (Phase 4, #3614).

E.T.H.O.S.'s file workspace: upload grant docs, research, policy templates, brand
assets; tag them; link them to a grant and/or a mail thread; download/delete.

File bytes live in Postgres (creed_files.data BYTEA, migration 416) — self-contained,
persists across restarts, backs up with the DB, and is never exposed via static.
Downloads go through an admin-gated route. Admin-only. 10 MB/file cap.
"""

import logging
import re

import psycopg2
from flask import Response, jsonify, request
from flask_login import login_required
from werkzeug.utils import secure_filename

from database import get_db_cursor

logger = logging.getLogger(__name__)

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB (app MAX_CONTENT_LENGTH is 16 MB)
_SAFE_HEADER = re.compile(r'[\r\n"]+')


def _row(r):
    d = dict(r)
    if d.get("uploaded_at") is not None and not isinstance(d["uploaded_at"], str):
        d["uploaded_at"] = d["uploaded_at"].isoformat()
    return d


def _gid(v):
    """Parse an optional grant_id form/json value to int or None."""
    if v in (None, "", "null"):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def register_files_routes(bp, admin_required):
    @bp.route("/api/files", methods=["GET"])
    @login_required
    @admin_required
    def files_list():
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT f.id, f.filename, f.content_type, f.size_bytes, f.tag, "
                    "f.grant_id, f.mail_ref, f.uploaded_at, g.title AS grant_title "
                    "FROM creed_files f LEFT JOIN creed_grants g ON g.id = f.grant_id "
                    "ORDER BY f.uploaded_at DESC LIMIT 200"
                )
                items = [_row(r) for r in cur.fetchall() or []]
            return jsonify({"files": items, "count": len(items)})
        except Exception as e:
            logger.error("files_list failed: %s", e)
            return jsonify({"files": [], "count": 0, "error": "load failed"}), 500

    @bp.route("/api/files", methods=["POST"])
    @login_required
    @admin_required
    def files_upload():
        up = request.files.get("file")
        if up is None or not up.filename:
            return jsonify({"error": "no file provided"}), 400
        data = up.read()
        if not data:
            return jsonify({"error": "file is empty"}), 400
        if len(data) > _MAX_BYTES:
            return jsonify({"error": "file too large (max 10 MB)"}), 413
        filename = secure_filename(up.filename) or "upload"
        tag = (request.form.get("tag") or "").strip() or None
        mail_ref = (request.form.get("mail_ref") or "").strip() or None
        grant_id = _gid(request.form.get("grant_id"))
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "INSERT INTO creed_files (filename, content_type, size_bytes, tag, "
                    "grant_id, mail_ref, data) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "RETURNING id, filename, content_type, size_bytes, tag, grant_id, "
                    "mail_ref, uploaded_at",
                    (filename, up.mimetype, len(data), tag, grant_id, mail_ref, psycopg2.Binary(data)),
                )
                row = _row(cur.fetchone())
            return jsonify(row), 201
        except psycopg2.errors.ForeignKeyViolation:
            return jsonify({"error": "linked grant does not exist"}), 400
        except Exception as e:
            logger.error("files_upload failed: %s", e)
            return jsonify({"error": "upload failed"}), 500

    @bp.route("/api/files/<int:file_id>/download", methods=["GET"])
    @login_required
    @admin_required
    def files_download(file_id):
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT filename, content_type, data FROM creed_files WHERE id=%s", (file_id,))
            r = cur.fetchone()
        if not r:
            return jsonify({"error": "not found"}), 404
        safe_name = _SAFE_HEADER.sub("_", r["filename"] or "download")
        resp = Response(bytes(r["data"]), mimetype=r["content_type"] or "application/octet-stream")
        resp.headers["Content-Disposition"] = 'attachment; filename="%s"' % safe_name
        return resp

    @bp.route("/api/files/<int:file_id>", methods=["PATCH"])
    @login_required
    @admin_required
    def files_update(file_id):
        j = request.get_json(silent=True) or {}
        sets, vals = [], []
        if "tag" in j:
            sets.append("tag=%s")
            vals.append((j.get("tag") or "").strip() or None)
        if "grant_id" in j:
            sets.append("grant_id=%s")
            vals.append(_gid(j.get("grant_id")))
        if "mail_ref" in j:
            sets.append("mail_ref=%s")
            vals.append((j.get("mail_ref") or "").strip() or None)
        if not sets:
            return jsonify({"error": "no editable fields"}), 400
        vals.append(file_id)
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    f"UPDATE creed_files SET {', '.join(sets)} WHERE id=%s "
                    "RETURNING id, filename, content_type, size_bytes, tag, grant_id, mail_ref, uploaded_at",
                    vals,
                )
                row = cur.fetchone()
            if not row:
                return jsonify({"error": "not found"}), 404
            return jsonify(_row(row))
        except psycopg2.errors.ForeignKeyViolation:
            return jsonify({"error": "linked grant does not exist"}), 400
        except Exception as e:
            logger.error("files_update failed: %s", e)
            return jsonify({"error": "could not update"}), 500

    @bp.route("/api/files/<int:file_id>", methods=["DELETE"])
    @login_required
    @admin_required
    def files_delete(file_id):
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("DELETE FROM creed_files WHERE id=%s", (file_id,))
                gone = cur.rowcount
            if not gone:
                return jsonify({"error": "not found"}), 404
            return jsonify({"deleted": file_id})
        except Exception as e:
            logger.error("files_delete failed: %s", e)
            return jsonify({"error": "could not delete"}), 500
