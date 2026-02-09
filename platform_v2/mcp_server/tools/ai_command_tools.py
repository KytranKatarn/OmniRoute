"""
A.R.C.H.I.E. MCP Server - AI Command Tools
P1 MCP Tool Expansion: AI Command Category

Tools for agent performance, ethics monitoring, LLM health,
node status, shift scheduling, and skills matrix.
All read-only, direct DB queries.
"""

import os
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
    "password": os.getenv("DB_PASSWORD", "archie_secure_2024"),
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
            return {"success": False, "error": "Provide agent_id for single mode, or use mode=leaderboard"}

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
            "agent_id": {"type": "integer", "description": "Agent ID (required for single mode)"},
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
            "agent_id": {"type": "integer", "description": "Filter by specific agent (optional)"},
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
            return {"success": False, "error": f"Unknown action: {action}. Use 'list' or 'on_duty'"}

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
            return {"success": False, "error": f"Unknown mode: {mode}. Use 'matrix' or 'gaps'"}

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
