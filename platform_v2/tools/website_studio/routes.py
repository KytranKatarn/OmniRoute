"""
Website Studio Routes
=====================
AI-assisted website building with deployment capabilities.

Dual-purpose module:
- Admin: Manages ARCHIE company website (archie-platform.com)
- Users: Build their own websites with their own credentials

Author: A.R.C.H.I.E. Platform
Date: 2026-01-12
"""

from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from functools import wraps
import psycopg2


# Admin required decorator
def admin_required(f):
    """Decorator to require admin role for a route"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"success": False, "error": "Authentication required"}), 401
        if not getattr(current_user, "is_admin", False):
            return jsonify({"success": False, "error": "Admin access required"}), 403
        return f(*args, **kwargs)

    return decorated_function


from psycopg2.extras import RealDictCursor
from datetime import datetime
import os
import json
import logging

logger = logging.getLogger("archie_platform")

# Import user context helpers
try:
    from user_context import (
        get_user_filter,
        can_access_resource,
        require_ownership,
        add_user_id_to_data,
        is_admin_user,
        log_user_activity,
    )
except ImportError:
    # Fallbacks if user_context not available
    def get_user_filter(*args, **kwargs):
        return f"user_id = {current_user.id}" if current_user.is_authenticated else "1=0"

    def can_access_resource(user_id):
        return current_user.is_authenticated and (
            current_user.id == user_id or getattr(current_user, "is_admin", False)
        )

    def is_admin_user():
        return getattr(current_user, "is_admin", False)


# Import AI assistant
try:
    from .ai_assistant import (
        suggest_website_design,
        generate_page_content,
        improve_seo,
        generate_css_styles,
    )

    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

# Import chat handler for chat-based editing
try:
    from .chat_handler import (
        get_chat_system_prompt,
        parse_file_changes,
        apply_file_changes,
        auto_commit_changes,
        generate_diff_preview,
        ensure_repo_cloned,
        build_site_context,
        WEBSITE_REPO_PATH,
        detect_task_role,
        save_chat_history,
        load_chat_history,
    )

    CHAT_HANDLER_AVAILABLE = True
except ImportError as e:
    CHAT_HANDLER_AVAILABLE = False
    import logging

    logging.getLogger("archie_platform").warning(f"Chat handler not available: {e}")

# Create blueprint
website_studio_bp = Blueprint(
    "website_studio",
    __name__,
    url_prefix="/tools/website-studio",
    template_folder="../../templates/tools",
)


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# ============================================================================
# MAIN PAGE
# ============================================================================


@website_studio_bp.route("/")
@login_required
def index():
    """Main Website Studio interface"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get user's projects with isolation
        if is_admin_user():
            cur.execute(
                """
                SELECT p.*, u.username as owner_name,
                       COUNT(DISTINCT pg.id) as page_count
                FROM website_builder_projects p
                LEFT JOIN users u ON p.user_id = u.id
                LEFT JOIN website_builder_pages pg ON p.id = pg.project_id
                GROUP BY p.id, u.username
                ORDER BY p.updated_at DESC
            """
            )
        else:
            cur.execute(
                """
                SELECT p.*, COUNT(DISTINCT pg.id) as page_count
                FROM website_builder_projects p
                LEFT JOIN website_builder_pages pg ON p.id = pg.project_id
                WHERE p.user_id = %s
                GROUP BY p.id
                ORDER BY p.updated_at DESC
            """,
                (current_user.id,),
            )

        projects = cur.fetchall()

        # Get user's integrations
        cur.execute(
            """
            SELECT * FROM user_integrations
            WHERE user_id = %s AND service IN ('github', 'vercel', 'netlify', 'cloudflare')
        """,
            (current_user.id,),
        )
        integrations = {row["service"]: row for row in cur.fetchall()}

        # Get deployment stats
        cur.execute(
            """
            SELECT deployment_type, COUNT(*) as count
            FROM website_deployments
            WHERE deployed_by = %s
            GROUP BY deployment_type
        """,
            (current_user.id,),
        )
        deployment_stats = {row["deployment_type"]: row["count"] for row in cur.fetchall()}

        return render_template(
            "website_studio.html",
            projects=projects,
            integrations=integrations,
            deployment_stats=deployment_stats,
            is_admin=is_admin_user(),
            ai_available=AI_AVAILABLE,
        )
    except Exception as e:
        current_app.logger.error(f"[WebsiteStudio] Error loading: {e}")
        return render_template(
            "website_studio.html",
            projects=[],
            integrations={},
            deployment_stats={},
            error=str(e),
            ai_available=AI_AVAILABLE,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


# ============================================================================
# PROJECT CRUD
# ============================================================================


@website_studio_bp.route("/api/projects", methods=["GET"])
@login_required
def get_projects():
    """Get all projects for current user (or all for admin)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if is_admin_user() and request.args.get("all") == "true":
            cur.execute(
                """
                SELECT p.*, u.username as owner_name
                FROM website_builder_projects p
                LEFT JOIN users u ON p.user_id = u.id
                ORDER BY p.updated_at DESC
            """
            )
        else:
            cur.execute(
                """
                SELECT * FROM website_builder_projects
                WHERE user_id = %s
                ORDER BY updated_at DESC
            """,
                (current_user.id,),
            )

        projects = cur.fetchall()

        return jsonify({"success": True, "projects": [dict(p) for p in projects]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


@website_studio_bp.route("/api/projects", methods=["POST"])
@login_required
def create_project():
    """Create a new website project"""
    try:
        data = request.get_json()

        if not data.get("name"):
            return jsonify({"success": False, "error": "Project name is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Create project
        cur.execute(
            """
            INSERT INTO website_builder_projects
            (user_id, name, description, template_type, settings)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                current_user.id,
                data["name"],
                data.get("description", ""),
                data.get("template_type", "blank"),
                json.dumps(data.get("settings", {})),
            ),
        )

        project = cur.fetchone()
        conn.commit()

        # Log activity
        try:
            log_user_activity(
                "create",
                "website_studio",
                {"project_name": data["name"]},
                "project",
                project["id"],
            )
        except Exception as e:
            pass  # Non-critical operation

        return jsonify(
            {
                "success": True,
                "message": "Project created successfully",
                "project": dict(project),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


@website_studio_bp.route("/api/projects/<int:project_id>", methods=["GET"])
@login_required
def get_project(project_id):
    """Get a specific project with pages"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get project
        cur.execute("SELECT * FROM website_builder_projects WHERE id = %s", (project_id,))
        project = cur.fetchone()

        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404

        # Check access
        if not can_access_resource(project["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        # Get pages
        cur.execute(
            """
            SELECT * FROM website_builder_pages
            WHERE project_id = %s
            ORDER BY sort_order, created_at
        """,
            (project_id,),
        )
        pages = cur.fetchall()

        # Get deployment info
        cur.execute(
            """
            SELECT * FROM website_deployments
            WHERE website_id = %s
            ORDER BY created_at DESC
            LIMIT 5
        """,
            (project_id,),
        )
        deployments = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "project": dict(project),
                "pages": [dict(p) for p in pages],
                "deployments": [dict(d) for d in deployments],
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


@website_studio_bp.route("/api/projects/<int:project_id>", methods=["PUT"])
@login_required
def update_project(project_id):
    """Update a project"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute("SELECT user_id FROM website_builder_projects WHERE id = %s", (project_id,))
        project = cur.fetchone()

        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if not can_access_resource(project["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        # Build update
        updates = []
        values = []
        allowed = ["name", "description", "template_type", "settings", "status"]

        for field in allowed:
            if field in data:
                updates.append(f"{field} = %s")
                val = json.dumps(data[field]) if field == "settings" else data[field]
                values.append(val)

        if not updates:
            return (
                jsonify({"success": False, "error": "No valid fields to update"}),
                400,
            )

        updates.append("updated_at = NOW()")
        values.append(project_id)

        cur.execute(
            f"""
            UPDATE website_builder_projects
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING *
        """,
            values,
        )

        updated = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "message": "Project updated", "project": dict(updated)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


@website_studio_bp.route("/api/projects/<int:project_id>", methods=["DELETE"])
@login_required
def delete_project(project_id):
    """Delete a project"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute(
            "SELECT user_id, name FROM website_builder_projects WHERE id = %s",
            (project_id,),
        )
        project = cur.fetchone()

        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if not can_access_resource(project["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        # Delete (CASCADE handles pages)
        cur.execute("DELETE FROM website_builder_projects WHERE id = %s", (project_id,))
        conn.commit()

        # Log activity
        try:
            log_user_activity(
                "delete",
                "website_studio",
                {"project_name": project["name"]},
                "project",
                project_id,
            )
        except Exception as e:
            pass  # Non-critical operation

        return jsonify({"success": True, "message": f'Project "{project["name"]}" deleted'})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


# ============================================================================
# AI ASSISTANCE
# ============================================================================


@website_studio_bp.route("/api/ai/suggest-design", methods=["POST"])
@login_required
def ai_suggest_design():
    """Get AI suggestions for website design"""
    if not AI_AVAILABLE:
        return jsonify({"success": False, "error": "AI assistance not available"}), 503

    try:
        data = request.get_json()

        if not data.get("description"):
            return jsonify({"success": False, "error": "Description is required"}), 400

        result = suggest_website_design(
            description=data["description"],
            website_type=data.get("website_type"),
            user_id=current_user.id,
        )

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/ai/generate-content", methods=["POST"])
@login_required
def ai_generate_content():
    """Generate content for a page"""
    if not AI_AVAILABLE:
        return jsonify({"success": False, "error": "AI assistance not available"}), 503

    try:
        data = request.get_json()

        if not data.get("page_name"):
            return jsonify({"success": False, "error": "Page name is required"}), 400

        result = generate_page_content(
            page_name=data["page_name"],
            website_description=data.get("website_description", ""),
            business_name=data.get("business_name"),
            tone=data.get("tone", "professional"),
        )

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/ai/improve-seo", methods=["POST"])
@login_required
def ai_improve_seo():
    """Get SEO improvement suggestions"""
    if not AI_AVAILABLE:
        return jsonify({"success": False, "error": "AI assistance not available"}), 503

    try:
        data = request.get_json()

        result = improve_seo(
            title=data.get("title", ""),
            description=data.get("description", ""),
            content=data.get("content", ""),
            keywords=data.get("keywords", []),
        )

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/ai/generate-styles", methods=["POST"])
@login_required
def ai_generate_styles():
    """Generate CSS styles"""
    if not AI_AVAILABLE:
        return jsonify({"success": False, "error": "AI assistance not available"}), 503

    try:
        data = request.get_json()

        result = generate_css_styles(
            design_style=data.get("design_style", "modern minimalist"),
            color_scheme=data.get("color_scheme"),
            components=data.get("components"),
        )

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# CHAT-BASED WEBSITE EDITING (Phase 7)
# ============================================================================


@website_studio_bp.route("/api/chat", methods=["POST"])
@login_required
def chat_with_archie():
    """
    Chat-based website editing endpoint.
    Send natural language requests to A.R.C.H.I.E. for website modifications.
    """
    if not CHAT_HANDLER_AVAILABLE:
        return jsonify({"success": False, "error": "Chat handler not available"}), 503

    try:
        data = request.get_json()
        message = data.get("message", "").strip()

        if not message:
            return jsonify({"success": False, "error": "Message is required"}), 400

        # Ensure repo is cloned
        repo_status = ensure_repo_cloned()
        if not repo_status.get("success"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Repository not available: {repo_status.get('error', 'Unknown error')}",
                    }
                ),
                500,
            )

        # Get system prompt with current site context
        system_prompt = get_chat_system_prompt()

        # Role detection — specialize the system prompt
        role = detect_task_role(message)
        if role == "design":
            system_prompt += (
                "\n\nFocus on CSS, visual design, and styling in your response. You are acting as a design specialist."
            )
        elif role == "deploy":
            system_prompt += (
                "\n\nThe user wants to deploy or manage hosting. Guide them through the deployment process."
            )

        # Import archie_bridge for AI response
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
            from archie_bridge import archie_bridge as ai_bridge
        except ImportError as e:
            current_app.logger.error(f"[WebsiteStudio] Failed to import archie_bridge: {e}")
            return jsonify({"success": False, "error": "AI bridge not available"}), 503

        # Send to A.R.C.H.I.E. via archie_bridge
        # It will route to the best available AI provider
        # Note: disable memory to keep prompt size manageable (system prompt already has site context)
        try:
            ai_result = ai_bridge(
                prompt=message,
                system_prompt=system_prompt,
                user_id=current_user.id if current_user.is_authenticated else None,
                enable_memory=False,  # Disabled - site context is already in system_prompt
            )

            # archie_bridge returns dict with 'success', 'response', 'model', 'provider', etc.
            if not ai_result.get("success"):
                current_app.logger.error(f"[WebsiteStudio] AI bridge returned failure: {ai_result}")
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": ai_result.get("error", "AI request failed"),
                            "message": "Sorry, I had trouble understanding that request. Please try again.",
                        }
                    ),
                    500,
                )

            response_text = ai_result.get("response", "")
            current_app.logger.info(
                f"[WebsiteStudio] AI response from {ai_result.get('provider', 'unknown')}/{ai_result.get('model', 'unknown')}"
            )

        except Exception as ai_error:
            current_app.logger.error(f"[WebsiteStudio] AI call failed: {ai_error}")
            return (
                jsonify(
                    {
                        "success": False,
                        "error": str(ai_error),
                        "message": "Sorry, I had trouble understanding that request. Please try again.",
                    }
                ),
                500,
            )

        if not response_text:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Empty response from AI",
                        "message": "Sorry, I had trouble understanding that request. Please try again.",
                    }
                ),
                500,
            )

        # Parse response for file changes
        changes = parse_file_changes(response_text)

        # Generate diff previews if changes found
        previews = []
        if changes:
            previews = generate_diff_preview(changes)

        # Save to chat history
        project_id = data.get("project_id")
        if project_id:
            existing = load_chat_history(project_id)
            existing.append({"role": "user", "message": message, "timestamp": datetime.utcnow().isoformat()})
            existing.append({"role": "ai", "message": response_text[:500], "timestamp": datetime.utcnow().isoformat()})
            save_chat_history(project_id, existing)

        return jsonify(
            {
                "success": True,
                "message": response_text,
                "changes": changes,
                "previews": previews,
                "has_changes": len(changes) > 0,
            }
        )

    except Exception as e:
        current_app.logger.error(f"[WebsiteStudio] Chat error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/chat/history/<int:project_id>", methods=["GET"])
@login_required
def get_chat_history_route(project_id):
    from .chat_handler import load_chat_history

    history = load_chat_history(project_id)
    return jsonify({"success": True, "history": history})


@website_studio_bp.route("/api/apply-changes", methods=["POST"])
@login_required
def apply_ai_changes():
    """
    Apply AI-generated file changes to the repository.
    """
    if not CHAT_HANDLER_AVAILABLE:
        return jsonify({"success": False, "error": "Chat handler not available"}), 503

    try:
        data = request.get_json()
        changes = data.get("changes", [])
        auto_commit = data.get("auto_commit", True)
        commit_message = data.get("commit_message")

        if not changes:
            return jsonify({"success": False, "error": "No changes to apply"}), 400

        # Apply the changes
        result = apply_file_changes(changes)

        # Auto-commit if enabled and changes were applied
        commit_result = None
        if auto_commit and result.get("applied"):
            if not commit_message:
                # Generate commit message from changes
                files_modified = [c.get("file", "unknown") for c in result.get("applied", [])]
                commit_message = f"Website update: {', '.join(files_modified[:3])}"
                if len(files_modified) > 3:
                    commit_message += f" (+{len(files_modified) - 3} more)"
                commit_message += " - via A.R.C.H.I.E."

            commit_result = auto_commit_changes(commit_message)

        return jsonify(
            {
                "success": result.get("success", False),
                "applied": result.get("applied", []),
                "failed": result.get("failed", []),
                "files_modified": result.get("files_modified", 0),
                "commit": commit_result,
            }
        )

    except Exception as e:
        current_app.logger.error(f"[WebsiteStudio] Apply changes error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/preview", methods=["GET"])
@login_required
def preview_site():
    """
    Serve the current site preview from local repository.
    """
    if not CHAT_HANDLER_AVAILABLE:
        return jsonify({"success": False, "error": "Chat handler not available"}), 503

    try:
        file_path = request.args.get("file", "index.html")

        # Security: prevent path traversal
        if ".." in file_path:
            return jsonify({"success": False, "error": "Invalid path"}), 400

        full_path = os.path.join(WEBSITE_REPO_PATH, file_path)

        if not os.path.exists(full_path):
            return jsonify({"success": False, "error": "File not found"}), 404

        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Determine content type
        ext = os.path.splitext(file_path)[1].lower()
        content_types = {
            ".html": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".json": "application/json",
        }
        content_type = content_types.get(ext, "text/plain")

        from flask import Response

        return Response(content, mimetype=content_type)

    except Exception as e:
        current_app.logger.error(f"[WebsiteStudio] Preview error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/preview/<path:file_path>")
@login_required
def serve_preview_file(file_path):
    """
    Serve any file from the website repository for live preview.
    This allows the preview iframe to load CSS, JS, and images with relative paths.
    """
    import mimetypes
    from flask import Response, send_file

    try:
        # Security: prevent path traversal
        if ".." in file_path:
            return Response("Invalid path", status=400)

        full_path = os.path.join(WEBSITE_REPO_PATH, file_path)

        # Verify the path is within the repo
        if not os.path.abspath(full_path).startswith(os.path.abspath(WEBSITE_REPO_PATH)):
            return Response("Invalid path", status=400)

        if not os.path.exists(full_path):
            return Response("File not found", status=404)

        # Determine mime type
        mime_type, _ = mimetypes.guess_type(full_path)
        if mime_type is None:
            mime_type = "application/octet-stream"

        # For binary files (images, etc.), use send_file
        if mime_type.startswith("image/") or mime_type == "application/octet-stream":
            return send_file(full_path, mimetype=mime_type)

        # For text files, read and return
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()

        return Response(content, mimetype=mime_type)

    except Exception as e:
        current_app.logger.error(f"[WebsiteStudio] Serve file error: {e}")
        return Response(f"Error: {str(e)}", status=500)


@website_studio_bp.route("/api/site-context", methods=["GET"])
@login_required
def get_site_context():
    """
    Get current site structure and context for the chat interface.
    """
    if not CHAT_HANDLER_AVAILABLE:
        return jsonify({"success": False, "error": "Chat handler not available"}), 503

    try:
        # Ensure repo is available
        repo_status = ensure_repo_cloned()

        context = build_site_context()

        return jsonify(
            {
                "success": True,
                "repo_status": repo_status,
                "file_tree": context.get("file_tree", ""),
                "file_count": len(context.get("file_contents", "").split("===")) - 1,
            }
        )

    except Exception as e:
        current_app.logger.error(f"[WebsiteStudio] Site context error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/chat/history", methods=["GET"])
@login_required
def get_chat_history():
    """
    Get chat history for the current user/project.
    """
    try:
        project_id = request.args.get("project_id", type=int)
        limit = request.args.get("limit", 50, type=int)

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if chat_history column exists in projects table
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'website_builder_projects' AND column_name = 'chat_history'
        """
        )

        if not cur.fetchone():
            # Add column if it doesn't exist
            cur.execute(
                """
                ALTER TABLE website_builder_projects
                ADD COLUMN IF NOT EXISTS chat_history JSONB DEFAULT '[]'
            """
            )
            conn.commit()

        if project_id:
            cur.execute(
                """
                SELECT chat_history FROM website_builder_projects
                WHERE id = %s AND user_id = %s
            """,
                (project_id, current_user.id),
            )
            result = cur.fetchone()
            history = result["chat_history"] if result else []
        else:
            history = []

        return jsonify({"success": True, "history": history[-limit:] if history else []})

    except Exception as e:
        current_app.logger.error(f"[WebsiteStudio] Chat history error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


@website_studio_bp.route("/api/chat/history", methods=["POST"])
@login_required
def save_chat_message():
    """
    Save a chat message to history.
    """
    try:
        data = request.get_json()
        project_id = data.get("project_id")
        message = data.get("message")
        role = data.get("role", "user")  # 'user' or 'assistant'

        if not project_id or not message:
            return (
                jsonify({"success": False, "error": "project_id and message required"}),
                400,
            )

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Ensure column exists
        cur.execute(
            """
            ALTER TABLE website_builder_projects
            ADD COLUMN IF NOT EXISTS chat_history JSONB DEFAULT '[]'
        """
        )

        # Append message to history
        chat_entry = {
            "role": role,
            "content": message,
            "timestamp": datetime.now().isoformat(),
        }

        cur.execute(
            """
            UPDATE website_builder_projects
            SET chat_history = COALESCE(chat_history, '[]'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE id = %s AND user_id = %s
            RETURNING id
        """,
            (json.dumps([chat_entry]), project_id, current_user.id),
        )

        result = cur.fetchone()
        conn.commit()

        if not result:
            return jsonify({"success": False, "error": "Project not found"}), 404

        return jsonify({"success": True, "message": "Chat message saved"})

    except Exception as e:
        current_app.logger.error(f"[WebsiteStudio] Save chat error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


# ============================================================================
# DEPLOYMENT
# ============================================================================


@website_studio_bp.route("/api/projects/<int:project_id>/deploy", methods=["POST"])
@login_required
def deploy_project(project_id):
    """Deploy a project to selected platform"""
    try:
        data = request.get_json()
        deployment_type = data.get("deployment_type", "github_pages")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute("SELECT * FROM website_builder_projects WHERE id = %s", (project_id,))
        project = cur.fetchone()

        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if not can_access_resource(project["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        # Check if user has required integration
        cur.execute(
            """
            SELECT * FROM user_integrations
            WHERE user_id = %s AND service = %s AND status = 'active'
        """,
            (current_user.id, deployment_type.split("_")[0]),
        )  # github_pages -> github

        integration = cur.fetchone()

        if not integration and not is_admin_user():
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Please connect your {deployment_type} account first",
                    }
                ),
                400,
            )

        # Create deployment record
        cur.execute(
            """
            INSERT INTO website_deployments
            (website_id, deployed_by, deployment_type, status)
            VALUES (%s, %s, %s, %s)
            RETURNING *
        """,
            (project_id, current_user.id, deployment_type, "pending"),
        )

        deployment = cur.fetchone()
        deployment_id = deployment["id"]
        conn.commit()

        # Execute actual deployment for GitHub Pages
        deploy_result = None
        if deployment_type == "github_pages" and CHAT_HANDLER_AVAILABLE:
            try:
                # Stage and commit any pending changes
                commit_result = auto_commit_changes(f"Deploy: Website update for {project['name']} - via A.R.C.H.I.E.")

                # Push to remote
                push_result = subprocess.run(
                    ["git", "push", "origin", "main"],
                    cwd=WEBSITE_REPO_PATH,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                if push_result.returncode == 0:
                    # Get the latest commit SHA
                    sha_result = subprocess.run(
                        ["git", "rev-parse", "HEAD"],
                        cwd=WEBSITE_REPO_PATH,
                        capture_output=True,
                        text=True,
                    )
                    commit_sha = sha_result.stdout.strip()[:8]

                    # Update deployment record to success
                    cur = conn.cursor(cursor_factory=RealDictCursor)
                    cur.execute(
                        """
                        UPDATE website_deployments
                        SET status = 'completed',
                            deployment_url = %s,
                            metadata = %s
                        WHERE id = %s
                    """,
                        (
                            "https://www.kytranempowerment.com",
                            json.dumps(
                                {
                                    "commit_sha": commit_sha,
                                    "push_output": push_result.stdout,
                                }
                            ),
                            deployment_id,
                        ),
                    )
                    conn.commit()
                    cur.close()

                    deploy_result = {
                        "success": True,
                        "commit_sha": commit_sha,
                        "url": "https://www.kytranempowerment.com",
                        "message": "Deployed successfully! Changes will be live in a few minutes.",
                    }
                else:
                    # Update deployment record to failed
                    cur = conn.cursor(cursor_factory=RealDictCursor)
                    cur.execute(
                        """
                        UPDATE website_deployments
                        SET status = 'failed',
                            metadata = %s
                        WHERE id = %s
                    """,
                        (json.dumps({"error": push_result.stderr}), deployment_id),
                    )
                    conn.commit()
                    cur.close()

                    deploy_result = {
                        "success": False,
                        "error": push_result.stderr or "Push failed",
                    }

            except subprocess.TimeoutExpired:
                deploy_result = {"success": False, "error": "Push timed out"}
            except Exception as e:
                deploy_result = {"success": False, "error": str(e)}

        return jsonify(
            {
                "success": True,
                "message": "Deployment initiated",
                "deployment": dict(deployment),
                "deploy_result": deploy_result,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


@website_studio_bp.route("/api/deploy-to-github-pages", methods=["POST"])
@login_required
@admin_required
def deploy_to_github_pages():
    """
    One-click deploy to GitHub Pages.
    Commits all changes, pushes to GitHub, and GitHub Pages auto-deploys.
    """
    if not CHAT_HANDLER_AVAILABLE:
        return jsonify({"success": False, "error": "Chat handler not available"}), 503

    try:
        data = request.get_json() or {}
        commit_message = data.get("message")

        # Ensure repo exists
        repo_status = ensure_repo_cloned()
        if not repo_status.get("success"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Repository not available: {repo_status.get('error')}",
                    }
                ),
                500,
            )

        # Check for uncommitted changes
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=WEBSITE_REPO_PATH,
            capture_output=True,
            text=True,
        )

        has_changes = bool(status_result.stdout.strip())

        # Commit if there are changes
        commit_sha = None
        if has_changes:
            if not commit_message:
                commit_message = f"Website deploy via A.R.C.H.I.E. - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

            commit_result = auto_commit_changes(commit_message)
            if commit_result.get("success") and commit_result.get("sha"):
                commit_sha = commit_result["sha"]

        # Get GitHub token for authenticated push
        github_token = os.getenv("GITHUB_TOKEN", "")

        # Configure remote URL with token for push
        if github_token:
            subprocess.run(
                [
                    "git",
                    "remote",
                    "set-url",
                    "origin",
                    f"https://{github_token}@github.com/{ADMIN_WEBSITE_REPO}.git",
                ],
                cwd=WEBSITE_REPO_PATH,
                capture_output=True,
            )

        # Push to GitHub
        push_result = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=WEBSITE_REPO_PATH,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if push_result.returncode != 0:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": push_result.stderr or "Push failed",
                        "details": "Make sure the GitHub token has push access to the repository.",
                    }
                ),
                500,
            )

        # Get the pushed commit SHA
        if not commit_sha:
            sha_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=WEBSITE_REPO_PATH,
                capture_output=True,
                text=True,
            )
            commit_sha = sha_result.stdout.strip()[:8]

        # Record deployment in database
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO website_deployments
            (website_id, deployed_by, deployment_type, status, deployment_url, metadata)
            VALUES (
                (SELECT id FROM website_builder_projects
                 WHERE name LIKE '%kytranempowerment%' LIMIT 1),
                %s, 'github_pages', 'completed',
                'https://www.kytranempowerment.com',
                %s
            )
            RETURNING *
        """,
            (
                current_user.id,
                json.dumps(
                    {
                        "commit_sha": commit_sha,
                        "had_changes": has_changes,
                        "push_output": push_result.stdout,
                    }
                ),
            ),
        )

        deployment = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": "Deployed successfully to GitHub Pages!",
                "commit_sha": commit_sha,
                "url": "https://www.kytranempowerment.com",
                "had_changes": has_changes,
                "deployment": dict(deployment) if deployment else None,
                "note": "Changes typically go live within 1-2 minutes.",
            }
        )

    except subprocess.TimeoutExpired:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Push operation timed out. Please try again.",
                }
            ),
            500,
        )
    except Exception as e:
        current_app.logger.error(f"[WebsiteStudio] Deploy error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


@website_studio_bp.route("/api/projects/<int:project_id>/deployments", methods=["GET"])
@login_required
def get_deployments(project_id):
    """Get deployment history for a project"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify access
        cur.execute("SELECT user_id FROM website_builder_projects WHERE id = %s", (project_id,))
        project = cur.fetchone()

        if not project or not can_access_resource(project["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        cur.execute(
            """
            SELECT * FROM website_deployments
            WHERE website_id = %s
            ORDER BY created_at DESC
            LIMIT 20
        """,
            (project_id,),
        )

        deployments = cur.fetchall()

        return jsonify({"success": True, "deployments": [dict(d) for d in deployments]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


# ============================================================================
# USER INTEGRATIONS
# ============================================================================


@website_studio_bp.route("/api/integrations", methods=["GET"])
@login_required
def get_integrations():
    """Get user's connected integrations"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, service, status, settings, last_verified_at, created_at
            FROM user_integrations
            WHERE user_id = %s AND service IN ('github', 'vercel', 'netlify', 'cloudflare')
        """,
            (current_user.id,),
        )

        integrations = cur.fetchall()

        return jsonify({"success": True, "integrations": [dict(i) for i in integrations]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


@website_studio_bp.route("/api/integrations/<service>", methods=["POST"])
@login_required
def connect_integration(service):
    """Connect a new integration"""
    try:
        allowed_services = ["github", "vercel", "netlify", "cloudflare"]
        if service not in allowed_services:
            return jsonify({"success": False, "error": "Invalid service"}), 400

        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Upsert integration
        cur.execute(
            """
            INSERT INTO user_integrations (user_id, service, credentials, settings, status)
            VALUES (%s, %s, %s, %s, 'active')
            ON CONFLICT (user_id, service)
            DO UPDATE SET
                credentials = EXCLUDED.credentials,
                settings = EXCLUDED.settings,
                status = 'active',
                updated_at = NOW()
            RETURNING id, service, status, settings
        """,
            (
                current_user.id,
                service,
                json.dumps(data.get("credentials", {})),  # Should be encrypted in production
                json.dumps(data.get("settings", {})),
            ),
        )

        integration = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": f"{service.title()} connected successfully",
                "integration": dict(integration),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


@website_studio_bp.route("/api/integrations/<service>", methods=["DELETE"])
@login_required
def disconnect_integration(service):
    """Disconnect an integration"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE user_integrations
            SET status = 'inactive', credentials = '{}'
            WHERE user_id = %s AND service = %s
        """,
            (current_user.id, service),
        )

        conn.commit()

        return jsonify({"success": True, "message": f"{service.title()} disconnected"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


# ============================================================================
# PAGES CRUD
# ============================================================================


@website_studio_bp.route("/api/projects/<int:project_id>/pages", methods=["GET"])
@login_required
def get_pages(project_id):
    """Get all pages for a project"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify access
        cur.execute("SELECT user_id FROM website_builder_projects WHERE id = %s", (project_id,))
        project = cur.fetchone()

        if not project or not can_access_resource(project["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        cur.execute(
            """
            SELECT * FROM website_builder_pages
            WHERE project_id = %s
            ORDER BY sort_order, created_at
        """,
            (project_id,),
        )

        pages = cur.fetchall()

        return jsonify({"success": True, "pages": [dict(p) for p in pages]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


@website_studio_bp.route("/api/projects/<int:project_id>/pages", methods=["POST"])
@login_required
def create_page(project_id):
    """Create a new page"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify access
        cur.execute("SELECT user_id FROM website_builder_projects WHERE id = %s", (project_id,))
        project = cur.fetchone()

        if not project or not can_access_resource(project["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        cur.execute(
            """
            INSERT INTO website_builder_pages
            (project_id, user_id, name, slug, content, settings, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                project_id,
                current_user.id,
                data.get("name", "New Page"),
                data.get("slug", "new-page"),
                data.get("content", ""),
                json.dumps(data.get("settings", {})),
                data.get("sort_order", 0),
            ),
        )

        page = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "message": "Page created", "page": dict(page)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


@website_studio_bp.route("/api/pages/<int:page_id>", methods=["PUT"])
@login_required
def update_page(page_id):
    """Update a page"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify access
        cur.execute("SELECT user_id FROM website_builder_pages WHERE id = %s", (page_id,))
        page = cur.fetchone()

        if not page or not can_access_resource(page["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        updates = []
        values = []
        allowed = [
            "name",
            "slug",
            "content",
            "settings",
            "sort_order",
            "seo_title",
            "seo_description",
        ]

        for field in allowed:
            if field in data:
                updates.append(f"{field} = %s")
                val = json.dumps(data[field]) if field == "settings" else data[field]
                values.append(val)

        if not updates:
            return jsonify({"success": False, "error": "No valid fields"}), 400

        updates.append("updated_at = NOW()")
        values.append(page_id)

        cur.execute(
            f"""
            UPDATE website_builder_pages
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING *
        """,
            values,
        )

        updated = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "message": "Page updated", "page": dict(updated)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


@website_studio_bp.route("/api/pages/<int:page_id>", methods=["DELETE"])
@login_required
def delete_page(page_id):
    """Delete a page"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify access
        cur.execute("SELECT user_id, name FROM website_builder_pages WHERE id = %s", (page_id,))
        page = cur.fetchone()

        if not page or not can_access_resource(page["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        cur.execute("DELETE FROM website_builder_pages WHERE id = %s", (page_id,))
        conn.commit()

        return jsonify({"success": True, "message": f'Page "{page["name"]}" deleted'})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


# ============================================================================
# WEBSITE DEPLOY - Migrated from admin/routes.py
# ============================================================================

# Import GitHub deployment if available
try:
    from services.github_deployment import (
        deploy_website,
        get_latest_commit,
        get_repo_info,
        get_deployment_history,
    )

    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False


@website_studio_bp.route("/api/deploy", methods=["POST"])
@login_required
@admin_required
def website_deploy():
    """Deploy website from GitHub"""
    if not GITHUB_AVAILABLE:
        return (
            jsonify({"success": False, "error": "GitHub integration not available"}),
            503,
        )

    try:
        result = deploy_website(current_user.id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/deploy/status", methods=["GET"])
@login_required
@admin_required
def website_status():
    """Get website deployment status"""
    if not GITHUB_AVAILABLE:
        return (
            jsonify({"success": False, "error": "GitHub integration not available"}),
            503,
        )

    try:
        commit = get_latest_commit()
        repo = get_repo_info()
        history = get_deployment_history(5)

        return jsonify(
            {
                "success": True,
                "latest_commit": commit,
                "repo_info": repo,
                "deployment_history": [dict(d) for d in history],
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# GIT INTEGRATION (Phase 22)
# ============================================================================

import subprocess

# Default repo for admin: kytranempowerment-site
ADMIN_WEBSITE_REPO = "KytranKatarn/kytranempowerment-site"
WEBSITE_REPO_PATH = "/tmp/website-repo"  # Clone location


@website_studio_bp.route("/api/git/status", methods=["GET"])
@login_required
def git_status():
    """Get git status of the website repository"""
    try:
        repo_path = WEBSITE_REPO_PATH
        if not os.path.exists(repo_path):
            return jsonify(
                {
                    "success": True,
                    "changed_files": [],
                    "message": "Repository not cloned",
                }
            )

        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )

        files = []
        for line in result.stdout.strip().split("\n"):
            if line:
                status_code = line[:2].strip()
                file_path = line[3:].strip()
                status_map = {
                    "M": "modified",
                    "A": "added",
                    "D": "deleted",
                    "??": "untracked",
                }
                files.append(
                    {
                        "path": file_path,
                        "status": status_map.get(status_code, "changed"),
                    }
                )

        return jsonify({"success": True, "changed_files": files})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/git/info", methods=["GET"])
@login_required
def git_info():
    """Get repository information"""
    try:
        repo_path = WEBSITE_REPO_PATH
        if not os.path.exists(repo_path):
            return jsonify({"success": False, "error": "Repository not cloned"})

        # Get remote URL
        remote_result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        remote_url = remote_result.stdout.strip()

        # Parse repo name from URL
        repo_name = "Unknown"
        if remote_url:
            # Handle both HTTPS and SSH URLs
            if "github.com" in remote_url:
                if remote_url.startswith("git@"):
                    # SSH format: git@github.com:user/repo.git
                    repo_name = remote_url.split(":")[-1].replace(".git", "")
                else:
                    # HTTPS format: https://github.com/user/repo.git
                    repo_name = "/".join(remote_url.split("/")[-2:]).replace(".git", "")

        # Get current branch
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        branch = branch_result.stdout.strip() or "main"

        # Build GitHub URL
        github_url = f"https://github.com/{repo_name}" if repo_name != "Unknown" else None

        return jsonify(
            {
                "success": True,
                "repo_name": repo_name,
                "branch": branch,
                "remote_url": github_url,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/git/fetch", methods=["POST"])
@login_required
def git_fetch():
    """Fetch from remote"""
    try:
        repo_path = WEBSITE_REPO_PATH
        if not os.path.exists(repo_path):
            return jsonify({"success": False, "error": "Repository not cloned"})

        result = subprocess.run(["git", "fetch", "--all"], cwd=repo_path, capture_output=True, text=True)

        if result.returncode != 0:
            return jsonify({"success": False, "error": result.stderr})

        return jsonify({"success": True, "message": "Fetch completed"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/git/commits", methods=["GET"])
@login_required
def git_commits():
    """Get recent commit history"""
    try:
        limit = request.args.get("limit", 10, type=int)
        repo_path = WEBSITE_REPO_PATH

        if not os.path.exists(repo_path):
            return jsonify({"success": True, "commits": []})

        result = subprocess.run(
            ["git", "log", f"-{limit}", "--pretty=format:%H|%an|%ar|%s"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )

        commits = []
        for line in result.stdout.strip().split("\n"):
            if line and "|" in line:
                parts = line.split("|", 3)
                if len(parts) >= 4:
                    commits.append(
                        {
                            "sha": parts[0],
                            "author": parts[1],
                            "date": parts[2],
                            "message": parts[3],
                        }
                    )

        return jsonify({"success": True, "commits": commits})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/git/commit", methods=["POST"])
@login_required
def git_commit():
    """Create a new commit"""
    try:
        data = request.get_json()
        message = data.get("message", "")
        stage_all = data.get("stage_all", True)

        if not message:
            return jsonify({"success": False, "error": "Commit message required"}), 400

        repo_path = WEBSITE_REPO_PATH

        if stage_all:
            subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True)

        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            return jsonify({"success": True, "message": "Commit created"})
        else:
            return (
                jsonify({"success": False, "error": result.stderr or "Nothing to commit"}),
                400,
            )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/git/pull", methods=["POST"])
@login_required
def git_pull():
    """Pull latest changes from remote"""
    try:
        repo_path = WEBSITE_REPO_PATH

        if not os.path.exists(repo_path):
            # Clone the repo first
            repo_url = f"https://github.com/{ADMIN_WEBSITE_REPO}.git"
            subprocess.run(["git", "clone", repo_url, repo_path], check=True)
            return jsonify({"success": True, "message": "Repository cloned"})

        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            return jsonify({"success": True, "message": result.stdout})
        else:
            return jsonify({"success": False, "error": result.stderr}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/git/push", methods=["POST"])
@login_required
@admin_required
def git_push():
    """Push commits to remote (admin only)"""
    try:
        repo_path = WEBSITE_REPO_PATH

        result = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            return jsonify({"success": True, "message": "Pushed successfully"})
        else:
            return jsonify({"success": False, "error": result.stderr}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/git/files", methods=["GET"])
@login_required
def git_files():
    """List files in the repository"""
    try:
        repo_path = WEBSITE_REPO_PATH

        if not os.path.exists(repo_path):
            return jsonify({"success": True, "files": []})

        files = []
        for root, dirs, filenames in os.walk(repo_path):
            # Skip .git directory
            if ".git" in root:
                continue
            for filename in filenames:
                rel_path = os.path.relpath(os.path.join(root, filename), repo_path)
                if not rel_path.startswith(".git"):
                    files.append(rel_path)

        return jsonify({"success": True, "files": sorted(files)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/git/tree", methods=["GET"])
@login_required
def git_tree():
    """Get hierarchical file tree for the repository (WD-1)"""
    try:
        repo_path = WEBSITE_REPO_PATH

        if not os.path.exists(repo_path):
            return jsonify(
                {
                    "success": True,
                    "tree": {"name": "root", "type": "directory", "children": []},
                }
            )

        # Get modified files from git status
        import subprocess

        modified_files = set()
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        # Format: "XY filename" where XY is status
                        parts = line.strip().split(maxsplit=1)
                        if len(parts) >= 2:
                            modified_files.add(parts[1])
        except Exception:
            pass

        def build_tree(path, name="root"):
            """Recursively build tree structure"""
            node = {"name": name, "type": "directory", "children": [], "path": ""}

            try:
                entries = sorted(os.listdir(path))
            except PermissionError:
                return node

            dirs = []
            files = []

            for entry in entries:
                if entry.startswith("."):
                    continue  # Skip hidden files/dirs
                full_path = os.path.join(path, entry)
                rel_path = os.path.relpath(full_path, repo_path)

                if os.path.isdir(full_path):
                    dirs.append((entry, full_path, rel_path))
                else:
                    files.append((entry, full_path, rel_path))

            # Add directories first
            for entry, full_path, rel_path in dirs:
                child = build_tree(full_path, entry)
                child["path"] = rel_path
                node["children"].append(child)

            # Add files
            for entry, full_path, rel_path in files:
                # Determine file type for icon
                ext = os.path.splitext(entry)[1].lower()
                file_type = "file"
                if ext in [".html", ".htm"]:
                    file_type = "html"
                elif ext in [".css", ".scss", ".sass", ".less"]:
                    file_type = "css"
                elif ext in [".js", ".jsx", ".ts", ".tsx"]:
                    file_type = "js"
                elif ext in [".json"]:
                    file_type = "json"
                elif ext in [".md", ".markdown"]:
                    file_type = "markdown"
                elif ext in [".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico"]:
                    file_type = "image"

                node["children"].append(
                    {
                        "name": entry,
                        "type": "file",
                        "file_type": file_type,
                        "path": rel_path,
                        "modified": rel_path in modified_files,
                        "size": os.path.getsize(full_path),
                    }
                )

            return node

        tree = build_tree(repo_path)
        return jsonify({"success": True, "tree": tree})
    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/git/file", methods=["GET"])
@login_required
def git_file_read():
    """Read a file from the repository"""
    try:
        file_path = request.args.get("path", "")
        if not file_path:
            return jsonify({"success": False, "error": "File path required"}), 400

        full_path = os.path.join(WEBSITE_REPO_PATH, file_path)

        # Security: prevent path traversal
        if ".." in file_path or not full_path.startswith(WEBSITE_REPO_PATH):
            return jsonify({"success": False, "error": "Invalid path"}), 400

        if not os.path.exists(full_path):
            return jsonify({"success": False, "error": "File not found"}), 404

        with open(full_path, "r") as f:
            content = f.read()

        return jsonify({"success": True, "content": content, "path": file_path})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@website_studio_bp.route("/api/git/file", methods=["PUT"])
@login_required
def git_file_write():
    """Write a file to the repository"""
    try:
        data = request.get_json()
        file_path = data.get("path", "")
        content = data.get("content", "")

        if not file_path:
            return jsonify({"success": False, "error": "File path required"}), 400

        full_path = os.path.join(WEBSITE_REPO_PATH, file_path)

        # Security: prevent path traversal
        if ".." in file_path or not full_path.startswith(WEBSITE_REPO_PATH):
            return jsonify({"success": False, "error": "Invalid path"}), 400

        # Ensure directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, "w") as f:
            f.write(content)

        return jsonify({"success": True, "message": "File saved"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# BUSINESS DIRECTORY (Phase 22)
# ============================================================================


@website_studio_bp.route("/api/directory", methods=["GET"])
@login_required
def get_directory():
    """Get business directory members"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if is_admin_user():
            # Admin sees AI team from agents table
            cur.execute(
                """
                SELECT id, name, role, specialization as description,
                       department, email, avatar, status
                FROM agents
                WHERE status = 'active'
                ORDER BY name
            """
            )
        else:
            # Users see their own directory entries
            cur.execute(
                """
                SELECT id, name, role, description, email, department
                FROM user_directory_entries
                WHERE user_id = %s
                ORDER BY name
            """,
                (current_user.id,),
            )

        members = cur.fetchall()

        return jsonify({"success": True, "members": [dict(m) for m in members]})
    except Exception as e:
        current_app.logger.error(f"[WebsiteStudio] Directory error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


@website_studio_bp.route("/api/directory", methods=["POST"])
@login_required
def add_directory_entry():
    """Add a new directory entry (for users)"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if table exists, create if not
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_directory_entries (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                role VARCHAR(255),
                description TEXT,
                email VARCHAR(255),
                department VARCHAR(255),
                phone VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        conn.commit()

        cur.execute(
            """
            INSERT INTO user_directory_entries
            (user_id, name, role, description, email, department)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                current_user.id,
                data.get("name"),
                data.get("role"),
                data.get("description"),
                data.get("email"),
                data.get("department"),
            ),
        )

        entry = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "message": "Entry added", "entry": dict(entry)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


@website_studio_bp.route("/api/directory/<int:entry_id>", methods=["DELETE"])
@login_required
def delete_directory_entry(entry_id):
    """Delete a directory entry"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute(
            """
            SELECT user_id FROM user_directory_entries WHERE id = %s
        """,
            (entry_id,),
        )
        entry = cur.fetchone()

        if not entry:
            return jsonify({"success": False, "error": "Entry not found"}), 404

        if not is_admin_user() and entry["user_id"] != current_user.id:
            return jsonify({"success": False, "error": "Access denied"}), 403

        cur.execute("DELETE FROM user_directory_entries WHERE id = %s", (entry_id,))
        conn.commit()

        return jsonify({"success": True, "message": "Entry deleted"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


# ============================================================================
# HOSTINGER API INTEGRATION (Phase 22)
# ============================================================================

try:
    from services.hostinger_integration import get_hostinger_api

    HOSTINGER_AVAILABLE = True
except ImportError:
    HOSTINGER_AVAILABLE = False
    get_hostinger_api = None


@website_studio_bp.route("/api/hostinger/status", methods=["GET"])
@login_required
def hostinger_status():
    """Check if Hostinger API is configured"""
    if not HOSTINGER_AVAILABLE:
        return jsonify(
            {
                "success": True,
                "available": False,
                "message": "Hostinger integration not installed",
            }
        )

    api = get_hostinger_api()
    return jsonify({"success": True, "available": True, "configured": api.is_configured()})


@website_studio_bp.route("/api/hostinger/domains", methods=["GET"])
@login_required
@admin_required
def hostinger_domains():
    """List all Hostinger domains"""
    if not HOSTINGER_AVAILABLE:
        return jsonify({"success": False, "error": "Hostinger not available"}), 503

    api = get_hostinger_api()
    if not api.is_configured():
        return (
            jsonify({"success": False, "error": "Hostinger API key not configured"}),
            400,
        )

    result = api.list_domains()
    return jsonify(result)


@website_studio_bp.route("/api/hostinger/domains/<domain>/dns", methods=["GET"])
@login_required
@admin_required
def hostinger_dns_records(domain):
    """Get DNS records for a domain"""
    if not HOSTINGER_AVAILABLE:
        return jsonify({"success": False, "error": "Hostinger not available"}), 503

    api = get_hostinger_api()
    if not api.is_configured():
        return jsonify({"success": False, "error": "API key not configured"}), 400

    result = api.get_dns_records(domain)
    return jsonify(result)


@website_studio_bp.route("/api/hostinger/domains/<domain>/dns", methods=["POST"])
@login_required
@admin_required
def hostinger_add_dns(domain):
    """Add a new DNS record"""
    if not HOSTINGER_AVAILABLE:
        return jsonify({"success": False, "error": "Hostinger not available"}), 503

    api = get_hostinger_api()
    data = request.get_json()

    result = api.add_dns_record(
        domain=domain,
        record_type=data.get("type"),
        name=data.get("name"),
        value=data.get("value"),
        ttl=data.get("ttl", 3600),
        priority=data.get("priority"),
    )
    return jsonify(result)


@website_studio_bp.route("/api/hostinger/domains/<domain>/dns/<record_id>", methods=["PUT"])
@login_required
@admin_required
def hostinger_update_dns(domain, record_id):
    """Update a DNS record"""
    if not HOSTINGER_AVAILABLE:
        return jsonify({"success": False, "error": "Hostinger not available"}), 503

    api = get_hostinger_api()
    data = request.get_json()

    result = api.update_dns_record(domain=domain, record_id=record_id, value=data.get("value"), ttl=data.get("ttl"))
    return jsonify(result)


@website_studio_bp.route("/api/hostinger/domains/<domain>/dns/<record_id>", methods=["DELETE"])
@login_required
@admin_required
def hostinger_delete_dns(domain, record_id):
    """Delete a DNS record"""
    if not HOSTINGER_AVAILABLE:
        return jsonify({"success": False, "error": "Hostinger not available"}), 503

    api = get_hostinger_api()
    result = api.delete_dns_record(domain, record_id)
    return jsonify(result)


@website_studio_bp.route("/api/hostinger/domains/<domain>/preset", methods=["POST"])
@login_required
@admin_required
def hostinger_apply_preset(domain):
    """Apply a DNS preset (GitHub Pages, Vercel, Netlify)"""
    if not HOSTINGER_AVAILABLE:
        return jsonify({"success": False, "error": "Hostinger not available"}), 503

    api = get_hostinger_api()
    data = request.get_json()
    preset = data.get("preset")

    if preset == "github_pages":
        username = data.get("username", "KytranKatarn")
        result = api.set_github_pages(domain, username)
    elif preset == "vercel":
        result = api.set_vercel(domain)
    elif preset == "netlify":
        site_name = data.get("site_name")
        if not site_name:
            return (
                jsonify({"success": False, "error": "site_name required for Netlify"}),
                400,
            )
        result = api.set_netlify(domain, site_name)
    else:
        return jsonify({"success": False, "error": f"Unknown preset: {preset}"}), 400

    return jsonify(result)


# ============================================================================
# E-COMMERCE TEMPLATES
# ============================================================================

# Pre-built e-commerce page templates
ECOMMERCE_TEMPLATES = {
    "storefront_home": {
        "name": "E-Commerce Homepage",
        "description": "Modern storefront homepage with hero, featured products, and categories",
        "category": "ecommerce",
        "content": """
<section class="hero-section">
    <div class="hero-content">
        <h1>Welcome to {{store_name}}</h1>
        <p>{{store_tagline}}</p>
        <a href="/products" class="btn btn-primary">Shop Now</a>
    </div>
</section>
<section class="featured-products">
    <h2>Featured Products</h2>
    <div class="product-grid" id="featured-products">
        <!-- Products loaded dynamically -->
    </div>
</section>
<section class="categories">
    <h2>Shop by Category</h2>
    <div class="category-grid" id="category-grid">
        <!-- Categories loaded dynamically -->
    </div>
</section>
""",
    },
    "product_listing": {
        "name": "Product Listing Page",
        "description": "Product grid with filters and sorting",
        "category": "ecommerce",
        "content": """
<div class="product-page">
    <aside class="filters">
        <h3>Filters</h3>
        <div class="filter-group">
            <h4>Category</h4>
            <div id="category-filters"></div>
        </div>
        <div class="filter-group">
            <h4>Price Range</h4>
            <input type="range" id="price-range" min="0" max="1000">
        </div>
    </aside>
    <main class="products-main">
        <div class="sort-controls">
            <select id="sort-select">
                <option value="newest">Newest</option>
                <option value="price_low">Price: Low to High</option>
                <option value="price_high">Price: High to Low</option>
            </select>
        </div>
        <div class="product-grid" id="product-grid"></div>
        <div class="pagination" id="pagination"></div>
    </main>
</div>
""",
    },
    "product_detail": {
        "name": "Product Detail Page",
        "description": "Single product view with gallery, description, and add to cart",
        "category": "ecommerce",
        "content": """
<div class="product-detail">
    <div class="product-gallery" id="product-gallery"></div>
    <div class="product-info">
        <h1 id="product-name"></h1>
        <p class="price" id="product-price"></p>
        <div class="description" id="product-description"></div>
        <div class="add-to-cart">
            <input type="number" id="quantity" value="1" min="1">
            <button class="btn btn-primary" id="add-to-cart">Add to Cart</button>
        </div>
    </div>
</div>
<section class="related-products">
    <h2>You May Also Like</h2>
    <div class="product-grid" id="related-products"></div>
</section>
""",
    },
    "cart_page": {
        "name": "Shopping Cart",
        "description": "Cart page with items, quantity controls, and checkout button",
        "category": "ecommerce",
        "content": """
<div class="cart-page">
    <h1>Your Cart</h1>
    <div class="cart-items" id="cart-items">
        <!-- Cart items loaded dynamically -->
    </div>
    <div class="cart-summary">
        <div class="subtotal">
            <span>Subtotal:</span>
            <span id="cart-subtotal">$0.00</span>
        </div>
        <div class="shipping">
            <span>Shipping:</span>
            <span id="cart-shipping">Calculated at checkout</span>
        </div>
        <div class="total">
            <span>Total:</span>
            <span id="cart-total">$0.00</span>
        </div>
        <button class="btn btn-primary btn-lg" id="checkout-btn">Proceed to Checkout</button>
    </div>
</div>
""",
    },
    "checkout_page": {
        "name": "Checkout Page",
        "description": "Checkout with shipping, billing, and payment forms",
        "category": "ecommerce",
        "content": """
<div class="checkout-page">
    <h1>Checkout</h1>
    <div class="checkout-form">
        <section class="shipping-info">
            <h2>Shipping Information</h2>
            <form id="shipping-form">
                <input type="text" placeholder="Full Name" required>
                <input type="email" placeholder="Email" required>
                <input type="text" placeholder="Address" required>
                <input type="text" placeholder="City" required>
                <input type="text" placeholder="Postal Code" required>
                <select id="country" required><option>Country</option></select>
            </form>
        </section>
        <section class="payment-info">
            <h2>Payment</h2>
            <div id="payment-element">
                <!-- Stripe Elements loaded here -->
            </div>
        </section>
    </div>
    <div class="order-summary">
        <h2>Order Summary</h2>
        <div id="order-items"></div>
        <div id="order-total"></div>
        <button class="btn btn-primary btn-lg" id="place-order">Place Order</button>
    </div>
</div>
""",
    },
    "subscription_signup": {
        "name": "Subscription Signup",
        "description": "Subscription plan selection and signup page",
        "category": "ecommerce",
        "content": """
<div class="subscription-page">
    <h1>Choose Your Plan</h1>
    <p class="subtitle">Select the plan that works best for you</p>
    <div class="plans-grid">
        <div class="plan-card" data-plan="free">
            <h3>Free</h3>
            <div class="price">$0<span>/month</span></div>
            <ul class="features">
                <li>Basic features</li>
                <li>Community support</li>
            </ul>
            <button class="btn btn-outline">Get Started</button>
        </div>
        <div class="plan-card featured" data-plan="pro">
            <div class="badge">Popular</div>
            <h3>Pro</h3>
            <div class="price">$19<span>/month</span></div>
            <ul class="features">
                <li>All Free features</li>
                <li>Priority support</li>
                <li>Advanced analytics</li>
            </ul>
            <button class="btn btn-primary">Subscribe Now</button>
        </div>
        <div class="plan-card" data-plan="business">
            <h3>Business</h3>
            <div class="price">$49<span>/month</span></div>
            <ul class="features">
                <li>All Pro features</li>
                <li>Dedicated support</li>
                <li>Custom integrations</li>
            </ul>
            <button class="btn btn-outline">Contact Sales</button>
        </div>
    </div>
</div>
""",
    },
}

# ============================================================================
# BUSINESS MOCKUP TEMPLATES (WD-5)
# ============================================================================

BUSINESS_TEMPLATES = {
    "landing_modern": {
        "name": "Modern Landing Page",
        "description": "Clean, conversion-focused landing page with hero, features, and CTA",
        "category": "business",
        "files": {
            "index.html": """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{company_name}} - {{tagline}}</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <nav class="navbar">
        <div class="logo">{{company_name}}</div>
        <ul class="nav-links">
            <li><a href="#features">Features</a></li>
            <li><a href="#about">About</a></li>
            <li><a href="#contact">Contact</a></li>
            <li><a href="#" class="btn btn-primary">Get Started</a></li>
        </ul>
    </nav>

    <section class="hero">
        <div class="hero-content">
            <h1>{{headline}}</h1>
            <p>{{subheadline}}</p>
            <div class="cta-buttons">
                <a href="#" class="btn btn-primary btn-lg">Start Free Trial</a>
                <a href="#" class="btn btn-outline btn-lg">Learn More</a>
            </div>
        </div>
        <div class="hero-image">
            <img src="hero-illustration.svg" alt="Hero">
        </div>
    </section>

    <section id="features" class="features">
        <h2>Why Choose Us</h2>
        <div class="features-grid">
            <div class="feature-card">
                <div class="feature-icon">⚡</div>
                <h3>Lightning Fast</h3>
                <p>Optimized performance that keeps your users engaged.</p>
            </div>
            <div class="feature-card">
                <div class="feature-icon">🔒</div>
                <h3>Secure</h3>
                <p>Enterprise-grade security for your peace of mind.</p>
            </div>
            <div class="feature-card">
                <div class="feature-icon">📊</div>
                <h3>Analytics</h3>
                <p>Powerful insights to drive your business decisions.</p>
            </div>
        </div>
    </section>

    <section id="about" class="about">
        <h2>About {{company_name}}</h2>
        <p>{{about_text}}</p>
    </section>

    <section id="contact" class="contact">
        <h2>Get In Touch</h2>
        <form class="contact-form">
            <input type="text" placeholder="Your Name" required>
            <input type="email" placeholder="Your Email" required>
            <textarea placeholder="Your Message" rows="4" required></textarea>
            <button type="submit" class="btn btn-primary">Send Message</button>
        </form>
    </section>

    <footer>
        <p>&copy; 2026 {{company_name}}. All rights reserved.</p>
    </footer>
</body>
</html>""",
            "styles.css": """* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

:root {
    --primary: #6366f1;
    --primary-dark: #4f46e5;
    --text: #1f2937;
    --text-light: #6b7280;
    --bg: #ffffff;
    --bg-alt: #f9fafb;
}

body {
    font-family: 'Inter', -apple-system, sans-serif;
    color: var(--text);
    line-height: 1.6;
}

.navbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 5%;
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    background: var(--bg);
    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
    z-index: 100;
}

.logo {
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--primary);
}

.nav-links {
    display: flex;
    gap: 2rem;
    list-style: none;
    align-items: center;
}

.nav-links a {
    text-decoration: none;
    color: var(--text);
    transition: color 0.3s;
}

.nav-links a:hover {
    color: var(--primary);
}

.btn {
    display: inline-block;
    padding: 0.75rem 1.5rem;
    border-radius: 8px;
    text-decoration: none;
    font-weight: 500;
    transition: all 0.3s;
    border: none;
    cursor: pointer;
}

.btn-primary {
    background: var(--primary);
    color: white;
}

.btn-primary:hover {
    background: var(--primary-dark);
}

.btn-outline {
    border: 2px solid var(--primary);
    color: var(--primary);
    background: transparent;
}

.btn-lg {
    padding: 1rem 2rem;
    font-size: 1.1rem;
}

.hero {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 100vh;
    padding: 6rem 5% 4rem;
    background: linear-gradient(135deg, #f5f7ff 0%, #ffffff 100%);
}

.hero-content {
    flex: 1;
    max-width: 600px;
}

.hero h1 {
    font-size: 3.5rem;
    line-height: 1.2;
    margin-bottom: 1.5rem;
}

.hero p {
    font-size: 1.25rem;
    color: var(--text-light);
    margin-bottom: 2rem;
}

.cta-buttons {
    display: flex;
    gap: 1rem;
}

.hero-image {
    flex: 1;
    display: flex;
    justify-content: center;
}

.hero-image img {
    max-width: 100%;
    height: auto;
}

.features {
    padding: 5rem 5%;
    background: var(--bg-alt);
    text-align: center;
}

.features h2 {
    font-size: 2.5rem;
    margin-bottom: 3rem;
}

.features-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 2rem;
    max-width: 1200px;
    margin: 0 auto;
}

.feature-card {
    background: white;
    padding: 2rem;
    border-radius: 16px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.08);
}

.feature-icon {
    font-size: 3rem;
    margin-bottom: 1rem;
}

.feature-card h3 {
    margin-bottom: 0.5rem;
}

.about, .contact {
    padding: 5rem 5%;
    max-width: 800px;
    margin: 0 auto;
    text-align: center;
}

.about h2, .contact h2 {
    font-size: 2.5rem;
    margin-bottom: 1.5rem;
}

.contact-form {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    max-width: 500px;
    margin: 0 auto;
}

.contact-form input,
.contact-form textarea {
    padding: 1rem;
    border: 2px solid #e5e7eb;
    border-radius: 8px;
    font-size: 1rem;
}

footer {
    text-align: center;
    padding: 2rem;
    background: var(--text);
    color: white;
}

@media (max-width: 768px) {
    .hero {
        flex-direction: column;
        text-align: center;
    }
    .hero h1 {
        font-size: 2.5rem;
    }
    .cta-buttons {
        flex-direction: column;
    }
}""",
        },
    },
    "portfolio_creative": {
        "name": "Creative Portfolio",
        "description": "Minimalist portfolio with project showcase and about section",
        "category": "business",
        "files": {
            "index.html": """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{name}} - Portfolio</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <header>
        <nav>
            <a href="#" class="logo">{{initials}}</a>
            <ul>
                <li><a href="#work">Work</a></li>
                <li><a href="#about">About</a></li>
                <li><a href="#contact">Contact</a></li>
            </ul>
        </nav>
    </header>

    <section class="intro">
        <h1>Hello, I'm <span class="highlight">{{name}}</span></h1>
        <p>{{title}} based in {{location}}</p>
    </section>

    <section id="work" class="work">
        <h2>Selected Work</h2>
        <div class="project-grid">
            <article class="project">
                <div class="project-image"></div>
                <h3>Project One</h3>
                <p>Brand Identity, Web Design</p>
            </article>
            <article class="project">
                <div class="project-image"></div>
                <h3>Project Two</h3>
                <p>UI/UX Design, Development</p>
            </article>
            <article class="project">
                <div class="project-image"></div>
                <h3>Project Three</h3>
                <p>Mobile App, Branding</p>
            </article>
            <article class="project">
                <div class="project-image"></div>
                <h3>Project Four</h3>
                <p>Web Application</p>
            </article>
        </div>
    </section>

    <section id="about" class="about">
        <div class="about-content">
            <h2>About Me</h2>
            <p>{{bio}}</p>
            <div class="skills">
                <span>Design</span>
                <span>Development</span>
                <span>Strategy</span>
            </div>
        </div>
        <div class="about-image"></div>
    </section>

    <section id="contact" class="contact">
        <h2>Let's Work Together</h2>
        <p>{{contact_cta}}</p>
        <a href="mailto:{{email}}" class="btn">Get in Touch</a>
    </section>

    <footer>
        <div class="social-links">
            <a href="#">LinkedIn</a>
            <a href="#">Dribbble</a>
            <a href="#">Twitter</a>
        </div>
        <p>&copy; 2026 {{name}}</p>
    </footer>
</body>
</html>""",
            "styles.css": """* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

:root {
    --accent: #ff6b35;
    --dark: #0a0a0a;
    --light: #fafafa;
    --gray: #666;
}

body {
    font-family: 'DM Sans', sans-serif;
    background: var(--light);
    color: var(--dark);
}

header {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    padding: 2rem 5%;
    display: flex;
    justify-content: space-between;
    z-index: 100;
    mix-blend-mode: difference;
}

.logo {
    font-size: 1.5rem;
    font-weight: 700;
    color: white;
    text-decoration: none;
}

nav ul {
    display: flex;
    gap: 2rem;
    list-style: none;
}

nav a {
    color: white;
    text-decoration: none;
    font-weight: 500;
}

.intro {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 0 5%;
}

.intro h1 {
    font-size: 5rem;
    font-weight: 400;
    line-height: 1.1;
}

.highlight {
    color: var(--accent);
}

.intro p {
    font-size: 1.5rem;
    color: var(--gray);
    margin-top: 1rem;
}

.work {
    padding: 5rem 5%;
}

.work h2 {
    font-size: 1rem;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--gray);
    margin-bottom: 3rem;
}

.project-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 2rem;
}

.project {
    cursor: pointer;
}

.project-image {
    aspect-ratio: 4/3;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 8px;
    margin-bottom: 1rem;
    transition: transform 0.3s;
}

.project:hover .project-image {
    transform: scale(0.98);
}

.project h3 {
    font-size: 1.5rem;
    margin-bottom: 0.5rem;
}

.project p {
    color: var(--gray);
}

.about {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4rem;
    padding: 5rem 5%;
    background: var(--dark);
    color: white;
}

.about h2 {
    font-size: 1rem;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--gray);
    margin-bottom: 2rem;
}

