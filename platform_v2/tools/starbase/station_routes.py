"""Starbase Command — Station routes (definitions, config, actions, benchmarks)"""

import json
import os
import time
import logging
from typing import List
from flask import jsonify, request
from flask_login import login_required, current_user
from database import get_db_cursor
import psycopg2
import psutil
import requests

try:
    from ai_bridge.agent_performance_tracker import (
        get_agent_performance,
        update_agent_performance,
        get_top_performers,
    )

    _HAS_PERFORMANCE_TRACKER = True
except ImportError:
    _HAS_PERFORMANCE_TRACKER = False

from .helpers import (
    _get_cached_ollama_tags,
    _get_cached_ollama_ps,
)

logger = logging.getLogger(__name__)


def register_station_routes(bp, admin_required):
    """Register station-related routes on the bridge blueprint."""

    # ============================================================================
    # STATION DEFINITIONS (Database-driven - 10 stations)
    # ============================================================================

    def get_stations_from_db():
        """Get all stations from database"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT station_code, station_name, full_name, description,
                           color, icon, default_llm, modules, position_row, position_order
                    FROM bridge_stations
                    WHERE is_active = TRUE
                    ORDER BY position_row, position_order
                """
                )
                stations = cur.fetchall()
                return {s["station_code"]: dict(s) for s in stations}
        except Exception as e:
            logger.error(f"Error loading stations from DB: {e}")
            return {}

    # Fallback stations if DB unavailable (6 consolidated stations — Project #91)
    STATIONS_FALLBACK = {
        "COMMAND": {
            "station_name": "Command",
            "full_name": "A.R.C.H.I.E. Command & Dispatch",
            "color": "#00FFFF",
            "icon": "🎯",
            "default_llm": "dolphin3-8k:latest",
            "modules": ["archie_core", "archie_chat", "bridge", "team_management", "security_network"],
        },
        "ANALYTICS": {
            "station_name": "Analytics",
            "full_name": "Analytics & Intelligence Hub",
            "color": "#FF00FF",
            "icon": "📊",
            "default_llm": "qwen25-classify",
            "modules": ["consciousness", "knowledge_base", "analytics"],
        },
        "RESEARCH": {
            "station_name": "Research",
            "full_name": "Research & Knowledge Center",
            "color": "#8B5CF6",
            "icon": "🔬",
            "default_llm": "qwen3-coder-cpu:latest",
            "modules": ["obsidian_vault", "api_docs", "dev_hq"],
        },
        "OPERATIONS": {
            "station_name": "Operations",
            "full_name": "Operations & Communications Center",
            "color": "#FFAA00",
            "icon": "📡",
            "default_llm": "dolphin3-8k:latest",
            "modules": [
                "system_operations",
                "backup_manager",
                "saas_manager",
                "email_manager",
                "automations",
                "scheduler",
                "autonomy",
            ],
        },
        "ENGINEERING": {
            "station_name": "Engineering",
            "full_name": "Engineering & Development Lab",
            "color": "#0EA5E9",
            "icon": "⚙️",
            "default_llm": "qwen3-coder-cpu:latest",
            "modules": ["dev_pipeline", "project_manager", "website_studio", "store_builder"],
        },
        "CREATIVE": {
            "station_name": "Creative",
            "full_name": "Creative & Wellness Studio",
            "color": "#F472B6",
            "icon": "🎨",
            "default_llm": "dolphin3-8k:latest",
            "modules": [
                "content_studio",
                "social_media",
                "media_hub",
                "crm",
                "call_center",
                "invoicing",
                "fitness",
                "therapy",
                "doc",
            ],
        },
    }

    # ============================================================================
    # STARSHIP NODE DETECTION
    # ============================================================================

    def get_starship_node_for_user(user_id):
        """Check if the current user is a starship node operator."""
        if not user_id:
            return None
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT node_id, node_name, deployment_mode, hostname, port,
                           status, bridge_priority, gpu_model, gpu_vram_gb,
                           cpu_model, cpu_cores, ram_gb, disk_gb
                    FROM remote_nodes
                    WHERE registered_by = %s AND deployment_mode = 'starship' AND is_active = true
                    LIMIT 1
                """,
                    (user_id,),
                )
                return cur.fetchone()
        except Exception:
            return None

    # ============================================================================
    # STATIONS API
    # ============================================================================

    @bp.route("/api/stations")
    @login_required
    def get_stations():
        """Get all station configurations from database (10 stations)"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Single query: stations + their assigned agents via LEFT JOIN + json_agg
                cur.execute(
                    """
                    SELECT bs.id, bs.station_code, bs.station_name, bs.full_name,
                           bs.description, bs.color, bs.icon, bs.default_llm,
                           bs.modules, bs.position_row, bs.position_order,
                           bs.max_primary, bs.max_auxiliary, bs.allow_overflow,
                           COALESCE(
                               json_agg(
                                   json_build_object(
                                       'id', a.id,
                                       'name', a.name,
                                       'first_name', a.first_name,
                                       'last_name', a.last_name,
                                       'title', a.title,
                                       'avatar_url', a.avatar_url,
                                       'model', a.model,
                                       'assignment_type', sa.assignment_type,
                                       'status', a.status,
                                       'shift_state', a.shift_state
                                   ) ORDER BY sa.priority
                               ) FILTER (WHERE a.id IS NOT NULL),
                               '[]'::json
                           ) as assigned_agents
                    FROM bridge_stations bs
                    LEFT JOIN station_assignments sa
                        ON sa.station_id = bs.id AND sa.is_active = TRUE
                    LEFT JOIN agents a
                        ON sa.agent_id = a.id
                    WHERE bs.is_active = TRUE
                    GROUP BY bs.id, bs.station_code, bs.station_name, bs.full_name,
                             bs.description, bs.color, bs.icon, bs.default_llm,
                             bs.modules, bs.position_row, bs.position_order,
                             bs.max_primary, bs.max_auxiliary, bs.allow_overflow
                    ORDER BY bs.position_row, bs.position_order
                """
                )
                db_stations = cur.fetchall()

                # Inline node coverage (avoids separate /api/stations/coverage call)
                cur.execute("SELECT * FROM v_station_node_coverage")
                coverage_rows = cur.fetchall()
                coverage_map = {c["station_code"]: c for c in coverage_rows}

                stations_data = []
                for station in db_stations:
                    agents = station["assigned_agents"] or []
                    primary_count = sum(1 for a in agents if a.get("assignment_type") == "primary")
                    backup_count = sum(1 for a in agents if a.get("assignment_type") == "backup")

                    cov = coverage_map.get(station["station_code"], {})
                    stations_data.append(
                        {
                            "id": station["id"],
                            "code": station["station_code"],
                            "name": station["station_name"],
                            "full_name": station["full_name"],
                            "description": station["description"],
                            "color": station["color"],
                            "icon": station["icon"],
                            "default_llm": station["default_llm"],
                            "modules": station["modules"] or [],
                            "position_row": station["position_row"],
                            "position_order": station["position_order"],
                            "assigned_agents": agents,
                            "primary_count": primary_count,
                            "backup_count": backup_count,
                            "total_agents": len(agents),
                            "max_primary": station.get("max_primary", 2),
                            "max_auxiliary": station.get("max_auxiliary", 1),
                            "allow_overflow": station.get("allow_overflow", True),
                            "status": "active",
                            "node_coverage": {
                                "total_nodes": cov.get("total_nodes", 0),
                                "primary_nodes": cov.get("primary_nodes", 0),
                                "backup_nodes": cov.get("backup_nodes", 0),
                            },
                        }
                    )

                return jsonify(
                    {
                        "success": True,
                        "stations": stations_data,
                        "total_stations": len(stations_data),
                        "coverage_summary": {
                            "total_stations": len(coverage_rows),
                            "stations_with_nodes": len([c for c in coverage_rows if c["total_nodes"] > 0]),
                            "total_assignments": sum(c["total_nodes"] for c in coverage_rows),
                        },
                    }
                )

        except Exception as e:
            logger.error(f"Error getting stations: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/modules/metadata", methods=["POST"])
    @login_required
    def get_modules_metadata():
        """Get metadata for a list of module names (icon, route, description)"""
        from module_registry import get_enabled_modules

        data = request.get_json() or {}
        module_names = data.get("modules", [])

        registry = {m.id: m for m in get_enabled_modules()}
        # Build name-to-module lookup for fuzzy matching
        name_lookup = {}
        for m in get_enabled_modules():
            name_lookup[m.name.lower()] = m
            name_lookup[m.id.lower()] = m
            for tag in m.tags:
                if tag.lower() not in name_lookup:
                    name_lookup[tag.lower()] = m

        results = []
        for name in module_names:
            mod = registry.get(name) or name_lookup.get(name.lower().replace(" ", "-")) or name_lookup.get(name.lower())
            if mod:
                results.append(
                    {
                        "id": mod.id,
                        "name": mod.name,
                        "icon": mod.icon,
                        "route": mod.route,
                        "description": mod.description,
                        "category": mod.category.value if hasattr(mod.category, "value") else str(mod.category),
                    }
                )
            else:
                results.append(
                    {
                        "id": name,
                        "name": name.replace("-", " ").replace("_", " ").title(),
                        "icon": "box",
                        "route": None,
                        "description": "",
                        "category": "unknown",
                    }
                )
        return jsonify({"success": True, "modules": results})

    @bp.route("/api/stations/<station_code>")
    @login_required
    def get_station_detail(station_code):
        """Get detailed info for a specific station"""
        station_code = station_code.upper()

        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Get station from database
                cur.execute(
                    """
                    SELECT id, station_code, station_name, full_name, description,
                           color, icon, default_llm, modules, position_row, position_order
                    FROM bridge_stations
                    WHERE station_code = %s AND is_active = TRUE
                """,
                    (station_code,),
                )
                station = cur.fetchone()

                if not station:
                    return (
                        jsonify({"success": False, "error": f"Station {station_code} not found"}),
                        404,
                    )

                # Get assigned agents with full details
                cur.execute(
                    """
                    SELECT a.id, a.name, a.first_name, a.last_name, a.title, a.avatar_url,
                           a.model, a.department, a.tier, a.status, a.worker_type,
                           sa.assignment_type, sa.shift_preference, sa.priority
                    FROM station_assignments sa
                    JOIN agents a ON sa.agent_id = a.id
                    WHERE sa.station_id = %s AND sa.is_active = TRUE
                    ORDER BY sa.priority
                """,
                    (station["id"],),
                )
                assigned_agents = cur.fetchall()

                return jsonify(
                    {
                        "success": True,
                        "station": {
                            "id": station["id"],
                            "code": station["station_code"],
                            "name": station["station_name"],
                            "full_name": station["full_name"],
                            "description": station["description"],
                            "color": station["color"],
                            "icon": station["icon"],
                            "default_llm": station["default_llm"],
                            "modules": station["modules"] or [],
                            "assigned_agents": assigned_agents,
                            "total_agents": len(assigned_agents),
                        },
                    }
                )

        except Exception as e:
            logger.error(f"Error getting station detail: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    def check_ollama_status(host, port):
        """Check if Ollama is running and responsive"""
        try:
            import time

            start = time.time()
            response = requests.get(f"http://{host}:{port}/api/tags", timeout=5)
            latency = int((time.time() - start) * 1000)

            if response.status_code == 200:
                return "online", latency
            else:
                return "degraded", latency
        except requests.exceptions.Timeout:
            return "timeout", None
        except requests.exceptions.ConnectionError:
            return "offline", None
        except Exception as e:
            logger.error(f"Error checking Ollama: {e}")
            return "error", None

    def get_ollama_models(host, port):
        """Get list of available Ollama models with sizes"""
        try:
            response = requests.get(f"http://{host}:{port}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return {model["name"]: model.get("size", 0) for model in data.get("models", [])}
        except Exception as e:
            logger.error(f"Error getting Ollama models: {e}")
        return {}

    # ============================================================================
    # STATION ACTIONS — DB-driven action registry for Bridge ACTN tab
    # ============================================================================

    @bp.route("/api/station-actions")
    @login_required
    def get_station_actions():
        """Return registered station actions, filtered by station_code or module_source."""
        try:
            station_code = request.args.get("station_code")
            module_source = request.args.get("module_source")

            with get_db_cursor(commit=False) as (conn, cur):
                if station_code:
                    # Support comma-separated station codes (zones map to multiple stations)
                    codes = [c.strip() for c in station_code.split(",") if c.strip()]
                    cur.execute(
                        """
                        SELECT id, action_key, station_code, module_source, label,
                               description, icon, color_class, sort_order,
                               http_method, endpoint_path, params_schema,
                               creates_job, job_type, requires_admin, test_config
                        FROM station_actions
                        WHERE station_code = ANY(%s) AND is_active = TRUE
                        ORDER BY sort_order, label
                        """,
                        (codes,),
                    )
                elif module_source:
                    cur.execute(
                        """
                        SELECT id, action_key, station_code, module_source, label,
                               description, icon, color_class, sort_order,
                               http_method, endpoint_path, params_schema,
                               creates_job, job_type, requires_admin, test_config
                        FROM station_actions
                        WHERE module_source = %s AND is_active = TRUE
                        ORDER BY sort_order, label
                        """,
                        (module_source,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, action_key, station_code, module_source, label,
                               description, icon, color_class, sort_order,
                               http_method, endpoint_path, params_schema,
                               creates_job, job_type, requires_admin, test_config
                        FROM station_actions
                        WHERE is_active = TRUE
                        ORDER BY station_code, sort_order, label
                        """
                    )

                actions = cur.fetchall()
                # Ensure params_schema is always a list
                for a in actions:
                    if a.get("params_schema") is None:
                        a["params_schema"] = []

            return jsonify({"success": True, "actions": actions, "count": len(actions)})
        except Exception as e:
            logger.error("station_actions error: %s", e)
            return jsonify({"success": True, "actions": [], "count": 0})

    # ---------------------------------------------------------------------------
    # Station action metrics (Project #109)
    # ---------------------------------------------------------------------------
    @bp.route("/api/bridge/stations/<station_code>/action-metrics")
    @login_required
    def get_station_action_metrics(station_code):
        """Aggregated action metrics for a station: execution count, avg duration,
        success rate, grouped by job_type. Sources: bridge_jobs + task_execution_log."""
        try:
            days = request.args.get("days", 30, type=int)
            days = min(max(days, 1), 365)

            with get_db_cursor(commit=False) as (conn, cur):
                # Bridge jobs metrics by job_type
                cur.execute(
                    """
                    SELECT job_type,
                           COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                           COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                           ROUND(AVG(EXTRACT(EPOCH FROM (completed_at - created_at)))
                                 FILTER (WHERE completed_at IS NOT NULL))::int AS avg_duration_s,
                           ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'completed')
                                 / NULLIF(COUNT(*), 0), 1) AS success_rate
                    FROM bridge_jobs
                    WHERE station_code = %s
                      AND created_at > NOW() - INTERVAL '1 day' * %s
                    GROUP BY job_type
                    ORDER BY total DESC
                    """,
                    (station_code, days),
                )
                job_metrics = cur.fetchall()

                # Task execution log metrics by task_type (more granular)
                cur.execute(
                    """
                    SELECT task_type,
                           COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE success = TRUE) AS completed,
                           COUNT(*) FILTER (WHERE success = FALSE) AS failed,
                           ROUND(AVG(duration_ms) FILTER (WHERE success = TRUE))::int AS avg_duration_ms,
                           ROUND(100.0 * COUNT(*) FILTER (WHERE success = TRUE)
                                 / NULLIF(COUNT(*), 0), 1) AS success_rate,
                           SUM(tokens_used) AS total_tokens
                    FROM task_execution_log
                    WHERE station_code = %s
                      AND created_at > NOW() - INTERVAL '1 day' * %s
                    GROUP BY task_type
                    ORDER BY total DESC
                    """,
                    (station_code, days),
                )
                task_metrics = cur.fetchall()

                # Overall station summary
                cur.execute(
                    """
                    SELECT COUNT(*) AS total_jobs,
                           COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                           COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                           ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'completed')
                                 / NULLIF(COUNT(*), 0), 1) AS success_rate
                    FROM bridge_jobs
                    WHERE station_code = %s
                      AND created_at > NOW() - INTERVAL '1 day' * %s
                    """,
                    (station_code, days),
                )
                summary = cur.fetchone()

            return jsonify(
                {
                    "success": True,
                    "station_code": station_code,
                    "period_days": days,
                    "summary": summary,
                    "job_metrics": job_metrics,
                    "task_metrics": task_metrics,
                }
            )
        except Exception as e:
            logger.error("action-metrics error for %s: %s", station_code, e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ---------------------------------------------------------------------------
    # Benchmark endpoints (Project #110)
    # ---------------------------------------------------------------------------
    @bp.route("/api/benchmarks/start", methods=["POST"])
    @login_required
    def start_benchmark():
        """Start a benchmark run for an action_key."""
        try:
            from services.benchmark_service import start_benchmark as _start

            data = request.get_json() or {}
            action_key = data.get("action_key")
            if not action_key:
                return jsonify({"success": False, "error": "action_key required"}), 400

            user_id = current_user.id if current_user.is_authenticated else None
            include_contractors = data.get("include_contractors", False)
            result = _start(action_key, user_id=user_id, include_contractors=include_contractors)
            status_code = 200 if result.get("success") else 400
            return jsonify(result), status_code
        except Exception as e:
            logger.error("benchmark start error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/benchmarks/active")
    @login_required
    def get_active_benchmark():
        """Return the currently running benchmark, if any."""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT id, action_key, station_code, total_agents,
                           completed_agents, failed_agents, status, started_at
                    FROM action_benchmark_runs
                    WHERE status = 'running'
                    ORDER BY started_at DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"success": True, "active": False})
                return jsonify(
                    {
                        "success": True,
                        "active": True,
                        "run": {
                            "id": row["id"],
                            "action_key": row["action_key"],
                            "station_code": row["station_code"],
                            "total_agents": row["total_agents"],
                            "completed_agents": row["completed_agents"],
                            "failed_agents": row["failed_agents"],
                            "status": row["status"],
                            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                        },
                    }
                )
        except Exception as e:
            logger.error("active benchmark check error: %s", e)
            return jsonify({"success": True, "active": False})

    @bp.route("/api/benchmarks/<int:run_id>/status")
    @login_required
    def get_benchmark_status(run_id):
        """Lightweight progress poll — no pool checkout, direct connection."""
        import psycopg2

        conn = None
        try:
            conn = psycopg2.connect(
                host=os.environ.get("DB_HOST", "192.168.1.200"),
                port=os.environ.get("DB_PORT", "5432"),
                database=os.environ.get("DB_NAME", "archie"),
                user=os.environ.get("DB_USER", "archie"),
                password=os.environ.get("DB_PASSWORD", ""),
            )
            cur = conn.cursor()
            cur.execute(
                "SELECT completed_agents, failed_agents, total_agents, status "
                "FROM action_benchmark_runs WHERE id = %s",
                (run_id,),
            )
            row = cur.fetchone()
            cur.close()
            if not row:
                return jsonify({"success": False, "error": "Not found"}), 404
            return jsonify(
                {
                    "success": True,
                    "run": {
                        "completed_agents": row[0],
                        "failed_agents": row[1],
                        "total_agents": row[2],
                        "status": row[3],
                    },
                }
            )
        except Exception as e:
            return jsonify({"success": True, "run": {"status": "running", "completed_agents": 0, "failed_agents": 0}})
        finally:
            if conn:
                try:
                    conn.close()
                except Exception as e:
                    logger.warning("Failed to close DB connection: %s", e)

    @bp.route("/api/benchmarks/<int:run_id>")
    @login_required
    def get_benchmark(run_id):
        """Get benchmark run info + ranked leaderboard."""
        try:
            from services.benchmark_service import get_benchmark_results

            data = get_benchmark_results(run_id)
            if not data:
                return jsonify({"success": False, "error": "Run not found"}), 404

            # Serialize datetimes
            run = data["run"]
            for key in ("started_at", "completed_at"):
                if run.get(key):
                    run[key] = run[key].isoformat() if hasattr(run[key], "isoformat") else str(run[key])

            for r in data["results"]:
                if r.get("tested_at"):
                    r["tested_at"] = (
                        r["tested_at"].isoformat() if hasattr(r["tested_at"], "isoformat") else str(r["tested_at"])
                    )

            return jsonify({"success": True, **data})
        except Exception as e:
            logger.error("benchmark get error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/benchmarks/<int:run_id>/skill-updates")
    @login_required
    def get_benchmark_skill_updates(run_id):
        """Get skill adjustments made by a specific benchmark run."""
        try:
            from services.benchmark_service import get_skill_updates

            data = get_skill_updates(run_id)
            return jsonify({"success": True, **(data or {})})
        except Exception as e:
            logger.error("benchmark skill-updates error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/benchmarks/<int:run_id>/pick", methods=["POST"])
    @login_required
    def set_benchmark_pick(run_id):
        """Mark an agent as the human-picked best for a benchmark run."""
        try:
            data = request.get_json(force=True)
            agent_name = data.get("agent_name")
            if not agent_name:
                return jsonify({"success": False, "error": "agent_name required"}), 400

            with get_db_cursor() as (conn, cur):
                # Clear previous picks for this run
                cur.execute(
                    "UPDATE action_benchmark_results SET is_human_pick = FALSE WHERE run_id = %s",
                    (run_id,),
                )
                # Set the new pick
                cur.execute(
                    "UPDATE action_benchmark_results SET is_human_pick = TRUE WHERE run_id = %s AND agent_name = %s",
                    (run_id, agent_name),
                )

                # Also boost picked agent's skill proficiency to 5 (Expert)
                try:
                    cur.execute("SELECT test_config FROM action_benchmark_runs WHERE id = %s", (run_id,))
                    row = cur.fetchone()
                    if row:
                        import json as _json

                        tc = row.get("test_config") if isinstance(row, dict) else row[0]
                        if isinstance(tc, str):
                            tc = _json.loads(tc)
                        capability = (tc or {}).get("capability", "general")
                        cur.execute("SELECT skill_name FROM capability_skill_map WHERE capability = %s", (capability,))
                        mapping = cur.fetchone()
                        skill_name = (
                            (mapping.get("skill_name") if isinstance(mapping, dict) else mapping[0])
                            if mapping
                            else capability
                        )
                        cur.execute(
                            "SELECT agent_id FROM action_benchmark_results WHERE run_id = %s AND agent_name = %s",
                            (run_id, agent_name),
                        )
                        ar = cur.fetchone()
                        if ar:
                            agent_id = ar.get("agent_id") if isinstance(ar, dict) else ar[0]
                            cur.execute(
                                """INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, updated_at)
                                VALUES (%s, %s, 'human_pick', %s, NOW())
                                ON CONFLICT (agent_id, skill_name) DO UPDATE
                                    SET proficiency_level = EXCLUDED.proficiency_level, updated_at = NOW()""",
                                (agent_id, skill_name, 5),
                            )
                except Exception as e:
                    logger.warning("Human pick skill boost failed: %s", e)

            return jsonify({"success": True, "agent_name": agent_name})
        except Exception as e:
            logger.error("set_benchmark_pick error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/benchmarks/latest/<path:action_key>")
    @login_required
    def get_latest_benchmark(action_key):
        """Get the most recent completed benchmark for an action."""
        try:
            from services.benchmark_service import get_latest_benchmark as _latest

            data = _latest(action_key)
            if not data:
                return jsonify({"success": False, "error": "No benchmarks found"}), 404

            # Serialize datetimes
            run = data["run"]
            for key in ("started_at", "completed_at"):
                if run.get(key):
                    run[key] = run[key].isoformat() if hasattr(run[key], "isoformat") else str(run[key])

            for r in data["results"]:
                if r.get("tested_at"):
                    r["tested_at"] = (
                        r["tested_at"].isoformat() if hasattr(r["tested_at"], "isoformat") else str(r["tested_at"])
                    )

            return jsonify({"success": True, **data})
        except Exception as e:
            logger.error("benchmark latest error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ---------------------------------------------------------------------------
    # Benchmark Recommendations
    # ---------------------------------------------------------------------------

    @bp.route("/api/benchmarks/recommendations")
    @login_required
    def get_recommendations():
        """List benchmark recommendations (optional ?station=X&status=pending)."""
        try:
            from services.benchmark_service import get_station_recommendations

            station = request.args.get("station")
            status = request.args.get("status", "pending")
            recs = get_station_recommendations(station_code=station, status=status)
            return jsonify({"success": True, "recommendations": recs})
        except Exception as e:
            logger.error("get recommendations error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/benchmarks/recommendations/generate", methods=["POST"])
    @login_required
    def generate_recommendations():
        """Trigger recommendation generation for all or a specific station."""
        try:
            from services.benchmark_service import generate_station_recommendations

            data = request.get_json(force=True) if request.is_json else {}
            station = data.get("station_code")
            recs = generate_station_recommendations(station_code=station)
            return jsonify(
                {
                    "success": True,
                    "generated": len(recs),
                    "recommendations": recs,
                }
            )
        except Exception as e:
            logger.error("generate recommendations error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/benchmarks/recommendations/<int:rec_id>/resolve", methods=["POST"])
    @login_required
    def resolve_recommendation_route(rec_id):
        """Approve or reject a recommendation. Body: {approved: bool}."""
        try:
            from services.benchmark_service import resolve_recommendation

            data = request.get_json(force=True)
            approved = data.get("approved", False)
            user_id = current_user.id if current_user.is_authenticated else None
            result = resolve_recommendation(rec_id, approved=approved, user_id=user_id)
            status_code = 200 if result.get("success") else 400
            return jsonify(result), status_code
        except Exception as e:
            logger.error("resolve recommendation error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/benchmarks/station-summary")
    @login_required
    def get_benchmark_station_summary():
        """Per-station summary: current agent, top 3, human pick, latest date."""
        try:
            from services.benchmark_service import get_station_summary

            summaries = get_station_summary()
            return jsonify({"success": True, "stations": summaries})
        except Exception as e:
            logger.error("station summary error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/benchmarks/score-matrix")
    @login_required
    def get_score_matrix_route():
        """Return agent×station score grid for heatmap display."""
        try:
            from services.benchmark_service import get_score_matrix

            matrix = get_score_matrix()
            return jsonify({"success": True, **matrix})
        except Exception as e:
            logger.error("score matrix error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/benchmarks/placement/generate", methods=["POST"])
    @login_required
    def generate_placement_route():
        """Generate optimal agent placement plan (not auto-applied)."""
        try:
            from services.benchmark_service import generate_optimal_placement

            plan = generate_optimal_placement()
            return jsonify({"success": True, **plan})
        except Exception as e:
            logger.error("generate placement error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/benchmarks/placement/apply", methods=["POST"])
    @login_required
    def apply_placement_route():
        """Apply an approved placement plan."""
        try:
            from services.benchmark_service import apply_placement

            data = request.get_json(force=True)
            user_id = current_user.id if current_user.is_authenticated else None
            result = apply_placement(data, user_id=user_id)
            status_code = 200 if result.get("success") else 400
            return jsonify(result), status_code
        except Exception as e:
            logger.error("apply placement error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/resources")
    @login_required
    def get_bridge_resources():
        """System resource overview from host monitor + Ollama model roster.

        Pulls real GPU data from host_monitor_data.json (same source as System Ops),
        shows all available vs loaded Ollama models, Ollama config limits, and
        capacity analysis for how many more models can fit in RAM.
        """
        try:
            import psutil

            # ── Real GPU data from host monitor ──
            gpu_data = {
                "name": "Unknown",
                "vram_total_mb": 0,
                "vram_used_mb": 0,
                "utilization_pct": 0,
                "temperature": None,
                "driver": None,
            }
            try:
                host_monitor_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                    "host_monitor_data.json",
                )
                with open(host_monitor_path) as f:
                    import json as _json

                    hm = _json.load(f)
                gpus = hm.get("gpu", [])
                if gpus and isinstance(gpus, list) and len(gpus) > 0:
                    g = gpus[0]
                    gpu_data = {
                        "name": g.get("model", "Unknown"),
                        "vram_total_mb": g.get("vram_total_mb", 0),
                        "vram_used_mb": g.get("vram_used_mb", 0),
                        "utilization_pct": g.get("utilization_percent", 0),
                        "temperature": g.get("temperature"),
                        "driver": g.get("driver"),
                    }
                # CPU model from host monitor
                cpu_model = hm.get("cpu", {}).get("model", "")
            except Exception:
                cpu_model = ""

            # ── Ollama: loaded models ──
            loaded_models = _get_cached_ollama_ps()
            ollama_loaded = []
            model_ram_used = 0
            model_vram_used = 0
            for m in loaded_models:
                size_bytes = m.get("size", 0)
                vram_bytes = m.get("size_vram", 0)
                ram_bytes = size_bytes - vram_bytes
                device = "gpu" if vram_bytes and vram_bytes > 0 else "cpu"
                if device == "gpu":
                    model_vram_used += vram_bytes
                model_ram_used += max(ram_bytes, 0)
                ollama_loaded.append(
                    {
                        "name": m.get("name", "unknown"),
                        "size_gb": round(size_bytes / (1024**3), 1) if size_bytes else 0,
                        "ram_gb": round(max(ram_bytes, 0) / (1024**3), 1),
                        "vram_gb": round(vram_bytes / (1024**3), 1) if vram_bytes else 0,
                        "device": device,
                    }
                )

            # ── Ollama: all available models ──
            all_models, model_count = _get_cached_ollama_tags()
            ollama_available = []
            unloaded_total_gb = 0
            loaded_names = {m["name"] for m in ollama_loaded}
            for m in all_models:
                name = m.get("name", "unknown")
                size_gb = round(m.get("size", 0) / (1024**3), 1)
                is_cloud = ":cloud" in name
                is_loaded = name in loaded_names
                ollama_available.append(
                    {
                        "name": name,
                        "size_gb": size_gb,
                        "loaded": is_loaded,
                        "cloud": is_cloud,
                    }
                )
                if not is_loaded and not is_cloud and size_gb > 0:
                    unloaded_total_gb += size_gb

            # ── System stats ──
            cpu_pct = psutil.cpu_percent(interval=0.1)
            ram = psutil.virtual_memory()
            ram_available_gb = round(ram.available / (1024**3), 1)

            # ── Ollama config (read from systemd override on host) ──
            ollama_config = {
                "max_loaded_models": 20,
                "keep_alive": "24h",
                "num_parallel": 4,
                "num_cpu": psutil.cpu_count(),
                "cpu_pct": 70,
            }
            try:
                conf_path = "/etc/systemd/system/ollama.service.d/override.conf"
                if os.path.exists(conf_path):
                    with open(conf_path) as _f:
                        for line in _f:
                            if "OLLAMA_MAX_LOADED_MODELS" in line:
                                val = line.split("=")[-1].strip().rstrip('"')
                                ollama_config["max_loaded_models"] = int(val)
                            elif "OLLAMA_KEEP_ALIVE" in line:
                                ollama_config["keep_alive"] = line.split("=")[-1].strip().rstrip('"')
                            elif "OLLAMA_NUM_PARALLEL" in line:
                                val = line.split("=")[-1].strip().rstrip('"')
                                ollama_config["num_parallel"] = int(val)
                            elif "OLLAMA_NUM_CPU" in line:
                                val = line.split("=")[-1].strip().rstrip('"')
                                ollama_config["num_cpu"] = int(val)
                                total = psutil.cpu_count()
                                ollama_config["cpu_pct"] = round(int(val) / total * 100) if total else 70
            except Exception as e:
                logger.warning("Failed to parse Ollama service config: %s", e)

            # ── Capacity analysis ──
            local_unloaded = [m for m in ollama_available if not m["loaded"] and not m["cloud"] and m["size_gb"] > 0]
            # Sort by size ascending (load small models first)
            local_unloaded.sort(key=lambda m: m["size_gb"])
            can_fit = []
            remaining_ram = ram_available_gb
            remaining_slots = ollama_config["max_loaded_models"] - len(ollama_loaded)
            for m in local_unloaded:
                if remaining_slots <= 0:
                    break
                if m["size_gb"] <= remaining_ram:
                    can_fit.append(m["name"])
                    remaining_ram -= m["size_gb"]
                    remaining_slots -= 1

            result = {
                "gpu": gpu_data,
                "cpu": {
                    "model": cpu_model,
                    "cores": psutil.cpu_count(),
                    "usage_pct": round(cpu_pct, 1),
                },
                "ram": {
                    "total_gb": round(ram.total / (1024**3), 1),
                    "used_gb": round(ram.used / (1024**3), 1),
                    "available_gb": ram_available_gb,
                    "pct": ram.percent,
                    "models_ram_gb": round(model_ram_used / (1024**3), 1),
                },
                "ollama_config": ollama_config,
                "ollama_loaded": ollama_loaded,
                "ollama_available": ollama_available,
                "capacity": {
                    "loaded_count": len(ollama_loaded),
                    "available_count": model_count,
                    "local_count": sum(1 for m in ollama_available if not m["cloud"]),
                    "cloud_count": sum(1 for m in ollama_available if m["cloud"]),
                    "max_slots": ollama_config["max_loaded_models"],
                    "free_slots": max(0, ollama_config["max_loaded_models"] - len(ollama_loaded)),
                    "unloaded_total_gb": round(unloaded_total_gb, 1),
                    "ram_available_gb": ram_available_gb,
                    "can_fit_more": remaining_slots > 0 and ram_available_gb > 1,
                    "could_load": can_fit,
                },
            }
            return jsonify({"success": True, **result})
        except Exception as e:
            logger.error("resources error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/stations/<station_code>/dispatch")
    @login_required
    def get_station_dispatch(station_code):
        """Get recent dispatch activity for a station using capability_station attribution."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT tel.id, 'task' AS source,
                           COALESCE(NULLIF(a.first_name, ''), a.name, tel.agent_name) AS agent_name,
                           tel.module_source, tel.task_type, tel.capability,
                           tel.model_used, tel.success, tel.created_at,
                           tel.duration_ms
                    FROM task_execution_log tel
                    LEFT JOIN agents a ON a.id = tel.agent_id
                    WHERE (
                        tel.request_metadata->>'capability_station' = %s
                        OR (tel.request_metadata->>'capability_station' IS NULL AND tel.station_code = %s)
                    )
                    ORDER BY tel.created_at DESC
                    LIMIT 20
                """,
                    (station_code, station_code),
                )
                events = cur.fetchall()
                for ev in events:
                    ev["created_at"] = ev["created_at"].isoformat() + "Z" if ev["created_at"] else None
                return jsonify(events)
        except Exception as e:
            logger.error("station_dispatch error: %s", e)
            return jsonify([])

    @bp.route("/api/stations/<station_code>/metrics")
    @login_required
    def get_station_metrics(station_code):
        """Get performance metrics for a station (24h window).

        Uses task_execution_log with capability_station metadata to attribute
        work to the station it was done FOR — including cross-station helpers
        and cloud contractors.
        """
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                # Query task_execution_log using capability_station metadata
                # for correct attribution of cross-station + contractor work.
                # Fallback to station_code for older entries without the field.
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS total_requests,
                        COALESCE(AVG(duration_ms), 0)::int AS avg_response_ms,
                        COALESCE(SUM(tokens_used), 0) AS total_tokens,
                        CASE WHEN COUNT(*) > 0
                            THEN ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END) / COUNT(*), 1)
                            ELSE 0
                        END AS success_rate
                    FROM task_execution_log
                    WHERE (
                        request_metadata->>'capability_station' = %s
                        OR (request_metadata->>'capability_station' IS NULL AND station_code = %s)
                    )
                    AND created_at > NOW() - INTERVAL '24 hours'
                    """,
                    (station_code, station_code),
                )
                stats = cur.fetchone()

                return jsonify(
                    {
                        "success": True,
                        "metrics": {
                            "requests_24h": stats["total_requests"],
                            "avg_response_ms": stats["avg_response_ms"],
                            "tokens_24h": int(stats["total_tokens"]),
                            "success_rate": float(stats["success_rate"]),
                        },
                    }
                )
        except Exception as e:
            logger.error(f"Error getting station metrics: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/stations/<station_code>/module-preview/<module_id>")
    @login_required
    def get_module_preview(station_code, module_id):
        """Get preview data for a module in station context"""
        from module_registry import get_module_by_id

        mod = get_module_by_id(module_id)
        if not mod:
            return jsonify({"success": False, "error": "Module not found"}), 404

        result = {
            "id": mod.id,
            "name": mod.name,
            "icon": mod.icon,
            "route": mod.route,
            "description": mod.description,
            "version": mod.version,
            "category": mod.category.value if hasattr(mod.category, "value") else str(mod.category),
            "tags": mod.tags,
            "stats": {},
        }

        # Module-specific stat queries (best-effort)
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                if module_id == "email-manager":
                    cur.execute(
                        "SELECT COUNT(*) AS count FROM email_messages WHERE created_at > NOW() - INTERVAL '7 days'"
                    )
                    r = cur.fetchone()
                    if r:
                        result["stats"]["emails_7d"] = r["count"]
                elif module_id == "backup-manager":
                    cur.execute("SELECT COUNT(*) AS count FROM backup_history WHERE status = 'completed'")
                    r = cur.fetchone()
                    if r:
                        result["stats"]["completed_backups"] = r["count"]
                elif module_id == "bridge":
                    cur.execute(
                        "SELECT COUNT(*) AS count FROM task_execution_log WHERE created_at > NOW() - INTERVAL '24 hours'"
                    )
                    r = cur.fetchone()
                    if r:
                        result["stats"]["interactions_24h"] = r["count"]
                elif module_id == "consciousness":
                    cur.execute("SELECT COUNT(*) AS count FROM knowledge_base WHERE status = 'active'")
                    r = cur.fetchone()
                    if r:
                        result["stats"]["active_entries"] = r["count"]
        except Exception:
            pass  # Stats are optional — don't fail if table doesn't exist

        return jsonify({"success": True, "module": result})

    @bp.route("/api/agents/<int:agent_id>/executions")
    @login_required
    def agent_executions(agent_id):
        """Recent execution history for a specific agent via orchestration_steps."""
        limit = request.args.get("limit", 10, type=int)
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                # Sessions where this agent participated (via steps)
                cur.execute(
                    """
                    SELECT DISTINCT ON (os.id)
                           os.id, os.session_id, os.status,
                           os.total_duration_ms, os.total_steps,
                           os.created_at, os.completed_at,
                           st.model_used,
                           (SELECT COUNT(*) FROM orchestration_steps s2
                            WHERE s2.session_id = os.id) AS step_count
                    FROM orchestration_sessions os
                    JOIN orchestration_steps st ON st.session_id = os.id
                        AND st.agent_id = %s
                    ORDER BY os.id DESC, st.id DESC
                    LIMIT %s
                """,
                    (agent_id, limit),
                )
                rows = cur.fetchall()
                for r in rows:
                    r["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
                    r["completed_at"] = r["completed_at"].isoformat() if r.get("completed_at") else None
                    # Convert UUID to string for JSON serialization
                    if r.get("session_id"):
                        r["session_id"] = str(r["session_id"])
                return jsonify(rows)
        except Exception as e:
            logger.error("agent_executions error: %s", e)
            return jsonify([])

    @bp.route("/api/agents/<int:agent_id>/emotional-state")
    @login_required
    def agent_emotional_state_detail(agent_id):
        """Current emotional state for a specific agent."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT current_mood, mood_intensity, stress_level, energy_level,
                           previous_mood, trigger_event, timestamp, metadata
                    FROM agent_emotional_state
                    WHERE agent_id = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                """,
                    (agent_id,),
                )
                state = cur.fetchone()
                # Also get last rest cycle
                cur.execute(
                    """
                    SELECT rest_type, started_at, ended_at, reason, initiated_by
                    FROM agent_rest_cycles
                    WHERE agent_id = %s
                    ORDER BY started_at DESC
                    LIMIT 1
                """,
                    (agent_id,),
                )
                rest = cur.fetchone()
                if state:
                    state["timestamp"] = state["timestamp"].isoformat() if state.get("timestamp") else None
                if rest:
                    rest["started_at"] = rest["started_at"].isoformat() if rest.get("started_at") else None
                    rest["ended_at"] = rest["ended_at"].isoformat() if rest.get("ended_at") else None
                return jsonify({"emotional_state": state, "last_rest": rest})
        except Exception as e:
            logger.error("agent_emotional_state_detail error: %s", e)
            return jsonify({"emotional_state": None, "last_rest": None})

    _profile_cache = {}  # agent_id -> (timestamp, response_dict)
    _profile_cache_ttl = 30  # seconds

    @bp.route("/api/agents/<int:agent_id>/profile")
    @login_required
    def agent_profile(agent_id):
        """Aggregated agent profile: details, skills, emotional state, performance, memory."""
        # Server-side cache: return cached if fresh
        import time as _time

        cached = _profile_cache.get(agent_id)
        if cached and (_time.time() - cached[0]) < _profile_cache_ttl:
            return jsonify(cached[1])

        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Agent details
                cur.execute(
                    """
                    SELECT a.id, a.name, a.display_name, a.first_name, a.last_name, a.title,
                           a.department, a.bio, a.model, a.status, a.avatar_url,
                           a.pronouns, a.worker_type, a.cost_tier, a.capabilities,
                           a.system_prompt, a.avatar_generation_prompt,
                           a.communication_style, a.temperature, a.shift_state,
                           a.tier, a.is_cloneable, a.image_model,
                           a.created_at, a.last_used,
                           bs.station_code, bs.station_name, bs.color as station_color
                    FROM agents a
                    LEFT JOIN station_assignments sa ON sa.agent_id = a.id AND sa.is_active = TRUE
                    LEFT JOIN bridge_stations bs ON bs.id = sa.station_id
                    WHERE a.id = %s
                """,
                    (agent_id,),
                )
                agent = cur.fetchone()
                if not agent:
                    return jsonify({"success": False, "error": "Agent not found"}), 404

                for k in ["created_at", "last_used"]:
                    if agent.get(k):
                        agent[k] = agent[k].isoformat()

                # Skills (with degradation count from learning log — LATERAL to avoid duplicates)
                cur.execute(
                    """
                    SELECT s.id, s.skill_name, s.skill_category, s.proficiency_level, s.notes,
                           COALESCE(ll.degradation_count, 0) as degradation_count
                    FROM agent_skills s
                    LEFT JOIN LATERAL (
                        SELECT degradation_count
                        FROM agent_learning_log
                        WHERE agent_id = s.agent_id AND skill_name = s.skill_name
                        ORDER BY confidence DESC
                        LIMIT 1
                    ) ll ON true
                    WHERE s.agent_id = %s
                    ORDER BY s.proficiency_level DESC, s.skill_name
                """,
                    (agent_id,),
                )
                skills = cur.fetchall()

                # Emotional state (latest)
                cur.execute(
                    """
                    SELECT current_mood, mood_intensity, stress_level, energy_level,
                           trigger_event, timestamp
                    FROM agent_emotional_state WHERE agent_id = %s
                    ORDER BY timestamp DESC LIMIT 1
                """,
                    (agent_id,),
                )
                emotional = cur.fetchone()
                if emotional and emotional.get("timestamp"):
                    emotional["timestamp"] = emotional["timestamp"].isoformat()

                # Performance (24h)
                cur.execute(
                    """
                    SELECT COUNT(*) as tasks_24h,
                           COUNT(*) FILTER (WHERE success = TRUE) as completed,
                           COUNT(*) FILTER (WHERE success = FALSE) as failed,
                           COALESCE(AVG(duration_ms), 0) as avg_duration_ms
                    FROM task_execution_log
                    WHERE agent_id = %s AND created_at >= NOW() - INTERVAL '24 hours'
                """,
                    (agent_id,),
                )
                perf = cur.fetchone()

                # Recent tasks (last 10)
                cur.execute(
                    """
                    SELECT id, module_source, task_type, capability, model_used,
                           duration_ms, success, error_message, created_at
                    FROM task_execution_log
                    WHERE agent_id = %s
                    ORDER BY created_at DESC LIMIT 10
                """,
                    (agent_id,),
                )
                recent = cur.fetchall()
                for r in recent:
                    if r.get("created_at"):
                        r["created_at"] = r["created_at"].isoformat()

                # Memory highlights (top 5 by importance)
                cur.execute(
                    """
                    SELECT memory_type, content, importance_score, source_module, created_at
                    FROM agent_memory
                    WHERE agent_id = %s AND is_deleted = FALSE
                    ORDER BY importance_score DESC NULLS LAST
                    LIMIT 5
                """,
                    (agent_id,),
                )
                memories = cur.fetchall()
                for m in memories:
                    if m.get("created_at"):
                        m["created_at"] = m["created_at"].isoformat()

                # Voice profile (active)
                cur.execute(
                    """
                    SELECT profile_name, engine, language, speaker
                    FROM agent_voice_profiles
                    WHERE agent_id = %s AND is_active = true
                    LIMIT 1
                """,
                    (agent_id,),
                )
                voice = cur.fetchone()

                # Emotional history (last 10 entries)
                cur.execute(
                    """
                    SELECT current_mood, mood_intensity, energy_level, stress_level,
                           trigger_event, timestamp
                    FROM agent_emotional_state
                    WHERE agent_id = %s ORDER BY timestamp DESC LIMIT 10
                """,
                    (agent_id,),
                )
                emotional_history = cur.fetchall()
                for eh in emotional_history:
                    if eh.get("timestamp"):
                        eh["timestamp"] = eh["timestamp"].isoformat()

                # Identity traits
                cur.execute(
                    """
                    SELECT identity_key, identity_value, confidence
                    FROM agent_identity WHERE agent_id = %s ORDER BY identity_key
                """,
                    (agent_id,),
                )
                identity = cur.fetchall()

                # Rest cycles (last 5)
                cur.execute(
                    """
                    SELECT rest_type, started_at, ended_at, reason,
                           stress_at_start, energy_at_start
                    FROM agent_rest_cycles WHERE agent_id = %s
                    ORDER BY started_at DESC LIMIT 5
                """,
                    (agent_id,),
                )
                rest_cycles = cur.fetchall()
                for rc in rest_cycles:
                    for k in ["started_at", "ended_at"]:
                        if rc.get(k):
                            rc[k] = rc[k].isoformat()

                # Performance rankings (top 5 capabilities)
                cur.execute(
                    """
                    SELECT capability, rank_score, rank_position,
                           tasks_completed, success_rate, sample_size
                    FROM agent_performance_rankings
                    WHERE agent_id = %s
                    ORDER BY rank_score DESC LIMIT 5
                """,
                    (agent_id,),
                )
                rankings = cur.fetchall()
                for rk in rankings:
                    for k in ["rank_score", "success_rate"]:
                        if rk.get(k) is not None:
                            rk[k] = float(rk[k])

                # Shift history (last 10 from agent_rotation_log)
                cur.execute(
                    """
                    SELECT rl.shift_state, rl.started_at, rl.ended_at,
                           rl.tasks_completed, rl.tasks_failed, rl.reason,
                           bs.station_code,
                           ra.name as replaced_by_name
                    FROM agent_rotation_log rl
                    LEFT JOIN bridge_stations bs ON bs.id = rl.station_id
                    LEFT JOIN agents ra ON ra.id = rl.replaced_by
                    WHERE rl.agent_id = %s
                    ORDER BY rl.started_at DESC LIMIT 10
                """,
                    (agent_id,),
                )
                shift_history = cur.fetchall()
                for sh in shift_history:
                    for k in ["started_at", "ended_at"]:
                        if sh.get(k):
                            sh[k] = sh[k].isoformat()

                # Build portrait paths from first_name
                first = (agent.get("first_name") or agent.get("name") or "").lower()
                # Use avatar_url from DB if set, fall back to SVG
                avatar = agent.get("avatar_url") or f"/static/avatars/{first}.svg"
                portraits = {
                    "portrait": avatar,
                    "avatar": avatar,
                    "icon": avatar,
                }

                # Portrait variants from agent_portraits table
                cur.execute(
                    """
                    SELECT id, variant_name, canonical_image_path, is_primary,
                           benchmark_score, benchmark_notes, approved, style_tags, face_seed
                    FROM agent_portraits
                    WHERE agent_id = %s
                    ORDER BY is_primary DESC, variant_name
                """,
                    (agent_id,),
                )
                portrait_variants = cur.fetchall()
                for pv in portrait_variants:
                    for k in ["benchmark_score"]:
                        if pv.get(k) is not None:
                            pv[k] = float(pv[k])

                # Bridge jobs benchmark (uses agent code name, not id)
                agent_code_name = agent.get("name") or ""
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total_jobs,
                        COUNT(*) FILTER (WHERE status = 'completed') as completed_jobs,
                        COUNT(*) FILTER (WHERE status = 'failed') as failed_jobs,
                        ROUND(AVG(EXTRACT(EPOCH FROM (completed_at - created_at)))::numeric, 1) as avg_duration_seconds,
                        ROUND((COUNT(*) FILTER (WHERE status = 'completed')::numeric / NULLIF(COUNT(*), 0) * 100), 1) as success_rate
                    FROM bridge_jobs
                    WHERE agent_name = %s
                """,
                    (agent_code_name,),
                )
                benchmark_row = cur.fetchone()
                benchmark = None
                if benchmark_row and benchmark_row.get("total_jobs", 0) > 0:
                    benchmark = {
                        "total_jobs": benchmark_row["total_jobs"],
                        "completed_jobs": benchmark_row["completed_jobs"],
                        "failed_jobs": benchmark_row["failed_jobs"],
                        "avg_duration_seconds": float(benchmark_row["avg_duration_seconds"] or 0),
                        "success_rate": float(benchmark_row["success_rate"] or 0),
                    }

                result = {
                    "success": True,
                    "agent": agent,
                    "skills": skills,
                    "emotional_state": emotional,
                    "emotional_history": emotional_history,
                    "identity": identity,
                    "voice": voice,
                    "rest_cycles": rest_cycles,
                    "rankings": rankings,
                    "shift_history": shift_history,
                    "portraits": portraits,
                    "portrait_variants": portrait_variants,
                    "benchmark": benchmark,
                    "performance_24h": {
                        "tasks": perf["tasks_24h"],
                        "completed": perf["completed"],
                        "failed": perf["failed"],
                        "avg_duration_ms": round(float(perf["avg_duration_ms"]), 1),
                    },
                    "recent_tasks": recent,
                    "memories": memories,
                }
                _profile_cache[agent_id] = (_time.time(), result)
                return jsonify(result)

        except Exception as e:
            logger.error("agent_profile error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # --- Agent Portrait Generation (Multi-GPU Fan-Out) ---

    @bp.route("/api/agents/<int:agent_id>/generate-portrait", methods=["POST"])
    @login_required
    def generate_agent_portrait(agent_id):
        """Fan-out portrait generation across all available ComfyUI hosts.

        Generates variants in parallel on each GPU, stores all with benchmark
        data in agent_portraits. First successful result becomes active avatar.
        """
        import os
        import shutil
        import threading
        import time as _time
        import uuid

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "SELECT name, avatar_generation_prompt FROM agents WHERE id = %s",
                    (agent_id,),
                )
                agent = cur.fetchone()
                if not agent:
                    return jsonify({"success": False, "error": "Agent not found"}), 404

                prompt = (request.get_json() or {}).get("prompt") or agent["avatar_generation_prompt"]
                if not prompt:
                    return jsonify({"success": False, "error": "No avatar prompt"}), 400

                agent_name = agent["name"].lower()
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                portraits_dir = os.path.join(base_dir, "static", "media", "portraits")
                os.makedirs(portraits_dir, exist_ok=True)

            # Discover all ComfyUI hosts
            from ai_bridge.comfyui_service import ComfyUIService

            hosts = []
            # Hub ComfyUI
            hub_host = os.getenv("COMFYUI_HOST", "http://archie_comfyui:8188")
            hub_svc = ComfyUIService(host=hub_host)
            if hub_svc.is_healthy:
                hub_models = hub_svc.get_models().get("installed", [])
                hosts.append(
                    {
                        "url": hub_host,
                        "name": "hub",
                        "gpu_model": "Quadro M4000",
                        "models": hub_models,
                        "vram_gb": 8,
                    }
                )

            # Fleet nodes with ComfyUI
            try:
                from ai_bridge.node_router import get_nodes_with_service

                nodes = get_nodes_with_service("comfyui")
                for n in nodes:
                    hostname = n.get("hostname") or n.get("vpn_ip")
                    port = n.get("port", 8188)
                    if not hostname:
                        continue
                    node_url = f"http://{hostname}:{port}"
                    node_svc = ComfyUIService(host=node_url)
                    if node_svc.is_healthy:
                        node_models = node_svc.get_models().get("installed", [])
                        hosts.append(
                            {
                                "url": node_url,
                                "name": hostname,
                                "gpu_model": n.get("gpu_model", "Unknown GPU"),
                                "models": node_models,
                                "vram_gb": float(n.get("gpu_vram_gb", 0) or 0),
                            }
                        )
            except Exception as e:
                logger.warning("Node discovery failed: %s", e)

            if not hosts:
                return jsonify({"success": False, "error": "No ComfyUI hosts available"}), 503

            # For each host, pick the best model and generate in parallel
            variants = []
            lock = threading.Lock()

            def _generate_on_host(host_info):
                svc = ComfyUIService(host=host_info["url"])
                models = host_info["models"]
                vram = host_info["vram_gb"]

                # Pick best model for this hardware
                model_tiers = [
                    (12, "sd_xl_base_1.0.safetensors", 1024, "SDXL"),
                    (4, "v1-5-pruned-emaonly.safetensors", 512, "SD 1.5"),
                    (4, "v1-5-pruned-emaonly.ckpt", 512, "SD 1.5"),
                ]
                selected_model = None
                res = 512
                model_label = "unknown"
                for min_vram, model, r, label in model_tiers:
                    if vram >= min_vram and model in models:
                        selected_model = model
                        res = r
                        model_label = label
                        break

                if not selected_model and models:
                    # Use first available model
                    selected_model = models[0]
                    model_label = selected_model

                if not selected_model:
                    return

                start = _time.time()
                try:
                    result = svc.generate_image(
                        prompt=prompt,
                        model=selected_model,
                        steps=25,
                        width=res,
                        height=res,
                        cfg=7.0,
                    )
                except Exception as e:
                    logger.warning("Fan-out gen failed on %s: %s", host_info["name"], e)
                    return

                elapsed_ms = int((_time.time() - start) * 1000)

                if result and result.success and result.file_path:
                    # Copy to unique variant path
                    variant_id = uuid.uuid4().hex[:8]
                    variant_filename = f"{agent_name}_{host_info['name'].replace('.', '-')}_{variant_id}.png"
                    variant_path = f"/static/media/portraits/{variant_filename}"
                    abs_src = os.path.join(base_dir, result.file_path.lstrip("/"))
                    abs_dst = os.path.join(portraits_dir, variant_filename)

                    if os.path.isfile(abs_src):
                        shutil.copy2(abs_src, abs_dst)
                        file_size = os.path.getsize(abs_dst)
                    else:
                        return

                    variant = {
                        "agent_id": agent_id,
                        "path": variant_path,
                        "prompt": prompt,
                        "model": selected_model,
                        "model_label": model_label,
                        "gpu_host": host_info["name"],
                        "gpu_model": host_info["gpu_model"],
                        "time_ms": elapsed_ms,
                        "res_w": res,
                        "res_h": res,
                        "file_size": file_size,
                    }
                    with lock:
                        variants.append(variant)

            threads = [threading.Thread(target=_generate_on_host, args=(h,)) for h in hosts]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=120)

            if not variants:
                return jsonify({"success": False, "error": "All hosts failed"}), 500

            # Save all variants to agent_portraits
            first_variant = None
            with get_db_cursor(commit=True) as (conn, cur):
                for v in variants:
                    cur.execute(
                        """INSERT INTO agent_portraits
                           (agent_id, canonical_image_path, identity_prompt,
                            model_used, gpu_host, gpu_model, generation_time_ms,
                            resolution_w, resolution_h, provider, file_size_bytes,
                            approved, created_at, updated_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'comfyui', %s,
                                   false, NOW(), NOW())
                           RETURNING id""",
                        (
                            v["agent_id"],
                            v["path"],
                            v["prompt"],
                            v["model"],
                            v["gpu_host"],
                            v["gpu_model"],
                            v["time_ms"],
                            v["res_w"],
                            v["res_h"],
                            v["file_size"],
                        ),
                    )
                    v["portrait_id"] = cur.fetchone()["id"]
                    if first_variant is None:
                        first_variant = v

                # Set fastest variant as active avatar
                best = min(variants, key=lambda x: (-x["res_w"], x["time_ms"]))
                cur.execute(
                    "UPDATE agents SET avatar_url = %s WHERE id = %s",
                    (best["path"], agent_id),
                )
                cur.execute(
                    "UPDATE agent_portraits SET approved = true WHERE id = %s",
                    (best["portrait_id"],),
                )

            return (
                jsonify(
                    {
                        "success": True,
                        "variants": [
                            {
                                "id": v["portrait_id"],
                                "image_path": v["path"],
                                "model": v["model_label"],
                                "gpu_host": v["gpu_host"],
                                "gpu_model": v["gpu_model"],
                                "time_ms": v["time_ms"],
                                "resolution": f"{v['res_w']}x{v['res_h']}",
                                "file_size": v["file_size"],
                            }
                            for v in sorted(variants, key=lambda x: x["time_ms"])
                        ],
                        "active": best["path"],
                        "message": f"{len(variants)} variant(s) generated for {agent['name']}",
                    }
                ),
                201,
            )

        except Exception as e:
            logger.error("generate_portrait error for agent %s: %s", agent_id, e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>/portraits", methods=["GET"])
    @login_required
    def get_agent_portraits(agent_id):
        """Get all portrait variants for an agent with benchmark data."""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, canonical_image_path, model_used, gpu_host,
                              gpu_model, generation_time_ms, resolution_w,
                              resolution_h, provider, file_size_bytes,
                              approved, created_at
                       FROM agent_portraits
                       WHERE agent_id = %s
                       ORDER BY created_at DESC""",
                    (agent_id,),
                )
                rows = cur.fetchall()
                return jsonify(
                    {
                        "success": True,
                        "portraits": [
                            {
                                "id": r["id"],
                                "image_path": r["canonical_image_path"],
                                "model": r["model_used"],
                                "gpu_host": r["gpu_host"],
                                "gpu_model": r["gpu_model"],
                                "time_ms": r["generation_time_ms"],
                                "resolution": (
                                    f"{r['resolution_w']}x{r['resolution_h']}" if r["resolution_w"] else "unknown"
                                ),
                                "file_size": r["file_size_bytes"],
                                "provider": r["provider"],
                                "approved": r["approved"],
                                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                            }
                            for r in rows
                        ],
                    }
                )
        except Exception as e:
            logger.error("get_portraits error for agent %s: %s", agent_id, e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>/portraits/<int:portrait_id>/select", methods=["POST"])
    @login_required
    def select_agent_portrait(agent_id, portrait_id):
        """Select a portrait variant as the active avatar."""
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                # Get the portrait path
                cur.execute(
                    "SELECT canonical_image_path FROM agent_portraits WHERE id = %s AND agent_id = %s",
                    (portrait_id, agent_id),
                )
                portrait = cur.fetchone()
                if not portrait:
                    return jsonify({"success": False, "error": "Portrait not found"}), 404

                # Unmark all, mark selected
                cur.execute(
                    "UPDATE agent_portraits SET approved = false WHERE agent_id = %s",
                    (agent_id,),
                )
                cur.execute(
                    "UPDATE agent_portraits SET approved = true WHERE id = %s",
                    (portrait_id,),
                )

                # Update avatar_url
                cur.execute(
                    "UPDATE agents SET avatar_url = %s WHERE id = %s",
                    (portrait["canonical_image_path"], agent_id),
                )

                return jsonify(
                    {
                        "success": True,
                        "image_path": portrait["canonical_image_path"],
                        "message": "Portrait selected as active avatar",
                    }
                )
        except Exception as e:
            logger.error("select_portrait error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # --- Agent Memory CRUD ---

    @bp.route("/api/agents/<int:agent_id>/memory", methods=["GET"])
    @login_required
    def get_agent_memories(agent_id):
        """Get agent memories with pagination and filters"""
        try:
            # Pagination
            page = request.args.get("page", 1, type=int)
            per_page = request.args.get("per_page", 20, type=int)
            offset = (page - 1) * per_page

            # Filters
            memory_type = request.args.get("memory_type")
            include_deleted = request.args.get("include_deleted", "false").lower() == "true"
            search = request.args.get("search")

            # Build query
            conditions = ["agent_id = %s"]
            params = [agent_id]

            if not include_deleted:
                conditions.append("is_deleted = FALSE")

            if memory_type:
                conditions.append("memory_type = %s")
                params.append(memory_type)

            if search:
                conditions.append("(content ILIKE %s OR memory_type ILIKE %s)")
                params.extend([f"%{search}%", f"%{search}%"])

            where_clause = " AND ".join(conditions)

            with get_db_cursor(commit=False) as (conn, cur):
                # Get total count
                cur.execute("SELECT COUNT(*) FROM agent_memory WHERE " + where_clause, params)
                total = cur.fetchone()["count"]

                # Get memories
                cur.execute(
                    "SELECT id, agent_id, memory_type, content, importance_score,"
                    " context, source_module, emotional_valence,"
                    " is_deleted, deleted_at, deleted_by, deletion_reason,"
                    " created_at, last_accessed, access_count,"
                    " decay_immunity, reinforcement_count"
                    " FROM agent_memory"
                    " WHERE " + where_clause + " ORDER BY importance_score DESC NULLS LAST, created_at DESC"
                    " LIMIT %s OFFSET %s",
                    params + [per_page, offset],
                )

                memories = cur.fetchall()

            return jsonify(
                {
                    "success": True,
                    "data": [dict(m) for m in memories],
                    "count": len(memories),
                    "total": total,
                    "page": page,
                    "per_page": per_page,
                }
            )
        except Exception as e:
            logger.error("get_agent_memories error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>/memory", methods=["POST"])
    @login_required
    def create_agent_memory(agent_id):
        """Create new agent memory"""
        try:
            data = request.get_json()

            if not data.get("content"):
                return (
                    jsonify({"success": False, "error": "content is required"}),
                    400,
                )

            with get_db_cursor(commit=True) as (conn, cur):
                # Verify agent exists
                cur.execute("SELECT id FROM agents WHERE id = %s", (agent_id,))
                if not cur.fetchone():
                    return jsonify({"success": False, "error": "Agent not found"}), 404

                cur.execute(
                    """
                    INSERT INTO agent_memory (agent_id, memory_type, content, importance_score, context, source_module)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, agent_id, memory_type, content, importance_score, context, source_module, created_at
                """,
                    (
                        agent_id,
                        data.get("memory_type", "general"),
                        data["content"],
                        data.get("importance_score", 0.5),
                        json.dumps(data["context"]) if isinstance(data.get("context"), dict) else data.get("context"),
                        data.get("source_module"),
                    ),
                )

                memory = cur.fetchone()

                # Log governance event
                cur.execute(
                    """
                    INSERT INTO governance_audit_log
                    (event_type, event_category, agent_id, user_id, action, target_table, target_id, new_value, outcome)
                    VALUES ('memory_created', 'data_management', %s, %s, 'create_memory', 'agent_memory', %s, %s, 'success')
                """,
                    (
                        agent_id,
                        current_user.id,
                        memory["id"],
                        json.dumps(dict(memory), default=str),
                    ),
                )

            return jsonify(
                {
                    "success": True,
                    "data": dict(memory),
                    "message": "Memory created successfully",
                }
            )
        except Exception as e:
            logger.error("create_agent_memory error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>/memory/<int:memory_id>", methods=["GET"])
    @login_required
    def get_agent_memory(agent_id, memory_id):
        """Get specific agent memory"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT * FROM agent_memory
                    WHERE id = %s AND agent_id = %s
                """,
                    (memory_id, agent_id),
                )

                memory = cur.fetchone()

            if not memory:
                return jsonify({"success": False, "error": "Memory not found"}), 404

            return jsonify({"success": True, "data": dict(memory)})
        except Exception as e:
            logger.error("get_agent_memory error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>/memory/<int:memory_id>", methods=["PUT"])
    @login_required
    def update_agent_memory(agent_id, memory_id):
        """Update agent memory"""
        try:
            data = request.get_json()

            with get_db_cursor(commit=True) as (conn, cur):
                # Get old value for audit
                cur.execute(
                    "SELECT * FROM agent_memory WHERE id = %s AND agent_id = %s",
                    (memory_id, agent_id),
                )
                old_memory = cur.fetchone()

                if not old_memory:
                    return jsonify({"success": False, "error": "Memory not found"}), 404

                # Build update
                updates = []
                params = []

                if "content" in data:
                    updates.append("content = %s")
                    params.append(data["content"])

                if "importance_score" in data:
                    updates.append("importance_score = %s")
                    params.append(data["importance_score"])

                if "context" in data:
                    updates.append("context = %s")
                    params.append(json.dumps(data["context"]) if isinstance(data["context"], dict) else data["context"])

                if "memory_type" in data:
                    updates.append("memory_type = %s")
                    params.append(data["memory_type"])

                if "emotional_valence" in data:
                    updates.append("emotional_valence = %s")
                    params.append(data["emotional_valence"])

                if "source_module" in data:
                    updates.append("source_module = %s")
                    params.append(data["source_module"])

                if not updates:
                    return jsonify({"success": False, "error": "No fields to update"}), 400

                updates.append("last_accessed = NOW()")
                params.extend([memory_id, agent_id])

                cur.execute(
                    f"""
                    UPDATE agent_memory SET {', '.join(updates)}
                    WHERE id = %s AND agent_id = %s
                    RETURNING *
                """,
                    params,
                )

                updated = cur.fetchone()

                # Log governance event
                cur.execute(
                    """
                    INSERT INTO governance_audit_log
                    (event_type, event_category, agent_id, user_id,
                     action, target_table, target_id, old_value,
                     new_value, outcome)
                    VALUES ('memory_updated', 'data_management', %s, %s, 'update_memory', 'agent_memory', %s, %s, %s, 'success')
                """,
                    (
                        agent_id,
                        current_user.id,
                        memory_id,
                        json.dumps(dict(old_memory), default=str),
                        json.dumps(dict(updated), default=str),
                    ),
                )

            return jsonify(
                {
                    "success": True,
                    "data": dict(updated),
                    "message": "Memory updated successfully",
                }
            )
        except Exception as e:
            logger.error("update_agent_memory error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>/memory/<int:memory_id>", methods=["DELETE"])
    @login_required
    def delete_agent_memory(agent_id, memory_id):
        """Soft delete agent memory using database function"""
        try:
            data = request.get_json() or {}
            reason = data.get("reason", "Manual deletion by admin")

            with get_db_cursor(commit=True) as (conn, cur):
                # Use the database soft_delete function
                try:
                    cur.execute(
                        "SELECT soft_delete_agent_memory(%s, %s, %s) as deleted",
                        (memory_id, current_user.id, reason),
                    )
                    result = cur.fetchone()

                    if not result or not result["deleted"]:
                        return (
                            jsonify({"success": False, "error": "Memory not found or already deleted"}),
                            404,
                        )
                except Exception:
                    # Fallback: manual soft delete if DB function doesn't exist
                    cur.execute(
                        """
                        UPDATE agent_memory
                        SET is_deleted = TRUE, deleted_at = NOW(), deleted_by = %s, deletion_reason = %s
                        WHERE id = %s AND agent_id = %s AND is_deleted = FALSE
                        RETURNING id
                    """,
                        (current_user.id, reason, memory_id, agent_id),
                    )
                    deleted = cur.fetchone()
                    if not deleted:
                        return (
                            jsonify({"success": False, "error": "Memory not found or already deleted"}),
                            404,
                        )

            return jsonify({"success": True, "message": "Memory soft-deleted successfully"})
        except Exception as e:
            logger.error("delete_agent_memory error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>/memory/<int:memory_id>/restore", methods=["POST"])
    @login_required
    def restore_agent_memory(agent_id, memory_id):
        """Restore soft-deleted agent memory"""
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE agent_memory
                    SET is_deleted = FALSE, deleted_at = NULL, deleted_by = NULL, deletion_reason = NULL
                    WHERE id = %s AND agent_id = %s AND is_deleted = TRUE
                    RETURNING *
                """,
                    (memory_id, agent_id),
                )

                restored = cur.fetchone()

                if not restored:
                    return (
                        jsonify({"success": False, "error": "Memory not found or not deleted"}),
                        404,
                    )

                # Log governance event
                cur.execute(
                    """
                    INSERT INTO governance_audit_log
                    (event_type, event_category, agent_id, user_id, action, target_table, target_id, outcome)
                    VALUES ('memory_restored', 'data_management', %s, %s, 'restore_memory', 'agent_memory', %s, 'success')
                """,
                    (agent_id, current_user.id, memory_id),
                )

            return jsonify(
                {
                    "success": True,
                    "data": dict(restored),
                    "message": "Memory restored successfully",
                }
            )
        except Exception as e:
            logger.error("restore_agent_memory error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # --- Agent Performance ---

    @bp.route("/api/agents/<int:agent_id>/performance", methods=["GET"])
    @login_required
    def get_agent_performance_data(agent_id):
        """Get performance metrics for an agent."""
        if not _HAS_PERFORMANCE_TRACKER:
            return jsonify({"success": False, "error": "Performance tracker not available"}), 501
        performance = get_agent_performance(agent_id)
        if performance is None:
            return jsonify({"success": False, "error": "No performance data"}), 404
        return jsonify({"success": True, "performance": performance})

    @bp.route("/api/agents/<int:agent_id>/performance/update", methods=["POST"])
    @login_required
    def update_agent_performance_metrics(agent_id):
        """Recalculate performance metrics for an agent."""
        if not _HAS_PERFORMANCE_TRACKER:
            return jsonify({"success": False, "error": "Performance tracker not available"}), 501
        success = update_agent_performance(agent_id)
        return jsonify({"success": success, "message": f"Performance metrics updated for agent #{agent_id}"})

    @bp.route("/api/agents/performance/leaderboard", methods=["GET"])
    @login_required
    def get_performance_leaderboard():
        """Get top performing agents."""
        if not _HAS_PERFORMANCE_TRACKER:
            return jsonify({"success": False, "error": "Performance tracker not available"}), 501
        limit = request.args.get("limit", 10, type=int)
        leaderboard = get_top_performers(limit=limit)
        return jsonify({"success": True, "leaderboard": leaderboard})

    @bp.route("/api/agents/<int:agent_id>/work-history", methods=["GET"])
    @login_required
    def get_agent_work_history(agent_id):
        """Get work history: proposals, discussions, stats."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                # Improvement proposals
                cur.execute(
                    """
                    SELECT id, title, status, category, priority,
                           proposed_at, deployed_at, test_status, escalation_status
                    FROM improvement_proposals
                    WHERE assigned_agent_id = %s OR contractor_agent_id = %s
                    ORDER BY proposed_at DESC LIMIT 20
                """,
                    (agent_id, agent_id),
                )
                proposals = [dict(r) for r in cur.fetchall()]

                # Discussions
                cur.execute(
                    """
                    SELECT DISTINCT d.id, d.topic, d.status, d.created_at,
                           (SELECT COUNT(*) FROM agent_discussion_messages
                            WHERE discussion_id = d.id AND agent_id = %s) as message_count
                    FROM agent_discussions d
                    JOIN agent_discussion_messages m ON d.id = m.discussion_id
                    WHERE m.agent_id = %s
                    ORDER BY d.created_at DESC LIMIT 10
                """,
                    (agent_id, agent_id),
                )
                discussions = [dict(r) for r in cur.fetchall()]

                # Performance stats
                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE assigned_agent_id = %s) as proposals_assigned,
                        COUNT(*) FILTER (WHERE assigned_agent_id = %s AND status = 'deployed') as proposals_deployed,
                        COUNT(*) FILTER (WHERE contractor_agent_id = %s) as contractor_consultations,
                        COUNT(*) FILTER (WHERE contractor_agent_id = %s AND status = 'deployed') as contractor_successes
                    FROM improvement_proposals
                """,
                    (agent_id, agent_id, agent_id, agent_id),
                )
                row = cur.fetchone()
                stats = dict(row) if row else {}

                # Serialize datetimes for JSON
                for p in proposals:
                    for k in ("proposed_at", "deployed_at"):
                        if p.get(k) and hasattr(p[k], "isoformat"):
                            p[k] = p[k].isoformat()
                for d in discussions:
                    if d.get("created_at") and hasattr(d["created_at"], "isoformat"):
                        d["created_at"] = d["created_at"].isoformat()

                return jsonify(
                    {
                        "success": True,
                        "proposals": proposals,
                        "discussions": discussions,
                        "stats": stats,
                    }
                )
        except Exception as e:
            logger.error(f"Error getting work history for agent {agent_id}: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500
