"""
A.R.C.H.I.E. MCP Server - Advanced Tools
Phase 50.6: AI Integration Hub

Tools for workflows, rate limiting, audit logging, and health checks
via Model Context Protocol.
"""

import os
from database import _get_db_password
import json
import logging
import psycopg2
import subprocess
import socket
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import Dict, Any

from . import register_tool

logger = logging.getLogger("archie_mcp.tools.advanced")

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
# WORKFLOW TOOLS
# ============================================================================


async def list_workflows_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    List available agent workflows
    """
    status_filter = arguments.get("status", "active")
    trigger_type = arguments.get("trigger_type")
    limit = min(arguments.get("limit", 20), 50)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        query = """
            SELECT id, name, description, trigger_type, trigger_config,
                   status, created_at, updated_at
            FROM agent_workflows
            WHERE 1=1
        """
        params = []

        if status_filter and status_filter != "all":
            query += " AND status = %s"
            params.append(status_filter)

        if trigger_type:
            query += " AND trigger_type = %s"
            params.append(trigger_type)

        query += " ORDER BY name LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        workflows = [dict(r) for r in cur.fetchall()]

        return {"success": True, "count": len(workflows), "workflows": workflows}

    except Exception as e:
        logger.error(f"Error listing workflows: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="list_workflows",
    category="advanced",
    description="""List available agent workflows.

Filter by:
- status: active, inactive, or 'all'
- trigger_type: manual, scheduled, event, webhook

