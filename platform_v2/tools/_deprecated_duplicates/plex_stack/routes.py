"""
Plex Stack Routes - Unified Plex Ecosystem Management
Services: Plex, Sonarr, Radarr, Prowlarr, Overseerr, SABnzbd
"""

from flask import render_template, jsonify, request
from . import plex_stack_bp
import subprocess
import requests
import logging

logger = logging.getLogger(__name__)

# Service configuration
PLEX_HOST = "192.168.1.200"
PLEX_SERVICES = {
    "plex": {"port": 32400, "path": "/web", "icon": "play-circle", "name": "Plex", "color": "#E5A00D"},
    "sonarr": {"port": 8989, "path": "", "icon": "tv", "name": "Sonarr", "color": "#00CCFF"},
    "radarr": {"port": 7878, "path": "", "icon": "film", "name": "Radarr", "color": "#FFC230"},
    "prowlarr": {"port": 9696, "path": "", "icon": "search", "name": "Prowlarr", "color": "#E66000"},
    "overseerr": {"port": 5055, "path": "", "icon": "inbox", "name": "Overseerr", "color": "#7B2D8E"},
    "sabnzbd": {"port": 8083, "path": "", "icon": "download", "name": "SABnzbd", "color": "#F0A000"},
}


@plex_stack_bp.route("/")
def index():
    """Plex Stack main page"""
    return render_template("tools/plex_stack.html", services=PLEX_SERVICES, host=PLEX_HOST)


@plex_stack_bp.route("/api/status")
def api_status():
    """Get status of all Plex stack services"""
    statuses = {}

    for service_id, config in PLEX_SERVICES.items():
        url = f"http://{PLEX_HOST}:{config['port']}{config.get('path', '')}"
        try:
            response = requests.get(url, timeout=3)
            statuses[service_id] = {
                "online": True,
                "status_code": response.status_code,
                "response_time": response.elapsed.total_seconds() * 1000,
                "url": url,
            }
        except requests.exceptions.RequestException as e:
            statuses[service_id] = {"online": False, "error": str(e), "url": url}

    # Get container status from Docker
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        name = parts[0].lower()
                        if name in statuses:
                            statuses[name]["container_status"] = parts[1]
                            statuses[name]["running"] = "Up" in parts[1]
    except Exception as e:
        logger.error(f"Failed to get docker status: {e}")

    return jsonify({"success": True, "services": statuses, "host": PLEX_HOST})


@plex_stack_bp.route("/api/services/<service_name>/action", methods=["POST"])
def api_service_action(service_name):
    """Perform action on a service container"""
    if service_name not in PLEX_SERVICES:
        return jsonify({"success": False, "error": "Unknown service"}), 404

    data = request.get_json() or {}
    action = data.get("action", "restart")

    if action not in ["start", "stop", "restart"]:
        return jsonify({"success": False, "error": "Invalid action"}), 400

    try:
        result = subprocess.run(["docker", action, service_name], capture_output=True, text=True, timeout=60)

        if result.returncode == 0:
            return jsonify({"success": True, "message": f"{service_name} {action}ed successfully"})
        else:
            return jsonify({"success": False, "error": result.stderr or "Action failed"}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Command timed out"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@plex_stack_bp.route("/api/services/<service_name>/logs")
def api_service_logs(service_name):
    """Get logs for a service container"""
    if service_name not in PLEX_SERVICES:
        return jsonify({"success": False, "error": "Unknown service"}), 404

    lines = request.args.get("lines", 100, type=int)

    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(lines), service_name], capture_output=True, text=True, timeout=30
        )

        # Docker logs go to stderr for some containers
        logs = result.stdout or result.stderr

        return jsonify({"success": True, "service": service_name, "logs": logs, "lines": lines})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@plex_stack_bp.route("/api/activity")
def api_activity():
    """Get recent activity from SABnzbd"""
    # SABnzbd API endpoint
    sabnzbd_url = f"http://{PLEX_HOST}:8083/api"

    try:
        # Get queue
        queue_response = requests.get(sabnzbd_url, params={"mode": "queue", "output": "json"}, timeout=5)

        # Get history
        history_response = requests.get(
            sabnzbd_url, params={"mode": "history", "output": "json", "limit": 10}, timeout=5
        )

        queue_data = queue_response.json() if queue_response.ok else {}
        history_data = history_response.json() if history_response.ok else {}

        return jsonify(
            {
                "success": True,
                "queue": queue_data.get("queue", {}).get("slots", []),
                "history": history_data.get("history", {}).get("slots", []),
                "speed": queue_data.get("queue", {}).get("speed", "0"),
                "size_left": queue_data.get("queue", {}).get("sizeleft", "0"),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "queue": [], "history": []})


@plex_stack_bp.route("/api/search")
def api_search():
    """Search for movies/TV shows via Overseerr"""
    query = request.args.get("q", "")
    if not query or len(query) < 2:
        return jsonify({"success": False, "error": "Query too short", "results": []})

    overseerr_url = f"http://{PLEX_HOST}:5055/api/v1/search"

    try:
        response = requests.get(overseerr_url, params={"query": query, "page": 1, "language": "en"}, timeout=10)

        if response.ok:
            data = response.json()
            return jsonify(
                {"success": True, "results": data.get("results", [])[:10], "total": data.get("totalResults", 0)}
            )
        else:
            return jsonify({"success": False, "error": f"Overseerr returned {response.status_code}", "results": []})
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "results": []})


@plex_stack_bp.route("/api/health")
def api_health():
    """Health check endpoint for module registry"""
    return jsonify(
        {"module": "plex_stack", "status": "active", "healthy": True, "message": "Plex Stack module operational"}
    )
