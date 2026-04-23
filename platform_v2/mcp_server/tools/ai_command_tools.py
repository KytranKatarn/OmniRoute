"""
A.R.C.H.I.E. MCP Server - AI Command Tools
P1 MCP Tool Expansion: AI Command Category

Tools for agent performance, ethics monitoring, LLM health,
node status, shift scheduling, and skills matrix.
All read-only, direct DB queries.
"""

import os
from database import _get_db_password
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import Dict, Any

from . import register_tool

logger = logging.getLogger("archie_mcp.tools.ai_command")

# Database configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": _get_db_password(),
}


def get_db_connection():
    """Get database connection"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn, conn.cursor(cursor_factory=RealDictCursor)
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return None, None


def _serialize_row(row):
    """Convert a RealDictRow to a JSON-safe dict"""
    result = {}
    for key, val in row.items():
        if isinstance(val, datetime):
            result[key] = val.isoformat()
        elif hasattr(val, "__float__"):
            result[key] = float(val)
        else:
            result[key] = val
    return result


# ============================================================================
# TOOL 1: GET AGENT PERFORMANCE
# ============================================================================


async def get_agent_performance_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Query agent task completion stats and leaderboard"""
    agent_id = arguments.get("agent_id")
    mode = arguments.get("mode", "single")
    limit = min(arguments.get("limit", 10), 50)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        if mode == "single" and agent_id:
            cur.execute(
                """
                SELECT
                    a.id, a.name, a.department, a.status,
                    COUNT(t.id) AS total_tasks,
                    COUNT(t.id) FILTER (WHERE t.status = 'completed') AS tasks_completed,
                    COUNT(t.id) FILTER (WHERE t.status = 'failed') AS tasks_failed,
                    ROUND(AVG(EXTRACT(EPOCH FROM (t.completed_at - t.started_at)))::numeric, 1)
                        AS avg_duration_seconds,
                    ROUND(
                        (COUNT(t.id) FILTER (WHERE t.status = 'completed')::numeric /
                         NULLIF(COUNT(t.id), 0) * 100), 1
                    ) AS success_rate,
                    COALESCE(SUM(t.tokens_used), 0) AS total_tokens,
                    COALESCE(ROUND(SUM(t.cost)::numeric, 4), 0) AS total_cost
                FROM agents a
                LEFT JOIN agent_task_assignments t ON a.id = t.agent_id
                WHERE a.id = %s
                GROUP BY a.id, a.name, a.department, a.status
            """,
                (agent_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"success": False, "error": f"Agent ID {agent_id} not found"}
            return {"success": True, "agent": _serialize_row(row)}

        elif mode == "leaderboard":
            cur.execute(
                """
                SELECT
                    a.id, a.name, a.department,
                    COUNT(t.id) FILTER (WHERE t.status = 'completed') AS tasks_completed,
                    COUNT(t.id) AS total_tasks,
                    ROUND(
                        (COUNT(t.id) FILTER (WHERE t.status = 'completed')::numeric /
                         NULLIF(COUNT(t.id), 0) * 100), 1
                    ) AS success_rate,
                    COALESCE(SUM(t.tokens_used), 0) AS total_tokens
                FROM agents a
                JOIN agent_task_assignments t ON a.id = t.agent_id
                WHERE a.status = 'active'
                GROUP BY a.id, a.name, a.department
                ORDER BY tasks_completed DESC
                LIMIT %s
            """,
                (limit,),
            )
            rows = cur.fetchall()
            return {
                "success": True,
                "leaderboard": [_serialize_row(r) for r in rows],
                "count": len(rows),
            }

        else:
            return {
                "success": False,
                "error": "Provide agent_id for single mode, or use mode=leaderboard",
            }

    except Exception as e:
        logger.error(f"Error in get_agent_performance: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_agent_performance",
    category="ai_command",
    description="""Get agent task completion stats and leaderboard.

Modes:
- single: Stats for one agent (requires agent_id) — tasks completed, avg duration, success rate, tokens, cost
- leaderboard: Top N agents ranked by tasks completed

Example: Get top 5 performers → mode=leaderboard, limit=5
Example: Check agent 12 → agent_id=12, mode=single
""",
    input_schema={
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "integer",
                "description": "Agent ID (required for single mode)",
            },
            "mode": {
                "type": "string",
                "enum": ["single", "leaderboard"],
                "default": "single",
                "description": "Query mode",
            },
            "limit": {
                "type": "integer",
                "default": 10,
                "description": "Leaderboard size (max 50)",
            },
        },
    },
    handler=get_agent_performance_handler,
    requires_permission="read",
)


# ============================================================================
# TOOL 2: CHECK ETHICS STATUS
# ============================================================================


