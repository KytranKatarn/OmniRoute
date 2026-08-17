"""
PCAP Routes — Packet capture management endpoints.
ADR-045 pattern: register_pcap_routes(bp, admin_required_decorator)
"""

import logging
import os
import re
import subprocess
import time
from datetime import datetime, timezone

from flask import jsonify, request, send_file
from flask_login import login_required
from database import get_db_cursor

logger = logging.getLogger(__name__)

# Module-level dict tracking running captures: capture_id -> Popen process
_running_captures = {}

# Strict IP validation pattern
_IP_PATTERN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")

MAX_DURATION = 300  # 5 minutes max


def _validate_ip(ip_str):
    """Validate an IPv4 address string."""
    if not _IP_PATTERN.match(ip_str):
        return False
    parts = ip_str.split(".")
    return all(0 <= int(p) <= 255 for p in parts)


def register_pcap_routes(bp, admin_required_decorator):
    """Register packet capture endpoints on the blueprint."""

    @bp.route("/api/pcap/start", methods=["POST"])
    @login_required
    @admin_required_decorator
    def pcap_start():
        """Start a packet capture for a specific device IP."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({"status": "error", "message": "JSON body required"}), 400

            device_ip = data.get("device_ip", "").strip()
            if not device_ip or not _validate_ip(device_ip):
                return (
                    jsonify({"status": "error", "message": "Invalid device_ip"}),
                    400,
                )

            duration = min(int(data.get("duration", 60)), MAX_DURATION)
            if duration < 1:
                duration = 60

            # Create DB record first to get capture ID
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "INSERT INTO pcap_captures (device_ip, duration, status) "
                    "VALUES (%s, %s, 'running') RETURNING id",
                    (device_ip, duration),
                )
                capture_id = cur.fetchone()["id"]

            # Build file path
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            safe_ip = device_ip.replace(".", "-")
            filepath = f"/tmp/pcap_{capture_id}_{safe_ip}_{ts}.pcap"

            # Start tcpdump subprocess
            cmd = [
                "tcpdump",
                "-i",
                "any",
                "-w",
                filepath,
                "host",
                device_ip,
            ]
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
            except FileNotFoundError:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE pcap_captures SET status = 'error' WHERE id = %s",
                        (capture_id,),
                    )
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "tcpdump not found on system",
                        }
                    ),
                    500,
                )

            _running_captures[capture_id] = proc

            # Update DB with file path
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE pcap_captures SET file_path = %s WHERE id = %s",
                    (filepath, capture_id),
                )

            # Schedule auto-stop after duration (in a thread)
            import threading

            def _auto_stop():
                time.sleep(duration)
                _stop_capture(capture_id)

            t = threading.Thread(target=_auto_stop, daemon=True)
            t.start()

            return jsonify(
                {
                    "status": "ok",
                    "capture_id": capture_id,
                    "device_ip": device_ip,
                    "duration": duration,
                    "file_path": filepath,
                }
            )

        except Exception as e:
            logger.error("[PCAP] Start failed: %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route("/api/pcap/stop/<int:capture_id>", methods=["POST"])
    @login_required
    @admin_required_decorator
    def pcap_stop(capture_id):
        """Stop a running packet capture."""
        try:
            result = _stop_capture(capture_id)
            if result.get("error"):
                return jsonify({"status": "error", "message": result["error"]}), 400
            return jsonify({"status": "ok", **result})
        except Exception as e:
            logger.error("[PCAP] Stop failed: %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route("/api/pcap/list", methods=["GET"])
    @login_required
    @admin_required_decorator
    def pcap_list():
        """List all packet captures."""
        try:
            limit = min(int(request.args.get("limit", 50)), 200)
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT * FROM pcap_captures ORDER BY started_at DESC LIMIT %s",
                    (limit,),
                )
                captures = [dict(row) for row in cur.fetchall()]
            return jsonify({"status": "ok", "captures": captures, "count": len(captures)})
        except Exception as e:
            logger.error("[PCAP] List failed: %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route("/api/pcap/download/<int:capture_id>", methods=["GET"])
    @login_required
    @admin_required_decorator
    def pcap_download(capture_id):
        """Download a completed pcap file."""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT file_path, status FROM pcap_captures WHERE id = %s",
                    (capture_id,),
                )
                row = cur.fetchone()

            if not row:
                return jsonify({"status": "error", "message": "Capture not found"}), 404

            filepath = row["file_path"]
            if not filepath or not os.path.exists(filepath):
                return (
                    jsonify({"status": "error", "message": "Capture file not available"}),
                    404,
                )

            return send_file(
                filepath,
                mimetype="application/vnd.tcpdump.pcap",
                as_attachment=True,
                download_name=os.path.basename(filepath),
            )
        except Exception as e:
            logger.error("[PCAP] Download failed: %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500


def _stop_capture(capture_id):
    """Stop a running capture, update DB. Returns dict with result or error."""
    proc = _running_captures.pop(capture_id, None)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "SELECT file_path, status FROM pcap_captures WHERE id = %s",
                (capture_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"error": "Capture not found"}

            file_size = 0
            if row["file_path"] and os.path.exists(row["file_path"]):
                file_size = os.path.getsize(row["file_path"])

            cur.execute(
                "UPDATE pcap_captures SET status = 'completed', " "file_size = %s, stopped_at = NOW() WHERE id = %s",
                (file_size, capture_id),
            )
            return {"capture_id": capture_id, "file_size": file_size, "status": "completed"}
    except Exception as e:
        logger.error("[PCAP] Stop capture DB update failed: %s", e)
        return {"error": "Internal server error"}
