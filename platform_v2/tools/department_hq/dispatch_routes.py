"""
Dispatch & Orchestration Routes — Department HQ
Centralizes AI Bridge dispatch monitoring, Ollama engine status,
agent workload, and autonomy loop job visibility.

ADR-045 pattern: register_dispatch_routes(bp, admin_required_decorator)
"""

import logging
import os

import requests as _req
from flask import current_app, jsonify, request
from flask_login import login_required

from database import get_db_cursor

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://192.168.1.200:11434")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = f"http://{OLLAMA_URL}"


def register_dispatch_routes(bp, admin_required_decorator):
    """Register dispatch & orchestration monitoring endpoints."""

    @bp.route("/api/dispatch/overview", methods=["GET"])
    @admin_required_decorator
    def dispatch_overview():
        """Aggregate endpoint: Ollama + active jobs + metrics + workload + loop jobs."""
        result = {
            "ollama": {},
            "active_jobs": [],
            "dispatch_metrics": {},
            "workload_grid": [],
            "loop_jobs": [],
        }

        # ── Ollama Engine Status ──
        try:
            ps = _req.get(f"{OLLAMA_URL}/api/ps", timeout=3).json()
            tags = _req.get(f"{OLLAMA_URL}/api/tags", timeout=3).json()
            models = ps.get("models", [])
            result["ollama"] = {
                "loaded_models": [
                    {
                        "name": m.get("name", ""),
                        "size": m.get("size", 0),
                        "size_vram": m.get("size_vram", 0),
                    }
                    for m in models
                ],
                "available_count": len(tags.get("models", [])),
                "parallel_slots": len(models),
                "total_vram_used_gb": round(sum(m.get("size_vram", 0) for m in models) / 1e9, 2),
                "total_ram_used_gb": round(sum(m.get("size", 0) for m in models) / 1e9, 2),
            }
        except Exception as e:
            logger.warning("[Dispatch] Ollama status failed: %s", e)
            result["ollama"] = {
                "loaded_models": [],
                "available_count": 0,
                "parallel_slots": 0,
                "total_vram_used_gb": 0,
                "total_ram_used_gb": 0,
                "error": str(e),
            }

        try:
            with get_db_cursor() as (conn, cur):
                # ── Active Bridge Jobs ──
                cur.execute(
                    """SELECT id, job_type, description, agent_name, station_code,
                              status, completed_steps, total_steps, failed_steps,
                              created_at, updated_at
                       FROM bridge_jobs
                       WHERE status IN ('running', 'pending')
                          OR (status = 'completed'
                              AND completed_at > NOW() - INTERVAL '5 minutes')
                       ORDER BY
                           CASE status
                               WHEN 'running' THEN 0
                               WHEN 'pending' THEN 1
                               ELSE 2
                           END,
                           created_at DESC
                       LIMIT 30"""
                )
                for row in cur.fetchall():
                    r = dict(row)
                    total = r.get("total_steps") or 0
                    done = r.get("completed_steps") or 0
                    result["active_jobs"].append(
                        {
                            "id": r["id"],
                            "job_type": r.get("job_type", ""),
                            "description": r.get("description", ""),
                            "agent_name": r.get("agent_name", ""),
                            "station_code": r.get("station_code", ""),
                            "status": r.get("status", ""),
                            "progress_pct": round(done / total * 100) if total > 0 else 0,
                            "completed_steps": done,
                            "total_steps": total,
                            "failed_steps": r.get("failed_steps", 0),
                            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                        }
                    )

                # ── Dispatch Metrics (24h) ──
                cur.execute(
                    """SELECT
                           COUNT(*) AS total_24h,
                           COUNT(*) FILTER (WHERE success = TRUE) AS success_24h,
                           COUNT(*) FILTER (WHERE success = FALSE) AS failed_24h,
                           COALESCE(ROUND(AVG(duration_ms)::numeric, 1), 0)
                               AS avg_duration_ms,
                           COUNT(*) FILTER (
                               WHERE created_at > NOW() - INTERVAL '1 hour'
                           ) AS total_1h,
                           COUNT(*) FILTER (
                               WHERE success = TRUE
                               AND created_at > NOW() - INTERVAL '1 hour'
                           ) AS success_1h,
                           COUNT(*) FILTER (
                               WHERE success = FALSE
                               AND created_at > NOW() - INTERVAL '1 hour'
                           ) AS failed_1h
                       FROM task_execution_log
                       WHERE created_at > NOW() - INTERVAL '24 hours'"""
                )
                row = cur.fetchone()
                if row:
                    r = dict(row)
                    result["dispatch_metrics"] = {
                        "total_24h": int(r.get("total_24h") or 0),
                        "success_24h": int(r.get("success_24h") or 0),
                        "failed_24h": int(r.get("failed_24h") or 0),
                        "avg_duration_ms": float(r.get("avg_duration_ms") or 0),
                        "total_1h": int(r.get("total_1h") or 0),
                        "success_1h": int(r.get("success_1h") or 0),
                        "failed_1h": int(r.get("failed_1h") or 0),
                    }

                # ── Agent Workload by Department ──
                cur.execute(
                    """SELECT department,
                              COALESCE(MAX(floor), 'UNKNOWN') AS floor,
                              COUNT(*) FILTER (
                                  WHERE shift_state = 'active'
                              ) AS active,
                              COUNT(*) FILTER (
                                  WHERE shift_state = 'deployed'
                              ) AS deployed,
                              COUNT(*) FILTER (
                                  WHERE shift_state = 'barracked'
                              ) AS barracked,
                              COUNT(*) FILTER (
                                  WHERE shift_state IN (
                                      'cooldown', 'winding_down'
                                  )
                              ) AS cooldown,
                              COUNT(*) AS total
                       FROM agents
                       WHERE status = 'active' AND department IS NOT NULL
                       GROUP BY department
                       ORDER BY department"""
                )
                for row in cur.fetchall():
                    r = dict(row)
                    result["workload_grid"].append(
                        {
                            "department": r["department"],
                            "floor": r["floor"],
                            "active": int(r.get("active") or 0),
                            "deployed": int(r.get("deployed") or 0),
                            "barracked": int(r.get("barracked") or 0),
                            "cooldown": int(r.get("cooldown") or 0),
                            "total": int(r.get("total") or 0),
                        }
                    )

                # ── Loop Jobs Health ──
                # Get 24h ok/err counts per job from autonomy_loop_log
                cur.execute(
                    """SELECT job_name,
                              COUNT(*) FILTER (WHERE status = 'success')
                                  AS ok_24h,
                              COUNT(*) FILTER (WHERE status != 'success')
                                  AS err_24h,
                              MAX(created_at) AS last_run
                       FROM autonomy_loop_log
                       WHERE created_at >= NOW() - INTERVAL '24 hours'
                       GROUP BY job_name"""
                )
                health_map = {r["job_name"]: dict(r) for r in cur.fetchall()}

        except Exception as e:
            logger.error("[Dispatch] DB queries failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

        # ── Scheduler next_run times ──
        next_run_map = {}
        try:
            scheduler = current_app.config.get("CONSCIOUSNESS_SCHEDULER")
            if scheduler and scheduler.running:
                for sj in scheduler.get_jobs():
                    nrt = sj.next_run_time
                    next_run_map[sj.id] = nrt.isoformat() if nrt else None
        except Exception:
            pass

        # ── Merge loop jobs from JobService ──
        try:
            svc = current_app.config.get("JOB_SERVICE")
            if svc:
                raw_jobs = svc.list_jobs()
                for j in raw_jobs:
                    name = j.get("name", "")
                    h = health_map.get(name, {})
                    result["loop_jobs"].append(
                        {
                            "name": name,
                            "department": j.get("department", ""),
                            "enabled": j.get("enabled", True),
                            "interval_hours": j.get("interval_hours"),
                            "last_run": h["last_run"].isoformat() if h.get("last_run") else j.get("last_run"),
                            "next_run": next_run_map.get(name),
                            "ok_24h": int(h.get("ok_24h") or 0),
                            "err_24h": int(h.get("err_24h") or 0),
                        }
                    )
        except Exception as e:
            logger.warning("[Dispatch] Loop jobs failed: %s", e)

        return jsonify({"success": True, **result})

    # ── Job Control Actions ──

    @bp.route("/api/dispatch/jobs/<name>/toggle", methods=["POST"])
    @admin_required_decorator
    def dispatch_job_toggle(name):
        """Enable or disable a loop job."""
        data = request.get_json() or {}
        enabled = data.get("enabled", True)
        try:
            svc = current_app.config.get("JOB_SERVICE")
            if not svc:
                return jsonify({"success": False, "error": "Job service unavailable"}), 503
            if enabled:
                svc.enable_job(name)
            else:
                svc.disable_job(name)
            return jsonify({"success": True, "name": name, "enabled": enabled})
        except Exception as e:
            logger.error("[Dispatch] Job toggle failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/dispatch/jobs/<name>/run", methods=["POST"])
    @admin_required_decorator
    def dispatch_job_run(name):
        """Manually trigger a loop job."""
        try:
            svc = current_app.config.get("JOB_SERVICE")
            if not svc:
                return jsonify({"success": False, "error": "Job service unavailable"}), 503
            svc.run_job(name)
            return jsonify({"success": True, "name": name, "message": "Job triggered"})
        except Exception as e:
            logger.error("[Dispatch] Job run failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    # ── Server Loop Toggles ──

    @bp.route("/api/dispatch/loops", methods=["GET"])
    @admin_required_decorator
    def dispatch_loops_status():
        """Get server loop statuses (embedding, analysis, translate)."""
        try:
            loop_svc = current_app.config.get("LOOP_SERVICE")
            if loop_svc:
                states = loop_svc.get_all_states()
            else:
                states = {}
            return jsonify({"success": True, "loops": states})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/dispatch/loops/toggle", methods=["POST"])
    @admin_required_decorator
    def dispatch_loop_toggle():
        """Toggle a server loop on/off."""
        data = request.get_json() or {}
        loop_name = data.get("name", "")
        try:
            loop_svc = current_app.config.get("LOOP_SERVICE")
            if not loop_svc:
                return jsonify({"success": False, "error": "Loop service unavailable"}), 503
            new_state = loop_svc.toggle(loop_name)
            return jsonify({"success": True, "name": loop_name, "running": new_state})
        except Exception as e:
            logger.error("[Dispatch] Loop toggle failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    # ── Approvals ──

    @bp.route("/api/dispatch/approvals", methods=["GET"])
    @admin_required_decorator
    def dispatch_approvals():
        """Fetch approval queue items."""
        status = request.args.get("status", "pending")
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, action_type, reason, requested_by,
                              status, tier, created_at
                       FROM autonomy_approval_queue
                       WHERE status = %s
                       ORDER BY created_at DESC LIMIT 50""",
                    (status,),
                )
                items = []
                for row in cur.fetchall():
                    r = dict(row)
                    items.append(
                        {
                            "id": r["id"],
                            "type": r.get("action_type", ""),
                            "description": r.get("reason", ""),
                            "requested_by": r.get("requested_by", ""),
                            "status": r.get("status", ""),
                            "tier": r.get("tier", 2),
                            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                        }
                    )
            return jsonify({"success": True, "approvals": items})
        except Exception as e:
            logger.error("[Dispatch] Approvals failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/dispatch/approvals/<int:approval_id>/<action>", methods=["POST"])
    @admin_required_decorator
    def dispatch_approval_action(approval_id, action):
        """Approve or reject an approval item."""
        if action not in ("approve", "reject"):
            return jsonify({"success": False, "error": "Invalid action"}), 400
        new_status = "approved" if action == "approve" else "rejected"
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE autonomy_approval_queue
                       SET status = %s, approved_at = NOW()
                       WHERE id = %s AND status = 'pending'""",
                    (new_status, approval_id),
                )
                if cur.rowcount == 0:
                    return jsonify({"success": False, "error": "Not found or already resolved"})
            return jsonify({"success": True, "id": approval_id, "status": new_status})
        except Exception as e:
            logger.error("[Dispatch] Approval action failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    # ── History ──

    @bp.route("/api/dispatch/history", methods=["GET"])
    @admin_required_decorator
    def dispatch_history():
        """Unified dispatch + loop history."""
        hours = min(int(request.args.get("hours", 24)), 168)
        limit = min(int(request.args.get("limit", 50)), 200)
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """(SELECT 'dispatch' AS source, id, agent_name AS actor,
                              task_type AS action, module_source AS module,
                              CASE WHEN success THEN 'success' ELSE 'failed' END AS status,
                              duration_ms, created_at
                        FROM task_execution_log
                        WHERE created_at > NOW() - INTERVAL '%s hours'
                        ORDER BY created_at DESC LIMIT %s)
                       UNION ALL
                       (SELECT 'loop' AS source, id, job_name AS actor,
                               status AS action, '' AS module,
                               status, duration_ms, created_at
                        FROM autonomy_loop_log
                        WHERE created_at > NOW() - INTERVAL '%s hours'
                        ORDER BY created_at DESC LIMIT %s)
                       ORDER BY created_at DESC LIMIT %s""",
                    (hours, limit, hours, limit, limit),
                )
                entries = []
                for row in cur.fetchall():
                    r = dict(row)
                    entries.append(
                        {
                            "source": r["source"],
                            "actor": r.get("actor", ""),
                            "action": r.get("action", ""),
                            "module": r.get("module", ""),
                            "status": r.get("status", ""),
                            "duration_ms": r.get("duration_ms"),
                            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                        }
                    )
            return jsonify({"success": True, "history": entries, "hours": hours})
        except Exception as e:
            logger.error("[Dispatch] History failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    # ── System Components ──

    @bp.route("/api/dispatch/components", methods=["GET"])
    @admin_required_decorator
    def dispatch_components():
        """System health: Ollama, Telegram, scheduler, per-dept agent counts."""
        components = []
        # Ollama
        try:
            r = _req.get(f"{OLLAMA_URL}/api/tags", timeout=3)
            components.append({"name": "Ollama", "ok": r.status_code == 200, "detail": "Connected"})
        except Exception:
            components.append({"name": "Ollama", "ok": False, "detail": "Unreachable"})

        # Scheduler
        try:
            sched = current_app.config.get("CONSCIOUSNESS_SCHEDULER")
            components.append(
                {
                    "name": "Scheduler",
                    "ok": bool(sched and sched.running),
                    "detail": f"{len(sched.get_jobs())} jobs" if sched and sched.running else "Stopped",
                }
            )
        except Exception:
            components.append({"name": "Scheduler", "ok": False, "detail": "Error"})

        # Agent Loop
        try:
            agent_loop = current_app.config.get("AGENT_LOOP")
            components.append(
                {
                    "name": "Agent Loop",
                    "ok": bool(agent_loop and getattr(agent_loop, "running", False)),
                    "detail": "Running" if agent_loop and getattr(agent_loop, "running", False) else "Stopped",
                }
            )
        except Exception:
            components.append({"name": "Agent Loop", "ok": False, "detail": "Error"})

        # Telegram
        try:
            has_token = bool(os.getenv("TELEGRAM_BOT_TOKEN"))
            components.append(
                {
                    "name": "Telegram Bot",
                    "ok": has_token,
                    "detail": "Token set" if has_token else "No token",
                }
            )
        except Exception:
            components.append({"name": "Telegram Bot", "ok": False, "detail": "Error"})

        # Per-department agent counts
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT department, COUNT(*) AS cnt
                       FROM agents
                       WHERE status = 'active' AND department IS NOT NULL
                       GROUP BY department ORDER BY department"""
                )
                for row in cur.fetchall():
                    components.append(
                        {
                            "name": row["department"],
                            "ok": True,
                            "detail": f"{row['cnt']} agents",
                        }
                    )
        except Exception:
            pass

        return jsonify({"success": True, "components": components})

    # ── Scheduler Jobs ──

    @bp.route("/api/dispatch/scheduler", methods=["GET"])
    @admin_required_decorator
    def dispatch_scheduler():
        """APScheduler job list with next_run times."""
        jobs = []
        try:
            sched = current_app.config.get("CONSCIOUSNESS_SCHEDULER")
            if sched and sched.running:
                for sj in sched.get_jobs():
                    nrt = sj.next_run_time
                    jobs.append(
                        {
                            "id": sj.id,
                            "name": sj.name or sj.id,
                            "next_run": nrt.isoformat() if nrt else None,
                            "trigger": str(sj.trigger) if sj.trigger else "",
                        }
                    )
        except Exception as e:
            logger.warning("[Dispatch] Scheduler list failed: %s", e)

        return jsonify({"success": True, "jobs": jobs})

    # ── Configuration ──

    @bp.route("/api/dispatch/config", methods=["GET"])
    @admin_required_decorator
    def dispatch_config():
        """Autonomy configuration key/value pairs."""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT config_key, config_value FROM autonomy_config ORDER BY config_key")
                entries = [{"key": r["config_key"], "value": r["config_value"]} for r in cur.fetchall()]
            return jsonify({"success": True, "config": entries})
        except Exception as e:
            logger.error("[Dispatch] Config failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/dispatch/config/<key>", methods=["PUT"])
    @admin_required_decorator
    def dispatch_config_update(key):
        """Update a config value."""
        data = request.get_json() or {}
        value = data.get("value", "")
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE autonomy_config SET config_value = %s, updated_at = NOW()
                       WHERE config_key = %s""",
                    (value, key),
                )
                if cur.rowcount == 0:
                    return jsonify({"success": False, "error": "Key not found"})
            return jsonify({"success": True, "key": key})
        except Exception as e:
            logger.error("[Dispatch] Config update failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    # ── Job Monitoring by Department ──

    @bp.route("/api/jobs/by-department")
    @admin_required_decorator
    def jobs_by_department():
        """Job monitoring — all jobs organized by department with failure stats."""
        from tools.department_hq.services.job_registry import JOB_REGISTRY

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT job_name, department,
                          COUNT(*) FILTER (WHERE status = 'error') as fail_count,
                          COUNT(*) FILTER (WHERE status IN ('success', 'partial')) as success_count,
                          MAX(created_at) as last_run,
                          (array_agg(error_message ORDER BY created_at DESC))[1] as last_error
                   FROM autonomy_loop_log
                   WHERE created_at > NOW() - INTERVAL '24 hours'
                   GROUP BY job_name, department"""
            )
            log_data = {r["job_name"]: dict(r) for r in cur.fetchall()}

        departments = {}
        for job_id, meta in JOB_REGISTRY.items():
            dept = meta["department"]
            if dept not in departments:
                departments[dept] = {
                    "name": dept,
                    "director": meta["director"],
                    "jobs": [],
                    "total_fails": 0,
                    "total_success": 0,
                }
            log = log_data.get(job_id, {})
            fail_count = log.get("fail_count", 0) or 0
            success_count = log.get("success_count", 0) or 0
            job_info = {
                "id": job_id,
                "description": meta["description"],
                "interval": meta["interval"],
                "fail_count": fail_count,
                "success_count": success_count,
                "last_run": str(log["last_run"])[:19] if log.get("last_run") else None,
                "last_error": (log.get("last_error") or "")[:200],
                "status": (
                    "error"
                    if fail_count > 0 and success_count == 0
                    else ("warning" if fail_count > 0 else ("ok" if success_count > 0 else "idle"))
                ),
            }
            departments[dept]["jobs"].append(job_info)
            departments[dept]["total_fails"] += fail_count
            departments[dept]["total_success"] += success_count

        # Sort departments by failure count descending
        sorted_depts = dict(sorted(departments.items(), key=lambda x: -x[1]["total_fails"]))

        return jsonify({"success": True, "departments": sorted_depts})

    # ── Repair Pipeline ──

    @bp.route("/api/dispatch/repair-pipeline", methods=["GET"])
    @admin_required_decorator
    def dispatch_repair_pipeline():
        """Repair pipeline status: proposals, sessions, CREED, audits."""
        result = {
            "open_proposals": 0,
            "active_sessions": 0,
            "creed_events": 0,
            "audit_findings": 0,
        }
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT COUNT(*) FROM improvement_proposals WHERE status = 'pending'")
                row = cur.fetchone()
                if row:
                    result["open_proposals"] = row[0]

                cur.execute("SELECT COUNT(*) FROM work_sessions WHERE status = 'active'")
                row = cur.fetchone()
                if row:
                    result["active_sessions"] = row[0]

                try:
                    cur.execute(
                        """SELECT COUNT(*) FROM governance_audit_log
                           WHERE timestamp > NOW() - INTERVAL '24 hours'"""
                    )
                    row = cur.fetchone()
                    if row:
                        result["creed_events"] = row[0]
                except Exception:
                    pass

                try:
                    cur.execute(
                        """SELECT COUNT(*) FROM security_scan_results
                           WHERE created_at > NOW() - INTERVAL '24 hours'"""
                    )
                    row = cur.fetchone()
                    if row:
                        result["audit_findings"] = row[0]
                except Exception:
                    pass

        except Exception as e:
            logger.warning("[Dispatch] Repair pipeline failed: %s", e)

        return jsonify({"success": True, **result})

    # ── Ops Summary (migrated from Autonomy — powers global alert bar) ──

    @bp.route("/api/dispatch/ops-summary", methods=["GET"])
    @admin_required_decorator
    def dispatch_ops_summary():
        """Lightweight counts for the global ops alert bar."""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT
                           COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                           COUNT(*) FILTER (
                               WHERE status = 'pending' AND expires_at < NOW()
                           ) AS expired
                       FROM autonomy_approval_queue"""
                )
                ar = dict(cur.fetchone())
                approvals = {
                    "pending": ar.get("pending") or 0,
                    "expired": ar.get("expired") or 0,
                }

                cur.execute(
                    """SELECT
                           COUNT(*) FILTER (WHERE status = 'running') AS running,
                           COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                           COUNT(*) FILTER (
                               WHERE status = 'running'
                               AND updated_at < NOW() - INTERVAL '15 minutes'
                           ) AS stalled
                       FROM bridge_jobs
                       WHERE status IN ('running', 'pending')
                          OR (status = 'running'
                              AND updated_at < NOW() - INTERVAL '15 minutes')"""
                )
                bj = dict(cur.fetchone())

                cur.execute(
                    """SELECT COUNT(*) AS cnt FROM bridge_jobs
                       WHERE status = 'failed'
                       AND completed_at >= NOW() - INTERVAL '1 hour'"""
                )
                bridge_failed = cur.fetchone()["cnt"] or 0

                cur.execute(
                    """SELECT COUNT(*) AS cnt FROM autonomy_loop_log
                       WHERE status != 'success'
                       AND created_at >= NOW() - INTERVAL '1 hour'"""
                )
                loop_errors = cur.fetchone()["cnt"] or 0

            agent_loop = current_app.config.get("AGENT_LOOP")
            agent_loop_running = bool(agent_loop and getattr(agent_loop, "is_running", False))
            scheduler = current_app.config.get("CONSCIOUSNESS_SCHEDULER")
            scheduler_running = bool(scheduler and scheduler.running)

            active_jobs = {
                "bridge_running": bj.get("running") or 0,
                "bridge_pending": bj.get("pending") or 0,
                "bridge_stalled": bj.get("stalled") or 0,
                "agent_loop_running": agent_loop_running,
                "scheduler_running": scheduler_running,
            }
            errors_1h = {
                "bridge_failed": bridge_failed,
                "loop_errors": loop_errors,
            }

            alerts = []
            if approvals["expired"] > 0:
                alerts.append({"severity": "high", "message": f"{approvals['expired']} expired approval(s)"})
            if (bj.get("stalled") or 0) > 0:
                alerts.append({"severity": "high", "message": f"{bj['stalled']} stalled bridge job(s)"})
            if loop_errors > 0:
                alerts.append({"severity": "medium", "message": f"{loop_errors} loop error(s) in last hour"})
            if bridge_failed > 0:
                alerts.append({"severity": "medium", "message": f"{bridge_failed} failed bridge job(s) in last hour"})
            if not agent_loop_running:
                alerts.append({"severity": "medium", "message": "Agent loop is not running"})
            if not scheduler_running:
                alerts.append({"severity": "medium", "message": "Scheduler is not running"})

            return jsonify(
                {"approvals": approvals, "active_jobs": active_jobs, "errors_1h": errors_1h, "alerts": alerts}
            )

        except Exception as e:
            logger.error("[Dispatch] Ops summary failed: %s", e)
            return jsonify({"approvals": {}, "active_jobs": {}, "errors_1h": {}, "alerts": []})

    # ── Dispatch Traffic Panel ──

    @bp.route("/api/dispatch/traffic", methods=["GET"])
    @admin_required_decorator
    def dispatch_traffic():
        """Live dispatch traffic feed and aggregations — powers Traffic Panel (Decision #540)."""
        hours = min(int(request.args.get("hours", 1)), 24)
        limit = min(int(request.args.get("limit", 30)), 100)
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT agent_name, capability, model_used, module_source,
                              success, duration_ms, created_at
                       FROM task_execution_log
                       WHERE created_at > NOW() - INTERVAL '%s hours'
                       ORDER BY created_at DESC LIMIT %s""",
                    (hours, limit),
                )
                feed = []
                for row in cur.fetchall():
                    r = dict(row)
                    feed.append(
                        {
                            "agent": r.get("agent_name") or "—",
                            "capability": r.get("capability") or "—",
                            "model": r.get("model_used") or "—",
                            "source": r.get("module_source") or "—",
                            "success": r.get("success"),
                            "duration_ms": r.get("duration_ms"),
                            "ts": r["created_at"].isoformat() if r.get("created_at") else None,
                        }
                    )

                cur.execute(
                    """SELECT COALESCE(module_source, 'unknown') AS label,
                              COUNT(*) AS total,
                              COUNT(*) FILTER (WHERE success) AS successes,
                              ROUND(AVG(duration_ms))::int AS avg_ms
                       FROM task_execution_log
                       WHERE created_at > NOW() - INTERVAL '%s hours'
                       GROUP BY module_source ORDER BY total DESC LIMIT 15""",
                    (hours,),
                )
                by_source = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    """SELECT COALESCE(agent_name, 'unknown') AS label,
                              COUNT(*) AS total,
                              COUNT(*) FILTER (WHERE success) AS successes,
                              ROUND(AVG(duration_ms))::int AS avg_ms
                       FROM task_execution_log
                       WHERE created_at > NOW() - INTERVAL '%s hours'
                       GROUP BY agent_name ORDER BY total DESC LIMIT 15""",
                    (hours,),
                )
                by_agent = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    """SELECT COALESCE(model_used, 'unknown') AS label,
                              COUNT(*) AS total,
                              COUNT(*) FILTER (WHERE success) AS successes,
                              ROUND(AVG(duration_ms))::int AS avg_ms
                       FROM task_execution_log
                       WHERE created_at > NOW() - INTERVAL '%s hours'
                       GROUP BY model_used ORDER BY total DESC LIMIT 15""",
                    (hours,),
                )
                by_model = [dict(r) for r in cur.fetchall()]

                by_node = []
                try:
                    cur.execute(
                        """SELECT COALESCE(rn.node_name, 'hub') AS label,
                                  COUNT(*) AS total
                           FROM dispatch_pending_queue dpq
                           LEFT JOIN remote_nodes rn ON dpq.node_id = rn.id
                           WHERE dpq.created_at > NOW() - INTERVAL '%s hours'
                           GROUP BY rn.node_name ORDER BY total DESC LIMIT 10""",
                        (hours,),
                    )
                    by_node = [dict(r) for r in cur.fetchall()]
                except Exception:
                    pass

            total = len(feed)
            successes = sum(1 for f in feed if f["success"])
            return jsonify(
                {
                    "success": True,
                    "hours": hours,
                    "total": total,
                    "success_rate": round(successes / total * 100) if total else 0,
                    "feed": feed,
                    "by_source": by_source,
                    "by_agent": by_agent,
                    "by_model": by_model,
                    "by_node": by_node,
                }
            )
        except Exception as e:
            logger.error("[Dispatch] Traffic failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    # ── Claude Requests Feed (Task #1297) ──

    @bp.route("/api/dispatch/claude-feed", methods=["GET"])
    @admin_required_decorator
    def dispatch_claude_feed():
        """Recent Claude MCP-initiated dispatches.

        Pulls task_execution_log rows tagged with request_origin='claude'
        by the dispatch_context wrapper in mcp_server/server.py. Powers the
        DHQ Dispatch tab "Claude Requests" panel.
        """
        limit = min(int(request.args.get("limit", 50)), 200)
        hours = min(int(request.args.get("hours", 24)), 168)
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, mcp_tool, agent_name, capability,
                              model_used, success, duration_ms, cost,
                              error_message, station_code, created_at
                       FROM task_execution_log
                       WHERE request_origin = 'claude'
                         AND created_at > NOW() - INTERVAL %s
                       ORDER BY id DESC
                       LIMIT %s""",
                    (f"{hours} hours", limit),
                )
                feed = []
                for row in cur.fetchall():
                    r = dict(row)
                    feed.append(
                        {
                            "id": r["id"],
                            "mcp_tool": r.get("mcp_tool") or "",
                            "agent": r.get("agent_name") or "",
                            "capability": r.get("capability") or "",
                            "model": r.get("model_used") or "",
                            "success": r.get("success"),
                            "duration_ms": r.get("duration_ms"),
                            "cost_usd": float(r["cost"]) if r.get("cost") is not None else None,
                            "error": r.get("error_message"),
                            "station": r.get("station_code") or "",
                            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                        }
                    )

                # Aggregates
                cur.execute(
                    """SELECT mcp_tool, COUNT(*) AS n,
                              SUM(CASE WHEN success THEN 1 ELSE 0 END) AS ok
                       FROM task_execution_log
                       WHERE request_origin = 'claude'
                         AND created_at > NOW() - INTERVAL %s
                       GROUP BY mcp_tool ORDER BY n DESC LIMIT 10""",
                    (f"{hours} hours",),
                )
                by_tool = [dict(r) for r in cur.fetchall()]

            total = len(feed)
            successes = sum(1 for f in feed if f["success"])
            return jsonify(
                {
                    "success": True,
                    "hours": hours,
                    "total": total,
                    "success_rate": round(successes / total * 100) if total else 0,
                    "feed": feed,
                    "by_tool": by_tool,
                }
            )
        except Exception as e:
            logger.error("[Dispatch] Claude feed failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500