.about p {
    font-size: 1.25rem;
    line-height: 1.8;
    margin-bottom: 2rem;
}

.skills {
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
}

.skills span {
    padding: 0.5rem 1rem;
    border: 1px solid var(--gray);
    border-radius: 100px;
    font-size: 0.875rem;
}

.about-image {
    background: linear-gradient(135deg, var(--accent) 0%, #ff8f6b 100%);
    border-radius: 8px;
}

.contact {
    padding: 8rem 5%;
    text-align: center;
}

.contact h2 {
    font-size: 3rem;
    margin-bottom: 1rem;
}

.contact p {
    color: var(--gray);
    margin-bottom: 2rem;
}

.btn {
    display: inline-block;
    padding: 1rem 2rem;
    background: var(--dark);
    color: white;
    text-decoration: none;
    border-radius: 100px;
    font-weight: 500;
    transition: transform 0.3s;
}

.btn:hover {
    transform: scale(1.05);
}

footer {
    padding: 2rem 5%;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-top: 1px solid #eee;
}

.social-links {
    display: flex;
    gap: 2rem;
}

.social-links a {
    color: var(--dark);
    text-decoration: none;
}

@media (max-width: 768px) {
    .intro h1 {
        font-size: 3rem;
    }
    .project-grid {
        grid-template-columns: 1fr;
    }
    .about {
        grid-template-columns: 1fr;
    }
}""",
        },
    },
    "agency_bold": {
        "name": "Bold Agency",
        "description": "High-impact agency site with services, team, and case studies",
        "category": "business",
        "files": {
            "index.html": """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{agency_name}} - {{tagline}}</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <nav class="nav">
        <div class="logo">{{agency_name}}</div>
        <button class="menu-toggle">Menu</button>
    </nav>

    <section class="hero">
        <h1>We create <br><span>digital experiences</span><br>that matter.</h1>
        <div class="hero-scroll">Scroll to explore</div>
    </section>

    <section class="services">
        <div class="section-header">
            <span class="label">What we do</span>
            <h2>Services</h2>
        </div>
        <div class="services-list">
            <div class="service">
                <span class="number">01</span>
                <h3>Brand Strategy</h3>
                <p>We build brands that stand out and connect with audiences.</p>
            </div>
            <div class="service">
                <span class="number">02</span>
                <h3>Web Design</h3>
                <p>Beautiful, functional websites that convert visitors.</p>
            </div>
            <div class="service">
                <span class="number">03</span>
                <h3>Development</h3>
                <p>Cutting-edge technology meets flawless execution.</p>
            </div>
            <div class="service">
                <span class="number">04</span>
                <h3>Marketing</h3>
                <p>Data-driven campaigns that deliver real results.</p>
            </div>
        </div>
    </section>

    <section class="work">
        <div class="section-header">
            <span class="label">Selected work</span>
            <h2>Case Studies</h2>
        </div>
        <div class="case-study">
            <div class="case-image"></div>
            <div class="case-info">
                <h3>Brand Transformation</h3>
                <p>How we helped Company X increase engagement by 300%</p>
                <a href="#">View Case Study →</a>
            </div>
        </div>
        <div class="case-study reverse">
            <div class="case-image"></div>
            <div class="case-info">
                <h3>E-commerce Redesign</h3>
                <p>A complete overhaul that doubled conversion rates</p>
                <a href="#">View Case Study →</a>
            </div>
        </div>
    </section>

    <section class="team">
        <div class="section-header">
            <span class="label">The team</span>
            <h2>Meet the makers</h2>
        </div>
        <div class="team-grid">
            <div class="team-member">
                <div class="member-image"></div>
                <h4>John Doe</h4>
                <p>Creative Director</p>
            </div>
            <div class="team-member">
                <div class="member-image"></div>
                <h4>Jane Smith</h4>
                <p>Lead Designer</p>
            </div>
            <div class="team-member">
                <div class="member-image"></div>
                <h4>Mike Johnson</h4>
                <p>Tech Lead</p>
            </div>
        </div>
    </section>

    <section class="cta">
        <h2>Ready to start your project?</h2>
        <a href="#" class="btn-cta">Let's Talk</a>
    </section>

    <footer>
        <div class="footer-content">
            <div class="footer-col">
                <h4>{{agency_name}}</h4>
                <p>Creating digital excellence since 2020</p>
            </div>
            <div class="footer-col">
                <h4>Contact</h4>
                <p>hello@{{domain}}</p>
                <p>{{phone}}</p>
            </div>
            <div class="footer-col">
                <h4>Follow</h4>
                <p>Instagram / Twitter / LinkedIn</p>
            </div>
        </div>
    </footer>
