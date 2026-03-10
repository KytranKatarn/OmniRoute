"""
Ops Center Routes — Summary, Active Jobs, Health, History

Provides lightweight API endpoints for the Unified Ops Center alert bar,
active-jobs tab, health grid, and unified history view.

Author: A.R.C.H.I.E. Platform
Created: 2026-03-10
"""

import logging
import os
from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import current_app, jsonify, request
from flask_login import login_required

logger = logging.getLogger("autonomy.ops")


def get_db():
    """Get database connection."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD"),
    )


def register_ops_routes(bp, admin_required):
    """Register Ops Center API routes on the autonomy blueprint."""

    # ------------------------------------------------------------------
    # 1. GET /api/ops-summary — lightweight counts for alert bar
    # ------------------------------------------------------------------
    @bp.route("/api/ops-summary")
    @login_required
    @admin_required
    def ops_summary():
        """Lightweight counts for the Ops Center alert bar."""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # --- Approval counts ---
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                    COUNT(*) FILTER (
                        WHERE status = 'pending'
                        AND expires_at < NOW()
                    ) AS expired,
                    EXTRACT(EPOCH FROM (
                        NOW() - MIN(created_at) FILTER (WHERE status = 'pending')
                    )) / 60 AS oldest_age_mins
                FROM autonomy_approval_queue
                """
            )
            approval_row = cur.fetchone()
            approvals = {
                "pending": approval_row["pending"] or 0,
                "expired": approval_row["expired"] or 0,
                "oldest_age_mins": (
                    round(float(approval_row["oldest_age_mins"]), 1) if approval_row["oldest_age_mins"] else None
                ),
            }

            # --- Bridge job counts ---
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'running') AS running,
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                    COUNT(*) FILTER (
                        WHERE status = 'running'
                        AND updated_at < NOW() - INTERVAL '15 minutes'
                    ) AS stalled
                FROM bridge_jobs
                WHERE status IN ('running', 'pending')
                   OR (status = 'running'
                       AND updated_at < NOW() - INTERVAL '15 minutes')
                """
            )
            bj = cur.fetchone()

            # Server loops
            try:
                from tools.consciousness.processing_routes import get_server_loops

                server_loops = get_server_loops()
            except Exception:
                server_loops = {}

            # Agent loop
            agent_loop = current_app.config.get("AGENT_LOOP")
            agent_loop_running = bool(agent_loop and agent_loop.is_running)
            agent_loop_count = 0
            if agent_loop:
                try:
                    st = agent_loop.get_status()
                    agent_loop_count = st.get("job_count", 0)
                except Exception:
                    pass

            # Scheduler
            scheduler = current_app.config.get("CONSCIOUSNESS_SCHEDULER")
            scheduler_running = bool(scheduler and scheduler.running)
            scheduler_count = 0
            if scheduler and scheduler.running:
                try:
                    scheduler_count = len(scheduler.get_jobs())
                except Exception:
                    pass

            active_jobs = {
                "bridge_running": bj["running"] or 0,
                "bridge_pending": bj["pending"] or 0,
                "bridge_stalled": bj["stalled"] or 0,
                "server_loops": server_loops,
                "agent_loop_running": agent_loop_running,
                "agent_loop_count": agent_loop_count,
                "scheduler_running": scheduler_running,
                "scheduler_count": scheduler_count,
            }

            # --- Errors in last hour ---
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM bridge_jobs
                WHERE status = 'failed'
                  AND completed_at >= NOW() - INTERVAL '1 hour'
                """
            )
            bridge_failed = cur.fetchone()["cnt"] or 0

            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM autonomy_loop_log
                WHERE status != 'success'
                  AND created_at >= NOW() - INTERVAL '1 hour'
                """
            )
            loop_errors = cur.fetchone()["cnt"] or 0

            errors_1h = {
                "bridge_failed": bridge_failed,
                "loop_errors": loop_errors,
            }

            # --- Build alerts ---
            alerts = []
            if approvals["expired"] > 0:
                alerts.append(
                    {
                        "severity": "high",
                        "message": f"{approvals['expired']} expired approval(s) in queue",
                    }
                )
            if (bj["stalled"] or 0) > 0:
                alerts.append(
                    {
                        "severity": "high",
                        "message": f"{bj['stalled']} stalled bridge job(s)",
                    }
                )
            if loop_errors > 0:
                alerts.append(
                    {
                        "severity": "medium",
                        "message": f"{loop_errors} loop error(s) in last hour",
                    }
                )
            if bridge_failed > 0:
                alerts.append(
                    {
                        "severity": "medium",
                        "message": f"{bridge_failed} failed bridge job(s) in last hour",
                    }
                )
            if approvals["pending"] > 5:
                alerts.append(
                    {
                        "severity": "low",
                        "message": f"{approvals['pending']} pending approvals",
                    }
                )
            if not agent_loop_running:
                alerts.append(
                    {
                        "severity": "medium",
                        "message": "Agent loop is not running",
                    }
                )
            if not scheduler_running:
                alerts.append(
                    {
                        "severity": "medium",
                        "message": "Scheduler is not running",
                    }
                )

            cur.close()
            conn.close()

            return jsonify(
                {
                    "approvals": approvals,
                    "active_jobs": active_jobs,
                    "errors_1h": errors_1h,
                    "alerts": alerts,
                }
            )

        except Exception as e:
            logger.exception("ops_summary error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # 2. GET /api/ops-active-jobs — detailed active jobs
    # ------------------------------------------------------------------
    @bp.route("/api/ops-active-jobs")
    @login_required
    @admin_required
    def ops_active_jobs():
        """Detailed active jobs for the Active Jobs tab."""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Bridge jobs: running, pending, or recently completed (5 min)
            cur.execute(
                """
                SELECT id, job_type, module_source, description,
                       total_steps, completed_steps, failed_steps,
                       status, agent_name, station_code,
                       created_at, updated_at, completed_at
                FROM bridge_jobs
                WHERE status IN ('running', 'pending')
                   OR (status IN ('completed', 'failed')
                       AND completed_at >= NOW() - INTERVAL '5 minutes')
                ORDER BY
                    CASE status
                        WHEN 'running' THEN 1
                        WHEN 'pending' THEN 2
                        ELSE 3
                    END,
                    created_at DESC
                LIMIT 50
                """
            )
            bridge_jobs = cur.fetchall()
            # Convert datetimes to ISO strings
            for job in bridge_jobs:
                for k in ("created_at", "updated_at", "completed_at"):
                    if job.get(k):
                        job[k] = job[k].isoformat()

            cur.close()
            conn.close()

            # Server loops
            try:
                from tools.consciousness.processing_routes import get_server_loops

                server_loops = get_server_loops()
            except Exception:
                server_loops = {}

            # Agent loop
            agent_loop = current_app.config.get("AGENT_LOOP")
            agent_loop_status = {"running": False, "jobs": [], "job_count": 0}
            if agent_loop:
                try:
                    agent_loop_status = agent_loop.get_status()
                except Exception:
                    pass

            # Scheduler jobs
            scheduler = current_app.config.get("CONSCIOUSNESS_SCHEDULER")
            scheduler_jobs = []
            if scheduler and scheduler.running:
                try:
                    for job in scheduler.get_jobs():
                        scheduler_jobs.append(
                            {
                                "id": job.id,
                                "name": job.name,
                                "next_run": (job.next_run_time.isoformat() if job.next_run_time else None),
                            }
                        )
                except Exception:
                    pass

            return jsonify(
                {
                    "bridge_jobs": bridge_jobs,
                    "server_loops": server_loops,
                    "agent_loop": agent_loop_status,
                    "scheduler_jobs": scheduler_jobs,
                }
            )

        except Exception as e:
            logger.exception("ops_active_jobs error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # 3. GET /api/ops-health — health grid
    # ------------------------------------------------------------------
    @bp.route("/api/ops-health")
    @login_required
    @admin_required
    def ops_health():
        """Health grid for the Health tab."""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Per-job health from autonomy_loop_log (24h)
            cur.execute(
                """
                SELECT
                    job_name,
                    MAX(created_at) AS last_run,
                    COUNT(*) FILTER (WHERE status = 'success') AS ok_24h,
                    COUNT(*) FILTER (WHERE status != 'success') AS err_24h
                FROM autonomy_loop_log
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY job_name
                ORDER BY job_name
                """
            )
            loop_health_rows = cur.fetchall()
            loop_health = []
            for row in loop_health_rows:
                loop_health.append(
                    {
                        "job_name": row["job_name"],
                        "last_run": (row["last_run"].isoformat() if row["last_run"] else None),
                        "ok_24h": row["ok_24h"] or 0,
                        "err_24h": row["err_24h"] or 0,
                    }
                )

            # Per-job-type health from bridge_jobs (24h)
            cur.execute(
                """
                SELECT
                    job_type,
                    MAX(completed_at) AS last_completed,
                    COUNT(*) FILTER (WHERE status = 'completed') AS ok_24h,
                    COUNT(*) FILTER (WHERE status = 'failed') AS err_24h
                FROM bridge_jobs
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY job_type
                ORDER BY job_type
                """
            )
            bridge_health_rows = cur.fetchall()
            bridge_health = []
            for row in bridge_health_rows:
                bridge_health.append(
                    {
                        "job_type": row["job_type"],
                        "last_completed": (row["last_completed"].isoformat() if row["last_completed"] else None),
                        "ok_24h": row["ok_24h"] or 0,
                        "err_24h": row["err_24h"] or 0,
                    }
                )

            cur.close()
            conn.close()

            # System components
            components = {}

            # Ollama
            try:
                import urllib.request

                req = urllib.request.Request("http://host.docker.internal:11434/api/tags")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    components["ollama"] = {
                        "status": "ok",
                        "http_code": resp.status,
                    }
            except Exception as e:
                components["ollama"] = {"status": "error", "error": str(e)}

            # Telegram
            telegram_token = bool(os.getenv("TELEGRAM_BOT_TOKEN"))
            telegram_authorized = 0
            if telegram_token:
                try:
                    conn2 = get_db()
                    cur2 = conn2.cursor()
                    cur2.execute("SELECT COUNT(*) FROM telegram_users WHERE is_authorized = true")
                    telegram_authorized = cur2.fetchone()[0]
                    cur2.close()
                    conn2.close()
                except Exception:
                    pass

            components["telegram"] = {
                "token_configured": telegram_token,
                "authorized_users": telegram_authorized,
            }

            return jsonify(
                {
                    "loop_health": loop_health,
                    "bridge_health": bridge_health,
                    "components": components,
                }
            )

        except Exception as e:
            logger.exception("ops_health error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # 4. GET /api/ops-history — unified history
    # ------------------------------------------------------------------
    @bp.route("/api/ops-history")
    @login_required
    @admin_required
    def ops_history():
        """Unified history merging autonomy_loop_log and bridge_jobs."""
        try:
            system = request.args.get("system", "all")
            hours = min(int(request.args.get("hours", 24)), 168)  # cap 7 days
            limit = min(int(request.args.get("limit", 100)), 500)

            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            parts = []
            params = []

            if system in ("all", "agent_loop"):
                parts.append(
                    """
                    SELECT
                        'agent_loop' AS system,
                        job_name AS name,
                        status,
                        created_at AS timestamp,
                        items_processed,
                        duration_ms,
                        error_message
                    FROM autonomy_loop_log
                    WHERE created_at >= NOW() - %s::interval
                    """
                )
                params.append(f"{hours} hours")

            if system in ("all", "bridge"):
                parts.append(
                    """
                    SELECT
                        'bridge' AS system,
                        job_type AS name,
                        status,
                        COALESCE(completed_at, created_at) AS timestamp,
                        completed_steps AS items_processed,
                        EXTRACT(EPOCH FROM (
                            COALESCE(completed_at, NOW()) - created_at
                        ))::int * 1000 AS duration_ms,
                        NULL AS error_message
                    FROM bridge_jobs
                    WHERE created_at >= NOW() - %s::interval
                    """
                )
                params.append(f"{hours} hours")

            if not parts:
                return jsonify({"rows": [], "total": 0})

            query = " UNION ALL ".join(parts) + " ORDER BY timestamp DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)
            rows = cur.fetchall()

            # Serialize datetimes
            for row in rows:
                if row.get("timestamp"):
                    row["timestamp"] = row["timestamp"].isoformat()

            # Total count (without limit)
            count_parts = []
            count_params = []
            if system in ("all", "agent_loop"):
                count_parts.append(
                    "SELECT COUNT(*) AS c FROM autonomy_loop_log " "WHERE created_at >= NOW() - %s::interval"
                )
                count_params.append(f"{hours} hours")
            if system in ("all", "bridge"):
                count_parts.append("SELECT COUNT(*) AS c FROM bridge_jobs " "WHERE created_at >= NOW() - %s::interval")
                count_params.append(f"{hours} hours")

            total_query = "SELECT SUM(c) AS total FROM (" + " UNION ALL ".join(count_parts) + ") sub"
            cur.execute(total_query, count_params)
            total = cur.fetchone()["total"] or 0

            cur.close()
            conn.close()

            return jsonify({"rows": rows, "total": int(total)})

        except Exception as e:
            logger.exception("ops_history error")
            return jsonify({"error": str(e)}), 500
