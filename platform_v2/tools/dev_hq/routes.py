"""Dev HQ Routes - Admin Only, Hub Only"""

import os
import re
import json as json_module
import urllib.request
import urllib.error
from flask import render_template, jsonify, request, abort
from flask_login import login_required, current_user
from psycopg2.extras import RealDictCursor, Json
from database import get_db_connection
from . import dev_hq_bp

# DB Schema and API Docs - reuse Blueprint intelligence functions
try:
    from tools.blueprint.blueprint_intelligence import (
        get_database_schema,
        get_api_endpoints,
    )

    INTELLIGENCE_AVAILABLE = True
except ImportError:
    INTELLIGENCE_AVAILABLE = False


def admin_hub_only(f):
    """Decorator: require admin role + hub deployment mode."""
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        if os.getenv("DEPLOYMENT_MODE", "hub") == "business_node":
            abort(404)
        return f(*args, **kwargs)

    return decorated


@dev_hq_bp.route("/")
@login_required
@admin_hub_only
def index():
    """Dev HQ main page."""
    return render_template("dev_hq.html")


# ---------------------------------------------------------------------------
# Task 4: Overview + Projects CRUD + Tasks CRUD
# ---------------------------------------------------------------------------


@dev_hq_bp.route("/api/overview")
@login_required
@admin_hub_only
def api_overview():
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT status, COUNT(*) as count FROM unified_projects GROUP BY status")
            project_stats = {row["status"]: row["count"] for row in cur.fetchall()}

            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status NOT IN ('completed', 'cancelled')) as open_tasks,
                    COUNT(*) FILTER (
                        WHERE status = 'completed'
                        AND completed_at >= NOW() - INTERVAL '7 days'
                    ) as completed_this_week,
                    COUNT(*) FILTER (
                        WHERE due_date < NOW()
                        AND status NOT IN ('completed', 'cancelled')
                    ) as overdue
                FROM unified_tasks
            """
            )
            task_stats = dict(cur.fetchone())

            cur.execute(
                """
                SELECT pa.*, up.name as project_name
                FROM project_activity pa
                LEFT JOIN unified_projects up ON pa.project_id = up.id
                ORDER BY pa.created_at DESC LIMIT 20
            """
            )
            activity = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT p.*, COUNT(t.id) as total_tasks,
                    COUNT(t.id) FILTER (WHERE t.status = 'completed') as completed_tasks
                FROM unified_projects p
                LEFT JOIN unified_tasks t ON t.project_id = p.id
                WHERE p.status = 'active'
                GROUP BY p.id ORDER BY p.updated_at DESC LIMIT 12
            """
            )
            active_projects = [dict(row) for row in cur.fetchall()]

            # Knowledge stats
            cur.execute(
                """
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE embedding IS NOT NULL) as embedded
                FROM knowledge_base
                WHERE knowledge_type != 'archie_v1'
            """
            )
            kb_row = cur.fetchone()
            knowledge_count = kb_row["total"] if kb_row else 0
            embedded_count = kb_row["embedded"] if kb_row else 0
            embedding_coverage = round((embedded_count / knowledge_count) * 100, 1) if knowledge_count > 0 else 0

            return jsonify(
                {
                    "success": True,
                    "project_stats": project_stats,
                    "task_stats": task_stats,
                    "activity": activity,
                    "active_projects": active_projects,
                    "knowledge_count": knowledge_count,
                    "embedding_coverage": embedding_coverage,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/projects")
@login_required
@admin_hub_only
def api_list_projects():
    status = request.args.get("status")
    priority = request.args.get("priority")
    search = request.args.get("search")
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            query = (
                "SELECT p.*, COUNT(t.id) as total_tasks,"
                " COUNT(t.id) FILTER (WHERE t.status = 'completed') as completed_tasks"
                " FROM unified_projects p"
                " LEFT JOIN unified_tasks t ON t.project_id = p.id WHERE 1=1"
            )
            params = []
            if status:
                query += " AND p.status = %s"
                params.append(status)
            if priority:
                query += " AND p.priority = %s"
                params.append(priority)
            if search:
                query += " AND (p.name ILIKE %s OR p.description ILIKE %s)"
                params.extend(["%" + search + "%", "%" + search + "%"])
            query += " GROUP BY p.id ORDER BY p.updated_at DESC"
            cur.execute(query, params)
            return jsonify({"success": True, "projects": [dict(r) for r in cur.fetchall()]})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/projects", methods=["POST"])
@login_required
@admin_hub_only
def api_create_project():
    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"success": False, "error": "Name required"}), 400
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            slug = re.sub(r"[^a-z0-9]+", "-", data["name"].lower()).strip("-")
            cur.execute(
                """INSERT INTO unified_projects
                (name, slug, description, project_type, status, priority,
                 target_date, created_by_user_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                (
                    data["name"],
                    slug,
                    data.get("description", ""),
                    data.get("project_type", "feature"),
                    data.get("status", "active"),
                    data.get("priority", "medium"),
                    data.get("target_date"),
                    current_user.id,
                ),
            )
            project = dict(cur.fetchone())
            conn.commit()
            return jsonify({"success": True, "project": project}), 201
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/projects/<int:project_id>", methods=["PUT"])
@login_required
@admin_hub_only
def api_update_project(project_id):
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data"}), 400
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            fields, params = [], []
            for key in [
                "name",
                "description",
                "project_type",
                "status",
                "priority",
                "target_date",
            ]:
                if key in data:
                    fields.append(f"{key} = %s")
                    params.append(data[key])
            if not fields:
                return jsonify({"success": False, "error": "No fields"}), 400
            fields.append("updated_at = NOW()")
            params.append(project_id)
            cur.execute(
                f"UPDATE unified_projects SET {', '.join(fields)}" " WHERE id = %s RETURNING *",
                params,
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Not found"}), 404
            conn.commit()
            return jsonify({"success": True, "project": dict(row)})
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/projects/<int:project_id>", methods=["DELETE"])
@login_required
@admin_hub_only
def api_delete_project(project_id):
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "DELETE FROM unified_tasks WHERE project_id = %s",
                (project_id,),
            )
            cur.execute(
                "DELETE FROM unified_projects WHERE id = %s RETURNING id",
                (project_id,),
            )
            if not cur.fetchone():
                return jsonify({"success": False, "error": "Not found"}), 404
            conn.commit()
            return jsonify({"success": True})
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/projects/<int:project_id>/tasks")
@login_required
@admin_hub_only
def api_list_tasks(project_id):
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT * FROM unified_tasks WHERE project_id = %s
                ORDER BY priority ASC, created_at ASC""",
                (project_id,),
            )
            return jsonify({"success": True, "tasks": [dict(r) for r in cur.fetchall()]})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/projects/<int:project_id>/tasks", methods=["POST"])