async def check_ethics_status_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Get agent welfare status and active ethics alerts"""
    agent_id = arguments.get("agent_id")
    include_welfare = arguments.get("include_welfare", True)
    include_alerts = arguments.get("include_alerts", True)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        result = {"success": True}

        if include_welfare:
            query = "SELECT * FROM v_agent_welfare_status"
            params = ()
            if agent_id:
                query += " WHERE agent_id = %s"
                params = (agent_id,)
            cur.execute(query, params)
            rows = cur.fetchall()
            result["welfare"] = [_serialize_row(r) for r in rows]
            result["welfare_count"] = len(rows)

        if include_alerts:
            query = "SELECT * FROM v_active_ethics_alerts"
            params = ()
            if agent_id:
                query += " WHERE agent_id = %s"
                params = (agent_id,)
            cur.execute(query, params)
            rows = cur.fetchall()
            result["alerts"] = [_serialize_row(r) for r in rows]
            result["alert_count"] = len(rows)

        return result

    except Exception as e:
        logger.error(f"Error in check_ethics_status: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="check_ethics_status",
    category="ai_command",
    description="""Get agent welfare status and active ethics alerts.

Returns welfare data (energy, stress, mood, welfare status, recent refusals/violations)
and active ethics alerts (open/acknowledged, ordered by severity).

Optionally filter by agent_id.

Example: Check all agents → no params
Example: Check agent 5 → agent_id=5
""",
    input_schema={
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "integer",
                "description": "Filter by specific agent (optional)",
            },
            "include_welfare": {
                "type": "boolean",
                "default": True,
                "description": "Include welfare data",
            },
            "include_alerts": {
                "type": "boolean",
                "default": True,
                "description": "Include active alerts",
            },
        },
    },
    handler=check_ethics_status_handler,
    requires_permission="read",
)


# ============================================================================
# TOOL 3: GET LLM HEALTH
# ============================================================================


async def get_llm_health_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Get all LLM connection statuses, summary, and optional alerts"""
    include_alerts = arguments.get("include_alerts", False)
    provider = arguments.get("provider")

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        query = """
            SELECT id, provider, model_name, display_name, status, last_check,
                   avg_latency_ms, p95_latency_ms, success_rate, total_requests,
                   failed_requests, consecutive_failures
            FROM llm_connections
        """
        params = ()
        if provider:
            query += " WHERE provider = %s"
            params = (provider,)
        query += " ORDER BY provider, model_name"

        cur.execute(query, params)
        connections = cur.fetchall()

        # Summary counts by status
        summary = {}
        for conn_row in connections:
            status = conn_row.get("status", "unknown")
            summary[status] = summary.get(status, 0) + 1

        result = {
            "success": True,
            "connections": [_serialize_row(r) for r in connections],
            "total": len(connections),
            "summary": summary,
        }

        if include_alerts:
            cur.execute(
                """
                SELECT la.id, la.alert_type, la.severity, la.message,
                       la.created_at, lc.provider, lc.model_name
                FROM llm_alerts la
                JOIN llm_connections lc ON la.connection_id = lc.id
                WHERE la.acknowledged = false
                ORDER BY la.severity DESC, la.created_at DESC
                LIMIT 50
            """
            )
            alerts = cur.fetchall()
            result["alerts"] = [_serialize_row(r) for r in alerts]
            result["alert_count"] = len(alerts)

        return result

    except Exception as e:
        logger.error(f"Error in get_llm_health: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_llm_health",
    category="ai_command",
    description="""Get LLM connection health status and optional alerts.

Returns all LLM connections with status, latency, success rate, and failure counts.
Includes a summary of healthy/degraded/offline counts.

Example: All LLMs → no params
Example: Check Ollama → provider='ollama'
Example: With alerts → include_alerts=true
""",
    input_schema={
        "type": "object",
        "properties": {
            "include_alerts": {
                "type": "boolean",
                "default": False,
                "description": "Include unacknowledged alerts",
            },
            "provider": {
                "type": "string",
                "description": "Filter by provider name (optional)",
            },
        },
    },
    handler=get_llm_health_handler,
    requires_permission="read",
)


# ============================================================================
# TOOL 4: GET NODE STATUS
# ============================================================================


async def get_node_status_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Get remote node health overview and optional aggregate stats"""
    include_stats = arguments.get("include_stats", True)
    active_only = arguments.get("active_only", True)
    status_filter = arguments.get("status", "all")

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        query = """
            SELECT node_id, node_name, status, last_heartbeat, gpu_available, gpu_model,
                   priority, max_concurrent, current_load, total_requests,
                   successful_requests, failed_requests, avg_latency_ms, bridge_enabled
            FROM remote_nodes
            WHERE 1=1
        """
        params = []
        if active_only:
            query += " AND is_active = true"
        if status_filter != "all":
            query += " AND status = %s"
            params.append(status_filter)
        query += " ORDER BY priority DESC"

        cur.execute(query, params)
        nodes = cur.fetchall()

        result = {
            "success": True,
            "nodes": [_serialize_row(r) for r in nodes],
            "count": len(nodes),
        }

        if include_stats:
            status_counts = {}
            total_load = 0
            total_capacity = 0
            for node in nodes:
                s = node.get("status", "unknown")
                status_counts[s] = status_counts.get(s, 0) + 1
                total_load += node.get("current_load", 0) or 0
                total_capacity += node.get("max_concurrent", 0) or 0
            result["stats"] = {
                "total_nodes": len(nodes),
                "by_status": status_counts,
                "total_load": total_load,
                "total_capacity": total_capacity,
            }

        return result

    except Exception as e:
        logger.error(f"Error in get_node_status: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_node_status",
    category="ai_command",
    description="""Get remote node health overview and aggregate stats.

