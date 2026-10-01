"""
A.R.C.H.I.E. MCP Server - Admin & Team Tools
Phase 50.5: AI Integration Hub

Tools for managing agents, system status, improvements, backups,
and analytics via Model Context Protocol.
"""

import os
from database import _get_db_password
import json
import logging
import psycopg2
import subprocess
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import Dict, Any, List

from . import register_tool, cap_limit, internal_api

logger = logging.getLogger("archie_mcp.tools.admin")

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


# ============================================================================
# ASSIGN AGENT TOOL
# ============================================================================


async def assign_agent_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assign an agent to a bridge station

    Manages team assignments across the 10 bridge stations:
    - Command, Consciousness, HR, R&D, Operations
    - Engineering, Creative, Security, Medical, Away Team
    """
    agent_id = arguments.get("agent_id")
    station_code = arguments.get("station_code")
    arguments.get("assignment_type", "primary")
    arguments.get("shift_preference", "any")
    arguments.get("notes", "")
    arguments.get("user_id", 2)  # Default to admin

    if not agent_id or not station_code:
        return {"success": False, "error": "agent_id and station_code are required"}

    # station_assignments table dropped — agents belong to departments via agents.department
    return {
        "success": False,
        "error": "Station assignments have been replaced by department membership. Use Department HQ to manage agent departments.",
        "deprecated": True,
    }


register_tool(
    name="assign_agent",
    category="admin",
    description="""Assign an AI agent to a bridge station.

Available stations: COMMAND, CONSCIOUSNESS, HR, RND, OPERATIONS,
ENGINEERING, CREATIVE, SECURITY, MEDICAL, AWAY_TEAM

Assignment types: primary, backup, trainee
Shift preferences: any, morning, afternoon, evening, night

Example: Assign agent 15 to Engineering as primary
""",
    input_schema={
        "type": "object",
        "properties": {
            "agent_id": {"type": "integer", "description": "ID of the agent to assign"},
            "station_code": {
                "type": "string",
                "description": "Station code (e.g., ENGINEERING, CREATIVE)",
                "enum": [
                    "COMMAND",
                    "CONSCIOUSNESS",
                    "HR",
                    "RND",
                    "OPERATIONS",
                    "ENGINEERING",
                    "CREATIVE",
                    "SECURITY",
                    "MEDICAL",
                    "AWAY_TEAM",
                ],
            },
            "assignment_type": {
                "type": "string",
                "enum": ["primary", "backup", "trainee"],
                "default": "primary",
            },
            "shift_preference": {
                "type": "string",
                "enum": ["any", "morning", "afternoon", "evening", "night"],
                "default": "any",
            },
            "notes": {"type": "string", "description": "Optional assignment notes"},
        },
        "required": ["agent_id", "station_code"],
    },
    handler=assign_agent_handler,
    requires_permission="write",
)


# ============================================================================
# UNASSIGN AGENT TOOL
# ============================================================================


async def unassign_agent_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove an agent from their current station assignment
    """
    agent_id = arguments.get("agent_id")

    if not agent_id:
        return {"success": False, "error": "agent_id is required"}

    # station_assignments table dropped — agents belong to departments via agents.department
    return {
        "success": False,
        "error": "Station assignments have been replaced by department membership. Use Department HQ to manage agent departments.",
        "deprecated": True,
        "agent_id": agent_id,
    }


register_tool(
    name="unassign_agent",
    category="admin",
    description="""Remove an agent from their current bridge station assignment.

Note: Fixed assignments (ARCHIE, Kytran on Command) cannot be removed.
""",
    input_schema={
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "integer",
                "description": "ID of the agent to unassign",
            }
        },
        "required": ["agent_id"],
    },
    handler=unassign_agent_handler,
    requires_permission="write",
)


# ============================================================================
# GET SYSTEM STATUS TOOL
# ============================================================================