</body>
</html>""",
            "styles.css": """* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

:root {
    --black: #0d0d0d;
    --white: #ffffff;
    --accent: #00ff88;
    --gray: #888;
}

body {
    font-family: 'Space Grotesk', sans-serif;
    background: var(--black);
    color: var(--white);
}

.nav {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    padding: 2rem 5%;
    display: flex;
    justify-content: space-between;
    align-items: center;
    z-index: 100;
}

.logo {
    font-size: 1.25rem;
    font-weight: 700;
    letter-spacing: -1px;
}

.menu-toggle {
    background: var(--accent);
    color: var(--black);
    border: none;
    padding: 0.75rem 1.5rem;
    font-weight: 700;
    cursor: pointer;
    transition: transform 0.3s;
}

.menu-toggle:hover {
    transform: scale(1.05);
}

.hero {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 0 5%;
    position: relative;
}

.hero h1 {
    font-size: 6vw;
    font-weight: 700;
    line-height: 1.1;
    letter-spacing: -3px;
}

.hero span {
    color: var(--accent);
}

.hero-scroll {
    position: absolute;
    bottom: 3rem;
    font-size: 0.875rem;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--gray);
}

.section-header {
    margin-bottom: 4rem;
}

.label {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 3px;
    color: var(--accent);
}