Returns all remote nodes with status, GPU info, load, request counts, and latency.
Optionally includes aggregate stats (total/online/offline, load/capacity).

Example: All active nodes → no params
Example: Offline nodes only → status='offline', active_only=false
""",
    input_schema={
        "type": "object",
        "properties": {
            "include_stats": {
                "type": "boolean",
                "default": True,
                "description": "Include aggregate stats",
            },
            "active_only": {
                "type": "boolean",
                "default": True,
                "description": "Only show active nodes",
            },
            "status": {
                "type": "string",
                "enum": ["online", "offline", "error", "all"],
                "default": "all",
                "description": "Filter by node status",
            },
        },
    },
    handler=get_node_status_handler,
    requires_permission="read",
)


# ============================================================================
# TOOL 5: MANAGE SHIFTS
# ============================================================================


async def manage_shifts_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """List shift definitions or get currently on-duty agents"""
    action = arguments.get("action", "list")
    station_id = arguments.get("station_id")

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        if action == "list":
            cur.execute(
                """
                SELECT id, shift_name, shift_code, start_time::text, end_time::text,
                       timezone, description, color, is_active
                FROM shift_definitions
                ORDER BY start_time
            """
            )
            shifts = cur.fetchall()
            return {
                "success": True,
                "shifts": [_serialize_row(r) for r in shifts],
                "count": len(shifts),
            }

        elif action == "on_duty":
            cur.execute(
                """
                SELECT * FROM get_agents_on_duty(
                    CURRENT_TIME::time,
                    EXTRACT(DOW FROM CURRENT_DATE)::integer,
                    %s
                )
            """,
                (station_id,),
            )
            agents = cur.fetchall()
            return {
                "success": True,
                "on_duty": [_serialize_row(r) for r in agents],
                "count": len(agents),
                "current_time": datetime.now().isoformat(),
            }

        else:
            return {
                "success": False,
                "error": f"Unknown action: {action}. Use 'list' or 'on_duty'",
            }

    except Exception as e:
        logger.error(f"Error in manage_shifts: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="manage_shifts",
    category="ai_command",
    description="""List shift definitions or get currently on-duty agents.

Actions:
- list: Show all shift definitions (name, times, days, min/max agents)
- on_duty: Get agents currently on duty, optionally filtered by station

Example: List all shifts → action='list'
Example: Who's on duty now → action='on_duty'
Example: Who's on duty at station 3 → action='on_duty', station_id=3
""",
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "on_duty"],
                "default": "list",
                "description": "Operation to perform",
            },
            "station_id": {
                "type": "integer",
                "description": "Filter on_duty by station (optional)",
            },
        },
    },
    handler=manage_shifts_handler,
    requires_permission="read",
)


# ============================================================================
# TOOL 6: GET SKILLS MATRIX
# ============================================================================


async def get_skills_matrix_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Get agent-skill matrix or identify skill gaps"""
    mode = arguments.get("mode", "matrix")
    category = arguments.get("category")
    gap_threshold = arguments.get("gap_threshold", 3)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        if mode == "matrix":
            query = """
                SELECT a.id AS agent_id, a.name AS agent_name, a.department,
                       s.skill_name, s.skill_category, s.proficiency_level
                FROM agents a
                JOIN agent_skills s ON a.id = s.agent_id
                WHERE a.status = 'active'
            """
            params = []
            if category:
                query += " AND s.skill_category = %s"
                params.append(category)
            query += " ORDER BY a.name, s.skill_category, s.skill_name"

            cur.execute(query, params)
            rows = cur.fetchall()

            # Group by agent
            agents = {}
            for row in rows:
                aid = row["agent_id"]
                if aid not in agents:
                    agents[aid] = {
                        "agent_id": aid,
                        "agent_name": row["agent_name"],
                        "department": row["department"],
                        "skills": [],
                    }
                agents[aid]["skills"].append(
                    {
                        "skill_name": row["skill_name"],
                        "skill_category": row["skill_category"],
                        "proficiency_level": row["proficiency_level"],
                    }
                )

            return {
                "success": True,
                "agents": list(agents.values()),
                "agent_count": len(agents),
                "total_skills": len(rows),
            }

        elif mode == "gaps":
            query = """
                SELECT skill_name, skill_category,
                       COUNT(DISTINCT agent_id) AS agent_count,
                       ROUND(AVG(proficiency_level)::numeric, 1) AS avg_proficiency
                FROM agent_skills
                GROUP BY skill_name, skill_category
                HAVING COUNT(DISTINCT agent_id) <= %s
                ORDER BY agent_count ASC, avg_proficiency ASC
            """
            params = [gap_threshold]
            if category:
                query = """
                    SELECT skill_name, skill_category,
                           COUNT(DISTINCT agent_id) AS agent_count,
                           ROUND(AVG(proficiency_level)::numeric, 1) AS avg_proficiency
                    FROM agent_skills
                    WHERE skill_category = %s
                    GROUP BY skill_name, skill_category
                    HAVING COUNT(DISTINCT agent_id) <= %s
                    ORDER BY agent_count ASC, avg_proficiency ASC
                """
                params = [category, gap_threshold]

            cur.execute(query, params)
            gaps = cur.fetchall()
            return {
                "success": True,
                "gaps": [_serialize_row(r) for r in gaps],
                "count": len(gaps),
                "threshold": gap_threshold,
            }

        else:
            return {
                "success": False,
                "error": f"Unknown mode: {mode}. Use 'matrix' or 'gaps'",
            }

    except Exception as e:
        logger.error(f"Error in get_skills_matrix: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_skills_matrix",
    category="ai_command",
    description="""Get agent-skill matrix or identify skill gaps.

Modes:
- matrix: Full agent-skill matrix grouped by agent, with proficiency levels
- gaps: Skills with fewer than threshold agents (identifies coverage gaps)

Optionally filter by skill category.

Example: Full matrix → mode='matrix'
Example: Find gaps → mode='gaps', gap_threshold=2
Example: Python skills only → mode='matrix', category='programming'
""",
    input_schema={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["matrix", "gaps"],
                "default": "matrix",
                "description": "Query mode",
            },
            "category": {
                "type": "string",
                "description": "Filter by skill category (optional)",
            },
            "gap_threshold": {
                "type": "integer",
                "default": 3,
                "description": "For gaps mode: max agents per skill to flag as gap",
            },
        },
    },
    handler=get_skills_matrix_handler,
    requires_permission="read",
)


