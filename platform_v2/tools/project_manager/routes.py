"""
A.R.C.H.I.E. Project Manager - API Routes
Phase 65: Unified Project & Documentation System

API endpoints for project management, task tracking, documentation,
team collaboration, and ARCHIE's self-awareness.
"""

from flask import request, jsonify, render_template, session
from functools import wraps
import json
import re
from datetime import datetime

from . import project_manager_bp
from database import get_db_connection

# ============================================================================
# HELPERS
# ============================================================================


def generate_slug(name: str) -> str:
    """Generate URL-friendly slug from name"""
    slug = re.sub(r"[^a-zA-Z0-9\s-]", "", name.lower())
    slug = re.sub(r"\s+", "-", slug)
    return slug[:100]


def get_current_user():
    """Get current user from session"""
    return session.get("user_id")


def api_response(success: bool, data: dict = None, error: str = None, status_code: int = 200):
    """Standard API response format"""
    response = {"success": success}
    if data:
        response.update(data)
    if error:
        response["error"] = error
    return jsonify(response), status_code


# ============================================================================
# PROJECT ENDPOINTS
# ============================================================================


@project_manager_bp.route("/api/projects", methods=["GET"])
def api_list_projects():
    """List all projects with optional filtering"""
    status = request.args.get("status")
    project_type = request.args.get("type")
    limit = min(int(request.args.get("limit", 50)), 200)

    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        where_clauses = []
        params = []

        if status:
            where_clauses.append("status = %s")
            params.append(status)
        if project_type:
            where_clauses.append("project_type = %s")
            params.append(project_type)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        params.append(limit)

        cur.execute(
            f"""
            SELECT
                p.id, p.name, p.slug, p.description, p.status,
                p.priority, p.project_type, p.tags, p.created_at,
                p.start_date, p.target_date,
                COALESCE(get_project_progress(p.id), 0) as progress,
                (SELECT COUNT(*) FROM unified_tasks t WHERE t.project_id = p.id) as task_count
            FROM unified_projects p
            {where_sql}
            ORDER BY p.priority DESC, p.updated_at DESC
            LIMIT %s
        """,
            params,
        )

        projects = cur.fetchall()

        return api_response(
            True,
            {
                "projects": [
                    {
                        "id": p["id"],
                        "name": p["name"],
                        "slug": p["slug"],
                        "description": p["description"],
                        "status": p["status"],
                        "priority": p["priority"],
                        "type": p["project_type"],
                        "tags": p["tags"],
                        "progress": round(p["progress"], 1),
                        "task_count": p["task_count"],
                        "start_date": str(p["start_date"]) if p["start_date"] else None,
                        "target_date": (str(p["target_date"]) if p["target_date"] else None),
                        "created_at": str(p["created_at"]),
                    }
                    for p in projects
                ],
                "total": len(projects),
            },
        )

    except Exception as e:
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


@project_manager_bp.route("/api/projects/<int:project_id>", methods=["GET"])
def api_get_project(project_id):
    """Get full project details"""
    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        cur.execute("SELECT * FROM unified_projects WHERE id = %s", (project_id,))
        project = cur.fetchone()

        if not project:
            return api_response(False, error="Project not found", status_code=404)

        # Get tasks
        cur.execute(
            """
            SELECT id, title, status, priority, task_type, estimated_effort,
                   assigned_user_id, assigned_agent_id, due_date, completed_at
            FROM unified_tasks
            WHERE project_id = %s
            ORDER BY priority DESC, status, created_at
        """,
            (project_id,),
        )
        tasks = cur.fetchall()

        # Get team
        cur.execute(
            """
            SELECT pt.*, u.username, a.name as agent_name
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
        """,
            (project_id,),
        )
        docs = cur.fetchall()

        # Get decisions
        cur.execute(
            """
            SELECT id, decision_number, title, status, decided_at
            FROM project_decisions
            WHERE project_id = %s
            ORDER BY decision_number DESC
        """,
            (project_id,),
        )
        decisions = cur.fetchall()

        # Get awareness
        cur.execute(
            """
            SELECT * FROM archie_project_awareness WHERE project_id = %s
        """,
            (project_id,),
        )
        awareness = cur.fetchone()

        return api_response(
            True,
            {
                "project": dict(project),
                "tasks": [dict(t) for t in tasks],
                "team": [
                    {
                        "id": t["id"],
                        "name": t["username"] or t["agent_name"],
                        "type": "user" if t["user_id"] else "agent",
                        "role": t["role"],
                        "permissions": t["permissions"],
                    }
                    for t in team
                ],
                "documents": [dict(d) for d in docs],
                "decisions": [dict(d) for d in decisions],
                "awareness": dict(awareness) if awareness else None,
            },
        )

    except Exception as e:
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