.section-header h2 {
    font-size: 4rem;
    margin-top: 0.5rem;
}

.services {
    padding: 8rem 5%;
    border-top: 1px solid #222;
}

.services-list {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 4rem;
}

.service {
    padding: 2rem 0;
    border-bottom: 1px solid #222;
}

.number {
    font-size: 0.75rem;
    color: var(--accent);
}

.service h3 {
    font-size: 2rem;
    margin: 1rem 0;
}

.service p {
    color: var(--gray);
}

.work {
    padding: 8rem 5%;
}

.case-study {
    display: grid;
    grid-template-columns: 1.5fr 1fr;
    gap: 4rem;
    margin-bottom: 6rem;
    align-items: center;
}

.case-study.reverse {
    grid-template-columns: 1fr 1.5fr;
}

.case-study.reverse .case-image {
    order: 2;
}

.case-image {
    aspect-ratio: 16/10;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    border-radius: 4px;
}

.case-info h3 {
    font-size: 2.5rem;
    margin-bottom: 1rem;
}

.case-info p {
    color: var(--gray);
    margin-bottom: 2rem;
}

.case-info a {
    color: var(--accent);
    text-decoration: none;
    font-weight: 500;
}

.team {
    padding: 8rem 5%;
    background: #111;
}

.team-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 3rem;
}

