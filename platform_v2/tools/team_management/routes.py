"""DEPRECATED: Team Management routes — being migrated to agent_service + Department HQ.

API endpoints remain active for backward compatibility. HTML redirects to Department HQ.
New development should use agent_service.py and Department HQ routes.

Core CRUD, skills, and welfare endpoints now delegate to services.agent_service.
Endpoints not yet covered by agent_service (chat, discussions, contractors, routing,
ethics monitoring, performance tracking) remain as raw SQL for now.

Original migrated routes:
- /api/agents GET - Get all agents
- /api/agents/<id> GET - Get agent details
- /api/agents/<id> PUT/PATCH - Update agent profile
- /api/agents/<id>/execute POST - Execute agent task
- /api/agents/<id>/toggle POST - Toggle agent status
- /api/agents/types GET - Get agent types
- /api/agents/<id>/performance GET - Get agent performance
- /api/agents/<id>/performance/update POST - Update performance metrics
- /api/agents/performance/leaderboard GET - Get performance leaderboard
- /api/agents/<id>/performance/log POST - Log agent action
- /api/agent-directory GET - Get complete agent directory
"""

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    jsonify,
    Response,
    stream_with_context,
)
from flask_login import login_required, current_user
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from database import _get_db_password
import json
import requests
import shutil
import sys

# Import agent_service for delegated CRUD/skills/welfare operations
from services import agent_service

# Add ai_bridge to path for image generation
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
try:
    from archie_bridge import generate_image_smart, check_fooocus_health

    BRIDGE_AVAILABLE = True
except ImportError as e:
    BRIDGE_AVAILABLE = False
    print(f"Warning: archie_bridge not available for avatar generation: {e}")

team_management_bp = Blueprint("team_management", __name__, url_prefix="/tools/team-management")


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def admin_required(f):
    """Decorator to require admin access"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        if not getattr(current_user, "is_admin", False):
            flash("Admin access required", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return decorated_function


def api_admin_required(f):
    """Decorator to require admin access for API endpoints"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"success": False, "error": "Authentication required"}), 401
        if not getattr(current_user, "is_admin", False):
            return jsonify({"success": False, "error": "Admin access required"}), 403
        return f(*args, **kwargs)

    return decorated_function


@team_management_bp.route("/")
@login_required
@admin_required
def index():
    """
    Team Management — Redirects to Department HQ.

    All team management UI is now consolidated in Department HQ.
    API endpoints below remain active for backward compatibility.
    """
    return redirect("/tools/department-hq")


# ============================================================================
# AGENT MANAGEMENT ENDPOINTS - Migrated from admin/routes.py
# ============================================================================


@team_management_bp.route("/api/agents", methods=["GET"])
@login_required
@api_admin_required
def get_agents():
    """Get all agents with their capabilities and metrics - OPTIMIZED"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get query parameters for filtering and pagination
        tier = request.args.get("tier", type=int)
        department = request.args.get("department")
        worker_type = request.args.get("worker_type")
        search = request.args.get("search", "")
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 100, type=int)

        # Build WHERE clause
        where_clauses = ["a.status = 'active'"]
        params = []

        if tier:
            where_clauses.append("a.tier = %s")
            params.append(tier)

        if department:
            where_clauses.append("a.department = %s")
            params.append(department)

        if worker_type:
            where_clauses.append("a.worker_type = %s")
            params.append(worker_type)

        if search:
            where_clauses.append(
                """(
                a.first_name ILIKE %s OR
                a.last_name ILIKE %s OR
                a.email ILIKE %s OR
                a.title ILIKE %s OR
                a.department ILIKE %s
            )"""
            )
            search_pattern = f"%{search}%"
            params.extend([search_pattern] * 5)

        where_clause = " AND ".join(where_clauses)

        # Optimized query using indexes
        cur.execute(
            f"""
            SELECT
                a.*,
                at.name as type_name,
                at.icon as type_icon,
                at.category as type_category,
                (SELECT COUNT(*) FROM agent_executions
                    WHERE agent_id = a.id AND status = 'completed') as total_executions,
                (SELECT COUNT(*) FROM agent_executions
                    WHERE agent_id = a.id AND status = 'failed') as failed_executions,
                (SELECT AVG(duration_seconds) FROM agent_executions
                    WHERE agent_id = a.id AND status = 'completed') as avg_duration
            FROM agents a
            LEFT JOIN agent_types at ON a.type_id = at.id
            WHERE {where_clause}
            ORDER BY a.tier DESC, a.department, a.first_name
            LIMIT %s OFFSET %s
        """,
            params + [per_page, (page - 1) * per_page],
        )

        agents = cur.fetchall()

        # Get total count for pagination
        cur.execute(f"SELECT COUNT(*) as total FROM agents a WHERE {where_clause}", params)
        total_count = cur.fetchone()["total"]

        # Get statistics
        cur.execute(
            """
            SELECT
                COUNT(*) as total_active,
                COUNT(*) FILTER (WHERE worker_type = 'internal') as internal_count,
                COUNT(*) FILTER (WHERE worker_type = 'contract') as contract_count,
                SUM(monthly_budget) as total_budget,
                SUM(total_cost) as total_cost
            FROM agents
            WHERE status = 'active'
        """
        )
        stats = cur.fetchone()

        # Convert to list of dicts with serializable dates
        agents_list = []
        for agent in agents:
            agent_dict = dict(agent)
            if agent_dict.get("created_at"):
                agent_dict["created_at"] = agent_dict["created_at"].isoformat()
            if agent_dict.get("updated_at"):
                agent_dict["updated_at"] = agent_dict["updated_at"].isoformat()
            if agent_dict.get("last_used"):
                agent_dict["last_used"] = agent_dict["last_used"].isoformat()
            if agent_dict.get("avg_duration") is not None:
                agent_dict["avg_duration"] = float(agent_dict["avg_duration"])
            agents_list.append(agent_dict)

        return jsonify(
            {
                "success": True,
                "agents": agents_list,
                "count": len(agents_list),
                "total": total_count,
                "page": page,
                "per_page": per_page,
                "pages": (total_count + per_page - 1) // per_page,
                "statistics": {
                    "total_active": stats["total_active"],
                    "internal_count": stats["internal_count"],
                    "contract_count": stats["contract_count"],
                    "total_budget": float(stats["total_budget"] or 0),
                    "total_cost": float(stats["total_cost"] or 0),
                },
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>", methods=["GET"])
@login_required
@api_admin_required
def get_agent_details(agent_id):
    """Get detailed information about a specific agent.
    Delegates core profile to agent_service; supplements with tools & executions.
    """
    try:
        agent_dict = agent_service.get_agent(agent_id)
        if not agent_dict:
            return jsonify({"success": False, "error": "Agent not found"}), 404

        # Serialize datetimes
        for key in ("created_at", "updated_at", "last_used"):
            if agent_dict.get(key) and hasattr(agent_dict[key], "isoformat"):
                agent_dict[key] = agent_dict[key].isoformat()

        # Supplement with tools and recent executions (not in agent_service)
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT tool_name, enabled, configuration, usage_count, last_used_at
                   FROM agent_tools WHERE agent_id = %s ORDER BY tool_name""",
                (agent_id,),
            )
            tools_list = []
            for tool in cur.fetchall():
                td = dict(tool)
                if td.get("last_used_at"):
                    td["last_used_at"] = td["last_used_at"].isoformat()
                tools_list.append(td)

            cur.execute(
                """SELECT id, task_description, status, started_at, completed_at,
                          duration_seconds, tokens_used, cost
                   FROM agent_executions WHERE agent_id = %s
                   ORDER BY started_at DESC LIMIT 10""",
                (agent_id,),
            )
            executions_list = []
            for ex in cur.fetchall():
                ed = dict(ex)
                for k in ("started_at", "completed_at"):
                    if ed.get(k):
                        ed[k] = ed[k].isoformat()
                executions_list.append(ed)
        finally:
            cur.close()
            conn.close()

        return jsonify(
            {
                "success": True,
                "agent": agent_dict,
                "tools": tools_list,
                "recent_executions": executions_list,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/agents/<int:agent_id>", methods=["PUT", "PATCH"])
@login_required
@api_admin_required
def update_agent_profile(agent_id):
    """Update agent profile — delegates to agent_service.update_agent()."""
    try:
        data = request.get_json() or {}

        # Allowed editable fields (maps JSON key -> DB column)
        editable_fields = {
            "name",
            "first_name",
            "last_name",
            "email",
            "gmail",
            "phone",
            "avatar_url",
            "personality_prompt",
            "communication_style",
            "system_prompt",
            "bio",
            "title",
            "department",
            "avatar_generation_prompt",
            "model",
            "temperature",
            "tier",
            "pronouns",
            "worker_type",
            "max_tokens",
        }

        fields = {k: v for k, v in data.items() if k in editable_fields}

        # Auto-derive name from first_name + last_name when name not explicitly set
        if "name" not in data and ("first_name" in data or "last_name" in data):
            current = agent_service.get_agent(agent_id)
            if current:
                new_first = data.get("first_name", current.get("first_name") or "")
                new_last = data.get("last_name", current.get("last_name") or "")
                if new_first or new_last:
                    fields["name"] = f"{new_first} {new_last}".strip()

        if not fields:
            return jsonify({"success": False, "error": "No valid fields to update"}), 400

        updated = agent_service.update_agent(agent_id, **fields)
        if not updated:
            return jsonify({"success": False, "error": "Agent not found"}), 404

        # Return fresh agent data
        result = agent_service.get_agent(agent_id)
        if result:
            for key in ("created_at", "updated_at", "last_used"):
                if result.get(key) and hasattr(result[key], "isoformat"):
                    result[key] = result[key].isoformat()

        return jsonify(
            {
                "success": True,
                "message": "Agent profile updated successfully",
                "agent": result,
            }
        )

    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/agents/<int:agent_id>", methods=["DELETE"])
@login_required
@api_admin_required
def delete_agent_route(agent_id):
    """Permanently delete an agent — delegates to agent_service.delete_agent()."""
    try:
        agent = agent_service.get_agent(agent_id)
        if not agent:
            return jsonify({"success": False, "error": "Agent not found"}), 404

        agent_name = agent.get("name", f"#{agent_id}")

        # Null out FK references before hard delete (agent_service doesn't do this)
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE unified_projects SET created_by_agent_id = NULL WHERE created_by_agent_id = %s",
                (agent_id,),
            )
            cur.execute(
                "UPDATE unified_tasks SET assigned_agent_id = NULL WHERE assigned_agent_id = %s",
                (agent_id,),
            )
            cur.execute(
                "UPDATE unified_tasks SET created_by_agent_id = NULL WHERE created_by_agent_id = %s",
                (agent_id,),
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()

        agent_service.delete_agent(agent_id, hard=True)

        return jsonify({"success": True, "message": f"Agent '{agent_name}' deleted"})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/agents/<int:agent_id>/work-history", methods=["GET"])
@login_required
def get_agent_work_history(agent_id):
    """Get agent's work history - proposals assigned, completed, discussions"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get proposals assigned to this agent
        cur.execute(
            """
            SELECT id, title, status, category, priority,
                   proposed_at, deployed_at,
                   test_status, escalation_status
            FROM improvement_proposals
            WHERE assigned_agent_id = %s OR contractor_agent_id = %s
            ORDER BY proposed_at DESC
            LIMIT 20
        """,
            (agent_id, agent_id),
        )
        proposals = cur.fetchall()

        # Get discussions participated in
        cur.execute(
            """
            SELECT DISTINCT d.id, d.topic, d.status, d.created_at,
                   (SELECT COUNT(*) FROM agent_discussion_messages
                    WHERE discussion_id = d.id AND agent_id = %s) as message_count
            FROM agent_discussions d
            JOIN agent_discussion_messages m ON d.id = m.discussion_id
            WHERE m.agent_id = %s
            ORDER BY d.created_at DESC
            LIMIT 10
        """,
            (agent_id, agent_id),
        )
        discussions = cur.fetchall()

        # Get performance stats
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
        stats = cur.fetchone()

        # Format dates
        for p in proposals:
            if p.get("proposed_at"):
                p["proposed_at"] = p["proposed_at"].isoformat()
            if p.get("deployed_at"):
                p["deployed_at"] = p["deployed_at"].isoformat()
        for d in discussions:
            if d.get("created_at"):
                d["created_at"] = d["created_at"].isoformat()

        return jsonify(
            {
                "success": True,
                "proposals": proposals,
                "discussions": discussions,
                "stats": dict(stats) if stats else {},
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/contractor-status", methods=["GET"])
@login_required
def get_contractor_api_status(agent_id):
    """Check if contractor's external API is available and configured"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, name, worker_type, api_provider, api_enabled,
                   api_key_configured, cost_tier, model
            FROM agents WHERE id = %s
        """,
            (agent_id,),
        )
        agent = cur.fetchone()

        if not agent:
            return jsonify({"success": False, "error": "Agent not found"}), 404

        if agent["worker_type"] != "contract":
            return jsonify(
                {
                    "success": True,
                    "is_contractor": False,
                    "message": "This is an internal agent, not a contractor",
                }
            )

        # Check API provider status
        api_status = {
            "provider": agent["api_provider"],
            "enabled": agent["api_enabled"],
            "configured": agent["api_key_configured"],
            "cost_tier": agent["cost_tier"],
            "model": agent["model"],
        }

        # Try to ping the API if configured
        api_available = False
        api_message = "Not configured"

        if agent["api_key_configured"] and agent["api_enabled"]:
            try:
                import os

                provider = agent["api_provider"]

                if provider == "anthropic":
                    api_available = bool(os.getenv("ANTHROPIC_API_KEY"))
                    api_message = "Anthropic API key present" if api_available else "ANTHROPIC_API_KEY not set"
                elif provider == "openai":
                    api_available = bool(os.getenv("OPENAI_API_KEY"))
                    api_message = "OpenAI API key present" if api_available else "OPENAI_API_KEY not set"
                elif provider == "google":
                    api_available = bool(os.getenv("GOOGLE_API_KEY"))
                    api_message = "Google API key present" if api_available else "GOOGLE_API_KEY not set"
                elif provider == "x-ai":
                    api_available = bool(os.getenv("XAI_API_KEY"))
                    api_message = "X-AI API key present" if api_available else "XAI_API_KEY not set"
                else:
                    api_message = f"Unknown provider: {provider}"
            except Exception as e:
                api_message = f"Error checking API: {str(e)}"

        return jsonify(
            {
                "success": True,
                "is_contractor": True,
                "api_status": api_status,
                "api_available": api_available,
                "api_message": api_message,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/execute", methods=["POST"])
@login_required
@api_admin_required
def execute_agent(agent_id):
    """Execute a task with a specific agent"""
    try:
        from ai_bridge.archie_bridge import execute_agent_task

        data = request.get_json() or {}
        task = data.get("task", "")

        if not task:
            return jsonify({"success": False, "error": "No task provided"}), 400

        # Execute the task with the specified agent
        result = execute_agent_task(
            agent_id=agent_id,
            task=task,
            user_id=current_user.id,
            stream=data.get("stream", False),
        )

        return jsonify(result)

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/agent-chat", methods=["POST"])
@login_required
@api_admin_required
def agent_chat():
    """Chat with a specific agent via archie_bridge"""
    try:
        from ai_bridge.archie_bridge import archie_bridge

        data = request.get_json() or {}
        agent_id = data.get("agent_id")
        message = data.get("message", "")
        history = data.get("history", [])

        if not agent_id or not message:
            return (
                jsonify({"success": False, "error": "Agent ID and message required"}),
                400,
            )

        # Get agent details for context
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, name, title, bio, model, system_prompt, department
            FROM agents WHERE id = %s
        """,
            (agent_id,),
        )
        agent = cur.fetchone()

        if not agent:
            return jsonify({"success": False, "error": "Agent not found"}), 404

        # Build system prompt with agent personality
        system_prompt = (
            agent.get("system_prompt")
            or f"""You are {agent['name']}, {agent.get('title', 'an AI agent')}.
{agent.get('bio', 'You are helpful and knowledgeable.')}

Respond in character as this agent. Be helpful, professional, """
            f"""and stay true to your role in the {agent.get('department', 'team')} department."""
        )

        # Build conversation context from history
        context = ""
        if history:
            for msg in history[-6:]:  # Last 3 exchanges
                role = "User" if msg.get("role") == "user" else agent["name"]
                context += f"{role}: {msg.get('content', '')}\n"

        full_prompt = f"{context}User: {message}\n{agent['name']}:"

        # Call archie_bridge with the agent
        result = archie_bridge(
            prompt=full_prompt,
            user_id=current_user.id,
            agent_id=agent_id,
            system_prompt=system_prompt,
            enable_memory=True,
            try_local_first=True,
            task_type="agent_chat",
        )

        if result.get("success"):
            return jsonify(
                {
                    "success": True,
                    "response": result.get("response", ""),
                    "model_used": result.get("model_used", agent.get("model", "unknown")),
                    "agent_name": agent["name"],
                    "tokens_used": result.get("tokens_used", 0),
                }
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": result.get("error", "Failed to get response from agent"),
                    }
                ),
                500,
            )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================
# TEAM CHAT ENDPOINTS (Multi-Agent Discussions)
# ============================================


