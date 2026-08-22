"""
Dispatch & Orchestration Routes — Department HQ
Centralizes AI Bridge dispatch monitoring, Ollama engine status,
agent workload, and autonomy loop job visibility.

ADR-045 pattern: register_dispatch_routes(bp, admin_required_decorator)
"""

import json
import logging
import os

import requests as _req
from flask import current_app, jsonify, request
from flask_login import login_required

from datetime import timedelta

from database import get_db_cursor
from services.time_utils import now_utc

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://192.168.1.200:11434")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = f"http://{OLLAMA_URL}"


# All-time dispatch totals ("total so far") — a full task_execution_log scan
# (~700ms over 600k+ rows), so cached in-process for 10 min.
_LIFETIME_CACHE = {"ts": 0.0, "data": None}


def _dispatch_lifetime_totals():
    """Cumulative dispatches / tokens / energy / CO2 across ALL of
    task_execution_log. CO2 uses the shared C.R.E.E.D. estimator fragment
    (cloud/contractor rows excluded). Cached 10 min."""
    import time

    now = time.time()
    cached = _LIFETIME_CACHE.get("data")
    if cached is not None and (now - _LIFETIME_CACHE["ts"]) < 600:
        return cached
    try:
        from services.carbon_footprint_service import _CANADA_GRID_KG_CO2_PER_KWH, co2_g_sql

        _co2 = co2_g_sql()
        with get_db_cursor() as (conn, cur):
            cur.execute(
                f"""SELECT COUNT(*)::bigint AS dispatches,
                          COALESCE(SUM(tokens_used), 0)::bigint AS tokens,
                          COALESCE(SUM({_co2}), 0)::double precision AS co2_g
                   FROM task_execution_log"""
            )
            r = dict(cur.fetchone())
        co2_kg = round(r["co2_g"] / 1000.0, 4)
        grid = _CANADA_GRID_KG_CO2_PER_KWH or 0.15
        data = {
            "dispatches": int(r["dispatches"]),
            "tokens": int(r["tokens"]),
            "co2_g": round(r["co2_g"], 1),
            "co2_kg": co2_kg,
            "energy_kwh": round(co2_kg / grid, 3),
        }
        _LIFETIME_CACHE.update(ts=now, data=data)
        return data
    except Exception:
        logger.exception("[Dispatch] lifetime totals failed")
        return _LIFETIME_CACHE.get("data")


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

                # ── Dispatch Metrics (24h) ── unified via the shared helper so
                # THIS panel, the Overview "Dispatches 24h" card and the
                # Consciousness dashboard all report the SAME truthful number
                # (task_execution_log + bridge_jobs, success_rate over decided
                # work, in-flight excluded). Single source of truth:
                # services/dispatch_health_service.py.
                from services.dispatch_health_service import dispatch_health

                h = dispatch_health(24)
                result["dispatch_metrics"] = {
                    "total_24h": h["total"],
                    "success_24h": h["success"],
                    "failed_24h": h["failed"],
                    "failed_real_24h": h["failed_real"],
                    "failed_timeout_24h": h["failed_timeout"],
                    "pending_24h": h["pending"],
                    "success_rate": h["success_rate"],
                    "success_rate_real": h["success_rate_real"],
                    "avg_duration_ms": h["avg_duration_ms"],
                    "tokens_24h": h["tokens"],
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
        # In-process scheduler exists when ARCHIE_RUN_SCHEDULER=1 here. When
        # the scheduler runs in the sidecar container, fall back to the
        # heartbeat row (Path C, decision_id 557).
        next_run_map = {}
        try:
            scheduler = current_app.config.get("CONSCIOUSNESS_SCHEDULER")
            if scheduler and scheduler.running:
                for sj in scheduler.get_jobs():
                    nrt = sj.next_run_time
                    next_run_map[sj.id] = nrt.isoformat() if nrt else None
            else:
                from services import scheduler_health

                for sj in scheduler_health.get_jobs():
                    next_run_map[sj["id"]] = sj.get("next_run")
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

    # ── Backlogs (work_control_service — unified see/toggle, decision #676) ──

    # Hub-DB queue-depth queries (best-effort; backlogs without one show "—").
    _BACKLOG_DEPTH_SQL = {
        "consciousness_embedding": "SELECT COUNT(*) AS n FROM knowledge_base WHERE embedding IS NULL",
        "delegate_task_worker": (
            "SELECT COUNT(*) AS n FROM unified_tasks " "WHERE delegation_source IS NOT NULL AND status = 'pending'"
        ),
        "fleet_backlog_runner": (
            "SELECT COUNT(*) AS n FROM unified_tasks " "WHERE delegation_source IS NULL AND status = 'pending'"
        ),
    }

    @bp.route("/api/dispatch/invokable-skills", methods=["GET"])
    @admin_required_decorator
    def dispatch_invokable_skills():
        """#5291 skill bridge: the invokable-actions registry for archie-tui and
        the cockpit. Membership generated live from delegation_service's
        KNOWN_TOOL_CAPABILITIES + CAPABILITY_DEPARTMENT_MAP; directors resolved
        from the roster so the payload never goes stale against a re-org."""
        from services.delegation_service import (
            build_invokable_skills_registry,
            resolve_department_directors,
        )

        # #5333: director resolution is shared with the internal-key route
        # (/api/internal/delegation/invokable-skills) so the two surfaces can
        # never disagree about who directs a department.
        directors = resolve_department_directors()
        return jsonify({"success": True, **build_invokable_skills_registry(directors)})

    @bp.route("/api/dispatch/backlogs", methods=["GET"])
    @admin_required_decorator
    def dispatch_backlogs():
        """Every module backlog with enabled-state + queue depth + last run."""
        from services import work_control_service as wc

        last_run = {}
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT job_name, MAX(created_at) AS last_run FROM autonomy_loop_log "
                    "WHERE created_at >= NOW() - INTERVAL '7 days' GROUP BY job_name"
                )
                last_run = {r["job_name"]: r["last_run"] for r in cur.fetchall()}
        except Exception as e:
            logger.warning("[Dispatch] backlog last_run failed: %s", e)

        out = []
        for b in [c for c in wc.list_controls() if c["kind"] == "backlog"]:
            depth = None
            sql = _BACKLOG_DEPTH_SQL.get(b["key"])
            if sql:
                try:
                    with get_db_cursor() as (conn, cur):
                        cur.execute(sql)
                        row = cur.fetchone()
                        depth = int(row["n"]) if row else None
                except Exception:
                    depth = None
            lr = last_run.get(b["key"])
            out.append({**b, "queue_depth": depth, "last_run": lr.isoformat() if lr else None})
        return jsonify({"success": True, "backlogs": out})

    @bp.route("/api/dispatch/backlogs/<key>/toggle", methods=["POST"])
    @admin_required_decorator
    def dispatch_backlog_toggle(key):
        """Enable/disable a backlog via work_control_service (routes to its backend)."""
        from services import work_control_service as wc

        data = request.get_json() or {}
        res = wc.set_enabled(key, bool(data.get("enabled", True)))
        if res.get("ok"):
            return jsonify({"success": True, **res})
        return jsonify({"success": False, **res}), 500

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

    @bp.route("/api/dispatch/interrupted-jobs", methods=["GET"])
    @admin_required_decorator
    def dispatch_interrupted_jobs():
        """#1716 — list interrupted (crash-orphaned) bridge_jobs."""
        try:
            from services.job_recovery_service import list_interrupted

            with get_db_cursor() as (conn, cur):
                jobs = list_interrupted(cur, limit=int(request.args.get("limit", 50)))
            for j in jobs:
                for k in ("created_at", "updated_at"):
                    if j.get(k):
                        j[k] = j[k].isoformat()
            return jsonify({"success": True, "jobs": jobs})
        except Exception as e:
            logger.error("[Dispatch] interrupted-jobs failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/dispatch/replay-job/<int:job_id>", methods=["POST"])
    @admin_required_decorator
    def dispatch_replay_job(job_id):
        """#1716 — replay an interrupted/failed job (re-clone + re-dispatch if re-entrant)."""
        try:
            from services.job_recovery_service import replay_job

            with get_db_cursor(commit=True) as (conn, cur):
                result = replay_job(cur, job_id)
            return jsonify({"success": True, **result})
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except Exception as e:
            logger.error("[Dispatch] replay-job failed: %s", e)
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
        """Paginated unified dispatch log (task_execution_log + bridge_jobs)."""
        agent = request.args.get("agent", "").strip()
        capability = request.args.get("capability", "").strip()
        source = request.args.get("source", "all")  # all | task | job
        status = request.args.get("status", "all")  # all | success | failed
        q = request.args.get("q", "").strip()
        try:
            per_page = min(int(request.args.get("per_page", 25)), 100)
            page = max(int(request.args.get("page", 1)), 1)
        except (ValueError, TypeError):
            per_page, page = 25, 1
        offset = (page - 1) * per_page

        now = now_utc()
        default_from = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        default_to = now.strftime("%Y-%m-%d")
        from_dt = request.args.get("from", default_from) + " 00:00:00"
        to_dt = request.args.get("to", default_to) + " 23:59:59"

        try:
            from services.carbon_footprint_service import co2_g_for, co2_g_sql, energy_wh_for

            _co2 = co2_g_sql()
            with get_db_cursor() as (conn, cur):
                # task_execution_log CTE
                # SAFETY: all items in task_filters/job_filters must use %(param)s placeholders.
                # Never interpolate user input directly — it flows through `params` dict only.
                task_filters = ["tel.created_at BETWEEN %(from_dt)s AND %(to_dt)s"]
                if agent:
                    task_filters.append("tel.agent_name = %(agent)s")
                if capability:
                    task_filters.append("tel.capability = %(capability)s")
                if status in ("success", "failed"):
                    task_filters.append("tel.success = %(status_bool)s")
                if q:
                    task_filters.append(
                        "(tel.agent_name ILIKE %(q_like)s OR tel.capability ILIKE %(q_like)s"
                        " OR tel.module_source ILIKE %(q_like)s"
                        " OR COALESCE(tel.error_message,'') ILIKE %(q_like)s)"
                    )
                task_cte = """
                    SELECT 'task'::text AS source,
                           COALESCE(a.name, tel.agent_name) AS agent_name,
                           tel.capability,
                           tel.module_source AS module,
                           tel.model_used,
                           tel.duration_ms,
                           tel.success,
                           tel.error_message,
                           tel.created_at,
                           tel.tokens_used,
                           tel.worker_type,
                           COALESCE(tel.cost, 0)::float AS cost,
                           CASE WHEN rn.node_id IS NULL OR rn.node_id = 'archie-starbase' THEN 'Starbase - A.R.C.H.I.E.' ELSE rn.node_name END AS node_name
                    FROM task_execution_log tel
                    LEFT JOIN remote_nodes rn ON rn.id = tel.node_used_id
                    LEFT JOIN agents a ON (
                        tel.agent_name ~ '^fleet-agent-[0-9]+$'
                        AND a.id::text = substring(tel.agent_name FROM 13)
                    )
                    WHERE {task_where}
                """.format(
                    task_where=" AND ".join(task_filters)
                )

                # bridge_jobs CTE — no duration_ms, job_type not capability
                job_filters = ["bj.created_at BETWEEN %(from_dt)s AND %(to_dt)s"]
                if agent:
                    job_filters.append("bj.agent_name = %(agent)s")
                if capability:
                    job_filters.append("bj.job_type = %(capability)s")
                if status in ("success", "failed"):
                    job_filters.append("(bj.status = 'completed') = %(status_bool)s")
                if q:
                    job_filters.append(
                        "(bj.agent_name ILIKE %(q_like)s OR bj.job_type ILIKE %(q_like)s"
                        " OR COALESCE(bj.module_source,'') ILIKE %(q_like)s"
                        " OR COALESCE(bj.error_message,'') ILIKE %(q_like)s)"
                    )
                job_cte = """
                    SELECT 'job'::text AS source,
                           COALESCE(a.name, bj.agent_name) AS agent_name,
                           bj.job_type AS capability,
                           bj.module_source AS module,
                           NULL::text AS model_used,
                           NULL::int AS duration_ms,
                           CASE WHEN bj.status = 'completed' THEN TRUE
                                WHEN bj.status IN ('failed','error','expired','cancelled','timeout') THEN FALSE
                                ELSE NULL END AS success,
                           bj.error_message,
                           bj.created_at,
                           NULL::int AS tokens_used,
                           NULL::text AS worker_type,
                           0::float AS cost,
                           CASE WHEN COALESCE(bj.metadata->>'node_name','') = ''
                                     OR LOWER(bj.metadata->>'node_name') IN ('archie starbase','archie-starbase','hub','archie-hub')
                                THEN 'Starbase - A.R.C.H.I.E.' ELSE bj.metadata->>'node_name' END AS node_name
                    FROM bridge_jobs bj
                    LEFT JOIN agents a ON (
                        bj.agent_name ~ '^fleet-agent-[0-9]+$'
                        AND a.id::text = substring(bj.agent_name FROM 13)
                    )
                    WHERE {job_where}
                """.format(
                    job_where=" AND ".join(job_filters)
                )

                if source == "task":
                    union_sql = task_cte
                elif source == "job":
                    union_sql = job_cte
                else:
                    union_sql = "({task}) UNION ALL ({job})".format(task=task_cte, job=job_cte)

                params = {
                    "from_dt": from_dt,
                    "to_dt": to_dt,
                    "agent": agent or None,
                    "capability": capability or None,
                    "q_like": "%" + q + "%" if q else None,
                    "status_bool": (True if status == "success" else False if status == "failed" else None),
                }

                # Stats query
                cur.execute(
                    """
                    WITH combined AS ({union})
                    SELECT
                        COUNT(*)::int AS total_calls,
                        COALESCE(SUM(tokens_used), 0)::bigint AS total_tokens,
                        COALESCE(SUM({co2}), 0)::double precision AS total_co2_g,
                        ROUND(
                            100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END)
                            / NULLIF(COUNT(*) FILTER (WHERE success IS NOT NULL), 0), 1
                        ) AS success_rate,
                        ROUND(
                            AVG(CASE WHEN success AND duration_ms IS NOT NULL
                                THEN duration_ms END) / 1000.0, 1
                        ) AS avg_duration_s,
                        MODE() WITHIN GROUP (ORDER BY agent_name) AS top_agent,
                        MODE() WITHIN GROUP (ORDER BY module) AS top_module
                    FROM combined
                    """.format(
                        union=union_sql, co2=_co2
                    ),
                    params,
                )
                sr = cur.fetchone()
                stats = {
                    "total_calls": int(sr["total_calls"] or 0),
                    "success_rate": float(sr["success_rate"] or 0),
                    "avg_duration_s": float(sr["avg_duration_s"] or 0),
                    "total_tokens": int(sr["total_tokens"] or 0),
                    "total_co2_g": round(float(sr["total_co2_g"] or 0), 3),
                    "top_agent": sr["top_agent"] or "—",
                    "top_module": sr["top_module"] or "—",
                }

                # Rows query
                cur.execute(
                    """
                    WITH combined AS ({union})
                    SELECT * FROM combined
                    ORDER BY created_at DESC
                    LIMIT %(per_page)s OFFSET %(offset)s
                    """.format(
                        union=union_sql
                    ),
                    {**params, "per_page": per_page, "offset": offset},
                )
                rows = [
                    {
                        "source": r["source"],
                        "agent_name": r["agent_name"],
                        "capability": r["capability"],
                        "module": r["module"],
                        "model_used": r["model_used"],
                        "duration_ms": r["duration_ms"],
                        "success": r["success"],
                        "error_message": r["error_message"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                        "tokens_used": r["tokens_used"],
                        "co2_g": (
                            None if r.get("worker_type") == "contract" else co2_g_for(r["model_used"], r["duration_ms"])
                        ),
                        "energy_wh": (
                            None
                            if r.get("worker_type") == "contract" or not r.get("model_used")
                            else energy_wh_for(r["model_used"], r["duration_ms"])
                        ),
                        "cost": r["cost"],
                        "node_name": r.get("node_name", "Hub"),
                    }
                    for r in cur.fetchall()
                ]

            total = stats["total_calls"]
            pages = max(1, (total + per_page - 1) // per_page)
            return jsonify(
                {
                    "stats": stats,
                    "rows": rows,
                    "lifetime": _dispatch_lifetime_totals(),
                    "total": total,
                    "page": page,
                    "pages": pages,
                }
            )

        except Exception:
            logger.exception("[Dispatch] dispatch_history failed")
            return (
                jsonify(
                    {
                        "error": "internal error",
                        "stats": {
                            "total_calls": 0,
                            "success_rate": 0,
                            "avg_duration_s": 0,
                            "top_agent": "—",
                            "top_module": "—",
                        },
                        "rows": [],
                        "total": 0,
                        "page": 1,
                        "pages": 1,
                    }
                ),
                500,
            )

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

        # Scheduler + Agent Loop. When the scheduler is in-process we read
        # the live object; when it's in the sidecar container (Path C,
        # decision_id 557) we read the heartbeat row instead. Heartbeat
        # row also wins over an in-process scheduler that's been stopped
        # but not torn down.
        try:
            sched = current_app.config.get("CONSCIOUSNESS_SCHEDULER")
            if sched and sched.running:
                components.append(
                    {
                        "name": "Scheduler",
                        "ok": True,
                        "detail": f"{len(sched.get_jobs())} jobs",
                    }
                )
            else:
                from services import scheduler_health

                hs = scheduler_health.read_status()
                components.append(
                    {
                        "name": "Scheduler",
                        "ok": hs["scheduler_running"],
                        "detail": (f"{hs['jobs_total']} jobs (sidecar)" if hs["scheduler_running"] else hs["detail"]),
                    }
                )
        except Exception:
            components.append({"name": "Scheduler", "ok": False, "detail": "Error"})

        # Agent Loop
        try:
            agent_loop = current_app.config.get("AGENT_LOOP")
            if agent_loop and getattr(agent_loop, "running", False):
                components.append(
                    {
                        "name": "Agent Loop",
                        "ok": True,
                        "detail": "Running",
                    }
                )
            else:
                from services import scheduler_health

                hs = scheduler_health.read_status()
                components.append(
                    {
                        "name": "Agent Loop",
                        "ok": hs["agent_loop_running"],
                        "detail": "Running (sidecar)" if hs["agent_loop_running"] else hs["detail"],
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
            else:
                # Path C: read job list from sidecar heartbeat
                from services import scheduler_health

                jobs = scheduler_health.get_jobs()
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
                       AND completed_at >= NOW() - INTERVAL '1 hour'
                       AND (metadata->>'reap_reason' IS NULL
                            OR metadata->>'reap_reason' NOT LIKE '%platform restarted%')"""
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
            # Path C: when scheduler is in the sidecar container, the
            # in-process objects above are None — fall back to heartbeat.
            if not scheduler_running or not agent_loop_running:
                from services import scheduler_health

                hs = scheduler_health.read_status()
                if not scheduler_running:
                    scheduler_running = hs["scheduler_running"]
                if not agent_loop_running:
                    agent_loop_running = hs["agent_loop_running"]

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
        # Drill-down filters (#4345): clicking a Traffic breakdown row filters the FEED
        # to that entity's recent actions (breakdowns stay overall). Parameterized.
        _fagent = (request.args.get("fagent") or "").strip()
        _fsource = (request.args.get("fsource") or "").strip()
        _fmodel = (request.args.get("fmodel") or "").strip()
        _fnode = (request.args.get("fnode") or "").strip()
        _feed_where = ["tel.created_at > NOW() - INTERVAL '%s hours'"]
        _feed_params = [hours]
        if _fagent:
            _feed_where.append("COALESCE(a.name, tel.agent_name) = %s")
            _feed_params.append(_fagent)
        if _fsource:
            _feed_where.append("tel.module_source = %s")
            _feed_params.append(_fsource)
        if _fmodel:
            _feed_where.append("tel.model_used = %s")
            _feed_params.append(_fmodel)
        if _fnode:
            if _fnode == "Starbase - A.R.C.H.I.E.":
                _feed_where.append("(rn.node_id IS NULL OR rn.node_id = 'archie-starbase')")
            else:
                _feed_where.append("rn.node_name = %s")
                _feed_params.append(_fnode)
        _drilled = bool(_fagent or _fsource or _fmodel or _fnode)
        # 'Real inference only' (default): hide non-LLM orchestration/job MARKERS
        # (worker_type NULL / sentinel models bridge-managed/internal), scrape
        # (browser) + embeddings from the FEED so it shows real LLM dispatches with
        # tokens. markers=all shows everything. A drill into a specific source/agent
        # always shows ALL its rows (incl. markers) so you can inspect them.
        _show_markers = (request.args.get("markers") or "").lower() == "all"
        if not _show_markers and not _drilled:
            _feed_where.append(
                "tel.worker_type IS NOT NULL "
                "AND lower(COALESCE(tel.model_used, '')) NOT IN "
                "('bridge-managed', 'internal', 'batch', 'browser', 'comfyui', '') "
                "AND lower(COALESCE(tel.model_used, '')) NOT LIKE '%%embed%%'"
            )
        _feed_limit = 100 if _drilled else limit
        try:
            # Carbon (grams CO2) — reuse the C.R.E.E.D. estimator methodology so
            # dispatch CO2 reconciles with the environmental pillar (#4564).
            from services.carbon_footprint_service import co2_g_for, co2_g_sql, energy_wh_for

            _co2 = co2_g_sql()
            _co2_tel = co2_g_sql("tel.model_used", "tel.duration_ms", "tel.worker_type")
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT COALESCE(a.name, tel.agent_name) AS agent_name,
                              tel.capability, tel.model_used, tel.module_source,
                              tel.success, tel.duration_ms, tel.tokens_used, tel.worker_type, tel.created_at,
                              CASE WHEN rn.node_id IS NULL OR rn.node_id = 'archie-starbase' THEN 'Starbase - A.R.C.H.I.E.' ELSE rn.node_name END AS node_name,
                              (tel.request_metadata->>'dr_mode')::boolean AS dr_mode
                       FROM task_execution_log tel
                       LEFT JOIN remote_nodes rn ON rn.id = tel.node_used_id
                       LEFT JOIN agents a ON (
                           tel.agent_name ~ '^fleet-agent-[0-9]+$'
                           AND a.id::text = substring(tel.agent_name FROM 13)
                       )
                       WHERE """
                    + " AND ".join(_feed_where)
                    + """
                       ORDER BY tel.created_at DESC LIMIT %s""",
                    tuple(_feed_params) + (_feed_limit,),
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
                            "node": r.get("node_name") or "Hub",
                            "success": r.get("success"),
                            "duration_ms": r.get("duration_ms"),
                            "tokens": r.get("tokens_used"),
                            "co2_g": (
                                None
                                if r.get("worker_type") == "contract"
                                else co2_g_for(r.get("model_used"), r.get("duration_ms"))
                            ),
                            "energy_wh": (
                                None
                                if r.get("worker_type") == "contract" or not r.get("model_used")
                                else energy_wh_for(r.get("model_used"), r.get("duration_ms"))
                            ),
                            "ts": r["created_at"].isoformat() if r.get("created_at") else None,
                            "dr_mode": bool(r.get("dr_mode")),
                        }
                    )

                cur.execute(
                    f"""SELECT COALESCE(module_source, 'unknown') AS label,
                              COUNT(*) AS total,
                              COUNT(*) FILTER (WHERE success) AS successes,
                              COALESCE(SUM(tokens_used), 0)::bigint AS tokens,
                              COALESCE(SUM({_co2}), 0)::double precision AS co2_g,
                              ROUND(AVG(duration_ms))::int AS avg_ms
                       FROM task_execution_log
                       WHERE created_at > NOW() - INTERVAL '%s hours'
                       GROUP BY module_source ORDER BY total DESC LIMIT 15""",
                    (hours,),
                )
                by_source = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    f"""SELECT COALESCE(agent_name, 'unknown') AS label,
                              COUNT(*) AS total,
                              COUNT(*) FILTER (WHERE success) AS successes,
                              COALESCE(SUM(tokens_used), 0)::bigint AS tokens,
                              COALESCE(SUM({_co2}), 0)::double precision AS co2_g,
                              ROUND(AVG(duration_ms))::int AS avg_ms
                       FROM task_execution_log
                       WHERE created_at > NOW() - INTERVAL '%s hours'
                       GROUP BY agent_name ORDER BY total DESC LIMIT 15""",
                    (hours,),
                )
                by_agent = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    f"""SELECT COALESCE(model_used, 'unknown') AS label,
                              COUNT(*) AS total,
                              COUNT(*) FILTER (WHERE success) AS successes,
                              COALESCE(SUM(tokens_used), 0)::bigint AS tokens,
                              COALESCE(SUM({_co2}), 0)::double precision AS co2_g,
                              ROUND(AVG(duration_ms))::int AS avg_ms
                       FROM task_execution_log
                       WHERE created_at > NOW() - INTERVAL '%s hours'
                         -- #4344: BY MODEL = real LLM generation only. Exclude orchestration/
                         -- marker rows (direct-INSERT job heartbeats omit worker_type -> NULL;
                         -- _log_execution ALWAYS sets it) + non-LLM compute (browser/scraper,
                         -- embeddings) + leftover placeholder labels. Markers still appear in
                         -- BY SOURCE / BY AGENT / the feed as real activity.
                         AND worker_type IS NOT NULL
                         AND model_used NOT IN ('internal','batch','bridge-managed','browser')
                         AND model_used NOT ILIKE '%%embed%%'
                       GROUP BY model_used ORDER BY total DESC LIMIT 15""",
                    (hours,),
                )
                by_model = [dict(r) for r in cur.fetchall()]

                by_node = []
                try:
                    # task_execution_log.node_used_id was added in PR #802 and is
                    # now the canonical fleet attribution source. The earlier
                    # version of this block joined dispatch_pending_queue on a
                    # non-existent node_id column — silent failure swallowed by
                    # the surrounding try/except. Fixed here as part of the
                    # DHQ Dispatch panel breakdown.
                    cur.execute(
                        """SELECT CASE WHEN rn.node_id IS NULL OR rn.node_id = 'archie-starbase'
                                       THEN 'Starbase - A.R.C.H.I.E.' ELSE rn.node_name END AS label,
                                  COUNT(*) AS total,
                                  COUNT(*) FILTER (WHERE tel.success) AS successes,
                                  COALESCE(SUM(tel.tokens_used), 0)::bigint AS tokens,
                                  COALESCE(SUM("""
                        + _co2_tel
                        + """), 0)::double precision AS co2_g,
                                  ROUND(AVG(tel.duration_ms))::int AS avg_ms
                           FROM task_execution_log tel
                           LEFT JOIN remote_nodes rn ON rn.id = tel.node_used_id
                           WHERE tel.created_at > NOW() - INTERVAL '%s hours'
                           GROUP BY CASE WHEN rn.node_id IS NULL OR rn.node_id = 'archie-starbase'
                                         THEN 'Starbase - A.R.C.H.I.E.' ELSE rn.node_name END
                           ORDER BY total DESC LIMIT 10""",
                        (hours,),
                    )
                    by_node = [dict(r) for r in cur.fetchall()]
                except Exception:
                    pass

            # Page-scoped only: the feed is LIMIT-capped, so these describe the
            # fetched page, NOT the whole window. Renamed from total/success_rate
            # which rendered "30 · 100%" beside window-wide failure tiles (#5706).
            # Sole consumer is loadDispatchTraffic() in department-hq.js (updated).
            page_total = len(feed)
            successes = sum(1 for f in feed if f["success"])
            return jsonify(
                {
                    "success": True,
                    "hours": hours,
                    "page_total": page_total,
                    "page_success_rate": round(successes / page_total * 100) if page_total else 0,
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
                    """SELECT tel.id, tel.mcp_tool,
                              COALESCE(a.name, tel.agent_name) AS agent_name,
                              tel.capability,
                              tel.model_used, tel.success, tel.duration_ms, tel.cost,
                              tel.error_message, tel.station_code, tel.created_at
                       FROM task_execution_log tel
                       LEFT JOIN agents a ON (
                           tel.agent_name ~ '^fleet-agent-[0-9]+$'
                           AND a.id::text = substring(tel.agent_name FROM 13)
                       )
                       WHERE tel.request_origin = 'claude'
                         AND tel.created_at > NOW() - INTERVAL %s
                       ORDER BY tel.id DESC
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

                # Queued + in-flight delegations (not yet completed). The
                # ContextVar attribution in PR #493 only catches synchronous
                # MCP→dispatch flows; mcp__archie__delegate_task is async by
                # design (queues to unified_tasks, dispatched later by
                # delegate_task_worker), so its rows never reach
                # task_execution_log with request_origin='claude'. This
                # second source closes the gap.
                # Surface (a) recent Claude delegations AND (b) ANY blocked/
                # failed delegation regardless of source or age — a stuck row
                # must never quietly age out of the queue (that is the whole
                # "forgotten blocked job" problem). The 'automation' Codex rows
                # (status='blocked') surface via the second clause so the owner
                # can Retry/Dismiss them from the queue too.
                cur.execute(
                    """SELECT id, status, title, delegation_args, delegation_source,
                              created_at, completed_at,
                              EXTRACT(EPOCH FROM (NOW() - created_at))::int AS age_secs
                       FROM unified_tasks
                       WHERE delegation_source IS NOT NULL
                         AND status NOT IN ('completed', 'cancelled')
                         AND (
                               (delegation_source = 'claude'
                                AND created_at > NOW() - INTERVAL %s)
                               OR status IN ('blocked', 'failed')
                             )
                       ORDER BY (status IN ('blocked', 'failed')) DESC, id DESC
                       LIMIT %s""",
                    (f"{hours} hours", limit),
                )
                pending = []
                for row in cur.fetchall():
                    r = dict(row)
                    args = r.get("delegation_args") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    pending.append(
                        {
                            "id": r["id"],
                            "status": r.get("status") or "",
                            "title": r.get("title") or "",
                            "capability": args.get("capability") or "",
                            "reason": args.get("reason") or "",
                            "requested_by": args.get("requested_by") or "",
                            "delegation_source": r.get("delegation_source") or "",
                            "age_secs": r.get("age_secs"),
                            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                            "completed_at": r["completed_at"].isoformat() if r.get("completed_at") else None,
                        }
                    )

            # True dispatched totals — NOT len(feed), which is capped at the row
            # LIMIT and only sees sync request_origin='claude' rows. delegate_task
            # is async, so its executions land in unified_tasks, not
            # task_execution_log. Count terminal delegations (completed+blocked)
            # alongside the sync rows so the header stops showing "0 dispatched"
            # when delegated work actually ran.
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT
                           (SELECT COUNT(*) FROM task_execution_log
                              WHERE request_origin = 'claude'
                                AND created_at > NOW() - INTERVAL %(win)s) AS tel_total,
                           (SELECT COUNT(*) FROM task_execution_log
                              WHERE request_origin = 'claude' AND success IS TRUE
                                AND created_at > NOW() - INTERVAL %(win)s) AS tel_ok,
                           (SELECT COUNT(*) FROM unified_tasks
                              WHERE delegation_source = 'claude'
                                AND status IN ('completed', 'blocked')
                                AND created_at > NOW() - INTERVAL %(win)s) AS del_total,
                           (SELECT COUNT(*) FROM unified_tasks
                              WHERE delegation_source = 'claude' AND status = 'completed'
                                AND created_at > NOW() - INTERVAL %(win)s) AS del_ok""",
                    {"win": f"{hours} hours"},
                )
                c = dict(cur.fetchone())
            total = int(c["tel_total"] or 0) + int(c["del_total"] or 0)
            successes = int(c["tel_ok"] or 0) + int(c["del_ok"] or 0)
            return jsonify(
                {
                    "success": True,
                    "hours": hours,
                    "total": total,
                    "success_rate": round(successes / total * 100) if total else 0,
                    "feed": feed,
                    "by_tool": by_tool,
                    "pending": pending,
                }
            )
        except Exception as e:
            logger.error("[Dispatch] Claude feed failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    # ── Blocked-job queue actions (owner Retry / Fix / Dismiss) ──────────
    # Give the owner a one-click lever on a blocked/failed delegation so it
    # never rots in the queue. All three are admin-gated and operate ONLY on
    # delegation rows (services.delegation_service guards status + source).
    @bp.route("/api/dispatch/delegations/<int:task_id>/retry", methods=["POST"])
    @admin_required_decorator
    def dispatch_delegation_retry(task_id):
        """Re-queue a blocked/failed delegation (codex_task -> deferred, else pending)."""
        try:
            from services.delegation_service import requeue_blocked_delegation

            result = requeue_blocked_delegation(task_id)
            return jsonify(result), (200 if result.get("success") else 400)
        except Exception as e:
            logger.error("[Dispatch] delegation retry failed for #%s: %s", task_id, e)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/dispatch/delegations/<int:task_id>/fix", methods=["POST"])
    @admin_required_decorator
    def dispatch_delegation_fix(task_id):
        """Deterministically document a stuck doc delegation (no slow LLM)."""
        try:
            from services.delegation_service import fix_documentation_delegation

            result = fix_documentation_delegation(task_id)
            return jsonify(result), (200 if result.get("success") else 400)
        except Exception as e:
            logger.error("[Dispatch] delegation fix failed for #%s: %s", task_id, e)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/dispatch/delegations/<int:task_id>/dismiss", methods=["POST"])
    @admin_required_decorator
    def dispatch_delegation_dismiss(task_id):
        """Cancel + audit-stamp a blocked/failed delegation so it leaves the queue."""
        try:
            from services.delegation_service import dismiss_delegation

            body = request.get_json(silent=True) or {}
            result = dismiss_delegation(task_id, reason=(body.get("reason") or ""))
            return jsonify(result), (200 if result.get("success") else 400)
        except Exception as e:
            logger.error("[Dispatch] delegation dismiss failed for #%s: %s", task_id, e)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/alerts/history", methods=["GET"])
    @admin_required_decorator
    def alerts_history():
        """Paginated system_notifications with filter + stats."""
        now = now_utc()
        default_from = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        default_to = now.strftime("%Y-%m-%d")
        from_date = (request.args.get("from_date", "") or "").strip() or default_from
        to_date = (request.args.get("to_date", "") or "").strip() or default_to
        type_filter = request.args.get("type", "all").strip()
        priority_filter = request.args.get("priority", "all").strip()
        status_filter = request.args.get("status", "all").strip()
        q = request.args.get("q", "").strip()
        try:
            limit = min(200, max(1, int(request.args.get("limit", 50))))
            page = max(1, int(request.args.get("page", 1)))
        except (ValueError, TypeError):
            limit, page = 50, 1
        offset = (page - 1) * limit

        try:
            with get_db_cursor() as (conn, cur):
                # History view shows all alerts (including archived/processed).
                # Active-only filter available via status_filter='active'.
                conditions = [
                    "created_at >= %(from_date)s::date",
                    "created_at < %(to_date)s::date + interval '1 day'",
                ]
                params = {"from_date": from_date, "to_date": to_date}

                if type_filter != "all":
                    conditions.append("type = %(type_filter)s")
                    params["type_filter"] = type_filter
                if priority_filter != "all":
                    conditions.append("priority = %(priority_filter)s")
                    params["priority_filter"] = priority_filter
                if status_filter == "unread":
                    conditions.append("is_read = false")
                elif status_filter == "read":
                    conditions.append("is_read = true")
                elif status_filter == "active":
                    conditions.append("is_archived = false")
                elif status_filter == "archived":
                    conditions.append("is_archived = true")
                if q:
                    conditions.append(
                        "(title ILIKE %(q_like)s OR message ILIKE %(q_like)s" " OR source ILIKE %(q_like)s)"
                    )
                    params["q_like"] = f"%{q}%"

                where = " AND ".join(conditions)

                # Windowed stats (respects active filters)
                cur.execute(
                    f"""
                    SELECT COUNT(*)::int AS total,
                           SUM(CASE WHEN is_read = false THEN 1 ELSE 0 END)::int AS unread
                    FROM system_notifications WHERE {where}
                    """,
                    params,
                )
                stat_row = cur.fetchone()
                total = int(stat_row["total"] or 0)
                unread = int(stat_row["unread"] or 0)

                # Fixed 24h error/warning counts (always full 24h, ignores date filter)
                cutoff_24h = now - timedelta(hours=24)
                cur.execute(
                    """
                    SELECT
                        SUM(CASE WHEN type = 'error'   THEN 1 ELSE 0 END)::int AS errors_24h,
                        SUM(CASE WHEN type = 'warning' THEN 1 ELSE 0 END)::int AS warnings_24h
                    FROM system_notifications
                    WHERE is_archived = false AND created_at >= %(cutoff)s
                    """,
                    {"cutoff": cutoff_24h},
                )
                sr = cur.fetchone()

                # Paginated rows
                cur.execute(
                    f"""
                    SELECT id, type, priority, title, message, source, source_icon,
                           is_read, telegram_forwarded, grouped_count, related_action,
                           metadata, created_at
                    FROM system_notifications
                    WHERE {where}
                    ORDER BY created_at DESC
                    LIMIT %(limit)s OFFSET %(offset)s
                    """,
                    {**params, "limit": limit, "offset": offset},
                )
                cols = [
                    "id",
                    "type",
                    "priority",
                    "title",
                    "message",
                    "source",
                    "source_icon",
                    "is_read",
                    "telegram_forwarded",
                    "grouped_count",
                    "related_action",
                    "metadata",
                    "created_at",
                ]
                rows = []
                for r in cur.fetchall():
                    row_dict = dict(zip(cols, r)) if not hasattr(r, "keys") else dict(r)
                    if row_dict.get("created_at"):
                        row_dict["created_at"] = row_dict["created_at"].isoformat()
                    rows.append(row_dict)

                pages = max(1, (total + limit - 1) // limit)
                return jsonify(
                    {
                        "stats": {
                            "total": total,
                            "unread": unread,
                            "errors_24h": int(sr["errors_24h"] or 0),
                            "warnings_24h": int(sr["warnings_24h"] or 0),
                        },
                        "rows": rows,
                        "page": page,
                        "pages": pages,
                        "total": total,
                    }
                )
        except Exception:
            logger.exception("[Dispatch] alerts_history failed")
            return jsonify({"error": "internal error"}), 500

    @bp.route("/api/dispatch/history/agents", methods=["GET"])
    @admin_required_decorator
    def dispatch_history_agents():
        """Distinct agent names for the history filter dropdown (last 90 days)."""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT DISTINCT agent_name
                    FROM task_execution_log
                    WHERE agent_name IS NOT NULL
                      AND created_at > NOW() - INTERVAL '90 days'
                    ORDER BY agent_name
                    """
                )
                agents = [r["agent_name"] for r in cur.fetchall()]
            return jsonify(agents)
        except Exception:
            logger.exception("dispatch_history_agents failed")
            return jsonify([]), 500

    @bp.route("/api/dispatch/history/capabilities", methods=["GET"])
    @admin_required_decorator
    def dispatch_history_capabilities():
        """Distinct capabilities for the history filter dropdown (last 90 days)."""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT DISTINCT capability
                    FROM task_execution_log
                    WHERE capability IS NOT NULL
                      AND created_at > NOW() - INTERVAL '90 days'
                    ORDER BY capability
                    """
                )
                caps = [r["capability"] for r in cur.fetchall()]
            return jsonify(caps)
        except Exception:
            logger.exception("dispatch_history_capabilities failed")
            return jsonify([]), 500