@project_manager_bp.route("/api/projects", methods=["POST"])
def api_create_project():
    """Create a new project"""
    data = request.get_json()

    if not data or not data.get("name"):
        return api_response(False, error="Project name is required", status_code=400)

    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        slug = generate_slug(data["name"])

        # Check for duplicate
        cur.execute("SELECT id FROM unified_projects WHERE slug = %s", (slug,))
        if cur.fetchone():
            slug = f"{slug}-{int(datetime.now().timestamp())}"

        cur.execute(
            """
            INSERT INTO unified_projects (
                name, slug, description, status, priority,
                project_type, parent_project_id, tags, metadata,
                start_date, target_date, created_by_user_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, slug
        """,
            (
                data["name"],
                slug,
                data.get("description"),
                data.get("status", "planning"),
                data.get("priority", 5),
                data.get("project_type", "feature"),
                data.get("parent_project_id"),
                data.get("tags", []),
                json.dumps(data.get("metadata", {})),
                data.get("start_date"),
                data.get("target_date"),
                get_current_user(),
            ),
        )

        result = cur.fetchone()

        # Create awareness record
        cur.execute(
            """
            INSERT INTO archie_project_awareness (project_id, notes, emotional_association)
            VALUES (%s, %s, 'curious')
        """,
            (result["id"], f"New project created: {data['name']}"),
        )

        conn.commit()

        return api_response(True, {"project_id": result["id"], "slug": result["slug"]}, status_code=201)

    except Exception as e:
        conn.rollback()
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


@project_manager_bp.route("/api/projects/<int:project_id>", methods=["PUT"])
def api_update_project(project_id):
    """Update a project"""
    data = request.get_json()

    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        updates = []
        params = []

        allowed_fields = [
            "name",
            "description",
            "status",
            "priority",
            "project_type",
            "tags",
            "start_date",
            "target_date",
        ]

        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = %s")
                params.append(data[field])

        if data.get("status") == "completed":
            updates.append("completed_at = NOW()")

        if not updates:
            return api_response(False, error="No updates provided", status_code=400)

        params.append(project_id)
        cur.execute(
            f"""
            UPDATE unified_projects
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING id, name, status
        """,
            params,
        )

        result = cur.fetchone()
        if not result:
            return api_response(False, error="Project not found", status_code=404)

        conn.commit()
        return api_response(True, {"project": dict(result)})

    except Exception as e:
        conn.rollback()
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


# ============================================================================
# TASK ENDPOINTS
# ============================================================================


@project_manager_bp.route("/api/projects/<int:project_id>/tasks", methods=["GET"])
def api_list_tasks(project_id):
    """List tasks for a project"""
    status = request.args.get("status")

    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        where = "project_id = %s"
        params = [project_id]

        if status:
            where += " AND status = %s"
            params.append(status)

        cur.execute(
            f"""
            SELECT t.*,
                   u.username as assigned_user,
                   a.name as assigned_agent
            FROM unified_tasks t
            LEFT JOIN users u ON t.assigned_user_id = u.id
            LEFT JOIN agents a ON t.assigned_agent_id = a.id
            WHERE {where}
            ORDER BY t.priority DESC, t.status, t.created_at
        """,
            params,
        )

        tasks = cur.fetchall()

        return api_response(True, {"tasks": [dict(t) for t in tasks], "total": len(tasks)})

    except Exception as e:
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