Returns workflow definitions with trigger configurations.
""",
    input_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["active", "inactive", "all"],
                "default": "active",
            },
            "trigger_type": {
                "type": "string",
                "enum": ["manual", "scheduled", "event", "webhook"],
            },
            "limit": {"type": "integer", "default": 20},
        },
    },
    handler=list_workflows_handler,
    requires_permission="read",
)


async def trigger_workflow_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Trigger execution of a workflow
    """
    workflow_id = arguments.get("workflow_id")
    workflow_name = arguments.get("workflow_name")
    input_data = arguments.get("input_data", {})
    agent_id = arguments.get("agent_id")
    user_id = arguments.get("user_id", 2)

    if not workflow_id and not workflow_name:
        return {"success": False, "error": "workflow_id or workflow_name required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Find workflow
        if workflow_id:
            cur.execute(
                """
                SELECT id, name, status, workflow_definition
                FROM agent_workflows WHERE id = %s
            """,
                (workflow_id,),
            )
        else:
            cur.execute(
                """
                SELECT id, name, status, workflow_definition
                FROM agent_workflows WHERE name = %s
            """,
                (workflow_name,),
            )

        workflow = cur.fetchone()

        if not workflow:
            return {"success": False, "error": "Workflow not found"}

        if workflow["status"] != "active":
            return {
                "success": False,
                "error": f"Workflow '{workflow['name']}' is not active (status: {workflow['status']})",
            }

        # Create execution record
        cur.execute(
            """
            INSERT INTO workflow_executions
            (workflow_id, agent_id, user_id, status, execution_log)
            VALUES (%s, %s, %s, 'running', %s)
            RETURNING id
        """,
            (
                workflow["id"],
                agent_id,
                user_id,
                json.dumps({"input": input_data, "started": datetime.now().isoformat()}),
            ),
        )

        execution_id = cur.fetchone()["id"]

        # Log to audit
        cur.execute(
            """
            INSERT INTO governance_audit_log
            (event_type, event_category, user_id, agent_id, action, target_table, target_id, new_value)
            VALUES ('workflow_trigger', 'automation', %s, %s, 'execute', 'agent_workflows', %s, %s)
        """,
            (
                user_id,
                agent_id,
                workflow["id"],
                json.dumps({"execution_id": execution_id, "input": input_data}),
            ),
        )

        conn.commit()

        return {
            "success": True,
            "execution_id": execution_id,
            "workflow": {"id": workflow["id"], "name": workflow["name"]},
            "status": "running",
            "message": f"Workflow '{workflow['name']}' triggered. Monitor with get_workflow_execution.",
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Error triggering workflow: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="trigger_workflow",
    category="advanced",
    description="""Trigger execution of an agent workflow.

Provide either workflow_id or workflow_name to identify the workflow.
Pass input_data as a JSON object for workflow parameters.

Returns execution_id to track progress with get_workflow_execution.
""",
    input_schema={
        "type": "object",
        "properties": {
            "workflow_id": {"type": "integer", "description": "Workflow ID"},
            "workflow_name": {
                "type": "string",
                "description": "Workflow name (alternative to ID)",
            },
            "input_data": {
                "type": "object",
                "description": "Input parameters for the workflow",
            },
            "agent_id": {
                "type": "integer",
                "description": "Agent executing the workflow",
            },
        },
    },
    handler=trigger_workflow_handler,
    requires_permission="write",
)


async def get_workflow_execution_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get status of a workflow execution
    """
    execution_id = arguments.get("execution_id")
    workflow_id = arguments.get("workflow_id")
    include_log = arguments.get("include_log", False)
    limit = min(arguments.get("limit", 10), 50)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        if execution_id:
            # Get specific execution
            cur.execute(
                """
                SELECT we.*, aw.name as workflow_name, a.name as agent_name
                FROM workflow_executions we
                JOIN agent_workflows aw ON we.workflow_id = aw.id
                LEFT JOIN agents a ON we.agent_id = a.id
                WHERE we.id = %s
            """,
                (execution_id,),
            )
            execution = cur.fetchone()

            if not execution:
                return {
                    "success": False,
                    "error": f"Execution {execution_id} not found",
                }

            result = {"success": True, "execution": dict(execution)}

            if not include_log:
                result["execution"].pop("execution_log", None)

            return result

        elif workflow_id:
            # Get recent executions for a workflow
            cur.execute(
                """
                SELECT we.id, we.status, we.started_at, we.completed_at,
                       we.error, a.name as agent_name
                FROM workflow_executions we
                LEFT JOIN agents a ON we.agent_id = a.id
                WHERE we.workflow_id = %s
                ORDER BY we.started_at DESC
                LIMIT %s
            """,
                (workflow_id, limit),
            )

            executions = [dict(r) for r in cur.fetchall()]

            return {
                "success": True,
                "workflow_id": workflow_id,
                "count": len(executions),
                "executions": executions,
            }

        else:
            # Get recent executions across all workflows
            cur.execute(
                """
                SELECT we.id, we.workflow_id, aw.name as workflow_name,
                       we.status, we.started_at, we.completed_at
                FROM workflow_executions we
                JOIN agent_workflows aw ON we.workflow_id = aw.id
                ORDER BY we.started_at DESC
                LIMIT %s
            """,
                (limit,),
            )

            executions = [dict(r) for r in cur.fetchall()]

            return {"success": True, "count": len(executions), "executions": executions}

    except Exception as e:
        logger.error(f"Error getting workflow execution: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_workflow_execution",
    category="advanced",
    description="""Get workflow execution status and history.

- With execution_id: Get specific execution details
- With workflow_id: Get recent executions for that workflow
- Without either: Get recent executions across all workflows

Set include_log=true for full execution logs (can be large).
""",
    input_schema={
        "type": "object",
        "properties": {
            "execution_id": {"type": "integer", "description": "Specific execution ID"},
            "workflow_id": {"type": "integer", "description": "Filter by workflow"},
            "include_log": {
                "type": "boolean",
                "description": "Include full execution log",
                "default": False,
            },
            "limit": {"type": "integer", "default": 10},
        },
    },
    handler=get_workflow_execution_handler,
    requires_permission="read",
)


async def create_workflow_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new workflow definition
    """
    name = arguments.get("name")
    description = arguments.get("description", "")
    trigger_type = arguments.get("trigger_type", "manual")
    trigger_config = arguments.get("trigger_config", {})
    workflow_definition = arguments.get("workflow_definition", {})
    user_id = arguments.get("user_id", 2)

    if not name:
        return {"success": False, "error": "name is required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Check for duplicate name
        cur.execute("SELECT id FROM agent_workflows WHERE name = %s", (name,))
        if cur.fetchone():
            return {"success": False, "error": f"Workflow '{name}' already exists"}

        cur.execute(
            """
            INSERT INTO agent_workflows
            (name, description, trigger_type, trigger_config, workflow_definition, status, created_by)
            VALUES (%s, %s, %s, %s, %s, 'active', %s)
            RETURNING id
        """,
            (
                name,
                description,
                trigger_type,
                json.dumps(trigger_config),
                json.dumps(workflow_definition),
                user_id,
            ),
        )

        workflow_id = cur.fetchone()["id"]

        # Audit log
        cur.execute(
            """
            INSERT INTO governance_audit_log
            (event_type, event_category, user_id, action, target_table, target_id, new_value)
            VALUES ('workflow_created', 'automation', %s, 'create', 'agent_workflows', %s, %s)
        """,
            (
                user_id,
                workflow_id,
                json.dumps({"name": name, "trigger_type": trigger_type}),
            ),
        )

        conn.commit()

        return {
            "success": True,
            "workflow_id": workflow_id,
            "name": name,
            "trigger_type": trigger_type,
            "status": "active",
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating workflow: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="create_workflow",
    category="advanced",
    description="""Create a new agent workflow.

Trigger types:
- manual: Triggered via API
- scheduled: Runs on schedule (cron format in trigger_config)
- event: Triggered by system events
- webhook: Triggered by external webhooks

workflow_definition contains the steps to execute.
""",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Unique workflow name"},
            "description": {"type": "string", "description": "Workflow description"},
            "trigger_type": {
                "type": "string",
                "enum": ["manual", "scheduled", "event", "webhook"],
                "default": "manual",
            },
            "trigger_config": {
                "type": "object",
                "description": "Trigger-specific configuration",
            },
            "workflow_definition": {
                "type": "object",
                "description": "Workflow steps and logic",
            },
        },
        "required": ["name"],
    },
    handler=create_workflow_handler,
    requires_permission="write",
)


