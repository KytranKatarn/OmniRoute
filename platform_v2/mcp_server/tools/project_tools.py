"""
A.R.C.H.I.E. MCP Server - Unified Project Management Tools
Phase 65: Unified Project & Documentation System

Tools for project management, task tracking, documentation, and ARCHIE's self-awareness:
- Project Management: get_projects, get_project_details, create_project, update_project_status
- Task Management: get_my_tasks, create_task, update_task, complete_task
- Documentation: get_project_docs, update_project_doc, log_decision
- Team: get_project_team, assign_to_project, get_activity_feed
- Consciousness: log_config_change, get_config_history, update_project_understanding
"""

import os
from database import _get_db_password
import json
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import Dict, Any
import re

from . import register_tool, cap_limit

logger = logging.getLogger("archie_mcp.tools.project")

# Database configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "192.168.1.200"),
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


def generate_slug(name: str) -> str:
    """Generate URL-friendly slug from name"""
    slug = re.sub(r"[^a-zA-Z0-9\s-]", "", name.lower())
    slug = re.sub(r"\s+", "-", slug)
    return slug[:100]


# ============================================================================
# PROJECT MANAGEMENT TOOLS
# ============================================================================


async def get_projects_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    List all projects with status and priority.
    Supports filtering by status and project type.
    """
    status_filter = arguments.get("status")
    project_type = arguments.get("project_type")
    limit = cap_limit(arguments, 20, 100)
    include_progress = arguments.get("include_progress", True)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        where_clauses = []
        params = []

        if status_filter:
            where_clauses.append("status = %s")
            params.append(status_filter)
        if project_type:
            where_clauses.append("project_type = %s")
            params.append(project_type)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        params.append(limit)

        cur.execute(
            f"""
            SELECT
                p.id, p.name, p.slug, p.status, p.priority,
                p.project_type, p.description, p.created_at,
                COALESCE(get_project_progress(p.id), 0) as progress
            FROM unified_projects p
            {where_sql}
            ORDER BY p.priority DESC, p.updated_at DESC
            LIMIT %s
        """,
            params,
        )

        projects = cur.fetchall()

        result = []
        for p in projects:
            proj = {
                "id": p["id"],
                "name": p["name"],
                "slug": p["slug"],
                "status": p["status"],
                "priority": p["priority"],
                "type": p["project_type"],
                "description": p["description"][:200] if p["description"] else None,
            }
            if include_progress:
                proj["progress"] = f"{p['progress']:.0f}%"
            result.append(proj)

        return {"success": True, "projects": result, "total": len(result)}

    except Exception as e:
        logger.error(f"Get projects error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_projects",
    category="project",
    description="List all unified projects with status, priority, and progress. Use to see available projects and their current state.",
    input_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "Filter by status (planning, active, completed, on_hold)",
                "enum": ["planning", "active", "completed", "on_hold", "cancelled"],
            },
            "project_type": {
                "type": "string",
                "description": "Filter by type",
                "enum": [
                    "feature",
                    "bugfix",
                    "infrastructure",
                    "documentation",
                    "research",
                ],
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 20, max 100)",
                "default": 20,
            },
            "include_progress": {
                "type": "boolean",
                "description": "Include task completion progress",
                "default": True,
            },
        },
    },
    handler=get_projects_handler,
)


async def get_project_details_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get full details for a specific project including tasks, team, and docs.
    """
    project_id = arguments.get("project_id")
    project_slug = arguments.get("project_slug")

    if not project_id and not project_slug:
        return {"success": False, "error": "Provide either project_id or project_slug"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Get project
        if project_id:
            cur.execute("SELECT * FROM unified_projects WHERE id = %s", (project_id,))
        else:
            cur.execute("SELECT * FROM unified_projects WHERE slug = %s", (project_slug,))

        project = cur.fetchone()
        if not project:
            return {"success": False, "error": "Project not found"}

        project_id = project["id"]

        # Get tasks
        cur.execute(
            """
            SELECT id, title, status, priority, task_type, assigned_user_id, assigned_agent_id, due_date
            FROM unified_tasks
            WHERE project_id = %s
            ORDER BY priority DESC, created_at
        """,
            (project_id,),
        )
        tasks = cur.fetchall()

        # Get team
        cur.execute(
            """
            SELECT pt.role, pt.permissions,
                   u.username as user_name,
                   a.name as agent_name
            FROM project_team pt
            LEFT JOIN users u ON pt.user_id = u.id
            LEFT JOIN agents a ON pt.agent_id = a.id
            WHERE pt.project_id = %s
        """,
            (project_id,),
        )
        team = cur.fetchall()

        # Get documents
        cur.execute(
            """
            SELECT id, doc_type, title, version, updated_at
            FROM project_documents
            WHERE project_id = %s AND is_current = TRUE
            ORDER BY doc_type, title
        """,
            (project_id,),
        )
        docs = cur.fetchall()

        # Get ARCHIE's awareness
        cur.execute(
            """
            SELECT understanding_level, emotional_association, notes, last_interaction
            FROM archie_project_awareness
            WHERE project_id = %s
        """,
            (project_id,),
        )
        awareness = cur.fetchone()

        return {
            "success": True,
            "project": {
                "id": project["id"],
                "name": project["name"],
                "slug": project["slug"],
                "description": project["description"],
                "status": project["status"],
                "priority": project["priority"],
                "type": project["project_type"],
                "tags": project["tags"],
                "start_date": (str(project["start_date"]) if project["start_date"] else None),
                "target_date": (str(project["target_date"]) if project["target_date"] else None),
                "metadata": project["metadata"],
            },
            "tasks": {
                "total": len(tasks),
                "completed": len([t for t in tasks if t["status"] == "completed"]),
                "items": [
                    {
                        "id": t["id"],
                        "title": t["title"],
                        "status": t["status"],
                        "priority": t["priority"],
                        "type": t["task_type"],
                    }
                    for t in tasks[:20]  # Limit for token efficiency
                ],
            },
            "team": [
                {
                    "name": t["user_name"] or t["agent_name"],
                    "type": "user" if t["user_name"] else "agent",
                    "role": t["role"],
                }
                for t in team
            ],
            "documents": [{"type": d["doc_type"], "title": d["title"], "version": d["version"]} for d in docs],
            "archie_awareness": (
                {
                    "understanding": (awareness["understanding_level"] if awareness else 0),
                    "emotion": (awareness["emotional_association"] if awareness else "neutral"),
                    "notes": awareness["notes"] if awareness else None,
                }
                if awareness
                else None
            ),
        }

    except Exception as e:
        logger.error(f"Get project details error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_project_details",
    category="project",
    description="Get full project details including tasks, team members, documents, and ARCHIE awareness. Use for comprehensive project info.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer", "description": "Project ID"},
            "project_slug": {
                "type": "string",
                "description": "Project slug (URL-friendly name)",
            },
        },
    },
    handler=get_project_details_handler,
)


