"""Family Tree — Document upload, OCR, and linking routes."""

import os
import uuid

from flask import jsonify, request
from flask_login import current_user, login_required

from database import get_db_cursor

UPLOAD_DIR = "/mnt/archie_brain/platform_v2/uploads/family_tree"


def _ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def register_document_routes(bp, admin_required):
    """Register document management endpoints on the blueprint."""

    @bp.route("/api/documents")
    @login_required
    def api_list_documents():
        sql = """
            SELECT * FROM family_documents
            WHERE user_id = %(user_id)s
            ORDER BY uploaded_at DESC
        """
        with get_db_cursor() as (conn, cur):
            cur.execute(sql, {"user_id": current_user.id})
            rows = [dict(r) for r in cur.fetchall()]
        return jsonify(rows)

    @bp.route("/api/documents/upload", methods=["POST"])
    @login_required
    def api_upload_document():
        _ensure_upload_dir()
        f = request.files.get("file")
        if f is None:
            return jsonify({"error": "No file provided"}), 400

        original_name = f.filename or "upload"
        ext = os.path.splitext(original_name)[1].lower()
        unique_name = f"{uuid.uuid4().hex}{ext}"
        save_path = os.path.join(UPLOAD_DIR, unique_name)
        f.save(save_path)

        file_type = ext.lstrip(".")
        sql = """
            INSERT INTO family_documents
                (user_id, original_filename, stored_filename, file_type, file_path, ocr_status)
            VALUES
                (%(user_id)s, %(original_name)s, %(unique_name)s, %(file_type)s, %(file_path)s, 'pending')
            RETURNING *
        """
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                sql,
                {
                    "user_id": current_user.id,
                    "original_name": original_name,
                    "unique_name": unique_name,
                    "file_type": file_type,
                    "file_path": save_path,
                },
            )
            row = cur.fetchone()

        if row is None:
            return jsonify({"error": "Failed to save document record"}), 500
        return jsonify(dict(row)), 201

    @bp.route("/api/documents/<int:doc_id>/ocr", methods=["POST"])
    @login_required
    def api_ocr_document(doc_id):
        # Mark as processing first
        sql_processing = """
            UPDATE family_documents SET ocr_status = 'processing'
            WHERE id = %(id)s AND user_id = %(user_id)s
            RETURNING file_path
        """
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(sql_processing, {"id": doc_id, "user_id": current_user.id})
            row = cur.fetchone()

        if row is None:
            return jsonify({"error": "Document not found"}), 404

        file_path = row["file_path"]

        try:
            from .services.ocr_service import process_document

            ocr_text = process_document(file_path)
            status = "complete"
        except Exception as exc:
            ocr_text = f"OCR failed: {exc}"
            status = "failed"

        sql_update = """
            UPDATE family_documents
            SET ocr_status = %(status)s, ocr_text = %(ocr_text)s
            WHERE id = %(id)s AND user_id = %(user_id)s
            RETURNING *
        """
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                sql_update,
                {
                    "status": status,
                    "ocr_text": ocr_text,
                    "id": doc_id,
                    "user_id": current_user.id,
                },
            )
            updated = cur.fetchone()

        return jsonify(dict(updated)) if updated else jsonify({"error": "Update failed"}), 500

    @bp.route("/api/documents/<int:doc_id>/link", methods=["POST"])
    @login_required
    def api_link_document(doc_id):
        data = request.get_json(silent=True) or {}
        person_id = data.get("person_id")
        if not person_id:
            return jsonify({"error": "person_id is required"}), 400

        sql = """
            UPDATE family_documents
            SET linked_person_id = %(person_id)s
            WHERE id = %(id)s AND user_id = %(user_id)s
            RETURNING *
        """
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                sql,
                {
                    "person_id": person_id,
                    "id": doc_id,
                    "user_id": current_user.id,
                },
            )
            row = cur.fetchone()

        if row is None:
            return jsonify({"error": "Document not found"}), 404
        return jsonify(dict(row))

    @bp.route("/api/documents/<int:doc_id>", methods=["DELETE"])
    @login_required
    def api_delete_document(doc_id):
        sql_fetch = """
            SELECT file_path FROM family_documents
            WHERE id = %(id)s AND user_id = %(user_id)s
        """
        with get_db_cursor() as (conn, cur):
            cur.execute(sql_fetch, {"id": doc_id, "user_id": current_user.id})
            row = cur.fetchone()

        if row is None:
            return jsonify({"error": "Document not found"}), 404

        file_path = row["file_path"]
        try:
            if file_path and os.path.isfile(file_path):
                os.remove(file_path)
        except OSError:
            pass  # Log if needed; don't block the DB delete

        sql_delete = """
            DELETE FROM family_documents
            WHERE id = %(id)s AND user_id = %(user_id)s
        """
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(sql_delete, {"id": doc_id, "user_id": current_user.id})

        return jsonify({"deleted": True})