# ============================================================================
# RATE LIMITING TOOLS
# ============================================================================


async def get_rate_limit_status_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get current rate limit status for MCP API
    """
    api_key_id = arguments.get("api_key_id")
    window_type = arguments.get("window_type", "hour")

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Get rate limit configuration (defaults if not set)
        limits = {"minute": 60, "hour": 1000, "day": 10000}

        # Calculate window start
        now = datetime.now()
        if window_type == "minute":
            window_start = now.replace(second=0, microsecond=0)
        elif window_type == "hour":
            window_start = now.replace(minute=0, second=0, microsecond=0)
        else:  # day
            window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if api_key_id:
            # Get specific API key usage
            cur.execute(
                """
                SELECT COALESCE(SUM(request_count), 0) as count
                FROM mcp_rate_limits
                WHERE api_key_id = %s AND window_type = %s AND window_start >= %s
            """,
                (api_key_id, window_type, window_start),
            )
            result = cur.fetchone()
            if not result:
                return {"success": False, "error": "Query returned no result"}
            current_usage = int(result["count"])

            return {
                "success": True,
                "api_key_id": api_key_id,
                "window_type": window_type,
                "window_start": window_start.isoformat(),
                "current_usage": current_usage,
                "limit": limits.get(window_type, 1000),
                "remaining": max(0, limits.get(window_type, 1000) - current_usage),
                "reset_at": (
                    window_start
                    + timedelta(
                        minutes=1 if window_type == "minute" else 0,
                        hours=1 if window_type == "hour" else 0,
                        days=1 if window_type == "day" else 0,
                    )
                ).isoformat(),
            }
        else:
            # Get overall usage summary
            cur.execute(
                """
                SELECT
                    window_type,
                    COUNT(DISTINCT api_key_id) as active_keys,
                    SUM(request_count) as total_requests
                FROM mcp_rate_limits
                WHERE window_start >= NOW() - INTERVAL '24 hours'
                GROUP BY window_type
            """
            )

            usage_by_window = {r["window_type"]: dict(r) for r in cur.fetchall()}

            return {
                "success": True,
                "summary": True,
                "window_type": window_type,
                "limits": limits,
                "usage_24h": usage_by_window,
            }

    except Exception as e:
        logger.error(f"Error getting rate limit status: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_rate_limit_status",
    category="advanced",
    description="""Check MCP API rate limit status.

