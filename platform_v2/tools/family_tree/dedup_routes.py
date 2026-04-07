"""Family Tree — Dedup/merge endpoints for duplicate person detection and merging."""

from flask import jsonify, request
from flask_login import current_user, login_required

from .services.dedup_service import find_duplicates, merge_persons


def register_dedup_routes(bp, admin_required):
    """Register dedup management endpoints on the blueprint."""

    @bp.route("/api/dedup/candidates")
    @login_required
    def api_dedup_candidates():
        """Return potential duplicate person pairs with similarity scores."""
        try:
            candidates = find_duplicates(current_user.id)
            return jsonify({"candidates": candidates, "count": len(candidates)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/dedup/merge", methods=["POST"])
    @login_required
    def api_dedup_merge():
        """Merge two persons: keep one, absorb the other."""
        data = request.get_json(silent=True) or {}
        keep_id = data.get("keep_id")
        merge_id = data.get("merge_id")

        if not keep_id or not merge_id:
            return jsonify({"error": "keep_id and merge_id are required"}), 400

        try:
            keep_id = int(keep_id)
            merge_id = int(merge_id)
        except (ValueError, TypeError):
            return jsonify({"error": "keep_id and merge_id must be integers"}), 400

        try:
            result = merge_persons(current_user.id, keep_id, merge_id)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500