@login_required
@admin_hub_only
def api_create_task(project_id):
    data = request.get_json()
    if not data or not data.get("title"):
        return jsonify({"success": False, "error": "Title required"}), 400
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """INSERT INTO unified_tasks
                (project_id, title, description, task_type, status,
                 priority, due_date, assigned_to_user)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                (
                    project_id,
                    data["title"],
                    data.get("description", ""),
                    data.get("task_type", "implementation"),
                    data.get("status", "pending"),
                    data.get("priority", "medium"),
                    data.get("due_date"),
                    data.get("assigned_to_user"),
                ),
            )
            task = dict(cur.fetchone())
            conn.commit()
            return jsonify({"success": True, "task": task}), 201
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/tasks/<int:task_id>", methods=["PUT"])
@login_required
@admin_hub_only
def api_update_task(task_id):
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data"}), 400
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            fields, params = [], []
            for key in [
                "title",
                "description",
                "task_type",
                "status",
                "priority",
                "due_date",
                "assigned_to_user",
            ]:
                if key in data:
                    fields.append(f"{key} = %s")
                    params.append(data[key])
            if not fields:
                return jsonify({"success": False, "error": "No fields"}), 400
            if data.get("status") == "completed":
                fields.append("completed_at = NOW()")
            fields.append("updated_at = NOW()")
            params.append(task_id)
            cur.execute(
                f"UPDATE unified_tasks SET {', '.join(fields)}" " WHERE id = %s RETURNING *",
                params,
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Not found"}), 404
            conn.commit()
            return jsonify({"success": True, "task": dict(row)})
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/tasks/<int:task_id>", methods=["DELETE"])
@login_required
@admin_hub_only
def api_delete_task(task_id):
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "DELETE FROM unified_tasks WHERE id = %s RETURNING id",
                (task_id,),
            )
            if not cur.fetchone():
                return jsonify({"success": False, "error": "Not found"}), 404
            conn.commit()
            return jsonify({"success": True})
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Task 5: Knowledge + Activity
# ---------------------------------------------------------------------------


@dev_hq_bp.route("/api/knowledge")
@login_required
@admin_hub_only
def api_knowledge():
    search = request.args.get("search", "")
    category = request.args.get("category", "")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            where_clauses = []
            params = []
            knowledge_type = request.args.get("knowledge_type", "")
            if search:
                where_clauses.append("(content ILIKE %s OR file_name ILIKE %s OR tags::text ILIKE %s)")
                params.extend(["%" + search + "%"] * 3)
            if knowledge_type:
                where_clauses.append("knowledge_type = %s")
                params.append(knowledge_type)
            if category:
                where_clauses.append("primary_category = %s")
                params.append(category)
            where_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""

            cur.execute(
                f"SELECT COUNT(*) as count FROM knowledge_base WHERE 1=1{where_sql}",
                params,
            )
            total = cur.fetchone()["count"]

            cur.execute(
                f"""SELECT id, file_name, file_path, primary_category,
                sub_category, tags, knowledge_type, importance_score,
                is_documentation, created_at, updated_at,
                LEFT(content, 300) as snippet
                FROM knowledge_base WHERE 1=1{where_sql}
                ORDER BY importance_score DESC, updated_at DESC
                LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            entries = [dict(r) for r in cur.fetchall()]

            cur.execute(
                "SELECT DISTINCT primary_category FROM knowledge_base" " WHERE primary_category IS NOT NULL ORDER BY 1"
            )
            categories = [r["primary_category"] for r in cur.fetchall()]

            return jsonify(
                {
                    "success": True,
                    "entries": entries,
                    "total": total,
                    "categories": categories,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/knowledge/<int:entry_id>")
@login_required
@admin_hub_only
def api_knowledge_detail(entry_id):
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT * FROM knowledge_base WHERE id = %s", (entry_id,))
            entry = cur.fetchone()
            if not entry:
                return jsonify({"success": False, "error": "Not found"}), 404
            return jsonify({"success": True, "entry": dict(entry)})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Decisions — Enhanced with filters + CRUD
# ---------------------------------------------------------------------------


@dev_hq_bp.route("/api/decisions")
@login_required
@admin_hub_only
def api_decisions():
    """List decisions with optional filters."""
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    search = request.args.get("search")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            query = (
                "SELECT d.*, p.name as project_name"
                " FROM project_decisions d"
                " LEFT JOIN unified_projects p ON d.project_id = p.id"
                " WHERE 1=1"
            )
            count_query = "SELECT COUNT(*) as count" " FROM project_decisions d" " WHERE 1=1"
            params = []
            count_params = []
            if project_id:
                query += " AND d.project_id = %s"
                count_query += " AND d.project_id = %s"
                params.append(int(project_id))
                count_params.append(int(project_id))
            if status:
                query += " AND d.status = %s"
                count_query += " AND d.status = %s"
                params.append(status)
                count_params.append(status)
            if search:
                query += " AND (d.title ILIKE %s OR d.decision ILIKE %s)"
                count_query += " AND (d.title ILIKE %s OR d.decision ILIKE %s)"
                params.extend(["%" + search + "%", "%" + search + "%"])
                count_params.extend(["%" + search + "%", "%" + search + "%"])
            cur.execute(count_query, count_params)
            total = cur.fetchone()["count"]
            query += " ORDER BY d.created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            cur.execute(query, params)
            return jsonify(
                {
                    "success": True,
                    "decisions": [dict(r) for r in cur.fetchall()],
                    "total": total,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/decisions/<int:decision_id>")
@login_required
@admin_hub_only
def api_decision_detail(decision_id):
    """Get a single decision by ID."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT d.*, p.name as project_name
                FROM project_decisions d
                LEFT JOIN unified_projects p ON d.project_id = p.id
                WHERE d.id = %s""",
                (decision_id,),
            )
            decision = cur.fetchone()
            if not decision:
                return jsonify({"success": False, "error": "Not found"}), 404
            return jsonify({"success": True, "decision": dict(decision)})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/decisions", methods=["POST"])
@login_required
@admin_hub_only
def api_create_decision():
    """Create a new decision."""
    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"success": False, "error": "title is required"}), 400
    project_id = data.get("project_id")
    context = data.get("context")
    decision = data.get("decision")
    alternatives = data.get("alternatives")
    consequences = data.get("consequences")
    status = data.get("status", "accepted")
    tags = data.get("tags")
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            # Auto-increment decision_number per project
            if project_id:
                cur.execute(
                    "SELECT COALESCE(MAX(decision_number), 0) + 1 AS next_num"
                    " FROM project_decisions WHERE project_id = %s",
                    (int(project_id),),
                )
                decision_number = cur.fetchone()["next_num"]
            else:
                cur.execute(
                    "SELECT COALESCE(MAX(decision_number), 0) + 1 AS next_num"
                    " FROM project_decisions WHERE project_id IS NULL"
                )
                decision_number = cur.fetchone()["next_num"]
            cur.execute(
                """INSERT INTO project_decisions
                (project_id, decision_number, title, status, context,
                 decision, alternatives, consequences, tags,
                 decided_by_user_id, decided_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING *""",
                (
                    int(project_id) if project_id else None,
                    decision_number,
                    title,
                    status,
                    context,
                    decision,
                    alternatives,
                    consequences,
                    tags,
                    current_user.id,
                ),
            )
            new_decision = dict(cur.fetchone())
            conn.commit()
            return jsonify({"success": True, "decision": new_decision}), 201
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/activity")
@login_required
@admin_hub_only
def api_activity():
    limit = min(int(request.args.get("limit", 30)), 100)
    project_id = request.args.get("project_id")
    activity_type = request.args.get("activity_type")
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            query = (
                "SELECT pa.*, up.name as project_name"
                " FROM project_activity pa"
                " LEFT JOIN unified_projects up ON pa.project_id = up.id"
                " WHERE 1=1"
            )
            params = []
            if project_id:
                query += " AND pa.project_id = %s"
                params.append(int(project_id))
            if activity_type:
                query += " AND pa.activity_type = %s"
                params.append(activity_type)
            query += " ORDER BY pa.created_at DESC LIMIT %s"
            params.append(limit)
            cur.execute(query, params)
            return jsonify({"success": True, "activity": [dict(r) for r in cur.fetchall()]})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Task 6: DB Schema + API Docs
# ---------------------------------------------------------------------------


@dev_hq_bp.route("/api/schema")
@login_required
@admin_hub_only
def api_schema():
    if not INTELLIGENCE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Blueprint Intelligence not available"}),
            500,
        )
    try:
        return jsonify(get_database_schema())
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@dev_hq_bp.route("/api/docs")
@login_required
@admin_hub_only
def api_docs():
    if not INTELLIGENCE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Blueprint Intelligence not available"}),
            500,
        )
    try:
        return jsonify(get_api_endpoints())
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Task 7: Integrations (MCP + Claude)
# ---------------------------------------------------------------------------