With api_key_id: Get specific key's current usage vs limits
Without: Get overall rate limit summary

Window types: minute, hour, day
""",
    input_schema={
        "type": "object",
        "properties": {
            "api_key_id": {
                "type": "integer",
                "description": "Specific API key to check",
            },
            "window_type": {
                "type": "string",
                "enum": ["minute", "hour", "day"],
                "default": "hour",
            },
        },
    },
    handler=get_rate_limit_status_handler,
    requires_permission="read",
)


async def record_api_usage_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Record an API request for rate limiting
    """
    api_key_id = arguments.get("api_key_id")
    request_count = arguments.get("request_count", 1)

    if not api_key_id:
        return {"success": False, "error": "api_key_id is required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        now = datetime.now()

        # Record for each window type
        for window_type in ["minute", "hour", "day"]:
            if window_type == "minute":
                window_start = now.replace(second=0, microsecond=0)
            elif window_type == "hour":
                window_start = now.replace(minute=0, second=0, microsecond=0)
            else:
                window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

            cur.execute(
                """
                INSERT INTO mcp_rate_limits (api_key_id, window_start, window_type, request_count)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (api_key_id, window_start, window_type)
                DO UPDATE SET request_count = mcp_rate_limits.request_count + EXCLUDED.request_count
            """,
                (api_key_id, window_start, window_type, request_count),
            )

        conn.commit()

        return {"success": True, "api_key_id": api_key_id, "recorded": request_count}

    except Exception as e:
        conn.rollback()
        logger.error(f"Error recording API usage: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="record_api_usage",
    category="advanced",
    description="""Record API usage for rate limiting tracking.

Called automatically by the MCP server for each request.
Can also be called manually to batch-record usage.
""",
    input_schema={
        "type": "object",
        "properties": {
            "api_key_id": {"type": "integer", "description": "API key ID"},
            "request_count": {
                "type": "integer",
                "description": "Number of requests to record",
                "default": 1,
            },
        },
        "required": ["api_key_id"],
    },
    handler=record_api_usage_handler,
    requires_permission="write",
)


# ============================================================================
# AUDIT LOGGING TOOLS
# ============================================================================


async def log_audit_event_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create an audit log entry
    """
    event_type = arguments.get("event_type")
    event_category = arguments.get("event_category", "general")
    action = arguments.get("action")
    target_table = arguments.get("target_table")
    target_id = arguments.get("target_id")
    old_value = arguments.get("old_value")
    new_value = arguments.get("new_value")
    reason = arguments.get("reason", "")
    outcome = arguments.get("outcome", "success")
    agent_id = arguments.get("agent_id")
    user_id = arguments.get("user_id", 2)

    if not event_type or not action:
        return {"success": False, "error": "event_type and action are required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        cur.execute(
            """
            INSERT INTO governance_audit_log
            (event_type, event_category, agent_id, user_id, action, target_table, target_id,
             old_value, new_value, reason, outcome)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                event_type,
                event_category,
                agent_id,
                user_id,
                action,
                target_table,
                target_id,
                json.dumps(old_value) if old_value else None,
                json.dumps(new_value) if new_value else None,
                reason,
                outcome,
            ),
        )

        log_id = cur.fetchone()["id"]
        conn.commit()

        return {
            "success": True,
            "audit_log_id": log_id,
            "event_type": event_type,
            "action": action,
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating audit log: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="log_audit_event",
    category="advanced",
    description="""Create a governance audit log entry.

Event categories: general, security, automation, data, admin
Actions: create, read, update, delete, execute, approve, reject

Include old_value and new_value for change tracking.
""",
    input_schema={
        "type": "object",
        "properties": {
            "event_type": {
                "type": "string",
                "description": "Type of event (e.g., user_login, data_export)",
            },
            "event_category": {
                "type": "string",
                "enum": ["general", "security", "automation", "data", "admin"],
                "default": "general",
            },
            "action": {
                "type": "string",
                "description": "Action performed",
                "enum": [
                    "create",
                    "read",
                    "update",
                    "delete",
                    "execute",
                    "approve",
                    "reject",
                ],
            },
            "target_table": {"type": "string", "description": "Table affected"},
            "target_id": {"type": "integer", "description": "ID of affected record"},
            "old_value": {
                "type": "object",
                "description": "Previous value (for updates)",
            },
            "new_value": {"type": "object", "description": "New value"},
            "reason": {"type": "string", "description": "Reason for action"},
            "outcome": {
                "type": "string",
                "enum": ["success", "failure", "blocked", "pending"],
                "default": "success",
            },
            "agent_id": {"type": "integer", "description": "Agent ID if applicable"},
        },
        "required": ["event_type", "action"],
    },
    handler=log_audit_event_handler,
    requires_permission="write",
)