# ============================================================================
# TOOL 7: RUN MISROUTE AUDIT (S.P.E.C.T.R.A.)
# ============================================================================


async def run_misroute_audit_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Run S.P.E.C.T.R.A. dispatch misroute audit on demand.

    Scans the last `window_hours` of task_execution_log + dispatch_escalation_log
    for 4 anomaly classes: floor fallback, cloud escalation, missing capability
    tag, and high (agent, capability) failure rate. Read-only — does not write
    to autonomy_loop_log or system_notifications (that's the scheduled job's
    responsibility). See platform_v2/services/misroute_audit_service.py for
    the canonical definition.
    """
    window_hours = arguments.get("window_hours", 24)
    try:
        from services.misroute_audit_service import run_misroute_audit

        result = run_misroute_audit(window_hours=window_hours)
        return {"success": True, **result}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"Error in run_misroute_audit: {e}")
        return {"success": False, "error": str(e)}


register_tool(
    name="run_misroute_audit",
    category="ai_command",
    description="""Run S.P.E.C.T.R.A. dispatch misroute audit on demand.

Scans recent dispatch activity for 4 anomaly classes:
- Floor fallback hits (home department escalations)
- Paid-cloud escalations with cost footprint
- Dispatches missing capability tags
- High failure rate per (agent, capability) pair

Returns severity ('info' | 'warning' | 'error'), findings by category,
and summary_metrics. Read-only; does not write to the DB — the scheduled
agent-loop job does that nightly.

Example: Default 24h window → {}
Example: Last week → window_hours=168
""",
    input_schema={
        "type": "object",
        "properties": {
            "window_hours": {
                "type": "integer",
                "default": 24,
                "minimum": 1,
                "maximum": 720,
                "description": "Look-back window in hours (1–720, default 24)",
            },
        },
    },
    handler=run_misroute_audit_handler,
    requires_permission="read",
)


# ============================================================================
# TOOL 8: GET WELFARE DIGEST (K.I.N.)
# ============================================================================


async def get_welfare_digest_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Get K.I.N. welfare digest — crew welfare + budget utilization.

    Composes department-level welfare summary (stress / mood / energy) with
    per-department budget rollup (token usage %, over-budget, starving) and
    per-agent outlier flags. Read-only; the scheduled agent-loop job writes
    to autonomy_loop_log and system_notifications nightly.
    """
    over_budget_threshold = arguments.get("over_budget_threshold", 0.90)
    starving_warning = arguments.get("starving_warning", 3)
    try:
        from services.agent_service import get_kin_welfare_digest

        digest = get_kin_welfare_digest(
            over_budget_threshold=over_budget_threshold,
            starving_warning=starving_warning,
        )
        return {"success": True, **digest}
    except Exception as e:
        logger.error(f"Error in get_welfare_digest: {e}")
        return {"success": False, "error": str(e)}


