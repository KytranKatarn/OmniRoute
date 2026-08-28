"""Fleet Module — Mission routes (SSE, starship command, mission profiles, flows, mesh)"""

import json
import time
import logging
from datetime import datetime, timezone
from flask import jsonify, request, Response, stream_with_context
from flask_login import login_required, current_user
from psycopg2.extras import RealDictCursor
from rbac import require_permission, Permission
from database import get_db_cursor

from .fleet_helpers import get_starship_node_for_user, _activity_queue

logger = logging.getLogger(__name__)


def register_mission_routes(bp, admin_required):
    """Register mission-related routes on the fleet blueprint."""

    # ============================================================================
    # Phase 6: Mission Control — SSE + Activity Endpoints
    # ============================================================================

    @bp.route("/api/dispatch/stream")
    @login_required
    def activity_stream():
        """SSE endpoint for real-time agent activity events."""

        def generate():
            last_sent_time = datetime.now(timezone.utc).isoformat() + "Z"
            while True:
                new_events = [e for e in _activity_queue if e["created_at"] > last_sent_time]
                for evt in reversed(new_events):
                    yield "event: {}\ndata: {}\n\n".format(evt["event_type"], json.dumps(evt))
                    last_sent_time = evt["created_at"]
                yield ": heartbeat\n\n"
                time.sleep(5)

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @bp.route("/api/dispatch/activity-history")
    @login_required
    def activity_history():
        """Return last 50 dispatch events from task_execution_log."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT tel.id, 'task' AS source,
                           COALESCE(NULLIF(a.first_name, ''), a.name, tel.agent_name) AS agent_name,
                           tel.module_source, tel.task_type, tel.capability,
                           tel.model_used, tel.success, tel.created_at
                    FROM task_execution_log tel
                    LEFT JOIN agents a ON a.id = tel.agent_id
                    ORDER BY tel.created_at DESC
                    LIMIT 50
                """
                )
                events = cur.fetchall()
                for ev in events:
                    ev["created_at"] = ev["created_at"].isoformat() + "Z" if ev["created_at"] else None
                return jsonify(events)
        except Exception as e:
            logger.error("activity_history error: %s", e)
            return jsonify([])

    # ============================================================================
    # STARSHIP COMMAND API
    # ============================================================================

    @bp.route("/api/starship/status")
    @login_required
    def starship_status():
        """Get current user's starship node status."""
        user_id = current_user.id if current_user.is_authenticated else None
        if not user_id:
            return jsonify({"success": False, "error": "Not authenticated"}), 401
        node = get_starship_node_for_user(user_id)
        if not node:
            return jsonify({"success": False, "error": "Not a starship operator"}), 403

        node_id = node["node_id"]
        with get_db_cursor() as (conn, cur):
            # Get job stats
            cur.execute(
                """
                SELECT COUNT(*) as total_jobs,
                       COUNT(*) FILTER (WHERE status = 'completed') as completed_jobs
                FROM bridge_jobs WHERE agent_name LIKE %s
            """,
                (f"%{node_id}%",),
            )
            stats = cur.fetchone()

            # Get models
            cur.execute(
                """
                SELECT model_name, model_size_gb, is_available
                FROM node_ollama_models WHERE node_id = %s ORDER BY model_name
            """,
                (node_id,),
            )
            models = [dict(m) for m in cur.fetchall()]

        return jsonify(
            {
                "success": True,
                "node": dict(node),
                "models": models,
                "stats": dict(stats) if stats else {},
            }
        )

    @bp.route("/api/starship/profile", methods=["POST"])
    @login_required
    def starship_update_profile():
        """Update starship node display name."""
        user_id = current_user.id if current_user.is_authenticated else None
        if not user_id:
            return jsonify({"success": False, "error": "Not authenticated"}), 401
        node = get_starship_node_for_user(user_id)
        if not node:
            return jsonify({"success": False, "error": "Not a starship operator"}), 403

        data = request.get_json() or {}
        display_name = data.get("display_name", "").strip()
        if not display_name or len(display_name) > 100:
            return jsonify({"success": False, "error": "Invalid name"}), 400

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE remote_nodes SET node_name = %s, updated_at = NOW()
                WHERE node_id = %s
            """,
                (display_name, node["node_id"]),
            )

        return jsonify({"success": True})

    # ============================================================================
    # MISSION PROFILES
    # ============================================================================

    @bp.route("/api/mission/active")
    @login_required
    def api_mission_active():
        """Get current active mission profile."""
        try:
            from ai_bridge.mission_manager import MissionManager

            mm = MissionManager()
            profile = mm.get_active_profile()
            return jsonify({"success": True, "profile": profile})
        except Exception as e:
            logger.exception("Failed to get active mission profile")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/mission/profiles")
    @login_required
    def api_mission_profiles():
        """List all mission profiles."""
        try:
            from ai_bridge.mission_manager import MissionManager

            mm = MissionManager()
            profiles = mm.get_all_profiles()
            return jsonify({"success": True, "profiles": profiles})
        except Exception as e:
            logger.exception("Failed to list mission profiles")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/mission/activate/<int:profile_id>", methods=["PUT"])
    @login_required
    def api_mission_activate(profile_id):
        """Activate a mission profile."""
        try:
            from ai_bridge.mission_manager import MissionManager

            mm = MissionManager()
            profile = mm.activate_profile(profile_id, triggered_by="manual", reason="User activated from Bridge UI")
            if profile:
                return jsonify({"success": True, "profile": profile})
            return jsonify({"success": False, "error": "Profile not found"}), 404
        except Exception as e:
            logger.exception("Failed to activate mission profile")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/mission/schedule", methods=["GET"])
    @login_required
    def api_mission_schedule_list():
        """List mission schedules."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT ms.*, mp.name as profile_name, mp.display_name as profile_display_name
                    FROM mission_schedules ms
                    JOIN mission_profiles mp ON mp.id = ms.profile_id
                    ORDER BY ms.id
                """
                )
                schedules = [dict(r) for r in cur.fetchall()]
            return jsonify({"success": True, "schedules": schedules})
        except Exception as e:
            logger.exception("Failed to list mission schedules")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/mission/schedule", methods=["POST"])
    @login_required
    def api_mission_schedule_add():
        """Add a mission schedule rule."""
        try:
            data = request.get_json() or {}
            profile_id = data.get("profile_id")
            cron = data.get("cron_expression")
            duration = data.get("duration_minutes")
            if not profile_id or not cron:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "profile_id and cron_expression required",
                        }
                    ),
                    400,
                )
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "INSERT INTO mission_schedules (profile_id, cron_expression, duration_minutes) VALUES (%s, %s, %s) RETURNING id",
                    (profile_id, cron, duration),
                )
                new_id = cur.fetchone()[0] if cur.description else None
            return jsonify({"success": True, "id": new_id})
        except Exception as e:
            logger.exception("Failed to add mission schedule")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/mission/schedule/<int:schedule_id>", methods=["DELETE"])
    @login_required
    def api_mission_schedule_delete(schedule_id):
        """Delete a mission schedule rule."""
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("DELETE FROM mission_schedules WHERE id = %s", (schedule_id,))
            return jsonify({"success": True})
        except Exception as e:
            logger.exception("Failed to delete mission schedule")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # FLOW ROUTER API ROUTES (Task #957)
    # ============================================================================

    @bp.route("/api/flows")
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def api_list_flows():
        """List available workflow flows."""
        try:
            from ai_bridge.mission_manager import WORKFLOW_FLOWS

            flows = []
            for key, flow in WORKFLOW_FLOWS.items():
                flows.append(
                    {
                        "key": key,
                        "name": flow["name"],
                        "description": flow.get("description", ""),
                        "steps": len(flow["steps"]),
                        "stations": list(dict.fromkeys(s["station"] for s in flow["steps"])),
                    }
                )
            return jsonify({"success": True, "flows": flows})
        except Exception as e:
            logger.exception("Failed to list flows")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/flows/<flow_name>/start", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def api_start_flow(flow_name):
        """Start a workflow flow."""
        try:
            from ai_bridge.mission_manager import MissionManager

            data = request.get_json(silent=True) or {}
            initial_data = data.get("initial_data", {})

            mgr = MissionManager()
            result = mgr.start_flow(flow_name, initial_data=initial_data)

            if result is None:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Unknown flow or job creation failed: {flow_name}",
                        }
                    ),
                    400,
                )

            return jsonify({"success": True, **result})
        except Exception as e:
            logger.exception("Failed to start flow")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/flows/advance/<int:job_id>", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def api_advance_flow(job_id):
        """Advance a workflow flow after a job completes."""
        try:
            from ai_bridge.mission_manager import MissionManager

            data = request.get_json(silent=True) or {}
            job_result = data.get("job_result", {})

            mgr = MissionManager()
            result = mgr.advance_flow(job_id, job_result=job_result)

            if result is None:
                return (
                    jsonify({"success": False, "error": "Job has no flow metadata"}),
                    404,
                )

            return jsonify({"success": True, **result})
        except Exception as e:
            logger.exception("Failed to advance flow")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # MESH CLUSTER API ROUTES — registered in __init__.py (ADR-045 pattern)
    # ============================================================================
