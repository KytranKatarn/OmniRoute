"""
Dispatch & Orchestration Routes — Department HQ
Centralizes AI Bridge dispatch monitoring, Ollama engine status,
agent workload, and autonomy loop job visibility.

ADR-045 pattern: register_dispatch_routes(bp, admin_required_decorator)
"""

import logging
import os

import requests as _req
from flask import current_app, jsonify
from flask_login import login_required

from database import get_db_cursor

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://192.168.1.200:11434")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = f"http://{OLLAMA_URL}"


def register_dispatch_routes(bp, admin_required_decorator):
    """Register dispatch & orchestration monitoring endpoints."""

    @bp.route("/api/dispatch/overview", methods=["GET"])
    @login_required
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