async def get_system_status_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get comprehensive A.R.C.H.I.E. platform status

    Returns counts and health metrics for:
    - Agents (active, total, by department)
    - Bridge stations (assignments, coverage)
    - Improvements (by status)
    - Knowledge base stats
    - Recent activity
    """
    include_details = arguments.get("include_details", False)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        status = {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "platform": "A.R.C.H.I.E. v5.0",
            "sections": {},
        }

        # Agent statistics + department coverage come from the hub's scoped
        # internal API (scope agents:read). This lane's DB role has no grant on
        # `agents`, so querying it directly raised InFailedSqlTransaction and
        # failed the entire tool — including the sections that DO work. limit=1:
        # we only want `total` and the facets, not the roster.
        roster = internal_api("/api/internal/agents", params={"limit": 1})
        if roster.get("ok"):
            facets = roster["data"].get("facets", {}) or {}
            states = facets.get("states", {}) or {}
            by_department = facets.get("departments", {}) or {}
            status["sections"]["agents"] = {
                "total": roster["data"].get("total"),
                "active": states.get("active"),
                "inactive": states.get("off_duty"),
                "training": states.get("training"),
                "by_state": states,
                "by_department": [
                    {"department": dept, "count": count}
                    for dept, count in sorted(by_department.items(), key=lambda kv: -kv[1])
                ],
                "source": "/api/internal/agents",
            }
            status["sections"]["stations"] = {
                "total": len(by_department),
                "coverage": [
                    {"department": dept, "agent_count": count} for dept, count in sorted(by_department.items())
                ],
                "empty": [],
                "note": "Derived from agent departments; bridge_stations is not readable by this lane.",
            }
        else:
            status["sections"]["agents"] = {
                "error": roster.get("error", "roster read failed"),
                "source": "/api/internal/agents",
            }

        # Each remaining section is independent: a table this lane cannot read
        # degrades that one section instead of failing the whole report. The
        # rollback is load-bearing — psycopg2 leaves the transaction aborted
        # after a permission error, so without it every later section would
        # fail with InFailedSqlTransaction even when its table IS readable.
        def _section(name: str, query: str, build):
            try:
                cur.execute(query)
                status["sections"][name] = build(cur.fetchall())
            except Exception as exc:
                logger.warning(f"get_system_status: section '{name}' unavailable: {exc}")
                try:
                    conn.rollback()
                except Exception:
                    pass
                status["sections"][name] = {"error": "not readable by this lane", "detail": str(exc).split("\n")[0]}

        _section(
            "improvements",
            "SELECT status, COUNT(*) as count FROM improvement_proposals GROUP BY status",
            lambda rows: {
                "total": sum(r["count"] for r in rows),
                "by_status": {r["status"]: r["count"] for r in rows},
            },
        )

        _section(
            "knowledge",
            "SELECT knowledge_type, COUNT(*) as count FROM knowledge_base GROUP BY knowledge_type",
            lambda rows: {
                "total": sum(r["count"] for r in rows),
                "by_type": {r["knowledge_type"]: r["count"] for r in rows},
            },
        )

        _section(
            "activity_24h",
            """
            SELECT
                COUNT(*) as api_calls,
                COALESCE(SUM(prompt_tokens + completion_tokens), 0) as tokens
            FROM token_usage_log
            WHERE created_at > NOW() - INTERVAL '24 hours'
            """,
            lambda rows: {
                "api_calls": rows[0]["api_calls"],
                "tokens_used": int(rows[0]["tokens"]),
            },
        )

        if include_details:
            _section(
                "recent_improvements",
                "SELECT id, title, status, priority, proposed_at FROM improvement_proposals ORDER BY proposed_at DESC LIMIT 5",
                lambda rows: [dict(r) for r in rows],
            )
            _section(
                "recent_backups",
                "SELECT id, backup_type, status, file_size_bytes, created_at FROM backup_log ORDER BY created_at DESC LIMIT 5",
                lambda rows: [dict(r) for r in rows],
            )

        return status

    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_system_status",
    category="admin",
    description="""Get comprehensive A.R.C.H.I.E. platform status.

