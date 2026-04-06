"""Family Tree — Photo upload, face detection, clustering, and restoration routes."""

import mimetypes
import os
import uuid

from flask import jsonify, request, send_file
from flask_login import current_user, login_required

from database import get_db_cursor

UPLOAD_DIR = "/mnt/archie_brain/platform_v2/uploads/family_tree"
PHOTO_TYPES = {"jpg", "jpeg", "png", "webp", "tiff"}


def _ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def register_photo_routes(bp, admin_required):
    """Register photo management endpoints on the blueprint."""

    @bp.route("/api/photos")
    @login_required
    def api_list_photos():
        type_list = ", ".join(f"'{t}'" for t in PHOTO_TYPES)
        sql = f"""
            SELECT * FROM family_documents
            WHERE user_id = %(user_id)s
              AND file_type IN ({type_list})
            ORDER BY uploaded_at DESC
        """
        with get_db_cursor() as (conn, cur):
            cur.execute(sql, {"user_id": current_user.id})
            rows = [dict(r) for r in cur.fetchall()]
        return jsonify(rows)

    @bp.route("/api/photos/upload", methods=["POST"])
    @login_required
    def api_upload_photo():
        _ensure_upload_dir()
        f = request.files.get("file")
        if f is None:
            return jsonify({"error": "No file provided"}), 400

        original_name = f.filename or "photo"
        ext = os.path.splitext(original_name)[1].lower().lstrip(".")
        if ext not in PHOTO_TYPES:
            return jsonify({"error": f"Unsupported photo type: {ext}"}), 400

        unique_name = f"{uuid.uuid4().hex}.{ext}"
        save_path = os.path.join(UPLOAD_DIR, unique_name)
        f.save(save_path)

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
                    "file_type": ext,
                    "file_path": save_path,
                },
            )
            row = cur.fetchone()

        if row is None:
            return jsonify({"error": "Failed to save photo record"}), 500

        doc = dict(row)
        doc_id = doc["id"]

        # Auto-detect faces
        faces_detected = []
        try:
            from .services.face_service import detect_faces

            faces_detected = detect_faces(doc_id, save_path, current_user.id)
        except Exception:
            pass  # Face detection failure is non-blocking

        doc["faces_detected"] = faces_detected
        return jsonify(doc), 201

    @bp.route("/api/photos/faces")
    @login_required
    def api_get_face_clusters():
        from .services.face_service import get_face_clusters

        clusters = get_face_clusters(current_user.id)
        return jsonify(clusters)

    @bp.route("/api/photos/cluster", methods=["POST"])
    @login_required
    def api_cluster_faces():
        from .services.face_service import cluster_faces

        result = cluster_faces(current_user.id)
        return jsonify(result)

    @bp.route("/api/photos/faces/<int:face_id>/label", methods=["POST"])
    @login_required
    def api_label_face(face_id):
        data = request.get_json(silent=True) or {}
        from .services.face_service import label_face

        result = label_face(face_id, current_user.id, data)
        if result is None:
            return jsonify({"error": "Face not found"}), 404
        return jsonify(result)

    @bp.route("/api/photos/<int:doc_id>/restore", methods=["POST"])
    @login_required
    def api_restore_photo(doc_id):
        # ComfyUI integration TBD — return queued status
        return jsonify(
            {
                "status": "queued",
                "doc_id": doc_id,
                "message": "Photo restoration queued. ComfyUI integration coming soon.",
            }
        )

    @bp.route("/api/photos/<int:doc_id>/serve")
    @login_required
    def api_serve_photo(doc_id):
        sql = """
            SELECT file_path, file_type FROM family_documents
            WHERE id = %(id)s AND user_id = %(user_id)s
        """
        with get_db_cursor() as (conn, cur):
            cur.execute(sql, {"id": doc_id, "user_id": current_user.id})
            row = cur.fetchone()

        if row is None:
            return jsonify({"error": "Photo not found"}), 404

        file_path = row["file_path"]
        file_type = row["file_type"]

        if not file_path or not os.path.isfile(file_path):
            return jsonify({"error": "File not found on disk"}), 404

        mimetype = mimetypes.types_map.get(f".{file_type}", "application/octet-stream")
        return send_file(file_path, mimetype=mimetype)