async def search_audit_log_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Search the governance audit log
    """
    event_type = arguments.get("event_type")
    event_category = arguments.get("event_category")
    action = arguments.get("action")
    agent_id = arguments.get("agent_id")
    user_id = arguments.get("user_id")
    target_table = arguments.get("target_table")
    outcome = arguments.get("outcome")
    since = arguments.get("since")  # ISO datetime
    until = arguments.get("until")  # ISO datetime
    limit = min(arguments.get("limit", 50), 200)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        query = """
            SELECT gal.*, a.name as agent_name, u.username
            FROM governance_audit_log gal
            LEFT JOIN agents a ON gal.agent_id = a.id
            LEFT JOIN users u ON gal.user_id = u.id
            WHERE 1=1
        """
        params = []

        if event_type:
            query += " AND gal.event_type = %s"
            params.append(event_type)

        if event_category:
            query += " AND gal.event_category = %s"
            params.append(event_category)

        if action:
            query += " AND gal.action = %s"
            params.append(action)

        if agent_id:
            query += " AND gal.agent_id = %s"
            params.append(agent_id)

        if user_id:
            query += " AND gal.user_id = %s"
            params.append(user_id)

        if target_table:
            query += " AND gal.target_table = %s"
            params.append(target_table)

        if outcome:
            query += " AND gal.outcome = %s"
            params.append(outcome)

        if since:
            query += " AND gal.timestamp >= %s"
            params.append(since)

        if until:
            query += " AND gal.timestamp <= %s"
            params.append(until)

        query += " ORDER BY gal.timestamp DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        logs = [dict(r) for r in cur.fetchall()]

        return {"success": True, "count": len(logs), "logs": logs}

    except Exception as e:
        logger.error(f"Error searching audit log: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="search_audit_log",
    category="advanced",
    description="""Search the governance audit log with filters.

Filter by:
- event_type, event_category, action
- agent_id, user_id, target_table
- outcome (success, failure, blocked, pending)
- since/until (ISO datetime strings)