Returns metrics for:
- Agents (active, inactive, training, by department)
- Bridge stations (assignments, coverage)
- Improvement proposals (by status)
- Knowledge base statistics
- 24-hour activity metrics

Set include_details=true for recent improvements and backups.
""",
    input_schema={
        "type": "object",
        "properties": {
            "include_details": {
                "type": "boolean",
                "description": "Include recent improvements and backups",
                "default": False,
            }
        },
    },
    handler=get_system_status_handler,
    requires_permission="read",
)


# ============================================================================
# LIST AGENTS TOOL
# ============================================================================


async def list_agents_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    List all agents with optional filtering
    """
    # `or "active"`, not `.get("status", "active")`: the MCP client sends an explicit
    # null for an omitted optional arg, which a two-arg get treats as a real value and
    # so silently disables the documented default filter.
    status_filter = arguments.get("status") or "active"
    department = arguments.get("department")
    station_code = arguments.get("station_code")
    limit = cap_limit(arguments, 50, 100)

    # Read the roster through the hub's scoped internal API rather than the DB.
    # This lane's role is codex_ro, which has no grant on `agents` or
    # `bridge_stations`, so the previous direct query failed with "permission
    # denied for table agents" on every call. /api/internal/agents is the
    # intended path (scope: agents:read) and needs no new credential.
    params: Dict[str, Any] = {"limit": limit}
    if department:
        params["department"] = department

    result = internal_api("/api/internal/agents", params=params)
    if not result.get("ok"):
        return {
            "success": False,
            "error": result.get("error", "internal agents read failed"),
            "hint": "The roster is served by /api/internal/agents (scope agents:read).",
        }

    payload = result["data"]
    rows = payload.get("agents", []) or []

    # The roster endpoint filters on shift_state, not the legacy `status`
    # column, and does not expose bridge_stations. Apply what we can here and
    # say plainly what could not be honoured rather than silently ignoring it.
    notes: List[str] = []
    if status_filter and status_filter != "all":
        kept = [a for a in rows if a.get("shift_state") == status_filter]
        if len(kept) != len(rows):
            rows = kept
        if status_filter in ("inactive", "training"):
            notes.append(
                f"status='{status_filter}' has no shift_state equivalent; filtered on "
                f"shift_state instead (available: {payload.get('facets', {}).get('states', {})})."
            )
    if station_code:
        notes.append(
            f"station_code='{station_code}' cannot be filtered: the roster endpoint does not "
            "expose bridge_stations. Use department, which maps to the station name."
        )

    agents = [
        {
            "id": a.get("id"),
            "name": a.get("name"),
            "title": a.get("title"),
            "department": a.get("department"),
            "shift_state": a.get("shift_state"),
            "model": a.get("model"),
            "worker_type": a.get("worker_type"),
            "is_department_ai": a.get("is_department_ai"),
            "performance_score": a.get("performance_score"),
            "success_rate": a.get("success_rate"),
            "last_used": a.get("last_used"),
        }
        for a in rows
    ]

    out = {
        "success": True,
        "count": len(agents),
        "total": payload.get("total"),
        "filters": {
            "status": status_filter,
            "department": department,
            "station_code": station_code,
        },
        "agents": agents,
    }
    if notes:
        out["notes"] = notes
    return out


register_tool(
    name="list_agents",
    category="admin",
    description="""List AI agents with optional filtering.

Filter by:
- status: active, inactive, training, or 'all'
- department: Engineering, Creative, Operations, etc.
- station_code: COMMAND, ENGINEERING, CREATIVE, etc.
""",
    input_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["active", "inactive", "training", "all"],
                "default": "active",
            },
            "department": {"type": "string", "description": "Filter by department"},
            "station_code": {
                "type": "string",
                "description": "Filter by assigned station",
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 50, max 100)",
                "default": 50,
            },
        },
    },
    handler=list_agents_handler,
    requires_permission="read",
)


# ============================================================================
# RUN IMPROVEMENT TOOL
# ============================================================================