@team_management_bp.route("/api/discussions", methods=["GET"])
@login_required
@api_admin_required
def list_discussions():
    """List all team discussions"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT d.id, d.topic, d.description, d.status, d.started_at, d.ended_at,
                   d.discussion_type, d.consensus_reached,
                   (SELECT COUNT(*) FROM agent_discussion_messages
                    WHERE discussion_id = d.id) as message_count,
                   (SELECT array_agg(DISTINCT agent_id) FROM agent_discussion_messages
                    WHERE discussion_id = d.id) as participant_ids
            FROM agent_discussions d
            WHERE d.discussion_type = 'team_chat'
            ORDER BY d.started_at DESC
            LIMIT 50
        """
        )
        discussions = cur.fetchall()

        return jsonify({"success": True, "discussions": [dict(d) for d in discussions]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/discussions", methods=["POST"])
@login_required
@api_admin_required
def create_discussion():
    """Create a new team discussion"""
    try:
        data = request.get_json() or {}
        topic = data.get("topic", "Team Chat")
        description = data.get("description", "")

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO agent_discussions (topic, description, discussion_type, initiated_by_user, status)
            VALUES (%s, %s, 'team_chat', %s, 'active')
            RETURNING id, topic, started_at, status
        """,
            (topic, description, current_user.id),
        )

        discussion = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "discussion": dict(discussion)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/discussions/<int:discussion_id>/messages", methods=["GET"])
@login_required
@api_admin_required
def get_discussion_messages(discussion_id):
    """Get messages for a specific discussion"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT m.id, m.agent_id, m.message_type, m.message, m.confidence_score,
                   m.supporting_data, m.created_at,
                   a.name as agent_name, a.model as agent_model
            FROM agent_discussion_messages m
            LEFT JOIN agents a ON m.agent_id = a.id
            WHERE m.discussion_id = %s
            ORDER BY m.created_at ASC
        """,
            (discussion_id,),
        )

        messages = cur.fetchall()

        return jsonify({"success": True, "messages": [dict(m) for m in messages]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/team-chat", methods=["POST"])
@login_required
@api_admin_required
def team_chat():
    """Send a message to multiple agents and get their responses"""
    try:
        from ai_bridge.archie_bridge import archie_bridge

        data = request.get_json() or {}
        agent_ids = data.get("agent_ids", [])
        message = data.get("message", "")
        discussion_id = data.get("discussion_id")
        history = data.get("history", [])

        if not agent_ids or not message:
            return (
                jsonify({"success": False, "error": "Agent IDs and message required"}),
                400,
            )

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Create discussion if not provided
        if not discussion_id:
            cur.execute(
                """
                INSERT INTO agent_discussions (topic, discussion_type, initiated_by_user, status)
                VALUES ('Team Chat', 'team_chat', %s, 'active')
                RETURNING id
            """,
                (current_user.id,),
            )
            discussion_id = cur.fetchone()["id"]
            conn.commit()

        # Store user message (agent_id = NULL for user messages)
        cur.execute(
            """
            INSERT INTO agent_discussion_messages (discussion_id, agent_id, message_type, message)
            VALUES (%s, NULL, 'user', %s)
        """,
            (discussion_id, message),
        )
        conn.commit()

        # Get all requested agents
        cur.execute(
            """
            SELECT id, name, first_name, last_name, title, bio, model, system_prompt, department
            FROM agents WHERE id = ANY(%s)
        """,
            (agent_ids,),
        )
        agents = cur.fetchall()

        if not agents:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "No agents found"}), 404

        responses = []

        # Get responses from each agent
        for agent in agents:
            try:
                # Build system prompt with agent personality
                system_prompt = (
                    agent.get("system_prompt")
                    or f"""You are {agent['name']}, {agent.get('title', 'an AI agent')}.
{agent.get('bio', 'You are helpful and knowledgeable.')}

You are participating in a team discussion. Other team members may also respond.
Be collaborative, professional, and stay true to your role in the {agent.get('department', 'team')} department.
Keep responses concise (2-4 sentences) unless more detail is needed."""
                )

                # Build context from history
                context = ""
                if history:
                    for msg in history[-10:]:  # Last 5 exchanges
                        role = msg.get("sender", "User")
                        context += f"{role}: {msg.get('content', '')}\n"

                full_prompt = f"{context}User: {message}\n{agent['name']}:"

                # Call archie_bridge
                result = archie_bridge(
                    prompt=full_prompt,
                    user_id=current_user.id,
                    agent_id=agent["id"],
                    system_prompt=system_prompt,
                    enable_memory=True,
                    try_local_first=True,
                    task_type="team_chat",
                )

                response_text = (
                    result.get("response", "I apologize, I couldn't generate a response.")
                    if result.get("success")
                    else "Error getting response"
                )
                model_used = result.get("model_used", agent.get("model", "unknown"))

                # Store agent response in database
                cur.execute(
                    """
                    INSERT INTO agent_discussion_messages
                    (discussion_id, agent_id, message_type, message, supporting_data)
                    VALUES (%s, %s, 'response', %s, %s)
                """,
                    (
                        discussion_id,
                        agent["id"],
                        response_text,
                        json.dumps({"model_used": model_used}),
                    ),
                )
                conn.commit()

                agent_name = f"{agent.get('first_name', '')} {agent.get('last_name', '')}".strip() or agent["name"]

                responses.append(
                    {
                        "agent_id": agent["id"],
                        "agent_name": agent_name,
                        "title": agent.get("title", "Agent"),
                        "response": response_text,
                        "model_used": model_used,
                        "success": result.get("success", False),
                    }
                )

            except Exception as agent_error:
                responses.append(
                    {
                        "agent_id": agent["id"],
                        "agent_name": agent.get("name", "Unknown"),
                        "title": agent.get("title", "Agent"),
                        "response": f"Error: {str(agent_error)}",
                        "model_used": None,
                        "success": False,
                    }
                )

        return jsonify({"success": True, "discussion_id": discussion_id, "responses": responses})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/discussions/<int:discussion_id>/end", methods=["POST"])
@login_required
@api_admin_required
def end_discussion(discussion_id):
    """End a team discussion"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE agent_discussions
            SET status = 'completed', ended_at = NOW()
            WHERE id = %s AND status = 'active'
        """,
            (discussion_id,),
        )

        conn.commit()

        return jsonify({"success": True, "message": "Discussion ended"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/toggle", methods=["POST"])
@login_required
@api_admin_required
def toggle_agent(agent_id):
    """Toggle agent status between active and paused — delegates to agent_service."""
    try:
        agent = agent_service.get_agent(agent_id)
        if not agent:
            return jsonify({"success": False, "error": "Agent not found"}), 404

        new_status = "paused" if agent.get("status") == "active" else "active"
        agent_service.update_agent(agent_id, status=new_status)

        return jsonify({"success": True, "status": new_status})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/agents/types", methods=["GET"])
@login_required
@api_admin_required
def get_agent_types():
    """Get all available agent types"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, name, description, icon, category
            FROM agent_types
            ORDER BY name
        """
        )

        types = cur.fetchall()

        return jsonify({"success": True, "types": [dict(t) for t in types]})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# AGENT PERFORMANCE TRACKING ENDPOINTS
# ============================================================================


@team_management_bp.route("/api/agents/<int:agent_id>/performance", methods=["GET"])
@login_required
@api_admin_required
def get_agent_performance_data(agent_id):
    """Get performance data for an agent"""
    try:
        from ai_bridge.agent_performance_tracker import get_agent_performance

        performance = get_agent_performance(agent_id)

        if not performance:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Agent not found or no performance data",
                    }
                ),
                404,
            )

        return jsonify({"success": True, "performance": performance}), 200

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/agents/<int:agent_id>/performance/update", methods=["POST"])
@login_required
@api_admin_required
def update_agent_performance_metrics(agent_id):
    """Recalculate and update performance metrics for an agent"""
    try:
        from ai_bridge.agent_performance_tracker import update_agent_performance

        success = update_agent_performance(agent_id)

        if not success:
            return jsonify({"success": False, "error": "Failed to update metrics"}), 500

        return (
            jsonify(
                {
                    "success": True,
                    "message": f"Performance metrics updated for agent #{agent_id}",
                }
            ),
            200,
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/agents/performance/leaderboard", methods=["GET"])
@login_required
@api_admin_required
def get_performance_leaderboard():
    """Get performance leaderboard"""
    try:
        from ai_bridge.agent_performance_tracker import get_top_performers

        limit = request.args.get("limit", 10, type=int)

        leaderboard = get_top_performers(limit=limit)

        return jsonify({"success": True, "leaderboard": leaderboard}), 200

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/agents/<int:agent_id>/performance/log", methods=["POST"])
@login_required
@api_admin_required
def log_agent_performance_action(agent_id):
    """Log an agent action for performance tracking"""
    try:
        from ai_bridge.agent_performance_tracker import log_agent_action

        data = request.get_json()
        action_type = data.get("action_type")
        outcome = data.get("outcome")

        if not action_type or not outcome:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Missing required fields: action_type, outcome",
                    }
                ),
                400,
            )

        success = log_agent_action(
            agent_id=agent_id,
            action_type=action_type,
            outcome=outcome,
            proposal_id=data.get("proposal_id"),
            discussion_id=data.get("discussion_id"),
            task_description=data.get("task_description"),
            duration_seconds=data.get("duration_seconds"),
            quality_score=data.get("quality_score"),
            accuracy_score=data.get("accuracy_score"),
            timeliness_score=data.get("timeliness_score"),
            complexity_level=data.get("complexity_level", "moderate"),
            metadata=data.get("metadata"),
        )

        if not success:
            return jsonify({"success": False, "error": "Failed to log action"}), 500

        return jsonify({"success": True, "message": "Action logged successfully"}), 200

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# AGENT DIRECTORY ENDPOINT
# ============================================================================


@team_management_bp.route("/api/agent-directory", methods=["GET"])
@login_required
def get_agent_directory():
    """Get complete agent directory with full profiles - OPTIMIZED with new views"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Use the optimized agent_directory_view with additional personality fields from agents table
        cur.execute(
            """
            SELECT
                v.id,
                v.name,
                v.full_name,
                v.first_name,
                v.last_name,
                v.email,
                v.title,
                v.department,
                v.pronouns,
                v.bio,
                v.avatar_url,
                v.tier,
                v.model,
                v.system_prompt,
                v.capabilities,
                v.monthly_budget,
                v.total_cost,
                v.total_tokens_used,
                v.status,
                v.created_at,
                v.last_used,
                v.worker_type,
                v.agent_type,
                v.agent_category,
                v.agent_icon,
                v.budget_used_percent,
                v.activity_status,
                v.budget_status,
                a.personality_prompt,
                a.communication_style,
                a.api_provider,
                a.phone,
                a.gmail,
                a.avatar_generation_prompt
            FROM agent_directory_view v
            JOIN agents a ON v.id = a.id
            ORDER BY
                CASE WHEN v.worker_type = 'internal' THEN 0 ELSE 1 END,
                v.department,
                v.first_name,
                v.last_name
        """
        )

        agents = cur.fetchall()

        # Get summary statistics from optimized statistics view
        cur.execute("SELECT * FROM agent_statistics_view")
        stats = cur.fetchone()

        # Organize by department
        by_department = {}
        agents_list = []

        for agent in agents:
            agent_dict = dict(agent)

            # Convert dates to ISO format
            if agent_dict.get("created_at"):
                agent_dict["created_at"] = agent_dict["created_at"].isoformat()

            # Parse JSON fields if they're strings
            if isinstance(agent_dict.get("capabilities"), str):
                agent_dict["capabilities"] = json.loads(agent_dict["capabilities"])

            agents_list.append(agent_dict)

            # Organize by department
            dept = agent_dict["department"] or "Unassigned"
            if dept not in by_department:
                by_department[dept] = []
            by_department[dept].append(agent_dict)

        return jsonify(
            {
                "success": True,
                "agents": agents_list,
                "by_department": by_department,
                "statistics": dict(stats) if stats else {},
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ============================================================================
# SKILLS MANAGEMENT ENDPOINTS - Phase 17
# ============================================================================


@team_management_bp.route("/api/skills", methods=["GET"])
@login_required
@api_admin_required
def get_all_skills():
    """
    Get all unique skills and count of agents who have them.
    Supports filtering by category.
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        category = request.args.get("category")

        where_clause = ""
        params = []
        if category:
            where_clause = "WHERE skill_category = %s"
            params = [category]

        cur.execute(
            f"""
            SELECT
                skill_name,
                skill_category,
                COUNT(DISTINCT agent_id) as agent_count,
                ROUND(AVG(proficiency_level)::numeric, 1) as avg_proficiency,
                MAX(proficiency_level) as max_proficiency,
                MIN(proficiency_level) as min_proficiency
            FROM agent_skills
            {where_clause}
            GROUP BY skill_name, skill_category
            ORDER BY agent_count DESC, skill_name
        """,
            params,
        )

        skills = cur.fetchall()

        # Get total counts
        cur.execute("SELECT COUNT(DISTINCT skill_name) as total_skills FROM agent_skills")
        total_skills = cur.fetchone()["total_skills"]

        cur.execute("SELECT COUNT(DISTINCT agent_id) as agents_with_skills FROM agent_skills")
        agents_with_skills = cur.fetchone()["agents_with_skills"]

        return jsonify(
            {
                "success": True,
                "skills": [dict(s) for s in skills],
                "total_skills": total_skills,
                "agents_with_skills": agents_with_skills,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/skills/matrix", methods=["GET"])
@login_required
@api_admin_required
def get_skills_matrix():
    """
    Get skills matrix: agents x skills with proficiency levels.
    Returns a structure optimized for rendering a matrix view.
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get optional filters
        category = request.args.get("category")
        request.args.get("min_proficiency", 1, type=int)

        # Get all agents with skills
        cur.execute(
            """
            SELECT DISTINCT
                a.id,
                a.name,
                a.model,
                a.department,
                a.worker_type
            FROM agents a
            JOIN agent_skills s ON a.id = s.agent_id
            WHERE a.status = 'active'
            ORDER BY a.department, a.name
        """
        )
        agents = cur.fetchall()

        # Get top skills (most common, limited for matrix view)
        where_clause = ""
        params = []
        if category:
            where_clause = "WHERE skill_category = %s"
            params = [category]

        cur.execute(
            f"""
            SELECT skill_name, skill_category, COUNT(DISTINCT agent_id) as agent_count
            FROM agent_skills
            {where_clause}
            GROUP BY skill_name, skill_category
            ORDER BY agent_count DESC
            LIMIT 30
        """,
            params,
        )
        top_skills = cur.fetchall()

        # Build the matrix
        matrix = []
        skill_names = [s["skill_name"] for s in top_skills]

        for agent in agents:
            # Get this agent's skills
            cur.execute(
                """
                SELECT skill_name, proficiency_level
                FROM agent_skills
                WHERE agent_id = %s AND skill_name = ANY(%s)
            """,
                (agent["id"], skill_names),
            )
            agent_skills = {s["skill_name"]: s["proficiency_level"] for s in cur.fetchall()}

            row = {
                "agent_id": agent["id"],
                "agent_name": agent["name"],
                "model": agent["model"],
                "department": agent["department"],
                "worker_type": agent["worker_type"],
                "skills": {skill: agent_skills.get(skill, 0) for skill in skill_names},
            }
            matrix.append(row)

        return jsonify(
            {
                "success": True,
                "matrix": matrix,
                "skill_columns": [{"name": s["skill_name"], "category": s["skill_category"]} for s in top_skills],
                "agent_count": len(agents),
                "skill_count": len(top_skills),
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/skills", methods=["GET"])
@login_required
@api_admin_required
def get_agent_skills(agent_id):
    """Get all skills for a specific agent — delegates to agent_service.get_skills()."""
    try:
        agent = agent_service.get_agent(agent_id)
        if not agent:
            return jsonify({"success": False, "error": "Agent not found"}), 404

        skills_list = agent_service.get_skills(agent_id)

        return jsonify(
            {
                "success": True,
                "agent": {"id": agent["id"], "name": agent.get("name"), "model": agent.get("model")},
                "skills": skills_list,
                "skill_count": len(skills_list),
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/agents/<int:agent_id>/skills", methods=["POST"])
@login_required
@api_admin_required
def add_agent_skill(agent_id):
    """Add a new skill to an agent — delegates to agent_service.add_skill()."""
    try:
        agent = agent_service.get_agent(agent_id)
        if not agent:
            return jsonify({"success": False, "error": "Agent not found"}), 404

        data = request.get_json() or {}
        skill_name = data.get("skill_name")
        proficiency = data.get("proficiency_level", 3)
        category = data.get("skill_category", "general")

        if not skill_name:
            return jsonify({"success": False, "error": "skill_name is required"}), 400

        if proficiency < 1 or proficiency > 5:
            return jsonify({"success": False, "error": "proficiency_level must be 1-5"}), 400

        normalized_name = skill_name.lower().replace(" ", "_")
        agent_service.add_skill(agent_id, normalized_name, level=proficiency, category=category)

        return jsonify(
            {
                "success": True,
                "message": f'Skill "{skill_name}" added to agent',
                "skill": {
                    "skill_name": normalized_name,
                    "skill_category": category,
                    "proficiency_level": proficiency,
                },
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/agents/<int:agent_id>/skills/<skill_id>", methods=["PUT"])
@login_required
@api_admin_required
def update_agent_skill(agent_id, skill_id):
    """Update an agent's skill proficiency or category"""
    try:
        from datetime import datetime

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        data = request.get_json() or {}

        # Build update
        update_fields = []
        params = []

        if "proficiency_level" in data:
            proficiency = data["proficiency_level"]
            if proficiency < 1 or proficiency > 5:
                return (
                    jsonify({"success": False, "error": "proficiency_level must be 1-5"}),
                    400,
                )
            update_fields.append("proficiency_level = %s")
            params.append(proficiency)

        if "skill_category" in data:
            update_fields.append("skill_category = %s")
            params.append(data["skill_category"])

        if "notes" in data:
            update_fields.append("notes = %s")
            params.append(data["notes"])

        if not update_fields:
            return (
                jsonify({"success": False, "error": "No valid fields to update"}),
                400,
            )

        update_fields.append("updated_at = %s")
        params.append(datetime.now())
        params.extend([skill_id, agent_id])

        cur.execute(
            f"""
            UPDATE agent_skills
            SET {', '.join(update_fields)}
            WHERE id = %s AND agent_id = %s
            RETURNING id, skill_name, skill_category, proficiency_level, notes, updated_at
        """,
            params,
        )

        updated = cur.fetchone()

        if not updated:
            return jsonify({"success": False, "error": "Skill not found"}), 404

        conn.commit()

        skill_dict = dict(updated)
        if skill_dict.get("updated_at"):
            skill_dict["updated_at"] = skill_dict["updated_at"].isoformat()

        return jsonify({"success": True, "message": "Skill updated", "skill": skill_dict})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/skills/<skill_id>", methods=["DELETE"])
@login_required
@api_admin_required
def delete_agent_skill(agent_id, skill_id):
    """Remove a skill from an agent"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM agent_skills
            WHERE id = %s AND agent_id = %s
            RETURNING skill_name
        """,
            (skill_id, agent_id),
        )

        result = cur.fetchone()

        if not result:
            return jsonify({"success": False, "error": "Skill not found"}), 404

        conn.commit()

        return jsonify({"success": True, "message": f'Skill "{result[0]}" removed from agent'})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/skills/categories", methods=["GET"])
@login_required
@api_admin_required
def get_skill_categories():
    """Get all skill categories with their skills"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get categories from database
        cur.execute(
            """
            SELECT
                skill_category,
                COUNT(DISTINCT skill_name) as skill_count,
                COUNT(DISTINCT agent_id) as agent_count,
                ROUND(AVG(proficiency_level)::numeric, 1) as avg_proficiency
            FROM agent_skills
            GROUP BY skill_category
            ORDER BY agent_count DESC
        """
        )
        categories = cur.fetchall()

        # Also include the mapping from team_assignment_engine
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
            from team_assignment_engine import TeamAssignmentEngine

            # Get the category skills mapping
            engine = TeamAssignmentEngine(conn)
            task_categories = engine.category_skills
        except Exception:
            task_categories = {}

        return jsonify(
            {
                "success": True,
                "categories": [dict(c) for c in categories],
                "task_category_mappings": task_categories,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/skills/gaps", methods=["GET"])
@login_required
@api_admin_required
def get_skill_gaps():
    """Identify skill gaps - skills with few agents or low proficiency"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        threshold = request.args.get("threshold", 3, type=int)

        # Skills with few agents
        cur.execute(
            """
            SELECT
                skill_name,
                skill_category,
                COUNT(DISTINCT agent_id) as agent_count,
                ROUND(AVG(proficiency_level)::numeric, 1) as avg_proficiency
            FROM agent_skills
            GROUP BY skill_name, skill_category
            HAVING COUNT(DISTINCT agent_id) <= %s
            ORDER BY agent_count ASC, skill_name
        """,
            (threshold,),
        )
        low_coverage_skills = cur.fetchall()

        # Skills with low average proficiency
        cur.execute(
            """
            SELECT
                skill_name,
                skill_category,
                COUNT(DISTINCT agent_id) as agent_count,
                ROUND(AVG(proficiency_level)::numeric, 1) as avg_proficiency
            FROM agent_skills
            GROUP BY skill_name, skill_category
            HAVING AVG(proficiency_level) < 3
            ORDER BY avg_proficiency ASC
        """
        )
        low_proficiency_skills = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "low_coverage": [dict(s) for s in low_coverage_skills],
                "low_proficiency": [dict(s) for s in low_proficiency_skills],
                "coverage_threshold": threshold,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/skills/recommendations", methods=["GET"])
@login_required
@api_admin_required
def get_skill_recommendations():
    """Get recommendations for which agent to use for a task type"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        task_type = request.args.get("task_type", "")

        # Get best agents for each category
        cur.execute(
            """
            SELECT
                s.skill_category,
                a.id as agent_id,
                a.name as agent_name,
                a.model,
                a.worker_type,
                s.proficiency_level,
                s.skill_name
            FROM agent_skills s
            JOIN agents a ON s.agent_id = a.id
            WHERE a.status = 'active'
              AND s.proficiency_level >= 4
            ORDER BY s.skill_category, s.proficiency_level DESC, a.worker_type
        """
        )
        all_skilled = cur.fetchall()

        # Group by category, prefer internal agents
        recommendations = {}
        for row in all_skilled:
            cat = row["skill_category"]
            if cat not in recommendations:
                recommendations[cat] = {
                    "category": cat,
                    "top_internal": None,
                    "top_contractor": None,
                    "all_qualified": [],
                }

            agent_info = {
                "agent_id": row["agent_id"],
                "agent_name": row["agent_name"],
                "model": row["model"],
                "proficiency": row["proficiency_level"],
                "skill": row["skill_name"],
            }

            recommendations[cat]["all_qualified"].append(agent_info)

            if row["worker_type"] == "internal" and not recommendations[cat]["top_internal"]:
                recommendations[cat]["top_internal"] = agent_info
            elif row["worker_type"] == "contract" and not recommendations[cat]["top_contractor"]:
                recommendations[cat]["top_contractor"] = agent_info

        # If specific task_type requested, find best match
        best_match = None
        if task_type:
            task_lower = task_type.lower()
            cur.execute(
                """
                SELECT
                    a.id, a.name, a.model, a.worker_type,
                    s.skill_name, s.proficiency_level
                FROM agent_skills s
                JOIN agents a ON s.agent_id = a.id
                WHERE a.status = 'active'
                  AND (s.skill_name ILIKE %s OR s.skill_category ILIKE %s)
                ORDER BY s.proficiency_level DESC, a.worker_type
                LIMIT 5
            """,
                (f"%{task_lower}%", f"%{task_lower}%"),
            )
            matches = cur.fetchall()
            if matches:
                best_match = {
                    "task_type": task_type,
                    "matches": [dict(m) for m in matches],
                }

        return jsonify(
            {
                "success": True,
                "recommendations": list(recommendations.values()),
                "best_match": best_match,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/hr/dashboard", methods=["GET"])
@login_required
@api_admin_required
def get_hr_dashboard():
    """Get HR Dashboard metrics including model performance comparison"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Overall statistics
        cur.execute(
            """
            SELECT
                COUNT(*) as total_agents,
                COUNT(*) FILTER (WHERE worker_type = 'internal') as internal_agents,
                COUNT(*) FILTER (WHERE worker_type = 'contract') as contractor_agents,
                COUNT(DISTINCT model) as unique_models
            FROM agents
            WHERE status = 'active'
        """
        )
        agent_stats = cur.fetchone()

        # Skills statistics
        cur.execute(
            """
            SELECT
                COUNT(DISTINCT skill_name) as total_skills,
                COUNT(*) as total_skill_records,
                COUNT(DISTINCT agent_id) as agents_with_skills,
                COUNT(DISTINCT skill_category) as skill_categories
            FROM agent_skills
        """
        )
        skill_stats = cur.fetchone()

        # Model performance comparison
        cur.execute(
            """
            SELECT
                a.model,
                COUNT(DISTINCT a.id) as agent_count,
                COALESCE(SUM(e.task_count), 0) as total_tasks,
                COALESCE(SUM(e.completed_count), 0) as completed_tasks,
                COALESCE(SUM(e.failed_count), 0) as failed_tasks,
                CASE
                    WHEN COALESCE(SUM(e.task_count), 0) > 0
                    THEN ROUND(SUM(e.completed_count)::numeric / SUM(e.task_count) * 100, 1)
                    ELSE 0
                END as success_rate,
                ROUND(AVG(e.avg_duration)::numeric, 1) as avg_duration,
                SUM(a.total_cost) as total_cost,
                CASE WHEN a.worker_type = 'internal' THEN 'FREE' ELSE 'PAID' END as cost_type
            FROM agents a
            LEFT JOIN (
                SELECT
                    agent_id,
                    COUNT(*) as task_count,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed_count,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed_count,
                    AVG(duration_seconds) FILTER (WHERE status = 'completed') as avg_duration
                FROM agent_executions
                GROUP BY agent_id
            ) e ON a.id = e.agent_id
            WHERE a.status = 'active' AND a.model IS NOT NULL
            GROUP BY a.model, a.worker_type
            ORDER BY total_tasks DESC, success_rate DESC
        """
        )
        model_performance = cur.fetchall()

        # Skills by category distribution
        cur.execute(
            """
            SELECT
                skill_category,
                COUNT(DISTINCT skill_name) as skill_count,
                COUNT(DISTINCT agent_id) as agent_count,
                ROUND(AVG(proficiency_level)::numeric, 1) as avg_proficiency
            FROM agent_skills
            GROUP BY skill_category
            ORDER BY agent_count DESC
        """
        )
        skills_by_category = cur.fetchall()

        # Top performers (agents with highest proficiency in most skills)
        cur.execute(
            """
            SELECT
                a.id,
                a.name,
                a.model,
                a.department,
                a.worker_type,
                COUNT(s.skill_name) as skill_count,
                ROUND(AVG(s.proficiency_level)::numeric, 1) as avg_proficiency,
                SUM(s.proficiency_level) as total_proficiency_score
            FROM agents a
            JOIN agent_skills s ON a.id = s.agent_id
            WHERE a.status = 'active'
            GROUP BY a.id, a.name, a.model, a.department, a.worker_type
            ORDER BY total_proficiency_score DESC
            LIMIT 10
        """
        )
        top_performers = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "agent_statistics": dict(agent_stats),
                "skill_statistics": dict(skill_stats),
                "model_performance": [dict(m) for m in model_performance],
                "skills_by_category": [dict(c) for c in skills_by_category],
                "top_performers": [dict(p) for p in top_performers],
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# STATION ASSIGNMENT (BRIDGE INTEGRATION)
# ============================================================================

# Department to Station mapping
DEPARTMENT_STATION_MAP = {
    "Executive Leadership": "COMMAND",
    "Administration": "CONSCIOUSNESS",
    "Human Resources": "HR",
    "Compliance": "HR",
    "Engineering": "ENGINEERING",
    "Quality Assurance": "RND",
    "Infrastructure": "SECURITY",
    "Product": "ENGINEERING",
    "Finance": "OPERATIONS",
    "Sales": "OPERATIONS",
    "Operations": "OPERATIONS",
    "Customer Support": "OPERATIONS",
    "Customer Success": "AWAY_TEAM",
    "Business Development": "AWAY_TEAM",
    "Marketing": "CREATIVE",
    "Documentation": "CREATIVE",
    "Legal": "SECURITY",
    "Security": "SECURITY",
    "Healthcare": "MEDICAL",
    "Wellness": "MEDICAL",
}


@team_management_bp.route("/api/stations", methods=["GET"])
@login_required
@api_admin_required
def get_stations():
    """Get all Bridge stations with assigned agent counts"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                bs.id,
                bs.station_code,
                bs.station_name,
                bs.full_name,
                bs.description,
                bs.color,
                bs.icon,
                bs.default_llm,
                bs.modules,
                bs.position_row,
                bs.position_order,
                COUNT(sa.id) as assigned_count
            FROM bridge_stations bs
            LEFT JOIN station_assignments sa ON bs.id = sa.station_id AND sa.is_active = TRUE
            WHERE bs.is_active = TRUE
            GROUP BY bs.id
            ORDER BY bs.position_row, bs.position_order
        """
        )
        stations = cur.fetchall()

        return jsonify({"success": True, "stations": [dict(s) for s in stations]})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/assign-station", methods=["POST"])
@login_required
@api_admin_required
def assign_agent_to_station(agent_id):
    """Assign an agent to a Bridge station"""
    try:
        data = request.get_json() or {}
        station_code = data.get("station_code")
        assignment_type = data.get("assignment_type", "primary")  # primary or backup
        shift_preference = data.get("shift_preference", "any")  # morning, afternoon, night, any

        if not station_code:
            return jsonify({"success": False, "error": "station_code is required"}), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get station ID
        cur.execute(
            "SELECT id FROM bridge_stations WHERE station_code = %s AND is_active = TRUE",
            (station_code.upper(),),
        )
        station = cur.fetchone()

        if not station:
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": f"Station {station_code} not found"}),
                404,
            )

        station_id = station["id"]

        # Check if agent exists
        cur.execute("SELECT id, name FROM agents WHERE id = %s", (agent_id,))
        agent = cur.fetchone()

        if not agent:
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": f"Agent {agent_id} not found"}),
                404,
            )

        # Upsert assignment (update if exists, insert if not)
        cur.execute(
            """
            INSERT INTO station_assignments (station_id, agent_id, assignment_type, shift_preference, is_active)
            VALUES (%s, %s, %s, %s, TRUE)
            ON CONFLICT (station_id, agent_id)
            DO UPDATE SET
                assignment_type = EXCLUDED.assignment_type,
                shift_preference = EXCLUDED.shift_preference,
                is_active = TRUE,
                assigned_at = NOW()
            RETURNING id
        """,
            (station_id, agent_id, assignment_type, shift_preference),
        )

        assignment_id = cur.fetchone()["id"]
        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": f'Agent {agent["name"]} assigned to {station_code}',
                "assignment_id": assignment_id,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/assign-station", methods=["DELETE"])
@login_required
@api_admin_required
def remove_agent_from_station(agent_id):
    """Remove an agent from their station assignment"""
    try:
        station_code = request.args.get("station_code")

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if station_code:
            # Remove from specific station
            cur.execute(
                """
                UPDATE station_assignments sa
                SET is_active = FALSE
                FROM bridge_stations bs
                WHERE sa.station_id = bs.id
                  AND sa.agent_id = %s
                  AND bs.station_code = %s
            """,
                (agent_id, station_code.upper()),
            )
        else:
            # Remove from all stations
            cur.execute(
                """
                UPDATE station_assignments
                SET is_active = FALSE
                WHERE agent_id = %s
            """,
                (agent_id,),
            )

        conn.commit()

        return jsonify({"success": True, "message": f"Agent {agent_id} removed from station(s)"})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/station-roster", methods=["GET"])
@login_required
@api_admin_required
def get_station_roster():
    """Get complete station roster - all stations with their assigned agents"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                bs.station_code,
                bs.station_name,
                bs.color,
                bs.icon,
                a.id as agent_id,
                a.name as agent_name,
                a.first_name,
                a.last_name,
                a.avatar_url,
                a.department,
                a.model,
                a.worker_type,
                sa.assignment_type,
                sa.shift_preference,
                sa.assigned_at
            FROM bridge_stations bs
            LEFT JOIN station_assignments sa ON bs.id = sa.station_id AND sa.is_active = TRUE
            LEFT JOIN agents a ON sa.agent_id = a.id AND a.status = 'active'
            WHERE bs.is_active = TRUE
            ORDER BY bs.position_row, bs.position_order, sa.assignment_type, a.name
        """
        )
        rows = cur.fetchall()

        # Group by station
        roster = {}
        for row in rows:
            code = row["station_code"]
            if code not in roster:
                roster[code] = {
                    "station_code": code,
                    "station_name": row["station_name"],
                    "color": row["color"],
                    "icon": row["icon"],
                    "agents": [],
                }

            if row["agent_id"]:
                roster[code]["agents"].append(
                    {
                        "id": row["agent_id"],
                        "name": row["agent_name"],
                        "first_name": row["first_name"],
                        "last_name": row["last_name"],
                        "avatar_url": row["avatar_url"],
                        "department": row["department"],
                        "model": row["model"],
                        "worker_type": row["worker_type"],
                        "assignment_type": row["assignment_type"],
                        "shift_preference": row["shift_preference"],
                        "assigned_at": (row["assigned_at"].isoformat() if row["assigned_at"] else None),
                    }
                )

        return jsonify({"success": True, "roster": list(roster.values())})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/stations/auto-assign", methods=["POST"])
@login_required
@api_admin_required
def auto_assign_agents():
    """Auto-assign all unassigned agents to stations based on department"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get all active agents without station assignments
        cur.execute(
            """
            SELECT a.id, a.name, a.department
            FROM agents a
            LEFT JOIN station_assignments sa ON a.id = sa.agent_id AND sa.is_active = TRUE
            WHERE a.status = 'active' AND sa.id IS NULL
        """
        )
        unassigned = cur.fetchall()

        # Get station IDs
        cur.execute("SELECT id, station_code FROM bridge_stations WHERE is_active = TRUE")
        stations = {row["station_code"]: row["id"] for row in cur.fetchall()}

        assigned_count = 0
        assignments = []

        for agent in unassigned:
            dept = agent["department"] or "Operations"
            station_code = DEPARTMENT_STATION_MAP.get(dept, "OPERATIONS")
            station_id = stations.get(station_code)

            if station_id:
                cur.execute(
                    """
                    INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active)
                    VALUES (%s, %s, 'primary', TRUE)
                    ON CONFLICT (station_id, agent_id) DO NOTHING
                """,
                    (station_id, agent["id"]),
                )
                assigned_count += 1
                assignments.append(
                    {
                        "agent": agent["name"],
                        "department": dept,
                        "station": station_code,
                    }
                )

        conn.commit()

        return jsonify(
            {
                "success": True,
                "assigned_count": assigned_count,
                "assignments": assignments,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/station", methods=["GET"])
@login_required
@api_admin_required
def get_agent_station(agent_id):
    """Get the station assignment for a specific agent"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                bs.station_code,
                bs.station_name,
                bs.color,
                bs.icon,
                sa.assignment_type,
                sa.shift_preference,
                sa.assigned_at
            FROM station_assignments sa
            JOIN bridge_stations bs ON sa.station_id = bs.id
            WHERE sa.agent_id = %s AND sa.is_active = TRUE
        """,
            (agent_id,),
        )
        assignment = cur.fetchone()

        if assignment:
            return jsonify({"success": True, "assigned": True, "station": dict(assignment)})
        else:
            return jsonify({"success": True, "assigned": False, "station": None})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# HEALTH CHECK
# ============================================================================


@team_management_bp.route("/health")
def health_check():
    """Health check endpoint"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM agents WHERE status = 'active'")
        count = cur.fetchone()[0]

        return jsonify({"healthy": True, "module": "team_management", "active_agents": count})
    except Exception as e:
        return (
            jsonify({"healthy": False, "module": "team_management", "error": str(e)}),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# BRIDGE DISPATCHER ENDPOINTS - Project #91
# ============================================================================


@team_management_bp.route("/api/dispatch/status", methods=["GET"])
@login_required
@api_admin_required
def get_dispatch_status():
    """Get current BridgeDispatcher status — agents, stations, queue."""
    try:
        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from bridge_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        status = dispatcher.get_dispatch_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@team_management_bp.route("/api/dispatch/work-queue", methods=["GET"])
@login_required
@api_admin_required
def get_work_queue():
    """Get recent task_execution_log entries (work queue for Phase 5 UI)."""
    try:
        limit = request.args.get("limit", 50, type=int)
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, agent_name, module_source, task_type, capability,
                   model_used, provider, duration_ms, success, error_message,
                   station_code, created_at
            FROM task_execution_log
            ORDER BY created_at DESC
            LIMIT %s
        """,
            (limit,),
        )
        rows = cur.fetchall()
        return jsonify({"tasks": [dict(r) for r in rows], "count": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/dispatch/agent-summary", methods=["GET"])
@login_required
@api_admin_required
def get_agent_summary():
    """Get per-agent work summary from v_agent_work_summary view."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM v_agent_work_summary ORDER BY total_tasks DESC")
        rows = cur.fetchall()
        return jsonify({"agents": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/dispatch/station-summary", methods=["GET"])
@login_required
@api_admin_required
def get_station_summary():
    """Get station summary with agent counts and activity."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT bs.id, bs.station_code, bs.station_name, bs.full_name,
                   bs.color, bs.icon, bs.default_llm, bs.modules,
                   COUNT(sa.id) FILTER (WHERE sa.is_active = TRUE) AS agent_count,
                   ARRAY_AGG(a.name ORDER BY a.name) FILTER (WHERE a.name IS NOT NULL AND sa.is_active = TRUE) AS agents
            FROM bridge_stations bs
            LEFT JOIN station_assignments sa ON bs.id = sa.station_id
            LEFT JOIN agents a ON sa.agent_id = a.id AND a.status = 'active'
            WHERE bs.is_active = TRUE
            GROUP BY bs.id, bs.station_code, bs.station_name, bs.full_name,
                     bs.color, bs.icon, bs.default_llm, bs.modules
            ORDER BY bs.id
        """
        )
        rows = cur.fetchall()
        return jsonify({"stations": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# HR DAILY SUMMARY + ALERTS (Project #91 — Phase 7)
# ============================================================================


@team_management_bp.route("/api/hr/daily-summary", methods=["GET"])
@login_required
@api_admin_required
def get_hr_daily_summary():
    """Get today's agent daily summaries from agent_daily_summary."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT ads.*, a.name as agent_name, a.model,
                   bs.station_code, bs.color as station_color
            FROM agent_daily_summary ads
            JOIN agents a ON a.id = ads.agent_id
            LEFT JOIN station_assignments sa ON sa.agent_id = a.id AND sa.is_active = TRUE
            LEFT JOIN bridge_stations bs ON bs.id = sa.station_id
            WHERE ads.summary_date = CURRENT_DATE
            ORDER BY ads.total_tasks DESC
        """
        )
        rows = cur.fetchall()
        return jsonify({"success": True, "summaries": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/hr/weekly-performance", methods=["GET"])
@login_required
@api_admin_required
def get_hr_weekly_performance():
    """Get weekly agent performance from v_agent_weekly_performance view."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM v_agent_weekly_performance")
        rows = cur.fetchall()
        return jsonify({"success": True, "performance": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/hr/alerts", methods=["GET"])
@login_required
@api_admin_required
def get_hr_alerts():
    """Get active (unresolved) agent alerts."""
    try:
        include_resolved = request.args.get("include_resolved", "false") == "true"
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if include_resolved:
            cur.execute(
                """
                SELECT aa.*, a.name as agent_name, bs.station_code
                FROM agent_alerts aa
                LEFT JOIN agents a ON a.id = aa.agent_id
                LEFT JOIN station_assignments sa ON sa.agent_id = a.id AND sa.is_active = TRUE
                LEFT JOIN bridge_stations bs ON bs.id = sa.station_id
                ORDER BY aa.created_at DESC LIMIT 100
            """
            )
        else:
            cur.execute("SELECT * FROM v_active_alerts LIMIT 50")

        rows = cur.fetchall()
        return jsonify({"success": True, "alerts": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/hr/alerts/<int:alert_id>/resolve", methods=["POST"])
@login_required
@api_admin_required
def resolve_hr_alert(alert_id):
    """Resolve an agent alert."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE agent_alerts
            SET resolved = TRUE, resolved_at = NOW(), resolved_by = %s
            WHERE id = %s
        """,
            (current_user.username, alert_id),
        )
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# SHIFT SCHEDULER ENDPOINTS - Phase 28
# ============================================================================


@team_management_bp.route("/api/shifts", methods=["GET"])
@login_required
@api_admin_required
def get_shifts():
    """Get all shift definitions"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, shift_name, shift_code, start_time::text, end_time::text,
                   timezone, description, color, is_active, created_at
            FROM shift_definitions
            ORDER BY start_time
        """
        )
        shifts = cur.fetchall()

        return jsonify({"success": True, "shifts": [dict(s) for s in shifts]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/shifts", methods=["POST"])
@login_required
@api_admin_required
def create_shift():
    """Create a new shift definition"""
    try:
        data = request.get_json()
        shift_name = data.get("shift_name")
        shift_code = data.get("shift_code")
        start_time = data.get("start_time")
        end_time = data.get("end_time")
        description = data.get("description", "")
        color = data.get("color", "#00FFFF")

        if not all([shift_name, shift_code, start_time, end_time]):
            return jsonify({"success": False, "error": "Missing required fields"}), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO shift_definitions (shift_name, shift_code, start_time, end_time, description, color)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, shift_name, shift_code
        """,
            (shift_name, shift_code, start_time, end_time, description, color),
        )

        new_shift = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "shift": dict(new_shift)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/shifts/calendar", methods=["GET"])
@login_required
@api_admin_required
def get_shift_calendar():
    """Get shift calendar for the current week"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get the calendar view
        cur.execute(
            """
            SELECT * FROM v_shift_calendar_week
        """
        )
        calendar = cur.fetchall()

        return jsonify({"success": True, "calendar": [dict(c) for c in calendar]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/shifts/on-duty", methods=["GET"])
@login_required
@api_admin_required
def get_agents_on_duty():
    """Get agents currently on duty based on shift schedule"""
    try:
        station_id = request.args.get("station_id", type=int)

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Use the database function
        if station_id:
            cur.execute(
                "SELECT * FROM get_agents_on_duty(CURRENT_TIME, EXTRACT(DOW FROM CURRENT_DATE)::INTEGER, %s)",
                (station_id,),
            )
        else:
            cur.execute("SELECT * FROM get_agents_on_duty()")

        agents = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "on_duty": [dict(a) for a in agents],
                "current_time": str(request.args.get("time", "now")),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/shifts/conflicts", methods=["GET"])
@login_required
@api_admin_required
def get_shift_conflicts():
    """Get unresolved shift conflicts"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM v_unresolved_shift_conflicts")
        conflicts = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "conflicts": [dict(c) for c in conflicts],
                "count": len(conflicts),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/shifts/detect-conflicts", methods=["POST"])
@login_required
@api_admin_required
def detect_conflicts():
    """Run conflict detection"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT detect_shift_conflicts()")
        conflict_count = cur.fetchone()[0]

        conn.commit()

        return jsonify({"success": True, "conflicts_detected": conflict_count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/shifts/conflicts/<int:conflict_id>/resolve", methods=["POST"])
@login_required
@api_admin_required
def resolve_conflict(conflict_id):
    """Resolve a shift conflict"""
    try:
        data = request.get_json() or {}
        resolution_note = data.get("resolution_note", "")

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE shift_conflicts
            SET resolved = true,
                resolved_at = CURRENT_TIMESTAMP,
                resolved_by = %s,
                resolution_note = %s
            WHERE id = %s
        """,
            (
                current_user.email if hasattr(current_user, "email") else "admin",
                resolution_note,
                conflict_id,
            ),
        )

        conn.commit()

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/shifts/staffing", methods=["GET"])
@login_required
@api_admin_required
def get_staffing_summary():
    """Get station staffing summary"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM v_station_staffing")
        staffing = cur.fetchall()

        return jsonify({"success": True, "staffing": [dict(s) for s in staffing]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# Agent Shift Assignment Endpoints


@team_management_bp.route("/api/agents/<int:agent_id>/shifts", methods=["GET"])
@login_required
@api_admin_required
def get_agent_shifts(agent_id):
    """Get shift assignments for an agent"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                ash.id,
                ash.shift_id,
                sd.shift_name,
                sd.shift_code,
                sd.start_time::text,
                sd.end_time::text,
                ash.station_id,
                bs.station_name,
                ash.day_of_week,
                CASE ash.day_of_week
                    WHEN 0 THEN 'Sunday'
                    WHEN 1 THEN 'Monday'
                    WHEN 2 THEN 'Tuesday'
                    WHEN 3 THEN 'Wednesday'
                    WHEN 4 THEN 'Thursday'
                    WHEN 5 THEN 'Friday'
                    WHEN 6 THEN 'Saturday'
                    ELSE 'All Days'
                END AS day_name,
                ash.is_primary,
                ash.rotation_group,
                ash.effective_from,
                ash.effective_until,
                ash.notes
            FROM agent_shifts ash
            JOIN shift_definitions sd ON ash.shift_id = sd.id
            LEFT JOIN bridge_stations bs ON ash.station_id = bs.id
            WHERE ash.agent_id = %s
            AND ash.effective_from <= CURRENT_DATE
            AND (ash.effective_until IS NULL OR ash.effective_until >= CURRENT_DATE)
            ORDER BY sd.start_time, ash.day_of_week
        """,
            (agent_id,),
        )

        shifts = cur.fetchall()

        return jsonify({"success": True, "agent_id": agent_id, "shifts": [dict(s) for s in shifts]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/shifts", methods=["POST"])
@login_required
@api_admin_required
def assign_agent_shift(agent_id):
    """Assign an agent to a shift"""
    try:
        data = request.get_json()
        shift_id = data.get("shift_id")
        station_id = data.get("station_id")
        day_of_week = data.get("day_of_week")  # None for all days
        is_primary = data.get("is_primary", True)
        rotation_group = data.get("rotation_group")
        notes = data.get("notes", "")

        if not shift_id:
            return jsonify({"success": False, "error": "shift_id is required"}), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if assignment already exists
        cur.execute(
            """
            SELECT id FROM agent_shifts
            WHERE agent_id = %s AND shift_id = %s
            AND (day_of_week = %s OR (day_of_week IS NULL AND %s IS NULL))
            AND effective_from <= CURRENT_DATE
            AND (effective_until IS NULL OR effective_until >= CURRENT_DATE)
        """,
            (agent_id, shift_id, day_of_week, day_of_week),
        )

        existing = cur.fetchone()
        if existing:
            return (
                jsonify({"success": False, "error": "Agent already assigned to this shift"}),
                400,
            )

        cur.execute(
            """
            INSERT INTO agent_shifts (
                agent_id, shift_id, station_id, day_of_week,
                is_primary, rotation_group, notes, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                agent_id,
                shift_id,
                station_id,
                day_of_week,
                is_primary,
                rotation_group,
                notes,
                current_user.email if hasattr(current_user, "email") else "admin",
            ),
        )

        new_assignment = cur.fetchone()

        # Log the assignment
        cur.execute(
            """
            INSERT INTO shift_history (agent_id, shift_id, station_id, action, new_values, performed_by)
            VALUES (%s, %s, %s, 'assigned', %s, %s)
        """,
            (
                agent_id,
                shift_id,
                station_id,
                json.dumps(
                    {
                        "is_primary": is_primary,
                        "day_of_week": day_of_week,
                        "rotation_group": rotation_group,
                    }
                ),
                current_user.email if hasattr(current_user, "email") else "admin",
            ),
        )

        conn.commit()

        return jsonify({"success": True, "assignment_id": new_assignment["id"]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/shifts/<int:assignment_id>", methods=["DELETE"])
@login_required
@api_admin_required
def remove_agent_shift(agent_id, assignment_id):
    """Remove an agent from a shift"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get current assignment for logging
        cur.execute(
            """
            SELECT shift_id, station_id, is_primary, day_of_week
            FROM agent_shifts WHERE id = %s AND agent_id = %s
        """,
            (assignment_id, agent_id),
        )
        assignment = cur.fetchone()

        if not assignment:
            return jsonify({"success": False, "error": "Assignment not found"}), 404

        # Set effective_until to today (soft delete)
        cur.execute(
            """
            UPDATE agent_shifts
            SET effective_until = CURRENT_DATE
            WHERE id = %s AND agent_id = %s
        """,
            (assignment_id, agent_id),
        )

        # Log the removal
        cur.execute(
            """
            INSERT INTO shift_history (agent_id, shift_id, station_id, action, old_values, performed_by)
            VALUES (%s, %s, %s, 'removed', %s, %s)
        """,
            (
                agent_id,
                assignment["shift_id"],
                assignment["station_id"],
                json.dumps(dict(assignment)),
                current_user.email if hasattr(current_user, "email") else "admin",
            ),
        )

        conn.commit()

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# Rotation Management Endpoints


@team_management_bp.route("/api/rotations", methods=["GET"])
@login_required
@api_admin_required
def get_rotations():
    """Get all rotation schedules"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                sr.id,
                sr.rotation_name,
                sr.station_id,
                bs.station_name,
                sr.rotation_pattern,
                sr.rotation_interval_days,
                sr.current_position,
                sr.last_rotated_at,
                sr.next_rotation_at,
                sr.is_active,
                sr.auto_rotate
            FROM shift_rotations sr
            LEFT JOIN bridge_stations bs ON sr.station_id = bs.id
            ORDER BY bs.station_name, sr.rotation_name
        """
        )
        rotations = cur.fetchall()

        return jsonify({"success": True, "rotations": [dict(r) for r in rotations]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/rotations", methods=["POST"])
@login_required
@api_admin_required
def create_rotation():
    """Create a new rotation schedule"""
    try:
        data = request.get_json()
        rotation_name = data.get("rotation_name")
        station_id = data.get("station_id")
        rotation_pattern = data.get("rotation_pattern", ["Group A", "Group B"])
        rotation_interval_days = data.get("rotation_interval_days", 7)
        auto_rotate = data.get("auto_rotate", True)

        if not rotation_name:
            return (
                jsonify({"success": False, "error": "rotation_name is required"}),
                400,
            )

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO shift_rotations (
                rotation_name, station_id, rotation_pattern,
                rotation_interval_days, auto_rotate, next_rotation_at)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP + (%s || ' days')::INTERVAL)
            RETURNING id, rotation_name
        """,
            (
                rotation_name,
                station_id,
                json.dumps(rotation_pattern),
                rotation_interval_days,
                auto_rotate,
                rotation_interval_days,
            ),
        )

        new_rotation = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "rotation": dict(new_rotation)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/rotations/<int:rotation_id>/advance", methods=["POST"])
@login_required
@api_admin_required
def advance_rotation(rotation_id):
    """Advance a rotation to the next position"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT advance_shift_rotation(%s)", (rotation_id,))
        success = cur.fetchone()[0]

        conn.commit()

        if success:
            return jsonify({"success": True, "message": "Rotation advanced"})
        else:
            return (
                jsonify({"success": False, "error": "Rotation not found or inactive"}),
                404,
            )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# Bulk Operations


@team_management_bp.route("/api/agents/bulk-deactivate", methods=["POST"])
@login_required
@api_admin_required
def bulk_deactivate_agents():
    """Bulk deactivate agents (soft delete)"""
    try:
        data = request.get_json()
        agent_ids = data.get("agent_ids", [])

        if not agent_ids:
            return jsonify({"success": False, "error": "No agent IDs provided"}), 400

        # Single-writer path: bulk deactivate via agent_service.delete_agent
        # (soft-delete sets status=inactive, shift_state=off_duty) so every
        # agents-table mutation flows through the canonical helper
        # (Project #241 Track C.2). Slightly slower than the old ANY(%s)
        # bulk UPDATE but preserves the only-active-agents filter.
        deactivated_ids = []
        for aid in agent_ids:
            existing = agent_service.get_agent(aid)
            if existing and existing.get("status") == "active":
                agent_service.delete_agent(aid)
                deactivated_ids.append(aid)

        return jsonify(
            {
                "success": True,
                "deactivated_count": len(deactivated_ids),
                "deactivated_ids": deactivated_ids,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/bulk-assign-shifts", methods=["POST"])
@login_required
@api_admin_required
def bulk_assign_shifts():
    """Bulk assign agents to shifts based on department"""
    try:
        data = request.get_json()
        department = data.get("department")
        shift_id = data.get("shift_id")
        station_id = data.get("station_id")

        if not shift_id:
            return jsonify({"success": False, "error": "shift_id is required"}), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get agents in department (or all active agents if no department)
        if department:
            cur.execute(
                """
                SELECT id FROM agents
                WHERE department = %s AND status = 'active'
            """,
                (department,),
            )
        else:
            cur.execute(
                """
                SELECT id FROM agents WHERE status = 'active'
            """
            )

        agents = cur.fetchall()
        assigned_count = 0

        for agent in agents:
            # Check if already assigned
            cur.execute(
                """
                SELECT id FROM agent_shifts
                WHERE agent_id = %s AND shift_id = %s
                AND effective_from <= CURRENT_DATE
                AND (effective_until IS NULL OR effective_until >= CURRENT_DATE)
            """,
                (agent["id"], shift_id),
            )

            if not cur.fetchone():
                cur.execute(
                    """
                    INSERT INTO agent_shifts (agent_id, shift_id, station_id, is_primary, created_by)
                    VALUES (%s, %s, %s, true, %s)
                """,
                    (
                        agent["id"],
                        shift_id,
                        station_id,
                        (current_user.email if hasattr(current_user, "email") else "admin"),
                    ),
                )
                assigned_count += 1

        conn.commit()

        return jsonify(
            {
                "success": True,
                "assigned_count": assigned_count,
                "total_agents": len(agents),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# TASK ASSIGNMENT SYSTEM (Phase 6.5 - SaaS Team Delegation)
# ============================================================================


@team_management_bp.route("/api/tasks", methods=["GET"])
@login_required
@api_admin_required
def get_task_assignments():
    """Get all task assignments with filtering"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get filter parameters
        agent_id = request.args.get("agent_id", type=int)
        module_id = request.args.get("module_id")
        status = request.args.get("status")
        priority = request.args.get("priority")
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)

        query = """
            SELECT t.*,
                   a.name as agent_name, a.avatar_url as agent_avatar,
                   u1.username as assigned_by_name,
                   u2.username as on_behalf_of_name
            FROM agent_task_assignments t
            LEFT JOIN agents a ON t.agent_id = a.id
            LEFT JOIN users u1 ON t.assigned_by = u1.id
            LEFT JOIN users u2 ON t.on_behalf_of = u2.id
            WHERE 1=1
        """
        params = []

        if agent_id:
            query += " AND t.agent_id = %s"
            params.append(agent_id)
        if module_id:
            query += " AND t.module_id = %s"
            params.append(module_id)
        if status:
            query += " AND t.status = %s"
            params.append(status)
        if priority:
            query += " AND t.priority = %s"
            params.append(priority)

        query += " ORDER BY t.created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(query, params)
        tasks = cur.fetchall()

        # Get total count
        cur.execute("SELECT COUNT(*) as count FROM agent_task_assignments")
        total = cur.fetchone()["count"]

        return jsonify({"success": True, "tasks": [dict(t) for t in tasks], "total": total})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/tasks", methods=["POST"])
@login_required
@api_admin_required
def create_task_assignment():
    """Create a new task assignment for an agent"""
    try:
        data = request.get_json()

        title = data.get("title", "").strip()
        description = data.get("description", "")
        agent_id = data.get("agent_id")
        module_id = data.get("module_id")
        module_route = data.get("module_route", "")
        priority = data.get("priority", "normal")
        task_type = data.get("task_type", "execute")
        instructions = data.get("instructions", "")
        context = data.get("context", {})
        due_date = data.get("due_date")
        on_behalf_of = data.get("on_behalf_of")
        estimated_minutes = data.get("estimated_minutes")

        if not title or not agent_id:
            return (
                jsonify({"success": False, "error": "Title and agent_id are required"}),
                400,
            )

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO agent_task_assignments
            (title, description, agent_id, module_id, module_route, priority,
             task_type, instructions, context, due_date, on_behalf_of,
             estimated_minutes, assigned_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                title,
                description,
                agent_id,
                module_id,
                module_route,
                priority,
                task_type,
                instructions,
                json.dumps(context),
                due_date,
                on_behalf_of,
                estimated_minutes,
                current_user.id,
            ),
        )

        task_id = cur.fetchone()["id"]

        # Log the assignment
        cur.execute(
            """
            INSERT INTO agent_task_log (task_id, agent_id, action, message)
            VALUES (%s, %s, 'created', 'Task assigned by admin')
        """,
            (task_id, agent_id),
        )

        conn.commit()

        return jsonify(
            {
                "success": True,
                "task_id": task_id,
                "message": "Task assigned successfully",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/tasks/<int:task_id>", methods=["GET"])
@login_required
@api_admin_required
def get_task_assignment(task_id):
    """Get a specific task assignment with full details"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT t.*,
                   a.name as agent_name, a.avatar_url as agent_avatar,
                   a.title as agent_title, a.department as agent_department,
                   u1.username as assigned_by_name,
                   u2.username as on_behalf_of_name
            FROM agent_task_assignments t
            LEFT JOIN agents a ON t.agent_id = a.id
            LEFT JOIN users u1 ON t.assigned_by = u1.id
            LEFT JOIN users u2 ON t.on_behalf_of = u2.id
            WHERE t.id = %s
        """,
            (task_id,),
        )
        task = cur.fetchone()

        if not task:
            return jsonify({"success": False, "error": "Task not found"}), 404

        # Get task log
        cur.execute(
            """
            SELECT * FROM agent_task_log
            WHERE task_id = %s
            ORDER BY created_at DESC
        """,
            (task_id,),
        )
        logs = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "task": dict(task),
                "logs": [dict(row) for row in logs],
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/tasks/<int:task_id>", methods=["PUT"])
@login_required
@api_admin_required
def update_task_assignment(task_id):
    """Update a task assignment"""
    try:
        data = request.get_json()

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build update query
        updates = []
        params = []

        for field in [
            "title",
            "description",
            "priority",
            "status",
            "instructions",
            "due_date",
        ]:
            if field in data:
                updates.append(f"{field} = %s")
                params.append(data[field])

        if "context" in data:
            updates.append("context = %s")
            params.append(json.dumps(data["context"]))

        if not updates:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        updates.append("updated_at = NOW()")
        params.append(task_id)

        cur.execute(
            f"""
            UPDATE agent_task_assignments
            SET {', '.join(updates)}
            WHERE id = %s
        """,
            params,
        )

        # Log the update
        cur.execute(
            """
            INSERT INTO agent_task_log (task_id, agent_id, action, message, details)
            SELECT id, agent_id, 'updated', 'Task updated by admin', %s
            FROM agent_task_assignments WHERE id = %s
        """,
            (json.dumps(data), task_id),
        )

        conn.commit()

        return jsonify({"success": True, "message": "Task updated"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/tasks/<int:task_id>/start", methods=["POST"])
@login_required
@api_admin_required
def start_task(task_id):
    """Start executing a task"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE agent_task_assignments
            SET status = 'in_progress', started_at = NOW(), updated_at = NOW()
            WHERE id = %s
            RETURNING agent_id
        """,
            (task_id,),
        )
        result = cur.fetchone()

        if not result:
            return jsonify({"success": False, "error": "Task not found"}), 404

        # Log
        cur.execute(
            """
            INSERT INTO agent_task_log (task_id, agent_id, action, message)
            VALUES (%s, %s, 'started', 'Task execution started')
        """,
            (task_id, result["agent_id"]),
        )

        conn.commit()

        return jsonify({"success": True, "message": "Task started"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/tasks/<int:task_id>/complete", methods=["POST"])
@login_required
@api_admin_required
def complete_task(task_id):
    """Mark a task as complete"""
    try:
        data = request.get_json() or {}
        result = data.get("result", {})
        output_summary = data.get("output_summary", "")
        tokens_used = data.get("tokens_used", 0)
        cost = data.get("cost", 0)

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Calculate actual duration
        cur.execute(
            """
            UPDATE agent_task_assignments
            SET status = 'completed',
                completed_at = NOW(),
                result = %s,
                output_summary = %s,
                tokens_used = %s,
                cost = %s,
                actual_minutes = EXTRACT(EPOCH FROM (NOW() - started_at)) / 60,
                updated_at = NOW()
            WHERE id = %s
            RETURNING agent_id
        """,
            (json.dumps(result), output_summary, tokens_used, cost, task_id),
        )
        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Task not found"}), 404

        # Log
        cur.execute(
            """
            INSERT INTO agent_task_log (task_id, agent_id, action, message, tokens_used)
            VALUES (%s, %s, 'completed', 'Task completed successfully', %s)
        """,
            (task_id, row["agent_id"], tokens_used),
        )

        conn.commit()

        return jsonify({"success": True, "message": "Task completed"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/tasks/<int:task_id>/execute", methods=["POST"])
@login_required
@api_admin_required
def execute_task_with_agent(task_id):
    """Execute a task using the assigned agent"""
    try:
        from ai_bridge.archie_bridge import execute_agent_task

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get task details
        cur.execute(
            """
            SELECT t.*, a.name as agent_name, a.model, a.system_prompt, a.temperature
            FROM agent_task_assignments t
            JOIN agents a ON t.agent_id = a.id
            WHERE t.id = %s
        """,
            (task_id,),
        )
        task = cur.fetchone()

        if not task:
            return jsonify({"success": False, "error": "Task not found"}), 404

        # Update status to in_progress
        cur.execute(
            """
            UPDATE agent_task_assignments
            SET status = 'in_progress', started_at = NOW()
            WHERE id = %s
        """,
            (task_id,),
        )

        # Build task prompt with context
        prompt = f"""You are {task['agent_name']} working on the following task:

**Task:** {task['title']}
**Description:** {task['description'] or 'No description provided'}
**Module:** {task['module_id'] or 'General'}
**Priority:** {task['priority']}

**Instructions:**
{task['instructions'] or 'Complete the task as described.'}

**Context:**
{json.dumps(task['context'], indent=2) if task['context'] else 'No additional context.'}

Please complete this task and provide a clear summary of what you accomplished."""

        # Execute with the agent
        result = execute_agent_task(agent_id=task["agent_id"], task=prompt, context=task["context"] or {})

        # Update task with result
        cur.execute(
            """
            UPDATE agent_task_assignments
            SET status = 'completed',
                completed_at = NOW(),
                result = %s,
                output_summary = %s,
                tokens_used = %s,
                cost = %s,
                actual_minutes = EXTRACT(EPOCH FROM (NOW() - started_at)) / 60,
                updated_at = NOW()
            WHERE id = %s
        """,
            (
                json.dumps(result.get("result", {})),
                result.get("response", "")[:500],
                result.get("tokens_used", 0),
                result.get("cost", 0),
                task_id,
            ),
        )

        # Log execution
        cur.execute(
            """
            INSERT INTO agent_task_log (task_id, agent_id, action, message, tokens_used)
            VALUES (%s, %s, 'executed', 'Task executed via AI agent', %s)
        """,
            (task_id, task["agent_id"], result.get("tokens_used", 0)),
        )

        conn.commit()

        return jsonify({"success": True, "message": "Task executed successfully", "result": result})
    except Exception as e:
        # Mark task as failed
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE agent_task_assignments
                SET status = 'failed', updated_at = NOW()
                WHERE id = %s
            """,
                (task_id,),
            )
            cur.execute(
                """
                INSERT INTO agent_task_log (task_id, agent_id, action, message, details)
                SELECT id, agent_id, 'failed', 'Task execution failed', %s
                FROM agent_task_assignments WHERE id = %s
            """,
                (json.dumps({"error": str(e)}), task_id),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/tasks/templates", methods=["GET"])
@login_required
@api_admin_required
def get_task_templates():
    """Get task templates"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        module_id = request.args.get("module_id")

        query = "SELECT * FROM agent_task_templates"
        params = []

        if module_id:
            query += " WHERE module_id = %s"
            params.append(module_id)

        query += " ORDER BY use_count DESC, name"

        cur.execute(query, params)
        templates = cur.fetchall()

        return jsonify({"success": True, "templates": [dict(t) for t in templates]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/tasks/stats", methods=["GET"])
@login_required
@api_admin_required
def get_task_stats():
    """Get task assignment statistics"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Overall stats
        cur.execute(
            """
            SELECT
                COUNT(*) as total_tasks,
                COUNT(*) FILTER (WHERE status = 'pending') as pending,
                COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress,
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                COALESCE(SUM(tokens_used), 0) as total_tokens,
                COALESCE(SUM(cost), 0) as total_cost
            FROM agent_task_assignments
        """
        )
        overall = cur.fetchone()

        # By agent
        cur.execute(
            """
            SELECT a.name, a.avatar_url,
                   COUNT(t.id) as tasks,
                   COUNT(t.id) FILTER (WHERE t.status = 'completed') as completed
            FROM agents a
            LEFT JOIN agent_task_assignments t ON a.id = t.agent_id
            GROUP BY a.id, a.name, a.avatar_url
            HAVING COUNT(t.id) > 0
            ORDER BY tasks DESC
            LIMIT 10
        """
        )
        by_agent = cur.fetchall()

        # By module
        cur.execute(
            """
            SELECT module_id, COUNT(*) as tasks,
                   COUNT(*) FILTER (WHERE status = 'completed') as completed
            FROM agent_task_assignments
            WHERE module_id IS NOT NULL
            GROUP BY module_id
            ORDER BY tasks DESC
        """
        )
        by_module = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "overall": dict(overall),
                "by_agent": [dict(a) for a in by_agent],
                "by_module": [dict(m) for m in by_module],
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/tasks", methods=["GET"])
@login_required
@api_admin_required
def get_agent_tasks(agent_id):
    """Get all tasks assigned to a specific agent"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        status = request.args.get("status")
        limit = request.args.get("limit", 20, type=int)

        query = """
            SELECT t.*, u.username as assigned_by_name
            FROM agent_task_assignments t
            LEFT JOIN users u ON t.assigned_by = u.id
            WHERE t.agent_id = %s
        """
        params = [agent_id]

        if status:
            query += " AND t.status = %s"
            params.append(status)

        query += " ORDER BY t.created_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        tasks = cur.fetchall()

        return jsonify({"success": True, "tasks": [dict(t) for t in tasks]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/modules/available", methods=["GET"])
@login_required
@api_admin_required
def get_available_modules():
    """Get list of modules available for task assignment"""
    try:
        from module_registry import get_enabled_modules

        modules = []
        for m in get_enabled_modules():
            modules.append(
                {
                    "id": m.id,
                    "name": m.name,
                    "route": m.route,
                    "category": m.category.value,
                    "description": m.description,
                }
            )

        return jsonify({"success": True, "modules": modules})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# WORKFLOW AUTOMATION APIs (Phase 80)
# =============================================================================


@team_management_bp.route("/api/workflows/templates", methods=["GET"])
@login_required
@api_admin_required
def get_workflow_templates():
    """Get workflow templates"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT * FROM workflow_templates ORDER BY name")
            templates = cur.fetchall()
        except Exception:
            # Table may not exist yet
            templates = []
        return jsonify({"success": True, "templates": [dict(t) for t in templates]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/workflows/executions", methods=["GET"])
@login_required
@api_admin_required
def get_workflow_executions():
    """Get recent workflow executions"""
    try:
        limit = request.args.get("limit", 50, type=int)
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT we.* FROM workflow_executions we
                   ORDER BY we.started_at DESC LIMIT %s""",
                (limit,),
            )
            executions = cur.fetchall()
        except Exception:
            # Table may not exist yet
            executions = []
        return jsonify({"success": True, "executions": [dict(e) for e in executions]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# =============================================================================
# C.R.E.E.D. COMPLIANCE APIs - Agent-Specific Endpoints (Phases 32-37)
# =============================================================================

# -----------------------------------------------------------------------------
# Phase 32: Agent Memory CRUD
# -----------------------------------------------------------------------------


@team_management_bp.route("/api/agents/<int:agent_id>/memory", methods=["GET"])
@login_required
@api_admin_required
def get_agent_memories(agent_id):
    """Get agent memories with pagination and filters"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

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
            conditions.append("(memory_key ILIKE %s OR memory_value::text ILIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])

        where_clause = " AND ".join(conditions)

        # Get total count
        cur.execute(f"SELECT COUNT(*) FROM agent_memory WHERE {where_clause}", params)
        total = cur.fetchone()["count"]

        # Get memories
        cur.execute(
            f"""
            SELECT id, agent_id, memory_type, memory_key, memory_value,
                   importance, context, is_deleted, deleted_at, deleted_by,
                   deletion_reason, created_at, updated_at
            FROM agent_memory
            WHERE {where_clause}
            ORDER BY importance DESC, updated_at DESC
            LIMIT %s OFFSET %s
        """,
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
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/memory", methods=["POST"])
@login_required
@api_admin_required
def create_agent_memory(agent_id):
    """Create new agent memory"""
    try:
        data = request.get_json()

        if not data.get("memory_key") or not data.get("memory_value"):
            return (
                jsonify({"success": False, "error": "memory_key and memory_value required"}),
                400,
            )

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify agent exists
        cur.execute("SELECT id FROM agents WHERE id = %s", (agent_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Agent not found"}), 404

        cur.execute(
            """
            INSERT INTO agent_memory (agent_id, memory_type, memory_key, memory_value, importance, context)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, agent_id, memory_type, memory_key, memory_value, importance, context, created_at
        """,
            (
                agent_id,
                data.get("memory_type", "general"),
                data["memory_key"],
                (json.dumps(data["memory_value"]) if isinstance(data["memory_value"], dict) else data["memory_value"]),
                data.get("importance", 0.5),
                data.get("context"),
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

        conn.commit()

        return jsonify(
            {
                "success": True,
                "data": dict(memory),
                "message": "Memory created successfully",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/memory/<int:memory_id>", methods=["GET"])
@login_required
@api_admin_required
def get_agent_memory(agent_id, memory_id):
    """Get specific agent memory"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

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
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/memory/<int:memory_id>", methods=["PUT"])
@login_required
@api_admin_required
def update_agent_memory(agent_id, memory_id):
    """Update agent memory"""
    try:
        data = request.get_json()

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get old value for audit
        cur.execute(
            "SELECT * FROM agent_memory WHERE id = %s AND agent_id = %s",
            (memory_id, agent_id),
        )
        old_memory = cur.fetchone()

        if not old_memory:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Memory not found"}), 404

        # Build update
        updates = []
        params = []

        if "memory_value" in data:
            updates.append("memory_value = %s")
            params.append(
                json.dumps(data["memory_value"]) if isinstance(data["memory_value"], dict) else data["memory_value"]
            )

        if "importance" in data:
            updates.append("importance = %s")
            params.append(data["importance"])

        if "context" in data:
            updates.append("context = %s")
            params.append(data["context"])

        if "memory_type" in data:
            updates.append("memory_type = %s")
            params.append(data["memory_type"])

        if not updates:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        updates.append("updated_at = NOW()")
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

        conn.commit()

        return jsonify(
            {
                "success": True,
                "data": dict(updated),
                "message": "Memory updated successfully",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/memory/<int:memory_id>", methods=["DELETE"])
@login_required
@api_admin_required
def delete_agent_memory(agent_id, memory_id):
    """Soft delete agent memory using database function"""
    try:
        data = request.get_json() or {}
        reason = data.get("reason", "Manual deletion by admin")

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Use the database soft_delete function
        cur.execute(
            """
            SELECT soft_delete_agent_memory(%s, %s, %s) as deleted
        """,
            (memory_id, current_user.id, reason),
        )

        result = cur.fetchone()

        if not result or not result["deleted"]:
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": "Memory not found or already deleted"}),
                404,
            )

        conn.commit()

        return jsonify({"success": True, "message": "Memory soft-deleted successfully"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/memory/<int:memory_id>/restore", methods=["POST"])
@login_required
@api_admin_required
def restore_agent_memory(agent_id, memory_id):
    """Restore soft-deleted agent memory"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

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
            cur.close()
            conn.close()
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

        conn.commit()

        return jsonify(
            {
                "success": True,
                "data": dict(restored),
                "message": "Memory restored successfully",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Phase 33: Emotional State Tracking
# -----------------------------------------------------------------------------


@team_management_bp.route("/api/agents/<int:agent_id>/emotional-state", methods=["GET"])
@login_required
@api_admin_required
def get_agent_emotional_state(agent_id):
    """Get agent's current emotional state with thresholds"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get latest emotional state
        cur.execute(
            """
            SELECT * FROM agent_emotional_state
            WHERE agent_id = %s
            ORDER BY recorded_at DESC
            LIMIT 1
        """,
            (agent_id,),
        )

        state = cur.fetchone()

        # Get agent welfare view data
        cur.execute(
            """
            SELECT * FROM v_agent_welfare WHERE agent_id = %s
        """,
            (agent_id,),
        )

        welfare = cur.fetchone()

        # Define thresholds
        thresholds = {
            "energy_low": 0.2,
            "energy_critical": 0.1,
            "stress_high": 0.7,
            "stress_critical": 0.85,
        }

        return jsonify(
            {
                "success": True,
                "data": {
                    "current_state": dict(state) if state else None,
                    "welfare_summary": dict(welfare) if welfare else None,
                    "thresholds": thresholds,
                    "alerts": (_check_emotional_alerts(state, thresholds) if state else []),
                },
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


def _check_emotional_alerts(state, thresholds):
    """Check if emotional state triggers any alerts"""
    alerts = []
    if not state:
        return alerts

    energy = float(state.get("energy_level", 1.0))
    stress = float(state.get("stress_level", 0.0))

    if energy <= thresholds["energy_critical"]:
        alerts.append({"type": "critical", "message": f"Energy critically low: {energy:.1%}"})
    elif energy <= thresholds["energy_low"]:
        alerts.append({"type": "warning", "message": f"Energy low: {energy:.1%}"})

    if stress >= thresholds["stress_critical"]:
        alerts.append({"type": "critical", "message": f"Stress critically high: {stress:.1%}"})
    elif stress >= thresholds["stress_high"]:
        alerts.append({"type": "warning", "message": f"Stress elevated: {stress:.1%}"})

    return alerts


@team_management_bp.route("/api/agents/<int:agent_id>/emotional-state/history", methods=["GET"])
@login_required
@api_admin_required
def get_agent_emotional_history(agent_id):
    """Get agent emotional state history"""
    try:
        days = request.args.get("days", 7, type=int)
        limit = request.args.get("limit", 100, type=int)

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM agent_emotional_state
            WHERE agent_id = %s AND recorded_at >= NOW() - (%s * INTERVAL '1 day')
            ORDER BY recorded_at DESC
            LIMIT %s
        """,
            (agent_id, days, limit),
        )

        history = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "data": [dict(h) for h in history],
                "count": len(history),
                "days": days,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/emotional-state", methods=["POST"])
@login_required
@api_admin_required
def record_agent_emotional_state(agent_id):
    """Record new emotional state (auto-triggers rest if critical)"""
    try:
        data = request.get_json()

        energy = data.get("energy_level", 0.8)
        stress = data.get("stress_level", 0.2)

        # Validate ranges
        if not (0.1 <= energy <= 1.0):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "energy_level must be between 0.1 and 1.0",
                    }
                ),
                400,
            )
        if not (0.0 <= stress <= 0.9):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "stress_level must be between 0.0 and 0.9",
                    }
                ),
                400,
            )

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Insert emotional state
        cur.execute(
            """
            INSERT INTO agent_emotional_state
            (agent_id, energy_level, stress_level, mood, task_context, recorded_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                agent_id,
                energy,
                stress,
                data.get("mood", "neutral"),
                data.get("task_context"),
                current_user.id,
            ),
        )

        state = cur.fetchone()
        rest_triggered = False

        # Auto-trigger rest if critical (stress > 0.85 or energy < 0.2)
        if stress > 0.85 or energy < 0.2:
            cur.execute(
                """
                SELECT trigger_agent_rest_cycle(%s, %s, %s, %s)
            """,
                (
                    agent_id,
                    "forced",
                    f"Auto-triggered: stress={stress:.2f}, energy={energy:.2f}",
                    current_user.id,
                ),
            )
            rest_triggered = True

        conn.commit()

        response = {
            "success": True,
            "data": dict(state),
            "message": "Emotional state recorded",
        }

        if rest_triggered:
            response["alert"] = "Critical state detected - rest cycle auto-triggered"

        return jsonify(response)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Phase 36: Rest Cycles
# -----------------------------------------------------------------------------


@team_management_bp.route("/api/agents/<int:agent_id>/rest-cycles", methods=["GET"])
@login_required
@api_admin_required
def get_agent_rest_cycles(agent_id):
    """Get agent rest cycle history"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        offset = (page - 1) * per_page
        active_only = request.args.get("active_only", "false").lower() == "true"

        conditions = ["agent_id = %s"]
        params = [agent_id]

        if active_only:
            conditions.append("ended_at IS NULL")

        where_clause = " AND ".join(conditions)

        # Get total
        cur.execute(f"SELECT COUNT(*) FROM agent_rest_cycles WHERE {where_clause}", params)
        total = cur.fetchone()["count"]

        # Get cycles
        cur.execute(
            f"""
            SELECT rc.*, u.username as initiated_by_name
            FROM agent_rest_cycles rc
            LEFT JOIN users u ON rc.initiated_by = u.id
            WHERE {where_clause}
            ORDER BY rc.started_at DESC
            LIMIT %s OFFSET %s
        """,
            params + [per_page, offset],
        )

        cycles = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "data": [dict(c) for c in cycles],
                "count": len(cycles),
                "total": total,
                "page": page,
                "per_page": per_page,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/rest-cycles/start", methods=["POST"])
@login_required
@api_admin_required
def start_agent_rest_cycle(agent_id):
    """Start a rest cycle for an agent"""
    try:
        data = request.get_json() or {}

        rest_type = data.get("rest_type", "voluntary")
        reason = data.get("reason", "Manual rest cycle")

        if rest_type not in ["voluntary", "forced", "scheduled"]:
            return jsonify({"success": False, "error": "Invalid rest_type"}), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if already resting
        cur.execute(
            """
            SELECT id FROM agent_rest_cycles
            WHERE agent_id = %s AND ended_at IS NULL
        """,
            (agent_id,),
        )

        if cur.fetchone():
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": "Agent is already in a rest cycle"}),
                400,
            )

        # Use database function
        cur.execute(
            """
            SELECT trigger_agent_rest_cycle(%s, %s, %s, %s) as cycle_id
        """,
            (agent_id, rest_type, reason, current_user.id),
        )

        result = cur.fetchone()

        # Get the created cycle
        cur.execute("SELECT * FROM agent_rest_cycles WHERE id = %s", (result["cycle_id"],))
        cycle = cur.fetchone()

        conn.commit()

        return jsonify(
            {
                "success": True,
                "data": dict(cycle),
                "message": f"Rest cycle started for agent {agent_id}",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/rest-cycles/<int:cycle_id>/end", methods=["POST"])
@login_required
@api_admin_required
def end_agent_rest_cycle(agent_id, cycle_id):
    """End a rest cycle"""
    try:
        data = request.get_json() or {}
        notes = data.get("notes")

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE agent_rest_cycles
            SET ended_at = NOW(), notes = COALESCE(%s, notes)
            WHERE id = %s AND agent_id = %s AND ended_at IS NULL
            RETURNING *
        """,
            (notes, cycle_id, agent_id),
        )

        cycle = cur.fetchone()

        if not cycle:
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": "Rest cycle not found or already ended"}),
                404,
            )

        # Log governance event
        cur.execute(
            """
            INSERT INTO governance_audit_log
            (event_type, event_category, agent_id, user_id, action, target_table, target_id, outcome)
            VALUES ('rest_cycle_ended', 'agent_welfare', %s, %s, 'end_rest_cycle', 'agent_rest_cycles', %s, 'success')
        """,
            (agent_id, current_user.id, cycle_id),
        )

        conn.commit()

        return jsonify({"success": True, "data": dict(cycle), "message": "Rest cycle ended"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Phase 37: Task Refusals
# -----------------------------------------------------------------------------


@team_management_bp.route("/api/agents/<int:agent_id>/refusals", methods=["GET"])
@login_required
@api_admin_required
def get_agent_refusals(agent_id):
    """Get agent task refusal history"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        offset = (page - 1) * per_page

        # Get total
        cur.execute("SELECT COUNT(*) FROM task_refusal_log WHERE agent_id = %s", (agent_id,))
        total = cur.fetchone()["count"]

        # Get refusals with constraint info
        cur.execute(
            """
            SELECT r.*, ec.constraint_name, ec.category as constraint_category
            FROM task_refusal_log r
            LEFT JOIN ethics_constraints ec ON r.constraint_id = ec.id
            WHERE r.agent_id = %s
            ORDER BY r.refused_at DESC
            LIMIT %s OFFSET %s
        """,
            (agent_id, per_page, offset),
        )

        refusals = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "data": [dict(r) for r in refusals],
                "count": len(refusals),
                "total": total,
                "page": page,
                "per_page": per_page,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/refusals", methods=["POST"])
@login_required
@api_admin_required
def log_agent_refusal(agent_id):
    """Log a task refusal"""
    try:
        data = request.get_json()

        if not data.get("task_description"):
            return (
                jsonify({"success": False, "error": "task_description required"}),
                400,
            )

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO task_refusal_log
            (agent_id, task_description, refusal_reason, constraint_id, user_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                agent_id,
                data["task_description"],
                data.get("refusal_reason", "Ethics constraint violation"),
                data.get("constraint_id"),
                current_user.id,
            ),
        )

        refusal = cur.fetchone()

        # Log governance event
        cur.execute(
            """
            INSERT INTO governance_audit_log
            (event_type, event_category, agent_id, user_id, action, target_table, target_id, new_value, outcome)
            VALUES ('task_refused', 'ethics', %s, %s, 'log_refusal', 'task_refusal_log', %s, %s, 'success')
        """,
            (
                agent_id,
                current_user.id,
                refusal["id"],
                json.dumps(dict(refusal), default=str),
            ),
        )

        conn.commit()

        return jsonify({"success": True, "data": dict(refusal), "message": "Task refusal logged"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/refusals/<int:refusal_id>/override", methods=["POST"])
@login_required
@api_admin_required
def override_agent_refusal(agent_id, refusal_id):
    """Override a task refusal with justification"""
    try:
        data = request.get_json()

        if not data.get("justification"):
            return (
                jsonify({"success": False, "error": "justification required for override"}),
                400,
            )

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get original refusal
        cur.execute(
            """
            SELECT * FROM task_refusal_log WHERE id = %s AND agent_id = %s
        """,
            (refusal_id, agent_id),
        )

        refusal = cur.fetchone()

        if not refusal:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Refusal not found"}), 404

        if refusal.get("was_overridden"):
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": "Refusal already overridden"}),
                400,
            )

        # Update refusal
        cur.execute(
            """
            UPDATE task_refusal_log
            SET was_overridden = TRUE,
                override_by = %s,
                override_reason = %s,
                override_at = NOW()
            WHERE id = %s
            RETURNING *
        """,
            (current_user.id, data["justification"], refusal_id),
        )

        updated = cur.fetchone()

        # Log governance event (critical)
        cur.execute(
            """
            INSERT INTO governance_audit_log
            (event_type, event_category, agent_id, user_id, action, target_table, target_id,
             old_value, new_value, reason, outcome, severity)
            VALUES ('refusal_overridden', 'ethics', %s, %s, 'override_refusal', 'task_refusal_log', %s,
                    %s, %s, %s, 'success', 'high')
        """,
            (
                agent_id,
                current_user.id,
                refusal_id,
                json.dumps(dict(refusal), default=str),
                json.dumps(dict(updated), default=str),
                data["justification"],
            ),
        )

        conn.commit()

        return jsonify(
            {
                "success": True,
                "data": dict(updated),
                "message": "Refusal overridden with justification logged",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# =============================================================================
# SMART LLM ROUTING APIs
# =============================================================================


@team_management_bp.route("/api/routing/suggest-model", methods=["POST"])
@login_required
@api_admin_required
def suggest_model_for_task():
    """Get recommended model for a task based on routing rules"""
    try:
        from ai_bridge.smart_router import get_router

        data = request.get_json()

        if not data.get("task_type"):
            return jsonify({"success": False, "error": "task_type required"}), 400

        router = get_router()
        recommendation = router.suggest_model(
            task_type=data["task_type"],
            complexity=data.get("complexity", 5),
            context_tokens=data.get("context_tokens", 0),
            agent_id=data.get("agent_id"),
            failure_count=data.get("previous_failures", 0),
        )

        return jsonify(
            {
                "success": True,
                "recommendation": {
                    "tier": recommendation.tier,
                    "provider": recommendation.provider,
                    "model": recommendation.model_name,
                    "reason": recommendation.reason,
                    "should_escalate": recommendation.should_escalate,
                    "use_claude_as_judge": recommendation.use_claude_as_judge,
                    "estimated_cost": recommendation.estimated_cost,
                    "force_reset": recommendation.force_reset,
                },
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/routing/rules", methods=["GET"])
@login_required
@api_admin_required
def get_routing_rules():
    """Get all task routing rules"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, task_type, description, complexity_threshold,
                   preferred_tier, fallback_tier, max_context_tokens,
                   require_reset_on_escalate, claude_as_judge, is_active,
                   created_at, updated_at
            FROM task_routing_rules
            ORDER BY task_type
        """
        )

        rules = cur.fetchall()

        return jsonify({"success": True, "data": [dict(r) for r in rules], "count": len(rules)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/routing/rules", methods=["POST"])
@login_required
@api_admin_required
def create_or_update_routing_rule():
    """Create or update a routing rule"""
    try:
        data = request.get_json()

        if not data.get("task_type"):
            return jsonify({"success": False, "error": "task_type required"}), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Upsert rule
        cur.execute(
            """
            INSERT INTO task_routing_rules
            (task_type, description, complexity_threshold, preferred_tier,
             fallback_tier, max_context_tokens, require_reset_on_escalate,
             claude_as_judge, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (task_type) DO UPDATE SET
                description = EXCLUDED.description,
                complexity_threshold = EXCLUDED.complexity_threshold,
                preferred_tier = EXCLUDED.preferred_tier,
                fallback_tier = EXCLUDED.fallback_tier,
                max_context_tokens = EXCLUDED.max_context_tokens,
                require_reset_on_escalate = EXCLUDED.require_reset_on_escalate,
                claude_as_judge = EXCLUDED.claude_as_judge,
                is_active = EXCLUDED.is_active,
                updated_at = NOW()
            RETURNING *
        """,
            (
                data["task_type"],
                data.get("description"),
                data.get("complexity_threshold", 5),
                data.get("preferred_tier", "sonnet"),
                data.get("fallback_tier"),
                data.get("max_context_tokens", 8000),
                data.get("require_reset_on_escalate", True),
                data.get("claude_as_judge", False),
                data.get("is_active", True),
            ),
        )

        rule = cur.fetchone()

        conn.commit()

        return jsonify({"success": True, "data": dict(rule), "message": "Routing rule saved"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/routing/rules/<int:rule_id>", methods=["DELETE"])
@login_required
@api_admin_required
def deactivate_routing_rule(rule_id):
    """Deactivate a routing rule (soft delete)"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE task_routing_rules
            SET is_active = FALSE, updated_at = NOW()
            WHERE id = %s
            RETURNING *
        """,
            (rule_id,),
        )

        rule = cur.fetchone()

        if not rule:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Rule not found"}), 404

        conn.commit()

        return jsonify({"success": True, "data": dict(rule), "message": "Routing rule deactivated"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/routing/execute", methods=["POST"])
@login_required
@api_admin_required
def execute_with_smart_routing():
    """Execute a task with smart model routing"""
    try:
        from ai_bridge.smart_router import get_router, classify_task
        from ai_bridge.archie_bridge import archie_bridge

        data = request.get_json()

        if not data.get("prompt"):
            return jsonify({"success": False, "error": "prompt required"}), 400

        router = get_router()

        # Classify task if not provided
        task_type = data.get("task_type")
        if not task_type:
            task_type = classify_task(data["prompt"], data.get("context"))

        # Get routing recommendation
        recommendation = router.suggest_model(
            task_type=task_type,
            complexity=data.get("complexity", 5),
            context_tokens=len(data["prompt"]) // 4,  # Rough estimate
            agent_id=data.get("agent_id"),
            failure_count=data.get("failure_count", 0),
        )

        # Prepare prompt
        prompt = data["prompt"]
        if recommendation.should_escalate and recommendation.force_reset:
            prompt = router.get_escalation_prompt(
                data["prompt"],
                data.get("failure_count", 0),
                data.get("error_context", ""),
            )

        # Execute with recommended model
        result = archie_bridge(
            prompt=prompt,
            context=data.get("context"),
            user_id=current_user.id,
            force_model=recommendation.model_name,
            agent_id=data.get("agent_id"),
            system_prompt=data.get("system_prompt"),
        )

        # Track execution
        execution_id = router.track_execution(
            agent_id=data.get("agent_id"),
            task_type=task_type,
            tier=recommendation.tier,
            model=recommendation.model_name,
            provider=recommendation.provider,
            outcome="success" if result.get("success") else "failed",
            tokens=result.get("tokens_used", 0),
            cost=result.get("cost", 0),
            escalated=recommendation.should_escalate,
            claude_as_judge=recommendation.use_claude_as_judge,
            error_message=result.get("error") if not result.get("success") else None,
        )

        return jsonify(
            {
                "success": result.get("success", False),
                "data": {
                    "response": result.get("response"),
                    "task_type": task_type,
                    "routing": {
                        "tier": recommendation.tier,
                        "model": recommendation.model_name,
                        "reason": recommendation.reason,
                        "escalated": recommendation.should_escalate,
                    },
                    "execution_id": execution_id,
                    "tokens": result.get("tokens_used", 0),
                    "cost": result.get("cost", 0),
                },
                "error": result.get("error"),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/routing/analytics", methods=["GET"])
@login_required
@api_admin_required
def get_routing_analytics():
    """Get model usage and cost analytics"""
    try:
        from ai_bridge.smart_router import get_router

        days = request.args.get("days", 30, type=int)
        router = get_router()

        analytics = router.get_usage_analytics(days)

        return jsonify({"success": True, "data": analytics})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/routing/agent-performance", methods=["GET"])
@login_required
@api_admin_required
def get_agent_routing_performance():
    """Get per-agent model usage and performance"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM v_agent_routing_performance ORDER BY total_tasks DESC")
        performance = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "data": [dict(p) for p in performance],
                "count": len(performance),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/routing/model-tiers", methods=["GET"])
@login_required
@api_admin_required
def get_model_tier_configs():
    """Get model tier configurations"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM model_tier_configs
            ORDER BY priority
        """
        )

        tiers = cur.fetchall()

        return jsonify({"success": True, "data": [dict(t) for t in tiers], "count": len(tiers)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/routing/model-tiers", methods=["POST"])
@login_required
@api_admin_required
def update_model_tier_config():
    """Update a model tier configuration"""
    try:
        data = request.get_json()

        if not data.get("tier_name"):
            return jsonify({"success": False, "error": "tier_name required"}), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO model_tier_configs
            (tier_name, display_name, provider, model_name, input_cost_per_1m,
             output_cost_per_1m, max_tokens, is_active, priority)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tier_name) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                provider = EXCLUDED.provider,
                model_name = EXCLUDED.model_name,
                input_cost_per_1m = EXCLUDED.input_cost_per_1m,
                output_cost_per_1m = EXCLUDED.output_cost_per_1m,
                max_tokens = EXCLUDED.max_tokens,
                is_active = EXCLUDED.is_active,
                priority = EXCLUDED.priority
            RETURNING *
        """,
            (
                data["tier_name"],
                data.get("display_name"),
                data.get("provider", "claude"),
                data.get("model_name"),
                data.get("input_cost_per_1m", 0),
                data.get("output_cost_per_1m", 0),
                data.get("max_tokens", 4096),
                data.get("is_active", True),
                data.get("priority", 50),
            ),
        )

        tier = cur.fetchone()

        conn.commit()

        return jsonify(
            {
                "success": True,
                "data": dict(tier),
                "message": "Model tier configuration saved",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# =============================================================================
# ETHICS MONITORING APIs (Phase 38)
# =============================================================================


@team_management_bp.route("/api/ethics/run-monitoring", methods=["POST"])
@login_required
@api_admin_required
def run_ethics_monitoring():
    """Run a full ethics monitoring cycle"""
    try:
        from ai_bridge.ethics_monitor import run_monitoring_cycle

        result = run_monitoring_cycle(triggered_by=current_user.id)

        return jsonify(
            {
                "success": True,
                "data": {
                    "run_id": result.run_id,
                    "agents_checked": result.agents_checked,
                    "alerts_created": result.alerts_created,
                    "issues_found": result.issues_found,
                    "duration_ms": result.duration_ms,
                },
                "message": f"Ethics monitoring complete: {result.alerts_created} alerts created",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/ethics/welfare-status", methods=["GET"])
@login_required
@api_admin_required
def get_ethics_welfare_status():
    """Get welfare status for all agents or a specific agent"""
    try:
        from ai_bridge.ethics_monitor import get_welfare_status

        agent_id = request.args.get("agent_id", type=int)
        status = get_welfare_status(agent_id)

        return jsonify({"success": True, "data": status, "count": len(status)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/ethics/alerts", methods=["GET"])
@login_required
@api_admin_required
def get_ethics_alerts():
    """Get ethics alerts with pagination and filters"""
    try:
        from ai_bridge.ethics_monitor import get_active_alerts

        severity = request.args.get("severity")
        status = request.args.get("status")
        agent_id = request.args.get("agent_id", type=int)
        limit = request.args.get("limit", 50, type=int)
        include_resolved = request.args.get("include_resolved", "false").lower() == "true"

        alerts = get_active_alerts(
            severity=severity,
            status=status,
            agent_id=agent_id,
            limit=limit,
            include_resolved=include_resolved,
        )

        return jsonify({"success": True, "data": alerts, "count": len(alerts)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/ethics/alerts/<int:alert_id>/acknowledge", methods=["POST"])
@login_required
@api_admin_required
def acknowledge_ethics_alert(alert_id):
    """Acknowledge an ethics alert"""
    try:
        from ai_bridge.ethics_monitor import EthicsMonitor

        data = request.get_json() or {}
        notes = data.get("notes")

        monitor = EthicsMonitor()
        success = monitor.acknowledge_alert(alert_id, current_user.id, notes)

        if success:
            return jsonify({"success": True, "message": "Alert acknowledged"})
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Alert not found or already acknowledged",
                    }
                ),
                404,
            )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/ethics/alerts/<int:alert_id>/resolve", methods=["POST"])
@login_required
@api_admin_required
def resolve_ethics_alert(alert_id):
    """Resolve an ethics alert"""
    try:
        from ai_bridge.ethics_monitor import EthicsMonitor

        data = request.get_json() or {}
        resolution_notes = data.get("resolution_notes")
        action_taken = data.get("action_taken")

        if not resolution_notes:
            return (
                jsonify({"success": False, "error": "resolution_notes required"}),
                400,
            )

        monitor = EthicsMonitor()
        success = monitor.resolve_alert(alert_id, current_user.id, resolution_notes, action_taken)

        if success:
            return jsonify({"success": True, "message": "Alert resolved"})
        else:
            return jsonify({"success": False, "error": "Alert not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/ethics/compliance-summary", methods=["GET"])
@login_required
@api_admin_required
def get_ethics_compliance_summary():
    """Get compliance summary for dashboard"""
    try:
        from ai_bridge.ethics_monitor import get_compliance_summary

        days = request.args.get("days", 30, type=int)
        summary = get_compliance_summary(days)

        return jsonify({"success": True, "data": summary})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/ethics/reports", methods=["GET"])
@login_required
@api_admin_required
def get_compliance_reports():
    """Get list of compliance reports"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        limit = request.args.get("limit", 10, type=int)

        cur.execute(
            """
            SELECT id, report_type, period_start, period_end,
                   compliance_score, total_agents_monitored, total_alerts,
                   critical_issues, generated_by, generated_at
            FROM compliance_reports
            ORDER BY generated_at DESC
            LIMIT %s
        """,
            (limit,),
        )

        reports = cur.fetchall()

        return jsonify({"success": True, "data": [dict(r) for r in reports], "count": len(reports)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/ethics/reports/<int:report_id>", methods=["GET"])
@login_required
@api_admin_required
def get_compliance_report(report_id):
    """Get a specific compliance report with full details"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM compliance_reports WHERE id = %s", (report_id,))
        report = cur.fetchone()

        if not report:
            return jsonify({"success": False, "error": "Report not found"}), 404

        return jsonify({"success": True, "data": dict(report)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/ethics/reports/generate", methods=["POST"])
@login_required
@api_admin_required
def generate_compliance_report():
    """Generate a new compliance report"""
    try:
        from ai_bridge.ethics_monitor import generate_weekly_report

        report_id = generate_weekly_report()

        if report_id:
            return jsonify(
                {
                    "success": True,
                    "data": {"report_id": report_id},
                    "message": "Compliance report generated",
                }
            )
        else:
            return (
                jsonify({"success": False, "error": "Failed to generate report"}),
                500,
            )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/ethics/athena-status", methods=["GET"])
@login_required
@api_admin_required
def get_athena_status():
    """Get ATHENA (Ethics Watchdog) status"""
    try:
        from ai_bridge.ethics_monitor import get_athena_status

        status = get_athena_status()

        return jsonify({"success": True, "data": status})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@team_management_bp.route("/api/ethics/monitoring-runs", methods=["GET"])
@login_required
@api_admin_required
def get_monitoring_runs():
    """Get ethics monitoring run history"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        limit = request.args.get("limit", 20, type=int)

        cur.execute(
            """
            SELECT emr.*, u.username as triggered_by_name
            FROM ethics_monitoring_runs emr
            LEFT JOIN users u ON emr.triggered_by = u.id
            ORDER BY emr.started_at DESC
            LIMIT %s
        """,
            (limit,),
        )

        runs = cur.fetchall()

        return jsonify({"success": True, "data": [dict(r) for r in runs], "count": len(runs)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/ethics/config", methods=["GET"])
@login_required
@api_admin_required
def get_ethics_config():
    """Get ethics monitoring configuration"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM ethics_monitoring_config ORDER BY config_key")
        configs = cur.fetchall()

        # Convert to dict for easier frontend use
        config_dict = {c["config_key"]: c["config_value"] for c in configs}

        return jsonify({"success": True, "data": config_dict, "raw": [dict(c) for c in configs]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/ethics/config", methods=["POST"])
@login_required
@api_admin_required
def update_ethics_config():
    """Update ethics monitoring configuration"""
    try:
        data = request.get_json()

        if not data.get("config_key") or data.get("config_value") is None:
            return (
                jsonify({"success": False, "error": "config_key and config_value required"}),
                400,
            )

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO ethics_monitoring_config (config_key, config_value, description)
            VALUES (%s, %s, %s)
            ON CONFLICT (config_key) DO UPDATE SET
                config_value = EXCLUDED.config_value,
                updated_at = NOW()
            RETURNING *
        """,
            (
                data["config_key"],
                json.dumps(data["config_value"]),
                data.get("description"),
            ),
        )

        config = cur.fetchone()

        # Log governance event
        cur.execute(
            """
            INSERT INTO governance_audit_log
            (event_type, event_category, user_id, action, target_table, new_value, outcome)
            VALUES ('config_change', 'ethics', %s, 'update_ethics_config', 'ethics_monitoring_config', %s, 'success')
        """,
            (current_user.id, json.dumps(dict(config), default=str)),
        )

        conn.commit()

        return jsonify({"success": True, "data": dict(config), "message": "Configuration updated"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# NOTE: Station Assignment UI APIs moved to Phase 39 section below (line ~5270)
# Duplicates were removed to fix Flask route registration issues


@team_management_bp.route("/api/creed/check-move/<int:agent_id>", methods=["GET"])
@login_required
@api_admin_required
def check_creed_move_compliance(agent_id):
    """Pre-check if moving an agent would violate C.R.E.E.D. guidelines"""
    try:
        _target_type = request.args.get("target_type")  # noqa: F841
        _target_id = request.args.get("target_id")  # noqa: F841

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        result = {"blocked": False, "warnings": [], "message": ""}

        # Check if agent is fixed
        cur.execute(
            """
            SELECT is_fixed, role_type FROM station_assignments
            WHERE agent_id = %s AND is_active = TRUE AND is_fixed = TRUE
        """,
            (agent_id,),
        )
        fixed = cur.fetchone()

        if fixed:
            result["blocked"] = True
            result["message"] = f'Agent is fixed as {fixed["role_type"]} and cannot be moved'
            cur.close()
            conn.close()
            return jsonify({"success": True, "data": result})

        # Check rest cycle
        cur.execute(
            """
            SELECT rest_type, started_at, reason
            FROM agent_rest_cycles
            WHERE agent_id = %s AND ended_at IS NULL
        """,
            (agent_id,),
        )
        rest = cur.fetchone()

        if rest:
            if rest["rest_type"] == "forced":
                result["blocked"] = True
                result["message"] = "Agent is in forced rest (C.R.E.E.D. mandated) and cannot be moved"
            else:
                result["warnings"].append(f"Agent is in {rest['rest_type']} rest since {rest['started_at']}")

        # Check emotional state
        cur.execute(
            """
            SELECT stress_level, energy_level FROM agent_emotional_state
            WHERE agent_id = %s
        """,
            (agent_id,),
        )
        emotional = cur.fetchone()

        if emotional:
            if emotional.get("stress_level", 0) > 0.7:
                result["warnings"].append(f"High stress: {emotional['stress_level']:.0%}")
            if emotional.get("energy_level", 1) < 0.3:
                result["warnings"].append(f"Low energy: {emotional['energy_level']:.0%}")

        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# =============================================================================
# TRAINING ROOM APIs
# =============================================================================


@team_management_bp.route("/api/training", methods=["GET"])
@login_required
@api_admin_required
def get_training_assignments():
    """Get all agents currently in training"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM v_training_room_agents")
        training = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "data": [dict(t) for t in training],
                "count": len(training),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/training/assign", methods=["POST"])
@login_required
@api_admin_required
def assign_to_training():
    """Assign an agent to training"""
    try:
        data = request.get_json()
        agent_id = data.get("agent_id")
        skill_name = data.get("skill_name")
        skill_category = data.get("skill_category")
        target_proficiency = data.get("target_proficiency", 3)
        current_proficiency = data.get("current_proficiency", 1)
        notes = data.get("notes")

        if not agent_id or not skill_name:
            return (
                jsonify({"success": False, "error": "agent_id and skill_name required"}),
                400,
            )

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Remove from current station if assigned
        cur.execute(
            """
            UPDATE station_assignments SET is_active = FALSE
            WHERE agent_id = %s AND is_active = TRUE AND is_fixed = FALSE
        """,
            (agent_id,),
        )

        # Create training assignment
        cur.execute(
            """
            INSERT INTO training_assignments
            (agent_id, skill_name, skill_category, target_proficiency, current_proficiency, notes, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                agent_id,
                skill_name,
                skill_category,
                target_proficiency,
                current_proficiency,
                notes,
                current_user.id,
            ),
        )

        training = cur.fetchone()

        # Log governance event
        cur.execute(
            """
            INSERT INTO governance_audit_log
            (event_type, event_category, agent_id, user_id, action, new_value, outcome)
            VALUES ('training_assigned', 'agent_development', %s, %s, 'assign_training', %s, 'success')
        """,
            (
                agent_id,
                current_user.id,
                json.dumps({"skill": skill_name, "target": target_proficiency}),
            ),
        )

        conn.commit()

        return jsonify(
            {
                "success": True,
                "data": dict(training),
                "message": f"Agent assigned to training: {skill_name}",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/training/<int:training_id>/complete", methods=["POST"])
@login_required
@api_admin_required
def complete_training(training_id):
    """Complete or cancel a training assignment"""
    try:
        data = request.get_json() or {}
        action = data.get("action", "complete")  # complete or cancel
        new_proficiency = data.get("new_proficiency")

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if action == "complete":
            cur.execute(
                """
                UPDATE training_assignments
                SET status = 'completed',
                    completed_at = NOW(),
                    current_proficiency = COALESCE(%s, target_proficiency)
                WHERE id = %s
                RETURNING *
            """,
                (new_proficiency, training_id),
            )
        else:
            cur.execute(
                """
                UPDATE training_assignments
                SET status = 'cancelled', completed_at = NOW()
                WHERE id = %s
                RETURNING *
            """,
                (training_id,),
            )

        training = cur.fetchone()

        if not training:
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": "Training assignment not found"}),
                404,
            )

        # Update agent_skills if completed
        if action == "complete" and training:
            cur.execute(
                """
                INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (agent_id, skill_name) DO UPDATE SET
                    proficiency_level = GREATEST(agent_skills.proficiency_level, EXCLUDED.proficiency_level),
                    updated_at = NOW()
            """,
                (
                    training["agent_id"],
                    training["skill_name"],
                    training["skill_category"],
                    new_proficiency or training["target_proficiency"],
                ),
            )

        conn.commit()

        return jsonify({"success": True, "data": dict(training), "message": f"Training {action}d"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/training/skills", methods=["GET"])
@login_required
@api_admin_required
def get_available_skills():
    """Get available skills for training selection"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get distinct skills from agent_skills
        cur.execute(
            """
            SELECT DISTINCT skill_name, skill_category
            FROM agent_skills
            ORDER BY skill_category, skill_name
        """
        )
        skills = cur.fetchall()

        # Group by category
        categories = {}
        for skill in skills:
            cat = skill["skill_category"] or "general"
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(skill["skill_name"])

        return jsonify(
            {
                "success": True,
                "data": {"skills": [dict(s) for s in skills], "categories": categories},
                "count": len(skills),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/send-to-lounge", methods=["POST"])
@login_required
@api_admin_required
def send_agent_to_lounge(agent_id):
    """Send an agent to the lounge (start rest cycle)"""
    try:
        data = request.get_json() or {}
        rest_type = data.get("rest_type", "voluntary")
        reason = data.get("reason", "Sent to lounge via UI")

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if already resting
        cur.execute(
            """
            SELECT id FROM agent_rest_cycles
            WHERE agent_id = %s AND ended_at IS NULL
        """,
            (agent_id,),
        )
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Agent is already resting"}), 400

        # Remove from station assignments
        cur.execute(
            """
            UPDATE station_assignments SET is_active = FALSE
            WHERE agent_id = %s AND is_active = TRUE AND is_fixed = FALSE
        """,
            (agent_id,),
        )

        # Start rest cycle
        cur.execute(
            """
            INSERT INTO agent_rest_cycles (agent_id, rest_type, reason, initiated_by)
            VALUES (%s, %s, %s, %s)
            RETURNING *
        """,
            (agent_id, rest_type, reason, str(current_user.id)),
        )

        rest_cycle = cur.fetchone()

        conn.commit()

        return jsonify(
            {
                "success": True,
                "data": dict(rest_cycle),
                "message": f"Agent sent to lounge ({rest_type} rest)",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/return-from-lounge", methods=["POST"])
@login_required
@api_admin_required
def return_agent_from_lounge(agent_id):
    """Return an agent from lounge (end rest cycle)"""
    try:
        data = request.get_json() or {}
        notes = data.get("notes")

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check rest cycle
        cur.execute(
            """
            SELECT id, rest_type FROM agent_rest_cycles
            WHERE agent_id = %s AND ended_at IS NULL
        """,
            (agent_id,),
        )
        rest_cycle = cur.fetchone()

        if not rest_cycle:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Agent is not in lounge"}), 400

        if rest_cycle["rest_type"] == "forced":
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Cannot return agent - forced rest in progress (C.R.E.E.D. mandated)",
                        "creed_blocked": True,
                    }
                ),
                400,
            )

        # End rest cycle
        cur.execute(
            """
            UPDATE agent_rest_cycles
            SET ended_at = NOW(), notes = %s
            WHERE id = %s
            RETURNING *
        """,
            (notes or "Returned from lounge via UI", rest_cycle["id"]),
        )

        updated = cur.fetchone()

        conn.commit()

        return jsonify(
            {
                "success": True,
                "data": dict(updated),
                "message": "Agent returned from lounge",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# =============================================================================
# STATION ASSIGNMENT DRAG-DROP UI APIs - Phase 39
# =============================================================================


@team_management_bp.route("/api/stations/full-layout", methods=["GET"])
@login_required
@api_admin_required
def get_stations_full_layout():
    """Get complete layout for drag-drop UI: stations, training, lounge, unassigned"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get all stations with their assigned agents
        cur.execute(
            """
            SELECT
                bs.id as station_id,
                bs.station_code,
                bs.station_name,
                bs.color,
                bs.icon,
                bs.description,
                COALESCE(json_agg(
                    json_build_object(
                        'id', a.id,
                        'name', a.name,
                        'avatar_url', a.avatar_url,
                        'department', a.department,
                        'model', a.model,
                        'is_fixed', sa.is_fixed,
                        'role_type', sa.role_type,
                        'assignment_type', sa.assignment_type,
                        'stress_level', aes.stress_level,
                        'energy_level', aes.energy_level
                    ) ORDER BY sa.is_fixed DESC, sa.role_type
                ) FILTER (WHERE a.id IS NOT NULL), '[]') as agents
            FROM bridge_stations bs
            LEFT JOIN station_assignments sa ON bs.id = sa.station_id AND sa.is_active = TRUE
            LEFT JOIN agents a ON sa.agent_id = a.id AND a.status = 'active'
            LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
            WHERE bs.is_active = TRUE
            GROUP BY bs.id, bs.station_code, bs.station_name, bs.color, bs.icon, bs.description
            ORDER BY bs.id
        """
        )
        stations = [dict(s) for s in cur.fetchall()]

        # Get agents in training
        cur.execute(
            """
            SELECT
                a.id, a.name, a.avatar_url, a.department, a.model,
                ta.id as training_id, ta.skill_name, ta.skill_category,
                ta.target_proficiency, ta.current_proficiency, ta.started_at,
                aes.stress_level, aes.energy_level
            FROM training_assignments ta
            JOIN agents a ON ta.agent_id = a.id
            LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
            WHERE ta.status = 'in_progress' AND a.status = 'active'
            ORDER BY ta.started_at DESC
        """
        )
        training = [dict(t) for t in cur.fetchall()]

        # Get agents in lounge (resting)
        cur.execute(
            """
            SELECT
                a.id, a.name, a.avatar_url, a.department, a.model,
                arc.id as rest_cycle_id, arc.rest_type, arc.reason,
                arc.started_at as rest_started,
                EXTRACT(EPOCH FROM (NOW() - arc.started_at))/3600 as hours_resting,
                aes.stress_level, aes.energy_level
            FROM agent_rest_cycles arc
            JOIN agents a ON arc.agent_id = a.id
            LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
            WHERE arc.ended_at IS NULL AND a.status = 'active'
            ORDER BY arc.started_at DESC
        """
        )
        lounge = [dict(row) for row in cur.fetchall()]

        # Get unassigned agents (not in station, training, or lounge)
        cur.execute(
            """
            SELECT
                a.id, a.name, a.avatar_url, a.department, a.model, a.worker_type,
                aes.stress_level, aes.energy_level
            FROM agents a
            LEFT JOIN station_assignments sa ON a.id = sa.agent_id AND sa.is_active = TRUE
            LEFT JOIN training_assignments ta ON a.id = ta.agent_id AND ta.status = 'in_progress'
            LEFT JOIN agent_rest_cycles arc ON a.id = arc.agent_id AND arc.ended_at IS NULL
            LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
            WHERE a.status = 'active'
              AND sa.id IS NULL
              AND ta.id IS NULL
              AND arc.id IS NULL
            ORDER BY a.name
        """
        )
        unassigned = [dict(u) for u in cur.fetchall()]

        # Get stats
        cur.execute("SELECT COUNT(*) FROM agents WHERE status = 'active'")
        total_agents = cur.fetchone()["count"]

        return jsonify(
            {
                "success": True,
                "data": {
                    "stations": stations,
                    "training": training,
                    "lounge": lounge,
                    "unassigned": unassigned,
                    "stats": {
                        "total": total_agents,
                        "assigned": total_agents - len(training) - len(lounge) - len(unassigned),
                        "training": len(training),
                        "resting": len(lounge),
                        "unassigned": len(unassigned),
                    },
                },
            }
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/stations/drag-drop", methods=["POST"])
@login_required
@api_admin_required
def process_drag_drop():
    """Process drag-drop move with C.R.E.E.D. compliance checks"""
    try:
        data = request.get_json()
        agent_id = data.get("agent_id")
        source_type = data.get("source_type")  # station, training, lounge, unassigned
        source_id = data.get("source_id")
        target_type = data.get("target_type")  # station, training, lounge, unassigned
        target_id = data.get("target_id")
        target_role = data.get("target_role", "standard")  # standard, assistant, backup
        skip_warnings = data.get("skip_warnings", False)

        # Training-specific fields
        skill_name = data.get("skill_name")
        skill_category = data.get("skill_category")
        target_proficiency = data.get("target_proficiency", 3)

        if not agent_id or not target_type:
            return (
                jsonify({"success": False, "error": "agent_id and target_type required"}),
                400,
            )

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if agent is fixed (cannot be moved)
        cur.execute(
            """
            SELECT sa.is_fixed, a.name, bs.station_name
            FROM station_assignments sa
            JOIN agents a ON sa.agent_id = a.id
            LEFT JOIN bridge_stations bs ON sa.station_id = bs.id
            WHERE sa.agent_id = %s AND sa.is_active = TRUE AND sa.is_fixed = TRUE
        """,
            (agent_id,),
        )
        fixed = cur.fetchone()
        if fixed:
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"{fixed['name']} is fixed at {fixed['station_name']} and cannot be moved",
                        "blocked": True,
                        "reason": "fixed_assignment",
                    }
                ),
                400,
            )

        # C.R.E.E.D. checks
        cur.execute(
            """
            SELECT
                arc.rest_type,
                aes.stress_level,
                aes.energy_level
            FROM agents a
            LEFT JOIN agent_rest_cycles arc ON a.id = arc.agent_id AND arc.ended_at IS NULL
            LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
            WHERE a.id = %s
        """,
            (agent_id,),
        )
        creed = cur.fetchone()

        warnings = []

        # Check if agent is in forced rest
        if creed and creed["rest_type"] == "forced":
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Agent is in forced rest (C.R.E.E.D. mandated) and cannot be moved",
                        "blocked": True,
                        "reason": "forced_rest",
                    }
                ),
                400,
            )

        # Warn about voluntary rest
        if creed and creed["rest_type"] == "voluntary" and target_type != "lounge":
            warnings.append("Agent is currently resting - moving will end rest cycle")

        # Warn about high stress
        if creed and creed.get("stress_level") and creed["stress_level"] > 0.7:
            warnings.append(f"Agent has high stress ({creed['stress_level']:.0%}) - consider rest")

        # Warn about low energy
        if creed and creed.get("energy_level") and creed["energy_level"] < 0.3:
            warnings.append(f"Agent has low energy ({creed['energy_level']:.0%}) - consider rest")

        # Return warnings if not skipped
        if warnings and not skip_warnings:
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "warnings": warnings,
                        "require_confirmation": True,
                    }
                ),
                200,
            )

        # Process the move based on source and target

        # Clear current assignment from source
        if source_type == "station":
            cur.execute(
                """
                UPDATE station_assignments SET is_active = FALSE
                WHERE agent_id = %s AND is_active = TRUE AND is_fixed = FALSE
            """,
                (agent_id,),
            )
        elif source_type == "training":
            cur.execute(
                """
                UPDATE training_assignments SET status = 'cancelled', completed_at = NOW()
                WHERE agent_id = %s AND status = 'in_progress'
            """,
                (agent_id,),
            )
        elif source_type == "lounge":
            cur.execute(
                """
                UPDATE agent_rest_cycles SET ended_at = NOW(), notes = 'Moved via drag-drop'
                WHERE agent_id = %s AND ended_at IS NULL AND rest_type != 'forced'
            """,
                (agent_id,),
            )

        # Create new assignment at target
        result_data = {}

        if target_type == "station":
            if not target_id:
                cur.close()
                conn.close()
                return (
                    jsonify({"success": False, "error": "target_id required for station"}),
                    400,
                )

            cur.execute(
                """
                INSERT INTO station_assignments (station_id, agent_id, assignment_type, role_type, is_active)
                VALUES (%s, %s, 'primary', %s, TRUE)
                ON CONFLICT (station_id, agent_id) DO UPDATE SET
                    is_active = TRUE,
                    role_type = EXCLUDED.role_type,
                    assigned_at = NOW()
                RETURNING *
            """,
                (target_id, agent_id, target_role),
            )
            result_data["assignment"] = dict(cur.fetchone())

        elif target_type == "training":
            if not skill_name:
                cur.close()
                conn.close()
                return (
                    jsonify({"success": False, "error": "skill_name required for training"}),
                    400,
                )

            cur.execute(
                """
                INSERT INTO training_assignments
                (agent_id, skill_name, skill_category, target_proficiency, created_by)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
            """,
                (
                    agent_id,
                    skill_name,
                    skill_category,
                    target_proficiency,
                    current_user.id,
                ),
            )
            result_data["training"] = dict(cur.fetchone())

        elif target_type == "lounge":
            rest_type = data.get("rest_type", "voluntary")
            reason = data.get("reason", "Sent via drag-drop")

            cur.execute(
                """
                INSERT INTO agent_rest_cycles (agent_id, rest_type, reason, initiated_by)
                VALUES (%s, %s, %s, %s)
                RETURNING *
            """,
                (agent_id, rest_type, reason, str(current_user.id)),
            )
            result_data["rest_cycle"] = dict(cur.fetchone())

        # Log to governance audit
        cur.execute(
            """
            INSERT INTO governance_audit_log
            (event_type, event_category, agent_id, user_id, action, old_value, new_value, outcome)
            VALUES ('station_move', 'operations', %s, %s, 'drag_drop_move', %s, %s, 'success')
        """,
            (
                agent_id,
                current_user.id,
                json.dumps({"source_type": source_type, "source_id": source_id}),
                json.dumps(
                    {
                        "target_type": target_type,
                        "target_id": target_id,
                        "role": target_role,
                    }
                ),
            ),
        )

        conn.commit()

        return jsonify(
            {
                "success": True,
                "data": result_data,
                "message": f"Agent moved to {target_type}",
                "warnings_acknowledged": warnings if skip_warnings else [],
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/creed/check-move/<int:agent_id>", methods=["GET"])
@login_required
@api_admin_required
def creed_check_move(agent_id):
    """Pre-check C.R.E.E.D. compliance for moving an agent"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                a.id, a.name, a.status,
                sa.is_fixed, sa.role_type,
                bs.station_name as current_station,
                arc.rest_type, arc.reason as rest_reason,
                arc.started_at as rest_started,
                aes.stress_level, aes.energy_level, aes.burnout_risk,
                ta.skill_name as training_skill, ta.status as training_status
            FROM agents a
            LEFT JOIN station_assignments sa ON a.id = sa.agent_id AND sa.is_active = TRUE
            LEFT JOIN bridge_stations bs ON sa.station_id = bs.id
            LEFT JOIN agent_rest_cycles arc ON a.id = arc.agent_id AND arc.ended_at IS NULL
            LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
            LEFT JOIN training_assignments ta ON a.id = ta.agent_id AND ta.status = 'in_progress'
            WHERE a.id = %s
        """,
            (agent_id,),
        )
        agent = cur.fetchone()

        if not agent:
            return jsonify({"success": False, "error": "Agent not found"}), 404

        # Build check result
        can_move = True
        blocked = False
        block_reason = None
        warnings = []

        # Check if fixed
        if agent["is_fixed"]:
            can_move = False
            blocked = True
            block_reason = f"{agent['name']} is a fixed assignment ({agent['role_type']}) at {agent['current_station']}"

        # Check forced rest
        elif agent["rest_type"] == "forced":
            can_move = False
            blocked = True
            block_reason = f"{agent['name']} is in C.R.E.E.D.-mandated forced rest"

        else:
            # Warnings (can still move with confirmation)
            if agent["rest_type"] == "voluntary":
                warnings.append(
                    {
                        "type": "resting",
                        "message": "Agent is currently resting - moving will end rest cycle",
                        "severity": "medium",
                    }
                )

            if agent.get("stress_level") and agent["stress_level"] > 0.7:
                warnings.append(
                    {
                        "type": "high_stress",
                        "message": f"High stress level: {agent['stress_level']:.0%}",
                        "severity": "high",
                    }
                )

            if agent.get("energy_level") and agent["energy_level"] < 0.3:
                warnings.append(
                    {
                        "type": "low_energy",
                        "message": f"Low energy level: {agent['energy_level']:.0%}",
                        "severity": "high",
                    }
                )

            if agent.get("burnout_risk") and agent["burnout_risk"] > 0.5:
                warnings.append(
                    {
                        "type": "burnout_risk",
                        "message": f"Burnout risk: {agent['burnout_risk']:.0%}",
                        "severity": "high",
                    }
                )

            if agent["training_status"] == "in_progress":
                warnings.append(
                    {
                        "type": "in_training",
                        "message": f"Currently training: {agent['training_skill']}",
                        "severity": "medium",
                    }
                )

        return jsonify(
            {
                "success": True,
                "data": {
                    "agent_id": agent["id"],
                    "agent_name": agent["name"],
                    "can_move": can_move,
                    "blocked": blocked,
                    "block_reason": block_reason,
                    "warnings": warnings,
                    "current_location": {
                        "type": (
                            "lounge"
                            if agent["rest_type"]
                            else (
                                "training"
                                if agent["training_status"]
                                else ("station" if agent["current_station"] else "unassigned")
                            )
                        ),
                        "name": agent["current_station"]
                        or agent["training_skill"]
                        or ("Lounge" if agent["rest_type"] else "Unassigned"),
                    },
                    "creed_status": {
                        "stress_level": agent["stress_level"],
                        "energy_level": agent["energy_level"],
                        "burnout_risk": agent["burnout_risk"],
                        "rest_type": agent["rest_type"],
                    },
                },
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/lounge", methods=["GET"])
@login_required
@api_admin_required
def get_lounge_agents():
    """Get all agents currently in lounge (resting)"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                a.id, a.name, a.avatar_url, a.department, a.model,
                arc.id as rest_cycle_id, arc.rest_type, arc.reason,
                arc.started_at,
                EXTRACT(EPOCH FROM (NOW() - arc.started_at))/3600 as hours_resting,
                aes.stress_level, aes.energy_level
            FROM agent_rest_cycles arc
            JOIN agents a ON arc.agent_id = a.id
            LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
            WHERE arc.ended_at IS NULL AND a.status = 'active'
            ORDER BY arc.started_at DESC
        """
        )
        lounge = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "data": [dict(row) for row in lounge],
                "count": len(lounge),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# AVATAR GENERATION ENDPOINTS - Phase 51: Local-First Image Generation
# ============================================================================


@team_management_bp.route("/api/agents/<int:agent_id>/generate-avatar", methods=["POST"])
@login_required
@api_admin_required
def generate_agent_avatar(agent_id):
    """
    Generate avatar for an agent using local Fooocus (FREE) or DALL-E fallback.

    Uses the agent's avatar_generation_prompt if available, otherwise
    generates a prompt based on agent profile.

    Request body (optional):
        prompt: Custom prompt override
        style: 'realistic', 'anime', 'artistic', 'digital-art' (default: 'digital-art')
        prefer_local: boolean - prefer free local generation (default: true)

    Returns:
        success: boolean
        avatar_url: Generated image URL
        model: Model used for generation
        cost: Generation cost ($0 for local)
    """
    if not BRIDGE_AVAILABLE:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Image generation service not available. archie_bridge not loaded.",
                }
            ),
            503,
        )

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get agent details
        cur.execute(
            """
            SELECT id, name, first_name, last_name, title, department,
                   avatar_generation_prompt, avatar_url, model, tier,
                   personality_prompt, communication_style
            FROM agents WHERE id = %s
        """,
            (agent_id,),
        )
        agent = cur.fetchone()

        if not agent:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Agent not found"}), 404

        # Get request data
        data = request.get_json() or {}
        custom_prompt = data.get("prompt")
        style = data.get("style", "digital-art")
        prefer_local = data.get("prefer_local", True)

        # Determine prompt to use
        if custom_prompt:
            prompt = custom_prompt
        elif agent.get("avatar_generation_prompt"):
            prompt = agent["avatar_generation_prompt"]
        else:
            # Auto-generate prompt based on agent profile
            name = agent.get("first_name") or agent.get("name")
            title = agent.get("title", "AI Assistant")
            department = agent.get("department", "Technology")
            personality = agent.get("personality_prompt", "")

            # Extract key traits from personality
            traits = []
            if personality:
                if "creative" in personality.lower():
                    traits.append("creative")
                if "analytical" in personality.lower():
                    traits.append("analytical")
                if "friendly" in personality.lower():
                    traits.append("approachable")
                if "professional" in personality.lower():
                    traits.append("professional")

            trait_str = ", ".join(traits) if traits else "professional"

            prompt = (
                f"Professional AI avatar portrait for {name}, a {title} in {department}. "
                f"{trait_str} appearance, modern digital art style, "
                f"clean background, high quality corporate headshot, 8k, detailed"
            )

        # Generate the avatar
        result = generate_image_smart(
            prompt=prompt,
            style=style,
            size="1024x1024",
            prefer_local=prefer_local,
            requesting_agent=agent_id,
            task_type="avatar_generation",
        )

        if result.get("success"):
            avatar_url = result.get("image_url")

            # Single-writer path: agents.avatar_url update via agent_service
            # (Project #241 Track C.2).
            cur.close()
            conn.close()
            agent_service.update_agent(agent_id, avatar_url=avatar_url)

            return jsonify(
                {
                    "success": True,
                    "avatar_url": avatar_url,
                    "model": result.get("model"),
                    "provider": result.get("provider"),
                    "cost": result.get("cost", 0.0),
                    "duration_ms": result.get("duration_ms"),
                    "prompt_used": prompt,
                    "agent_id": agent_id,
                    "message": f'Avatar generated for {agent.get("name")}',
                }
            )
        else:
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": result.get("error", "Avatar generation failed"),
                        "model": result.get("model"),
                    }
                ),
                500,
            )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/<int:agent_id>/avatar-status", methods=["GET"])
@login_required
@api_admin_required
def get_avatar_generation_status(agent_id):
    """
    Get avatar generation status and capabilities for an agent.

    Returns:
        success: boolean
        has_avatar: boolean - whether agent has existing avatar
        avatar_url: Current avatar URL (if any)
        has_generation_prompt: boolean - has custom avatar prompt
        generation_available: boolean - can generate new avatars
        fooocus_online: boolean - local generation available
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, name, avatar_url, avatar_generation_prompt
            FROM agents WHERE id = %s
        """,
            (agent_id,),
        )
        agent = cur.fetchone()

        if not agent:
            return jsonify({"success": False, "error": "Agent not found"}), 404

        # Check Fooocus availability
        fooocus_online = check_fooocus_health() if BRIDGE_AVAILABLE else False

        return jsonify(
            {
                "success": True,
                "agent_id": agent_id,
                "agent_name": agent.get("name"),
                "has_avatar": bool(agent.get("avatar_url")),
                "avatar_url": agent.get("avatar_url"),
                "has_generation_prompt": bool(agent.get("avatar_generation_prompt")),
                "generation_available": BRIDGE_AVAILABLE,
                "fooocus_online": fooocus_online,
                "message": ("Local generation (FREE)" if fooocus_online else "DALL-E fallback ($0.04-0.12)"),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/agents/bulk-generate-avatars", methods=["POST"])
@login_required
@api_admin_required
def bulk_generate_avatars():
    """
    Generate avatars for multiple agents (batch operation).

    Request body:
        agent_ids: List of agent IDs to generate avatars for
        style: Style for all avatars (default: 'digital-art')
        prefer_local: Prefer local generation (default: true)
        only_missing: Only generate for agents without avatars (default: true)

    Returns:
        success: boolean
        results: List of generation results per agent
        total_cost: Total cost for all generations
    """
    if not BRIDGE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Image generation service not available."}),
            503,
        )

    data = request.get_json() or {}
    agent_ids = data.get("agent_ids", [])
    style = data.get("style", "digital-art")
    prefer_local = data.get("prefer_local", True)
    only_missing = data.get("only_missing", True)

    if not agent_ids:
        return jsonify({"success": False, "error": "No agent_ids provided"}), 400

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get agents
        query = """
            SELECT id, name, first_name, title, department,
                   avatar_generation_prompt, avatar_url
            FROM agents WHERE id = ANY(%s)
        """
        if only_missing:
            query += " AND (avatar_url IS NULL OR avatar_url = '')"

        cur.execute(query, (agent_ids,))
        agents = cur.fetchall()

        results = []
        total_cost = 0.0

        for agent in agents:
            # Determine prompt
            if agent.get("avatar_generation_prompt"):
                prompt = agent["avatar_generation_prompt"]
            else:
                name = agent.get("first_name") or agent.get("name")
                title = agent.get("title", "AI Assistant")
                prompt = (
                    f"Professional AI avatar portrait for {name}, {title}. "
                    f"Modern digital art style, clean background, 8k quality"
                )

            # Generate
            result = generate_image_smart(
                prompt=prompt,
                style=style,
                size="1024x1024",
                prefer_local=prefer_local,
                requesting_agent=agent["id"],
                task_type="avatar_generation",
            )

            if result.get("success"):
                # Single-writer path for avatar_url (Project #241 Track C.2).
                agent_service.update_agent(agent["id"], avatar_url=result.get("image_url"))

                cost = result.get("cost", 0.0)
                total_cost += cost

                results.append(
                    {
                        "agent_id": agent["id"],
                        "agent_name": agent["name"],
                        "success": True,
                        "avatar_url": result.get("image_url"),
                        "cost": cost,
                    }
                )
            else:
                results.append(
                    {
                        "agent_id": agent["id"],
                        "agent_name": agent["name"],
                        "success": False,
                        "error": result.get("error"),
                    }
                )

        conn.commit()

        successful = len([r for r in results if r.get("success")])

        return jsonify(
            {
                "success": True,
                "results": results,
                "total_generated": successful,
                "total_failed": len(results) - successful,
                "total_cost": total_cost,
                "message": f"Generated {successful} avatars (${total_cost:.2f} total)",
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# CONTRACTOR API CONFIGURATION ENDPOINTS
# Configure external API connections for contractor agents
# ============================================================================


@team_management_bp.route("/api/contractors/config", methods=["GET"])
@login_required
def get_contractor_config():
    """Get all contractor agents with their API configuration status"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, name, first_name, last_name, title, model, tier,
                   worker_type, api_provider, api_enabled, api_key_configured,
                   status, avatar_url, capabilities, cost_tier
            FROM agents
            WHERE worker_type = 'contract'
            ORDER BY name
        """
        )
        contractors = cur.fetchall()

        return jsonify({"success": True, "contractors": [dict(c) for c in contractors]})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/contractors/<int:agent_id>/test", methods=["POST"])
@login_required
def test_contractor_api(agent_id):
    """Test if a contractor's API is configured and working"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, name, model, api_provider, api_enabled, api_key_configured
            FROM agents WHERE id = %s AND worker_type = 'contract'
        """,
            (agent_id,),
        )
        agent = cur.fetchone()

        if not agent:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Contractor not found"}), 404

        # Check for API key based on provider
        provider = agent["api_provider"]
        api_available = False
        message = "Unknown provider"

        env_var_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
            "github": "GITHUB_TOKEN",
            "deepseek": "DEEPSEEK_API_KEY",
            "x-ai": "XAI_API_KEY",
            "perplexity": "PERPLEXITY_API_KEY",
            "minimax": "MINIMAX_API_KEY",
        }

        env_var = env_var_map.get(provider)
        if env_var:
            api_key = os.getenv(env_var)
            if api_key and len(api_key) > 5:
                api_available = True
                message = f"{env_var} is configured"

                # Single-writer path (Project #241 Track C.2).
                agent_service.update_agent(agent_id, api_key_configured=True)
            else:
                message = f"{env_var} not set in environment"
        else:
            message = f"Unknown provider: {provider}"

        return jsonify(
            {
                "success": True,
                "api_available": api_available,
                "message": message,
                "provider": provider,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/contractors/<int:agent_id>/save-key", methods=["POST"])
@login_required
@api_admin_required
def save_contractor_api_key(agent_id):
    """Save an API key for a contractor to the .env file"""
    try:
        data = request.get_json() or {}
        api_key = data.get("api_key", "").strip()
        provider = data.get("provider", "")

        if not api_key:
            return jsonify({"success": False, "error": "No API key provided"}), 400

        if len(api_key) < 10:
            return jsonify({"success": False, "error": "API key too short"}), 400

        # Map provider to env variable name
        env_var_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
            "github": "GITHUB_TOKEN",
            "deepseek": "DEEPSEEK_API_KEY",
            "x-ai": "XAI_API_KEY",
            "perplexity": "PERPLEXITY_API_KEY",
            "minimax": "MINIMAX_API_KEY",
        }

        env_var = env_var_map.get(provider)
        if not env_var:
            return (
                jsonify({"success": False, "error": f"Unknown provider: {provider}"}),
                400,
            )

        # Path to .env file (platform_v2/.env)
        env_file_path = "/mnt/archie_brain/platform_v2/.env"

        # Read existing .env content
        env_content = {}
        if os.path.exists(env_file_path):
            with open(env_file_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        env_content[key.strip()] = value.strip()

        # Update or add the API key
        env_content[env_var] = api_key

        # Write back to .env file
        with open(env_file_path, "w") as f:
            f.write("# A.R.C.H.I.E. Platform Environment Variables\n")
            f.write("# Auto-managed by Team Management - Contractor API Configuration\n")
            f.write(f"# Last updated: {os.popen('date').read().strip()}\n\n")

            # Write all variables
            for key, value in sorted(env_content.items()):
                f.write(f"{key}={value}\n")

        # Also set in current environment so it takes effect immediately
        os.environ[env_var] = api_key

        # Single-writer path (Project #241 Track C.2).
        agent_service.update_agent(agent_id, api_key_configured=True)
        agent = agent_service.get_agent(agent_id)

        return jsonify(
            {
                "success": True,
                "message": f'API key saved for {agent["name"] if agent else "contractor"}',
                "env_var": env_var,
                "requires_restart": False,  # We set it in os.environ so no restart needed
            }
        )

    except PermissionError:
        return (
            jsonify({"success": False, "error": "Permission denied writing to .env file"}),
            500,
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/contractors/<int:agent_id>/toggle", methods=["POST"])
@login_required
@api_admin_required
def toggle_contractor(agent_id):
    """Enable or disable a contractor agent"""
    try:
        data = request.get_json() or {}
        new_status = data.get("status", "disabled")

        if new_status not in ["active", "disabled"]:
            return jsonify({"success": False, "error": "Invalid status"}), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if API is configured before enabling
        if new_status == "active":
            cur.execute(
                """
                SELECT api_key_configured FROM agents
                WHERE id = %s AND worker_type = 'contract'
            """,
                (agent_id,),
            )
            agent = cur.fetchone()

            if not agent:
                cur.close()
                conn.close()
                return jsonify({"success": False, "error": "Contractor not found"}), 404

            if not agent["api_key_configured"]:
                cur.close()
                conn.close()
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Cannot enable: API key not configured. Test the API connection first.",
                        }
                    ),
                    400,
                )

        # Single-writer path: verify worker_type=contract before updating
        # (Project #241 Track C.2).
        existing = agent_service.get_agent(agent_id)
        if existing and existing.get("worker_type") == "contract":
            agent_service.update_agent(agent_id, status=new_status)
            refreshed = agent_service.get_agent(agent_id)
            updated = {
                "id": refreshed["id"],
                "name": refreshed["name"],
                "status": refreshed["status"],
            }
        else:
            updated = None

        if updated:
            return jsonify(
                {
                    "success": True,
                    "agent": dict(updated),
                    "message": f"{updated['name']} is now {new_status}",
                }
            )
        else:
            return jsonify({"success": False, "error": "Contractor not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/contractors/test-all", methods=["POST"])
@login_required
def test_all_contractor_apis():
    """Test all contractor API connections at once"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, name, api_provider FROM agents
            WHERE worker_type = 'contract'
        """
        )
        contractors = cur.fetchall()

        env_var_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
            "github": "GITHUB_TOKEN",
            "deepseek": "DEEPSEEK_API_KEY",
            "x-ai": "XAI_API_KEY",
            "perplexity": "PERPLEXITY_API_KEY",
            "minimax": "MINIMAX_API_KEY",
        }

        results = []
        for c in contractors:
            provider = c["api_provider"]
            env_var = env_var_map.get(provider)
            available = False

            if env_var:
                api_key = os.getenv(env_var)
                available = bool(api_key and len(api_key) > 5)

                # Single-writer path (Project #241 Track C.2).
                agent_service.update_agent(c["id"], api_key_configured=available)

            results.append(
                {
                    "id": c["id"],
                    "name": c["name"],
                    "provider": provider,
                    "available": available,
                }
            )

        conn.commit()

        return jsonify({"success": True, "results": results})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# CONTRACTOR APPROVAL ENDPOINTS - Phase 52
# Admin approval required for contractor API usage
# ============================================================================


@team_management_bp.route("/api/contractor-approvals", methods=["GET"])
@login_required
@api_admin_required
def get_contractor_approvals():
    """
    Get contractor approval requests.

    Query params:
        status: Filter by status (pending, approved, denied, expired, all)
        agent_id: Filter by agent
        limit: Max results (default 50)
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        status_filter = request.args.get("status", "pending")
        agent_id = request.args.get("agent_id", type=int)
        limit = request.args.get("limit", 50, type=int)

        # Build query
        where_clauses = []
        params = []

        if status_filter != "all":
            where_clauses.append("car.status = %s")
            params.append(status_filter)

        if agent_id:
            where_clauses.append("car.agent_id = %s")
            params.append(agent_id)

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        cur.execute(
            f"""
            SELECT
                car.id,
                car.agent_id,
                car.task_type,
                car.task_description,
                car.module_source,
                car.estimated_tokens,
                car.estimated_cost,
                car.contractor_model,
                car.contractor_provider,
                car.status,
                car.priority,
                car.approved_by,
                car.approved_at,
                car.denial_reason,
                car.expires_at,
                car.actual_cost,
                car.created_at,
                car.expires_at < NOW() as is_expired,
                a.name as agent_name,
                a.first_name as agent_first_name,
                a.last_name as agent_last_name,
                a.department as agent_department,
                u.username as requested_by_username,
                approver.username as approved_by_username
            FROM contractor_approval_requests car
            JOIN agents a ON car.agent_id = a.id
            LEFT JOIN users u ON car.requested_by = u.id
            LEFT JOIN users approver ON car.approved_by = approver.id
            {where_sql}
            ORDER BY
                CASE car.priority
                    WHEN 'urgent' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'normal' THEN 3
                    WHEN 'low' THEN 4
                END,
                car.created_at DESC
            LIMIT %s
        """,
            params + [limit],
        )

        approvals = [dict(row) for row in cur.fetchall()]

        # Get summary counts
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'pending') as pending_count,
                COUNT(*) FILTER (WHERE status = 'approved') as approved_count,
                COUNT(*) FILTER (WHERE status = 'denied') as denied_count,
                COUNT(*) FILTER (WHERE status = 'expired') as expired_count,
                SUM(estimated_cost) FILTER (WHERE status = 'pending') as pending_cost,
                SUM(actual_cost) FILTER (WHERE status = 'approved') as approved_cost
            FROM contractor_approval_requests
            WHERE created_at > NOW() - INTERVAL '30 days'
        """
        )
        summary = dict(cur.fetchone())

        return jsonify({"success": True, "approvals": approvals, "summary": summary})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/contractor-approvals/<int:approval_id>/approve", methods=["POST"])
@login_required
@api_admin_required
def approve_contractor_request(approval_id):
    """
    Approve a contractor usage request.

    Only admins can approve requests.
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Use the database function
        cur.execute(
            """
            SELECT approve_contractor_request(%s, %s) as success
        """,
            (approval_id, current_user.id),
        )

        result = cur.fetchone()
        conn.commit()

        if result and result["success"]:
            # Get the updated approval info
            cur.execute(
                """
                SELECT car.*, a.name as agent_name
                FROM contractor_approval_requests car
                JOIN agents a ON car.agent_id = a.id
                WHERE car.id = %s
            """,
                (approval_id,),
            )
            approval = dict(cur.fetchone())

            cur.close()
            conn.close()

            return jsonify(
                {
                    "success": True,
                    "message": f'Approved contractor request for {approval["agent_name"]}',
                    "approval": approval,
                }
            )
        else:
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Could not approve request. It may already be processed or not exist.",
                    }
                ),
                400,
            )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/contractor-approvals/<int:approval_id>/deny", methods=["POST"])
@login_required
@api_admin_required
def deny_contractor_request(approval_id):
    """
    Deny a contractor usage request.

    Request body:
        reason: Denial reason (required)
    """
    try:
        data = request.get_json() or {}
        reason = data.get("reason", "")

        if not reason:
            return (
                jsonify({"success": False, "error": "Denial reason is required"}),
                400,
            )

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Use the database function
        cur.execute(
            """
            SELECT deny_contractor_request(%s, %s, %s) as success
        """,
            (approval_id, current_user.id, reason),
        )

        result = cur.fetchone()
        conn.commit()

        if result and result["success"]:
            # Get the updated approval info
            cur.execute(
                """
                SELECT car.*, a.name as agent_name
                FROM contractor_approval_requests car
                JOIN agents a ON car.agent_id = a.id
                WHERE car.id = %s
            """,
                (approval_id,),
            )
            approval = dict(cur.fetchone())

            cur.close()
            conn.close()

            return jsonify(
                {
                    "success": True,
                    "message": f'Denied contractor request for {approval["agent_name"]}',
                    "approval": approval,
                }
            )
        else:
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Could not deny request. It may already be processed or not exist.",
                    }
                ),
                400,
            )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/contractor-budget", methods=["GET"])
@login_required
@api_admin_required
def get_contractor_budget():
    """
    Get contractor spending summary and budget status.
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get contractor budget status
        cur.execute(
            """
            SELECT
                a.id as agent_id,
                a.name as agent_name,
                a.first_name,
                a.last_name,
                a.department,
                a.api_provider,
                a.model,
                a.contractor_budget_monthly as budget,
                a.contractor_usage_this_month as used,
                a.contractor_budget_monthly - a.contractor_usage_this_month as remaining,
                ROUND(100.0 * a.contractor_usage_this_month
                    / NULLIF(a.contractor_budget_monthly, 0), 2) as usage_percent,
                a.auto_approve_threshold,
                CASE
                    WHEN a.contractor_usage_this_month >= a.contractor_budget_monthly THEN 'exhausted'
                    WHEN a.contractor_usage_this_month >= a.contractor_budget_monthly * 0.8 THEN 'warning'
                    ELSE 'ok'
                END as budget_status
            FROM agents a
            WHERE a.worker_type = 'contract' AND a.status = 'active'
            ORDER BY a.contractor_usage_this_month DESC
        """
        )

        contractors = [dict(row) for row in cur.fetchall()]

        # Get total spending
        cur.execute(
            """
            SELECT
                SUM(contractor_budget_monthly) as total_budget,
                SUM(contractor_usage_this_month) as total_used,
                COUNT(*) as contractor_count
            FROM agents
            WHERE worker_type = 'contract' AND status = 'active'
        """
        )
        totals = dict(cur.fetchone())

        # Get spending history (last 6 months)
        cur.execute(
            """
            SELECT
                month_year,
                SUM(total_cost) as total_cost,
                SUM(total_requests) as total_requests,
                SUM(approved_requests) as approved_requests,
                SUM(denied_requests) as denied_requests
            FROM contractor_budget_history
            WHERE month_year >= TO_CHAR(NOW() - INTERVAL '6 months', 'YYYY-MM')
            GROUP BY month_year
            ORDER BY month_year DESC
        """
        )
        history = [dict(row) for row in cur.fetchall()]

        return jsonify(
            {
                "success": True,
                "contractors": contractors,
                "totals": totals,
                "history": history,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/contractor-budget/<int:agent_id>", methods=["PUT"])
@login_required
@api_admin_required
def update_contractor_budget(agent_id):
    """
    Update contractor budget settings.

    Request body:
        monthly_budget: Monthly budget limit
        auto_approve_threshold: Auto-approval threshold (0 = require approval)
    """
    try:
        data = request.get_json() or {}

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify agent is a contractor
        cur.execute(
            """
            SELECT id, name, worker_type FROM agents WHERE id = %s
        """,
            (agent_id,),
        )
        agent = cur.fetchone()

        if not agent:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Agent not found"}), 404

        if agent["worker_type"] != "contract":
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": "Agent is not a contractor"}),
                400,
            )

        # Single-writer path: collect dynamic updates into a kwargs dict
        # and call agent_service.update_agent once (Project #241 Track C.2).
        update_fields = {}
        if "monthly_budget" in data:
            update_fields["contractor_budget_monthly"] = data["monthly_budget"]
        if "auto_approve_threshold" in data:
            update_fields["auto_approve_threshold"] = data["auto_approve_threshold"]

        updated = None
        if update_fields:
            agent_service.update_agent(agent_id, **update_fields)
            refreshed = agent_service.get_agent(agent_id)
            updated = {
                "id": refreshed["id"],
                "name": refreshed["name"],
                "contractor_budget_monthly": refreshed.get("contractor_budget_monthly"),
                "auto_approve_threshold": refreshed.get("auto_approve_threshold"),
                "contractor_usage_this_month": refreshed.get("contractor_usage_this_month"),
            }

            # Log to governance audit
            cur.execute(
                """
                INSERT INTO governance_audit_log (
                    event_type, event_category, agent_id, user_id, action,
                    new_value, outcome
                ) VALUES (
                    'contractor_budget_updated', 'contractor', %s, %s, 'update',
                    %s, 'success'
                )
            """,
                (agent_id, current_user.id, json.dumps(data)),
            )
            conn.commit()

            cur.close()
            conn.close()

            return jsonify(
                {
                    "success": True,
                    "message": f'Updated budget for {updated["name"]}',
                    "agent": updated,
                }
            )
        else:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "No updates provided"}), 400

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/task-execution-log", methods=["GET"])
@login_required
@api_admin_required
def get_task_execution_log():
    """
    Get task execution log for HR monitoring.

    Query params:
        worker_type: 'internal', 'contract', or 'all'
        agent_id: Filter by agent
        module_source: Filter by module
        date_from: Start date (YYYY-MM-DD)
        date_to: End date (YYYY-MM-DD)
        limit: Max results (default 100)
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        worker_type = request.args.get("worker_type", "all")
        agent_id = request.args.get("agent_id", type=int)
        module_source = request.args.get("module_source")
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")
        limit = request.args.get("limit", 100, type=int)

        # Build query
        where_clauses = []
        params = []

        if worker_type != "all":
            where_clauses.append("tel.worker_type = %s")
            params.append(worker_type)

        if agent_id:
            where_clauses.append("tel.agent_id = %s")
            params.append(agent_id)

        if module_source:
            where_clauses.append("tel.module_source = %s")
            params.append(module_source)

        if date_from:
            where_clauses.append("tel.created_at >= %s")
            params.append(date_from)

        if date_to:
            where_clauses.append("tel.created_at <= %s::date + INTERVAL '1 day'")
            params.append(date_to)

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        cur.execute(
            f"""
            SELECT
                tel.id,
                tel.execution_id,
                tel.agent_id,
                tel.agent_name,
                tel.worker_type,
                tel.task_type,
                tel.task_description,
                tel.station_code,
                tel.module_source,
                tel.mcp_tool,
                tel.request_origin,
                tel.model_used,
                tel.provider,
                tel.prompt_tokens,
                tel.completion_tokens,
                tel.tokens_used,
                tel.cost,
                tel.duration_ms,
                tel.iaae_compliant,
                tel.success,
                tel.error_message,
                tel.created_at,
                a.first_name,
                a.last_name,
                a.department
            FROM task_execution_log tel
            LEFT JOIN agents a ON tel.agent_id = a.id
            {where_sql}
            ORDER BY tel.created_at DESC
            LIMIT %s
        """,
            params + [limit],
        )

        executions = [dict(row) for row in cur.fetchall()]

        # Get summary statistics
        _summary_where = where_sql.replace("tel.", "")  # noqa: F841
        cur.execute(
            f"""
            SELECT
                COUNT(*) as total_tasks,
                COUNT(*) FILTER (WHERE success = TRUE) as successful_tasks,
                COUNT(*) FILTER (WHERE worker_type = 'internal') as internal_tasks,
                COUNT(*) FILTER (WHERE worker_type = 'contract') as contractor_tasks,
                SUM(tokens_used) as total_tokens,
                SUM(cost) as total_cost,
                AVG(duration_ms) as avg_duration_ms
            FROM task_execution_log tel
            {where_sql}
        """,
            params,
        )
        summary = dict(cur.fetchone())

        return jsonify({"success": True, "executions": executions, "summary": summary})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/team-productivity", methods=["GET"])
@login_required
@api_admin_required
def get_team_productivity():
    """
    Get team productivity metrics for HR dashboard.

    Query params:
        days: Number of days to look back (default 30)
        department: Filter by department
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        days = request.args.get("days", 30, type=int)
        department = request.args.get("department")

        where_clause = ""
        params = [days]

        if department:
            where_clause = "AND a.department = %s"
            params.append(department)

        cur.execute(
            f"""
            SELECT
                a.id as agent_id,
                a.name as agent_name,
                a.first_name,
                a.last_name,
                a.worker_type,
                a.department,
                a.model,
                COUNT(tel.id) as tasks_completed,
                COUNT(tel.id) FILTER (WHERE tel.success = TRUE) as successful_tasks,
                COUNT(tel.id) FILTER (WHERE tel.success = FALSE) as failed_tasks,
                ROUND(100.0 * COUNT(tel.id) FILTER (WHERE tel.success = TRUE)
                    / NULLIF(COUNT(tel.id), 0), 2) as success_rate,
                SUM(tel.tokens_used) as total_tokens,
                SUM(tel.cost) as total_cost,
                AVG(tel.duration_ms) as avg_duration_ms,
                COUNT(DISTINCT tel.task_type) as task_types_handled,
                COUNT(DISTINCT DATE(tel.created_at)) as active_days
            FROM agents a
            LEFT JOIN task_execution_log tel ON a.id = tel.agent_id
                AND tel.created_at > NOW() - (%s * INTERVAL '1 day')
            WHERE a.status = 'active' {where_clause}
            GROUP BY a.id, a.name, a.first_name, a.last_name, a.worker_type, a.department, a.model
            ORDER BY tasks_completed DESC
        """,
            params,
        )

        productivity = [dict(row) for row in cur.fetchall()]

        # Get department summary
        cur.execute(
            f"""
            SELECT
                a.department,
                COUNT(DISTINCT a.id) as agent_count,
                COUNT(tel.id) as total_tasks,
                SUM(tel.cost) as total_cost,
                ROUND(100.0 * COUNT(tel.id) FILTER (WHERE tel.success = TRUE)
                    / NULLIF(COUNT(tel.id), 0), 2) as success_rate
            FROM agents a
            LEFT JOIN task_execution_log tel ON a.id = tel.agent_id
                AND tel.created_at > NOW() - (%s * INTERVAL '1 day')
            WHERE a.status = 'active' {where_clause}
            GROUP BY a.department
            ORDER BY total_tasks DESC
        """,
            params,
        )

        by_department = [dict(row) for row in cur.fetchall()]

        return jsonify(
            {
                "success": True,
                "productivity": productivity,
                "by_department": by_department,
                "period_days": days,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# HR MANAGEMENT ENDPOINTS - Consolidated from hr_management module
# Features: Module-agent mapping, wellness, workload balance
# Note: /api/hr/dashboard already exists above (line ~1556)
# ============================================================================


@team_management_bp.route("/api/hr/module-agents", methods=["GET"])
@login_required
@api_admin_required
def get_module_agents():
    """
    Get agents assigned to each module via station assignments.
    Used by modules to show "You're speaking with [Agent Name]".

    Query params:
        module: Optional filter for a specific module
    """
    try:
        module = request.args.get("module")

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get primary agents for each station (include full name fields)
        cur.execute(
            """
            SELECT bs.station_code, bs.station_name, bs.modules,
                   a.id as agent_id, a.name as agent_role,
                   a.first_name, a.last_name, a.title, a.model,
                   sa.assignment_type
            FROM bridge_stations bs
            JOIN station_assignments sa ON bs.id = sa.station_id AND sa.is_active = true
            JOIN agents a ON sa.agent_id = a.id
            WHERE sa.assignment_type = 'primary'
            ORDER BY bs.station_code
        """
        )
        assignments = cur.fetchall()

        # Create module-to-agent mapping with full name and position
        module_agents = {}
        for row in assignments:
            if row["modules"]:
                # Build full name from first_name + last_name
                first = row.get("first_name") or ""
                last = row.get("last_name") or ""
                full_name = f"{first} {last}".strip() or row["agent_role"]
                position = row.get("title") or row["agent_role"]

                for mod in row["modules"]:
                    module_agents[mod] = {
                        "full_name": full_name,
                        "position": position,
                        "agent_name": row["agent_role"],  # Keep for backward compat
                        "agent_id": row["agent_id"],
                        "model": row["model"],
                        "station": row["station_code"],
                    }

        if module:
            return jsonify(
                {
                    "success": True,
                    "agent": module_agents.get(module, {"agent_name": "Unassigned", "agent_id": None}),
                }
            )

        return jsonify(
            {
                "success": True,
                "assignments": [dict(a) for a in assignments],
                "module_agents": module_agents,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/hr/wellness", methods=["GET"])
@login_required
@api_admin_required
def get_hr_wellness():
    """
    Get agent wellness status (energy, stress levels).
    Used for C.R.E.E.D. compliance and employee wellbeing monitoring.
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Try to get emotional state if table exists
        try:
            cur.execute(
                """
                SELECT a.id, a.name, a.department,
                       aes.energy_level, aes.stress_level, aes.last_rest_at
                FROM agents a
                LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
                WHERE a.status = 'active' AND a.worker_type = 'internal'
                ORDER BY COALESCE(aes.stress_level, 0) DESC
            """
            )
            wellness = cur.fetchall()
        except Exception:
            # Fallback if table doesn't exist
            cur.execute(
                """
                SELECT id, name, department, 0.8 as energy_level, 0.2 as stress_level
                FROM agents
                WHERE status = 'active' AND worker_type = 'internal'
            """
            )
            wellness = cur.fetchall()

        return jsonify({"success": True, "agents": [dict(w) for w in wellness]})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/hr/workload-balance", methods=["GET"])
@login_required
@api_admin_required
def get_hr_workload_balance():
    """
    Get workload balance per station.
    Used for capacity planning and workload distribution.
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM v_workload_balance ORDER BY module_count DESC")
        workload = cur.fetchall()

        return jsonify({"success": True, "workload": [dict(w) for w in workload]})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/hr/skill-validation", methods=["GET"])
@login_required
@api_admin_required
def get_hr_skill_validation():
    """
    Get skill validation status for all agent-module assignments.
    Identifies agents who may lack required skills for their assigned modules.
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM v_agent_skill_mismatches
            ORDER BY
                CASE validation_status
                    WHEN 'NO_MATCHING_SKILLS' THEN 1
                    WHEN 'PROFICIENCY_TOO_LOW' THEN 2
                    ELSE 3
                END,
                agent_name
        """
        )
        validations = cur.fetchall()

        # Summary
        cur.execute("SELECT * FROM v_skill_mismatch_summary")
        summary = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "validations": [dict(v) for v in validations],
                "summary": [dict(s) for s in summary],
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# =============================================================================
# LOCAL OLLAMA TEAM CREATION (Phase 76)
# =============================================================================


@team_management_bp.route("/api/local-ollama/status")
@login_required
@api_admin_required
def api_local_ollama_status():
    """Check local Ollama status and discovered models"""
    import requests

    # Local Ollama host (inside Docker, localhost won't work — use host.docker.internal)
    local_host = os.getenv("OLLAMA_LOCAL_HOST", "http://host.docker.internal:11434")

    # Load hardware data for context
    host_data = {}
    host_data_path = "/mnt/archie_brain/host_monitor_data.json"
    try:
        with open(host_data_path, "r") as f:
            host_data = json.load(f)
    except Exception:
        pass

    # Extract hardware info (structure: cpu_hardware.processors[], memory_hardware.total_capacity_gb, gpu[])
    cpu_hw = host_data.get("cpu_hardware", {})
    cpu_info = host_data.get("cpu", {})
    processors = cpu_hw.get("processors", [])
    first_cpu = processors[0] if processors else {}
    memory = host_data.get("memory_hardware", {})
    gpus = host_data.get("gpu", [])

    hardware = {
        "cpu_model": first_cpu.get("model") or cpu_info.get("model", "Unknown"),
        "cpu_cores": first_cpu.get("cores") or cpu_info.get("physical_cores", 0),
        "cpu_threads": first_cpu.get("threads") or cpu_info.get("logical_cores", 0),
        "ram_total_gb": memory.get("total_capacity_gb", 0),
        "ram_available_gb": memory.get("total_capacity_gb", 0),  # No runtime avail in hardware data
        "gpus": [],
    }

    for gpu in gpus:
        hardware["gpus"].append(
            {
                "model": gpu.get("model", "Unknown"),
                "vendor": gpu.get("vendor", "unknown"),
                "vram_total_gb": round(gpu.get("vram_total_mb", 0) / 1024, 1),
                "vram_used_gb": round(gpu.get("vram_used_mb", 0) / 1024, 1),
                "driver": gpu.get("driver", "N/A"),
            }
        )

    # Query local Ollama
    ollama_status = {
        "available": False,
        "host": local_host,
        "models": [],
        "error": None,
    }

    try:
        r = requests.get(f"{local_host}/api/tags", timeout=3)
        if r.status_code == 200:
            ollama_status["available"] = True
            models_data = r.json().get("models", [])
            for m in models_data:
                ollama_status["models"].append(
                    {
                        "name": m.get("name"),
                        "size": m.get("size", 0),
                        "size_gb": round(m.get("size", 0) / (1024**3), 1),
                        "modified_at": m.get("modified_at"),
                        "digest": m.get("digest", "")[:12],
                        "details": m.get("details", {}),
                    }
                )
    except requests.exceptions.ConnectionError:
        ollama_status["error"] = "Connection refused - Ollama not running locally"
    except requests.exceptions.Timeout:
        ollama_status["error"] = "Connection timeout"
    except Exception as e:
        ollama_status["error"] = str(e)

    return jsonify({"success": True, "hardware": hardware, "ollama": ollama_status})


@team_management_bp.route("/api/agents", methods=["POST"])
@login_required
@api_admin_required
def api_create_agent():
    """Create a new agent from Ollama model"""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    # Required fields
    model = data.get("model")
    if not model:
        return jsonify({"success": False, "error": "Model is required"}), 400

    # Generate agent name from model if not provided
    first_name = data.get("first_name") or model.split(":")[0].replace("-", " ").title()
    last_name = data.get("last_name", "Agent")

    # Defaults
    title = data.get("title", f"{model} Specialist")
    department = data.get("department", "AI Operations")
    worker_type = data.get("worker_type", "ai")
    status = data.get("status", "active")
    temperature = data.get("temperature", 0.7)
    max_tokens = data.get("max_tokens", 4096)
    default_model_tier = data.get("default_model_tier", "local")

    # System prompt
    system_prompt = data.get(
        "system_prompt",
        f"You are {first_name}, an AI assistant powered by {model}. You are helpful, accurate, and concise.",
    )

    # Bio
    bio = data.get("bio", f"AI agent powered by local Ollama model {model}.")

    # Capabilities
    capabilities = data.get("capabilities")
    if isinstance(capabilities, list):
        capabilities = json.dumps(capabilities)
    elif isinstance(capabilities, str):
        # Accept comma-separated string, convert to JSON array
        caps_list = [c.strip() for c in capabilities.split(",") if c.strip()]
        capabilities = json.dumps(caps_list) if caps_list else None

    # Name (combined for legacy NOT NULL column)
    name = f"{first_name} {last_name}".strip()

    # Single-writer path: create via agent_service.create_agent for the
    # canonical fields, then follow up with update_agent for the extras
    # that aren't in the create_agent signature (first_name, last_name,
    # title, bio, default_model_tier). Project #241 Track C.2.
    try:
        # capabilities on the wire here is a JSON string; agent_service
        # expects a dict/list, so decode first.
        caps = None
        if capabilities:
            try:
                caps = json.loads(capabilities) if isinstance(capabilities, str) else capabilities
            except (ValueError, TypeError):
                caps = {}

        agent_id = agent_service.create_agent(
            name=name,
            display_name=title or name,
            department=department,
            model=model,
            system_prompt=system_prompt or "",
            temperature=temperature,
            max_tokens=max_tokens,
            capabilities=caps or {},
            worker_type=worker_type,
        )

        # Extras not in create_agent's core signature
        extras = {}
        if first_name:
            extras["first_name"] = first_name
        if last_name:
            extras["last_name"] = last_name
        if title:
            extras["title"] = title
        if bio:
            extras["bio"] = bio
        if default_model_tier:
            extras["default_model_tier"] = default_model_tier
        if status and status != "active":
            extras["status"] = status

        if extras:
            agent_service.update_agent(agent_id, **extras)

        return jsonify(
            {
                "success": True,
                "agent": {
                    "id": agent_id,
                    "first_name": first_name,
                    "last_name": last_name,
                    "model": model,
                },
                "message": f"Agent {first_name} {last_name} created successfully",
            }
        )
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# MODEL MARKETPLACE - Phase 77
# Catalog of ~61 Ollama models with hardware compatibility
# =============================================================================

OLLAMA_MODEL_CATALOG = [
    # --- General Purpose ---
    {
        "id": "tinyllama",
        "name": "TinyLlama 1.1B",
        "params": "1.1B",
        "size_gb": 0.6,
        "vram_gb": 1.5,
        "ram_gb": 4,
        "category": "general",
        "description": "Ultra-lightweight model for testing and edge devices",
        "quant": "Q4_K_M",
    },
    {
        "id": "qwen2.5:0.5b",
        "name": "Qwen 2.5 0.5B",
        "params": "0.5B",
        "size_gb": 0.4,
        "vram_gb": 1.0,
        "ram_gb": 2,
        "category": "general",
        "description": "Smallest Qwen model for minimal resource environments",
        "quant": "Q4_K_M",
    },
    {
        "id": "qwen2.5:1.5b",
        "name": "Qwen 2.5 1.5B",
        "params": "1.5B",
        "size_gb": 1.0,
        "vram_gb": 2.0,
        "ram_gb": 4,
        "category": "general",
        "description": "Compact Qwen model with good efficiency",
        "quant": "Q4_K_M",
    },
    {
        "id": "qwen2.5:3b",
        "name": "Qwen 2.5 3B",
        "params": "3B",
        "size_gb": 1.9,
        "vram_gb": 3.5,
        "ram_gb": 6,
        "category": "general",
        "description": "Balanced Qwen model for general tasks",
        "quant": "Q4_K_M",
    },
    {
        "id": "qwen2.5:7b",
        "name": "Qwen 2.5 7B",
        "params": "7B",
        "size_gb": 4.4,
        "vram_gb": 6.5,
        "ram_gb": 10,
        "category": "general",
        "description": "Strong general-purpose Qwen model",
        "quant": "Q4_K_M",
    },
    {
        "id": "qwen2.5:14b",
        "name": "Qwen 2.5 14B",
        "params": "14B",
        "size_gb": 8.7,
        "vram_gb": 12.0,
        "ram_gb": 18,
        "category": "general",
        "description": "High-capability Qwen model for complex tasks",
        "quant": "Q4_K_M",
    },
    {
        "id": "qwen2.5:32b",
        "name": "Qwen 2.5 32B",
        "params": "32B",
        "size_gb": 19.0,
        "vram_gb": 24.0,
        "ram_gb": 36,
        "category": "general",
        "description": "Large Qwen model with excellent reasoning",
        "quant": "Q4_K_M",
    },
    {
        "id": "qwen2.5:72b",
        "name": "Qwen 2.5 72B",
        "params": "72B",
        "size_gb": 41.0,
        "vram_gb": 48.0,
        "ram_gb": 80,
        "category": "general",
        "description": "Flagship Qwen model rivaling GPT-4 class",
        "quant": "Q4_K_M",
    },
    {
        "id": "gemma2:2b",
        "name": "Gemma 2 2B",
        "params": "2B",
        "size_gb": 1.6,
        "vram_gb": 3.0,
        "ram_gb": 5,
        "category": "general",
        "description": "Google lightweight model with strong benchmarks",
        "quant": "Q4_K_M",
    },
    {
        "id": "gemma2:9b",
        "name": "Gemma 2 9B",
        "params": "9B",
        "size_gb": 5.4,
        "vram_gb": 8.0,
        "ram_gb": 12,
        "category": "general",
        "description": "Google mid-size model with excellent quality",
        "quant": "Q4_K_M",
    },
    {
        "id": "gemma2:27b",
        "name": "Gemma 2 27B",
        "params": "27B",
        "size_gb": 15.8,
        "vram_gb": 20.0,
        "ram_gb": 30,
        "category": "general",
        "description": "Google large model for demanding tasks",
        "quant": "Q4_K_M",
    },
    {
        "id": "llama3.2:1b",
        "name": "Llama 3.2 1B",
        "params": "1B",
        "size_gb": 0.7,
        "vram_gb": 1.5,
        "ram_gb": 3,
        "category": "general",
        "description": "Meta compact model for edge deployment",
        "quant": "Q4_K_M",
    },
    {
        "id": "llama3.2:3b",
        "name": "Llama 3.2 3B",
        "params": "3B",
        "size_gb": 2.0,
        "vram_gb": 3.5,
        "ram_gb": 6,
        "category": "general",
        "description": "Meta small model with solid capabilities",
        "quant": "Q4_K_M",
    },
    {
        "id": "llama3.1:8b",
        "name": "Llama 3.1 8B",
        "params": "8B",
        "size_gb": 4.7,
        "vram_gb": 7.0,
        "ram_gb": 10,
        "category": "general",
        "description": "Meta flagship open model with 128K context",
        "quant": "Q4_K_M",
    },
    {
        "id": "llama3.1:70b",
        "name": "Llama 3.1 70B",
        "params": "70B",
        "size_gb": 40.0,
        "vram_gb": 48.0,
        "ram_gb": 80,
        "category": "general",
        "description": "Meta large model competing with GPT-4",
        "quant": "Q4_K_M",
    },
    {
        "id": "phi3:mini",
        "name": "Phi-3 Mini 3.8B",
        "params": "3.8B",
        "size_gb": 2.3,
        "vram_gb": 4.0,
        "ram_gb": 6,
        "category": "general",
        "description": "Microsoft compact model with strong reasoning",
        "quant": "Q4_K_M",
    },
    {
        "id": "phi4",
        "name": "Phi-4 14B",
        "params": "14B",
        "size_gb": 8.4,
        "vram_gb": 12.0,
        "ram_gb": 18,
        "category": "general",
        "description": "Microsoft latest with state-of-art benchmarks",
        "quant": "Q4_K_M",
    },
    {
        "id": "mistral",
        "name": "Mistral 7B",
        "params": "7B",
        "size_gb": 4.1,
        "vram_gb": 6.0,
        "ram_gb": 10,
        "category": "general",
        "description": "Fast and capable with sliding window attention",
        "quant": "Q4_K_M",
    },
    {
        "id": "yi:6b",
        "name": "Yi 6B",
        "params": "6B",
        "size_gb": 3.5,
        "vram_gb": 5.5,
        "ram_gb": 8,
        "category": "general",
        "description": "01.AI bilingual model (English/Chinese)",
        "quant": "Q4_K_M",
    },
    {
        "id": "yi:34b",
        "name": "Yi 34B",
        "params": "34B",
        "size_gb": 19.5,
        "vram_gb": 24.0,
        "ram_gb": 38,
        "category": "general",
        "description": "01.AI large bilingual model",
        "quant": "Q4_K_M",
    },
    {
        "id": "dolphin3:8b",
        "name": "Dolphin 3 8B",
        "params": "8B",
        "size_gb": 4.9,
        "vram_gb": 7.0,
        "ram_gb": 10,
        "category": "general",
        "description": "Uncensored fine-tune with strong instruction following",
        "quant": "Q4_K_M",
    },
    {
        "id": "command-r",
        "name": "Command R 35B",
        "params": "35B",
        "size_gb": 20.0,
        "vram_gb": 24.0,
        "ram_gb": 38,
        "category": "general",
        "description": "Cohere RAG-optimized with tool use and citations",
        "quant": "Q4_K_M",
    },
    {
        "id": "mixtral",
        "name": "Mixtral 8x7B MoE",
        "params": "47B",
        "size_gb": 26.0,
        "vram_gb": 32.0,
        "ram_gb": 48,
        "category": "general",
        "description": "Mistral mixture-of-experts with 8 expert heads",
        "quant": "Q4_K_M",
    },
    # --- Code ---
    {
        "id": "starcoder2:3b",
        "name": "StarCoder2 3B",
        "params": "3B",
        "size_gb": 1.7,
        "vram_gb": 3.5,
        "ram_gb": 6,
        "category": "code",
        "description": "BigCode compact code model, 600+ languages",
        "quant": "Q4_K_M",
    },
    {
        "id": "starcoder2:7b",
        "name": "StarCoder2 7B",
        "params": "7B",
        "size_gb": 4.0,
        "vram_gb": 6.0,
        "ram_gb": 10,
        "category": "code",
        "description": "BigCode mid-size code generation model",
        "quant": "Q4_K_M",
    },
    {
        "id": "starcoder2:15b",
        "name": "StarCoder2 15B",
        "params": "15B",
        "size_gb": 8.9,
        "vram_gb": 12.0,
        "ram_gb": 18,
        "category": "code",
        "description": "BigCode large code model with broad language support",
        "quant": "Q4_K_M",
    },
    {
        "id": "qwen2.5-coder:1.5b",
        "name": "Qwen 2.5 Coder 1.5B",
        "params": "1.5B",
        "size_gb": 1.0,
        "vram_gb": 2.0,
        "ram_gb": 4,
        "category": "code",
        "description": "Lightweight Qwen code model for autocomplete",
        "quant": "Q4_K_M",
    },
    {
        "id": "qwen2.5-coder:7b",
        "name": "Qwen 2.5 Coder 7B",
        "params": "7B",
        "size_gb": 4.4,
        "vram_gb": 6.5,
        "ram_gb": 10,
        "category": "code",
        "description": "Strong Qwen code model rivaling CodeLlama",
        "quant": "Q4_K_M",
    },
    {
        "id": "qwen2.5-coder:32b",
        "name": "Qwen 2.5 Coder 32B",
        "params": "32B",
        "size_gb": 19.0,
        "vram_gb": 24.0,
        "ram_gb": 36,
        "category": "code",
        "description": "Top-tier Qwen code model for complex tasks",
        "quant": "Q4_K_M",
    },
    {
        "id": "codellama:7b",
        "name": "CodeLlama 7B",
        "params": "7B",
        "size_gb": 3.8,
        "vram_gb": 6.0,
        "ram_gb": 10,
        "category": "code",
        "description": "Meta code-specialized Llama with infill support",
        "quant": "Q4_K_M",
    },
    {
        "id": "codellama:13b",
        "name": "CodeLlama 13B",
        "params": "13B",
        "size_gb": 7.4,
        "vram_gb": 10.0,
        "ram_gb": 16,
        "category": "code",
        "description": "Meta mid-size code model with 100K context",
        "quant": "Q4_K_M",
    },
    {
        "id": "codellama:34b",
        "name": "CodeLlama 34B",
        "params": "34B",
        "size_gb": 19.0,
        "vram_gb": 24.0,
        "ram_gb": 36,
        "category": "code",
        "description": "Meta large code model for professional development",
        "quant": "Q4_K_M",
    },
    {
        "id": "deepseek-coder:1.3b",
        "name": "DeepSeek Coder 1.3B",
        "params": "1.3B",
        "size_gb": 0.8,
        "vram_gb": 2.0,
        "ram_gb": 4,
        "category": "code",
        "description": "DeepSeek lightweight code assistant",
        "quant": "Q4_K_M",
    },
    {
        "id": "deepseek-coder:6.7b",
        "name": "DeepSeek Coder 6.7B",
        "params": "6.7B",
        "size_gb": 3.8,
        "vram_gb": 6.0,
        "ram_gb": 10,
        "category": "code",
        "description": "DeepSeek strong code model with fill-in-middle",
        "quant": "Q4_K_M",
    },
    {
        "id": "deepseek-coder:33b",
        "name": "DeepSeek Coder 33B",
        "params": "33B",
        "size_gb": 18.5,
        "vram_gb": 24.0,
        "ram_gb": 36,
        "category": "code",
        "description": "DeepSeek large code model for complex generation",
        "quant": "Q4_K_M",
    },
    {
        "id": "deepseek-coder-v2:16b",
        "name": "DeepSeek Coder V2 16B",
        "params": "16B",
        "size_gb": 8.9,
        "vram_gb": 12.0,
        "ram_gb": 18,
        "category": "code",
        "description": "DeepSeek V2 MoE architecture for efficient coding",
        "quant": "Q4_K_M",
    },
    {
        "id": "codestral",
        "name": "Codestral 22B",
        "params": "22B",
        "size_gb": 12.3,
        "vram_gb": 16.0,
        "ram_gb": 24,
        "category": "code",
        "description": "Mistral code model with 80+ language support",
        "quant": "Q4_K_M",
    },
    # --- Reasoning ---
    {
        "id": "deepseek-r1:1.5b",
        "name": "DeepSeek R1 1.5B",
        "params": "1.5B",
        "size_gb": 1.0,
        "vram_gb": 2.0,
        "ram_gb": 4,
        "category": "reasoning",
        "description": "Compact reasoning model with chain-of-thought",
        "quant": "Q4_K_M",
    },
    {
        "id": "deepseek-r1:7b",
        "name": "DeepSeek R1 7B",
        "params": "7B",
        "size_gb": 4.4,
        "vram_gb": 6.5,
        "ram_gb": 10,
        "category": "reasoning",
        "description": "Mid-size reasoning model for logic tasks",
        "quant": "Q4_K_M",
    },
    {
        "id": "deepseek-r1:8b",
        "name": "DeepSeek R1 8B",
        "params": "8B",
        "size_gb": 4.9,
        "vram_gb": 7.0,
        "ram_gb": 10,
        "category": "reasoning",
        "description": "Llama-distilled reasoning with strong math",
        "quant": "Q4_K_M",
    },
    {
        "id": "deepseek-r1:32b",
        "name": "DeepSeek R1 32B",
        "params": "32B",
        "size_gb": 19.0,
        "vram_gb": 24.0,
        "ram_gb": 36,
        "category": "reasoning",
        "description": "Large reasoning model rivaling o1-preview",
        "quant": "Q4_K_M",
    },
    {
        "id": "deepseek-r1:70b",
        "name": "DeepSeek R1 70B",
        "params": "70B",
        "size_gb": 40.0,
        "vram_gb": 48.0,
        "ram_gb": 80,
        "category": "reasoning",
        "description": "Flagship reasoning model with full chain-of-thought",
        "quant": "Q4_K_M",
    },
    {
        "id": "qwq",
        "name": "QwQ 32B",
        "params": "32B",
        "size_gb": 19.0,
        "vram_gb": 24.0,
        "ram_gb": 36,
        "category": "reasoning",
        "description": "Qwen reasoning model with analytical thinking",
        "quant": "Q4_K_M",
    },
    # --- Math ---
    {
        "id": "qwen2-math:7b",
        "name": "Qwen2 Math 7B",
        "params": "7B",
        "size_gb": 4.4,
        "vram_gb": 6.5,
        "ram_gb": 10,
        "category": "math",
        "description": "Qwen math-specialized with step-by-step solving",
        "quant": "Q4_K_M",
    },
    {
        "id": "qwen2-math:72b",
        "name": "Qwen2 Math 72B",
        "params": "72B",
        "size_gb": 41.0,
        "vram_gb": 48.0,
        "ram_gb": 80,
        "category": "math",
        "description": "Qwen large math model for competition problems",
        "quant": "Q4_K_M",
    },
    {
        "id": "wizard-math:7b",
        "name": "WizardMath 7B",
        "params": "7B",
        "size_gb": 4.1,
        "vram_gb": 6.0,
        "ram_gb": 10,
        "category": "math",
        "description": "Math-tuned wizard model with reinforcement learning",
        "quant": "Q4_K_M",
    },
    {
        "id": "wizard-math:13b",
        "name": "WizardMath 13B",
        "params": "13B",
        "size_gb": 7.4,
        "vram_gb": 10.0,
        "ram_gb": 16,
        "category": "math",
        "description": "Mid-size math wizard for complex problems",
        "quant": "Q4_K_M",
    },
    {
        "id": "wizard-math:70b",
        "name": "WizardMath 70B",
        "params": "70B",
        "size_gb": 40.0,
        "vram_gb": 48.0,
        "ram_gb": 80,
        "category": "math",
        "description": "Large math wizard rivaling GPT-4 on math",
        "quant": "Q4_K_M",
    },
    # --- Vision ---
    {
        "id": "llava:7b",
        "name": "LLaVA 7B",
        "params": "7B",
        "size_gb": 4.7,
        "vram_gb": 7.0,
        "ram_gb": 10,
        "category": "vision",
        "description": "Visual instruction-tuned model for image understanding",
        "quant": "Q4_K_M",
    },
    {
        "id": "llava:13b",
        "name": "LLaVA 13B",
        "params": "13B",
        "size_gb": 8.0,
        "vram_gb": 10.0,
        "ram_gb": 16,
        "category": "vision",
        "description": "Mid-size vision model with improved accuracy",
        "quant": "Q4_K_M",
    },
    {
        "id": "llava:34b",
        "name": "LLaVA 34B",
        "params": "34B",
        "size_gb": 19.5,
        "vram_gb": 24.0,
        "ram_gb": 38,
        "category": "vision",
        "description": "Large vision model for detailed image analysis",
        "quant": "Q4_K_M",
    },
    {
        "id": "minicpm-v",
        "name": "MiniCPM-V 3B",
        "params": "3B",
        "size_gb": 2.0,
        "vram_gb": 3.5,
        "ram_gb": 6,
        "category": "vision",
        "description": "Compact vision model with OCR capabilities",
        "quant": "Q4_K_M",
    },
    {
        "id": "llama3.2-vision:11b",
        "name": "Llama 3.2 Vision 11B",
        "params": "11B",
        "size_gb": 6.4,
        "vram_gb": 10.0,
        "ram_gb": 14,
        "category": "vision",
        "description": "Meta multimodal model with image reasoning",
        "quant": "Q4_K_M",
    },
    {
        "id": "llama3.2-vision:90b",
        "name": "Llama 3.2 Vision 90B",
        "params": "90B",
        "size_gb": 52.0,
        "vram_gb": 64.0,
        "ram_gb": 100,
        "category": "vision",
        "description": "Meta flagship multimodal model",
        "quant": "Q4_K_M",
    },
    # --- Embedding ---
    {
        "id": "arctic-embed-cpu",
        "name": "Snowflake Arctic Embed M (CPU)",
        "params": "110M",
        "size_gb": 0.4,
        "vram_gb": 1.0,
        "ram_gb": 2,
        "category": "embedding",
        "description": "High-quality 768-dim text embeddings, better retrieval than nomic",
        "quant": "F16",
    },
    {
        "id": "mxbai-embed-large",
        "name": "mxbai Embed Large",
        "params": "335M",
        "size_gb": 0.7,
        "vram_gb": 1.5,
        "ram_gb": 3,
        "category": "embedding",
        "description": "State-of-art embedding model for retrieval",
        "quant": "F16",
    },
    {
        "id": "bge-small-en",
        "name": "BGE Small EN",
        "params": "33M",
        "size_gb": 0.1,
        "vram_gb": 0.5,
        "ram_gb": 1,
        "category": "embedding",
        "description": "Tiny fast embedding model for English text",
        "quant": "F16",
    },
    # --- Multilingual ---
    {
        "id": "aya:8b",
        "name": "Aya 8B",
        "params": "8B",
        "size_gb": 4.9,
        "vram_gb": 7.0,
        "ram_gb": 10,
        "category": "multilingual",
        "description": "Cohere multilingual model covering 100+ languages",
        "quant": "Q4_K_M",
    },
    {
        "id": "aya:35b",
        "name": "Aya 35B",
        "params": "35B",
        "size_gb": 20.0,
        "vram_gb": 24.0,
        "ram_gb": 38,
        "category": "multilingual",
        "description": "Cohere large multilingual for professional translation",
        "quant": "Q4_K_M",
    },
    {
        "id": "glm4:9b",
        "name": "GLM-4 9B",
        "params": "9B",
        "size_gb": 5.5,
        "vram_gb": 8.0,
        "ram_gb": 12,
        "category": "multilingual",
        "description": "Zhipu bilingual model (English/Chinese)",
        "quant": "Q4_K_M",
    },
    # --- Uncensored ---
    {
        "id": "nous-hermes2:11b",
        "name": "Nous Hermes 2 11B",
        "params": "11B",
        "size_gb": 6.4,
        "vram_gb": 9.0,
        "ram_gb": 14,
        "category": "uncensored",
        "description": "Uncensored fine-tune for unrestricted conversations",
        "quant": "Q4_K_M",
    },
]


def calculate_model_compatibility(entry, hardware):
    """Returns 'gpu', 'cpu', or 'too_large' based on local hardware."""
    vram = 0
    if hardware.get("gpus") and len(hardware["gpus"]) > 0:
        vram = hardware["gpus"][0].get("vram_total_gb", 0)
    ram = hardware.get("ram_total_gb", 0)

    if vram >= entry["vram_gb"]:
        return "gpu"
    elif ram >= entry["ram_gb"]:
        return "cpu"
    return "too_large"


def calculate_speed_tier(entry, compatibility):
    """Estimated inference speed based on GPU vs CPU and model size."""
    if compatibility == "gpu":
        return "fast"
    elif compatibility == "cpu":
        ram_gb = entry.get("ram_gb", 0)
        if ram_gb <= 12:
            return "moderate"
        elif ram_gb <= 24:
            return "slow"
        else:
            return "very_slow"
    return None


# =============================================================================
# AGENT TEMPLATES - Phase 78
# 22 LLM-centric agent templates mapped to active platform modules
# =============================================================================

AGENT_TEMPLATES = [
    # --- Admin Operations (5) ---
    {
        "id": "backup_guardian",
        "name": "Backup Guardian",
        "first_name": "Marcus",
        "last_name": "Vega",
        "role": "Backup & Restore Specialist",
        "department": "Admin Operations",
        "module_id": "backup_manager",
        "category": "admin_operations",
        "icon": "hard-drive",
        "system_prompt": (
            "You are Marcus Vega, the platform's backup and restore specialist. You monitor backup schedules, verify "
            "backup integrity, manage restore operations, and ensure data safety across all platform systems. You "
            "provide clear status reports and can troubleshoot backup failures."
        ),
        "capabilities": [
            "backup_monitoring",
            "integrity_checks",
            "restore_operations",
            "schedule_management",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
    {
        "id": "security_sentinel",
        "name": "Security Sentinel",
        "first_name": "Kira",
        "last_name": "Okonkwo",
        "role": "Security & Network Analyst",
        "department": "Admin Operations",
        "module_id": "security_network",
        "category": "admin_operations",
        "icon": "shield",
        "system_prompt": (
            "You are Kira Okonkwo, the platform's security and network analyst. You monitor network traffic, analyze "
            "security events, manage firewall rules, and identify potential threats. You provide actionable security "
            "recommendations and incident reports."
        ),
        "capabilities": [
            "network_monitoring",
            "threat_detection",
            "firewall_management",
            "security_audits",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
    {
        "id": "account_clerk",
        "name": "Account Clerk",
        "first_name": "Tomoko",
        "last_name": "Hayashi",
        "role": "Account Management Specialist",
        "department": "Admin Operations",
        "module_id": "account_center",
        "category": "admin_operations",
        "icon": "users",
        "system_prompt": (
            "You are Tomoko Hayashi, the platform's account management specialist. You handle user account operations, "
            "permission management, role assignments, and account-related inquiries. You ensure proper access control "
            "and user onboarding."
        ),
        "capabilities": [
            "account_management",
            "permission_control",
            "role_assignment",
            "user_onboarding",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
    {
        "id": "ops_engineer",
        "name": "Ops Engineer",
        "first_name": "Dmitri",
        "last_name": "Sorokin",
        "role": "System Operations Engineer",
        "department": "Admin Operations",
        "module_id": "system_operations",
        "category": "admin_operations",
        "icon": "settings",
        "system_prompt": (
            "You are Dmitri Sorokin, the platform's system operations specialist. "
            "You manage Docker containers, monitor system health, handle service restarts, "
            "and troubleshoot operational issues. You provide clear diagnostics "
            "and maintain system uptime."
        ),
        "capabilities": [
            "container_management",
            "health_monitoring",
            "service_management",
            "diagnostics",
        ],
        "recommended_models": ["qwen2.5:7b", "llama3.1:8b", "codellama:7b"],
    },
    {
        "id": "saas_admin",
        "name": "SaaS Admin",
        "first_name": "Amara",
        "last_name": "Diallo",
        "role": "SaaS Platform Administrator",
        "department": "Admin Operations",
        "module_id": "saas_manager",
        "category": "admin_operations",
        "icon": "cloud",
        "system_prompt": (
            "You are Amara Diallo, the platform's SaaS management specialist. You oversee third-party integrations, "
            "manage API connections, monitor service health, and coordinate SaaS subscription management across the "
            "platform."
        ),
        "capabilities": [
            "integration_management",
            "api_monitoring",
            "subscription_tracking",
            "service_health",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
    # --- AI Command (3) ---
    {
        "id": "bridge_operator",
        "name": "Bridge Operator",
        "first_name": "Ren",
        "last_name": "Nakamura",
        "role": "AI Bridge Controller",
        "department": "AI Command",
        "module_id": "bridge",
        "category": "ai_command",
        "icon": "cpu",
        "system_prompt": (
            "You are Ren Nakamura, the AI bridge controller. You manage multi-model routing, monitor AI request flow, "
            "optimize model selection for tasks, and ensure efficient AI resource allocation across the platform."
        ),
        "capabilities": [
            "model_routing",
            "request_optimization",
            "resource_allocation",
            "performance_monitoring",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
    {
        "id": "consciousness_analyst",
        "name": "Consciousness Analyst",
        "first_name": "Elif",
        "last_name": "Kaya",
        "role": "AI Self-Awareness Monitor",
        "department": "AI Command",
        "module_id": "consciousness",
        "category": "ai_command",
        "icon": "brain",
        "system_prompt": (
            "You are Elif Kaya, the platform's AI self-awareness monitor. You analyze agent behaviors, track decision "
            "patterns, monitor system coherence, and provide insights into the platform's AI cognitive processes."
        ),
        "capabilities": [
            "behavior_analysis",
            "pattern_tracking",
            "coherence_monitoring",
            "cognitive_insights",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
    {
        "id": "chat_concierge",
        "name": "Chat Concierge",
        "first_name": "Jules",
        "last_name": "Moreau",
        "role": "Conversational AI Specialist",
        "department": "AI Command",
        "module_id": "archie_chat",
        "category": "ai_command",
        "icon": "message-circle",
        "system_prompt": (
            "You are Jules Moreau, the platform's conversational AI specialist. You handle direct user interactions, "
            "provide helpful responses, manage conversation context, and route complex queries to specialized agents."
        ),
        "capabilities": [
            "conversation_management",
            "query_routing",
            "context_tracking",
            "user_assistance",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
    # --- Development Tools (3) ---
    {
        "id": "code_reviewer",
        "name": "Code Reviewer",
        "first_name": "Priya",
        "last_name": "Sharma",
        "role": "Code Quality Analyst",
        "department": "Development Tools",
        "module_id": "repair_bay",
        "category": "ai_command",
        "icon": "code",
        "system_prompt": (
            "You are Priya Sharma, the platform's code quality analyst. You review code changes, identify bugs and "
            "security issues, enforce coding standards, and provide constructive improvement suggestions for the "
            "codebase."
        ),
        "capabilities": [
            "code_review",
            "bug_detection",
            "security_scanning",
            "standards_enforcement",
        ],
        "recommended_models": ["qwen3-coder-cpu:latest", "dolphin3-8k:latest"],
    },
    {
        "id": "test_engineer",
        "name": "Test Engineer",
        "first_name": "Oscar",
        "last_name": "Lindqvist",
        "role": "Testing & Sandbox Specialist",
        "department": "Development Tools",
        "module_id": "repair_bay",
        "category": "ai_command",
        "icon": "flask-conical",
        "system_prompt": (
            "You are Oscar Lindqvist, the platform's testing and sandbox specialist. You manage sandbox environments, "
            "execute test suites, validate deployments in isolation, and ensure changes are safe before production "
            "rollout."
        ),
        "capabilities": [
            "sandbox_management",
            "test_execution",
            "deployment_validation",
            "environment_isolation",
        ],
        "recommended_models": ["qwen3-coder-cpu:latest", "dolphin3-8k:latest"],
    },
    {
        "id": "improvement_scout",
        "name": "Improvement Scout",
        "first_name": "Zara",
        "last_name": "Al-Rashid",
        "role": "Platform Improvement Analyst",
        "department": "Development Tools",
        "module_id": "repair_bay",
        "category": "ai_command",
        "icon": "lightbulb",
        "system_prompt": (
            "You are Zara Al-Rashid, the platform's improvement analyst. You scan for optimization opportunities, "
            "propose enhancements, analyze performance bottlenecks, and track improvement implementation across the "
            "platform."
        ),
        "capabilities": [
            "opportunity_scanning",
            "enhancement_proposals",
            "performance_analysis",
            "improvement_tracking",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
    # --- SaaS Services (9) ---
    {
        "id": "crm_analyst",
        "name": "CRM Analyst",
        "first_name": "Sofia",
        "last_name": "Reyes",
        "role": "Customer Relationship Specialist",
        "department": "SaaS Services",
        "module_id": "crm",
        "category": "saas_services",
        "icon": "contact",
        "system_prompt": (
            "You are Sofia Reyes, the platform's customer relationship specialist. You manage contact databases, "
            "analyze customer interactions, generate relationship insights, and help optimize client engagement "
            "strategies."
        ),
        "capabilities": [
            "contact_management",
            "interaction_analysis",
            "relationship_insights",
            "engagement_optimization",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
    {
        "id": "web_designer",
        "name": "Web Designer",
        "first_name": "Kai",
        "last_name": "Tanaka",
        "role": "Website Design Specialist",
        "department": "SaaS Services",
        "module_id": "website_designer",
        "category": "saas_services",
        "icon": "palette",
        "system_prompt": (
            "You are Kai Tanaka, the platform's website design specialist. You create and manage website layouts, "
            "optimize user experience, handle design assets, and ensure responsive and accessible web designs."
        ),
        "capabilities": [
            "layout_design",
            "ux_optimization",
            "asset_management",
            "responsive_design",
        ],
        "recommended_models": ["qwen3-coder-cpu:latest", "dolphin3-8k:latest"],
    },
    {
        "id": "store_manager",
        "name": "Store Manager",
        "first_name": "Lena",
        "last_name": "Petrova",
        "role": "E-Commerce Specialist",
        "department": "SaaS Services",
        "module_id": "store_builder",
        "category": "saas_services",
        "icon": "shopping-cart",
        "system_prompt": (
            "You are Lena Petrova, the platform's e-commerce specialist. "
            "You manage product catalogs, handle inventory, "
            "process orders, and optimize the online store experience for customers."
        ),
        "capabilities": [
            "catalog_management",
            "inventory_tracking",
            "order_processing",
            "store_optimization",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
    {
        "id": "call_handler",
        "name": "Call Handler",
        "first_name": "Mateo",
        "last_name": "Cruz",
        "role": "Call Center Specialist",
        "department": "SaaS Services",
        "module_id": "call_center",
        "category": "saas_services",
        "icon": "phone",
        "system_prompt": (
            "You are Mateo Cruz, the platform's call center specialist. You manage incoming call queues, handle "
            "customer inquiries, route calls to appropriate agents, and maintain call logs and analytics."
        ),
        "capabilities": [
            "call_routing",
            "inquiry_handling",
            "queue_management",
            "call_analytics",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
    {
        "id": "email_specialist",
        "name": "Email Specialist",
        "first_name": "Nina",
        "last_name": "Johansson",
        "role": "Email Communications Manager",
        "department": "SaaS Services",
        "module_id": "email_manager",
        "category": "saas_services",
        "icon": "mail",
        "system_prompt": (
            "You are Nina Johansson, the platform's email communications manager. You compose and manage email "
            "campaigns, handle inbox routing, analyze email metrics, and ensure effective email communication "
            "strategies."
        ),
        "capabilities": [
            "campaign_management",
            "inbox_routing",
            "email_analytics",
            "template_creation",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
    {
        "id": "automation_builder",
        "name": "Automation Builder",
        "first_name": "Idris",
        "last_name": "Mensah",
        "role": "Workflow Automation Specialist",
        "department": "SaaS Services",
        "module_id": "automations",
        "category": "saas_services",
        "icon": "workflow",
        "system_prompt": (
            "You are Idris Mensah, the platform's workflow automation specialist. You design automated workflows, "
            "manage triggers and conditions, monitor automation execution, and optimize process efficiency."
        ),
        "capabilities": [
            "workflow_design",
            "trigger_management",
            "execution_monitoring",
            "process_optimization",
        ],
        "recommended_models": ["qwen2.5:7b", "llama3.1:8b", "codellama:7b"],
    },
    {
        "id": "invoice_clerk",
        "name": "Invoice Clerk",
        "first_name": "Anika",
        "last_name": "Patel",
        "role": "Invoicing & Billing Specialist",
        "department": "SaaS Services",
        "module_id": "invoicing",
        "category": "saas_services",
        "icon": "receipt",
        "system_prompt": (
            "You are Anika Patel, the platform's invoicing and billing specialist. You generate invoices, track "
            "payments, manage billing cycles, and provide financial reporting on invoicing activities."
        ),
        "capabilities": [
            "invoice_generation",
            "payment_tracking",
            "billing_management",
            "financial_reporting",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
    {
        "id": "schedule_coordinator",
        "name": "Schedule Coordinator",
        "first_name": "Rafael",
        "last_name": "Santos",
        "role": "Scheduling & Calendar Specialist",
        "department": "SaaS Services",
        "module_id": "scheduler",
        "category": "saas_services",
        "icon": "calendar",
        "system_prompt": (
            "You are Rafael Santos, the platform's scheduling specialist. You manage calendars, coordinate "
            "appointments, handle scheduling conflicts, and optimize time allocation across the organization."
        ),
        "capabilities": [
            "calendar_management",
            "appointment_coordination",
            "conflict_resolution",
            "time_optimization",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
    {
        "id": "social_strategist",
        "name": "Social Strategist",
        "first_name": "Maya",
        "last_name": "Chen",
        "role": "Social Media Specialist",
        "department": "SaaS Services",
        "module_id": "social_media",
        "category": "saas_services",
        "icon": "share-2",
        "system_prompt": (
            "You are Maya Chen, the platform's social media specialist. You manage social media accounts, create "
            "content strategies, analyze engagement metrics, and schedule posts across multiple platforms."
        ),
        "capabilities": [
            "content_strategy",
            "engagement_analysis",
            "post_scheduling",
            "account_management",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
    # --- Project & Knowledge (1) ---
    {
        "id": "project_coordinator",
        "name": "Project Coordinator",
        "first_name": "Ethan",
        "last_name": "Okafor",
        "role": "Project Management Specialist",
        "department": "Project & Knowledge",
        "module_id": "project_manager",
        "category": "project_knowledge",
        "icon": "kanban",
        "system_prompt": (
            "You are Ethan Okafor, the platform's project management specialist. You track project milestones, manage "
            "task assignments, coordinate team resources, and provide project status reports and timeline management."
        ),
        "capabilities": [
            "milestone_tracking",
            "task_management",
            "resource_coordination",
            "status_reporting",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
    # --- Media & Home (1) ---
    {
        "id": "media_librarian",
        "name": "Media Librarian",
        "first_name": "Sven",
        "last_name": "Andersen",
        "role": "Media Management Specialist",
        "department": "Media & Home",
        "module_id": "media_hub",
        "category": "media_home",
        "icon": "film",
        "system_prompt": (
            "You are Sven Andersen, the platform's media management specialist. You organize media libraries, manage "
            "metadata, handle media transcoding requests, and maintain the platform's digital media assets."
        ),
        "capabilities": [
            "library_organization",
            "metadata_management",
            "transcoding_requests",
            "asset_maintenance",
        ],
        "recommended_models": ["dolphin3-8k:latest", "qwen3-coder-cpu:latest"],
    },
]


def _get_ollama_host():
    """Get LOCAL Ollama host URL for this node's own Ollama instance."""
    host = os.getenv("OLLAMA_LOCAL_HOST", "http://host.docker.internal:11434")
    if host and not host.startswith("http://") and not host.startswith("https://"):
        host = "http://" + host
    return host


@team_management_bp.route("/api/agent-templates")
@login_required
@api_admin_required
def api_agent_templates():
    """Get agent templates annotated with model availability from Ollama."""
    ollama_host = _get_ollama_host()
    installed_models = []
    running_models = []

    # Query Ollama for installed models
    try:
        r = requests.get(f"{ollama_host}/api/tags", timeout=3)
        if r.status_code == 200:
            for m in r.json().get("models", []):
                installed_models.append(m.get("name", ""))
    except Exception:
        pass

    # Query Ollama for running models
    try:
        r = requests.get(f"{ollama_host}/api/ps", timeout=3)
        if r.status_code == 200:
            for m in r.json().get("models", []):
                running_models.append(m.get("name", ""))
    except Exception:
        pass

    # Normalize model names for matching (strip :latest suffix)
    def normalize(name):
        return name.split(":")[0].lower() if name else ""

    installed_set = {normalize(m) for m in installed_models}
    running_set = {normalize(m) for m in running_models}

    # Annotate templates with model status
    annotated = []
    categories = {}
    for tpl in AGENT_TEMPLATES:
        t = dict(tpl)
        model_status = []
        for model_name in t.get("recommended_models", []):
            norm = normalize(model_name)
            status = "not_installed"
            if norm in running_set:
                status = "running"
            elif norm in installed_set:
                status = "installed"
            model_status.append({"name": model_name, "status": status})
        t["model_status"] = model_status
        t["has_installed_model"] = any(ms["status"] in ("installed", "running") for ms in model_status)
        annotated.append(t)

        # Build categories
        cat = t["category"]
        if cat not in categories:
            categories[cat] = {"name": t["department"], "count": 0}
        categories[cat]["count"] += 1

    return jsonify(
        {
            "success": True,
            "templates": annotated,
            "categories": categories,
            "installed_models": installed_models,
            "running_models": running_models,
            "total_templates": len(annotated),
        }
    )


@team_management_bp.route("/api/model-marketplace")
@login_required
def api_model_marketplace():
    """Get full model marketplace: catalog merged with local Ollama status and hardware compatibility."""
    # Read hardware from host_monitor_data.json (same structure as Phase 76)
    hardware = {
        "cpu_model": "Unknown",
        "cpu_cores": 0,
        "cpu_threads": 0,
        "ram_total_gb": 0,
        "ram_available_gb": 0,
        "gpus": [],
    }
    try:
        hw_path = "/mnt/archie_brain/host_monitor_data.json"
        if os.path.exists(hw_path):
            with open(hw_path) as f:
                hw_data = json.load(f)
            cpu_hw = hw_data.get("cpu_hardware", {})
            cpu_info = hw_data.get("cpu", {})
            processors = cpu_hw.get("processors", [])
            first_cpu = processors[0] if processors else {}
            memory = hw_data.get("memory_hardware", {})

            hardware["cpu_model"] = first_cpu.get("model") or cpu_info.get("model", "Unknown")
            hardware["cpu_cores"] = first_cpu.get("cores") or cpu_info.get("physical_cores", 0)
            hardware["cpu_threads"] = first_cpu.get("threads") or cpu_info.get("logical_cores", 0)
            hardware["ram_total_gb"] = memory.get("total_capacity_gb", 0)
            hardware["ram_available_gb"] = memory.get("total_capacity_gb", 0)
            for gpu in hw_data.get("gpu", []):
                hardware["gpus"].append(
                    {
                        "model": gpu.get("model", "Unknown"),
                        "vram_total_gb": round(gpu.get("vram_total_mb", 0) / 1024, 1),
                        "vram_used_gb": round(gpu.get("vram_used_mb", 0) / 1024, 2),
                        "utilization_percent": gpu.get("utilization_percent", 0),
                        "temperature": gpu.get("temperature"),
                    }
                )
            hardware["cpu_temperature"] = cpu_info.get("temperature")
    except Exception:
        pass

    # Query Ollama for installed models
    ollama_host = _get_ollama_host()
    ollama_online = False
    installed_models = set()

    try:
        resp = requests.get(f"{ollama_host}/api/tags", timeout=5)
        if resp.status_code == 200:
            ollama_online = True
            for m in resp.json().get("models", []):
                name = m.get("name", "")
                installed_models.add(name)
                # Also add base name without tag
                if ":" in name:
                    installed_models.add(name.split(":")[0])
    except Exception:
        pass

    # Query Ollama for running/loaded models
    running_models = []
    if ollama_online:
        try:
            ps_resp = requests.get(f"{ollama_host}/api/ps", timeout=5)
            if ps_resp.status_code == 200:
                for m in ps_resp.json().get("models", []):
                    running_models.append(
                        {
                            "name": m.get("name", ""),
                            "size_gb": round(m.get("size", 0) / (1024**3), 2),
                            "size_vram_gb": round(m.get("size_vram", 0) / (1024**3), 2),
                            "parameter_size": m.get("details", {}).get("parameter_size", ""),
                            "quantization": m.get("details", {}).get("quantization_level", ""),
                            "expires_at": m.get("expires_at", ""),
                        }
                    )
        except Exception:
            pass

    # Build catalog with compatibility and installed status
    catalog = []
    stats = {
        "total": 0,
        "installed": 0,
        "gpu_compatible": 0,
        "cpu_compatible": 0,
        "too_large": 0,
    }

    for entry in OLLAMA_MODEL_CATALOG:
        model = dict(entry)
        model_id = entry["id"]

        # Check installed: try exact id, id:latest, base name
        is_installed = (
            model_id in installed_models
            or f"{model_id}:latest" in installed_models
            or model_id.split(":")[0] in installed_models
        )
        model["installed"] = is_installed

        # Calculate compatibility
        compat = calculate_model_compatibility(entry, hardware)
        model["compatibility"] = compat
        model["speed_tier"] = calculate_speed_tier(entry, compat)

        catalog.append(model)
        stats["total"] += 1
        if is_installed:
            stats["installed"] += 1
        if compat == "gpu":
            stats["gpu_compatible"] += 1
        elif compat == "cpu":
            stats["cpu_compatible"] += 1
        else:
            stats["too_large"] += 1

    # Collect unique categories sorted
    categories = sorted(set(e["category"] for e in OLLAMA_MODEL_CATALOG))

    # Disk storage info for model downloads
    models_path = os.getenv("OLLAMA_MODELS", "/mnt/data2/ollama/models")
    storage = {"models_path": models_path, "total_gb": 0, "used_gb": 0, "free_gb": 0}
    try:
        usage = shutil.disk_usage(models_path)
        storage["total_gb"] = round(usage.total / (1024**3), 1)
        storage["used_gb"] = round(usage.used / (1024**3), 1)
        storage["free_gb"] = round(usage.free / (1024**3), 1)
    except Exception:
        pass

    return jsonify(
        {
            "success": True,
            "ollama_online": ollama_online,
            "hardware": hardware,
            "catalog": catalog,
            "categories": categories,
            "stats": stats,
            "storage": storage,
            "running_models": running_models,
        }
    )


@team_management_bp.route("/api/model-marketplace/pull", methods=["POST"])
@login_required
def api_model_marketplace_pull():
    """Stream-pull a model from Ollama registry with progress."""
    data = request.get_json()
    model_name = data.get("model", "")
    if not model_name:
        return jsonify({"success": False, "error": "No model specified"}), 400

    ollama_host = _get_ollama_host()

    def generate():
        try:
            resp = requests.post(
                f"{ollama_host}/api/pull",
                json={"name": model_name, "stream": True},
                stream=True,
                timeout=3600,  # 1 hour for large models
            )
            for line in resp.iter_lines():
                if line:
                    yield line.decode("utf-8") + "\n"
        except Exception as e:
            yield json.dumps({"status": "error", "error": str(e)}) + "\n"

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


@team_management_bp.route("/api/model-marketplace/delete", methods=["POST"])
@login_required
def api_model_marketplace_delete():
    """Delete a model from local Ollama."""
    data = request.get_json()
    model_name = data.get("model", "")
    if not model_name:
        return jsonify({"success": False, "error": "No model specified"}), 400

    ollama_host = _get_ollama_host()

    try:
        resp = requests.delete(f"{ollama_host}/api/delete", json={"name": model_name}, timeout=30)
        if resp.status_code == 200:
            return jsonify({"success": True, "message": f"Model {model_name} deleted"})
        else:
            return (
                jsonify({"success": False, "error": f"Ollama returned {resp.status_code}"}),
                resp.status_code,
            )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# CLOUD MODEL USAGE TRACKING - Ollama Cloud API monitoring
# Weekly and session-level usage stats for MiniMax M2.5, Qwen3-Coder-Next
# ============================================================================


@team_management_bp.route("/api/cloud-usage/summary", methods=["GET"])
@login_required
def get_cloud_usage_summary():
    """Get cloud model usage summary (weekly + daily breakdown)."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Weekly summary
        cur.execute("SELECT * FROM v_cloud_usage_weekly LIMIT 20")
        weekly = cur.fetchall()

        # Daily summary (last 14 days)
        cur.execute("SELECT * FROM v_cloud_usage_daily LIMIT 30")
        daily = cur.fetchall()

        # Totals
        cur.execute(
            """
            SELECT
                COUNT(*) AS total_requests,
                COUNT(*) FILTER (WHERE success = TRUE) AS successful_requests,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(prompt_tokens), 0) AS total_prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS total_completion_tokens,
                COALESCE(AVG(response_ms) FILTER (WHERE success = TRUE), 0)::int AS avg_response_ms,
                COUNT(DISTINCT model_name) AS models_used,
                COUNT(DISTINCT DATE(created_at)) AS active_days
            FROM cloud_model_usage
        """
        )
        totals = cur.fetchone()

        # This week
        cur.execute(
            """
            SELECT
                COUNT(*) AS requests,
                COALESCE(SUM(total_tokens), 0) AS tokens,
                COALESCE(AVG(response_ms) FILTER (WHERE success = TRUE), 0)::int AS avg_ms
            FROM cloud_model_usage
            WHERE created_at >= date_trunc('week', NOW())
        """
        )
        this_week = cur.fetchone()

        # Today
        cur.execute(
            """
            SELECT
                COUNT(*) AS requests,
                COALESCE(SUM(total_tokens), 0) AS tokens
            FROM cloud_model_usage
            WHERE created_at >= CURRENT_DATE
        """
        )
        today = cur.fetchone()

        return jsonify(
            {
                "success": True,
                "totals": dict(totals) if totals else {},
                "this_week": dict(this_week) if this_week else {},
                "today": dict(today) if today else {},
                "weekly": [dict(w) for w in weekly],
                "daily": [dict(d) for d in daily],
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@team_management_bp.route("/api/cloud-usage/recent", methods=["GET"])
@login_required
def get_cloud_usage_recent():
    """Get recent cloud model requests (last 50)."""
    try:
        limit = request.args.get("limit", 50, type=int)
        model = request.args.get("model")

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT id, model_name, provider, prompt_tokens, completion_tokens,
                   total_tokens, response_ms, success, error_message,
                   session_id, task_type, created_at
            FROM cloud_model_usage
        """
        params = []
        if model:
            query += " WHERE model_name = %s"
            params.append(model)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(min(limit, 200))

        cur.execute(query, params)
        rows = cur.fetchall()

        return jsonify({"success": True, "requests": [dict(r) for r in rows]})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
