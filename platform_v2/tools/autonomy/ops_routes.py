"""
Ops Center Routes — Summary, Active Jobs, Health, History

Provides lightweight API endpoints for the Unified Ops Center alert bar,
active-jobs tab, health grid, and unified history view.

Author: A.R.C.H.I.E. Platform
Created: 2026-03-10
"""

import logging
import os
from database import _get_db_password
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
        password=_get_db_password(),
    )


def register_ops_routes(bp, admin_required):
    """Register Ops Center API routes on the autonomy blueprint."""

    # ------------------------------------------------------------------
    # 0a. GET /api/ops-server-loop/status — server loop states
    # ------------------------------------------------------------------
    @bp.route("/api/ops-server-loop/status", methods=["GET"])
    @login_required
    @admin_required
    def ops_server_loop_status():
        """Get server loop states."""
        try:
            from services.loop_service import get_server_loops

            loops = get_server_loops()
            return jsonify({"success": True, "loops": loops})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ------------------------------------------------------------------
    # 0b. POST /api/ops-server-loop/toggle — toggle a server loop
    # ------------------------------------------------------------------
    @bp.route("/api/ops-server-loop/toggle", methods=["POST"])
    @login_required
    @admin_required
    def ops_server_loop_toggle():
        """Toggle a server loop on/off."""
        try:
            from services.loop_service import get_server_loops, set_server_loop, VALID_LOOP_OPS

            data = request.get_json() or {}
            op = data.get("op", "")
            if op not in VALID_LOOP_OPS:
                return jsonify({"success": False, "error": f"Invalid op: {op}. Valid: {VALID_LOOP_OPS}"}), 400
            enabled = data.get("enabled", True)
            loops = set_server_loop(op, enabled)
            return jsonify({"success": True, "loops": loops, "toggled": op, "enabled": enabled})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

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
                from services.loop_service import get_server_loops

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
    # 1b. GET /api/repair-pipeline-status — repair pipeline overview
    # ------------------------------------------------------------------
    @bp.route("/api/repair-pipeline-status")
    @login_required
    @admin_required
    def repair_pipeline_status():
        """Return current repair pipeline status: proposals, work sessions, gate events."""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Count proposals by status (from code_health_audit source)
            proposal_counts = {}
            try:
                cur.execute(
                    """SELECT status, COUNT(*) AS count
                       FROM improvement_proposals
                       WHERE metadata->>'source' = 'code_health_audit'
                       GROUP BY status"""
                )
                proposal_counts = {r["status"]: r["count"] for r in cur.fetchall()}
            except Exception:
                # Table may not exist yet
                pass

            # Count recent work sessions (fix type, last 7 days)
            session_counts = {}
            try:
                cur.execute(
                    """SELECT status, COUNT(*) AS count
                       FROM dept_work_sessions
                       WHERE session_type = 'fix'
                         AND started_at > NOW() - INTERVAL '7 days'
                       GROUP BY status"""
                )
                session_counts = {r["status"]: r["count"] for r in cur.fetchall()}
            except Exception:
                pass

            # Latest C.R.E.E.D. gate events (last 7 days)
            gate_events = []
            try:
                cur.execute(
                    """SELECT event_type, outcome, COUNT(*) AS count
                       FROM governance_audit_log
                       WHERE event_category = 'creed_gate'
                         AND timestamp > NOW() - INTERVAL '7 days'
                       GROUP BY event_type, outcome"""
                )
                gate_events = [dict(r) for r in cur.fetchall()]
            except Exception:
                pass

            # Latest code audit summary (red/yellow/green counts)
            audit_summary = {"red": 0, "yellow": 0, "green": 0}
            try:
                cur.execute(
                    """SELECT DISTINCT ON (module_name)
                          module_name, issues_found, notes, status
                       FROM code_audit_log
                       ORDER BY module_name, audited_at DESC"""
                )
                red_codes = {"SQL_INJECTION", "HARDCODED_SECRET", "DIRECT_OLLAMA", "DIRECT_CLOUD"}
                yellow_codes = {"BARE_EXCEPT", "LARGE_FILE", "MISSING_INIT"}
                for row in cur.fetchall():
                    notes = row["notes"] or ""
                    issues = row["issues_found"] or 0
                    if issues == 0:
                        audit_summary["green"] += 1
                    elif any(code in notes for code in red_codes):
                        audit_summary["red"] += 1
                    elif any(code in notes for code in yellow_codes):
                        audit_summary["yellow"] += 1
                    else:
                        audit_summary["green"] += 1
            except Exception:
                pass

            cur.close()
            conn.close()

            return jsonify(
                {
                    "proposals": proposal_counts,
                    "sessions": session_counts,
                    "gate_events": gate_events,
                    "audit_summary": audit_summary,
                }
            )

        except Exception as e:
            logger.exception("repair_pipeline_status error")
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
                from services.loop_service import get_server_loops

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

            # Department agent counts (Starbase integration)
            cur.execute(
                """
                SELECT department,
                    COUNT(*) FILTER (WHERE shift_state = 'active') AS active,
                    COUNT(*) FILTER (WHERE shift_state = 'barracked') AS barracked,
                    COUNT(*) FILTER (WHERE shift_state IN ('cooldown', 'winding_down')) AS cooldown,
                    COUNT(*) AS total
                FROM agents
                WHERE status = 'active' AND department IS NOT NULL
                GROUP BY department
                ORDER BY department
                """
            )
            dept_agents = {}
            for row in cur.fetchall():
                dept_agents[row["department"]] = {
                    "active": row["active"],
                    "barracked": row["barracked"],
                    "cooldown": row["cooldown"],
                    "total": row["total"],
                }

            # Recent bridge dispatch stats per department (24h)
            cur.execute(
                """
                SELECT station_code AS dept,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'completed') AS ok,
                    COUNT(*) FILTER (WHERE status = 'failed') AS err
                FROM bridge_jobs
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                  AND station_code IS NOT NULL
                GROUP BY station_code
                """
            )
            dept_dispatches = {}
            for row in cur.fetchall():
                dept_dispatches[row["dept"]] = {
                    "total": row["total"],
                    "ok": row["ok"],
                    "err": row["err"],
                }

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
                    "dept_agents": dept_agents,
                    "dept_dispatches": dept_dispatches,
                }
            )

        except Exception as e:
            logger.exception("ops_health error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # 3b. GET /api/ops-jobs — list all jobs from JobService
    # ------------------------------------------------------------------
    @bp.route("/api/ops-jobs")
    @login_required
    @admin_required
    def api_ops_jobs():
        """List all registered jobs from JobService."""
        try:
            svc = current_app.config.get("JOB_SERVICE")
            if not svc:
                return jsonify({"error": "JobService not initialized"}), 503
            jobs = svc.list_jobs()
            jobs.sort(key=lambda j: (j.get("department", ""), j.get("name", "")))
            return jsonify({"jobs": jobs, "total": len(jobs)})
        except Exception as e:
            logger.exception("api_ops_jobs error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # 3c. GET /api/ops-jobs/<name> — single job status
    # ------------------------------------------------------------------
    @bp.route("/api/ops-jobs/<name>")
    @login_required
    @admin_required
    def api_ops_job_status(name):
        """Get detailed status for a single job."""
        try:
            svc = current_app.config.get("JOB_SERVICE")
            if not svc:
                return jsonify({"error": "JobService not initialized"}), 503
            status = svc.get_job_status(name)
            if not status:
                return jsonify({"error": f"Job '{name}' not found"}), 404
            return jsonify(status)
        except Exception as e:
            logger.exception("api_ops_job_status error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # 3d. POST /api/ops-jobs/<name>/disable — disable a job
    # ------------------------------------------------------------------
    @bp.route("/api/ops-jobs/<name>/disable", methods=["POST"])
    @login_required
    @admin_required
    def api_ops_job_disable(name):
        """Disable a job by name."""
        try:
            svc = current_app.config.get("JOB_SERVICE")
            if not svc:
                return jsonify({"error": "JobService not initialized"}), 503
            ok = svc.disable_job(name)
            if not ok:
                return jsonify({"error": f"Job '{name}' not found"}), 404
            return jsonify({"success": True, "job": name, "enabled": False})
        except Exception as e:
            logger.exception("api_ops_job_disable error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # 3e. POST /api/ops-jobs/<name>/enable — enable a job
    # ------------------------------------------------------------------
    @bp.route("/api/ops-jobs/<name>/enable", methods=["POST"])
    @login_required
    @admin_required
    def api_ops_job_enable(name):
        """Enable a job by name."""
        try:
            svc = current_app.config.get("JOB_SERVICE")
            if not svc:
                return jsonify({"error": "JobService not initialized"}), 503
            ok = svc.enable_job(name)
            if not ok:
                return jsonify({"error": f"Job '{name}' not found"}), 404
            return jsonify({"success": True, "job": name, "enabled": True})
        except Exception as e:
            logger.exception("api_ops_job_enable error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # 3f. POST /api/ops-jobs/<name>/reschedule — change job interval
    # ------------------------------------------------------------------
    @bp.route("/api/ops-jobs/<name>/reschedule", methods=["POST"])
    @login_required
    @admin_required
    def api_ops_job_reschedule(name):
        """Reschedule a job with a new interval."""
        try:
            data = request.get_json() or {}
            interval_hours = data.get("interval_hours")
            if interval_hours is None:
                return jsonify({"error": "interval_hours required"}), 400
            interval_hours = float(interval_hours)
            if interval_hours <= 0:
                return jsonify({"error": "interval_hours must be positive"}), 400

            svc = current_app.config.get("JOB_SERVICE")
            if not svc:
                return jsonify({"error": "JobService not initialized"}), 503
            ok = svc.reschedule_job(name, interval_hours)
            if not ok:
                return jsonify({"error": f"Job '{name}' not found"}), 404
            return jsonify({"success": True, "job": name, "interval_hours": interval_hours})
        except Exception as e:
            logger.exception("api_ops_job_reschedule error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # 3g. POST /api/ops-jobs/<name>/run — manually trigger a job
    # ------------------------------------------------------------------
    @bp.route("/api/ops-jobs/<name>/run", methods=["POST"])
    @login_required
    @admin_required
    def api_ops_job_run(name):
        """Manually trigger a job by name."""
        try:
            svc = current_app.config.get("JOB_SERVICE")
            if not svc:
                return jsonify({"error": "JobService not initialized"}), 503
            result = svc.run_job(name)
            return jsonify(result)
        except Exception as e:
            logger.exception("api_ops_job_run error")
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