async def run_improvement_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Manage improvement proposals - create, list, update status
    """
    action = arguments.get("action", "list")

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        if action == "list":
            status_filter = arguments.get("status", "all")
            limit = cap_limit(arguments, 20, 50)

            query = """
                SELECT id, title, description, category, priority, status,
                       proposed_at, risk_level, complexity, sandbox_tested
                FROM improvement_proposals
                WHERE 1=1
            """
            params = []

            if status_filter != "all":
                query += " AND status = %s"
                params.append(status_filter)

            query += " ORDER BY proposed_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)
            improvements = [dict(r) for r in cur.fetchall()]

            return {
                "success": True,
                "action": "list",
                "count": len(improvements),
                "improvements": improvements,
            }

        elif action == "create":
            title = arguments.get("title")
            description = arguments.get("description", "")
            category = arguments.get("category", "enhancement")
            priority = arguments.get("priority", "medium")
            risk_level = arguments.get("risk_level", "medium")
            user_id = arguments.get("user_id", 2)

            if not title:
                return {"success": False, "error": "title is required"}

            cur.execute(
                """
                INSERT INTO improvement_proposals
                (title, description, category, priority, status, risk_level, proposed_by)
                VALUES (%s, %s, %s, %s, 'proposed', %s, %s)
                RETURNING id
            """,
                (title, description, category, priority, risk_level, user_id),
            )

            improvement_id = cur.fetchone()["id"]
            conn.commit()

            return {
                "success": True,
                "action": "create",
                "improvement_id": improvement_id,
                "title": title,
                "status": "proposed",
            }

        elif action == "update_status":
            improvement_id = arguments.get("improvement_id")
            new_status = arguments.get("new_status")
            notes = arguments.get("notes", "")

            if not improvement_id or not new_status:
                return {
                    "success": False,
                    "error": "improvement_id and new_status required",
                }

            valid_statuses = [
                "proposed",
                "approved",
                "in_progress",
                "testing",
                "deployed",
                "rejected",
                "on_hold",
            ]
            if new_status not in valid_statuses:
                return {
                    "success": False,
                    "error": f"Invalid status. Must be one of: {valid_statuses}",
                }

            # Update based on status
            updates = ["status = %s", "notes = COALESCE(notes, '') || %s"]
            params = [
                new_status,
                f"\n[{datetime.now().isoformat()}] Status -> {new_status}: {notes}",
            ]

            if new_status == "approved":
                updates.append("approved_at = NOW()")
            elif new_status == "in_progress":
                updates.append("reviewed_at = NOW()")
            elif new_status == "deployed":
                updates.append("deployed_at = NOW()")
            elif new_status == "testing":
                updates.append("test_started_at = NOW()")
                updates.append("test_status = 'running'")

            query = f"""
                UPDATE improvement_proposals
                SET {', '.join(updates)}
                WHERE id = %s
                RETURNING id, title, status
            """
            params.append(improvement_id)

            cur.execute(query, params)
            result = cur.fetchone()

            if not result:
                return {
                    "success": False,
                    "error": f"Improvement {improvement_id} not found",
                }

            conn.commit()

            return {
                "success": True,
                "action": "update_status",
                "improvement": dict(result),
            }

        elif action == "get":
            improvement_id = arguments.get("improvement_id")

            if not improvement_id:
                return {"success": False, "error": "improvement_id required"}

            cur.execute(
                """
                SELECT * FROM improvement_proposals
                WHERE id = %s
            """,
                (improvement_id,),
            )
            improvement = cur.fetchone()

            if not improvement:
                return {
                    "success": False,
                    "error": f"Improvement {improvement_id} not found",
                }

            return {"success": True, "action": "get", "improvement": dict(improvement)}

        else:
            return {
                "success": False,
                "error": f"Unknown action: {action}. Use: list, create, update_status, get",
            }

    except Exception as e:
        conn.rollback()
        logger.error(f"Error in improvement operation: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="run_improvement",
    category="admin",
    description="""Manage improvement proposals for the A.R.C.H.I.E. platform.