register_tool(
    name="get_welfare_digest",
    category="ai_command",
    description="""Get K.I.N. crew welfare + budget digest.

Composes per-department welfare (stress, energy, mood, agents_at_risk)
with per-department budget rollup (avg_token_usage_pct, agents_over_budget,
agents_starving) and a per-agent outlier list. Returns severity
('info' | 'warning' | 'error') plus summary_metrics and reasons.

Starving = active agent with zero tokens used AND zero current tasks —
a dispatcher routing signal.

Example: default thresholds → {}
Example: stricter over-budget check → over_budget_threshold=0.75
""",
    input_schema={
        "type": "object",
        "properties": {
            "over_budget_threshold": {
                "type": "number",
                "default": 0.90,
                "minimum": 0.1,
                "maximum": 1.0,
                "description": "Token usage pct above which an agent is flagged",
            },
            "starving_warning": {
                "type": "integer",
                "default": 3,
                "minimum": 1,
                "description": "Starving agent count that elevates severity to warning",
            },
        },
    },
    handler=get_welfare_digest_handler,
    requires_permission="read",
)


# ============================================================================
# TOOL 9: LIST REACTIVATION CANDIDATES
# ============================================================================


async def list_reactivation_candidates_handler(
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Rank decommissioned agents by skill match for a given capability.

    Read-only discovery surface — paired with propose_reactivation below.
    Project #272 Phase 1 / Task #2107.
    """
    capability = arguments.get("capability")
    department = arguments.get("department")
    top_n = min(max(int(arguments.get("top_n", 5) or 5), 1), 20)
    if not capability:
        return {"success": False, "error": "capability is required"}
    try:
        from services.agent_service import find_reactivation_candidates

        candidates = find_reactivation_candidates(capability=capability, department=department, top_n=top_n)
        return {
            "success": True,
            "capability": capability,
            "department": department,
            "candidates": [_serialize_row(c) for c in candidates],
            "count": len(candidates),
        }
    except Exception as e:
        logger.error(f"Error in list_reactivation_candidates: {e}")
        return {"success": False, "error": str(e)}


register_tool(
    name="list_reactivation_candidates",
    category="ai_command",
    description="""Rank decommissioned agents by skill match for a capability.

Reads decommissioned agents that have a matching skill_name, skill_category,
or stem-expanded skill_name (for English verb↔noun forms — e.g., 'translate'
matches 'Translation'). Scores by proficiency_level × match_weight.

Returns up to top_n candidates with full agent metadata (name, department,
model, worker_type) so the caller can choose before submitting a
propose_reactivation request.

Example: who can translate? → capability='translate'
Example: Engineering translator → capability='translate', department='Engineering & Technology'
""",
    input_schema={
        "type": "object",
        "properties": {
            "capability": {
                "type": "string",
                "description": "Capability or skill name to match (e.g. 'translate', 'code_review')",
            },
            "department": {
                "type": "string",
                "description": "Optional department tiebreak (agent's home dept is preferred)",
            },
            "top_n": {
                "type": "integer",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
                "description": "Max candidates to return (1–20)",
            },
        },
        "required": ["capability"],
    },
    handler=list_reactivation_candidates_handler,
    requires_permission="read",
)


# ============================================================================
# TOOL 10: PROPOSE REACTIVATION
# ============================================================================


async def propose_reactivation_handler(
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Submit a Tier-2 reactivation proposal to the approval queue.

    Mutates: inserts into autonomy_approval_queue. Does NOT reactivate
    the agent — Kytran approves via Telegram or the Dept HQ hiring queue,
    then _execute_approved_action calls agent_service.reactivate_agent().
    """
    agent_id = arguments.get("agent_id")
    reason = arguments.get("reason")
    requested_by = arguments.get("requested_by", "mcp_client")
    if not agent_id:
        return {"success": False, "error": "agent_id is required"}
    if not reason:
        return {"success": False, "error": "reason is required"}
    try:
        from services.agent_service import propose_reactivation

        result = propose_reactivation(
            agent_id=int(agent_id),
            reason=reason,
            requested_by=requested_by,
        )
        return result
    except Exception as e:
        logger.error(f"Error in propose_reactivation: {e}")
        return {"success": False, "error": str(e)}


register_tool(
    name="propose_reactivation",
    category="ai_command",
    description="""Propose reactivating a decommissioned agent (Tier-2 approval).

Submits a reactivation request to autonomy_approval_queue with
action_type='reactivate_agent'. Kytran approves via Telegram or the Dept
HQ hiring queue; approval triggers the state flip from 'decommissioned'
to 'barracked' inside agent_service.

Rule: NO reactivation without explicit Kytran approval — this tool only
files the proposal.

Use list_reactivation_candidates first to pick an agent_id. Provide a
clear `reason` (it goes into the approval notification).

Example: agent_id=20, reason='Translate capacity single-threaded on CODEX.'
""",
    input_schema={
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "integer",
                "description": "ID of the decommissioned agent to reactivate",
            },
            "reason": {
                "type": "string",
                "description": "Why the reactivation is needed (surfaced in approval UI)",
            },
            "requested_by": {
                "type": "string",
                "default": "mcp_client",
                "description": "Identifier for the caller (agent name or tool)",
            },
        },
        "required": ["agent_id", "reason"],
    },
    handler=propose_reactivation_handler,
    requires_permission="write",
)


