"""Fleet dispatch activity routes and the public registration entry point.

Job/detail/resume/delegate and cross-station routes moved unchanged to
fleet_dispatch_job_routes.py. register_dispatch_routes still registers both
modules, preserving all nine URLs, methods and authentication guards.
"""

import logging
from datetime import datetime, timezone
from flask import jsonify, request
from flask_login import login_required
from database import get_db_cursor

from .fleet_helpers import LEGACY_STATION_COLORS, DEPARTMENT_TO_STATION

__all__ = [
    "logging",
    "datetime",
    "timezone",
    "jsonify",
    "request",
    "login_required",
    "get_db_cursor",
    "LEGACY_STATION_COLORS",
    "DEPARTMENT_TO_STATION",
    "logger",
    "register_dispatch_routes",
]

logger = logging.getLogger(__name__)


def register_dispatch_routes(bp, admin_required):
    """Register dispatch-related routes on the fleet blueprint."""

    # ============================================================================
    # DISPATCH ACTIVITY API (Project #91 — Phase 6)
    # ============================================================================

    @bp.route("/api/bridge/dispatch-status")
    @login_required
    def get_dispatch_status():
        """Get current BridgeDispatcher status: active agents, assignments, queue depth"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Active agents with their department (station_assignments DROPPED)
                cur.execute(
                    """
                    SELECT a.id, a.name, a.first_name, a.last_name, a.title, a.model,
                           a.status, a.avatar_url,
                           a.department
                    FROM agents a
                    WHERE a.status = 'active'
                    ORDER BY a.department, a.name
                """
                )
                agents = cur.fetchall()

                # Recent dispatch activity (rolling 24h + 1h)
                cur.execute(
                    """
                    SELECT COUNT(*) as total_dispatches,
                           COUNT(CASE WHEN success = TRUE THEN 1 END) as successful,
                           COUNT(CASE WHEN success = FALSE THEN 1 END) as failed,
                           COALESCE(AVG(duration_ms), 0) as avg_duration_ms
                    FROM task_execution_log
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                """
                )
                dispatch_stats_24h = cur.fetchone()

                cur.execute(
                    """
                    SELECT COUNT(*) as total_dispatches,
                           COUNT(CASE WHEN success = TRUE THEN 1 END) as successful,
                           COUNT(CASE WHEN success = FALSE THEN 1 END) as failed
                    FROM task_execution_log
                    WHERE created_at > NOW() - INTERVAL '1 hour'
                """
                )
                dispatch_stats_1h = cur.fetchone()

                # Active tasks (in-progress right now — last 2 minutes)
                cur.execute(
                    """
                    SELECT tel.id, a.name as agent_name, tel.module_source,
                           tel.task_type, tel.model_used, tel.created_at
                    FROM task_execution_log tel
                    LEFT JOIN agents a ON a.id = tel.agent_id
                    WHERE tel.created_at > NOW() - INTERVAL '2 minutes'
                          AND tel.success IS NULL
                    ORDER BY tel.created_at DESC
                    LIMIT 10
                """
                )
                active_tasks = cur.fetchall()

                # Per-station dispatch counts (last 24h) — bridge_stations deprecated, color from Python map
                cur.execute(
                    """
                    SELECT COALESCE(tel.station_code, 'UNASSIGNED') as station_code,
                           COUNT(*) as dispatch_count,
                           COALESCE(AVG(tel.duration_ms), 0) as avg_ms
                    FROM task_execution_log tel
                    WHERE tel.created_at > NOW() - INTERVAL '24 hours'
                    GROUP BY tel.station_code
                    ORDER BY dispatch_count DESC
                """
                )
                station_activity = cur.fetchall()

                return jsonify(
                    {
                        "success": True,
                        "agents": [
                            {
                                "id": a["id"],
                                "name": a["name"],
                                "first_name": a.get("first_name"),
                                "last_name": a.get("last_name"),
                                "title": a["title"],
                                "model": a["model"],
                                "status": a["status"],
                                "avatar_url": a.get("avatar_url"),
                                "station_code": DEPARTMENT_TO_STATION.get(
                                    a.get("department", ""), a.get("department", "")
                                ),
                                "station_name": a.get("department"),
                                "station_color": LEGACY_STATION_COLORS.get(
                                    DEPARTMENT_TO_STATION.get(a.get("department", ""), ""), "#666"
                                ),
                                "department": a.get("department"),
                                "assignment_type": "primary",
                            }
                            for a in agents
                        ],
                        "dispatch_stats": {
                            "total_1h": dispatch_stats_1h["total_dispatches"],
                            "total_24h": dispatch_stats_24h["total_dispatches"],
                            "successful_1h": dispatch_stats_1h["successful"],
                            "successful_24h": dispatch_stats_24h["successful"],
                            "failed_1h": dispatch_stats_1h["failed"],
                            "failed_24h": dispatch_stats_24h["failed"],
                            "avg_duration_ms": round(float(dispatch_stats_24h["avg_duration_ms"]), 1),
                        },
                        "active_tasks": [
                            {
                                "id": t["id"],
                                "agent_name": t["agent_name"],
                                "module": t["module_source"],
                                "task_type": t["task_type"],
                                "model": t["model_used"],
                                "started": t["created_at"].isoformat() if t["created_at"] else None,
                            }
                            for t in active_tasks
                        ],
                        "station_activity": [
                            {
                                "station_code": s["station_code"],
                                "station_name": s["station_code"].title() if s["station_code"] else "Unassigned",
                                "color": LEGACY_STATION_COLORS.get(s["station_code"], "#666"),
                                "dispatch_count": s["dispatch_count"],
                                "avg_ms": round(float(s["avg_ms"]), 1),
                            }
                            for s in station_activity
                        ],
                    }
                )

        except Exception as e:
            logger.error(f"Error getting dispatch status: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/dispatch-history")
    @login_required
    def get_dispatch_history():
        """Get recent task execution history for the Bridge dispatch panel"""
        try:
            limit = request.args.get("limit", 50, type=int)
            limit = min(limit, 200)

            with get_db_cursor(commit=False) as (conn, cur):

                cur.execute(
                    """
                    SELECT tel.id,
                           COALESCE(
                               NULLIF(CONCAT_WS(' ', a.first_name, a.last_name), ''),
                               a.name,
                               tel.agent_name
                           ) as agent_display_name,
                           COALESCE(a.name, tel.agent_name) as agent_callsign,
                           a.avatar_url,
                           tel.module_source, tel.task_type, tel.capability,
                           tel.model_used, tel.duration_ms, tel.success,
                           tel.error_message, tel.created_at,
                           tel.station_code
                    FROM task_execution_log tel
                    LEFT JOIN agents a ON a.id = tel.agent_id
                    WHERE tel.created_at > NOW() - INTERVAL '24 hours'
                    ORDER BY tel.created_at DESC
                    LIMIT %s
                """,
                    (limit,),
                )
                history = cur.fetchall()

                return jsonify(
                    {
                        "success": True,
                        "history": [
                            {
                                "id": h["id"],
                                "agent_name": h["agent_display_name"] or h.get("agent_callsign") or "Unknown",
                                "avatar_url": h.get("avatar_url"),
                                "module": h["module_source"],
                                "task_type": h["task_type"],
                                "capability": h.get("capability"),
                                "model": h["model_used"],
                                "duration_ms": h["duration_ms"],
                                "success": h["success"],
                                "error": h.get("error_message"),
                                "timestamp": h["created_at"].isoformat() if h["created_at"] else None,
                                "station_code": h.get("station_code"),
                                "station_color": LEGACY_STATION_COLORS.get(h.get("station_code", ""), "#666"),
                            }
                            for h in history
                        ],
                        "total": len(history),
                    }
                )

        except Exception as e:
            logger.error(f"Error getting dispatch history: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # DISPATCH OVERVIEW — Merged stats + history + jobs in one call
    # ============================================================================

    @bp.route("/api/bridge/dispatch-overview")
    @login_required
    def get_dispatch_overview():
        """Single endpoint for the Dispatch tab: stats, history, active jobs, station bars."""
        try:
            limit = request.args.get("limit", 20, type=int)
            limit = min(limit, 200)
            jobs_limit = request.args.get("jobs_limit", 10, type=int)

            with get_db_cursor(commit=False) as (conn, cur):

                # 1. Dispatch stats (24h + 1h)
                cur.execute(
                    """
                    SELECT COUNT(*) as total_dispatches,
                           COUNT(CASE WHEN success = TRUE THEN 1 END) as successful,
                           COUNT(CASE WHEN success = FALSE THEN 1 END) as failed,
                           COALESCE(AVG(duration_ms), 0) as avg_duration_ms
                    FROM task_execution_log
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                """
                )
                stats_24h = cur.fetchone()

                cur.execute(
                    """
                    SELECT COUNT(*) as total_dispatches,
                           COUNT(CASE WHEN success = TRUE THEN 1 END) as successful,
                           COUNT(CASE WHEN success = FALSE THEN 1 END) as failed
                    FROM task_execution_log
                    WHERE created_at > NOW() - INTERVAL '1 hour'
                """
                )
                stats_1h = cur.fetchone()

                # 2. Recent dispatch history
                cur.execute(
                    """
                    SELECT tel.id,
                           COALESCE(
                               NULLIF(CONCAT_WS(' ', a.first_name, a.last_name), ''),
                               a.name,
                               tel.agent_name
                           ) as agent_display_name,
                           COALESCE(a.name, tel.agent_name) as agent_callsign,
                           a.avatar_url,
                           tel.module_source, tel.task_type, tel.capability,
                           tel.model_used, tel.duration_ms, tel.success,
                           tel.error_message, tel.created_at,
                           tel.station_code
                    FROM task_execution_log tel
                    LEFT JOIN agents a ON a.id = tel.agent_id
                    WHERE tel.created_at > NOW() - INTERVAL '24 hours'
                    ORDER BY tel.created_at DESC
                    LIMIT %s
                """,
                    (limit,),
                )
                history = cur.fetchall()

                # 3. Per-station activity — bridge_stations deprecated, color from Python map
                cur.execute(
                    """
                    SELECT COALESCE(tel.station_code, 'UNASSIGNED') as station_code,
                           COUNT(*) as dispatch_count,
                           COALESCE(AVG(tel.duration_ms), 0) as avg_ms
                    FROM task_execution_log tel
                    WHERE tel.created_at > NOW() - INTERVAL '24 hours'
                    GROUP BY tel.station_code
                    ORDER BY dispatch_count DESC
                """
                )
                station_activity = cur.fetchall()

                # 4. Active bridge jobs
                cur.execute(
                    """
                    SELECT bj.id, bj.job_type, bj.status,
                           bj.completed_steps, bj.total_steps,
                           bj.created_at, bj.updated_at, bj.completed_at,
                           bj.description, bj.agent_name,
                           COALESCE(
                               NULLIF(CONCAT_WS(' ', a.first_name, a.last_name), ''),
                               a.name,
                               bj.agent_name
                           ) as agent_display_name,
                           a.avatar_url,
                           bj.station_code, bj.module_source
                    FROM bridge_jobs bj
                    LEFT JOIN agents a ON a.name = bj.agent_name
                    WHERE bj.status IN ('pending', 'running')
                       OR (bj.status IN ('completed', 'failed')
                           AND bj.completed_at > NOW() - INTERVAL '2 minutes')
                    ORDER BY bj.created_at DESC
                    LIMIT %s
                """,
                    (jobs_limit,),
                )
                jobs = cur.fetchall()

                return jsonify(
                    {
                        "success": True,
                        "dispatch_stats": {
                            "total_1h": stats_1h["total_dispatches"],
                            "total_24h": stats_24h["total_dispatches"],
                            "successful_1h": stats_1h["successful"],
                            "successful_24h": stats_24h["successful"],
                            "failed_1h": stats_1h["failed"],
                            "failed_24h": stats_24h["failed"],
                            "avg_duration_ms": round(float(stats_24h["avg_duration_ms"]), 1),
                        },
                        "history": [
                            {
                                "id": h["id"],
                                "agent_name": h["agent_display_name"] or h.get("agent_callsign") or "Unknown",
                                "avatar_url": h.get("avatar_url"),
                                "module": h["module_source"],
                                "task_type": h["task_type"],
                                "capability": h.get("capability"),
                                "model": h["model_used"],
                                "duration_ms": h["duration_ms"],
                                "success": h["success"],
                                "error": h.get("error_message"),
                                "timestamp": h["created_at"].isoformat() if h["created_at"] else None,
                                "station_code": h.get("station_code"),
                                "station_color": LEGACY_STATION_COLORS.get(h.get("station_code", ""), "#666"),
                            }
                            for h in history
                        ],
                        "station_activity": [
                            {
                                "station_code": s["station_code"],
                                "station_name": s["station_code"].title() if s["station_code"] else "Unassigned",
                                "color": LEGACY_STATION_COLORS.get(s["station_code"], "#666"),
                                "dispatch_count": s["dispatch_count"],
                                "avg_ms": round(float(s["avg_ms"]), 1),
                            }
                            for s in station_activity
                        ],
                        "jobs": [
                            {
                                "id": j["id"],
                                "job_type": j["job_type"],
                                "status": j["status"],
                                "completed_steps": j["completed_steps"],
                                "total_steps": j["total_steps"],
                                "agent_name": j.get("agent_display_name") or j.get("agent_name"),
                                "avatar_url": j.get("avatar_url"),
                                "station_code": j.get("station_code"),
                                "module": j.get("module_source"),
                                "description": j.get("description"),
                                "created_at": j["created_at"].isoformat() if j["created_at"] else None,
                                "completed_at": j["completed_at"].isoformat() if j.get("completed_at") else None,
                            }
                            for j in jobs
                        ],
                    }
                )

        except Exception as e:
            logger.error(f"Error getting dispatch overview: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # BRIDGE JOBS — Workload tracking for multi-step operations
    # ============================================================================

    from .fleet_dispatch_job_routes import register_dispatch_job_routes

    register_dispatch_job_routes(bp, admin_required)