Actions:
- list: List improvements (filter by status)
- create: Create new improvement proposal
- update_status: Change status (proposed, approved, in_progress, testing, deployed, rejected, on_hold)
- get: Get full details of an improvement

Example: Create a new feature proposal for better search
""",
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "update_status", "get"],
                "default": "list",
            },
            "improvement_id": {
                "type": "integer",
                "description": "For update_status or get actions",
            },
            "status": {
                "type": "string",
                "description": "For list action - filter by status",
                "enum": [
                    "all",
                    "proposed",
                    "approved",
                    "in_progress",
                    "testing",
                    "deployed",
                    "rejected",
                ],
            },
            "new_status": {"type": "string", "description": "For update_status action"},
            "title": {"type": "string", "description": "For create action"},
            "description": {"type": "string", "description": "For create action"},
            "category": {
                "type": "string",
                "enum": [
                    "enhancement",
                    "bugfix",
                    "feature",
                    "refactor",
                    "security",
                    "performance",
                ],
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "critical"],
            },
            "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
            "notes": {"type": "string", "description": "For update_status action"},
            "limit": {"type": "integer", "default": 20},
        },
    },
    handler=run_improvement_handler,
    requires_permission="write",
)


# ============================================================================
# MANAGE BACKUP TOOL
# ============================================================================


async def manage_backup_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Manage system backups - list history and create new backups
    """
    action = arguments.get("action", "list")

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        if action == "list":
            limit = cap_limit(arguments, 20, 50)
            status_filter = arguments.get("status")

            query = """
                SELECT id, backup_type, file_path, file_size_bytes, status,
                       created_at, completed_at, error_message
                FROM backup_log
                WHERE 1=1
            """
            params = []

            if status_filter:
                query += " AND status = %s"
                params.append(status_filter)

            query += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)
            backups = []
            for r in cur.fetchall():
                backup = dict(r)
                # Format file size
                if backup.get("file_size_bytes"):
                    size_mb = backup["file_size_bytes"] / (1024 * 1024)
                    backup["file_size_formatted"] = f"{size_mb:.2f} MB"
                backups.append(backup)

            return {
                "success": True,
                "action": "list",
                "count": len(backups),
                "backups": backups,
            }

        elif action == "create":
            backup_type = arguments.get("backup_type", "full")
            user_id = arguments.get("user_id", 2)

            # Create backup log entry
            cur.execute(
                """
                INSERT INTO backup_log (backup_type, status, created_by)
                VALUES (%s, 'pending', %s)
                RETURNING id
            """,
                (backup_type, user_id),
            )
            backup_id = cur.fetchone()["id"]
            conn.commit()

            # Note: Actual backup would be triggered via backup_manager
            # This creates the tracking record
            return {
                "success": True,
                "action": "create",
                "backup_id": backup_id,
                "backup_type": backup_type,
                "status": "pending",
                "message": "Backup job created. Use backup_manager UI to execute.",
            }

        elif action == "status":
            backup_id = arguments.get("backup_id")

            if not backup_id:
                return {"success": False, "error": "backup_id required"}

            cur.execute(
                """
                SELECT * FROM backup_log WHERE id = %s
            """,
                (backup_id,),
            )
            backup = cur.fetchone()

            if not backup:
                return {"success": False, "error": f"Backup {backup_id} not found"}

            return {"success": True, "action": "status", "backup": dict(backup)}

        else:
            return {
                "success": False,
                "error": f"Unknown action: {action}. Use: list, create, status",
            }

    except Exception as e:
        conn.rollback()
        logger.error(f"Error in backup operation: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="manage_backup",
    category="admin",
    description="""Manage A.R.C.H.I.E. system backups.

Actions:
- list: List backup history (filter by status: pending, running, completed, failed)
- create: Create a new backup job (types: full, database, files, config)
- status: Get status of a specific backup

Note: Actual backup execution happens via the Backup Manager UI.
""",
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "status"],
                "default": "list",
            },
            "backup_id": {"type": "integer", "description": "For status action"},
            "backup_type": {
                "type": "string",
                "enum": ["full", "database", "files", "config"],
                "default": "full",
            },
            "status": {
                "type": "string",
                "description": "For list action - filter",
                "enum": ["pending", "running", "completed", "failed"],
            },
            "limit": {"type": "integer", "default": 20},
        },
    },
    handler=manage_backup_handler,
    requires_permission="write",
)