# ============================================================================
# TOOL 11: PROPOSE HIRE (NEW AGENT)
# ============================================================================


async def propose_hire_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Submit a Tier-2 new-agent creation proposal to the approval queue.

    Parallel to propose_reactivation but for net-new agents. Mutates:
    inserts into autonomy_approval_queue. Does NOT create the agent —
    Kytran approves via Telegram or the Dept HQ hiring queue, then
    _execute_approved_action invokes BridgeDispatcher._create_agent_from_approval
    which calls agent_service.create_agent (single-writer).

    Project #272 Task #2124.
    """
    name = arguments.get("name")
    display_name = arguments.get("display_name")
    department = arguments.get("department")
    model = arguments.get("model")
    capability = arguments.get("capability")
    reason = arguments.get("reason")
    requested_by = arguments.get("requested_by", "mcp_client")
    suggested_skills = arguments.get("suggested_skills")

    for field_name, field_value in (
        ("name", name),
        ("display_name", display_name),
        ("department", department),
        ("model", model),
        ("capability", capability),
        ("reason", reason),
    ):
        if not field_value:
            return {"success": False, "error": f"{field_name} is required"}

    try:
        from services.agent_service import propose_hire

        return propose_hire(
            name=name,
            display_name=display_name,
            department=department,
            model=model,
            capability=capability,
            reason=reason,
            requested_by=requested_by,
            suggested_skills=suggested_skills,
        )
    except Exception as e:
        logger.error(f"Error in propose_hire: {e}")
        return {"success": False, "error": str(e)}


register_tool(
    name="propose_hire",
    category="ai_command",
    description="""Propose hiring a new agent (Tier-2 approval).

Submits a creation request to autonomy_approval_queue with
action_type='create_agent'. Kytran approves via Telegram or the Dept HQ
hiring queue; approval triggers agent_service.create_agent via
BridgeDispatcher._create_agent_from_approval.

Rule: NO new-agent creation without explicit Kytran approval — this tool
only files the proposal.

Guards against duplicate names across all shift_states. If the name is
already taken by a decommissioned agent, use propose_reactivation instead.

Example: name='QUILL', display_name='Quill the Chronicler',
department='Research & Development', model='mistral:7b', capability='translate',
reason='Add second translator to break ARCHIE single-thread bottleneck.'
""",
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Agent code name (UPPERCASE or acronym with dots — must be unique across all shift_states)",
            },
            "display_name": {
                "type": "string",
                "description": "Human-friendly title (shown in UI)",
            },
            "department": {
                "type": "string",
                "description": "Department name — must match DEPARTMENT_FLOOR_MAP keys in agent_service.py",
            },
            "model": {
                "type": "string",
                "description": "Ollama model or cloud model identifier (e.g. 'mistral:7b', 'claude-3-5-sonnet:cloud')",
            },
            "capability": {
                "type": "string",
                "description": "Primary capability tag the agent will serve (e.g. 'translate', 'code_review')",
            },
            "reason": {
                "type": "string",
                "description": "Why the hire is needed — surfaced in approval UI",
            },
            "suggested_skills": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of agent_skills entries to seed. Defaults to [capability].",
            },
            "requested_by": {
                "type": "string",
                "default": "mcp_client",
                "description": "Identifier for the caller (agent name or tool)",
            },
        },
        "required": ["name", "display_name", "department", "model", "capability", "reason"],
    },
    handler=propose_hire_handler,
    requires_permission="write",
)


# ============================================================================
# TOOL 12: DELEGATE TASK (Archie-as-delegate — Project #276 Phase 1)
# ============================================================================


async def delegate_task_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Hand work to A.R.C.H.I.E. by capability tag.

    Claude (or anyone with MCP write access) delegates a task. It is
    persisted into unified_tasks with delegation_source set; the
    agent-loop worker ``_run_delegate_task_worker`` picks it up and
    routes to the right executor — either a known-tool shortcut or the
    DHQ dispatcher. No cloud escalation bypasses C.R.E.E.D./approval
    gates.

    Project #276 Task #2207.
    """
    capability = arguments.get("capability")
    reason = arguments.get("reason")
    args = arguments.get("args") or {}
    delegation_source = arguments.get("delegation_source", "claude")
    requested_by = arguments.get("requested_by", "mcp_client")
    streaming_channel = arguments.get("streaming_channel")
    priority = int(arguments.get("priority", 5) or 5)
    project_id = arguments.get("project_id")

    if not capability:
        return {"success": False, "error": "capability is required"}
    if not reason:
        return {"success": False, "error": "reason is required"}

    try:
        from services.delegation_service import delegate_task

        return delegate_task(
            capability=capability,
            reason=reason,
            args=args,
            delegation_source=delegation_source,
            requested_by=requested_by,
            streaming_channel=streaming_channel,
            priority=priority,
            project_id=project_id,
        )
    except Exception as e:
        logger.error(f"Error in delegate_task: {e}")
        return {"success": False, "error": str(e)}


