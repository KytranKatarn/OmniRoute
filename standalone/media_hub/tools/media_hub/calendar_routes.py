"""Media Hub API routes."""

from . import media_hub_bp
from .routes_shared import *  # noqa: F401,F403

@media_hub_bp.route("/api/calendar/upcoming")
def api_calendar_upcoming():
    """Get upcoming episodes from Sonarr"""
    days = request.args.get("days", 7, type=int)
    start_date = request.args.get("start")  # Optional: YYYY-MM-DD format

    sonarr_config = get_service_config("sonarr")
    if not sonarr_config or not sonarr_config.get("api_key"):
        return jsonify({"success": False, "error": "Sonarr not configured", "episodes": []})

    try:
        from .clients.sonarr import SonarrClient

        sonarr = SonarrClient(
            host=sonarr_config["host"],
            port=sonarr_config["port"],
            api_key=sonarr_config["api_key"],
            use_ssl=sonarr_config["use_ssl"],
        )
        episodes = sonarr.get_upcoming_episodes(days, start_date)
        return jsonify(
            {
                "success": True,
                "episodes": [ep.to_dict() for ep in episodes],
                "days": days,
                "start": start_date,
            }
        )
    except Exception as e:
        logger.error(f"Error getting calendar: {e}")
        return jsonify({"success": False, "error": str(e), "episodes": []})

@media_hub_bp.route("/api/downloads")
def api_downloads():
    """Get current downloads from SABnzbd"""
    sabnzbd_config = get_service_config("sabnzbd")
    if not sabnzbd_config or not sabnzbd_config.get("api_key"):
        return jsonify(
            {
                "success": False,
                "error": "SABnzbd not configured",
                "queue": [],
                "history": [],
            }
        )

    try:
        from .clients.sabnzbd import SABnzbdClient

        sabnzbd = SABnzbdClient(
            host=sabnzbd_config["host"],
            port=sabnzbd_config["port"],
            api_key=sabnzbd_config["api_key"],
            use_ssl=sabnzbd_config["use_ssl"],
        )

        queue = sabnzbd.get_queue()
        history = sabnzbd.get_history(10)
        speed = sabnzbd.get_speed()

        return jsonify(
            {
                "success": True,
                "queue": [item.to_dict() for item in queue],
                "history": [item.to_dict() for item in history],
                "speed": speed,
            }
        )
    except Exception as e:
        logger.error(f"Error getting downloads: {e}")
        return jsonify({"success": False, "error": str(e), "queue": [], "history": []})

@media_hub_bp.route("/api/settings")
def api_settings():
    """Get all service configurations (without decrypted API keys)"""
    services = get_all_services()
    return jsonify(
        {
            "success": True,
            "services": services,
            "encryption_key_source": get_key_source(),
        }
    )