# ============================================================================
# VIEW ANALYTICS TOOL
# ============================================================================


async def view_analytics_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    View platform analytics - token usage, costs, activity trends
    """
    period = arguments.get("period", "24h")
    metric_type = arguments.get("metric_type", "overview")

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Parse period
        period_map = {
            "1h": timedelta(hours=1),
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
        }
        interval = period_map.get(period, timedelta(hours=24))

        analytics = {
            "success": True,
            "period": period,
            "metric_type": metric_type,
            "timestamp": datetime.now().isoformat(),
        }

        if metric_type in ["overview", "tokens"]:
            # Token usage
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_calls,
                    COALESCE(SUM(prompt_tokens), 0) as input_tokens,
                    COALESCE(SUM(completion_tokens), 0) as output_tokens,
                    COALESCE(SUM(prompt_tokens + completion_tokens), 0) as total_tokens,
                    COALESCE(SUM(cost), 0) as total_cost
                FROM token_usage_log
                WHERE created_at > NOW() - %s
            """,
                (interval,),
            )
            token_stats = dict(cur.fetchone())

            # Convert to native Python types
            analytics["tokens"] = {
                "total_calls": int(token_stats["total_calls"]),
                "input_tokens": int(token_stats["input_tokens"]),
                "output_tokens": int(token_stats["output_tokens"]),
                "total_tokens": int(token_stats["total_tokens"]),
                "total_cost": float(token_stats["total_cost"]),
            }

        if metric_type in ["overview", "models"]:
            # Usage by model
            cur.execute(
                """
                SELECT
                    model,
                    COUNT(*) as calls,
                    COALESCE(SUM(prompt_tokens + completion_tokens), 0) as tokens,
                    COALESCE(SUM(cost), 0) as cost
                FROM token_usage_log
                WHERE created_at > NOW() - %s
                GROUP BY model
                ORDER BY calls DESC
                LIMIT 10
            """,
                (interval,),
            )

            analytics["by_model"] = []
            for r in cur.fetchall():
                analytics["by_model"].append(
                    {
                        "model": r["model"],
                        "calls": int(r["calls"]),
                        "tokens": int(r["tokens"]),
                        "cost": float(r["cost"]),
                    }
                )

        if metric_type in ["overview", "agents"]:
            # Usage by agent
            cur.execute(
                """
                SELECT
                    a.name as agent_name,
                    t.agent_id,
                    COUNT(*) as calls,
                    COALESCE(SUM(t.prompt_tokens + t.completion_tokens), 0) as tokens
                FROM token_usage_log t
                LEFT JOIN agents a ON t.agent_id = a.id
                WHERE t.created_at > NOW() - %s AND t.agent_id IS NOT NULL
                GROUP BY t.agent_id, a.name
                ORDER BY calls DESC
                LIMIT 10
            """,
                (interval,),
            )

            analytics["by_agent"] = []
            for r in cur.fetchall():
                analytics["by_agent"].append(
                    {
                        "agent_id": r["agent_id"],
                        "agent_name": r["agent_name"] or "Unknown",
                        "calls": int(r["calls"]),
                        "tokens": int(r["tokens"]),
                    }
                )

        if metric_type in ["overview", "hourly"]:
            # Hourly trend (last 24 hours)
            cur.execute(
                """
                SELECT
                    date_trunc('hour', created_at) as hour,
                    COUNT(*) as calls,
                    COALESCE(SUM(prompt_tokens + completion_tokens), 0) as tokens
                FROM token_usage_log
                WHERE created_at > NOW() - INTERVAL '24 hours'
                GROUP BY hour
                ORDER BY hour
            """
            )

            analytics["hourly_trend"] = []
            for r in cur.fetchall():
                analytics["hourly_trend"].append(
                    {
                        "hour": r["hour"].isoformat() if r["hour"] else None,
                        "calls": int(r["calls"]),
                        "tokens": int(r["tokens"]),
                    }
                )

        return analytics

    except Exception as e:
        logger.error(f"Error getting analytics: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="view_analytics",
    category="admin",
    description="""View A.R.C.H.I.E. platform analytics.

Periods: 1h, 24h, 7d, 30d
Metric types:
- overview: All metrics combined
- tokens: Token usage and costs
- models: Usage broken down by AI model
- agents: Usage broken down by agent
- hourly: Hourly trend for last 24h

Example: Get 7-day token usage overview
""",
    input_schema={
        "type": "object",
        "properties": {
            "period": {
                "type": "string",
                "enum": ["1h", "24h", "7d", "30d"],
                "default": "24h",
            },
            "metric_type": {
                "type": "string",
                "enum": ["overview", "tokens", "models", "agents", "hourly"],
                "default": "overview",
            },
        },
    },
    handler=view_analytics_handler,
    requires_permission="read",
)