@dev_hq_bp.route("/api/integrations/mcp")
@login_required
@admin_hub_only
def api_mcp_status():
    result = {"success": True}
    mcp_path = os.path.join(os.getenv("ARCHIE_BRAIN_PATH", "/mnt/archie_brain"), ".mcp.json")
    try:
        with open(mcp_path, "r") as f:
            mcp_config = json_module.load(f)
        for server in mcp_config.get("mcpServers", {}).values():
            for key in list(server.get("env", {})):
                if any(s in key.lower() for s in ["password", "secret", "key"]):
                    val = server["env"][key]
                    server["env"][key] = val[:4] + "****" if len(val) > 4 else "****"
        result["mcp_config"] = mcp_config
    except Exception as e:
        result["mcp_config"] = {"error": str(e)}

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                "SELECT id, name, category, description, is_enabled as enabled,"
                " tags, created_at FROM mcp_tool_definitions ORDER BY category, name"
            )
            result["mcp_tools_db"] = [dict(r) for r in cur.fetchall()]
        except Exception:
            result["mcp_tools_db"] = []
        try:
            cur.execute(
                """SELECT tool_name, COUNT(*) as usage_count,
                MAX(created_at) as last_used
                FROM mcp_tool_usage
                GROUP BY tool_name ORDER BY usage_count DESC"""
            )
            result["tool_usage"] = [dict(r) for r in cur.fetchall()]
        except Exception:
            result["tool_usage"] = []
        cur.close()
    return jsonify(result)