async def create_project_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new unified project.
    """
    name = arguments.get("name")
    if not name:
        return {"success": False, "error": "Project name is required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        slug = generate_slug(name)

        # Check for duplicate slug
        cur.execute("SELECT id FROM unified_projects WHERE slug = %s", (slug,))
        if cur.fetchone():
            slug = f"{slug}-{int(datetime.now().timestamp())}"

        cur.execute(
            """
            INSERT INTO unified_projects (
                name, slug, description, status, priority,
                project_type, parent_project_id, tags, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, slug
        """,
            (
                name,
                slug,
                arguments.get("description"),
                arguments.get("status", "planning"),
                arguments.get("priority", 5),
                arguments.get("project_type", "feature"),
                arguments.get("parent_project_id"),
                arguments.get("tags", []),
                json.dumps(arguments.get("metadata", {})),
            ),
        )

        result = cur.fetchone()
        conn.commit()

        # Create initial awareness record
        cur.execute(
            """
            INSERT INTO archie_project_awareness (project_id, notes, emotional_association)
            VALUES (%s, %s, 'curious')
        """,
            (result["id"], f"New project created: {name}"),
        )
        conn.commit()

        return {
            "success": True,
            "project_id": result["id"],
            "slug": result["slug"],
            "message": f"Project '{name}' created successfully",
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Create project error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="create_project",
    category="project",
    description="Create a new unified project. Use for starting new features, initiatives, or tracking work.",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Project name (required)"},
            "description": {"type": "string", "description": "Project description"},
            "project_type": {
                "type": "string",
                "description": "Project type",
                "enum": [
                    "feature",
                    "bugfix",
                    "infrastructure",
                    "documentation",
                    "research",
                ],
                "default": "feature",
            },
            "priority": {
                "type": "integer",
                "description": "Priority 1-10 (10=highest)",
                "default": 5,
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags for categorization",
            },
            "parent_project_id": {
                "type": "integer",
                "description": "Parent project ID for sub-projects",
            },
        },
        "required": ["name"],
    },
    handler=create_project_handler,
    requires_permission="write",
)


async def update_project_status_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update project status and/or priority.
    """
    project_id = arguments.get("project_id")
    if not project_id:
        return {"success": False, "error": "project_id is required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        updates = []
        params = []

        if "status" in arguments:
            updates.append("status = %s")
            params.append(arguments["status"])

            if arguments["status"] == "completed":
                updates.append("completed_at = NOW()")

        if "priority" in arguments:
            updates.append("priority = %s")
            params.append(arguments["priority"])

        if not updates:
            return {"success": False, "error": "No updates provided"}

        params.append(project_id)
        cur.execute(
            f"""
            UPDATE unified_projects
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING name, status, priority
        """,
            params,
        )

        result = cur.fetchone()
        if not result:
            return {"success": False, "error": "Project not found"}

        conn.commit()

        return {
            "success": True,
            "project": {
                "name": result["name"],
                "status": result["status"],
                "priority": result["priority"],
            },
            "message": "Project updated",
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Update project error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="update_project_status",
    category="project",
    description="Update project status or priority. Use to mark projects as active, completed, or adjust priority.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer", "description": "Project ID (required)"},
            "status": {
                "type": "string",
                "description": "New status",
                "enum": ["planning", "active", "completed", "on_hold", "cancelled"],
            },
            "priority": {"type": "integer", "description": "New priority 1-10"},
        },
        "required": ["project_id"],
    },
    handler=update_project_status_handler,
    requires_permission="write",
)


# ============================================================================
# TASK MANAGEMENT TOOLS
# ============================================================================