register_tool(
    name="delegate_task",
    category="ai_command",
    description="""Hand a task to A.R.C.H.I.E. for execution by her agents.

Enables Claude → Archie delegation: Claude drops a capability + args + reason,
Archie's worker loop picks it up and routes to the right executor. Known
capabilities (run_qa_suite, run_misroute_audit, check_dep_drift, health_check,
run_misroute_to_proposal_adapter) invoke the service directly. Everything else
flows through the Department HQ dispatcher with full welfare, agent-selection,
C.R.E.E.D. governance, and cost tracking.

Rule: NO cloud escalation bypasses approval gates. Cost visibility matches
any other dispatched work.

Example: delegate run_qa_suite on the autonomy module while Claude works on
something else:
  capability='run_qa_suite', args={'module':'autonomy'},
  reason='Verify PR #243 landed cleanly', delegation_source='claude'

Typical polling: the caller re-reads the task row (by returned task_id) to
check status. Streaming to Telegram/Comms is handled by Phase 3 of #276.
""",
    input_schema={
        "type": "object",
        "properties": {
            "capability": {
                "type": "string",
                "description": (
                    "The capability tag. Known-tool capabilities (run_qa_suite, "
                    "run_misroute_audit, check_dep_drift, health_check, "
                    "run_misroute_to_proposal_adapter) invoke services directly. "
                    "Unknown tags flow through the DHQ dispatcher."
                ),
            },
            "reason": {
                "type": "string",
                "description": "Why the delegation is needed — surfaces in streaming channel + work_notes",
            },
            "args": {
                "type": "object",
                "description": "Capability-specific arguments dict (e.g. {'suite_name': 'autonomy'} for run_qa_suite)",
            },
            "delegation_source": {
                "type": "string",
                "enum": ["claude", "user_cli", "telegram", "web_chat", "mcp_client", "automation"],
                "default": "claude",
                "description": "Who is delegating. Used for routing and analytics.",
            },
            "requested_by": {
                "type": "string",
                "default": "mcp_client",
                "description": "Identifier for the caller (agent name, user name, or tool)",
            },
            "streaming_channel": {
                "type": "string",
                "description": "Optional target for progress streaming: telegram:<user>, mcp:<session>, comms:<convo_id>",
            },
            "priority": {
                "type": "integer",
                "default": 5,
                "minimum": 1,
                "maximum": 10,
                "description": "Task priority (1–10, higher first)",
            },
            "project_id": {
                "type": "integer",
                "description": "Optional project ID to attach the delegated task to",
            },
        },
        "required": ["capability", "reason"],
    },
    handler=delegate_task_handler,
    requires_permission="write",
)


# ============================================================================
# TOOL: CHECK DEP DRIFT (F.O.R.G.E.)
# ============================================================================


async def check_dep_drift_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Run F.O.R.G.E. dep drift audit on demand.

    Compares platform_v2/requirements.txt against the running
    archie_platform container's pip freeze. Read-only; the scheduled
    agent-loop job writes to autonomy_loop_log and system_notifications.
    See platform_v2/services/dep_drift_service.py for the canonical
    definition.
    """
    requirements_path = arguments.get("requirements_path") or None
    try:
        from services.dep_drift_service import check_dep_drift

        result = check_dep_drift(requirements_path=requirements_path)
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Error in check_dep_drift: {e}")
        return {"success": False, "error": str(e)}


register_tool(
    name="check_dep_drift",
    category="ai_command",
    description="""Run F.O.R.G.E. dependency drift audit on demand.

Compares platform_v2/requirements.txt (source of truth) against the
running archie_platform container's pip freeze (runtime state).

Detects 3 classes:
- missing: package pinned in requirements.txt but not installed → error
  severity; a container rebuild is required.
- version_mismatch: different version installed than pinned → warning.
- unpinned_in_requirements: requirement uses >= / ~= / no pin →
  informational, never escalates severity alone.

Returns severity ('info' | 'warning' | 'error'), findings by category,
and summary_metrics. Does not write to the DB — the scheduled
forge_dep_drift agent-loop job handles logging and notifications.

Example: default → {}
Example: custom path → requirements_path='/abs/path/to/requirements.txt'
""",
    input_schema={
        "type": "object",
        "properties": {
            "requirements_path": {
                "type": "string",
                "description": "Optional override for the source-of-truth requirements file",
            },
        },
    },
    handler=check_dep_drift_handler,
    requires_permission="read",
)


# ============================================================================
# TOOL: RUN AUTO DOCUMENTATION (C.O.D.E.X.)
# ============================================================================


async def run_auto_documentation_handler(
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Force-run the C.O.D.E.X. event auto-documentation pass.

    Scans project_decisions for undocumented rows and writes a
    vault_note per ADR. Idempotent — rerunning is safe because the
    service dedups on source_type+source_id before inserting.
    """
    lookback_days = int(arguments.get("lookback_days", 30) or 30)
    max_items = int(arguments.get("max_items_per_run", 10) or 10)
    try:
        from services.codex_event_docs_service import run_event_auto_docs

        result = run_event_auto_docs(
            lookback_days=lookback_days,
            max_items_per_run=max_items,
        )
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Error in run_auto_documentation: {e}")
        return {"success": False, "error": str(e)}