.member-image {
    aspect-ratio: 3/4;
    background: linear-gradient(135deg, #333 0%, #222 100%);
    margin-bottom: 1rem;
}

.team-member h4 {
    font-size: 1.25rem;
}

.team-member p {
    color: var(--gray);
    font-size: 0.875rem;
}

.cta {
    padding: 10rem 5%;
    text-align: center;
}

.cta h2 {
    font-size: 4rem;
    margin-bottom: 3rem;
}

.btn-cta {
    display: inline-block;
    padding: 1.5rem 3rem;
    background: var(--accent);
    color: var(--black);
    text-decoration: none;
    font-size: 1.25rem;
    font-weight: 700;
    transition: transform 0.3s;
}

.btn-cta:hover {
    transform: scale(1.05);
}

footer {
    padding: 4rem 5%;
    border-top: 1px solid #222;
}

.footer-content {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr;
    gap: 4rem;
}

.footer-col h4 {
    margin-bottom: 1rem;
}

.footer-col p {
    color: var(--gray);
    font-size: 0.875rem;
    line-height: 1.8;
}

@media (max-width: 768px) {
    .hero h1 {
        font-size: 10vw;
    }
    .services-list, .team-grid {
        grid-template-columns: 1fr;
    }
    .case-study, .case-study.reverse {
        grid-template-columns: 1fr;
    }
    .case-study.reverse .case-image {
        order: 0;
    }
}""",
        },
    },
}

# ============================================================================
# APPLICATION MOCKUP TEMPLATES (WD-5)
# ============================================================================

APPLICATION_TEMPLATES = {
    "saas_landing": {
        "name": "SaaS Landing Page",
        "description": "Modern SaaS product landing with pricing and features",
        "category": "application",
        "files": {
            "index.html": """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{product_name}} - {{tagline}}</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <nav>
        <div class="logo">{{product_name}}</div>
        <ul>
            <li><a href="#features">Features</a></li>
            <li><a href="#pricing">Pricing</a></li>
            <li><a href="#" class="btn-ghost">Log in</a></li>
            <li><a href="#" class="btn-primary">Start Free</a></li>
        </ul>
    </nav>

    <header class="hero">
        <div class="badge">🚀 Now in Beta</div>
        <h1>{{headline}}</h1>
        <p>{{subheadline}}</p>
        <div class="hero-cta">
            <input type="email" placeholder="Enter your email">
            <button class="btn-primary">Get Early Access</button>
        </div>
        <p class="trust">Trusted by 1,000+ teams worldwide</p>
        <div class="logos">
            <span>Stripe</span>
            <span>Notion</span>
            <span>Linear</span>
            <span>Vercel</span>
        </div>
    </header>

    <section id="features" class="features">
        <h2>Everything you need to succeed</h2>
        <div class="features-grid">
            <div class="feature">
                <div class="icon">📊</div>
                <h3>Real-time Analytics</h3>
                <p>Get instant insights with our powerful dashboard.</p>
            </div>
            <div class="feature">
                <div class="icon">🔄</div>
                <h3>Seamless Integration</h3>
                <p>Connect with 100+ tools you already use.</p>
            </div>
            <div class="feature">
                <div class="icon">🛡️</div>
                <h3>Enterprise Security</h3>
                <p>SOC 2 compliant with end-to-end encryption.</p>
            </div>
            <div class="feature">
                <div class="icon">⚡</div>
                <h3>Lightning Fast</h3>
                <p>Sub-100ms response times, globally.</p>
            </div>
        </div>
    </section>

    <section id="pricing" class="pricing">
        <h2>Simple, transparent pricing</h2>
        <p>Start free, upgrade when you're ready</p>
        <div class="pricing-grid">
            <div class="plan">
                <h3>Starter</h3>
                <div class="price">$0<span>/month</span></div>
                <ul>
                    <li>✓ Up to 5 users</li>
                    <li>✓ Basic analytics</li>
                    <li>✓ 1GB storage</li>
                    <li>✓ Email support</li>
                </ul>
                <button class="btn-outline">Get Started</button>
            </div>
            <div class="plan featured">
                <div class="popular">Most Popular</div>
                <h3>Pro</h3>
                <div class="price">$29<span>/month</span></div>
                <ul>
                    <li>✓ Unlimited users</li>
                    <li>✓ Advanced analytics</li>
                    <li>✓ 100GB storage</li>
                    <li>✓ Priority support</li>
                    <li>✓ API access</li>
                </ul>
                <button class="btn-primary">Start Free Trial</button>
            </div>
            <div class="plan">
                <h3>Enterprise</h3>
                <div class="price">Custom</div>
                <ul>
                    <li>✓ Everything in Pro</li>
                    <li>✓ Unlimited storage</li>
                    <li>✓ Dedicated support</li>
                    <li>✓ Custom integrations</li>
                    <li>✓ SLA guarantee</li>
                </ul>
                <button class="btn-outline">Contact Sales</button>
            </div>
        </div>
    </section>

    <section class="cta-section">
        <h2>Ready to get started?</h2>
        <p>Join thousands of teams already using {{product_name}}</p>
        <button class="btn-primary btn-lg">Start Your Free Trial</button>
    </section>

    <footer>
        <div class="footer-grid">
            <div>
                <div class="logo">{{product_name}}</div>
                <p>Making work better, one team at a time.</p>
            </div>
            <div>
                <h4>Product</h4>
                <a href="#">Features</a>
                <a href="#">Pricing</a>
                <a href="#">Roadmap</a>
            </div>
            <div>
                <h4>Company</h4>
                <a href="#">About</a>
                <a href="#">Blog</a>
                <a href="#">Careers</a>
            </div>
            <div>
                <h4>Legal</h4>
                <a href="#">Privacy</a>
                <a href="#">Terms</a>
            </div>
        </div>
        <div class="footer-bottom">
            <p>&copy; 2026 {{product_name}}. All rights reserved.</p>
        </div>
    </footer>