Returns most recent entries first.
""",
    input_schema={
        "type": "object",
        "properties": {
            "event_type": {"type": "string"},
            "event_category": {
                "type": "string",
                "enum": ["general", "security", "automation", "data", "admin"],
            },
            "action": {
                "type": "string",
                "enum": [
                    "create",
                    "read",
                    "update",
                    "delete",
                    "execute",
                    "approve",
                    "reject",
                ],
            },
            "agent_id": {"type": "integer"},
            "user_id": {"type": "integer"},
            "target_table": {"type": "string"},
            "outcome": {
                "type": "string",
                "enum": ["success", "failure", "blocked", "pending"],
            },
            "since": {"type": "string", "description": "ISO datetime for start range"},
            "until": {"type": "string", "description": "ISO datetime for end range"},
            "limit": {"type": "integer", "default": 50},
        },
    },
    handler=search_audit_log_handler,
    requires_permission="read",
)


async def get_audit_summary_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get audit log statistics and summary
    """
    period = arguments.get("period", "24h")

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

        summary = {
            "success": True,
            "period": period,
            "timestamp": datetime.now().isoformat(),
        }

        # Total events
        cur.execute(
            """
            SELECT COUNT(*) as total
            FROM governance_audit_log
            WHERE timestamp > NOW() - %s
        """,
            (interval,),
        )
        summary["total_events"] = cur.fetchone()["total"]

        # By category
        cur.execute(
            """
            SELECT event_category, COUNT(*) as count
            FROM governance_audit_log
            WHERE timestamp > NOW() - %s
            GROUP BY event_category
            ORDER BY count DESC
        """,
            (interval,),
        )
        summary["by_category"] = {r["event_category"]: r["count"] for r in cur.fetchall()}

        # By action
        cur.execute(
            """
            SELECT action, COUNT(*) as count
            FROM governance_audit_log
            WHERE timestamp > NOW() - %s
            GROUP BY action
            ORDER BY count DESC
        """,
            (interval,),
        )
        summary["by_action"] = {r["action"]: r["count"] for r in cur.fetchall()}

        # By outcome
        cur.execute(
            """
            SELECT outcome, COUNT(*) as count
            FROM governance_audit_log
            WHERE timestamp > NOW() - %s AND outcome IS NOT NULL
            GROUP BY outcome
        """,
            (interval,),
        )
        summary["by_outcome"] = {r["outcome"]: r["count"] for r in cur.fetchall()}

        # Top event types
        cur.execute(
            """
            SELECT event_type, COUNT(*) as count
            FROM governance_audit_log
            WHERE timestamp > NOW() - %s
            GROUP BY event_type
            ORDER BY count DESC
            LIMIT 10
        """,
            (interval,),
        )
        summary["top_event_types"] = [dict(r) for r in cur.fetchall()]

        # Most active agents
        cur.execute(
            """
            SELECT a.name, gal.agent_id, COUNT(*) as count
            FROM governance_audit_log gal
            JOIN agents a ON gal.agent_id = a.id
            WHERE gal.timestamp > NOW() - %s AND gal.agent_id IS NOT NULL
            GROUP BY gal.agent_id, a.name
            ORDER BY count DESC
            LIMIT 5
        """,
            (interval,),
        )
        summary["most_active_agents"] = [dict(r) for r in cur.fetchall()]

        return summary

    except Exception as e:
        logger.error(f"Error getting audit summary: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_audit_summary",
    category="advanced",
    description="""Get governance audit log statistics.

Periods: 1h, 24h, 7d, 30d

Returns:
- Total events
- Breakdown by category, action, outcome
- Top event types
- Most active agents
""",
    input_schema={
        "type": "object",
        "properties": {
            "period": {
                "type": "string",
                "enum": ["1h", "24h", "7d", "30d"],
                "default": "24h",
            }
        },
    },
    handler=get_audit_summary_handler,
    requires_permission="read",
)


# ============================================================================
# HEALTH CHECK TOOLS
# ============================================================================


