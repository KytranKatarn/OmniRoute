"""
Async download routes — prepare, poll, retrieve.
POST  /api/download/prepare/<backup_name>  → {job_id, status}
GET   /api/download/status/<job_id>        → {status, file_size_bytes, ...}
GET   /api/download/retrieve/<job_id>      → sends file (one-time, auto-deletes after)
"""

import os

from flask import jsonify, send_file


def register_download_routes(bp, admin_required):

    @bp.route("/api/download/prepare/<backup_name>", methods=["POST"])
    @admin_required
    def prepare_backup_download(backup_name):
        """Kick off async tar.gz creation for a backup."""
        from flask_login import current_user

        from services.backup_download_service import prepare_download

        result = prepare_download(
            backup_name=backup_name,
            triggered_by=getattr(current_user, "username", "unknown"),
        )
        return jsonify(result), 200 if result["success"] else 400

    @bp.route("/api/download/status/<int:job_id>", methods=["GET"])
    @admin_required
    def get_download_job_status(job_id):
        """Poll download preparation status."""
        from services.backup_download_service import get_download_status

        return jsonify(get_download_status(job_id))

    @bp.route("/api/download/retrieve/<int:job_id>", methods=["GET"])
    @admin_required
    def retrieve_prepared_download(job_id):
        """Serve the prepared archive file (one-time — marks as used and schedules file deletion)."""
        from services.backup_download_service import serve_and_delete

        result = serve_and_delete(job_id)
        if not result["success"]:
            return jsonify(result), 404

        archive_path = result["archive_path"]
        if not os.path.exists(archive_path):
            return jsonify({"success": False, "error": "archive_file_missing"}), 404

        # Strip the job-id prefix to get a clean download filename
        filename = os.path.basename(archive_path).replace(f"download_{job_id}_", "")

        def _delete_after():
            try:
                if os.path.exists(archive_path):
                    os.remove(archive_path)
            except Exception:
                pass

        try:
            response = send_file(archive_path, as_attachment=True, download_name=filename)
            response.call_on_close(_delete_after)
            return response
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