</body>
</html>""",
            "styles.css": """* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

:root {
    --primary: #5046e5;
    --primary-light: #6366f1;
    --dark: #0f172a;
    --text: #334155;
    --light: #f8fafc;
    --border: #e2e8f0;
}

body {
    font-family: 'Inter', -apple-system, sans-serif;
    color: var(--text);
    background: var(--light);
}

nav {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1.5rem 5%;
    background: white;
    border-bottom: 1px solid var(--border);
}

.logo {
    font-size: 1.5rem;
    font-weight: 800;
    color: var(--dark);
}

nav ul {
    display: flex;
    gap: 2rem;
    list-style: none;
    align-items: center;
}

nav a {
    text-decoration: none;
    color: var(--text);
    font-weight: 500;
}

.btn-primary {
    background: var(--primary);
    color: white;
    padding: 0.75rem 1.5rem;
    border-radius: 8px;
    border: none;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.3s;
}

.btn-primary:hover {
    background: var(--primary-light);
}

.btn-outline {
    background: transparent;
    color: var(--dark);
    padding: 0.75rem 1.5rem;
    border-radius: 8px;
    border: 2px solid var(--border);
    font-weight: 600;
    cursor: pointer;
    transition: all 0.3s;
}

.btn-outline:hover {
    border-color: var(--primary);
    color: var(--primary);
}

