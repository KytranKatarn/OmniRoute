"""Family Tree — DNA upload and ethnicity estimation endpoints."""

from flask import jsonify, request
from flask_login import current_user, login_required

from .services.dna_service import (
    delete_dna_profile,
    estimate_ethnicity,
    get_dna_profile,
    parse_dna_file,
    save_dna_profile,
)

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def register_dna_routes(bp, admin_required):
    """Register DNA upload and profile endpoints on the blueprint."""

    @bp.route("/api/dna/upload", methods=["POST"])
    @login_required
    def api_dna_upload():
        """Upload a raw DNA file, parse it, estimate ethnicity, and store."""
        # Consent acknowledgment required
        consent = request.form.get("consent", "").strip().lower()
        if consent != "true":
            return (
                jsonify(
                    {
                        "error": "Consent required. You must acknowledge that you are uploading your own DNA data "
                        "and consent to local processing. Set consent=true in your request.",
                        "consent_required": True,
                    }
                ),
                400,
            )

        provider = request.form.get("provider", "").strip()
        if provider.lower() not in ("23andme", "ancestrydna"):
            return jsonify({"error": "provider must be '23andme' or 'ancestrydna'"}), 400

        if "file" not in request.files:
            return jsonify({"error": "No file uploaded. Use form field 'file'."}), 400

        uploaded = request.files["file"]
        if not uploaded.filename:
            return jsonify({"error": "Empty filename"}), 400

        # Read file content
        raw = uploaded.read()
        if len(raw) > MAX_FILE_SIZE:
            return jsonify({"error": "File too large. Max 50 MB."}), 413

        try:
            file_content = raw.decode("utf-8", errors="replace")
        except Exception:
            return jsonify({"error": "Could not decode file as text"}), 400

        # Parse
        try:
            snp_data = parse_dna_file(file_content, provider)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": f"Parse error: {e}"}), 500

        if snp_data["snp_count"] == 0:
            return jsonify({"error": "No valid SNPs found in file. Check format and provider."}), 400

        # Estimate ethnicity
        ethnicity = estimate_ethnicity(snp_data)

        # Save to DB
        try:
            profile_id = save_dna_profile(
                user_id=current_user.id,
                provider=provider,
                snp_count=snp_data["snp_count"],
                ethnicity_estimates=ethnicity,
                upload_filename=uploaded.filename,
            )
        except Exception as e:
            return jsonify({"error": f"Database error: {e}"}), 500

        return jsonify(
            {
                "success": True,
                "profile_id": profile_id,
                "provider": provider,
                "snp_count": snp_data["snp_count"],
                "ethnicity": ethnicity,
            }
        )

    @bp.route("/api/dna/profile")
    @login_required
    def api_dna_profile():
        """Get all stored DNA profiles for the current user."""
        try:
            profiles = get_dna_profile(current_user.id)
            return jsonify({"profiles": profiles, "count": len(profiles)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/dna/profile/<int:profile_id>", methods=["DELETE"])
    @login_required
    def api_dna_delete(profile_id):
        """Delete a DNA profile by id (only if owned by current user)."""
        try:
            deleted = delete_dna_profile(current_user.id, profile_id)
            if not deleted:
                return jsonify({"error": "Profile not found or not owned by you"}), 404
            return jsonify({"success": True, "deleted_id": profile_id})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