async def health_check_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Perform comprehensive system health check
    """
    include_details = arguments.get("include_details", False)

    health = {
        "success": True,
        "timestamp": datetime.now().isoformat(),
        "status": "healthy",
        "checks": {},
    }

    issues = []

    # Database check
    conn, cur = get_db_connection()
    if conn:
        try:
            cur.execute("SELECT 1")
            health["checks"]["database"] = {"status": "healthy", "latency_ms": 0}

            if include_details:
                cur.execute("SELECT COUNT(*) as tables FROM information_schema.tables WHERE table_schema='public'")
                health["checks"]["database"]["tables"] = cur.fetchone()["tables"]

                cur.execute("SELECT pg_database_size('archie') as size")
                size_bytes = cur.fetchone()["size"]
                health["checks"]["database"]["size_mb"] = round(size_bytes / (1024 * 1024), 2)
        except Exception as e:
            health["checks"]["database"] = {"status": "unhealthy", "error": str(e)}
            issues.append("Database query failed")
        finally:
            cur.close()
            conn.close()
    else:
        health["checks"]["database"] = {
            "status": "unhealthy",
            "error": "Connection failed",
        }
        issues.append("Database connection failed")

    # MCP Server check
    try:
        from . import get_all_tools

        tools = get_all_tools()
        health["checks"]["mcp_server"] = {
            "status": "healthy",
            "tools_loaded": len(tools),
        }
    except Exception as e:
        health["checks"]["mcp_server"] = {"status": "unhealthy", "error": str(e)}
        issues.append("MCP tools failed to load")

    # Disk space check (basic)
    try:
        result = subprocess.run(["df", "-h", "/mnt/archie_brain"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            if len(lines) > 1:
                parts = lines[1].split()
                usage_pct = int(parts[4].replace("%", ""))
                health["checks"]["disk"] = {
                    "status": "healthy" if usage_pct < 90 else "warning",
                    "usage_percent": usage_pct,
                    "available": parts[3],
                }
                if usage_pct >= 90:
                    issues.append(f"Disk usage at {usage_pct}%")
    except Exception as e:
        health["checks"]["disk"] = {"status": "unknown", "error": str(e)}

    # Memory check
    try:
        result = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            if len(lines) > 1:
                parts = lines[1].split()
                total = int(parts[1])
                used = int(parts[2])
                usage_pct = round((used / total) * 100, 1)
                health["checks"]["memory"] = {
                    "status": "healthy" if usage_pct < 90 else "warning",
                    "usage_percent": usage_pct,
                    "total_mb": total,
                    "used_mb": used,
                }
                if usage_pct >= 90:
                    issues.append(f"Memory usage at {usage_pct}%")
    except Exception as e:
        health["checks"]["memory"] = {"status": "unknown", "error": str(e)}

    # Set overall status
    if any(c.get("status") == "unhealthy" for c in health["checks"].values()):
        health["status"] = "unhealthy"
    elif any(c.get("status") == "warning" for c in health["checks"].values()):
        health["status"] = "degraded"

    health["issues"] = issues

    return health


register_tool(
    name="health_check",
    category="advanced",
    description="""Perform comprehensive A.R.C.H.I.E. system health check.

Checks:
- Database connectivity and stats
- MCP server and tools
- Disk space
- Memory usage

Set include_details=true for extended information.
""",
    input_schema={
        "type": "object",
        "properties": {
            "include_details": {
                "type": "boolean",
                "description": "Include extended details",
                "default": False,
            }
        },
    },
    handler=health_check_handler,
    requires_permission="read",
)


async def get_service_status_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get status of A.R.C.H.I.E. services
    """
    service = arguments.get("service")

    services = {
        "platform": {"port": 3000, "name": "A.R.C.H.I.E. Platform"},
        "database": {"port": 5432, "name": "PostgreSQL"},
        "ollama": {"port": 11434, "name": "Ollama LLM"},
        "n8n": {"port": 5678, "name": "n8n Workflows"},
    }

    def check_port(port):
        """Check if a port is listening"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        try:
            result = sock.connect_ex(("localhost", port))
            return result == 0
        except Exception:
            return False
        finally:
            sock.close()

    if service:
        # Check specific service
        if service not in services:
            return {
                "success": False,
                "error": f"Unknown service: {service}. Available: {list(services.keys())}",
            }

        svc = services[service]
        is_up = check_port(svc["port"])

        return {
            "success": True,
            "service": service,
            "name": svc["name"],
            "port": svc["port"],
            "status": "running" if is_up else "stopped",
            "healthy": is_up,
        }
    else:
        # Check all services
        results = []
        for svc_name, svc in services.items():
            is_up = check_port(svc["port"])
            results.append(
                {
                    "service": svc_name,
                    "name": svc["name"],
                    "port": svc["port"],
                    "status": "running" if is_up else "stopped",
                    "healthy": is_up,
                }
            )

        all_healthy = all(r["healthy"] for r in results)
        some_healthy = any(r["healthy"] for r in results)

        return {
            "success": True,
            "overall_status": ("healthy" if all_healthy else ("degraded" if some_healthy else "unhealthy")),
            "services": results,
        }


register_tool(
    name="get_service_status",
    category="advanced",
    description="""Get status of A.R.C.H.I.E. services.