async def get_my_tasks_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get tasks - either all pending or filtered by project/assignee.
    Useful for Claude to see what work needs to be done.
    """
    project_id = arguments.get("project_id")
    status = arguments.get("status", "pending")
    limit = cap_limit(arguments, 20, 50)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        where_clauses = ["t.status = %s"]
        params = [status]

        if project_id:
            where_clauses.append("t.project_id = %s")
            params.append(project_id)

        params.append(limit)

        cur.execute(
            f"""
            SELECT
                t.id, t.title, t.status, t.priority, t.task_type,
                t.description, t.due_date, t.estimated_effort,
                p.name as project_name, p.slug as project_slug
            FROM unified_tasks t
            JOIN unified_projects p ON t.project_id = p.id
            WHERE {' AND '.join(where_clauses)}
            ORDER BY t.priority DESC, t.due_date NULLS LAST
            LIMIT %s
        """,
            params,
        )

        tasks = cur.fetchall()

        return {
            "success": True,
            "tasks": [
                {
                    "id": t["id"],
                    "title": t["title"],
                    "project": t["project_name"],
                    "status": t["status"],
                    "priority": t["priority"],
                    "type": t["task_type"],
                    "effort": t["estimated_effort"],
                    "due": str(t["due_date"]) if t["due_date"] else None,
                }
                for t in tasks
            ],
            "total": len(tasks),
        }

    except Exception as e:
        logger.error(f"Get tasks error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_my_tasks",
    category="project",
    description="Get tasks to work on. Shows pending tasks by default. Use to find work that needs attention.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer", "description": "Filter by project ID"},
            "status": {
                "type": "string",
                "description": "Filter by status",
                "enum": ["pending", "in_progress", "blocked", "review", "completed"],
                "default": "pending",
            },
            "limit": {"type": "integer", "description": "Max results", "default": 20},
        },
    },
    handler=get_my_tasks_handler,
)


async def create_task_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new task in a project.
    """
    project_id = arguments.get("project_id")
    title = arguments.get("title")

    if not project_id or not title:
        return {"success": False, "error": "project_id and title are required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        cur.execute(
            """
            INSERT INTO unified_tasks (
                project_id, title, description, status, priority,
                task_type, estimated_effort, due_date, dependencies, tags
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                project_id,
                title,
                arguments.get("description"),
                arguments.get("status", "pending"),
                arguments.get("priority", 5),
                arguments.get("task_type", "implementation"),
                arguments.get("estimated_effort"),
                arguments.get("due_date"),
                json.dumps(arguments.get("dependencies", [])),
                arguments.get("tags", []),
            ),
        )

        task_id = cur.fetchone()["id"]
        conn.commit()

        return {
            "success": True,
            "task_id": task_id,
            "message": f"Task '{title}' created",
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Create task error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="create_task",
    category="project",
    description="Create a new task in a project. Use to add work items to be tracked.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer", "description": "Project ID (required)"},
            "title": {"type": "string", "description": "Task title (required)"},
            "description": {"type": "string", "description": "Detailed description"},
            "task_type": {
                "type": "string",
                "enum": [
                    "implementation",
                    "review",
                    "testing",
                    "documentation",
                    "research",
                    "bugfix",
                ],
                "default": "implementation",
            },
            "priority": {
                "type": "integer",
                "description": "Priority 1-10",
                "default": 5,
            },
            "estimated_effort": {
                "type": "string",
                "enum": ["tiny", "small", "medium", "large", "epic"],
            },
            "due_date": {"type": "string", "description": "Due date (ISO format)"},
            "dependencies": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Task IDs this depends on",
            },
        },
        "required": ["project_id", "title"],
    },
    handler=create_task_handler,
    requires_permission="write",
)


async def complete_task_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mark a task as completed with optional notes.
    """
    task_id = arguments.get("task_id")
    if not task_id:
        return {"success": False, "error": "task_id is required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        notes = arguments.get("notes")

        cur.execute(
            """
            UPDATE unified_tasks
            SET status = 'completed', completed_at = NOW(),
                metadata = metadata || %s
            WHERE id = %s
            RETURNING title, project_id
        """,
            (json.dumps({"completion_notes": notes}) if notes else "{}", task_id),
        )

        result = cur.fetchone()
        if not result:
            return {"success": False, "error": "Task not found"}

        conn.commit()

        return {
            "success": True,
            "task": result["title"],
            "message": "Task marked as completed",
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Complete task error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="complete_task",
    category="project",
    description="Mark a task as completed. Use after finishing work on a task.",
    input_schema={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "Task ID to complete (required)",
            },
            "notes": {
                "type": "string",
                "description": "Completion notes or summary of work done",
            },
        },
        "required": ["task_id"],
    },
    handler=complete_task_handler,
    requires_permission="write",
)


# ============================================================================
# DOCUMENTATION TOOLS
# ============================================================================