# ============================================================================
# GET STATION ASSIGNMENTS TOOL
# ============================================================================


async def get_station_assignments_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get current bridge station assignments
    """
    station_code = arguments.get("station_code")
    include_empty = arguments.get("include_empty", True)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        if station_code:
            # Get specific station
            cur.execute(
                """
                -- station_assignments was DROPPED; a station's crew is now derived from
                -- bridge_stations.station_name = agents.department, and the station's
                -- primary is the department AI. assignment_type/shift_preference/
                -- is_fixed/role_type lived only on the dropped table, so they are
                -- reported from the surviving model rather than invented.
                SELECT
                    bs.id, bs.station_code, bs.station_name, bs.color, bs.icon,
                    a.id as agent_id, a.name as agent_name, a.title as agent_title,
                    a.department, a.status as agent_status,
                    a.is_department_ai, a.shift_state
                FROM bridge_stations bs
                LEFT JOIN agents a
                       ON a.department = bs.station_name
                      AND a.worker_type = 'ai'
                      AND a.status = 'active'
                WHERE bs.station_code = %s AND bs.is_active = TRUE
                ORDER BY a.is_department_ai DESC NULLS LAST, a.name
            """,
                (station_code.upper(),),
            )
            results = cur.fetchall()

            if not results:
                return {
                    "success": False,
                    "error": f"Station '{station_code}' not found",
                }

            station_info = {
                "id": results[0]["id"],
                "code": results[0]["station_code"],
                "name": results[0]["station_name"],
                "color": results[0]["color"],
                "icon": results[0]["icon"],
                "agents": [],
            }

            for r in results:
                if r["agent_id"]:
                    station_info["agents"].append(
                        {
                            "id": r["agent_id"],
                            "name": r["agent_name"],
                            "title": r["agent_title"],
                            "department": r["department"],
                            "status": r["agent_status"],
                            # The department AI is the station's primary; every other
                            # agent in the department is auxiliary. This replaces the
                            # dropped station_assignments.assignment_type.
                            "assignment_type": ("primary" if r["is_department_ai"] else "auxiliary"),
                            "is_department_ai": bool(r["is_department_ai"]),
                            "shift_state": r["shift_state"],
                        }
                    )

            return {"success": True, "station": station_info}

        else:
            # Get all stations
            cur.execute(
                """
                -- agent_count now counts the station's department crew (see above).
                SELECT
                    bs.id, bs.station_code, bs.station_name, bs.color, bs.icon,
                    COUNT(a.id) as agent_count
                FROM bridge_stations bs
                LEFT JOIN agents a
                       ON a.department = bs.station_name
                      AND a.worker_type = 'ai'
                      AND a.status = 'active'
                WHERE bs.is_active = TRUE
                GROUP BY bs.id
                ORDER BY bs.id
            """
            )

            stations = []
            for r in cur.fetchall():
                if include_empty or r["agent_count"] > 0:
                    stations.append(
                        {
                            "id": r["id"],
                            "code": r["station_code"],
                            "name": r["station_name"],
                            "color": r["color"],
                            "icon": r["icon"],
                            "agent_count": r["agent_count"],
                        }
                    )

            return {
                "success": True,
                "total_stations": len(stations),
                "stations": stations,
            }

    except Exception as e:
        logger.error(f"Error getting station assignments: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_station_assignments",
    category="admin",
    description="""Get bridge station assignments overview.