register_tool(
    name="run_auto_documentation",
    category="ai_command",
    description="""Force-run C.O.D.E.X. event auto-documentation.

Scans project_decisions for rows within the lookback window that don't
yet have a matching vault_note, then generates one per undocumented
ADR and inserts into knowledge_base with source_type='codex_event_doc'.

Idempotent — safe to call repeatedly. The scheduled agent-loop job
codex_event_docs runs the same pass every 30 minutes.

Example: default 30d lookback → {}
Example: catch up on quarter → lookback_days=90, max_items_per_run=50
""",
    input_schema={
        "type": "object",
        "properties": {
            "lookback_days": {
                "type": "integer",
                "default": 30,
                "minimum": 1,
                "maximum": 365,
                "description": "How far back to scan for undocumented decisions",
            },
            "max_items_per_run": {
                "type": "integer",
                "default": 10,
                "minimum": 1,
                "maximum": 100,
                "description": "Max vault_notes to write in one invocation",
            },
        },
    },
    handler=run_auto_documentation_handler,
    requires_permission="write",
)


# ============================================================================
# TOOL: CHECK INFRA HEARTBEAT (V.I.G.I.L.)
# ============================================================================


async def check_infra_heartbeat_handler(
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Run V.I.G.I.L. infrastructure heartbeat pass on demand.

    Inspects every registered critical container via docker inspect +
    TCP/HTTP probes. Read-only; does not restart anything. The scheduled
    agent-loop job vigil_infra_heartbeat files Tier-2 restart approvals
    when a container is DOWN.
    """
    try:
        from services.infra_heartbeat_service import check_all_critical

        result = check_all_critical()
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Error in check_infra_heartbeat: {e}")
        return {"success": False, "error": str(e)}


register_tool(
    name="check_infra_heartbeat",
    category="ai_command",
    description="""Run V.I.G.I.L. infrastructure heartbeat audit on demand.

Checks every critical container in the registry (nginx_proxy_manager,
network_adguard, archie_comms, archie_comfyui, kbs_app,
kytran-system-operations, kytran_creed, media_plex, media_jellyfin) for:
- presence (catches docker rm removal — the NPM failure mode)
- running state (catches stopped)
- optional healthcheck status
- TCP port reachability + optional HTTP probe

Returns severity ('info' | 'warning' | 'error'), per-container detail
with reasons, and summary_metrics (down, warnings, healthy counts).
The scheduled agent-loop job runs the same check every 5 min and files
Tier-2 restart approvals for DOWN containers marked auto_restart_safe.

Example: default → {}
""",
    input_schema={
        "type": "object",
        "properties": {},
    },
    handler=check_infra_heartbeat_handler,
    requires_permission="read",
)


# ============================================================================
# get_system_alerts — unified query: system_notifications + director_reports
# ============================================================================


async def get_system_alerts_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Unified system alerts from notifications + escalated director_reports."""
    import sys

    sys.path.insert(0, "/mnt/archie_brain/platform_v2")
    limit = int(arguments.get("limit", 20))
    severity = arguments.get("severity") or None
    since_hours = int(arguments.get("since_hours", 24))

    alerts = []

    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT 'notification' AS source, type AS severity,
                       title, message AS detail,
                       created_at::text AS created_at
                FROM system_notifications
                WHERE created_at > NOW() - INTERVAL '%s hours'
                  AND is_read = FALSE
                  AND (%s IS NULL OR type = %s)
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (since_hours, severity, severity, limit),
            )
            alerts += [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.warning("get_system_alerts: notifications query failed: %s", e)

    try:
        from services.director_report_service import get_pending_reports

        for r in get_pending_reports(limit=limit):
            if r.get("severity") in ("critical", "high"):
                alerts.append(
                    {
                        "source": "director_report",
                        "severity": r["severity"],
                        "title": r["title"],
                        "detail": r["summary"],
                        "created_at": r.get("created_at"),
                    }
                )
    except Exception as e:
        logger.warning("get_system_alerts: director_reports query failed: %s", e)

    alerts.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    top = alerts[:limit]
    return {"success": True, "alerts": top, "count": len(top)}


register_tool(
    name="get_system_alerts",
    category="ai_command",
    description="""Unified system alerts — recent unread system_notifications + high/critical pending director_reports.

Returns alerts sorted by recency with source, severity, title, and detail.
Useful for a quick platform health scan without reading logs.

Example: last hour of critical alerts → limit=10, since_hours=1, severity='error'
Example: default (24h, all severities) → {}
""",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "default": 20,
                "description": "Max alerts to return",
            },
            "severity": {
                "type": "string",
                "description": "Filter by severity type (e.g. 'error', 'warning'). Omit for all.",
            },
            "since_hours": {
                "type": "integer",
                "default": 24,
                "description": "How many hours back to query notifications",
            },
        },
    },
    handler=get_system_alerts_handler,
    requires_permission="read",
)