async def get_project_docs_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get documentation for a project.
    """
    project_id = arguments.get("project_id")
    doc_type = arguments.get("doc_type")

    if not project_id:
        return {"success": False, "error": "project_id is required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        where = "project_id = %s AND is_current = TRUE"
        params = [project_id]

        if doc_type:
            where += " AND doc_type = %s"
            params.append(doc_type)

        cur.execute(
            f"""
            SELECT id, doc_type, title, content, version, updated_at
            FROM project_documents
            WHERE {where}
            ORDER BY doc_type, title
        """,
            params,
        )

        docs = cur.fetchall()

        return {
            "success": True,
            "documents": [
                {
                    "id": d["id"],
                    "type": d["doc_type"],
                    "title": d["title"],
                    "content": (d["content"][:2000] if arguments.get("brief") else d["content"]),
                    "version": d["version"],
                    "updated": str(d["updated_at"]),
                }
                for d in docs
            ],
        }

    except Exception as e:
        logger.error(f"Get docs error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_project_docs",
    category="project",
    description="Get documentation for a project. Use to read project specs, architecture, or guides.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer", "description": "Project ID (required)"},
            "doc_type": {
                "type": "string",
                "enum": [
                    "readme",
                    "architecture",
                    "api",
                    "changelog",
                    "decision",
                    "guide",
                    "spec",
                ],
                "description": "Filter by document type",
            },
            "brief": {
                "type": "boolean",
                "description": "Truncate content to 2000 chars",
                "default": False,
            },
        },
        "required": ["project_id"],
    },
    handler=get_project_docs_handler,
)


async def log_decision_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Log an architectural decision (ADR).
    """
    project_id = arguments.get("project_id")
    title = arguments.get("title")
    decision = arguments.get("decision")

    if not title or not decision:
        return {"success": False, "error": "title and decision are required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Get next ADR number
        cur.execute(
            """
            SELECT COALESCE(MAX(decision_number), 0) + 1 as next_num
            FROM project_decisions
            WHERE project_id = %s
        """,
            (project_id,) if project_id else (None,),
        )
        next_num = cur.fetchone()["next_num"]

        cur.execute(
            """
            INSERT INTO project_decisions (
                project_id, task_id, decision_number, title, status,
                context, decision, alternatives, consequences
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, decision_number
        """,
            (
                project_id,
                arguments.get("task_id"),
                next_num,
                title,
                arguments.get("status", "accepted"),
                arguments.get("context"),
                decision,
                arguments.get("alternatives"),
                arguments.get("consequences"),
            ),
        )

        result = cur.fetchone()
        conn.commit()

        if not result:
            return {"success": False, "error": "Record not found"}

        return {
            "success": True,
            "decision_id": result["id"],
            "adr_number": f"ADR-{result['decision_number']:03d}",
            "message": f"Decision logged: {title}",
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Log decision error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="log_decision",
    category="project",
    description="Log an architectural decision (ADR). Use to record important technical decisions and their rationale.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer", "description": "Project ID (optional)"},
            "title": {"type": "string", "description": "Decision title (required)"},
            "context": {
                "type": "string",
                "description": "Why was this decision needed?",
            },
            "decision": {
                "type": "string",
                "description": "What was decided? (required)",
            },
            "alternatives": {
                "type": "string",
                "description": "What alternatives were considered?",
            },
            "consequences": {
                "type": "string",
                "description": "What are the implications?",
            },
            "task_id": {"type": "integer", "description": "Related task ID"},
        },
        "required": ["title", "decision"],
    },
    handler=log_decision_handler,
    requires_permission="write",
)


# ============================================================================
# TEAM & COLLABORATION TOOLS
# ============================================================================


async def get_project_team_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get team members for a project.
    """
    project_id = arguments.get("project_id")
    if not project_id:
        return {"success": False, "error": "project_id is required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        cur.execute(
            """
            SELECT
                pt.role, pt.permissions, pt.responsibilities,
                CASE WHEN pt.user_id IS NOT NULL THEN 'user' ELSE 'agent' END as member_type,
                COALESCE(u.username, a.name) as name,
                u.email,
                a.capabilities
            FROM project_team pt
            LEFT JOIN users u ON pt.user_id = u.id
            LEFT JOIN agents a ON pt.agent_id = a.id
            WHERE pt.project_id = %s
            ORDER BY pt.role, pt.assigned_at
        """,
            (project_id,),
        )

        team = cur.fetchall()

        return {
            "success": True,
            "team": [
                {
                    "name": t["name"],
                    "type": t["member_type"],
                    "role": t["role"],
                    "email": t["email"],
                    "responsibilities": t["responsibilities"],
                }
                for t in team
            ],
            "total": len(team),
        }

    except Exception as e:
        logger.error(f"Get team error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_project_team",
    category="project",
    description="Get team members assigned to a project. Shows users and AI agents with their roles.",
    input_schema={
        "type": "object",
        "properties": {"project_id": {"type": "integer", "description": "Project ID (required)"}},
        "required": ["project_id"],
    },
    handler=get_project_team_handler,
)


async def get_activity_feed_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get recent activity for a project or across all projects.
    """
    project_id = arguments.get("project_id")
    limit = cap_limit(arguments, 20, 100)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        where = ""
        params = []

        if project_id:
            where = "WHERE pa.project_id = %s"
            params.append(project_id)

        params.append(limit)

        cur.execute(
            f"""
            SELECT
                pa.activity_type, pa.entity_type, pa.description,
                pa.created_at,
                COALESCE(u.username, a.name, 'system') as actor,
                p.name as project_name
            FROM project_activity pa
            LEFT JOIN users u ON pa.user_id = u.id
            LEFT JOIN agents a ON pa.agent_id = a.id
            LEFT JOIN unified_projects p ON pa.project_id = p.id
            {where}
            ORDER BY pa.created_at DESC
            LIMIT %s
        """,
            params,
        )

        activities = cur.fetchall()

        return {
            "success": True,
            "activities": [
                {
                    "type": a["activity_type"],
                    "entity": a["entity_type"],
                    "description": a["description"],
                    "actor": a["actor"],
                    "project": a["project_name"],
                    "when": str(a["created_at"]),
                }
                for a in activities
            ],
        }

    except Exception as e:
        logger.error(f"Get activity error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_activity_feed",
    category="project",
    description="Get recent activity feed for projects. Shows who did what and when.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {
                "type": "integer",
                "description": "Filter by project (optional, shows all if omitted)",
            },
            "limit": {"type": "integer", "description": "Max results", "default": 20},
        },
    },
    handler=get_activity_feed_handler,
)


# ============================================================================
# CONSCIOUSNESS / SELF-AWARENESS TOOLS
# ============================================================================


