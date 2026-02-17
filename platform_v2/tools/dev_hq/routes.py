"""Dev HQ Routes - Admin Only, Hub Only"""

import os
import json as json_module
from flask import render_template, jsonify, request, abort
from flask_login import login_required, current_user
from psycopg2.extras import RealDictCursor
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

            return jsonify(
                {
                    "success": True,
                    "project_stats": project_stats,
                    "task_stats": task_stats,
                    "activity": activity,
                    "active_projects": active_projects,
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
            cur.execute(
                """INSERT INTO unified_projects
                (name, description, project_type, status, priority,
                 target_date, created_by_user)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                (
                    data["name"],
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
                ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END,
                created_at ASC""",
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
            if search:
                where_clauses.append("(content ILIKE %s OR file_name ILIKE %s OR tags::text ILIKE %s)")
                params.extend(["%" + search + "%"] * 3)
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


@dev_hq_bp.route("/api/decisions")
@login_required
@admin_hub_only
def api_decisions():
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT d.*, p.name as project_name FROM project_decisions d
                LEFT JOIN unified_projects p ON d.project_id = p.id
                ORDER BY d.created_at DESC"""
            )
            return jsonify({"success": True, "decisions": [dict(r) for r in cur.fetchall()]})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            cur.close()


@dev_hq_bp.route("/api/activity")
@login_required
@admin_hub_only
def api_activity():
    limit = min(int(request.args.get("limit", 30)), 100)
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT pa.*, up.name as project_name
                FROM project_activity pa
                LEFT JOIN unified_projects up ON pa.project_id = up.id
                ORDER BY pa.created_at DESC LIMIT %s""",
                (limit,),
            )
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
                "SELECT name, category, description, enabled, created_at"
                " FROM mcp_tool_definitions ORDER BY category, name"
            )
            result["mcp_tools_db"] = [dict(r) for r in cur.fetchall()]
        except Exception:
            result["mcp_tools_db"] = []
        try:
            cur.execute(
                """SELECT tool_name, COUNT(*) as usage_count,
                MAX(executed_at) as last_used
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