Without station_code: Returns all 10 stations with agent counts
With station_code: Returns detailed agent list for that station

Stations: COMMAND, CONSCIOUSNESS, HR, RND, OPERATIONS,
ENGINEERING, CREATIVE, SECURITY, MEDICAL, AWAY_TEAM
""",
    input_schema={
        "type": "object",
        "properties": {
            "station_code": {
                "type": "string",
                "description": "Get specific station details",
            },
            "include_empty": {
                "type": "boolean",
                "description": "Include stations with no agents",
                "default": True,
            },
        },
    },
    handler=get_station_assignments_handler,
    requires_permission="read",
)


# ============================================================================
# RUN BACKUP TOOL - Actually execute backups
# ============================================================================


async def run_backup_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute actual system backup (not just log entry)

    Creates a full backup including database, platform files, docs, etc.
    Runs backup inside Docker container via docker exec.
    """
    description = arguments.get("description", "MCP automated backup")
    # Sanitize description for shell safety
    safe_description = description.replace("'", "").replace('"', "").replace(";", "").replace("&", "")[:50]

    try:
        # Execute backup inside Docker container
        cmd = [
            "docker",
            "exec",
            "archie_platform",
            "python3",
            "-c",
            f"""
import sys
sys.path.insert(0, '/app')
import json
from tools.backup_manager.backup_manager_routes import create_backup_programmatic
result = create_backup_programmatic("{safe_description}", "mcp_system")
print(json.dumps(result, default=str))
""",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            return {"success": False, "error": f"Docker exec failed: {result.stderr}"}

        if not result.stdout.strip():
            return {"success": False, "error": "Backup command produced no output"}

        # Parse the JSON output
        try:
            backup_result = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": f"Failed to parse backup result: {result.stdout}",
            }

        if backup_result.get("success"):
            return {
                "success": True,
                "message": f"Backup created successfully (Build #{backup_result.get('build_number')})",
                "backup_name": backup_result.get("backup_name"),
                "backup_path": backup_result.get("backup_path"),
                "build_number": backup_result.get("build_number"),
                "platform_version": backup_result.get("backup", {}).get("platform_version"),
                "components": backup_result.get("backup", {}).get("components", {}),
            }
        else:
            return {
                "success": False,
                "error": backup_result.get("error", "Unknown backup error"),
            }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Backup timed out after 5 minutes"}
    except Exception as e:
        logger.error(f"Error running backup: {e}")
        return {"success": False, "error": str(e)}


register_tool(
    name="run_backup",
    category="admin",
    description="""Execute actual system backup (database + platform files).

Creates a comprehensive backup including:
- Database (all tables)
- Platform code (tools, templates, static files)
- AI bridge code
- Documentation
- N8N workflows
- Scripts and configuration

Returns backup name, path, and build number on success.

Example: Create a backup before making changes
""",
    input_schema={
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Description for this backup (will be part of backup name)",
                "default": "MCP automated backup",
            }
        },
    },
    handler=run_backup_handler,
    requires_permission="admin",
)


logger.info(
    "Admin tools registered: assign_agent, unassign_agent, get_system_status, "
    "list_agents, run_improvement, manage_backup, run_backup, view_analytics, get_station_assignments"
)