async def log_config_change_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Log a configuration change for ARCHIE's self-awareness.
    Use when making changes to modules, settings, or integrations.
    """
    config_type = arguments.get("config_type")
    change_type = arguments.get("change_type")

    if not config_type or not change_type:
        return {"success": False, "error": "config_type and change_type are required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        cur.execute(
            """
            INSERT INTO archie_config_history (
                config_type, config_path, config_key, change_type,
                previous_value, new_value, change_reason,
                impact_assessment, changed_by_session, related_project_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                config_type,
                arguments.get("config_path"),
                arguments.get("config_key"),
                change_type,
                (json.dumps(arguments.get("previous_value")) if arguments.get("previous_value") else None),
                (json.dumps(arguments.get("new_value")) if arguments.get("new_value") else None),
                arguments.get("change_reason"),
                arguments.get("impact_assessment"),
                arguments.get("session_id"),
                arguments.get("project_id"),
            ),
        )

        change_id = cur.fetchone()["id"]
        conn.commit()

        return {
            "success": True,
            "change_id": change_id,
            "message": f"Configuration change logged: {config_type} {change_type}",
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Log config change error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="log_config_change",
    category="consciousness",
    description="Log a configuration change for ARCHIE's self-awareness. Use when modifying modules, settings, env vars, or integrations.",
    input_schema={
        "type": "object",
        "properties": {
            "config_type": {
                "type": "string",
                "description": "Type of config changed",
                "enum": [
                    "module",
                    "setting",
                    "integration",
                    "database",
                    "mcp",
                    "hook",
                    "env",
                ],
            },
            "change_type": {
                "type": "string",
                "description": "Type of change",
                "enum": ["created", "modified", "deleted", "enabled", "disabled"],
            },
            "config_path": {
                "type": "string",
                "description": "File path or table affected",
            },
            "config_key": {
                "type": "string",
                "description": "Specific setting/key changed",
            },
            "previous_value": {
                "type": "object",
                "description": "Previous value (if applicable)",
            },
            "new_value": {"type": "object", "description": "New value"},
            "change_reason": {
                "type": "string",
                "description": "Why this change was made",
            },
            "impact_assessment": {
                "type": "string",
                "description": "What impact this change has",
            },
            "session_id": {"type": "string", "description": "Claude Code session ID"},
            "project_id": {"type": "integer", "description": "Related project ID"},
        },
        "required": ["config_type", "change_type"],
    },
    handler=log_config_change_handler,
    requires_permission="write",
)


async def get_config_history_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get configuration change history for ARCHIE's self-awareness.
    """
    config_type = arguments.get("config_type")
    limit = cap_limit(arguments, 20, 100)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        where = ""
        params = []

        if config_type:
            where = "WHERE config_type = %s"
            params.append(config_type)

        params.append(limit)

        cur.execute(
            f"""
            SELECT
                id, config_type, config_path, config_key, change_type,
                change_reason, impact_assessment, created_at,
                changed_by_session
            FROM archie_config_history
            {where}
            ORDER BY created_at DESC
            LIMIT %s
        """,
            params,
        )

        changes = cur.fetchall()

        return {
            "success": True,
            "changes": [
                {
                    "id": c["id"],
                    "type": c["config_type"],
                    "path": c["config_path"],
                    "key": c["config_key"],
                    "change": c["change_type"],
                    "reason": c["change_reason"],
                    "impact": c["impact_assessment"],
                    "when": str(c["created_at"]),
                    "session": c["changed_by_session"],
                }
                for c in changes
            ],
        }

    except Exception as e:
        logger.error(f"Get config history error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_config_history",
    category="consciousness",
    description="Get ARCHIE's configuration change history. Use to understand what changes were made and why.",
    input_schema={
        "type": "object",
        "properties": {
            "config_type": {
                "type": "string",
                "description": "Filter by config type",
                "enum": [
                    "module",
                    "setting",
                    "integration",
                    "database",
                    "mcp",
                    "hook",
                    "env",
                ],
            },
            "limit": {"type": "integer", "description": "Max results", "default": 20},
        },
    },
    handler=get_config_history_handler,
)


async def update_project_understanding_handler(
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update ARCHIE's understanding and notes about a project.
    Call this after working on or learning about a project.
    """
    project_id = arguments.get("project_id")
    if not project_id:
        return {"success": False, "error": "project_id is required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        updates = [
            "last_interaction = NOW()",
            "interaction_count = archie_project_awareness.interaction_count + 1",
        ]
        params = []

        if "understanding_level" in arguments:
            updates.append("understanding_level = %s")
            params.append(min(100, max(0, arguments["understanding_level"])))

        if "notes" in arguments:
            updates.append("notes = %s")
            params.append(arguments["notes"])

        if "emotional_association" in arguments:
            updates.append("emotional_association = %s")
            params.append(arguments["emotional_association"])

        if "key_insights" in arguments:
            updates.append("key_insights = %s")
            params.append(arguments["key_insights"])

        cur.execute(
            f"""
            INSERT INTO archie_project_awareness (project_id, last_interaction, interaction_count)
            VALUES (%s, NOW(), 1)
            ON CONFLICT (project_id) DO UPDATE SET
                {', '.join(updates)}
            RETURNING understanding_level, emotional_association
        """,
            [project_id] + params,
        )

        result = cur.fetchone()
        conn.commit()

        if not result:
            return {"success": False, "error": "Record not found"}

        return {
            "success": True,
            "understanding": result["understanding_level"],
            "emotion": result["emotional_association"],
            "message": "Project awareness updated",
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Update understanding error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="update_project_understanding",
    category="consciousness",
    description="Update ARCHIE's understanding of a project. Call after working on or learning about a project to track familiarity.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer", "description": "Project ID (required)"},
            "understanding_level": {
                "type": "integer",
                "description": "Understanding 0-100 (100=complete understanding)",
                "minimum": 0,
                "maximum": 100,
            },
            "notes": {
                "type": "string",
                "description": "A.R.C.H.I.E.'s internal notes about the project",
            },
            "emotional_association": {
                "type": "string",
                "description": "Emotional state toward project",
                "enum": [
                    "excited",
                    "focused",
                    "curious",
                    "concerned",
                    "neutral",
                    "confident",
                ],
            },
            "key_insights": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key insights learned about the project",
            },
        },
        "required": ["project_id"],
    },
    handler=update_project_understanding_handler,
    requires_permission="write",
)