Services monitored:
- platform: A.R.C.H.I.E. Platform (port 3000)
- database: PostgreSQL (port 5432)
- ollama: Ollama LLM (port 11434)
- n8n: n8n Workflows (port 5678)

Without service parameter: checks all services
With service parameter: checks specific service
""",
    input_schema={
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "enum": ["platform", "database", "ollama", "n8n"],
                "description": "Specific service to check",
            }
        },
    },
    handler=get_service_status_handler,
    requires_permission="read",
)


# ============================================================================
# SYSTEM CONFIGURATION TOOL
# ============================================================================


async def get_system_config_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get system configuration and environment info
    """
    include_sensitive = arguments.get("include_sensitive", False)

    config = {
        "success": True,
        "timestamp": datetime.now().isoformat(),
        "platform": {
            "name": "A.R.C.H.I.E.",
            "version": "5.0.0",
            "phase": "50.6 - MCP Server Complete",
        },
        "environment": {
            "python_path": os.getenv("PYTHONPATH", "not set"),
            "flask_env": os.getenv("FLASK_ENV", "production"),
            "debug_mode": os.getenv("FLASK_DEBUG", "0") == "1",
        },
        "database": {
            "host": DB_CONFIG["host"],
            "database": DB_CONFIG["database"],
            "user": DB_CONFIG["user"],
        },
        "mcp_server": {
            "tools_directory": "/mnt/archie_brain/platform_v2/mcp_server/tools",
            "categories": ["knowledge", "creation", "business", "admin", "advanced"],
        },
    }

    if include_sensitive:
        # Only include if explicitly requested
        config["database"]["password"] = "***" + DB_CONFIG["password"][-4:] if DB_CONFIG["password"] else None

    # Get tool counts
    try:
        from . import get_all_tools, get_tools_by_category

        all_tools = get_all_tools()
        config["mcp_server"]["total_tools"] = len(all_tools)
        config["mcp_server"]["tools_by_category"] = {}
        for cat in config["mcp_server"]["categories"]:
            config["mcp_server"]["tools_by_category"][cat] = len(get_tools_by_category(cat))
    except Exception as e:
        config["mcp_server"]["error"] = str(e)

    return config


register_tool(
    name="get_system_config",
    category="advanced",
    description="""Get A.R.C.H.I.E. system configuration.

Returns:
- Platform version and phase
- Environment settings
- Database configuration
- MCP server tool counts

Set include_sensitive=true to see partial credentials (admin only).
""",
    input_schema={
        "type": "object",
        "properties": {
            "include_sensitive": {
                "type": "boolean",
                "description": "Include partial sensitive info",
                "default": False,
            }
        },
    },
    handler=get_system_config_handler,
    requires_permission="read",
)


logger.info(
    "Advanced tools registered: list_workflows, trigger_workflow, get_workflow_execution, "
    "create_workflow, get_rate_limit_status, record_api_usage, log_audit_event, "
    "search_audit_log, get_audit_summary, health_check, get_service_status, get_system_config"
)
