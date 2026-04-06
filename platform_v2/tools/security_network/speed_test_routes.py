"""
Speed Test Routes
=================
REST endpoints for running internet speed tests and viewing history.
Uses speedtest-cli for measurements, stores results in speed_test_results.
"""

import json
import logging
import subprocess

from flask import jsonify, request
from flask_login import login_required

from database import get_db_cursor

logger = logging.getLogger(__name__)


def register_speed_test_routes(bp, admin_required_decorator):
    """Register all speed test endpoints."""

    @bp.route("/api/speed-test/history")
    @login_required
    @admin_required_decorator
    def api_speed_test_history():
        """Return speed test history, most recent first."""
        try:
            limit = request.args.get("limit", 50, type=int)
            limit = min(max(limit, 1), 500)

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT id, download_mbps, upload_mbps, ping_ms,
                           server_name, tested_at
                    FROM speed_test_results
                    ORDER BY tested_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()

            results = []
            for r in rows:
                results.append(
                    {
                        "id": r["id"],
                        "download_mbps": float(r["download_mbps"]) if r["download_mbps"] else None,
                        "upload_mbps": float(r["upload_mbps"]) if r["upload_mbps"] else None,
                        "ping_ms": float(r["ping_ms"]) if r["ping_ms"] else None,
                        "server_name": r["server_name"],
                        "tested_at": r["tested_at"].isoformat() if r["tested_at"] else None,
                    }
                )

            return jsonify({"success": True, "results": results, "count": len(results)})
        except Exception as e:
            logger.error("Speed test history error: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/speed-test/run", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_speed_test_run():
        """Run a speed test using speedtest-cli and store the result."""
        try:
            result = subprocess.run(
                ["speedtest-cli", "--json"],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                stderr = result.stderr.strip() if result.stderr else "Unknown error"
                return jsonify({"success": False, "error": f"speedtest-cli failed: {stderr}"}), 500

            data = json.loads(result.stdout)

            download_mbps = round(data.get("download", 0) / 1_000_000, 2)
            upload_mbps = round(data.get("upload", 0) / 1_000_000, 2)
            ping_ms = round(data.get("ping", 0), 2)
            server_name = data.get("server", {}).get("name", "Unknown")

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO speed_test_results
                        (download_mbps, upload_mbps, ping_ms, server_name, tested_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    RETURNING id, tested_at
                    """,
                    (download_mbps, upload_mbps, ping_ms, server_name),
                )
                row = cur.fetchone()

            test_result = {
                "id": row["id"],
                "download_mbps": download_mbps,
                "upload_mbps": upload_mbps,
                "ping_ms": ping_ms,
                "server_name": server_name,
                "tested_at": row["tested_at"].isoformat() if row["tested_at"] else None,
            }

            return jsonify({"success": True, "result": test_result})

        except FileNotFoundError:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "speedtest-cli is not installed. Install with: pip install speedtest-cli",
                    }
                ),
                503,
            )
        except subprocess.TimeoutExpired:
            return jsonify({"success": False, "error": "Speed test timed out after 120 seconds"}), 504
        except json.JSONDecodeError as e:
            logger.error("Failed to parse speedtest-cli output: %s", e)
            return jsonify({"success": False, "error": "Failed to parse speed test output"}), 500
        except Exception as e:
            logger.error("Speed test run error: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/speed-test/latest")
    @login_required
    @admin_required_decorator
    def api_speed_test_latest():
        """Return the most recent speed test result."""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT id, download_mbps, upload_mbps, ping_ms,
                           server_name, tested_at
                    FROM speed_test_results
                    ORDER BY tested_at DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()

            if not row:
                return jsonify({"success": True, "result": None, "message": "No speed tests recorded yet"})

            result = {
                "id": row["id"],
                "download_mbps": float(row["download_mbps"]) if row["download_mbps"] else None,
                "upload_mbps": float(row["upload_mbps"]) if row["upload_mbps"] else None,
                "ping_ms": float(row["ping_ms"]) if row["ping_ms"] else None,
                "server_name": row["server_name"],
                "tested_at": row["tested_at"].isoformat() if row["tested_at"] else None,
            }

            return jsonify({"success": True, "result": result})
        except Exception as e:
            logger.error("Speed test latest error: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500