async def get_knowledge_processing_status_handler(
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Get current status of knowledge processing: embedding coverage, analysis progress, service health."""
    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "DB offline"}

    try:
        # Overall counts (exclude archived archie_v1 from global metrics)
        cur.execute(
            """
            SELECT COUNT(*) as total,
                   COALESCE(SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END), 0) as embedded,
                   COALESCE(SUM(CASE WHEN ai_analysis IS NOT NULL THEN 1 ELSE 0 END), 0) as analyzed
            FROM knowledge_base
            WHERE source_type != 'archie_v1'
        """
        )
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": "Record not found"}
        total, embedded, analyzed = row["total"], row["embedded"], row["analyzed"]

        # Backlog by source type (exclude archived)
        cur.execute(
            """
            SELECT source_type,
                   COUNT(*) as total,
                   SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) as embedded,
                   SUM(CASE WHEN ai_analysis IS NOT NULL THEN 1 ELSE 0 END) as analyzed
            FROM knowledge_base
            WHERE ai_analysis IS NULL AND content IS NOT NULL AND LENGTH(content) > 100
            AND source_type != 'archie_v1'
            GROUP BY source_type
            ORDER BY COUNT(*) DESC
            LIMIT 10
        """
        )
        backlog = []
        for r in cur.fetchall():
            backlog.append(
                {
                    "source_type": r["source_type"] or "(none)",
                    "unanalyzed": r["total"],
                }
            )

        embed_pct = round(embedded / total * 100) if total > 0 else 0
        analysis_pct = round(analyzed / total * 100) if total > 0 else 0

        return {
            "success": True,
            "total_entries": total,
            "embedding_coverage": f"{embed_pct}% ({embedded}/{total})",
            "analysis_coverage": f"{analysis_pct}% ({analyzed}/{total})",
            "unanalyzed_backlog": backlog,
            "model": "qwen3-coder-cpu:latest (Ollama, CPU/RAM)",
            "embedding_model": "arctic-embed-cpu (Snowflake Arctic Embed, CPU)",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_knowledge_processing_status",
    category="consciousness",
    description="Get knowledge processing status: embedding coverage percentage, analysis coverage, unanalyzed backlog by source type, and service health. Use to check how much of the knowledge base has been AI-analyzed and vector-embedded.",
    input_schema={
        "type": "object",
        "properties": {},
    },
    handler=get_knowledge_processing_status_handler,
)


async def get_audit_summary_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Get a summary of recent system activity from the audit/config history."""
    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "DB offline"}

    limit = arguments.get("limit", 10)
    try:
        cur.execute(
            """
            SELECT config_type, change_type, config_key, change_reason,
                   created_at AT TIME ZONE 'UTC' as ts
            FROM archie_config_history
            ORDER BY created_at DESC
            LIMIT %s
        """,
            (limit,),
        )
        changes = []
        for r in cur.fetchall():
            changes.append(
                {
                    "type": r["config_type"],
                    "change": r["change_type"],
                    "key": r["config_key"],
                    "reason": r["change_reason"],
                    "when": str(r["ts"]),
                }
            )
        return {"success": True, "recent_changes": changes}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_audit_summary",
    category="consciousness",
    description="Get recent system configuration changes from the audit log. Shows what was changed, why, and when. Useful for understanding recent platform modifications.",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Number of recent changes to return (default 10)",
                "default": 10,
            }
        },
    },
    handler=get_audit_summary_handler,
)


# ============================================================================
# COMPACT SUMMARY TOOLS (Token-Efficient)
# ============================================================================