@project_manager_bp.route("/api/tasks", methods=["POST"])
def api_create_task():
    """Create a new task"""
    data = request.get_json()

    if not data or not data.get("project_id") or not data.get("title"):
        return api_response(False, error="project_id and title are required", status_code=400)

    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        cur.execute(
            """
            INSERT INTO unified_tasks (
                project_id, title, description, status, priority,
                task_type, estimated_effort, assigned_user_id, assigned_agent_id,
                parent_task_id, dependencies, due_date, tags
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                data["project_id"],
                data["title"],
                data.get("description"),
                data.get("status", "pending"),
                data.get("priority", 5),
                data.get("task_type", "implementation"),
                data.get("estimated_effort"),
                data.get("assigned_user_id"),
                data.get("assigned_agent_id"),
                data.get("parent_task_id"),
                json.dumps(data.get("dependencies", [])),
                data.get("due_date"),
                data.get("tags", []),
            ),
        )

        task_id = cur.fetchone()["id"]
        conn.commit()

        return api_response(True, {"task_id": task_id}, status_code=201)

    except Exception as e:
        conn.rollback()
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


@project_manager_bp.route("/api/tasks/<int:task_id>", methods=["PUT"])
def api_update_task(task_id):
    """Update a task"""
    data = request.get_json()

    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        updates = []
        params = []

        allowed_fields = [
            "title",
            "description",
            "status",
            "priority",
            "task_type",
            "estimated_effort",
            "assigned_user_id",
            "assigned_agent_id",
            "due_date",
            "blockers",
        ]

        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = %s")
                params.append(data[field])

        if data.get("status") == "completed":
            updates.append("completed_at = NOW()")
        elif data.get("status") == "in_progress" and "started_at" not in updates:
            updates.append("started_at = COALESCE(started_at, NOW())")

        if not updates:
            return api_response(False, error="No updates provided", status_code=400)

        params.append(task_id)
        cur.execute(
            f"""
            UPDATE unified_tasks
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING id, title, status
        """,
            params,
        )

        result = cur.fetchone()
        if not result:
            return api_response(False, error="Task not found", status_code=404)

        conn.commit()
        return api_response(True, {"task": dict(result)})

    except Exception as e:
        conn.rollback()
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


# ============================================================================
# DOCUMENT ENDPOINTS
# ============================================================================


@project_manager_bp.route("/api/projects/<int:project_id>/documents", methods=["GET"])
def api_list_documents(project_id):
    """List documents for a project"""
    doc_type = request.args.get("type")

    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        where = "project_id = %s AND is_current = TRUE"
        params = [project_id]

        if doc_type:
            where += " AND doc_type = %s"
            params.append(doc_type)

        cur.execute(
            f"""
            SELECT id, doc_type, title, version, file_path, created_at, updated_at
            FROM project_documents
            WHERE {where}
            ORDER BY doc_type, title
        """,
            params,
        )

        docs = cur.fetchall()

        return api_response(True, {"documents": [dict(d) for d in docs]})

    except Exception as e:
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


@project_manager_bp.route("/api/documents/<int:doc_id>", methods=["GET"])
def api_get_document(doc_id):
    """Get document content"""
    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        cur.execute(
            """
            SELECT * FROM project_documents WHERE id = %s
        """,
            (doc_id,),
        )

        doc = cur.fetchone()
        if not doc:
            return api_response(False, error="Document not found", status_code=404)

        return api_response(True, {"document": dict(doc)})

    except Exception as e:
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


@project_manager_bp.route("/api/documents", methods=["POST"])
def api_create_document():
    """Create or update a document"""
    data = request.get_json()

    if not data or not data.get("project_id") or not data.get("title") or not data.get("content"):
        return api_response(False, error="project_id, title, and content are required", status_code=400)

    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        # Check if document exists
        cur.execute(
            """
            SELECT id, version FROM project_documents
            WHERE project_id = %s AND title = %s AND is_current = TRUE
        """,
            (data["project_id"], data["title"]),
        )

        existing = cur.fetchone()

        if existing:
            # Mark old version as not current
            cur.execute(
                """
                UPDATE project_documents SET is_current = FALSE WHERE id = %s
            """,
                (existing["id"],),
            )

            new_version = existing["version"] + 1
        else:
            new_version = 1

        # Create new version
        cur.execute(
            """
            INSERT INTO project_documents (
                project_id, doc_type, title, content, content_format,
                version, is_current, file_path, tags, updated_by_user_id
            ) VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s)
            RETURNING id
        """,
            (
                data["project_id"],
                data.get("doc_type", "readme"),
                data["title"],
                data["content"],
                data.get("content_format", "markdown"),
                new_version,
                data.get("file_path"),
                data.get("tags", []),
                get_current_user(),
            ),
        )

        doc_id = cur.fetchone()["id"]
        conn.commit()

        return api_response(True, {"document_id": doc_id, "version": new_version}, status_code=201)

    except Exception as e:
        conn.rollback()
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


# ============================================================================
# DECISION ENDPOINTS
# ============================================================================


@project_manager_bp.route("/api/decisions", methods=["GET"])
def api_list_decisions():
    """List architectural decisions"""
    project_id = request.args.get("project_id")
    limit = min(int(request.args.get("limit", 50)), 200)

    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        where = ""
        params = []

        if project_id:
            where = "WHERE project_id = %s"
            params.append(int(project_id))

        params.append(limit)

        cur.execute(
            f"""
            SELECT d.*, p.name as project_name
            FROM project_decisions d
            LEFT JOIN unified_projects p ON d.project_id = p.id
            {where}
            ORDER BY d.decided_at DESC
            LIMIT %s
        """,
            params,
        )

        decisions = cur.fetchall()

        return api_response(True, {"decisions": [dict(d) for d in decisions]})

    except Exception as e:
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


@project_manager_bp.route("/api/decisions", methods=["POST"])
def api_create_decision():
    """Create a new decision record"""
    data = request.get_json()

    if not data or not data.get("title") or not data.get("decision"):
        return api_response(False, error="title and decision are required", status_code=400)

    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        # Get next ADR number
        project_id = data.get("project_id")
        cur.execute(
            """
            SELECT COALESCE(MAX(decision_number), 0) + 1 as next_num
            FROM project_decisions
            WHERE project_id IS NOT DISTINCT FROM %s
        """,
            (project_id,),
        )
        next_num = cur.fetchone()["next_num"]

        cur.execute(
            """
            INSERT INTO project_decisions (
                project_id, task_id, decision_number, title, status,
                context, decision, alternatives, consequences,
                decided_by_user_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, decision_number
        """,
            (
                project_id,
                data.get("task_id"),
                next_num,
                data["title"],
                data.get("status", "accepted"),
                data.get("context"),
                data["decision"],
                data.get("alternatives"),
                data.get("consequences"),
                get_current_user(),
            ),
        )

        result = cur.fetchone()
        conn.commit()

        return api_response(
            True,
            {
                "decision_id": result["id"],
                "adr_number": f"ADR-{result['decision_number']:03d}",
            },
            status_code=201,
        )

    except Exception as e:
        conn.rollback()
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


# ============================================================================
# TEAM ENDPOINTS
# ============================================================================


@project_manager_bp.route("/api/projects/<int:project_id>/team", methods=["GET"])
def api_get_team(project_id):
    """Get project team"""
    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        cur.execute(
            """
            SELECT pt.*, u.username, u.email, a.name as agent_name
            FROM project_team pt
            LEFT JOIN users u ON pt.user_id = u.id
            LEFT JOIN agents a ON pt.agent_id = a.id
            WHERE pt.project_id = %s
            ORDER BY pt.role, pt.assigned_at
        """,
            (project_id,),
        )

        team = cur.fetchall()

        return api_response(
            True,
            {
                "team": [
                    {
                        "id": t["id"],
                        "name": t["username"] or t["agent_name"],
                        "type": "user" if t["user_id"] else "agent",
                        "user_id": t["user_id"],
                        "agent_id": t["agent_id"],
                        "role": t["role"],
                        "permissions": t["permissions"],
                        "responsibilities": t["responsibilities"],
                    }
                    for t in team
                ]
            },
        )

    except Exception as e:
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


@project_manager_bp.route("/api/projects/<int:project_id>/team", methods=["POST"])
def api_add_team_member(project_id):
    """Add a team member to a project"""
    data = request.get_json()

    if not data or (not data.get("user_id") and not data.get("agent_id")):
        return api_response(False, error="user_id or agent_id is required", status_code=400)

    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        cur.execute(
            """
            INSERT INTO project_team (
                project_id, user_id, agent_id, role, permissions,
                responsibilities, assigned_by_user_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
        """,
            (
                project_id,
                data.get("user_id"),
                data.get("agent_id"),
                data.get("role", "contributor"),
                json.dumps(data.get("permissions", {"read": True, "write": False, "admin": False})),
                data.get("responsibilities"),
                get_current_user(),
            ),
        )

        result = cur.fetchone()
        conn.commit()

        if result:
            return api_response(True, {"team_member_id": result["id"]}, status_code=201)
        else:
            return api_response(False, error="Member already on team", status_code=409)

    except Exception as e:
        conn.rollback()
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


# ============================================================================
# ACTIVITY ENDPOINTS
# ============================================================================


@project_manager_bp.route("/api/activity", methods=["GET"])
def api_get_activity():
    """Get activity feed"""
    project_id = request.args.get("project_id")
    limit = min(int(request.args.get("limit", 50)), 200)

    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        where = ""
        params = []

        if project_id:
            where = "WHERE pa.project_id = %s"
            params.append(int(project_id))

        params.append(limit)

        cur.execute(
            f"""
            SELECT
                pa.*,
                u.username, a.name as agent_name,
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

        return api_response(
            True,
            {
                "activities": [
                    {
                        "id": a["id"],
                        "type": a["activity_type"],
                        "entity": a["entity_type"],
                        "description": a["description"],
                        "actor": a["username"] or a["agent_name"] or "system",
                        "project": a["project_name"],
                        "created_at": str(a["created_at"]),
                    }
                    for a in activities
                ]
            },
        )

    except Exception as e:
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


# ============================================================================
# CONSCIOUSNESS / SELF-AWARENESS ENDPOINTS
# ============================================================================


@project_manager_bp.route("/api/config-history", methods=["GET"])
def api_get_config_history():
    """Get ARCHIE's configuration change history"""
    config_type = request.args.get("type")
    limit = min(int(request.args.get("limit", 50)), 200)

    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        where = ""
        params = []

        if config_type:
            where = "WHERE config_type = %s"
            params.append(config_type)

        params.append(limit)

        cur.execute(
            f"""
            SELECT * FROM archie_config_history
            {where}
            ORDER BY created_at DESC
            LIMIT %s
        """,
            params,
        )

        changes = cur.fetchall()

        return api_response(True, {"changes": [dict(c) for c in changes]})

    except Exception as e:
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


@project_manager_bp.route("/api/config-history", methods=["POST"])
def api_log_config_change():
    """Log a configuration change"""
    data = request.get_json()

    if not data or not data.get("config_type") or not data.get("change_type"):
        return api_response(False, error="config_type and change_type are required", status_code=400)

    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        cur.execute(
            """
            INSERT INTO archie_config_history (
                config_type, config_path, config_key, change_type,
                previous_value, new_value, change_reason,
                impact_assessment, changed_by_user_id, changed_by_session,
                related_project_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                data["config_type"],
                data.get("config_path"),
                data.get("config_key"),
                data["change_type"],
                (json.dumps(data.get("previous_value")) if data.get("previous_value") else None),
                json.dumps(data.get("new_value")) if data.get("new_value") else None,
                data.get("change_reason"),
                data.get("impact_assessment"),
                get_current_user(),
                data.get("session_id"),
                data.get("project_id"),
            ),
        )

        change_id = cur.fetchone()["id"]
        conn.commit()

        return api_response(True, {"change_id": change_id}, status_code=201)

    except Exception as e:
        conn.rollback()
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


@project_manager_bp.route("/api/projects/<int:project_id>/awareness", methods=["GET"])
def api_get_awareness(project_id):
    """Get ARCHIE's awareness of a project"""
    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        cur.execute(
            """
            SELECT * FROM archie_project_awareness WHERE project_id = %s
        """,
            (project_id,),
        )

        awareness = cur.fetchone()

        if not awareness:
            return api_response(True, {"awareness": None})

        return api_response(True, {"awareness": dict(awareness)})

    except Exception as e:
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


@project_manager_bp.route("/api/projects/<int:project_id>/awareness", methods=["PUT"])
def api_update_awareness(project_id):
    """Update ARCHIE's awareness of a project"""
    data = request.get_json()

    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database connection failed", status_code=500)

    try:
        cur.execute(
            """
            INSERT INTO archie_project_awareness (
                project_id, understanding_level, notes,
                emotional_association, key_insights,
                last_interaction, interaction_count
            ) VALUES (%s, %s, %s, %s, %s, NOW(), 1)
            ON CONFLICT (project_id) DO UPDATE SET
                understanding_level = COALESCE(%s, archie_project_awareness.understanding_level),
                notes = COALESCE(%s, archie_project_awareness.notes),
                emotional_association = COALESCE(%s, archie_project_awareness.emotional_association),
                key_insights = COALESCE(%s, archie_project_awareness.key_insights),
                last_interaction = NOW(),
                interaction_count = archie_project_awareness.interaction_count + 1
            RETURNING *
        """,
            (
                project_id,
                data.get("understanding_level", 0),
                data.get("notes"),
                data.get("emotional_association", "neutral"),
                data.get("key_insights", []),
                data.get("understanding_level"),
                data.get("notes"),
                data.get("emotional_association"),
                data.get("key_insights"),
            ),
        )

        awareness = cur.fetchone()
        conn.commit()

        return api_response(True, {"awareness": dict(awareness)})

    except Exception as e:
        conn.rollback()
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()


# ============================================================================
# DASHBOARD / UI ROUTES
# ============================================================================


@project_manager_bp.route("/")
def dashboard():
    """Project Manager dashboard"""
    return render_template("tools/project_manager/dashboard.html")


@project_manager_bp.route("/projects")
def projects_list():
    """Projects list view"""
    return render_template("tools/project_manager/projects.html")


@project_manager_bp.route("/projects/<int:project_id>")
def project_detail(project_id):
    """Project detail view"""
    return render_template("tools/project_manager/project_detail.html", project_id=project_id)


# ============================================================================
# STATUS ENDPOINT
# ============================================================================


@project_manager_bp.route("/api/status", methods=["GET"])
def api_status():
    """Get Project Manager module status"""
    conn, cur = get_db_connection()
    if not conn:
        return api_response(False, error="Database offline", status_code=500)

    try:
        cur.execute("SELECT COUNT(*) FROM unified_projects")
        project_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) FROM unified_tasks WHERE status != 'completed'")
        open_tasks = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) FROM project_decisions")
        decision_count = cur.fetchone()["count"]

        return api_response(
            True,
            {
                "status": "healthy",
                "module": "project_manager",
                "version": "1.0.0",
                "stats": {
                    "projects": project_count,
                    "open_tasks": open_tasks,
                    "decisions": decision_count,
                },
            },
        )

    except Exception as e:
        return api_response(False, error=str(e), status_code=500)
    finally:
        cur.close()
        conn.close()
