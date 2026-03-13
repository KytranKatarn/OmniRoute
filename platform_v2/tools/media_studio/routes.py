"""Media Studio API routes — thin HTTP handlers calling services.

All generation routes through Bridge dispatcher. Gallery with
per-user ownership. ComfyUI fleet status with GPU tiering.
"""

import logging

from flask import jsonify, request, render_template
from flask_login import login_required, current_user

from . import media_studio_bp

logger = logging.getLogger(__name__)


# ─── Page Route ─────────────────────────────────────────────────────


@media_studio_bp.route("/")
@login_required
def index():
    """Render the Media Studio LCARS UI."""
    return render_template("tools/media_studio/media_studio.html")


# ─── Dashboard ──────────────────────────────────────────────────────


@media_studio_bp.route("/api/dashboard")
@login_required
def api_dashboard():
    """Dashboard stats, recent generations, fleet GPU status."""
    from .services.generation_service import get_dashboard_stats
    from .services.comfyui_manager import get_fleet_comfyui_status

    stats = get_dashboard_stats(current_user.id)
    fleet = get_fleet_comfyui_status()

    return jsonify({"stats": stats, "fleet": fleet})


# ─── Generation ─────────────────────────────────────────────────────


@media_studio_bp.route("/api/generate", methods=["POST"])
@login_required
def api_generate():
    """Submit a generation request."""
    from .services.generation_service import submit_generation

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    media_type = data.get("media_type", "image")
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    result = submit_generation(
        user_id=current_user.id,
        media_type=media_type,
        prompt=prompt,
        negative_prompt=data.get("negative_prompt", ""),
        params={k: data[k] for k in ("model", "width", "height", "steps", "cfg", "sampler", "seed") if k in data},
    )

    if "error" in result:
        return jsonify(result), 400 if "Unsupported" in result["error"] else 500

    return jsonify(result), 201


# ─── Queue ──────────────────────────────────────────────────────────


@media_studio_bp.route("/api/queue")
@login_required
def api_queue():
    """Get generation queue for current user."""
    from .services.generation_service import get_queue_status

    limit = request.args.get("limit", 20, type=int)
    jobs = get_queue_status(owner_type="user", owner_id=current_user.id, limit=limit)
    return jsonify({"jobs": jobs})


@media_studio_bp.route("/api/queue/<int:queue_id>/cancel", methods=["POST"])
@login_required
def api_cancel_job(queue_id):
    """Cancel a pending/dispatched generation job."""
    from .services.generation_service import cancel_generation

    ok = cancel_generation(queue_id, current_user.id)
    if ok:
        return jsonify({"status": "cancelled"})
    return jsonify({"error": "Job not found or not cancellable"}), 404


# ─── Gallery ────────────────────────────────────────────────────────


@media_studio_bp.route("/api/gallery")
@login_required
def api_gallery():
    """Paginated gallery for current user."""
    from .services.gallery_service import get_gallery

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    media_type = request.args.get("type")
    favorites = request.args.get("favorites", "false").lower() == "true"

    result = get_gallery(
        owner_type="user",
        owner_id=current_user.id,
        media_type=media_type,
        favorites_only=favorites,
        page=page,
        per_page=per_page,
    )
    return jsonify(result)


@media_studio_bp.route("/api/gallery/<int:media_id>")
@login_required
def api_gallery_detail(media_id):
    """Single media detail with full metadata."""
    from .services.gallery_service import get_media_detail

    item = get_media_detail(media_id, "user", current_user.id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    return jsonify(item)


@media_studio_bp.route("/api/gallery/<int:media_id>/favorite", methods=["POST"])
@login_required
def api_toggle_favorite(media_id):
    """Toggle favorite on a media item."""
    from .services.gallery_service import toggle_favorite

    new_state = toggle_favorite(media_id, "user", current_user.id)
    if new_state is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"is_favorite": new_state})


@media_studio_bp.route("/api/gallery/<int:media_id>", methods=["DELETE"])
@login_required
def api_delete_media(media_id):
    """Soft delete a media item."""
    from .services.gallery_service import delete_media

    ok = delete_media(media_id, "user", current_user.id)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"status": "deleted"})


# ─── Models + ComfyUI Status ───────────────────────────────────────


@media_studio_bp.route("/api/models")
@login_required
def api_models():
    """Available ComfyUI models across fleet."""
    from .services.comfyui_manager import get_available_models

    return jsonify({"models": get_available_models()})


@media_studio_bp.route("/api/comfyui/status")
@login_required
def api_comfyui_status():
    """Fleet ComfyUI health with GPU tiers."""
    from .services.comfyui_manager import get_fleet_comfyui_status

    return jsonify({"nodes": get_fleet_comfyui_status()})


# ─── Assignments ────────────────────────────────────────────────────


@media_studio_bp.route("/api/assignments/<target_type>/<int:target_id>")
@login_required
def api_get_assignment(target_type, target_id):
    """Get active media assignments for a target."""
    from .services.gallery_service import get_active_assignment

    assignment_type = request.args.get("type", "")
    if not assignment_type:
        return jsonify({"error": "type parameter required"}), 400

    result = get_active_assignment(assignment_type, target_type, target_id)
    return jsonify({"assignment": result})


@media_studio_bp.route("/api/assignments", methods=["POST"])
@login_required
def api_create_assignment():
    """Assign media to a UI location."""
    from .services.gallery_service import assign_media

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    required = ["media_id", "assignment_type", "target_type"]
    if not all(k in data for k in required):
        return jsonify({"error": f"Required: {', '.join(required)}"}), 400

    assignment_id = assign_media(
        media_id=data["media_id"],
        assignment_type=data["assignment_type"],
        target_type=data["target_type"],
        target_id=data.get("target_id"),
    )
    return jsonify({"id": assignment_id}), 201