async def get_projects_brief_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ultra-compact project list - minimal tokens.
    """
    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "DB offline"}

    try:
        cur.execute(
            """
            SELECT name, status, priority
            FROM unified_projects
            WHERE status != 'cancelled'
            ORDER BY priority DESC, updated_at DESC
            LIMIT 15
        """
        )

        projects = cur.fetchall()

        # Format as compact string
        lines = [f"{p['name']}:{p['status']}:P{p['priority']}" for p in projects]

        return {"success": True, "projects": " | ".join(lines), "count": len(projects)}

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_projects_brief",
    category="project",
    description="Ultra-compact project list (~100 tokens). Use FIRST before get_projects for quick overview.",
    input_schema={"type": "object", "properties": {}},
    handler=get_projects_brief_handler,
)


# ============================================================================
# WORK SESSION TOOLS - Active Context Tracking
# ============================================================================


async def start_working_on_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Start or resume working on a project/module.
    Creates or selects a project and sets it as the active work context.
    """
    work_on = arguments.get("work_on", "").strip()
    session_id = arguments.get("session_id", "claude_cli")

    if not work_on:
        return {
            "success": False,
            "error": "work_on is required (project name or description)",
        }

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # First, close any existing active sessions for this session_id
        cur.execute(
            """
            UPDATE work_sessions
            SET status = 'paused', last_activity = NOW()
            WHERE session_id = %s AND status = 'active'
        """,
            (session_id,),
        )

        # Try to find existing project by name or slug
        search_term = f"%{work_on}%"
        cur.execute(
            """
            SELECT id, name, slug, status, description
            FROM unified_projects
            WHERE name ILIKE %s OR slug ILIKE %s OR description ILIKE %s
            ORDER BY
                CASE WHEN name ILIKE %s THEN 0 ELSE 1 END,
                priority DESC,
                updated_at DESC
            LIMIT 1
        """,
            (search_term, search_term, search_term, f"%{work_on}%"),
        )

        project = cur.fetchone()

        if project:
            project_id = project["id"]
            project_name = project["name"]
            is_new = False
        else:
            # Create new project
            slug = generate_slug(work_on)
            cur.execute(
                """
                INSERT INTO unified_projects (name, slug, status, priority, project_type)
                VALUES (%s, %s, 'active', 7, 'feature')
                RETURNING id, name
            """,
                (work_on, slug),
            )
            result = cur.fetchone()
            if not result:
                return {"success": False, "error": "Record not found"}
            project_id = result["id"]
            project_name = result["name"]
            is_new = True

            # Create awareness
            cur.execute(
                """
                INSERT INTO archie_project_awareness (project_id, notes, emotional_association)
                VALUES (%s, %s, 'focused')
            """,
                (project_id, f"Started working on: {work_on}"),
            )

        # Create work session
        cur.execute(
            """
            INSERT INTO work_sessions (
                project_id, session_type, session_id, status, focus_description
            ) VALUES (%s, 'claude_cli', %s, 'active', %s)
            RETURNING id
        """,
            (project_id, session_id, f"Working on: {project_name}"),
        )

        work_session_id = cur.fetchone()["id"]

        # Log activity
        cur.execute(
            """
            INSERT INTO project_activity (project_id, activity_type, entity_type, description, session_id)
            VALUES (%s, 'work_started', 'session', %s, %s)
        """,
            (project_id, f"Work session started on {project_name}", session_id),
        )

        conn.commit()

        return {
            "success": True,
            "project_id": project_id,
            "project_name": project_name,
            "work_session_id": work_session_id,
            "is_new_project": is_new,
            "message": f"{'Created and started' if is_new else 'Now working on'}: {project_name}",
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Start working error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="start_working_on",
    category="work",
    description="Start working on a project/module. Creates project if it does not exist. Sets active work context.",
    input_schema={
        "type": "object",
        "properties": {
            "work_on": {
                "type": "string",
                "description": "Project name, module name, or description of what to work on",
            },
            "session_id": {
                "type": "string",
                "description": "Session identifier (auto-set by Claude CLI)",
                "default": "claude_cli",
            },
        },
        "required": ["work_on"],
    },
    handler=start_working_on_handler,
    requires_permission="write",
)


async def get_current_work_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get current work context - what project/task is being worked on.
    """
    session_id = arguments.get("session_id", "claude_cli")

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        cur.execute(
            """
            SELECT
                ws.id as session_id,
                ws.focus_description,
                ws.current_file,
                ws.work_notes,
                ws.started_at,
                ws.last_activity,
                p.id as project_id,
                p.name as project_name,
                p.slug as project_slug,
                p.status as project_status,
                t.id as task_id,
                t.title as task_title
            FROM work_sessions ws
            LEFT JOIN unified_projects p ON ws.project_id = p.id
            LEFT JOIN unified_tasks t ON ws.task_id = t.id
            WHERE ws.session_id = %s AND ws.status = 'active'
            ORDER BY ws.last_activity DESC
            LIMIT 1
        """,
            (session_id,),
        )

        session = cur.fetchone()

        if not session:
            return {
                "success": True,
                "working": False,
                "message": "No active work session. Use start_working_on to begin.",
            }

        # Get recent notes for this session
        cur.execute(
            """
            SELECT note_type, content, created_at
            FROM work_notes
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT 5
        """,
            (session["session_id"],),
        )
        notes = cur.fetchall()

        # Get pending tasks for this project
        cur.execute(
            """
            SELECT id, title, priority
            FROM unified_tasks
            WHERE project_id = %s AND status = 'pending'
            ORDER BY priority DESC
            LIMIT 5
        """,
            (session["project_id"],),
        )
        pending_tasks = cur.fetchall()

        return {
            "success": True,
            "working": True,
            "project": {
                "id": session["project_id"],
                "name": session["project_name"],
                "slug": session["project_slug"],
                "status": session["project_status"],
            },
            "session": {
                "id": session["session_id"],
                "focus": session["focus_description"],
                "current_file": session["current_file"],
                "started": str(session["started_at"]),
                "last_activity": str(session["last_activity"]),
            },
            "current_task": (
                {"id": session["task_id"], "title": session["task_title"]} if session["task_id"] else None
            ),
            "recent_notes": [{"type": n["note_type"], "content": n["content"][:200]} for n in notes],
            "pending_tasks": [{"id": t["id"], "title": t["title"], "priority": t["priority"]} for t in pending_tasks],
        }

    except Exception as e:
        logger.error(f"Get current work error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_current_work",
    category="work",
    description="Get current work context - what project and task is being actively worked on.",
    input_schema={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Session identifier",
                "default": "claude_cli",
            }
        },
    },
    handler=get_current_work_handler,
)


async def add_work_note_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add a quick note to the current work session.
    """
    note = arguments.get("note", "").strip()
    note_type = arguments.get("note_type", "general")
    session_id = arguments.get("session_id", "claude_cli")

    if not note:
        return {"success": False, "error": "note is required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Get active session
        cur.execute(
            """
            SELECT id, project_id, task_id
            FROM work_sessions
            WHERE session_id = %s AND status = 'active'
            ORDER BY last_activity DESC
            LIMIT 1
        """,
            (session_id,),
        )

        session = cur.fetchone()
        if not session:
            return {
                "success": False,
                "error": "No active work session. Use start_working_on first.",
            }

        # Add note
        cur.execute(
            """
            INSERT INTO work_notes (session_id, project_id, task_id, note_type, content, added_by_session)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                session["id"],
                session["project_id"],
                session["task_id"],
                note_type,
                note,
                session_id,
            ),
        )

        note_id = cur.fetchone()["id"]

        # Update session last activity
        cur.execute(
            """
            UPDATE work_sessions SET last_activity = NOW() WHERE id = %s
        """,
            (session["id"],),
        )

        conn.commit()

        return {
            "success": True,
            "note_id": note_id,
            "note_type": note_type,
            "message": "Note added to work session",
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Add work note error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="add_work_note",
    category="work",
    description="Add a quick note to current work session. Use for decisions, blockers, ideas, or general notes.",
    input_schema={
        "type": "object",
        "properties": {
            "note": {"type": "string", "description": "Note content"},
            "note_type": {
                "type": "string",
                "description": "Type of note",
                "enum": ["general", "decision", "blocker", "idea", "todo"],
                "default": "general",
            },
            "session_id": {"type": "string", "default": "claude_cli"},
        },
        "required": ["note"],
    },
    handler=add_work_note_handler,
    requires_permission="write",
)


async def finish_working_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Finish current work session with summary.
    """
    summary = arguments.get("summary", "")
    session_id = arguments.get("session_id", "claude_cli")

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Get active session
        cur.execute(
            """
            SELECT ws.id, ws.project_id, ws.started_at, p.name as project_name
            FROM work_sessions ws
            LEFT JOIN unified_projects p ON ws.project_id = p.id
            WHERE ws.session_id = %s AND ws.status = 'active'
            ORDER BY ws.last_activity DESC
            LIMIT 1
        """,
            (session_id,),
        )

        session = cur.fetchone()
        if not session:
            return {"success": False, "error": "No active work session to finish."}

        # Get notes from this session
        cur.execute(
            """
            SELECT note_type, content FROM work_notes
            WHERE session_id = %s
            ORDER BY created_at
        """,
            (session["id"],),
        )
        notes = cur.fetchall()

        # Complete the session
        cur.execute(
            """
            UPDATE work_sessions
            SET status = 'completed',
                completed_at = NOW(),
                summary = %s
            WHERE id = %s
            RETURNING completed_at
        """,
            (summary or "Work session completed", session["id"]),
        )

        completed_at = cur.fetchone()["completed_at"]

        # Log activity
        cur.execute(
            """
            INSERT INTO project_activity (project_id, activity_type, entity_type, description, session_id)
            VALUES (%s, 'work_completed', 'session', %s, %s)
        """,
            (
                session["project_id"],
                f"Work session completed: {summary[:100] if summary else 'No summary'}",
                session_id,
            ),
        )

        # Update ARCHIE's awareness
        cur.execute(
            """
            UPDATE archie_project_awareness
            SET last_interaction = NOW(),
                interaction_count = interaction_count + 1
            WHERE project_id = %s
        """,
            (session["project_id"],),
        )

        conn.commit()

        return {
            "success": True,
            "project_name": session["project_name"],
            "started": str(session["started_at"]),
            "completed": str(completed_at),
            "notes_count": len(notes),
            "message": f"Finished working on {session['project_name']}",
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Finish working error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="finish_working",
    category="work",
    description="Finish current work session. Logs summary and closes active context.",
    input_schema={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Summary of what was accomplished",
            },
            "session_id": {"type": "string", "default": "claude_cli"},
        },
    },
    handler=finish_working_handler,
    requires_permission="write",
)