.btn-ghost {
    color: var(--text);
}

.btn-lg {
    padding: 1rem 2rem;
    font-size: 1.1rem;
}

.hero {
    text-align: center;
    padding: 6rem 5%;
    background: white;
}

.badge {
    display: inline-block;
    padding: 0.5rem 1rem;
    background: #fef3c7;
    color: #92400e;
    border-radius: 100px;
    font-size: 0.875rem;
    font-weight: 500;
    margin-bottom: 2rem;
}

.hero h1 {
    font-size: 4rem;
    color: var(--dark);
    line-height: 1.1;
    max-width: 800px;
    margin: 0 auto 1.5rem;
}

.hero > p {
    font-size: 1.25rem;
    color: var(--text);
    max-width: 600px;
    margin: 0 auto 2rem;
}

.hero-cta {
    display: flex;
    gap: 0.5rem;
    justify-content: center;
    margin-bottom: 3rem;
}

.hero-cta input {
    padding: 0.875rem 1.25rem;
    border: 2px solid var(--border);
    border-radius: 8px;
    width: 300px;
    font-size: 1rem;
}

.trust {
    font-size: 0.875rem;
    color: #64748b;
    margin-bottom: 1rem;
}

.logos {
    display: flex;
    gap: 3rem;
    justify-content: center;
    color: #94a3b8;
    font-weight: 600;
}

.features {
    padding: 6rem 5%;
}

.features h2 {
    text-align: center;
    font-size: 2.5rem;
    color: var(--dark);
    margin-bottom: 4rem;
}

.features-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 2rem;
    max-width: 1200px;
    margin: 0 auto;
}

.feature {
    background: white;
    padding: 2rem;
    border-radius: 16px;
    border: 1px solid var(--border);
}

.icon {
    font-size: 2.5rem;
    margin-bottom: 1rem;
}

.feature h3 {
    color: var(--dark);
    margin-bottom: 0.5rem;
}

.pricing {
    padding: 6rem 5%;
    background: white;
    text-align: center;
}

.pricing h2 {
    font-size: 2.5rem;
    color: var(--dark);
    margin-bottom: 0.5rem;
}

.pricing > p {
    color: var(--text);
    margin-bottom: 4rem;
}

.pricing-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 2rem;
    max-width: 1000px;
    margin: 0 auto;
}

.plan {
    background: var(--light);
    padding: 2.5rem;
    border-radius: 16px;
    border: 2px solid var(--border);
    text-align: left;
    position: relative;
}

.plan.featured {
    background: var(--dark);
    color: white;
    border-color: var(--dark);
    transform: scale(1.05);
}

.popular {
    position: absolute;
    top: -12px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--primary);
    color: white;
    padding: 0.25rem 1rem;
    border-radius: 100px;
    font-size: 0.75rem;
    font-weight: 600;
}

.plan h3 {
    font-size: 1.25rem;
    margin-bottom: 1rem;
}

.price {
    font-size: 3rem;
    font-weight: 800;
    color: var(--dark);
    margin-bottom: 1.5rem;
}

.plan.featured .price {
    color: white;
}

.price span {
    font-size: 1rem;
    font-weight: 500;
    color: var(--text);
}

.plan.featured .price span {
    color: #94a3b8;
}

.plan ul {
    list-style: none;
    margin-bottom: 2rem;
}

.plan li {
    padding: 0.5rem 0;
    color: var(--text);
}

.plan.featured li {
    color: #cbd5e1;
}

.plan button {
    width: 100%;
}

.cta-section {
    padding: 6rem 5%;
    text-align: center;
    background: linear-gradient(135deg, var(--primary) 0%, var(--primary-light) 100%);
    color: white;
}

.cta-section h2 {
    font-size: 2.5rem;
    margin-bottom: 1rem;
}

.cta-section p {
    margin-bottom: 2rem;
    opacity: 0.9;
}

.cta-section .btn-primary {
    background: white;
    color: var(--primary);
}

footer {
    padding: 4rem 5% 2rem;
    background: var(--dark);
    color: white;
}

.footer-grid {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr 1fr;
    gap: 4rem;
    margin-bottom: 3rem;
}

.footer-grid .logo {
    color: white;
    margin-bottom: 1rem;
}

.footer-grid p {
    color: #94a3b8;
}

.footer-grid h4 {
    margin-bottom: 1rem;
}

.footer-grid a {
    display: block;
    color: #94a3b8;
    text-decoration: none;
    padding: 0.25rem 0;
}

.footer-bottom {
    text-align: center;
    padding-top: 2rem;
    border-top: 1px solid #1e293b;
    color: #64748b;
}

@media (max-width: 768px) {
    .hero h1 {
        font-size: 2.5rem;
    }
    .features-grid, .pricing-grid {
        grid-template-columns: 1fr;
    }
    .plan.featured {
        transform: none;
    }
}""",
        },
    },
    "dashboard_admin": {
        "name": "Admin Dashboard",
        "description": "Clean admin dashboard with sidebar, stats, and data tables",
        "category": "application",
        "files": {
            "index.html": """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard - {{app_name}}</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <aside class="sidebar">
        <div class="sidebar-header">
            <span class="logo">{{app_name}}</span>
        </div>
        <nav class="sidebar-nav">
            <a href="#" class="nav-item active">
                <span class="icon">📊</span> Dashboard
            </a>
            <a href="#" class="nav-item">
                <span class="icon">👥</span> Users
            </a>
            <a href="#" class="nav-item">
                <span class="icon">📦</span> Products
            </a>
            <a href="#" class="nav-item">
                <span class="icon">💳</span> Orders
            </a>
            <a href="#" class="nav-item">
                <span class="icon">📈</span> Analytics
            </a>
            <a href="#" class="nav-item">
                <span class="icon">⚙️</span> Settings
            </a>
        </nav>
        <div class="sidebar-footer">
            <div class="user-info">
                <div class="avatar">JD</div>
                <div>
                    <div class="name">John Doe</div>
                    <div class="role">Administrator</div>
                </div>
            </div>
        </div>
    </aside>

    <main class="main-content">
        <header class="header">
            <h1>Dashboard</h1>
            <div class="header-actions">
                <input type="search" placeholder="Search...">
                <button class="btn-icon">🔔</button>
                <button class="btn-primary">+ New</button>
            </div>
        </header>

        <section class="stats-grid">
            <div class="stat-card">
                <div class="stat-icon blue">👥</div>
                <div class="stat-info">
                    <span class="stat-value">12,489</span>
                    <span class="stat-label">Total Users</span>
                </div>
                <span class="stat-change positive">+12%</span>
            </div>
            <div class="stat-card">
                <div class="stat-icon green">💰</div>
                <div class="stat-info">
                    <span class="stat-value">$84,254</span>
                    <span class="stat-label">Revenue</span>
                </div>
                <span class="stat-change positive">+8%</span>
            </div>
            <div class="stat-card">
                <div class="stat-icon orange">📦</div>
                <div class="stat-info">
                    <span class="stat-value">1,249</span>
                    <span class="stat-label">Orders</span>
                </div>
                <span class="stat-change negative">-3%</span>
            </div>
            <div class="stat-card">
                <div class="stat-icon purple">⭐</div>
                <div class="stat-info">
                    <span class="stat-value">4.8</span>
                    <span class="stat-label">Rating</span>
                </div>
                <span class="stat-change positive">+0.2</span>
            </div>
        </section>

        <section class="content-grid">
            <div class="card chart-card">
                <div class="card-header">
                    <h2>Revenue Overview</h2>
                    <select>
                        <option>Last 7 days</option>
                        <option>Last 30 days</option>
                        <option>Last 90 days</option>
                    </select>
                </div>
                <div class="chart-placeholder">
                    <!-- Chart would go here -->
                    <div class="chart-bars">
                        <div class="bar" style="height: 60%"></div>
                        <div class="bar" style="height: 80%"></div>
                        <div class="bar" style="height: 45%"></div>
                        <div class="bar" style="height: 90%"></div>
                        <div class="bar" style="height: 70%"></div>
                        <div class="bar" style="height: 85%"></div>
                        <div class="bar" style="height: 65%"></div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h2>Recent Activity</h2>
                    <a href="#">View all</a>
                </div>
                <div class="activity-list">
                    <div class="activity-item">
                        <div class="activity-dot green"></div>
                        <div class="activity-content">
                            <p>New user registered</p>
                            <span>2 minutes ago</span>
                        </div>
                    </div>
                    <div class="activity-item">
                        <div class="activity-dot blue"></div>
                        <div class="activity-content">
                            <p>Order #1234 completed</p>
                            <span>15 minutes ago</span>
                        </div>
                    </div>
                    <div class="activity-item">
                        <div class="activity-dot orange"></div>
                        <div class="activity-content">
                            <p>Payment received - $150</p>
                            <span>1 hour ago</span>
                        </div>
                    </div>
                    <div class="activity-item">
                        <div class="activity-dot purple"></div>
                        <div class="activity-content">
                            <p>New review posted</p>
                            <span>3 hours ago</span>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <section class="card table-card">
            <div class="card-header">
                <h2>Recent Orders</h2>
                <button class="btn-outline">Export</button>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Order ID</th>
                        <th>Customer</th>
                        <th>Product</th>
                        <th>Amount</th>
                        <th>Status</th>
                        <th>Date</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>#ORD-001</td>
                        <td>John Smith</td>
                        <td>Premium Plan</td>
                        <td>$299.00</td>
                        <td><span class="badge success">Completed</span></td>
                        <td>Jan 20, 2026</td>
                    </tr>
                    <tr>
                        <td>#ORD-002</td>
                        <td>Sarah Johnson</td>
                        <td>Pro Plan</td>
                        <td>$149.00</td>
                        <td><span class="badge warning">Pending</span></td>
                        <td>Jan 19, 2026</td>
                    </tr>
                    <tr>
                        <td>#ORD-003</td>
                        <td>Mike Brown</td>
                        <td>Enterprise</td>
                        <td>$599.00</td>
                        <td><span class="badge success">Completed</span></td>
                        <td>Jan 18, 2026</td>
                    </tr>
                    <tr>
                        <td>#ORD-004</td>
                        <td>Emily Davis</td>
                        <td>Starter Plan</td>
                        <td>$49.00</td>
                        <td><span class="badge danger">Cancelled</span></td>
                        <td>Jan 17, 2026</td>
                    </tr>
                </tbody>
            </table>
        </section>
    </main>
</body>
</html>""",
            "styles.css": """* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

:root {
    --sidebar-width: 260px;
    --primary: #4f46e5;
    --bg: #f1f5f9;
    --card: #ffffff;
    --text: #1e293b;
    --text-light: #64748b;
    --border: #e2e8f0;
}

body {
    font-family: 'Inter', -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    display: flex;
}

.sidebar {
    width: var(--sidebar-width);
    height: 100vh;
    background: var(--card);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    position: fixed;
}

.sidebar-header {
    padding: 1.5rem;
    border-bottom: 1px solid var(--border);
}

.logo {
    font-size: 1.25rem;
    font-weight: 800;
    color: var(--primary);
}

.sidebar-nav {
    flex: 1;
    padding: 1rem 0;
}

.nav-item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.875rem 1.5rem;
    color: var(--text-light);
    text-decoration: none;
    transition: all 0.2s;
}

.nav-item:hover {
    background: var(--bg);
    color: var(--text);
}

.nav-item.active {
    background: #eef2ff;
    color: var(--primary);
    border-right: 3px solid var(--primary);
}

.icon {
    font-size: 1.25rem;
}

.sidebar-footer {
    padding: 1rem 1.5rem;
    border-top: 1px solid var(--border);
}

