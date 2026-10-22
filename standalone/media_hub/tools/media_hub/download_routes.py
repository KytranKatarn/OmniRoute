"""Media Hub API routes."""

from . import media_hub_bp
from .routes_shared import *  # noqa: F401,F403

def get_sabnzbd_client():
    """Get SABnzbd client instance"""
    sabnzbd_config = get_service_config("sabnzbd")
    if not sabnzbd_config or not sabnzbd_config.get("api_key"):
        return None

    from .clients.sabnzbd import SABnzbdClient

    return SABnzbdClient(
        host=sabnzbd_config["host"],
        port=sabnzbd_config["port"],
        api_key=sabnzbd_config["api_key"],
        use_ssl=sabnzbd_config["use_ssl"],
    )

@media_hub_bp.route("/api/downloads/pause", methods=["POST"])
def api_downloads_pause_all():
    """Pause all downloads"""
    client = get_sabnzbd_client()
    if not client:
        return jsonify({"success": False, "error": "SABnzbd not configured"})

    try:
        result = client.pause_queue()
        return jsonify(
            {
                "success": result,
                "message": "Queue paused" if result else "Failed to pause",
            }
        )
    except Exception as e:
        logger.error(f"Error pausing downloads: {e}")
        return jsonify({"success": False, "error": str(e)})

@media_hub_bp.route("/api/downloads/resume", methods=["POST"])
def api_downloads_resume_all():
    """Resume all downloads"""
    client = get_sabnzbd_client()
    if not client:
        return jsonify({"success": False, "error": "SABnzbd not configured"})

    try:
        result = client.resume_queue()
        return jsonify(
            {
                "success": result,
                "message": "Queue resumed" if result else "Failed to resume",
            }
        )
    except Exception as e:
        logger.error(f"Error resuming downloads: {e}")
        return jsonify({"success": False, "error": str(e)})

@media_hub_bp.route("/api/downloads/<nzo_id>/pause", methods=["POST"])
def api_download_pause(nzo_id):
    """Pause a specific download"""
    client = get_sabnzbd_client()
    if not client:
        return jsonify({"success": False, "error": "SABnzbd not configured"})

    try:
        result = client.pause_item(nzo_id)
        return jsonify({"success": result})
    except Exception as e:
        logger.error(f"Error pausing download: {e}")
        return jsonify({"success": False, "error": str(e)})

@media_hub_bp.route("/api/downloads/<nzo_id>/resume", methods=["POST"])
def api_download_resume(nzo_id):
    """Resume a specific download"""
    client = get_sabnzbd_client()
    if not client:
        return jsonify({"success": False, "error": "SABnzbd not configured"})

    try:
        result = client.resume_item(nzo_id)
        return jsonify({"success": result})
    except Exception as e:
        logger.error(f"Error resuming download: {e}")
        return jsonify({"success": False, "error": str(e)})

@media_hub_bp.route("/api/downloads/<nzo_id>", methods=["DELETE"])
@media_hub_admin_required
def api_download_delete(nzo_id):
    """Delete a download from queue"""
    client = get_sabnzbd_client()
    if not client:
        return jsonify({"success": False, "error": "SABnzbd not configured"})

    try:
        result = client.delete_item(nzo_id)
        return jsonify({"success": result})
    except Exception as e:
        logger.error(f"Error deleting download: {e}")
        return jsonify({"success": False, "error": str(e)})

@media_hub_bp.route("/api/downloads/speed", methods=["POST"])
def api_set_speed_limit():
    """Set download speed limit"""
    data = request.get_json() or {}
    limit_kbps = data.get("limit", 0)  # 0 = unlimited

    client = get_sabnzbd_client()
    if not client:
        return jsonify({"success": False, "error": "SABnzbd not configured"})

    try:
        result = client.set_speed_limit(limit_kbps)
        return jsonify({"success": result, "limit_kbps": limit_kbps})
    except Exception as e:
        logger.error(f"Error setting speed limit: {e}")
        return jsonify({"success": False, "error": str(e)})