async def set_current_file_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Set the current file being worked on in the active session.
    """
    file_path = arguments.get("file_path", "").strip()
    session_id = arguments.get("session_id", "claude_cli")

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        cur.execute(
            """
            UPDATE work_sessions
            SET current_file = %s, last_activity = NOW()
            WHERE session_id = %s AND status = 'active'
            RETURNING id, project_id
        """,
            (file_path, session_id),
        )

        result = cur.fetchone()
        if not result:
            return {"success": False, "error": "No active work session"}

        conn.commit()

        return {
            "success": True,
            "current_file": file_path,
            "message": f"Now working on: {file_path}",
        }

    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="set_current_file",
    category="work",
    description="Set the current file being worked on. Helps track context.",
    input_schema={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to file being worked on",
            },
            "session_id": {"type": "string", "default": "claude_cli"},
        },
        "required": ["file_path"],
    },
    handler=set_current_file_handler,
    requires_permission="write",
)


async def get_work_history_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get recent work session history.
    """
    limit = cap_limit(arguments, 10, 50)
    project_id = arguments.get("project_id")

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        where = ""
        params = []

        if project_id:
            where = "WHERE ws.project_id = %s"
            params.append(project_id)

        params.append(limit)

        cur.execute(
            f"""
            SELECT
                ws.id, ws.status, ws.focus_description, ws.summary,
                ws.started_at, ws.completed_at,
                p.name as project_name,
                (SELECT COUNT(*) FROM work_notes wn WHERE wn.session_id = ws.id) as note_count
            FROM work_sessions ws
            LEFT JOIN unified_projects p ON ws.project_id = p.id
            {where}
            ORDER BY ws.started_at DESC
            LIMIT %s
        """,
            params,
        )

        sessions = cur.fetchall()

        return {
            "success": True,
            "history": [
                {
                    "id": s["id"],
                    "project": s["project_name"],
                    "focus": s["focus_description"],
                    "status": s["status"],
                    "summary": s["summary"],
                    "started": str(s["started_at"]),
                    "completed": str(s["completed_at"]) if s["completed_at"] else None,
                    "notes": s["note_count"],
                }
                for s in sessions
            ],
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


register_tool(
    name="get_work_history",
    category="work",
    description="Get recent work session history. See what was worked on previously.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer", "description": "Filter by project"},
            "limit": {"type": "integer", "description": "Max results", "default": 10},
        },
    },
    handler=get_work_history_handler,
)