.user-info {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.avatar {
    width: 40px;
    height: 40px;
    background: var(--primary);
    color: white;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 600;
}

.name {
    font-weight: 600;
    font-size: 0.875rem;
}

.role {
    font-size: 0.75rem;
    color: var(--text-light);
}

.main-content {
    flex: 1;
    margin-left: var(--sidebar-width);
    padding: 2rem;
}

.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2rem;
}

.header h1 {
    font-size: 1.5rem;
}

.header-actions {
    display: flex;
    gap: 1rem;
    align-items: center;
}

.header-actions input {
    padding: 0.625rem 1rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    width: 250px;
}

.btn-icon {
    width: 40px;
    height: 40px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: white;
    cursor: pointer;
    font-size: 1.25rem;
}

.btn-primary {
    background: var(--primary);
    color: white;
    padding: 0.625rem 1rem;
    border: none;
    border-radius: 8px;
    font-weight: 500;
    cursor: pointer;
}

.btn-outline {
    background: transparent;
    color: var(--text);
    padding: 0.5rem 1rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    font-weight: 500;
    cursor: pointer;
}

.stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1.5rem;
    margin-bottom: 2rem;
}

.stat-card {
    background: var(--card);
    padding: 1.5rem;
    border-radius: 12px;
    display: flex;
    align-items: center;
    gap: 1rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.stat-icon {
    width: 48px;
    height: 48px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.5rem;
}

.stat-icon.blue { background: #dbeafe; }
.stat-icon.green { background: #dcfce7; }
.stat-icon.orange { background: #fed7aa; }
.stat-icon.purple { background: #e9d5ff; }

.stat-info {
    flex: 1;
}

.stat-value {
    display: block;
    font-size: 1.5rem;
    font-weight: 700;
}

.stat-label {
    font-size: 0.875rem;
    color: var(--text-light);
}

.stat-change {
    font-size: 0.875rem;
    font-weight: 500;
}

.stat-change.positive { color: #22c55e; }
.stat-change.negative { color: #ef4444; }

.content-grid {
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: 1.5rem;
    margin-bottom: 2rem;
}

.card {
    background: var(--card);
    border-radius: 12px;
    padding: 1.5rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
}

.card-header h2 {
    font-size: 1rem;
}

.card-header select {
    padding: 0.5rem;
    border: 1px solid var(--border);
    border-radius: 6px;
}

.card-header a {
    color: var(--primary);
    text-decoration: none;
    font-size: 0.875rem;
}

.chart-placeholder {
    height: 200px;
    display: flex;
    align-items: flex-end;
    padding: 1rem 0;
}

.chart-bars {
    display: flex;
    gap: 1rem;
    width: 100%;
    height: 100%;
    align-items: flex-end;
}

.bar {
    flex: 1;
    background: linear-gradient(180deg, var(--primary) 0%, #818cf8 100%);
    border-radius: 4px 4px 0 0;
    transition: height 0.3s;
}

.activity-list {
    display: flex;
    flex-direction: column;
    gap: 1rem;
}

.activity-item {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.activity-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
}

.activity-dot.green { background: #22c55e; }
.activity-dot.blue { background: #3b82f6; }
.activity-dot.orange { background: #f97316; }
.activity-dot.purple { background: #a855f7; }

.activity-content p {
    font-size: 0.875rem;
    margin-bottom: 0.25rem;
}

.activity-content span {
    font-size: 0.75rem;
    color: var(--text-light);
}

.table-card {
    overflow: hidden;
}

table {
    width: 100%;
    border-collapse: collapse;
}

th, td {
    text-align: left;
    padding: 1rem;
    border-bottom: 1px solid var(--border);
}

th {
    font-size: 0.75rem;
    text-transform: uppercase;
    color: var(--text-light);
    font-weight: 600;
}

td {
    font-size: 0.875rem;
}

.badge {
    padding: 0.25rem 0.75rem;
    border-radius: 100px;
    font-size: 0.75rem;
    font-weight: 500;
}

.badge.success {
    background: #dcfce7;
    color: #166534;
}

.badge.warning {
    background: #fef3c7;
    color: #92400e;
}

.badge.danger {
    background: #fee2e2;
    color: #dc2626;
}

@media (max-width: 1024px) {
    .stats-grid {
        grid-template-columns: repeat(2, 1fr);
    }
    .content-grid {
        grid-template-columns: 1fr;
    }
}""",
        },
    },
}

# Combined template registry for unified access
ALL_TEMPLATES = {
    "business": BUSINESS_TEMPLATES,
    "ecommerce": ECOMMERCE_TEMPLATES,
    "application": APPLICATION_TEMPLATES,
}


@website_studio_bp.route("/api/templates", methods=["GET"])
@login_required
def get_all_templates():
    """Get all available templates organized by category (WD-5)"""
    result = {}
    for category, templates in ALL_TEMPLATES.items():
        result[category] = []
        for key, template in templates.items():
            result[category].append(
                {
                    "id": key,
                    "name": template["name"],
                    "description": template["description"],
                    "category": category,
                    "has_files": "files" in template,
                }
            )

    return jsonify(
        {
            "success": True,
            "templates": result,
            "total_count": sum(len(t) for t in result.values()),
        }
    )


@website_studio_bp.route("/api/templates/<category>/<template_id>", methods=["GET"])
@login_required
def get_template_detail(category, template_id):
    """Get a specific template with full content (WD-5)"""
    if category not in ALL_TEMPLATES:
        return jsonify({"success": False, "error": "Invalid category"}), 404

    templates = ALL_TEMPLATES[category]
    if template_id not in templates:
        return jsonify({"success": False, "error": "Template not found"}), 404

    template = templates[template_id]
    return jsonify(
        {
            "success": True,
            "template": {"id": template_id, "category": category, **template},
        }
    )


@website_studio_bp.route("/api/projects/<int:project_id>/apply-template", methods=["POST"])
@login_required
def apply_template_to_project(project_id):
    """Apply a mockup template to a project (WD-5)"""
    data = request.get_json() or {}
    category = data.get("category")
    template_id = data.get("template_id")
    variables = data.get("variables", {})

    if not category or not template_id:
        return (
            jsonify({"success": False, "error": "Missing category or template_id"}),
            400,
        )

    if category not in ALL_TEMPLATES:
        return jsonify({"success": False, "error": "Invalid category"}), 404

    templates = ALL_TEMPLATES[category]
    if template_id not in templates:
        return jsonify({"success": False, "error": "Template not found"}), 404

    template = templates[template_id]

    # Get template files
    if "files" in template:
        files = template["files"]
    elif "content" in template:
        # Legacy e-commerce templates have single content
        files = {"index.html": template["content"]}
    else:
        return jsonify({"success": False, "error": "Template has no content"}), 400

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify project exists
        cur.execute("SELECT id FROM website_builder_projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            return jsonify({"success": False, "error": "Project not found"}), 404

        created_pages = []
        for filename, content in files.items():
            # Replace template variables
            for var, value in variables.items():
                content = content.replace("{{" + var + "}}", value)

            # Determine slug from filename
            slug = filename.replace(".html", "").replace(".css", "-css").replace(".js", "-js")
            if slug == "index":
                slug = "home"

            # Check if page exists
            cur.execute(
                """
                SELECT id FROM website_builder_pages
                WHERE project_id = %s AND slug = %s
            """,
                (project_id, slug),
            )
            existing = cur.fetchone()

            if existing:
                cur.execute(
                    """
                    UPDATE website_builder_pages
                    SET content = %s, updated_at = NOW()
                    WHERE id = %s
                """,
                    (content, existing["id"]),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO website_builder_pages (project_id, title, slug, content)
                    VALUES (%s, %s, %s, %s)
                """,
                    (project_id, filename, slug, content),
                )

            created_pages.append(filename)

        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": f'Applied template "{template["name"]}" with {len(created_pages)} files',
                "files": created_pages,
            }
        )

    except Exception as e:
        logger.error(f"Error applying template: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


@website_studio_bp.route("/api/templates/ecommerce", methods=["GET"])
@login_required
def get_ecommerce_templates():
    """Get available e-commerce page templates"""
    templates = []
    for key, template in ECOMMERCE_TEMPLATES.items():
        templates.append(
            {
                "id": key,
                "name": template["name"],
                "description": template["description"],
                "category": template["category"],
            }
        )

    return jsonify({"success": True, "templates": templates})


@website_studio_bp.route("/api/templates/ecommerce/<template_id>", methods=["GET"])
@login_required
def get_ecommerce_template(template_id):
    """Get a specific e-commerce template with content"""
    if template_id not in ECOMMERCE_TEMPLATES:
        return jsonify({"success": False, "error": "Template not found"}), 404

    template = ECOMMERCE_TEMPLATES[template_id]
    return jsonify({"success": True, "template": {"id": template_id, **template}})


@website_studio_bp.route("/api/projects/<int:project_id>/apply-store-template", methods=["POST"])
@login_required
def apply_store_template(project_id):
    """Apply e-commerce template to a project and link to store"""
    try:
        data = request.get_json()
        store_id = data.get("store_id")
        templates_to_apply = data.get(
            "templates",
            ["storefront_home", "product_listing", "product_detail", "cart_page"],
        )

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify project ownership
        cur.execute(
            "SELECT user_id, settings FROM website_builder_projects WHERE id = %s",
            (project_id,),
        )
        project = cur.fetchone()

        if not project or not can_access_resource(project["user_id"]):
            return (
                jsonify({"success": False, "error": "Project not found or access denied"}),
                404,
            )

        # Get store details if provided
        store = None
        if store_id:
            cur.execute(
                "SELECT id, name, slug, description FROM user_stores WHERE id = %s",
                (store_id,),
            )
            store = cur.fetchone()

        created_pages = []

        # Create pages from templates
        for template_id in templates_to_apply:
            if template_id not in ECOMMERCE_TEMPLATES:
                continue

            template = ECOMMERCE_TEMPLATES[template_id]

            # Replace placeholders if store info available
            content = template["content"]
            if store:
                content = content.replace("{{store_name}}", store["name"] or "Our Store")
                content = content.replace(
                    "{{store_tagline}}",
                    store["description"] or "Quality products for you",
                )

            # Determine slug
            slug_map = {
                "storefront_home": "home",
                "product_listing": "products",
                "product_detail": "product",
                "cart_page": "cart",
                "checkout_page": "checkout",
                "subscription_signup": "subscribe",
            }
            slug = slug_map.get(template_id, template_id.replace("_", "-"))

            # Check if page exists
            cur.execute(
                """
                SELECT id FROM website_builder_pages
                WHERE project_id = %s AND slug = %s
            """,
                (project_id, slug),
            )
            existing = cur.fetchone()

            if existing:
                # Update existing
                cur.execute(
                    """
                    UPDATE website_builder_pages
                    SET name = %s, html_content = %s, updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, name, slug
                """,
                    (template["name"], content, existing["id"]),
                )
            else:
                # Create new
                cur.execute(
                    """
                    INSERT INTO website_builder_pages (project_id, name, slug, html_content)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, name, slug
                """,
                    (project_id, template["name"], slug, content),
                )

            page = cur.fetchone()
            created_pages.append(dict(page))

        # Update project settings to link store
        if store_id:
            settings = project.get("settings", {}) or {}
            settings["store_id"] = store_id
            settings["ecommerce_enabled"] = True

            cur.execute(
                """
                UPDATE website_builder_projects
                SET settings = %s, updated_at = NOW()
                WHERE id = %s
            """,
                (json.dumps(settings), project_id),
            )

            # Also update store with website link
            cur.execute(
                """
                UPDATE user_stores
                SET website_id = %s, updated_at = NOW()
                WHERE id = %s
            """,
                (project_id, store_id),
            )

        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": f"Applied {len(created_pages)} e-commerce templates",
                "pages": created_pages,
                "store_linked": store_id is not None,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


@website_studio_bp.route("/api/status")
def api_status():
    """Get module status"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT COUNT(*) as count FROM website_builder_projects WHERE published = true")
        active_projects = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM website_builder_pages")
        published_pages = cur.fetchone()["count"]

        return jsonify(
            {
                "module": "website_studio",
                "status": "operational",
                "healthy": True,
                "active_projects": active_projects,
                "published_pages": published_pages,
                "ai_available": AI_AVAILABLE,
                "github_available": GITHUB_AVAILABLE,
                "hostinger_available": HOSTINGER_AVAILABLE,
                "ecommerce_templates": len(ECOMMERCE_TEMPLATES),
            }
        )

    except Exception as e:
        return (
            jsonify(
                {
                    "module": "website_studio",
                    "status": "error",
                    "healthy": False,
                    "error": str(e),
                }
            ),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)


# ============================================================================
# HEALTH CHECK
# ============================================================================


@website_studio_bp.route("/health")
def health_check():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM website_builder_projects")
        count = cur.fetchone()[0]

        return jsonify(
            {
                "healthy": True,
                "module": "website_studio",
                "ai_available": AI_AVAILABLE,
                "github_available": GITHUB_AVAILABLE,
                "hostinger_available": HOSTINGER_AVAILABLE,
                "total_projects": count,
            }
        )
    except Exception as e:
        return (
            jsonify({"healthy": False, "module": "website_studio", "error": str(e)}),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            logger.debug("DB cleanup error", exc_info=True)