@dev_hq_bp.route("/api/integrations/claude")
@login_required
@admin_hub_only
def api_claude_config():
    brain_path = os.getenv("ARCHIE_BRAIN_PATH", "/mnt/archie_brain")
    result = {"success": True}

    # Platform CLAUDE.md is at /app/.claude/CLAUDE.md inside container
    app_root = os.getenv("APP_ROOT", "/app")
    for label, md_path in [
        ("claude_md_root", os.path.join(brain_path, "CLAUDE.md")),
        (
            "claude_md_platform",
            os.path.join(app_root, ".claude", "CLAUDE.md"),
        ),
    ]:
        try:
            with open(md_path, "r") as f:
                result[label] = f.read()
        except Exception:
            result[label] = None

    settings_path = os.path.join(app_root, ".claude", "settings.json")
    try:
        with open(settings_path, "r") as f:
            result["claude_settings"] = json_module.load(f)
    except Exception:
        result["claude_settings"] = None

    commands_dir = os.path.join(app_root, ".claude", "commands")
    try:
        commands = []
        if os.path.isdir(commands_dir):
            for fn in sorted(os.listdir(commands_dir)):
                if fn.endswith(".md"):
                    with open(os.path.join(commands_dir, fn), "r") as f:
                        first_line = f.readline().strip().lstrip("#").strip()
                    commands.append({"name": fn.replace(".md", ""), "description": first_line})
        result["custom_commands"] = commands
    except Exception:
        result["custom_commands"] = []

    hooks_dir = os.path.join(app_root, "scripts", "hooks")
    try:
        result["hooks"] = sorted(os.listdir(hooks_dir)) if os.path.isdir(hooks_dir) else []
    except Exception:
        result["hooks"] = []

    return jsonify(result)


# ---------------------------------------------------------------------------
# Task 8: Module Docs (User Guides + Coder Docs)
# ---------------------------------------------------------------------------


@dev_hq_bp.route("/api/docs/modules")
@login_required
@admin_hub_only
def api_docs_modules():
    """Return list of modules that have documentation, with doc counts."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                SELECT memory_metadata->>'module' as module,
                       memory_metadata->>'doc_type' as doc_type,
                       COUNT(*) as count
                FROM knowledge_base
                WHERE knowledge_type = 'vault_note'
                  AND memory_metadata->>'doc_type' IS NOT NULL
                  AND memory_metadata->>'module' IS NOT NULL
                GROUP BY 1, 2
                ORDER BY 1, 2
            """
            )
            rows = cur.fetchall()
            modules = {}
            for row in rows:
                mod = row["module"]
                if mod not in modules:
                    modules[mod] = {"coder": 0, "user": 0}
                modules[mod][row["doc_type"]] = row["count"]
            return jsonify({"success": True, "modules": modules})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/docs/list")
@login_required
@admin_hub_only
def api_docs_list():
    """List module documentation entries from knowledge_base.

    Uses memory_metadata->>'doc_type' to distinguish user vs coder docs
    (tags column is overwritten by the auto_categorize trigger).
    """
    search = request.args.get("search", "")
    doc_type = request.args.get("doc_type", "")  # 'user' or 'coder'
    module = request.args.get("module", "")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            where_clauses = [
                "knowledge_type = 'vault_note'",
                "memory_metadata->>'doc_type' IS NOT NULL",
            ]
            params = []
            if search:
                where_clauses.append("(content ILIKE %s OR file_name ILIKE %s OR title ILIKE %s)")
                params.extend(["%" + search + "%"] * 3)
            if doc_type == "user":
                where_clauses.append("memory_metadata->>'doc_type' = 'user'")
            elif doc_type == "coder":
                where_clauses.append("memory_metadata->>'doc_type' = 'coder'")
            if module:
                where_clauses.append("memory_metadata->>'module' = %s")
                params.append(module)
            where_sql = " AND ".join(where_clauses)

            cur.execute(
                f"SELECT COUNT(*) as count FROM knowledge_base WHERE {where_sql}",
                params,
            )
            total = cur.fetchone()["count"]

            cur.execute(
                f"""SELECT id, file_name, title, primary_category, sub_category,
                tags, knowledge_type, importance_score, memory_metadata,
                created_at, updated_at,
                LEFT(content, 200) as snippet
                FROM knowledge_base WHERE {where_sql}
                ORDER BY importance_score DESC, updated_at DESC
                LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            entries = [dict(r) for r in cur.fetchall()]

            return jsonify({"success": True, "entries": entries, "total": total})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/docs/<int:doc_id>")
@login_required
@admin_hub_only
def api_docs_detail(doc_id):
    """Get full content of a documentation entry."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT * FROM knowledge_base WHERE id = %s", (doc_id,))
            entry = cur.fetchone()
            if not entry:
                return jsonify({"success": False, "error": "Not found"}), 404
            return jsonify({"success": True, "entry": dict(entry)})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/docs", methods=["POST"])
@login_required
@admin_hub_only
def api_docs_create():
    """Create a new documentation entry."""
    data = request.get_json()
    if not data or not data.get("content"):
        return jsonify({"success": False, "error": "Content is required"}), 400
    title = data.get("title", "Untitled Document")
    content = data["content"]
    doc_type = data.get("doc_type", "coder")  # 'user' or 'coder'
    category = data.get("category", "")
    module = data.get("module", "")
    importance = 0.95 if doc_type == "coder" else 0.90
    meta_dict = {"doc_type": doc_type}
    if module:
        meta_dict["module"] = module
    metadata = json_module.dumps(meta_dict)

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """INSERT INTO knowledge_base
                (content, file_name, knowledge_type, importance_score,
                 is_documentation, primary_category, title,
                 memory_metadata, created_at, updated_at)
                VALUES (%s, %s, 'vault_note', %s, true, %s, %s, %s::jsonb, NOW(), NOW())
                RETURNING id""",
                (content, title, importance, category, title, metadata),
            )
            new_id = cur.fetchone()["id"]
            conn.commit()
            return jsonify({"success": True, "id": new_id})
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/docs/<int:doc_id>", methods=["PUT"])
@login_required
@admin_hub_only
def api_docs_update(doc_id):
    """Update a documentation entry."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            sets = []
            params = []
            if "content" in data:
                sets.append("content = %s")
                params.append(data["content"])
            if "title" in data:
                sets.append("title = %s")
                params.append(data["title"])
                sets.append("file_name = %s")
                params.append(data["title"])
            if "category" in data:
                sets.append("primary_category = %s")
                params.append(data["category"])
            if "doc_type" in data or "module" in data:
                # Merge doc_type/module into existing memory_metadata
                meta_update = {}
                if "doc_type" in data:
                    meta_update["doc_type"] = data["doc_type"]
                if "module" in data:
                    meta_update["module"] = data["module"]
                sets.append("memory_metadata = COALESCE(memory_metadata, '{}'::jsonb) || %s::jsonb")
                params.append(json_module.dumps(meta_update))
            if not sets:
                return jsonify({"success": False, "error": "No valid fields"}), 400
            sets.append("updated_at = NOW()")
            params.append(doc_id)
            cur.execute(
                f"UPDATE knowledge_base SET {', '.join(sets)} WHERE id = %s",
                params,
            )
            conn.commit()
            if cur.rowcount == 0:
                return jsonify({"success": False, "error": "Not found"}), 404
            return jsonify({"success": True})
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/docs/<int:doc_id>", methods=["DELETE"])
@login_required
@admin_hub_only
def api_docs_delete(doc_id):
    """Delete a documentation entry."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("DELETE FROM knowledge_base WHERE id = %s", (doc_id,))
            conn.commit()
            if cur.rowcount == 0:
                return jsonify({"success": False, "error": "Not found"}), 404
            return jsonify({"success": True})
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Cross-Project Tasks + Integrations Health
# ---------------------------------------------------------------------------


