"""Department HQ fleet job operations and cross-station reporting routes."""

import logging
from datetime import datetime, timezone
from flask import jsonify, request
from flask_login import login_required
from database import get_db_cursor

logger = logging.getLogger(__name__)


def register_dispatch_job_routes(bp, admin_required):
    """Register job operations with the original route guards."""

    @bp.route("/api/bridge/jobs")
    @login_required
    def get_bridge_jobs():
        """Get active and recent bridge jobs with progress info."""
        try:
            limit = request.args.get("limit", 20, type=int)
            limit = min(limit, 100)
            status_filter = request.args.get("status")

            with get_db_cursor(commit=False) as (conn, cur):

                if status_filter:
                    cur.execute(
                        """
                        SELECT bj.id, bj.job_type, bj.module_source, bj.description,
                               bj.total_steps, bj.completed_steps, bj.failed_steps,
                               bj.status,
                               COALESCE(
                                   NULLIF(CONCAT_WS(' ', a.first_name, a.last_name), ''),
                                   a.name,
                                   bj.agent_name
                               ) as agent_display_name,
                               bj.agent_name as agent_callsign,
                               bj.station_code,
                               bj.metadata,
                               bj.created_at, bj.updated_at, bj.completed_at
                        FROM bridge_jobs bj
                        LEFT JOIN agents a ON a.name = bj.agent_name AND a.status = 'active'
                        WHERE bj.status = %s
                        ORDER BY bj.created_at DESC
                        LIMIT %s
                        """,
                        (status_filter, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT bj.id, bj.job_type, bj.module_source, bj.description,
                               bj.total_steps, bj.completed_steps, bj.failed_steps,
                               bj.status,
                               COALESCE(
                                   NULLIF(CONCAT_WS(' ', a.first_name, a.last_name), ''),
                                   a.name,
                                   bj.agent_name
                               ) as agent_display_name,
                               bj.agent_name as agent_callsign,
                               bj.station_code,
                               bj.metadata,
                               bj.created_at, bj.updated_at, bj.completed_at
                        FROM bridge_jobs bj
                        LEFT JOIN agents a ON a.name = bj.agent_name AND a.status = 'active'
                        ORDER BY
                            CASE bj.status
                                WHEN 'running' THEN 0
                                WHEN 'pending' THEN 1
                                ELSE 2
                            END,
                            bj.created_at DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                jobs = cur.fetchall()

                now = datetime.now(timezone.utc)
                result = []
                for j in jobs:
                    total = j["total_steps"] or 1
                    completed = j["completed_steps"] or 0
                    progress_pct = round((completed / total) * 100, 1) if total > 0 else 0

                    # Estimate ETA for running jobs
                    eta_seconds = None
                    if j["status"] == "running" and completed > 0 and j["created_at"]:
                        elapsed = (now - j["created_at"].replace(tzinfo=None)).total_seconds()
                        per_step = elapsed / completed
                        remaining = total - completed
                        eta_seconds = int(per_step * remaining)

                    result.append(
                        {
                            "id": j["id"],
                            "job_type": j["job_type"],
                            "module_source": j["module_source"],
                            "description": j["description"],
                            "total_steps": total,
                            "completed_steps": completed,
                            "failed_steps": j["failed_steps"] or 0,
                            "status": j["status"],
                            "agent_name": j.get("agent_display_name") or j.get("agent_callsign") or "Unknown",
                            "agent_callsign": j.get("agent_callsign") or "",
                            "station_code": j.get("station_code") or "",
                            "metadata": j["metadata"] or {},
                            "progress_pct": progress_pct,
                            "eta_seconds": eta_seconds,
                            "created_at": j["created_at"].isoformat() if j["created_at"] else None,
                            "updated_at": j["updated_at"].isoformat() if j["updated_at"] else None,
                            "completed_at": j["completed_at"].isoformat() if j["completed_at"] else None,
                        }
                    )

                return jsonify({"success": True, "jobs": result, "total": len(result)})

        except Exception as e:
            logger.error(f"Error getting bridge jobs: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/jobs/<int:job_id>")
    @login_required
    def get_bridge_job_detail(job_id):
        """Get single bridge job detail with linked execution log entries."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Get the job
                cur.execute(
                    """
                    SELECT bj.id, bj.job_type, bj.module_source, bj.description,
                           bj.total_steps, bj.completed_steps, bj.failed_steps,
                           bj.status, bj.station_code,
                           COALESCE(
                               NULLIF(CONCAT_WS(' ', a.first_name, a.last_name), ''),
                               a.name,
                               bj.agent_name
                           ) as agent_display_name,
                           bj.metadata,
                           bj.created_at, bj.updated_at, bj.completed_at
                    FROM bridge_jobs bj
                    LEFT JOIN agents a ON a.name = bj.agent_name AND a.status = 'active'
                    WHERE bj.id = %s
                    """,
                    (job_id,),
                )
                job = cur.fetchone()
                if not job:
                    return jsonify({"success": False, "error": "Job not found"}), 404

                # Get linked execution log entries
                cur.execute(
                    """
                    SELECT tel.id,
                           COALESCE(
                               NULLIF(CONCAT_WS(' ', a.first_name, a.last_name), ''),
                               a.name,
                               tel.agent_name
                           ) as agent_name,
                           tel.capability,
                           tel.model_used, tel.duration_ms, tel.success,
                           tel.error_message, tel.created_at
                    FROM task_execution_log tel
                    LEFT JOIN agents a ON a.id = tel.agent_id
                    WHERE tel.job_id = %s
                    ORDER BY tel.created_at
                    """,
                    (job_id,),
                )
                executions = cur.fetchall()

                total = job["total_steps"] or 1
                completed = job["completed_steps"] or 0
                progress_pct = round((completed / total) * 100, 1) if total > 0 else 0

                return jsonify(
                    {
                        "success": True,
                        "job": {
                            "id": job["id"],
                            "job_type": job["job_type"],
                            "module_source": job["module_source"],
                            "description": job["description"],
                            "total_steps": total,
                            "completed_steps": completed,
                            "failed_steps": job["failed_steps"] or 0,
                            "status": job["status"],
                            "agent_name": job.get("agent_display_name") or "Unknown",
                            "station_code": job.get("station_code") or "",
                            "metadata": job["metadata"] or {},
                            "progress_pct": progress_pct,
                            "created_at": job["created_at"].isoformat() if job["created_at"] else None,
                            "updated_at": job["updated_at"].isoformat() if job["updated_at"] else None,
                            "completed_at": job["completed_at"].isoformat() if job["completed_at"] else None,
                        },
                        "executions": [
                            {
                                "id": e["id"],
                                "agent_name": e["agent_name"],
                                "capability": e["capability"],
                                "model": e["model_used"],
                                "duration_ms": e["duration_ms"],
                                "success": e["success"],
                                "error": e.get("error_message"),
                                "timestamp": e["created_at"].isoformat() if e["created_at"] else None,
                            }
                            for e in executions
                        ],
                    }
                )

        except Exception as e:
            logger.error(f"Error getting bridge job detail: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # DURABLE EXECUTION — Resume failed jobs from checkpoint (Task #955)
    # ============================================================================

    @bp.route("/api/bridge/jobs/<int:job_id>/resume", methods=["POST"])
    @login_required
    def api_resume_job(job_id):
        """Resume a failed job from its last checkpoint."""
        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            result = dispatcher.resume_job(job_id)
            if result:
                return jsonify({"success": True, "resumed": result})
            return jsonify({"success": False, "error": "No checkpoint found or job not failed"}), 404
        except Exception as e:
            logger.error(f"Error resuming job {job_id}: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/jobs/<int:job_id>/delegate", methods=["POST"])
    @login_required
    def api_delegate_subtask(job_id):
        """Delegate a subtask to another agent within a job context."""
        data = request.get_json() or {}
        capability = data.get("capability")
        prompt = data.get("prompt")
        timeout = data.get("timeout", 60)

        if not capability or not prompt:
            return jsonify({"success": False, "error": "capability and prompt required"}), 400

        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            result = dispatcher.delegate_subtask(job_id, capability, prompt, timeout)
            return jsonify(result)
        except Exception as e:
            logger.error(f"Error delegating subtask for job {job_id}: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # CROSS-STATION DISPATCH ANALYTICS
    # ============================================================================

    @bp.route("/api/dispatch/cross-station-analytics")
    @login_required
    def cross_station_analytics():
        """Cross-department dispatch analytics."""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT a.department, bj.status, COUNT(*) as cnt
                       FROM bridge_jobs bj
                       LEFT JOIN agents a ON a.name = bj.agent_name
                       WHERE bj.created_at > NOW() - INTERVAL '7 days'
                       GROUP BY a.department, bj.status
                       ORDER BY cnt DESC"""
                )
                cross_dispatches = cur.fetchall()
            return jsonify(success=True, cross_dispatches=cross_dispatches, borrowing=[])
        except Exception as e:
            logger.error(f"cross_station_analytics error: {e}")
            return jsonify(success=False, error="Internal server error"), 500

    @bp.route("/api/dispatch/reassignment-recommendations")
    @login_required
    def reassignment_recommendations():
        """Suggest agent reassignments based on cross-station dispatch patterns."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT home_station, dispatch_station, capability, module_source,
                           dispatch_count, success_rate
                    FROM cross_station_dispatch_summary
                    WHERE dispatch_count >= 5
                    ORDER BY dispatch_count DESC LIMIT 20
                """
                )
                frequent = cur.fetchall()

                recommendations = []
                for row in frequent:
                    cur.execute(
                        """
                        SELECT a.id, a.name, a.display_name, ask.skill_name,
                               ask.proficiency_level, a.department
                        FROM agents a
                        JOIN agent_skills ask ON ask.agent_id = a.id
                        WHERE ask.skill_name ILIKE %s
                          AND (a.department IS NULL OR a.department != %s)
                        ORDER BY ask.proficiency_level DESC LIMIT 3
                    """,
                        (f"%{row['capability']}%", row.get("home_station", "")),
                    )
                    candidates = cur.fetchall()
                    if candidates:
                        recommendations.append(
                            {
                                "pattern": dict(row),
                                "candidates": [dict(c) for c in candidates],
                            }
                        )
            return jsonify(success=True, recommendations=recommendations)
        except Exception as e:
            logger.error(f"reassignment_recommendations error: {e}")
            return jsonify(success=False, error="Internal server error"), 500