@dev_hq_bp.route("/api/tasks")
@login_required
@admin_hub_only
def api_all_tasks():
    """Cross-project task listing with filters."""
    status = request.args.get("status")
    priority = request.args.get("priority")
    project_id = request.args.get("project_id")
    search = request.args.get("search")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            query = (
                "SELECT t.*, p.name as project_name"
                " FROM unified_tasks t"
                " LEFT JOIN unified_projects p ON t.project_id = p.id"
                " WHERE 1=1"
            )
            params = []
            if status:
                query += " AND t.status = %s"
                params.append(status)
            if priority:
                query += " AND t.priority = %s"
                params.append(priority)
            if project_id:
                query += " AND t.project_id = %s"
                params.append(int(project_id))
            if search:
                query += " AND (t.title ILIKE %s OR t.description ILIKE %s)"
                params.extend(["%" + search + "%", "%" + search + "%"])
            query += " ORDER BY t.priority ASC, t.created_at DESC"

            # Count total before pagination
            count_query = "SELECT COUNT(*) as count FROM unified_tasks t WHERE 1=1"
            count_params = []
            if status:
                count_query += " AND t.status = %s"
                count_params.append(status)
            if priority:
                count_query += " AND t.priority = %s"
                count_params.append(priority)
            if project_id:
                count_query += " AND t.project_id = %s"
                count_params.append(int(project_id))
            if search:
                count_query += " AND (t.title ILIKE %s OR t.description ILIKE %s)"
                count_params.extend(["%" + search + "%", "%" + search + "%"])
            cur.execute(count_query, count_params)
            total = cur.fetchone()["count"]

            query += " LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            cur.execute(query, params)
            tasks = [dict(r) for r in cur.fetchall()]

            # Get project list for filter dropdown
            cur.execute("SELECT id, name FROM unified_projects" " WHERE status = 'active' ORDER BY name")
            projects = [dict(r) for r in cur.fetchall()]

            return jsonify(
                {
                    "success": True,
                    "tasks": tasks,
                    "total": total,
                    "projects": projects,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/integrations/health")
@login_required
@admin_hub_only
def api_integrations_health():
    """Consolidated health check for all integrations."""
    services = {}

    # MCP: parse .mcp.json
    mcp_path = os.path.join(os.getenv("ARCHIE_BRAIN_PATH", "/mnt/archie_brain"), ".mcp.json")
    try:
        with open(mcp_path, "r") as f:
            mcp_config = json_module.load(f)
        server_count = len(mcp_config.get("mcpServers", {}))
        services["mcp"] = {
            "name": "MCP Servers",
            "status": "online" if server_count > 0 else "warning",
            "detail": f"{server_count} servers configured",
            "icon": "cpu",
        }
    except Exception as e:
        services["mcp"] = {
            "name": "MCP Servers",
            "status": "offline",
            "detail": str(e),
            "icon": "cpu",
        }

    # Ollama: HTTP ping
    ollama_host = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
    try:
        req = urllib.request.Request(f"{ollama_host}/api/tags", method="GET")
        req.add_header("User-Agent", "archie-devhq/1.0")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json_module.loads(resp.read())
            model_count = len(data.get("models", []))
        services["ollama"] = {
            "name": "Ollama",
            "status": "online",
            "detail": f"{model_count} models loaded",
            "icon": "brain",
        }
    except Exception:
        services["ollama"] = {
            "name": "Ollama",
            "status": "offline",
            "detail": "Connection failed",
            "icon": "brain",
        }

    # GitHub: env var check
    gh_token = os.getenv("GITHUB_TOKEN", "")
    services["github"] = {
        "name": "GitHub",
        "status": "online" if gh_token else "warning",
        "detail": "Token configured" if gh_token else "No token set",
        "icon": "github",
    }

    # Telegram: env var check
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    services["telegram"] = {
        "name": "Telegram",
        "status": "online" if tg_token else "warning",
        "detail": "Bot configured" if tg_token else "No token set",
        "icon": "send",
    }

    # Home Assistant: env var check
    ha_key = os.getenv("HA_API_KEY", "")
    services["homeassistant"] = {
        "name": "Home Assistant",
        "status": "online" if ha_key else "warning",
        "detail": "API key configured" if ha_key else "No API key set",
        "icon": "home",
    }

    return jsonify({"success": True, "services": services})


# ---------------------------------------------------------------------------
# Ideas Board
# ---------------------------------------------------------------------------


@dev_hq_bp.route("/api/ideas")
@login_required
@admin_hub_only
def api_list_ideas():
    """List ideas with filters."""
    status = request.args.get("status")
    category = request.args.get("category")
    search = request.args.get("search")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            query = "SELECT * FROM project_ideas WHERE 1=1"
            count_query = "SELECT COUNT(*) as count FROM project_ideas WHERE 1=1"
            params = []
            count_params = []
            if status:
                query += " AND status = %s"
                count_query += " AND status = %s"
                params.append(status)
                count_params.append(status)
            if category:
                query += " AND category = %s"
                count_query += " AND category = %s"
                params.append(category)
                count_params.append(category)
            if search:
                query += " AND (title ILIKE %s OR description ILIKE %s)"
                count_query += " AND (title ILIKE %s OR description ILIKE %s)"
                params.extend(["%" + search + "%", "%" + search + "%"])
                count_params.extend(["%" + search + "%", "%" + search + "%"])
            cur.execute(count_query, count_params)
            total = cur.fetchone()["count"]
            query += " ORDER BY priority DESC, created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            cur.execute(query, params)
            return jsonify(
                {
                    "success": True,
                    "ideas": [dict(r) for r in cur.fetchall()],
                    "total": total,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/ideas", methods=["POST"])
@login_required
@admin_hub_only
def api_create_idea():
    """Create a new idea."""
    data = request.get_json()
    if not data or not data.get("title"):
        return jsonify({"success": False, "error": "Title required"}), 400
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """INSERT INTO project_ideas
                (title, description, category, priority, tags, created_by_user_id)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
                (
                    data["title"],
                    data.get("description", ""),
                    data.get("category", "feature"),
                    data.get("priority", 5),
                    data.get("tags", []),
                    current_user.id,
                ),
            )
            idea = dict(cur.fetchone())
            conn.commit()
            return jsonify({"success": True, "idea": idea}), 201
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/ideas/<int:idea_id>", methods=["PUT"])
@login_required
@admin_hub_only
def api_update_idea(idea_id):
    """Update an existing idea."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data"}), 400
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            fields, params = [], []
            for key in ["title", "description", "category", "priority", "status", "tags"]:
                if key in data:
                    fields.append(f"{key} = %s")
                    params.append(data[key])
            if not fields:
                return jsonify({"success": False, "error": "No fields"}), 400
            fields.append("updated_at = NOW()")
            params.append(idea_id)
            cur.execute(
                f"UPDATE project_ideas SET {', '.join(fields)} WHERE id = %s RETURNING *",
                params,
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Not found"}), 404
            conn.commit()
            return jsonify({"success": True, "idea": dict(row)})
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/ideas/<int:idea_id>", methods=["DELETE"])
@login_required
@admin_hub_only
def api_delete_idea(idea_id):
    """Delete an idea."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "DELETE FROM project_ideas WHERE id = %s RETURNING id",
                (idea_id,),
            )
            if not cur.fetchone():
                return jsonify({"success": False, "error": "Not found"}), 404
            conn.commit()
            return jsonify({"success": True})
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/ideas/<int:idea_id>/promote", methods=["POST"])
@login_required
@admin_hub_only
def api_promote_idea(idea_id):
    """Promote an idea to a project."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT * FROM project_ideas WHERE id = %s", (idea_id,))
            idea = cur.fetchone()
            if not idea:
                return jsonify({"success": False, "error": "Not found"}), 404
            if idea["status"] == "promoted":
                return jsonify({"success": False, "error": "Already promoted"}), 400

            slug = re.sub(r"[^a-z0-9]+", "-", idea["title"].lower()).strip("-")
            cur.execute(
                """INSERT INTO unified_projects
                (name, slug, description, project_type, priority, tags, status,
                 created_by_user_id)
                VALUES (%s, %s, %s, %s, %s, %s, 'active', %s) RETURNING *""",
                (
                    idea["title"],
                    slug,
                    idea["description"],
                    idea["category"],
                    idea["priority"],
                    idea["tags"],
                    current_user.id,
                ),
            )
            project = dict(cur.fetchone())

            cur.execute(
                """UPDATE project_ideas
                SET status = 'promoted', promoted_to_project_id = %s,
                    updated_at = NOW()
                WHERE id = %s""",
                (project["id"], idea_id),
            )
            conn.commit()
            return jsonify(
                {
                    "success": True,
                    "project": project,
                    "idea_id": idea_id,
                }
            )
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Project Documents — versioned CRUD (uses existing project_documents table)
# ---------------------------------------------------------------------------


@dev_hq_bp.route("/api/projects/<int:project_id>/docs")
@login_required
@admin_hub_only
def api_project_docs(project_id):
    """List current-version documents for a project."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT id, project_id, doc_type, title,
                       LEFT(content, 200) as snippet,
                       content_format, version, file_path,
                       metadata, tags, created_at, updated_at,
                       updated_by_user_id
                FROM project_documents
                WHERE project_id = %s AND is_current = true
                ORDER BY updated_at DESC""",
                (project_id,),
            )
            docs = [dict(r) for r in cur.fetchall()]
            return jsonify({"success": True, "docs": docs})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/projects/<int:project_id>/docs/<int:doc_id>")
@login_required
@admin_hub_only
def api_project_doc_detail(project_id, doc_id):
    """Get full document detail."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT * FROM project_documents
                WHERE id = %s AND project_id = %s""",
                (doc_id, project_id),
            )
            doc = cur.fetchone()
            if not doc:
                return jsonify({"success": False, "error": "Not found"}), 404
            return jsonify({"success": True, "doc": dict(doc)})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/projects/<int:project_id>/docs", methods=["POST"])
@login_required
@admin_hub_only
def api_create_project_doc(project_id):
    """Create a new project document."""
    data = request.get_json() or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"success": False, "error": "content is required"}), 400
    doc_type = data.get("doc_type", "note")
    title = data.get("title", "Untitled")
    tags = data.get("tags")
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """INSERT INTO project_documents
                (project_id, doc_type, title, content, content_format,
                 version, is_current, tags, updated_by_user_id)
                VALUES (%s, %s, %s, %s, 'markdown', 1, true, %s, %s)
                RETURNING *""",
                (project_id, doc_type, title, content, tags, current_user.id),
            )
            doc = dict(cur.fetchone())
            conn.commit()
            return jsonify({"success": True, "doc": doc}), 201
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/projects/<int:project_id>/docs/<int:doc_id>", methods=["PUT"])
@login_required
@admin_hub_only
def api_update_project_doc(project_id, doc_id):
    """Versioned update — marks old doc as not current, inserts new version."""
    data = request.get_json() or {}
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT * FROM project_documents
                WHERE id = %s AND project_id = %s""",
                (doc_id, project_id),
            )
            old_doc = cur.fetchone()
            if not old_doc:
                return jsonify({"success": False, "error": "Not found"}), 404

            # Mark old version as not current
            cur.execute(
                "UPDATE project_documents SET is_current = false WHERE id = %s",
                (doc_id,),
            )

            # Insert new version
            new_version = old_doc["version"] + 1
            cur.execute(
                """INSERT INTO project_documents
                (project_id, doc_type, title, content, content_format,
                 version, is_current, file_path, metadata, tags,
                 updated_by_user_id)
                VALUES (%s, %s, %s, %s, %s, %s, true, %s, %s, %s, %s)
                RETURNING *""",
                (
                    project_id,
                    data.get("doc_type", old_doc["doc_type"]),
                    data.get("title", old_doc["title"]),
                    data.get("content", old_doc["content"]),
                    data.get("content_format", old_doc["content_format"]),
                    new_version,
                    data.get("file_path", old_doc["file_path"]),
                    Json(data.get("metadata") if "metadata" in data else old_doc["metadata"]),
                    data.get("tags") if "tags" in data else old_doc["tags"],
                    current_user.id,
                ),
            )
            new_doc = dict(cur.fetchone())
            conn.commit()
            return jsonify({"success": True, "doc": new_doc})
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/projects/<int:project_id>/docs/<int:doc_id>", methods=["DELETE"])
@login_required
@admin_hub_only
def api_delete_project_doc(project_id, doc_id):
    """Delete a project document."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """DELETE FROM project_documents
                WHERE id = %s AND project_id = %s RETURNING id""",
                (doc_id, project_id),
            )
            deleted = cur.fetchone()
            if not deleted:
                return jsonify({"success": False, "error": "Not found"}), 404
            conn.commit()
            return jsonify({"success": True, "deleted_id": deleted["id"]})
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# System Tab: MCP Usage Analytics, Health History, Quick Actions
# ---------------------------------------------------------------------------


def _run_and_store_health_check():
    """Run health checks on all services and store results in history table."""
    import time as _time

    checks = []
    ollama_host = os.getenv("OLLAMA_HOST", "host.docker.internal:11434")
    if not ollama_host.startswith("http"):
        ollama_host = "http://" + ollama_host

    # Ollama
    try:
        start = _time.time()
        req = urllib.request.Request(f"{ollama_host}/api/tags", method="GET")
        req.add_header("User-Agent", "archie-devhq/1.0")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json_module.loads(resp.read())
            model_count = len(data.get("models", []))
        elapsed = int((_time.time() - start) * 1000)
        checks.append(("ollama", "online", f"{model_count} models", elapsed))
    except Exception:
        checks.append(("ollama", "offline", "unreachable", None))

    # PostgreSQL
    try:
        start = _time.time()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        elapsed = int((_time.time() - start) * 1000)
        checks.append(("postgresql", "online", "connected", elapsed))
    except Exception:
        checks.append(("postgresql", "offline", "unreachable", None))

    # MCP servers
    mcp_path = os.path.join(os.getenv("ARCHIE_BRAIN_PATH", "/mnt/archie_brain"), ".mcp.json")
    try:
        with open(mcp_path, "r") as f:
            mcp = json_module.load(f)
        count = len(mcp.get("mcpServers", {}))
        checks.append(("mcp", "online" if count > 0 else "warning", f"{count} servers", None))
    except Exception:
        checks.append(("mcp", "offline", "config missing", None))

    # GitHub token
    gh = os.getenv("GITHUB_TOKEN")
    checks.append(("github", "online" if gh else "warning", "token set" if gh else "no token", None))

    # Telegram
    tg = os.getenv("TELEGRAM_BOT_TOKEN")
    checks.append(("telegram", "online" if tg else "warning", "token set" if tg else "no token", None))

    # Home Assistant
    ha = os.getenv("HA_API_KEY")
    checks.append(("home_assistant", "online" if ha else "warning", "key set" if ha else "no key", None))

    # Store results
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for svc, status, detail, resp_ms in checks:
                    cur.execute(
                        """INSERT INTO service_health_history
                        (service_name, status, detail, response_time_ms)
                        VALUES (%s, %s, %s, %s)""",
                        (svc, status, detail, resp_ms),
                    )
                cur.execute("DELETE FROM service_health_history WHERE checked_at < NOW() - INTERVAL '7 days'")
                conn.commit()
    except Exception:
        pass

    return [{"service": s, "status": st, "detail": d, "response_time_ms": ms} for s, st, d, ms in checks]


def sync_mcp_tool_registry():
    """Sync .mcp.json server info to mcp_tool_definitions table."""
    mcp_path = os.path.join(os.getenv("ARCHIE_BRAIN_PATH", "/mnt/archie_brain"), ".mcp.json")
    try:
        with open(mcp_path, "r") as f:
            mcp_config = json_module.load(f)
    except Exception:
        return 0

    servers = mcp_config.get("mcpServers", {})
    synced = 0

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for server_name in servers:
                    cur.execute(
                        """INSERT INTO mcp_tool_definitions
                        (name, category, display_name, description, is_enabled)
                        VALUES (%s, %s, %s, %s, TRUE)
                        ON CONFLICT (name) DO UPDATE SET
                            display_name = EXCLUDED.display_name,
                            updated_at = NOW()""",
                        (
                            f"_server_{server_name}",
                            "admin",
                            f"MCP Server: {server_name}",
                            f"Auto-registered from .mcp.json",
                        ),
                    )
                    synced += 1
                conn.commit()
    except Exception:
        pass

    return synced


@dev_hq_bp.route("/api/integrations/mcp/usage")
@login_required
@admin_hub_only
def api_mcp_usage():
    """MCP tool usage analytics."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            try:
                cur.execute(
                    """SELECT tool_name, total_calls, successful_calls,
                    avg_response_ms, last_called
                    FROM v_mcp_tool_usage_summary
                    ORDER BY total_calls DESC"""
                )
                tool_stats = [dict(r) for r in cur.fetchall()]
            except Exception:
                tool_stats = []

            try:
                cur.execute(
                    """SELECT DATE(created_at) as day,
                    COUNT(*) as calls,
                    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes,
                    SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failures
                    FROM mcp_tool_usage
                    WHERE created_at > NOW() - INTERVAL '7 days'
                    GROUP BY DATE(created_at) ORDER BY day"""
                )
                daily_volume = [dict(r) for r in cur.fetchall()]
            except Exception:
                daily_volume = []

            try:
                cur.execute(
                    """SELECT tool_name, error_code, error_message, COUNT(*) as count
                    FROM mcp_tool_usage
                    WHERE success = FALSE AND created_at > NOW() - INTERVAL '7 days'
                    GROUP BY tool_name, error_code, error_message
                    ORDER BY count DESC LIMIT 20"""
                )
                errors = [dict(r) for r in cur.fetchall()]
            except Exception:
                errors = []

            cur.close()
        return jsonify({"tool_stats": tool_stats, "daily_volume": daily_volume, "errors": errors})
    except Exception as e:
        return jsonify({"tool_stats": [], "daily_volume": [], "errors": [], "error": str(e)})


@dev_hq_bp.route("/api/integrations/health/history")
@login_required
@admin_hub_only
def api_health_history():
    """Last 24h of health checks for sparkline display."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """SELECT service_name, status, detail, response_time_ms, checked_at
                FROM service_health_history
                WHERE checked_at > NOW() - INTERVAL '24 hours'
                ORDER BY service_name, checked_at"""
            )
            rows = cur.fetchall()
            cur.close()

        history = {}
        for row in rows:
            svc = row["service_name"]
            if svc not in history:
                history[svc] = []
            history[svc].append(
                {
                    "status": row["status"],
                    "detail": row["detail"],
                    "response_time_ms": row["response_time_ms"],
                    "checked_at": row["checked_at"].isoformat() if row["checked_at"] else None,
                }
            )

        return jsonify({"history": history})
    except Exception as e:
        return jsonify({"history": {}, "error": str(e)})


@dev_hq_bp.route("/api/integrations/health/check", methods=["POST"])
@login_required
@admin_hub_only
def api_run_health_check():
    """Run health check now and store results."""
    results = _run_and_store_health_check()
    return jsonify({"success": True, "results": results, "message": "Health check complete"})


@dev_hq_bp.route("/api/system/actions/clear-cache", methods=["POST"])
@login_required
@admin_hub_only
def api_clear_bridge_cache():
    """Clear old bridge conversations."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """DELETE FROM bridge_interaction_log
                    WHERE created_at < NOW() - INTERVAL '1 day'
                    RETURNING id"""
                )
                deleted = cur.rowcount
                conn.commit()
        return jsonify({"success": True, "message": f"Cleared {deleted} old bridge log entries"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@dev_hq_bp.route("/api/system/actions/warmup", methods=["POST"])
@login_required
@admin_hub_only
def api_restart_warmup():
    """Trigger Ollama model warmup."""
    ollama_host = os.getenv("OLLAMA_HOST", "host.docker.internal:11434")
    if not ollama_host.startswith("http"):
        ollama_host = "http://" + ollama_host
    models = ["dolphin3-8k:latest", "arctic-embed-cpu:latest", "qwen25-classify:latest"]
    results = []
    for model in models:
        try:
            payload = json_module.dumps({"model": model, "prompt": "warmup", "stream": False}).encode()
            req = urllib.request.Request(
                f"{ollama_host}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "archie-devhq/1.0"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                results.append({"model": model, "status": "ok" if resp.status == 200 else "error"})
        except Exception as e:
            results.append({"model": model, "status": "error", "error": str(e)})
    return jsonify(
        {
            "success": True,
            "results": results,
            "message": f"Warmed up {len([r for r in results if r['status'] == 'ok'])}/{len(models)} models",
        }
    )


@dev_hq_bp.route("/api/system/actions/reindex-embeddings", methods=["POST"])
@login_required
@admin_hub_only
def api_reindex_embeddings():
    """Report missing embeddings count."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT COUNT(*) FROM knowledge_base
                    WHERE embedding IS NULL AND knowledge_type != 'archie_v1'"""
                )
                missing = cur.fetchone()[0]
        return jsonify(
            {
                "success": True,
                "missing_embeddings": missing,
                "message": f"{missing} entries need embeddings",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@dev_hq_bp.route("/api/system/actions/sync-mcp-tools", methods=["POST"])
@login_required
@admin_hub_only
def api_sync_mcp_tools():
    """Manually trigger MCP tool registry sync."""
    count = sync_mcp_tool_registry()
    return jsonify({"success": True, "synced": count, "message": f"Synced {count} entries"})


@dev_hq_bp.route("/api/integrations/mcp/tools/<int:tool_id>/hints", methods=["PUT"])
@login_required
@admin_hub_only
def api_update_tool_hints(tool_id):
    """Update routing hints metadata for a tool definition."""
    data = request.get_json() or {}
    hints = data.get("routing_hints", {})

    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """UPDATE mcp_tool_definitions
                SET tags = COALESCE(tags, '{}')::jsonb || %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id, name, tags""",
                (Json({"routing_hints": hints}), tool_id),
            )
            updated = cur.fetchone()
            conn.commit()
            cur.close()

        if not updated:
            return jsonify({"error": "Tool not found"}), 404
        return jsonify({"success": True, "tool": dict(updated)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
