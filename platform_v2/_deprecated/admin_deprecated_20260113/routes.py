"""
A.R.C.H.I.E. Improvements Lab - Complete Routes
================================================
Comprehensive improvements management: proposals, teams, sandbox, deployment, discussions.

Migrated from admin panel 2026-01-12 with all 94+ routes for improvements.

Author: A.R.C.H.I.E. Platform
"""

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    flash,
    session,
)
from flask_login import login_required, current_user
from functools import wraps
import psycopg2
import psycopg2.extras
from psycopg2.extras import RealDictCursor
from datetime import datetime
import json
import os
from database import _get_db_password
import traceback

# Import improvement modules
from .manager import ImprovementManager

# Import improvement chat system
import sys

sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
try:
    from improvement_chat import (
        chat_about_improvements,
        self_reflection_chat,
    )
    from improvement_engine import (
        detect_improvement_opportunities,
        run_auto_improvement_detection,
    )

    CHAT_AVAILABLE = True
except Exception as e:
    print(f"Warning: Improvement chat not available: {e}")
    CHAT_AVAILABLE = False

# Create blueprint
improvements_bp = Blueprint("improvements", __name__, url_prefix="/tools/improvements-lab")

# Base path for file operations
ALLOWED_BASE = "/mnt/archie_brain/platform_v2"


# ============================================================================
# HELPERS
# ============================================================================


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
        if not getattr(current_user, "is_admin", False):
            return jsonify({"success": False, "error": "Admin access required"}), 403
        return f(*args, **kwargs)

    return decorated_function


# ============================================================================
# MAIN PAGES
# ============================================================================


@improvements_bp.route("/")
@login_required
def index():
    """Self-improvement dashboard"""
    if not getattr(current_user, "is_admin", False):
        flash("Admin access required", "error")
        return redirect(url_for("dashboard"))

    try:
        manager = ImprovementManager()
        status_filter = request.args.get("status", None)
        proposals = manager.list_proposals(status=status_filter)
        stats = manager.get_stats()

        return render_template(
            "tools/improvements.html",
            proposals=proposals,
            stats=stats,
            current_filter=status_filter,
        )
    except Exception as e:
        traceback.print_exc()
        flash(f"Error loading improvements: {str(e)}", "error")
        return redirect(url_for("dashboard"))


@improvements_bp.route("/chat")
@login_required
def chat_interface():
    """Interactive chat interface for discussing improvements with A.R.C.H.I.E."""
    if not getattr(current_user, "is_admin", False):
        flash("Admin access required", "error")
        return redirect(url_for("dashboard"))

    return render_template("tools/improvements_chat.html", chat_available=CHAT_AVAILABLE)


# ============================================================================
# CHAT ROUTES
# ============================================================================


@improvements_bp.route("/chat/send", methods=["POST"])
@login_required
@admin_required
def send_chat_message():
    """Send a message to A.R.C.H.I.E. about improvements"""
    if not CHAT_AVAILABLE:
        return jsonify({"success": False, "error": "Chat system not available"}), 503

    try:
        data = request.get_json()
        message = data.get("message", "").strip()
        conversation_id = data.get("conversation_id")

        if not message:
            return jsonify({"success": False, "error": "Message required"}), 400

        result = chat_about_improvements(
            user_message=message,
            user_id=current_user.id,
            conversation_id=conversation_id,
        )

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/chat/self-reflect", methods=["POST"])
@login_required
@admin_required
def self_reflect():
    """Trigger A.R.C.H.I.E. self-reflection"""
    if not CHAT_AVAILABLE:
        return jsonify({"success": False, "error": "Chat system not available"}), 503

    try:
        data = request.get_json() or {}
        topic = data.get("topic", "overall performance")

        result = self_reflection_chat(topic=topic, user_id=current_user.id)

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/detect", methods=["POST"])
@login_required
@admin_required
def detect_improvements():
    """Run automatic improvement detection"""
    if not CHAT_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Detection system not available"}),
            503,
        )

    try:
        summary = run_auto_improvement_detection()
        opportunities = detect_improvement_opportunities()

        flash(
            f'Detected {summary["opportunities_detected"]} opportunities, created {summary["proposals_created"]} proposals',
            "success",
        )

        return jsonify({"success": True, **summary, "opportunities": opportunities[:10]})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# MANAGER-BASED ROUTES
# ============================================================================


@improvements_bp.route("/proposal/<int:proposal_id>/test", methods=["POST"])
@login_required
@admin_required
def test_proposal(proposal_id):
    """Test a proposal using the manager"""
    try:
        manager = ImprovementManager()
        result = manager.test_proposal(proposal_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposal/<int:proposal_id>/approve", methods=["POST"])
@login_required
@admin_required
def approve_proposal_manager(proposal_id):
    """Approve proposal using manager"""
    try:
        manager = ImprovementManager()
        result = manager.approve_proposal(proposal_id, current_user.id)
        if result["success"]:
            flash("Proposal approved!", "success")
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposal/<int:proposal_id>/reject", methods=["POST"])
@login_required
@admin_required
def reject_proposal_manager(proposal_id):
    """Reject proposal using manager"""
    try:
        reason = request.json.get("reason", "No reason provided")
        manager = ImprovementManager()
        result = manager.reject_proposal(proposal_id, current_user.id, reason)
        if result["success"]:
            flash("Proposal rejected", "info")
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposal/<int:proposal_id>/deploy", methods=["POST"])
@login_required
@admin_required
def deploy_proposal_manager(proposal_id):
    """Deploy proposal using manager"""
    try:
        manager = ImprovementManager()
        result = manager.deploy_proposal(proposal_id)
        if result["success"]:
            flash("Proposal deployed!", "success")
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# LIST AND BASIC CRUD
# ============================================================================


@improvements_bp.route("/list", methods=["GET"])
@login_required
@admin_required
def list_improvements():
    """List all improvement proposals"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, title, description, priority, status,
                   code_changes, proposed_at, category, rationale, risk_level
            FROM improvement_proposals
            ORDER BY proposed_at DESC
        """
        )

        improvements = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "improvements": [
                    {
                        "id": i["id"],
                        "title": i["title"],
                        "description": i["description"],
                        "priority": i["priority"],
                        "status": i["status"],
                        "code_changes": i["code_changes"],
                        "category": i.get("category", "general"),
                        "rationale": i.get("rationale", ""),
                        "risk_level": i.get("risk_level", "medium"),
                        "proposed_at": (i["proposed_at"].strftime("%Y-%m-%d %H:%M") if i["proposed_at"] else "N/A"),
                    }
                    for i in improvements
                ],
            }
        )
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/<int:id>/approve", methods=["POST"])
@login_required
@admin_required
def approve_improvement(id):
    """Approve improvement"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT id FROM improvement_proposals WHERE id = %s", (id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Not found"}), 404

        cur.execute(
            """
            UPDATE improvement_proposals
            SET status = 'approved',
                reviewed_at = NOW(),
                approved_at = NOW(),
                approved_by = %s
            WHERE id = %s
        """,
            (current_user.id, id),
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/<int:id>/reject", methods=["POST"])
@login_required
@admin_required
def reject_improvement(id):
    """Reject improvement"""
    try:
        data = request.json or {}
        reason = data.get("reason", "No reason provided")

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT id FROM improvement_proposals WHERE id = %s", (id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Not found"}), 404

        cur.execute(
            """
            UPDATE improvement_proposals
            SET status = 'rejected',
                reviewed_at = NOW(),
                notes = %s
            WHERE id = %s
        """,
            (reason, id),
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/<int:id>/implement", methods=["POST"])
@login_required
@admin_required
def implement_improvement(id):
    """Mark as implemented"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT id FROM improvement_proposals WHERE id = %s", (id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Not found"}), 404

        cur.execute(
            """
            UPDATE improvement_proposals
            SET status = 'implemented',
                implemented_at = NOW()
            WHERE id = %s
        """,
            (id,),
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# STATS
# ============================================================================


@improvements_bp.route("/stats", methods=["GET"])
@login_required
@admin_required
def get_improvement_stats():
    """Get improvement statistics"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'pending' OR status = 'proposed') as pending,
                COUNT(*) FILTER (WHERE status = 'approved') as approved,
                COUNT(*) FILTER (WHERE status = 'deployed' OR status = 'implemented') as deployed,
                COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
                COUNT(*) FILTER (WHERE status = 'testing') as testing,
                COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress
            FROM improvement_proposals
        """
        )

        stats = cur.fetchone()

        # Get recent activity
        cur.execute(
            """
            SELECT id, title, status, proposed_at
            FROM improvement_proposals
            ORDER BY proposed_at DESC
            LIMIT 5
        """
        )
        recent = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "stats": dict(stats) if stats else {},
                "recent": [dict(r) for r in recent],
            }
        )
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# HEALTH CHECK
# ============================================================================


@improvements_bp.route("/health")
def health_check():
    """Health check endpoint"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM improvement_proposals")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()

        return jsonify(
            {
                "healthy": True,
                "module": "improvements",
                "total_proposals": count,
                "chat_available": CHAT_AVAILABLE,
            }
        )
    except Exception as e:
        return (
            jsonify({"healthy": False, "module": "improvements", "error": str(e)}),
            500,
        )


# MIGRATION START - Append everything below to improvements/routes.py
# ============================================================================


# ============================================================================
# ADVANCED CHAT ROUTES (with session and delegation)
# ============================================================================


@improvements_bp.route("/chat/advanced", methods=["POST"])
@login_required
@admin_required
def improvements_chat():
    """Claude Code-style chat for improvements with auto-proposal creation and escalation"""
    print(f"Advanced improvements chat called by user {current_user.id} ({current_user.username})")
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

        data = request.json
        user_message = data.get("message", "")
        print(f"Message: {user_message[:80]}...")

        if not user_message:
            return jsonify({"success": False, "error": "No message"}), 400

        # Get or initialize conversation history from session

        session_key = f"improvements_conversation_{current_user.id}"
        conversation_id_key = f"improvements_conversation_id_{current_user.id}"
        conversation_history = session.get(session_key, [])
        conversation_id = session.get(conversation_id_key, None)

        # Limit history to last 20 messages (10 exchanges) for context
        if len(conversation_history) > 20:
            conversation_history = conversation_history[-20:]

        print(f"Conversation history: {len(conversation_history)} messages")
        print(f"Conversation ID: {conversation_id}")

        # Process message with Claude Code-style engine
        print("A.R.C.H.I.E. processing...")

        # Import the chat function
        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from improvement_chat import chat_about_improvements

        archie_result = chat_about_improvements(
            user_message=user_message,
            user_id=current_user.id,
            conversation_id=conversation_id,  # Pass existing conversation ID for memory
        )

        # Store conversation ID for next message
        if archie_result.get("success") and archie_result.get("conversation_id"):
            session[conversation_id_key] = archie_result["conversation_id"]
            print(f"Stored conversation ID: {archie_result['conversation_id']}")

        # Check if A.R.C.H.I.E. wants to delegate
        if archie_result.get("should_delegate"):
            print(f"A.R.C.H.I.E. delegating to {archie_result['delegation_info'].get('suggested_department')}...")

            # A.R.C.H.I.E.'s intro message + delegated response
            archie_intro = archie_result.get("response", "")

            # Now delegate to specialist
            from ai_bridge.delegation_engine import execute_with_delegation

            delegation_result = execute_with_delegation(
                task=user_message,
                user_id=current_user.id,
                department=archie_result["delegation_info"].get("suggested_department"),
            )

            # Return SEPARATE messages - A.R.C.H.I.E.'s intro and specialist's response
            specialist_name = delegation_result.get("delegation", {}).get("employee_name", "Specialist")

            # Create notification for task acknowledgment
            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO notifications (user_id, type, title, message, is_read)
                    VALUES (%s, %s, %s, %s, FALSE)
                """,
                    (
                        current_user.id,
                        "task_delegated",
                        f"{specialist_name} acknowledged your task",
                        f"{specialist_name} is now working on: {user_message[:100]}",
                    ),
                )
                conn.commit()
                cur.close()
                conn.close()
                print(f"Notification created: {specialist_name} acknowledged task")
            except Exception as notif_error:
                print(f"Failed to create notification: {notif_error}")

            result = {
                "success": delegation_result.get("success"),
                "messages": [
                    {
                        "from": "A.R.C.H.I.E.",
                        "title": "Your Personal AI Assistant",
                        "response": archie_intro,
                        "worker_type": "internal",
                    },
                    {
                        "from": specialist_name,
                        "title": delegation_result.get("delegation", {}).get("employee_title", ""),
                        "response": delegation_result.get("response", ""),
                        "worker_type": delegation_result.get("delegation", {}).get("worker_type", "internal"),
                    },
                ],
                "delegation": delegation_result.get("delegation", {}),
                "archie_handled": False,
                "delegated_to": specialist_name,
                "notification_created": True,
            }
        else:
            # A.R.C.H.I.E. handles it herself - NO DELEGATION
            print("A.R.C.H.I.E. handled directly (no delegation needed)")
            result = {
                "success": archie_result.get("success"),
                "response": archie_result.get("response"),
                "delegation": {
                    "employee_name": "A.R.C.H.I.E.",
                    "employee_title": "Your Personal AI Assistant",
                    "department": "Core",
                    "worker_type": "internal",
                    "model": archie_result.get("model_used", "qwen2.5-coder:7b"),
                    "reason": "Direct response - no delegation needed",
                },
                "archie_handled": True,
                "used_script": archie_result.get("used_script", False),
            }

        # Extract response details - handle both single response and messages array
        if result.get("success"):
            # Check if we have separate messages (new delegation format)
            if "messages" in result:
                # Combine messages for conversation history
                response_text = "\n\n".join([f"{msg['from']}: {msg['response']}" for msg in result["messages"]])
            else:
                # Single response (A.R.C.H.I.E. handled directly)
                response_text = result.get("response", "Error: No response")

            delegation = result.get("delegation", {})
            execution_record = result.get("execution_record", {})
            audit_trail = result.get("audit_trail", "")

            # Extract from raw result for backwards compatibility
            raw_result = result.get("raw_result", {})
            memory_used = raw_result.get("memory_used", False)
            memories_learned = raw_result.get("memories_learned", 0)
            tools_used = raw_result.get("tools_used", [])
            conversation = raw_result.get("conversation", [])
            iterations = raw_result.get("iterations", 0)
        else:
            response_text = "Error: " + result.get("error", "Unknown error")
            delegation = {}
            execution_record = {}
            audit_trail = ""
            memory_used = False
            memories_learned = 0
            tools_used = []
            conversation = []
            iterations = 0

        # Update conversation history in session
        conversation_history.append({"role": "user", "content": user_message})
        conversation_history.append({"role": "assistant", "content": response_text})

        # Keep only last 10 messages
        if len(conversation_history) > 10:
            conversation_history = conversation_history[-10:]

        session[session_key] = conversation_history
        print(f"Updated conversation history: {len(conversation_history)} messages")

        # Store conversation in improvement_conversations table
        try:
            conn = get_db()
            cur = conn.cursor()

            # Store full conversation as JSON
            conversation_json = json.dumps(conversation)
            tools_json = json.dumps(tools_used)

            cur.execute(
                """
                INSERT INTO improvement_conversations
                (user_id, user_message, archie_response, memory_used, memories_learned,
                 conversation_data, tools_used, iterations)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    current_user.id,
                    user_message,
                    response_text,
                    memory_used,
                    memories_learned,
                    conversation_json,
                    tools_json,
                    iterations,
                ),
            )

            conv_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
        except Exception as db_error:
            # Table might not exist yet - log but continue
            print(f"Error storing conversation: {db_error}")
            conv_id = None

        return jsonify(
            {
                "success": True,
                "response": response_text,
                "messages": result.get("messages", None),
                "memory_used": memory_used,
                "memories_learned": memories_learned,
                "tools_used": tools_used,
                "conversation": conversation,
                "iterations": iterations,
                "conversation_id": conv_id,
                "delegation": delegation,
                "execution_record": execution_record,
                "audit_trail": audit_trail,
                "notification_created": result.get("notification_created", False),
            }
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/chat/history", methods=["GET"])
@login_required
@admin_required
def improvements_chat_history():
    """Get conversation history for improvements discussions"""
    try:
        limit = request.args.get("limit", 50, type=int)

        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT *
            FROM improvement_conversations
            WHERE user_id = %s
            ORDER BY created_at ASC
            LIMIT %s
        """,
            (current_user.id, limit),
        )

        conversations = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({"success": True, "conversations": [dict(c) for c in conversations]})

    except Exception as e:
        return jsonify({"success": False, "error": str(e), "conversations": []}), 500


@improvements_bp.route("/chat/clear", methods=["POST"])
@login_required
@admin_required
def improvements_chat_clear():
    """Clear improvement conversation history (both database and session)"""
    try:

        # Clear session conversation history
        session_key = f"archie_conversation_{current_user.id}"
        if session_key in session:
            del session[session_key]
            print(f"Cleared session conversation history for user {current_user.id}")

        # Clear database conversation history
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM improvement_conversations
            WHERE user_id = %s
        """,
            (current_user.id,),
        )

        deleted_count = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()

        print(f"Deleted {deleted_count} conversation records from database")

        return jsonify({"success": True, "deleted_count": deleted_count, "session_cleared": True})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# APPLY CHANGE & DB MIGRATION
# ============================================================================


@improvements_bp.route("/apply-change", methods=["POST"])
@login_required
@admin_required
def improvements_apply_change():
    """Apply a file change proposed by A.R.C.H.I.E."""
    try:
        from consciousness.archie_tools import write_file

        data = request.json
        file_path = data.get("path", "")
        content = data.get("content", "")

        if not file_path or not content:
            return jsonify({"success": False, "error": "Missing path or content"}), 400

        # Execute write with backup
        result = write_file(file_path, content, create_backup=True)

        if result["success"]:
            # Log the change
            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO audit_log (user_id, action, details, timestamp)
                    VALUES (%s, %s, %s, NOW())
                """,
                    (
                        current_user.id,
                        "file_write",
                        json.dumps(
                            {
                                "file": file_path,
                                "backup": result.get("backup_path"),
                                "source": "improvements_ai",
                            }
                        ),
                    ),
                )
                conn.commit()
                cur.close()
                conn.close()
            except:
                pass  # Audit logging is optional

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/migrate-db", methods=["POST"])
@login_required
@admin_required
def improvements_migrate_db():
    """Migrate improvement_conversations table to support new features"""
    try:
        conn = get_db()
        cur = conn.cursor()

        # Add new columns if they don't exist
        cur.execute(
            """
            ALTER TABLE improvement_conversations
            ADD COLUMN IF NOT EXISTS conversation_data JSONB,
            ADD COLUMN IF NOT EXISTS tools_used JSONB,
            ADD COLUMN IF NOT EXISTS iterations INTEGER DEFAULT 0
        """
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "message": "Database migrated successfully"})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# PLAN-AND-EXECUTE WORKFLOW ENDPOINTS
# ============================================================================


@improvements_bp.route("/create-plan", methods=["POST"])
@login_required
@admin_required
def improvements_create_plan():
    """Create an improvement plan using A.R.C.H.I.E.'s planning workflow"""
    try:
        from ai_bridge.archie_bridge import archie_bridge_with_planning

        data = request.json
        user_request = data.get("request", "")

        if not user_request:
            return jsonify({"success": False, "error": "No request provided"}), 400

        # Create plan using A.R.C.H.I.E.
        result = archie_bridge_with_planning(
            prompt=user_request,
            user_id=current_user.id,
            force_model="deepseek-coder-v2:16b",
        )

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals", methods=["GET"])
@login_required
@admin_required
def improvements_get_proposals():
    """Get all improvement proposals"""
    try:
        status = request.args.get("status", None)

        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if status:
            cur.execute(
                """
                SELECT id, title, description, category, priority, status,
                       proposed_at, proposed_by, plan_steps, metadata
                FROM improvement_proposals
                WHERE status = %s
                ORDER BY proposed_at DESC
            """,
                (status,),
            )
        else:
            cur.execute(
                """
                SELECT id, title, description, category, priority, status,
                       proposed_at, proposed_by, plan_steps, metadata
                FROM improvement_proposals
                ORDER BY proposed_at DESC
            """
            )

        proposals = cur.fetchall()
        cur.close()
        conn.close()

        # Convert to list of dicts with serializable dates
        proposals_list = []
        for p in proposals:
            proposal_dict = dict(p)
            if proposal_dict.get("proposed_at"):
                proposal_dict["proposed_at"] = proposal_dict["proposed_at"].isoformat()
            proposals_list.append(proposal_dict)

        return jsonify({"success": True, "proposals": proposals_list, "count": len(proposals_list)})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>", methods=["GET"])
@login_required
@admin_required
def improvements_get_proposal(proposal_id):
    """Get specific improvement proposal"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT * FROM improvement_proposals
            WHERE id = %s
        """,
            (proposal_id,),
        )

        proposal = cur.fetchone()
        cur.close()
        conn.close()

        if not proposal:
            return jsonify({"success": False, "error": "Proposal not found"}), 404

        # Convert dates to ISO format
        proposal_dict = dict(proposal)
        for date_field in [
            "proposed_at",
            "reviewed_at",
            "implemented_at",
            "approved_at",
        ]:
            if proposal_dict.get(date_field):
                proposal_dict[date_field] = proposal_dict[date_field].isoformat()

        return jsonify({"success": True, "proposal": proposal_dict})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>", methods=["DELETE"])
@login_required
@admin_required
def improvements_delete_proposal(proposal_id):
    """Permanently delete a proposal (only for deletable statuses)"""
    try:
        conn = get_db()
        cur = conn.cursor()

        # Check proposal exists and is in deletable status
        cur.execute(
            """
            SELECT id, status, title FROM improvement_proposals WHERE id = %s
        """,
            (proposal_id,),
        )
        proposal = cur.fetchone()

        if not proposal:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Proposal not found"}), 404

        # Only allow deletion of certain statuses
        deletable_statuses = [
            "proposed",
            "failed",
            "archived",
            "rejected",
            "pending",
            "pending_approval",
        ]
        if proposal[1] not in deletable_statuses:
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f'Cannot delete proposal with status "{proposal[1]}". Only proposals with status: {", ".join(deletable_statuses)} can be deleted.',
                    }
                ),
                400,
            )

        # Clear code_issues references first
        cur.execute(
            "UPDATE code_issues SET proposal_id = NULL WHERE proposal_id = %s",
            (proposal_id,),
        )

        # Delete sandbox instances
        cur.execute("DELETE FROM sandbox_instances WHERE proposal_id = %s", (proposal_id,))

        # Delete the proposal
        cur.execute("DELETE FROM improvement_proposals WHERE id = %s", (proposal_id,))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "message": f'Proposal #{proposal_id} "{proposal[2]}" deleted permanently',
            }
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/approve", methods=["POST"])
@login_required
@admin_required
def improvements_approve_proposal(proposal_id):
    """Approve an improvement proposal and auto-generate plan if needed"""
    try:
        conn = get_db()
        cur = conn.cursor()

        # First get the proposal to check metadata and plan_steps
        cur.execute(
            """
            SELECT id, title, description, metadata, plan_steps, category
            FROM improvement_proposals
            WHERE id = %s AND status IN ('pending_approval', 'pending', 'proposed')
        """,
            (proposal_id,),
        )

        proposal = cur.fetchone()
        if not proposal:
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Proposal not found or already processed",
                    }
                ),
                404,
            )

        prop_id, title, description, metadata, existing_plan, category = proposal

        # Auto-generate plan_steps if not present
        plan_steps = existing_plan
        if not plan_steps:
            # Parse metadata
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}

            file_path = metadata.get("file_path") if metadata else None
            line_number = metadata.get("line_number") if metadata else None
            issue_type = metadata.get("issue_type", category) if metadata else category

            if file_path:
                # CodeRabbit-sourced proposal with specific file target
                plan_steps = [
                    {
                        "step": 1,
                        "description": "Read and analyze the target file",
                        "action": "read_file",
                        "target": file_path,
                        "details": f"Read file to understand current implementation around line {line_number or 'N/A'}",
                    },
                    {
                        "step": 2,
                        "description": f"Apply the fix: {title}",
                        "action": "edit_file",
                        "target": file_path,
                        "details": f"{description}\n\nFocus on line {line_number or 'the relevant section'}. Issue type: {issue_type}",
                    },
                ]
            else:
                # Generic proposal
                plan_steps = [
                    {
                        "step": 1,
                        "description": "Analyze and implement the improvement",
                        "action": "edit_file",
                        "target": "TBD",
                        "details": description or title,
                    }
                ]

        # Update proposal with approval and plan_steps
        cur.execute(
            """
            UPDATE improvement_proposals
            SET status = 'approved',
                approved_by = %s,
                approved_at = NOW(),
                reviewed_at = NOW(),
                plan_steps = %s
            WHERE id = %s
            RETURNING id
        """,
            (current_user.id, json.dumps(plan_steps), proposal_id),
        )

        cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "message": "Proposal approved with execution plan",
                "proposal_id": proposal_id,
                "plan_generated": existing_plan is None,
                "steps_count": len(plan_steps) if plan_steps else 0,
            }
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/reject", methods=["POST"])
@login_required
@admin_required
def improvements_reject_proposal(proposal_id):
    """Reject an improvement proposal"""
    try:
        data = request.json
        reason = data.get("reason", "Rejected by user")

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE improvement_proposals
            SET status = 'rejected',
                reviewed_at = NOW(),
                metadata = jsonb_set(
                    COALESCE(metadata, '{}'::jsonb),
                    '{rejection_reason}',
                    to_jsonb(%s::text)
                )
            WHERE id = %s AND status IN ('pending_approval', 'pending', 'proposed')
            RETURNING id
        """,
            (reason, proposal_id),
        )

        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not result:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Proposal not found or already processed",
                    }
                ),
                404,
            )

        return jsonify(
            {
                "success": True,
                "message": "Proposal rejected",
                "proposal_id": proposal_id,
            }
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/retry", methods=["POST"])
@login_required
@admin_required
def improvements_retry_failed_proposal(proposal_id):
    """Retry a failed improvement proposal with automatic escalation"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from improvement_conversation_engine import retry_proposal_with_escalation

        result = retry_proposal_with_escalation(proposal_id=proposal_id, user_id=current_user.id)

        if result["success"]:
            return jsonify(
                {
                    "success": True,
                    "escalated": result.get("escalated", False),
                    "attempt_number": result.get("attempt_number", 1),
                    "assigned_agent": result.get("assigned_agent", "Internal Team"),
                    "agent_type": result.get("agent_type", "internal"),
                    "message": result.get("response", "Retry started successfully"),
                    "proposal_id": proposal_id,
                }
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": result.get("response", "Failed to retry proposal"),
                    }
                ),
                500,
            )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/regenerate-plan", methods=["POST"])
@login_required
@admin_required
def improvements_regenerate_plan(proposal_id):
    """Regenerate implementation plan for a proposal using AI code generation"""
    try:
        # Import the code generation engine
        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from code_generation_engine import generate_code_for_proposal

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get the existing proposal with metadata
        cur.execute(
            """
            SELECT id, title, description, category, priority, metadata
            FROM improvement_proposals
            WHERE id = %s
        """,
            (proposal_id,),
        )

        proposal = cur.fetchone()
        if not proposal:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Proposal not found"}), 404

        title = proposal["title"]
        description = proposal["description"] or title
        category = proposal["category"] or "general"
        metadata = proposal["metadata"] or {}

        # Parse metadata if it's a string
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except:
                metadata = {}

        # Check if this is a CodeRabbit issue with file info
        file_path = metadata.get("file_path")
        target_files = [file_path] if file_path else None

        # Use AI to generate code changes
        print(f"🤖 Generating AI plan for proposal #{proposal_id}: {title}")

        code_result = generate_code_for_proposal(
            proposal_id=proposal_id,
            proposal_title=title,
            proposal_description=description,
            category=category,
            target_files=target_files,
        )

        if not code_result.get("success"):
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f'AI code generation failed: {code_result.get("error", "Unknown error")}',
                    }
                ),
                500,
            )

        # Convert code changes to plan_steps format
        changes = code_result.get("changes", [])
        plan_steps = []

        for i, change in enumerate(changes, 1):
            plan_steps.append(
                {
                    "step": i,
                    "description": change.get("description", f"Change {i}"),
                    "action": change.get("action", "edit_file"),
                    "target": change.get("file_path", "unknown"),
                    "details": change.get("diff", change.get("new_content", "")),
                    "old_content": change.get("old_content", ""),
                    "new_content": change.get("new_content", ""),
                }
            )

        # If AI didn't generate any changes, create a basic plan
        if not plan_steps:
            line_number = metadata.get("line_number")
            if file_path:
                plan_steps = [
                    {
                        "step": 1,
                        "description": "Read and analyze the target file",
                        "action": "read_file",
                        "target": file_path,
                        "details": f"Read file to understand current implementation around line {line_number or 'N/A'}",
                    },
                    {
                        "step": 2,
                        "description": f"Apply the fix: {title}",
                        "action": "edit_file",
                        "target": file_path,
                        "details": f"{description}",
                    },
                ]
            else:
                search_term = title.split(":")[-1].strip() if ":" in title else title
                plan_steps = [
                    {
                        "step": 1,
                        "description": "Search for relevant code",
                        "action": "search_code",
                        "target": search_term[:50],
                        "details": f"Find files related to: {title}",
                    },
                    {
                        "step": 2,
                        "description": f"Implement: {title}",
                        "action": "edit_file",
                        "target": "TBD",
                        "details": description,
                    },
                ]

        # Update the proposal with new plan_steps and AI metadata
        cur.execute(
            """
            UPDATE improvement_proposals
            SET plan_steps = %s,
                metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                test_retry_count = 0
            WHERE id = %s
            RETURNING id
        """,
            (
                json.dumps(plan_steps),
                json.dumps(
                    {
                        "ai_generated_plan": True,
                        "plan_generated_at": datetime.now().isoformat(),
                        "model_used": code_result.get("metadata", {}).get("model_used", "unknown"),
                        "changes_count": len(changes),
                    }
                ),
                proposal_id,
            ),
        )

        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not result:
            return (
                jsonify({"success": False, "error": "Failed to update proposal"}),
                500,
            )

        return jsonify(
            {
                "success": True,
                "message": f"AI-generated plan with {len(plan_steps)} executable steps",
                "steps_count": len(plan_steps),
                "proposal_id": proposal_id,
                "ai_generated": True,
                "has_file_target": bool(file_path),
                "model_used": code_result.get("metadata", {}).get("model_used", "unknown"),
            }
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/execute", methods=["POST"])
@login_required
@admin_required
def improvements_execute_proposal(proposal_id):
    """Execute an approved improvement proposal using WorkflowOrchestrator with retry support"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

        from tools.backup_manager import create_backup

        data = request.get_json(silent=True) or {}
        skip_backup = data.get("skip_backup", False)
        use_orchestrator = data.get("use_orchestrator", True)  # Default to using orchestrator

        # First check if proposal has plan_steps
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, status, plan_steps, title
            FROM improvement_proposals
            WHERE id = %s
        """,
            (proposal_id,),
        )
        proposal = cur.fetchone()
        cur.close()
        conn.close()

        if not proposal:
            return jsonify({"success": False, "error": "Proposal not found"}), 404

        # Check if plan_steps exist
        if not proposal.get("plan_steps") or len(proposal.get("plan_steps", [])) == 0:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": 'No implementation plan found. Please click "Regenerate Plan" first to generate an AI implementation plan.',
                        "legacy": True,
                        "suggestion": 'Click the "Regenerate Plan" button to create an AI-generated implementation plan.',
                    }
                ),
                400,
            )

        # STEP 1: Create pre-deployment backup
        backup_result = None
        if not skip_backup:
            print(f"Creating pre-deployment backup for proposal #{proposal_id}...")
            try:
                backup_result = create_backup(
                    description=f"pre_improvement_{proposal_id}",
                    created_by_username=current_user.username,
                    proposal_id=proposal_id,
                )

                if backup_result.get("success"):
                    backup_name = backup_result["backup_name"]
                    print(f"Backup created: {backup_name}")

                    # Store backup reference in proposal
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute(
                        """
                        UPDATE improvement_proposals
                        SET backup_name = %s,
                            backup_created_at = NOW()
                        WHERE id = %s
                    """,
                        (backup_name, proposal_id),
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
            except Exception as backup_error:
                print(f"Backup error (non-fatal): {backup_error}")
                traceback.print_exc()

        # STEP 2: Execute using WorkflowOrchestrator (with retry support)
        print(f"Executing proposal #{proposal_id} via WorkflowOrchestrator...")

        if use_orchestrator:
            try:
                from workflow_orchestrator import execute_workflow

                result = execute_workflow(proposal_id)

                # If workflow succeeded, check test results for retry handling
                if result.get("success"):
                    # Check if tests failed - integrate with retry handler
                    test_passed = result.get("test_passed", True)
                    if not test_passed:
                        from test_retry_handler import handle_test_failure

                        test_results = result.get("test_results", {})
                        retry_result = handle_test_failure(proposal_id, test_results)
                        result["retry_info"] = retry_result
                        result["message"] = f"Tests failed. {retry_result.get('message', 'Retry initiated.')}"

            except ImportError as ie:
                print(f"WorkflowOrchestrator not available: {ie}, falling back to direct execution")
                # Fallback to direct execution
                from ai_bridge.archie_bridge import execute_proposal

                result = execute_proposal(
                    proposal_id=proposal_id,
                    user_id=current_user.id,
                    approved_steps=data.get("steps", None),
                )
        else:
            # Direct execution without orchestrator
            from ai_bridge.archie_bridge import execute_proposal

            result = execute_proposal(
                proposal_id=proposal_id,
                user_id=current_user.id,
                approved_steps=data.get("steps", None),
            )

        # Add backup info to result
        if backup_result and backup_result.get("success"):
            result["backup_created"] = True
            result["backup_name"] = backup_result["backup_name"]
            result["backup_path"] = backup_result.get("backup_path")

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/restore", methods=["POST"])
@login_required
@admin_required
def improvements_restore_proposal(proposal_id):
    """Restore files from proposal backups"""
    try:
        from ai_bridge.archie_bridge import restore_from_backups, get_proposal_backups

        backups_result = get_proposal_backups(proposal_id)

        if not backups_result["success"]:
            return jsonify(backups_result), 404

        if backups_result["count"] == 0:
            return (
                jsonify({"success": False, "error": "No backups found for this proposal"}),
                404,
            )

        restore_result = restore_from_backups(proposal_id, backups_result["backups"])

        return jsonify(restore_result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/backups", methods=["GET"])
@login_required
@admin_required
def improvements_get_backups(proposal_id):
    """Get list of backups for a proposal"""
    try:
        from ai_bridge.archie_bridge import get_proposal_backups

        result = get_proposal_backups(proposal_id)
        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/escalate", methods=["POST"])
@login_required
@admin_required
def improvements_escalate_proposal(proposal_id):
    """Escalate a failed proposal to senior developers"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get proposal details
        cur.execute("SELECT * FROM improvement_proposals WHERE id = %s", (proposal_id,))
        proposal = cur.fetchone()

        if not proposal:
            return jsonify({"success": False, "error": "Proposal not found"}), 404

        # Update status to escalated
        cur.execute(
            """
            UPDATE improvement_proposals
            SET status = 'escalated', escalated_at = NOW()
            WHERE id = %s
        """,
            (proposal_id,),
        )

        # Create notification for senior developers
        cur.execute(
            """
            INSERT INTO notifications (user_id, type, title, message, is_read)
            VALUES (%s, %s, %s, %s, FALSE)
        """,
            (
                2,  # Admin user
                "task_escalated",
                f"Failed Task Escalated: Proposal #{proposal_id}",
                f'Proposal "{proposal["title"]}" has failed and needs senior developer attention.',
            ),
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "message": "Proposal escalated to senior developers"})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/archive", methods=["POST"])
@login_required
@admin_required
def improvements_archive_proposal(proposal_id):
    """Archive a proposal for future reference"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE improvement_proposals
            SET status = 'archived', archived_at = NOW()
            WHERE id = %s
        """,
            (proposal_id,),
        )

        if cur.rowcount == 0:
            return jsonify({"success": False, "error": "Proposal not found"}), 404

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "message": "Proposal archived"})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/stuck", methods=["GET"])
@login_required
@admin_required
def get_stuck_proposals():
    """Get all proposals stuck in pending status for > 48 hours"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                id, title, description, category, priority, status,
                proposed_at,
                EXTRACT(EPOCH FROM (NOW() - proposed_at))/3600 as hours_stuck
            FROM improvement_proposals
            WHERE status IN ('pending', 'pending_approval', 'proposed')
            AND proposed_at < NOW() - INTERVAL '48 hours'
            ORDER BY proposed_at ASC
        """
        )
        stuck_proposals = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "stuck_proposals": stuck_proposals,
                "count": len(stuck_proposals),
            }
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/unstuck", methods=["POST"])
@login_required
@admin_required
def unstuck_proposal(proposal_id):
    """Manually unstick a proposal by auto-escalating it"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get proposal details
        cur.execute("SELECT * FROM improvement_proposals WHERE id = %s", (proposal_id,))
        proposal = cur.fetchone()

        if not proposal:
            return jsonify({"success": False, "error": "Proposal not found"}), 404

        # Check if it's actually stuck
        cur.execute(
            """
            SELECT EXTRACT(EPOCH FROM (NOW() - proposed_at))/3600 as hours_pending
            FROM improvement_proposals
            WHERE id = %s
        """,
            (proposal_id,),
        )
        result = cur.fetchone()
        hours_pending = result["hours_pending"] if result else 0

        # Update status to escalated with note
        cur.execute(
            """
            UPDATE improvement_proposals
            SET
                status = 'escalated',
                escalated_at = NOW(),
                notes = COALESCE(notes || E'\n\n', '') || %s
            WHERE id = %s
        """,
            (
                f"[AUTO-UNSTUCK] Proposal was stuck in '{proposal['status']}' for {hours_pending:.1f} hours.",
                proposal_id,
            ),
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "message": f"Proposal unstuck and escalated (was stuck for {hours_pending:.1f} hours)",
            }
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/auto-escalate-stuck", methods=["POST"])
@login_required
@admin_required
def auto_escalate_stuck_proposals():
    """Automatically escalate all proposals stuck > 48 hours"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, title, status,
                   EXTRACT(EPOCH FROM (NOW() - proposed_at))/3600 as hours_stuck
            FROM improvement_proposals
            WHERE status IN ('pending', 'pending_approval', 'proposed')
            AND proposed_at < NOW() - INTERVAL '48 hours'
        """
        )
        stuck_proposals = cur.fetchall()

        escalated_count = 0
        for proposal in stuck_proposals:
            cur.execute(
                """
                UPDATE improvement_proposals
                SET
                    status = 'escalated',
                    escalated_at = NOW(),
                    notes = COALESCE(notes || E'\n\n', '') || %s
                WHERE id = %s
            """,
                (
                    f"[AUTO-ESCALATED] Stuck in '{proposal['status']}' for {proposal['hours_stuck']:.1f} hours.",
                    proposal["id"],
                ),
            )
            escalated_count += 1

        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "message": f"Auto-escalated {escalated_count} stuck proposals",
                "count": escalated_count,
            }
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# WORKFLOW ROUTES
# ============================================================================


@improvements_bp.route("/workflow/status/<int:proposal_id>", methods=["GET"])
@login_required
def get_workflow_status_api(proposal_id):
    """Get workflow status for a proposal"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from background_workflow_runner import get_proposal_workflow_status

        status = get_proposal_workflow_status(proposal_id)

        if not status:
            return (
                jsonify({"success": False, "message": "No workflow found for this proposal"}),
                404,
            )

        return jsonify({"success": True, "workflow": status})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/workflow/start/<int:proposal_id>", methods=["POST"])
@login_required
@admin_required
def start_workflow_manually(proposal_id):
    """Manually start workflow for a proposal"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from background_workflow_runner import start_workflow_background

        result = start_workflow_background(proposal_id)

        if result.get("success"):
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/workflow/run-automation", methods=["POST"])
@login_required
@admin_required
def run_workflow_automation():
    """Manually trigger workflow automation cycle"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from workflow_automator import WorkflowAutomator

        automator = WorkflowAutomator()
        result = automator.run_workflow_automation()

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/workflow/stats", methods=["GET"])
@login_required
@admin_required
def get_workflow_stats():
    """Get workflow statistics and metrics"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from workflow_automator import WorkflowAutomator

        automator = WorkflowAutomator()
        result = automator.get_workflow_stats()

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# PROPOSAL STEPS & DIFF ROUTES
# ============================================================================


@improvements_bp.route("/proposals/<int:proposal_id>/generate-steps", methods=["POST"])
@login_required
@admin_required
def generate_implementation_steps(proposal_id):
    """Generate step-by-step implementation guidance for a proposal"""
    try:
        from ai_bridge.step_guidance_generator import StepGuidanceGenerator

        generator = StepGuidanceGenerator()
        steps_data = generator.generate_steps(proposal_id=proposal_id)

        # Save steps to proposal
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE improvement_proposals
            SET plan_steps = %s
            WHERE id = %s
        """,
            (json.dumps(steps_data), proposal_id),
        )
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "steps": steps_data})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/update-step", methods=["POST"])
@login_required
@admin_required
def update_implementation_step(proposal_id):
    """Update the status of a specific implementation step"""
    try:
        data = request.get_json()
        step_number = data.get("step_number")
        status = data.get("status")
        notes = data.get("notes")

        from ai_bridge.step_guidance_generator import update_step

        result = update_step(proposal_id=proposal_id, step_number=step_number, status=status, notes=notes)

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/generate-diff", methods=["POST"])
@login_required
@admin_required
def generate_code_diff(proposal_id):
    """Generate code diff for a proposal"""
    try:
        data = request.get_json()
        old_content = data.get("old_content", "")
        new_content = data.get("new_content", "")
        filename = data.get("filename", "file.txt")

        from ai_bridge.code_diff_engine import CodeDiffEngine

        engine = CodeDiffEngine()
        diff_data = engine.generate_diff(old_content, new_content, filename)
        side_by_side = engine.generate_side_by_side_diff(old_content, new_content, filename)

        # Save diff to proposal
        conn = get_db()
        cur = conn.cursor()
        diff_markdown = engine.create_proposal_diff(
            proposal_description="Code changes",
            file_path=filename,
            old_content=old_content,
            new_content=new_content,
        )
        cur.execute(
            """
            UPDATE improvement_proposals
            SET code_diff = %s
            WHERE id = %s
        """,
            (diff_markdown, proposal_id),
        )
        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "diff": diff_data,
                "side_by_side": side_by_side,
                "markdown": diff_markdown,
            }
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/preview", methods=["GET"])
@login_required
@admin_required
def get_code_preview(proposal_id):
    """Get code preview/diff for a proposal"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, title, code_diff, code_changes, plan_steps
            FROM improvement_proposals
            WHERE id = %s
        """,
            (proposal_id,),
        )

        proposal = cur.fetchone()
        cur.close()
        conn.close()

        if not proposal:
            return jsonify({"success": False, "error": "Proposal not found"}), 404

        code_diff = proposal[2] if len(proposal) > 2 else None
        code_changes = proposal[3] if len(proposal) > 3 else None
        plan_steps = proposal[4] if len(proposal) > 4 else None

        diff_data = None
        if code_diff:
            try:
                diff_data = json.loads(code_diff) if code_diff.startswith("{") else code_diff
            except:
                diff_data = code_diff

        return jsonify(
            {
                "success": True,
                "proposal_id": proposal_id,
                "title": proposal[1],
                "code_diff": diff_data,
                "code_changes": code_changes,
                "plan_steps": plan_steps,
                "has_preview": bool(code_diff or code_changes),
            }
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/apply-changes", methods=["POST"])
@login_required
@admin_required
def apply_code_changes(proposal_id):
    """Apply code changes to a file with automatic backup"""
    try:
        data = request.get_json()
        filepath = data.get("filepath")
        new_content = data.get("new_content")
        create_backup = data.get("backup", True)

        if not filepath or new_content is None:
            return (
                jsonify({"success": False, "error": "Missing filepath or new_content"}),
                400,
            )

        # Validate filepath (security check)
        if ".." in filepath or filepath.startswith("/"):
            return jsonify({"success": False, "error": "Invalid filepath"}), 400

        from ai_bridge.code_diff_engine import apply_changes

        result = apply_changes(filepath, new_content, backup=create_backup)

        if result["success"]:
            # Log the change
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO improvement_workflow_states
                (proposal_id, from_status, to_status, changed_by, reason, automated)
                VALUES (%s, 'in_progress', 'code_applied', %s, %s, false)
            """,
                (
                    proposal_id,
                    current_user.id if current_user else None,
                    f"Applied changes to {filepath}. Backup: {result.get('backup_path', 'none')}",
                ),
            )
            conn.commit()
            cur.close()
            conn.close()

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/activity", methods=["GET"])
@login_required
@admin_required
def get_proposal_activity(proposal_id):
    """Get activity log for a proposal"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT
                id,
                from_status,
                to_status,
                changed_at,
                reason,
                automated
            FROM improvement_workflow_states
            WHERE proposal_id = %s
            ORDER BY changed_at DESC
        """,
            (proposal_id,),
        )

        activities = cur.fetchall()
        cur.close()
        conn.close()

        return (
            jsonify(
                {
                    "success": True,
                    "activities": [dict(activity) for activity in activities],
                }
            ),
            200,
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# TEAM ROUTES
# ============================================================================


@improvements_bp.route("/proposals/<int:proposal_id>/team", methods=["GET"])
@login_required
@admin_required
def get_proposal_team(proposal_id):
    """Get the currently assigned team for a proposal"""
    try:
        from ai_bridge.team_assignment_engine import TeamAssignmentEngine

        conn = get_db()
        engine = TeamAssignmentEngine(conn)
        team = engine.get_team_for_proposal(proposal_id)
        conn.close()

        return jsonify({"success": True, "team": team, "team_size": len(team)})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/assign-team", methods=["POST"])
@login_required
@admin_required
def assign_team_to_proposal_endpoint(proposal_id):
    """Manually assign or reassign team to a proposal"""
    try:
        data = request.get_json() or {}
        force_internal = data.get("force_internal", True)

        from ai_bridge.team_assignment_engine import assign_team_to_proposal

        result = assign_team_to_proposal(
            proposal_id=proposal_id,
            force_internal=force_internal,
            user_id=current_user.id if current_user else None,
        )

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/team-assignments/<int:assignment_id>/reassign", methods=["POST"])
@login_required
@admin_required
def reassign_team_member(assignment_id):
    """Reassign a specific team member to a different agent"""
    try:
        data = request.get_json()
        new_agent_id = data.get("new_agent_id")
        reason = data.get("reason", "Manual reassignment by admin")

        if not new_agent_id:
            return jsonify({"success": False, "error": "new_agent_id is required"}), 400

        from ai_bridge.team_assignment_engine import TeamAssignmentEngine

        conn = get_db()
        engine = TeamAssignmentEngine(conn)
        success = engine.reassign_agent(assignment_id, new_agent_id, reason)
        conn.close()

        if success:
            return jsonify({"success": True, "message": "Team member reassigned successfully"})
        else:
            return (
                jsonify({"success": False, "error": "Failed to reassign team member"}),
                500,
            )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/team-assignments/<int:assignment_id>/update-status", methods=["POST"])
@login_required
@admin_required
def update_team_assignment_status(assignment_id):
    """Update the status of a team assignment"""
    try:
        data = request.get_json()
        status = data.get("status")
        notes = data.get("notes")

        if not status:
            return jsonify({"success": False, "error": "status is required"}), 400

        if status not in ["assigned", "in_progress", "completed", "blocked"]:
            return jsonify({"success": False, "error": "Invalid status"}), 400

        conn = get_db()
        cur = conn.cursor()

        update_fields = ["status = %s"]
        params = [status]

        if notes:
            update_fields.append("notes = %s")
            params.append(notes)

        if status == "completed":
            update_fields.append("completed_at = NOW()")

        params.append(assignment_id)

        cur.execute(
            f"""
            UPDATE improvement_team_assignments
            SET {', '.join(update_fields)}
            WHERE id = %s
        """,
            params,
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "message": "Status updated successfully"})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/team/add-member", methods=["POST"])
@login_required
@admin_required
def add_team_member(proposal_id):
    """Add an additional team member to a proposal"""
    try:
        data = request.get_json()
        agent_id = data.get("agent_id")
        role = data.get("role", "developer")

        if not agent_id:
            return jsonify({"success": False, "error": "agent_id is required"}), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO improvement_team_assignments
            (proposal_id, agent_id, role, status, assigned_by, assigned_at)
            VALUES (%s, %s, %s, 'assigned', %s, NOW())
            ON CONFLICT (proposal_id, agent_id) DO NOTHING
            RETURNING id
        """,
            (proposal_id, agent_id, role, current_user.id if current_user else None),
        )

        result = cur.fetchone()

        if result:
            cur.execute(
                """
                UPDATE agents
                SET current_load = COALESCE(current_load, 0) + 1,
                    last_used = NOW()
                WHERE id = %s
            """,
                (agent_id,),
            )

            cur.execute(
                """
                UPDATE improvement_proposals
                SET team_size = (
                    SELECT COUNT(*) FROM improvement_team_assignments
                    WHERE proposal_id = %s
                )
                WHERE id = %s
            """,
                (proposal_id, proposal_id),
            )

            conn.commit()
            cur.close()
            conn.close()

            return jsonify({"success": True, "assignment_id": result[0]})
        else:
            conn.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Agent already assigned to this proposal",
                    }
                ),
                400,
            )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route(
    "/proposals/<int:proposal_id>/team/remove-member/<int:assignment_id>",
    methods=["DELETE"],
)
@login_required
@admin_required
def remove_team_member(proposal_id, assignment_id):
    """Remove a team member from a proposal"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT agent_id FROM improvement_team_assignments
            WHERE id = %s AND proposal_id = %s
        """,
            (assignment_id, proposal_id),
        )

        result = cur.fetchone()

        if not result:
            conn.close()
            return (
                jsonify({"success": False, "error": "Team assignment not found"}),
                404,
            )

        agent_id = result["agent_id"]

        cur.execute("DELETE FROM improvement_team_assignments WHERE id = %s", (assignment_id,))

        cur.execute(
            """
            UPDATE agents
            SET current_load = GREATEST(COALESCE(current_load, 0) - 1, 0)
            WHERE id = %s
        """,
            (agent_id,),
        )

        cur.execute(
            """
            UPDATE improvement_proposals
            SET team_size = (
                SELECT COUNT(*) FROM improvement_team_assignments
                WHERE proposal_id = %s
            )
            WHERE id = %s
        """,
            (proposal_id, proposal_id),
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "message": "Team member removed successfully"})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/teams/active", methods=["GET"])
@login_required
@admin_required
def get_active_team_assignments():
    """Get all active team assignments"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT
                ta.proposal_id,
                p.title as proposal_title,
                ta.agent_id,
                COALESCE(a.first_name || ' ' || a.last_name, a.name) as agent_name,
                a.worker_type as agent_worker_type,
                ta.role,
                ta.assigned_at::text,
                ta.status
            FROM improvement_team_assignments ta
            JOIN improvement_proposals p ON ta.proposal_id = p.id
            JOIN agents a ON ta.agent_id = a.id
            WHERE ta.status IN ('assigned', 'in_progress')
            AND p.status NOT IN ('completed', 'rejected', 'archived')
            ORDER BY ta.assigned_at DESC
        """
        )

        assignments = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({"success": True, "assignments": assignments}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/teams/assignments", methods=["GET"])
@login_required
@admin_required
def get_team_assignments():
    """Alias for /teams/active - Get all active team assignments"""
    return get_active_team_assignments()


# ============================================================================
# SANDBOX ROUTES
# ============================================================================


@improvements_bp.route("/proposals/<int:proposal_id>/sandbox/create", methods=["POST"])
@login_required
@admin_required
def create_sandbox(proposal_id):
    """Create a sandbox environment for testing an improvement proposal"""
    try:
        data = request.get_json() or {}

        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from sandbox_manager import SandboxManager

        manager = SandboxManager()

        result = manager.create_sandbox(
            proposal_id=proposal_id,
            sandbox_type=data.get("sandbox_type"),
            backup_ref=data.get("backup_ref"),
            metadata=data.get("metadata"),
        )

        if result["success"]:
            return jsonify(result), 200
        else:
            return jsonify(result), 400

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/sandbox/<int:sandbox_id>", methods=["GET"])
@login_required
@admin_required
def get_sandbox_status(sandbox_id):
    """Get the status and details of a sandbox instance"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from sandbox_manager import SandboxManager

        manager = SandboxManager()
        result = manager.get_sandbox_status(sandbox_id)

        if "error" in result:
            return jsonify(result), 404

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/sandbox/<int:sandbox_id>/test", methods=["POST"])
@login_required
@admin_required
def run_sandbox_tests(sandbox_id):
    """Run tests in a sandbox environment"""
    try:
        data = request.get_json() or {}
        test_suite = data.get("test_suite", "default")

        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from sandbox_manager import SandboxManager

        manager = SandboxManager()
        result = manager.run_tests(sandbox_id, test_suite)

        if result["success"]:
            return jsonify(result), 200
        else:
            return jsonify(result), 400

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/sandbox/<int:sandbox_id>/destroy", methods=["DELETE"])
@login_required
@admin_required
def destroy_sandbox(sandbox_id):
    """Destroy a sandbox and cleanup resources"""
    try:
        force = request.args.get("force", "false").lower() == "true"

        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from sandbox_manager import SandboxManager

        manager = SandboxManager()
        result = manager.destroy_sandbox(sandbox_id, force=force)

        if result["success"]:
            return jsonify(result), 200
        else:
            return jsonify(result), 400

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/sandbox", methods=["GET"])
@login_required
@admin_required
def list_sandboxes():
    """List sandbox instances with optional filters"""
    try:
        proposal_id = request.args.get("proposal_id", type=int)
        status = request.args.get("status")
        limit = request.args.get("limit", 20, type=int)

        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from sandbox_manager import SandboxManager

        manager = SandboxManager()
        result = manager.list_sandboxes(proposal_id=proposal_id, status=status, limit=limit)

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/sandbox/determine-type", methods=["GET"])
@login_required
@admin_required
def determine_sandbox_type(proposal_id):
    """Determine which sandbox type should be used for a proposal"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from sandbox_manager import SandboxManager

        manager = SandboxManager()
        sandbox_type = manager.determine_sandbox_type(proposal_id=proposal_id)

        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT priority, complexity, category
            FROM improvement_proposals
            WHERE id = %s
        """,
            (proposal_id,),
        )
        proposal = cur.fetchone()
        cur.close()
        conn.close()

        if not proposal:
            return jsonify({"success": False, "error": "Proposal not found"}), 404

        reason = ""
        if proposal["category"] in [
            "security",
            "database",
            "architecture",
            "performance",
            "api",
            "infrastructure",
        ]:
            reason = f"High-risk category '{proposal['category']}' requires full Docker isolation"
        elif proposal["priority"] in ["high", "critical"]:
            reason = f"High priority ({proposal['priority']}) requires full Docker isolation"
        elif proposal.get("complexity") == "high":
            reason = "High complexity requires full Docker isolation"
        else:
            reason = "Low risk proposal can use lightweight schema sandbox"

        return (
            jsonify(
                {
                    "success": True,
                    "proposal_id": proposal_id,
                    "recommended_type": sandbox_type,
                    "priority": proposal["priority"],
                    "complexity": proposal.get("complexity"),
                    "category": proposal["category"],
                    "reason": reason,
                }
            ),
            200,
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/sandbox", methods=["GET"])
@login_required
@admin_required
def get_proposal_sandbox(proposal_id):
    """Get sandbox details for a specific proposal"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT id, title, category, priority, status, complexity
            FROM improvement_proposals
            WHERE id = %s
        """,
            (proposal_id,),
        )
        proposal = cur.fetchone()

        if not proposal:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Proposal not found"}), 404

        cur.execute(
            """
            SELECT *
            FROM sandbox_instances
            WHERE proposal_id = %s
            AND destroyed_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
        """,
            (proposal_id,),
        )

        sandbox = cur.fetchone()

        tables_cloned = None
        if sandbox and sandbox["sandbox_type"] == "schema_separation" and sandbox.get("schema_name"):
            try:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = %s
                """,
                    (sandbox["schema_name"],),
                )
                result = cur.fetchone()
                if result:
                    tables_cloned = result[0]
            except:
                pass

        cur.close()
        conn.close()

        if sandbox and tables_cloned is not None:
            if not sandbox.get("metadata"):
                sandbox["metadata"] = {}
            sandbox["metadata"]["tables_cloned"] = tables_cloned

        return (
            jsonify(
                {
                    "success": True,
                    "sandbox": dict(sandbox) if sandbox else None,
                    "proposal": dict(proposal),
                }
            ),
            200,
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/sandboxes/active", methods=["GET"])
@login_required
@admin_required
def get_active_sandboxes():
    """Get all active sandboxes"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT
                id,
                proposal_id,
                sandbox_type,
                container_id,
                schema_name,
                status,
                created_at::text,
                destroyed_at::text,
                test_results,
                backup_ref,
                metadata
            FROM sandbox_instances
            WHERE status IN ('creating', 'ready', 'testing')
            AND destroyed_at IS NULL
            ORDER BY created_at DESC
        """
        )

        sandboxes = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({"success": True, "sandboxes": sandboxes}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/sandboxes/create", methods=["POST"])
@login_required
@admin_required
def create_sandbox_standalone():
    """Create a sandbox for a proposal (standalone endpoint)"""
    try:
        data = request.get_json()
        proposal_id = data.get("proposal_id")

        if not proposal_id:
            return jsonify({"success": False, "error": "proposal_id required"}), 400

        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from sandbox_manager import SandboxManager

        manager = SandboxManager()

        # Get sandbox type from request, or determine automatically
        sandbox_type = data.get("sandbox_type")

        # If docker is requested or auto-determined, check if docker-compose is available
        # Inside the container, docker-compose is not available, so fallback to schema
        if not sandbox_type:
            sandbox_type = manager.determine_sandbox_type(proposal_id=proposal_id)

        # Inside the container, always use schema_separation
        # Docker-based sandboxes require running from host, not inside container
        if sandbox_type == "docker_container":
            print("[Sandbox] Running inside container, using schema_separation instead of docker_container")
            sandbox_type = "schema_separation"

        result = manager.create_sandbox(proposal_id, sandbox_type=sandbox_type)

        return jsonify(result), 200 if result["success"] else 500

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/sandboxes/<int:sandbox_id>/logs", methods=["GET"])
@login_required
@admin_required
def get_sandbox_logs(sandbox_id):
    """Get logs from a sandbox including test results"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get sandbox metadata
        cur.execute(
            """
            SELECT metadata, test_results, status, proposal_id
            FROM sandbox_instances
            WHERE id = %s
        """,
            (sandbox_id,),
        )

        sandbox = cur.fetchone()

        if not sandbox:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Sandbox not found"}), 404

        # Build comprehensive logs
        logs_parts = []
        logs_parts.append(f"=== SANDBOX #{sandbox_id} ===")
        logs_parts.append(f"Status: {sandbox.get('status', 'unknown')}")
        logs_parts.append(f"Proposal: #{sandbox.get('proposal_id', 'N/A')}")
        logs_parts.append("")

        # Add metadata logs if available
        metadata = sandbox.get("metadata") or {}
        if isinstance(metadata, dict):
            if metadata.get("application_results"):
                logs_parts.append("=== CODE APPLICATION ===")
                app_results = metadata["application_results"]
                logs_parts.append(f"Files Modified: {app_results.get('files_modified', 0)}")
                logs_parts.append(f"Files Created: {app_results.get('files_created', 0)}")
                logs_parts.append(f"Applied At: {app_results.get('applied_at', 'N/A')}")
                logs_parts.append(f"Backup: {app_results.get('backup_path', 'N/A')}")
                logs_parts.append("")

            if metadata.get("deployment_log"):
                logs_parts.append("=== DEPLOYMENT LOG ===")
                dep_log = metadata["deployment_log"]
                if isinstance(dep_log, list):
                    logs_parts.extend(dep_log)
                else:
                    logs_parts.append(str(dep_log))
                logs_parts.append("")

        # Get test results from sandbox_test_results table
        cur.execute(
            """
            SELECT test_name, status, duration_ms, output, error_message, executed_at
            FROM sandbox_test_results
            WHERE sandbox_id = %s
            ORDER BY executed_at DESC
            LIMIT 10
        """,
            (sandbox_id,),
        )

        test_results = cur.fetchall()

        if test_results:
            logs_parts.append("=== TEST RESULTS ===")
            for test in test_results:
                status_icon = "✅" if test["status"] == "passed" else "❌"
                logs_parts.append(
                    f"{status_icon} {test['test_name']}: {test['status'].upper()} ({test['duration_ms']}ms)"
                )
                if test.get("output"):
                    logs_parts.append(f"   Output: {test['output'][:200]}")
                if test.get("error_message"):
                    logs_parts.append(f"   Error: {test['error_message'][:200]}")
            logs_parts.append("")

        # Add overall test summary if available
        test_summary = sandbox.get("test_results")
        if test_summary and isinstance(test_summary, dict):
            logs_parts.append("=== TEST SUMMARY ===")
            logs_parts.append(f"Overall Status: {test_summary.get('overall_status', 'N/A').upper()}")
            logs_parts.append(f"Passed: {test_summary.get('passed', 0)}")
            logs_parts.append(f"Failed: {test_summary.get('failed', 0)}")
            logs_parts.append(f"Total: {test_summary.get('total', 0)}")

        cur.close()
        conn.close()

        logs = "\n".join(logs_parts) if logs_parts else "No logs available"

        return jsonify({"success": True, "logs": logs}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/agents/available", methods=["GET"])
@login_required
@admin_required
def get_available_agents():
    """Get available team members/agents for fix assignments"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get active agents who can handle fixes
        cur.execute(
            """
            SELECT id, name, role, department, worker_type, status,
                   expertise_areas, api_provider
            FROM agents
            WHERE status = 'active'
            AND (worker_type IN ('employee', 'contract') OR worker_type IS NULL)
            ORDER BY
                CASE WHEN worker_type = 'employee' THEN 0
                     WHEN worker_type = 'contract' THEN 1
                     ELSE 2 END,
                name
            LIMIT 50
        """
        )

        agents = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({"success": True, "agents": [dict(a) for a in agents]}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/request-fix", methods=["POST"])
@login_required
@admin_required
def request_fix():
    """Request a fix from a team member for test errors"""
    try:
        data = request.get_json(silent=True) or {}
        sandbox_id = data.get("sandbox_id")
        proposal_id = data.get("proposal_id")
        agent_id = data.get("agent_id")  # None for auto-assign
        notes = data.get("notes", "")

        if not proposal_id:
            return jsonify({"success": False, "error": "Proposal ID required"}), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get proposal details
        cur.execute(
            "SELECT id, title, category FROM improvement_proposals WHERE id = %s",
            (proposal_id,),
        )
        proposal = cur.fetchone()

        if not proposal:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Proposal not found"}), 404

        # Auto-assign if no agent specified
        if not agent_id:
            # Find best match based on category
            cur.execute(
                """
                SELECT id, name FROM agents
                WHERE status = 'active'
                AND (expertise_areas @> %s OR department ILIKE %s)
                ORDER BY RANDOM()
                LIMIT 1
            """,
                (json.dumps([proposal["category"]]), f"%{proposal['category']}%"),
            )
            assigned = cur.fetchone()

            if assigned:
                agent_id = assigned["id"]
                agent_name = assigned["name"]
            else:
                # Fallback to any available employee
                cur.execute(
                    """
                    SELECT id, name FROM agents
                    WHERE status = 'active' AND worker_type = 'employee'
                    ORDER BY RANDOM()
                    LIMIT 1
                """
                )
                fallback = cur.fetchone()
                if fallback:
                    agent_id = fallback["id"]
                    agent_name = fallback["name"]
                else:
                    cur.close()
                    conn.close()
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "No agents available for assignment",
                            }
                        ),
                        400,
                    )
        else:
            cur.execute("SELECT name FROM agents WHERE id = %s", (agent_id,))
            agent_row = cur.fetchone()
            agent_name = agent_row["name"] if agent_row else "Unknown"

        # Update proposal with fix request
        cur.execute(
            """
            UPDATE improvement_proposals
            SET assigned_agent_id = %s,
                status = 'fix_requested',
                metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
            WHERE id = %s
        """,
            (
                agent_id,
                json.dumps(
                    {
                        "fix_requested_at": datetime.now().isoformat(),
                        "fix_requested_by": current_user.username,
                        "fix_notes": notes,
                        "fix_sandbox_id": sandbox_id,
                    }
                ),
                proposal_id,
            ),
        )

        # Log to chat if available
        try:
            cur.execute(
                """
                INSERT INTO proposal_chat_messages
                (proposal_id, sender_type, sender_name, content, message_type)
                VALUES (%s, 'system', 'System', %s, 'action')
            """,
                (
                    proposal_id,
                    f"Fix requested from {agent_name}. Notes: {notes or 'None'}",
                ),
            )
        except Exception:
            pass  # Chat table might not exist

        conn.commit()
        cur.close()
        conn.close()

        return (
            jsonify(
                {
                    "success": True,
                    "message": f"Fix request assigned to {agent_name}",
                    "assigned_agent_id": agent_id,
                    "assigned_agent_name": agent_name,
                }
            ),
            200,
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/sandboxes/<int:sandbox_id>/clear-results", methods=["POST"])
@login_required
@admin_required
def clear_sandbox_test_results(sandbox_id):
    """Clear old test results, keeping only the most recent run"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get the most recent test run timestamp for this sandbox
        cur.execute(
            """
            SELECT MAX(executed_at) as latest
            FROM sandbox_test_results
            WHERE sandbox_id = %s
        """,
            (sandbox_id,),
        )
        result = cur.fetchone()

        if not result or not result["latest"]:
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "success": True,
                        "message": "No test results to clear",
                        "deleted": 0,
                    }
                ),
                200,
            )

        latest_time = result["latest"]

        # Delete all results except the most recent batch (within 1 minute of latest)
        cur.execute(
            """
            DELETE FROM sandbox_test_results
            WHERE sandbox_id = %s
            AND executed_at < %s - INTERVAL '1 minute'
        """,
            (sandbox_id, latest_time),
        )

        deleted_count = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()

        return (
            jsonify(
                {
                    "success": True,
                    "message": f"Cleared {deleted_count} old test result(s)",
                    "deleted": deleted_count,
                }
            ),
            200,
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/sandboxes/<int:sandbox_id>/access", methods=["GET"])
@login_required
@admin_required
def access_sandbox_environment(sandbox_id):
    """Access the sandbox environment in a new window"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, proposal_id, sandbox_type, schema_name, container_id, status, sandbox_url
            FROM sandbox_instances
            WHERE id = %s
            AND destroyed_at IS NULL
        """,
            (sandbox_id,),
        )

        sandbox = cur.fetchone()
        cur.close()
        conn.close()

        if not sandbox:
            return (
                f"""<html><body style="background: #000; color: #FF0000;">
            <h1>Sandbox #{sandbox_id} not found</h1></body></html>""",
                404,
            )

        sandbox_type = sandbox[2]
        schema_name = sandbox[3]
        status = sandbox[5]

        return render_template(
            "sandbox_access.html",
            sandbox_id=sandbox_id,
            sandbox_type=sandbox_type,
            schema_name=schema_name,
            status=status,
        )

    except Exception as e:
        traceback.print_exc()
        return (
            f"""<html><body style="background: #000; color: #FF0000;">
        <h1>Error: {str(e)}</h1></body></html>""",
            500,
        )


@improvements_bp.route("/sandboxes/<int:sandbox_id>/test-connection", methods=["GET"])
@login_required
@admin_required
def test_sandbox_connection(sandbox_id):
    """Test connection to sandbox and return schema information"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT schema_name
            FROM sandbox_instances
            WHERE id = %s
            AND destroyed_at IS NULL
        """,
            (sandbox_id,),
        )

        sandbox = cur.fetchone()
        if not sandbox:
            return jsonify({"success": False, "error": "Sandbox not found"}), 404

        schema_name = sandbox[0]

        cur.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = %s
        """,
            (schema_name,),
        )
        table_count = cur.fetchone()[0]

        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
            ORDER BY table_name
            LIMIT 10
        """,
            (schema_name,),
        )
        sample_tables = [row[0] for row in cur.fetchall()]

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "schema_name": schema_name,
                "table_count": table_count,
                "sample_tables": sample_tables,
            }
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/sandboxes/<int:sandbox_id>/test", methods=["POST"])
@login_required
@admin_required
def execute_sandbox_tests(sandbox_id):
    """Run test suites in a sandbox"""
    try:
        from ai_bridge.sandbox_test_runner import run_sandbox_tests as execute_tests

        data = request.get_json() or {}
        proposal_id = data.get("proposal_id")
        sandbox_type = data.get("sandbox_type", "schema_separation")
        required_only = data.get("required_only", False)

        if not proposal_id:
            return (
                jsonify({"success": False, "error": "Missing required field: proposal_id"}),
                400,
            )

        result = execute_tests(
            sandbox_id=sandbox_id,
            proposal_id=proposal_id,
            sandbox_type=sandbox_type,
            required_only=required_only,
        )

        # Transform response to match UI expectations
        # Backend returns 'summary' with 'total_tests', UI expects 'test_results' with 'total'
        if result.get("success") and result.get("summary"):
            summary = result["summary"]
            result["test_results"] = {
                "passed": summary.get("passed", 0),
                "failed": summary.get("failed", 0),
                "total": summary.get("total_tests", 0),
                "errors": summary.get("errors", 0),
                "duration": summary.get("duration_seconds", 0),
                "overall_status": summary.get("overall_status", "unknown"),
            }
            # Also update sandbox status in database
            try:
                conn = get_db()
                cur = conn.cursor()
                # Use 'tested' for passed, 'failed' for failed tests (valid per DB constraint)
                test_status = "tested" if result.get("overall_status") == "passed" else "failed"
                cur.execute(
                    """
                    UPDATE sandbox_instances
                    SET status = %s,
                        test_results = %s
                    WHERE id = %s
                """,
                    (test_status, json.dumps(result["test_results"]), sandbox_id),
                )
                conn.commit()
                cur.close()
                conn.close()
            except Exception as db_err:
                print(f"Warning: Could not update sandbox test results: {db_err}")

        return jsonify(result), 200 if result.get("success") else 500

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/sandboxes/<int:sandbox_id>/health", methods=["GET"])
@login_required
@admin_required
def check_sandbox_health(sandbox_id):
    """Run health check on a sandbox"""
    try:
        from ai_bridge.sandbox_test_runner import (
            check_sandbox_health as run_health_check,
        )

        result = run_health_check(sandbox_id)

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/sandboxes/<int:sandbox_id>/results", methods=["GET"])
@login_required
@admin_required
def get_sandbox_test_results(sandbox_id):
    """Get test results for a sandbox"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT
                str.id,
                str.test_name,
                str.status,
                str.duration_ms,
                str.error_message,
                str.output,
                str.executed_at::text,
                sts.test_type,
                sts.required
            FROM sandbox_test_results str
            JOIN sandbox_test_suites sts ON str.test_suite_id = sts.id
            WHERE str.sandbox_id = %s
            ORDER BY str.executed_at DESC
        """,
            (sandbox_id,),
        )

        results = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({"success": True, "results": results}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/test-suites", methods=["GET"])
@login_required
@admin_required
def get_test_suites():
    """Get all available test suites"""
    try:
        from ai_bridge.sandbox_test_runner import SandboxTestRunner

        required_only = request.args.get("required_only", "false").lower() == "true"

        runner = SandboxTestRunner()
        suites = runner.get_test_suites(required_only=required_only)

        return jsonify({"success": True, "test_suites": suites}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/sandbox/queue-status", methods=["GET"])
@login_required
@admin_required
def get_sandbox_queue_status():
    """Get current sandbox queue status"""
    try:
        from sandbox_queue import get_queue_status

        status = get_queue_status()

        for idx, proposal in enumerate(status["queue"]):
            proposal["queue_position"] = idx + 1

        return jsonify({"success": True, **status}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/can-use-sandbox", methods=["GET"])
@login_required
@admin_required
def check_proposal_sandbox_access(proposal_id):
    """Check if a specific proposal can use the sandbox"""
    try:
        from sandbox_queue import can_proposal_use_sandbox

        result = can_proposal_use_sandbox(proposal_id)

        return jsonify({"success": True, **result}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/sandbox/release", methods=["POST"])
@login_required
@admin_required
def release_sandbox():
    """Release the sandbox after proposal deployment"""
    try:
        from sandbox_queue import SandboxQueue

        data = request.get_json() or {}
        proposal_id = data.get("proposal_id")

        if not proposal_id:
            return (
                jsonify({"success": False, "error": "Missing required field: proposal_id"}),
                400,
            )

        queue = SandboxQueue()
        result = queue.release_sandbox(proposal_id)

        return jsonify({"success": True, **result}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# DEPLOYMENT ROUTES
# ============================================================================


@improvements_bp.route("/proposals/<int:proposal_id>/deploy", methods=["POST"])
@login_required
@admin_required
def deploy_proposal(proposal_id):
    """Deploy an improvement proposal with full safety protocol"""
    try:

        data = request.get_json() or {}
        user_id = session.get("user_id")

        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from safe_deployment_protocol import SafeDeploymentProtocol

        protocol = SafeDeploymentProtocol()

        result = protocol.deploy_proposal(
            proposal_id=proposal_id,
            deployed_by_user_id=user_id,
            force=data.get("force", False),
            skip_backup=data.get("skip_backup", False),
            skip_health_check=data.get("skip_health_check", False),
        )

        if result["success"]:
            return jsonify(result), 200
        elif result.get("requires_approval"):
            return jsonify(result), 403
        else:
            return jsonify(result), 400

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/deploy-to-production", methods=["POST"])
@login_required
@admin_required
def deploy_proposal_to_production(proposal_id):
    """Deploy tested proposal to production - applies actual code changes"""
    try:

        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT
                ip.*,
                si.id as sandbox_id,
                si.schema_name,
                si.test_results
            FROM improvement_proposals ip
            LEFT JOIN sandbox_instances si ON si.proposal_id = ip.id
            WHERE ip.id = %s
            AND si.destroyed_at IS NULL
            ORDER BY si.created_at DESC
            LIMIT 1
        """,
            (proposal_id,),
        )

        proposal = cur.fetchone()

        if not proposal:
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": "Proposal or sandbox not found"}),
                404,
            )

        # Check if tests have passed - look at proposal's test_status, not sandbox
        test_status = proposal.get("test_status")
        if test_status != "passed":
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f'Cannot deploy: tests have not passed (status: {test_status or "not run"})',
                    }
                ),
                400,
            )

        cur.close()
        conn.close()

        from code_deployer import CodeDeployer

        deployer = CodeDeployer()
        result = deployer.deploy_proposal(
            proposal_id=proposal_id,
            deployed_by=session.get("user_id", 2),  # Default to admin (id=2)
        )

        if not result["success"]:
            return jsonify(result), 400

        response = {
            "success": True,
            "message": result["message"],
            "files_modified": result["files_modified"],
            "modified_files": result.get("modified_files", []),
            "deployment_log": result.get("deployment_log", []),
            "restart_required": result.get("restart_required", False),
        }

        return jsonify(response), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/restart-platform", methods=["POST"])
@login_required
@admin_required
def restart_platform():
    """Restart the platform container with EXTERNAL failsafe auto-rollback"""
    try:
        import subprocess
        import threading
        import os

        # Check if deployment info exists for failsafe
        deployment_info_file = "/backups/last_deployment.json"
        has_failsafe = os.path.exists(deployment_info_file)

        # Launch EXTERNAL watchdog in a separate container BEFORE restarting
        # This watchdog will monitor health and rollback if needed
        if has_failsafe:
            try:
                # Run watchdog in a detached alpine container with access to docker and files
                watchdog_cmd = [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    "archie_watchdog",
                    "-v",
                    "/var/run/docker.sock:/var/run/docker.sock",
                    "-v",
                    "/mnt/archie_brain:/mnt/archie_brain",
                    "--network",
                    "host",
                    "docker:cli",
                    "sh",
                    "-c",
                    "/mnt/archie_brain/scripts/deployment_watchdog.sh",
                ]
                result = subprocess.run(watchdog_cmd, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    print(f"[FAILSAFE] External watchdog started: {result.stdout.strip()[:12]}")
                else:
                    print(f"[FAILSAFE] Could not start watchdog: {result.stderr}")
            except Exception as e:
                print(f"[FAILSAFE] Watchdog start error: {e}")

        def trigger_restart():
            """Just trigger the restart - external watchdog handles monitoring"""
            import time

            time.sleep(2)  # Allow response to be sent first

            try:
                print("[RESTART] Initiating container restart...")
                print("[RESTART] External watchdog will monitor and rollback if needed")
                result = subprocess.run(
                    ["docker", "restart", "archie_platform"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )

                if result.returncode != 0:
                    print(f"[RESTART] Restart command failed: {result.stderr}")
                else:
                    print("[RESTART] Container restart triggered successfully")

            except Exception as e:
                print(f"[RESTART] Error: {e}")

        # Start restart in background thread (external watchdog handles monitoring)
        thread = threading.Thread(target=trigger_restart)
        thread.daemon = True
        thread.start()

        return (
            jsonify(
                {
                    "success": True,
                    "message": "Platform restart initiated with failsafe monitoring.",
                    "has_failsafe": has_failsafe,
                    "note": "Container health will be monitored. If unhealthy, code will auto-rollback to previous version.",
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/deployments/<int:deployment_id>", methods=["GET"])
@login_required
@admin_required
def get_deployment_status(deployment_id):
    """Get status and details of a deployment"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from safe_deployment_protocol import SafeDeploymentProtocol

        protocol = SafeDeploymentProtocol()
        result = protocol.get_deployment_status(deployment_id)

        if "error" in result:
            return jsonify(result), 404

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/deployments", methods=["GET"])
@login_required
@admin_required
def list_deployments():
    """List deployment history with filters"""
    try:
        proposal_id = request.args.get("proposal_id", type=int)
        status = request.args.get("status")
        limit = request.args.get("limit", 20, type=int)

        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from safe_deployment_protocol import SafeDeploymentProtocol

        protocol = SafeDeploymentProtocol()
        result = protocol.list_deployments(proposal_id=proposal_id, status=status, limit=limit)

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/deployments/recent", methods=["GET"])
@login_required
@admin_required
def get_recent_deployments():
    """Get recent deployments"""
    try:
        limit = request.args.get("limit", 10, type=int)

        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT
                id,
                proposal_id,
                deployed_by,
                backup_name,
                sandbox_id,
                deployment_type,
                status,
                deployed_at::text,
                rolled_back_at::text,
                rollback_reason,
                health_check_passed,
                deployment_log
            FROM improvement_deployments
            ORDER BY deployed_at DESC
            LIMIT %s
        """,
            (limit,),
        )

        deployments = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({"success": True, "deployments": deployments}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/deployments/<int:deployment_id>/logs", methods=["GET"])
@login_required
@admin_required
def get_deployment_logs(deployment_id):
    """Get logs from a deployment"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT deployment_log
            FROM improvement_deployments
            WHERE id = %s
        """,
            (deployment_id,),
        )

        deployment = cur.fetchone()
        cur.close()
        conn.close()

        if not deployment:
            return jsonify({"success": False, "error": "Deployment not found"}), 404

        return (
            jsonify(
                {
                    "success": True,
                    "logs": deployment.get("deployment_log", "No logs available"),
                }
            ),
            200,
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/deployments/<int:deployment_id>/rollback", methods=["POST"])
@login_required
@admin_required
def rollback_deployment(deployment_id):
    """Rollback a deployment to pre-deployment state"""
    try:
        data = request.get_json() or {}
        reason = data.get("reason", "Manual rollback requested")

        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from auto_rollback import AutoRollbackManager

        manager = AutoRollbackManager()
        result = manager.rollback_deployment(deployment_id=deployment_id, reason=reason, auto_triggered=False)

        if result["success"]:
            return jsonify(result), 200
        else:
            return jsonify(result), 400

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/deployments/<int:deployment_id>/can-rollback", methods=["GET"])
@login_required
@admin_required
def check_can_rollback(deployment_id):
    """Check if a deployment can be rolled back"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from auto_rollback import AutoRollbackManager

        manager = AutoRollbackManager()
        result = manager.can_rollback(deployment_id)

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/deployments/rollback-history", methods=["GET"])
@login_required
@admin_required
def get_rollback_history():
    """Get history of rollbacks"""
    try:
        proposal_id = request.args.get("proposal_id", type=int)
        limit = request.args.get("limit", 20, type=int)

        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from auto_rollback import AutoRollbackManager

        manager = AutoRollbackManager()
        result = manager.get_rollback_history(proposal_id=proposal_id, limit=limit)

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/can-deploy", methods=["GET"])
@login_required
@admin_required
def check_can_deploy(proposal_id):
    """Check if a proposal can be auto-deployed or requires manual approval"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from deployment_decision import DeploymentDecisionEngine

        engine = DeploymentDecisionEngine()
        result = engine.can_auto_deploy(proposal_id=proposal_id)

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/deployments/<int:deployment_id>/health", methods=["GET"])
@login_required
@admin_required
def get_deployment_health(deployment_id):
    """Get current health status of a deployment"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from deployment_monitor import DeploymentMonitor

        monitor = DeploymentMonitor()
        result = monitor.get_deployment_health(deployment_id)

        if "error" in result:
            return jsonify(result), 404

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/deployments/<int:deployment_id>/monitor", methods=["POST"])
@login_required
@admin_required
def monitor_deployment_once(deployment_id):
    """Run a single monitoring check on a deployment"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from deployment_monitor import DeploymentMonitor

        monitor = DeploymentMonitor()
        result = monitor.monitor_deployment(deployment_id)

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/deployments/active-monitors", methods=["GET"])
@login_required
@admin_required
def get_active_deployment_monitors():
    """Get all deployments currently being monitored"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from deployment_monitor import DeploymentMonitor

        monitor = DeploymentMonitor()
        result = monitor.get_active_monitors()

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/restart-archie", methods=["POST"])
@login_required
@admin_required
def restart_archie_services():
    """Restart A.R.C.H.I.E. services after code deployment"""
    try:
        from code_deployer import restart_archie

        result = restart_archie()
        return jsonify(result), 200 if result["success"] else 500

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# ESCALATION ROUTES
# ============================================================================


@improvements_bp.route("/escalations", methods=["GET"])
@login_required
@admin_required
def get_escalation_history():
    """Get escalation history"""
    try:
        proposal_id = request.args.get("proposal_id", type=int)
        limit = request.args.get("limit", 20, type=int)

        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from escalation_handler import EscalationHandler

        handler = EscalationHandler()
        result = handler.get_escalation_history(proposal_id=proposal_id, limit=limit)

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# DISCUSSION ROUTES
# ============================================================================


@improvements_bp.route("/discussions/start", methods=["POST"])
@login_required
@admin_required
def start_discussion():
    """Start a new multi-agent discussion for a proposal"""
    try:
        from ai_bridge.team_discussion_engine import TeamDiscussionEngine

        data = request.get_json()
        proposal_id = data.get("proposal_id")
        topic = data.get("topic")
        description = data.get("description")
        agent_ids = data.get("agent_ids", [])

        if not proposal_id or not topic:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Missing required fields: proposal_id, topic",
                    }
                ),
                400,
            )

        engine = TeamDiscussionEngine()
        discussion_id = engine.start_discussion(proposal_id, topic, description)

        if not discussion_id:
            return (
                jsonify({"success": False, "error": "Failed to create discussion"}),
                500,
            )

        if agent_ids:
            engine.assign_agents_to_discussion(discussion_id, agent_ids)

        return (
            jsonify(
                {
                    "success": True,
                    "discussion_id": discussion_id,
                    "message": f"Discussion #{discussion_id} started with {len(agent_ids)} agents",
                }
            ),
            200,
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/discussions/<int:discussion_id>/contribute", methods=["POST"])
@login_required
@admin_required
def add_contribution(discussion_id):
    """Add an agent's contribution to a discussion"""
    try:
        from ai_bridge.team_discussion_engine import TeamDiscussionEngine

        data = request.get_json()
        agent_id = data.get("agent_id")
        message = data.get("message")
        message_type = data.get("message_type", "analysis")
        confidence_score = data.get("confidence_score", 0.8)
        supporting_data = data.get("supporting_data")

        if not agent_id or not message:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Missing required fields: agent_id, message",
                    }
                ),
                400,
            )

        engine = TeamDiscussionEngine()
        success = engine.agent_contribute(
            discussion_id,
            agent_id,
            message,
            message_type,
            confidence_score,
            supporting_data,
        )

        if not success:
            return (
                jsonify({"success": False, "error": "Failed to add contribution"}),
                500,
            )

        return (
            jsonify({"success": True, "message": "Contribution added successfully"}),
            200,
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/discussions/<int:discussion_id>/evaluate", methods=["POST"])
@login_required
@admin_required
def create_evaluation(discussion_id):
    """Create a formal evaluation from an agent"""
    try:
        from ai_bridge.team_discussion_engine import TeamDiscussionEngine

        data = request.get_json()
        proposal_id = data.get("proposal_id")
        agent_id = data.get("agent_id")

        if not proposal_id or not agent_id:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Missing required fields: proposal_id, agent_id",
                    }
                ),
                400,
            )

        engine = TeamDiscussionEngine()
        success = engine.create_agent_evaluation(
            proposal_id=proposal_id,
            discussion_id=discussion_id,
            agent_id=agent_id,
            recommendation=data.get("recommendation", "needs_review"),
            confidence_level=data.get("confidence_level", 0.8),
            risk_assessment=data.get("risk_assessment", "medium"),
            estimated_effort=data.get("estimated_effort", "2-4h"),
            technical_notes=data.get("technical_notes", ""),
            manager_summary=data.get("manager_summary", ""),
            concerns=data.get("concerns", []),
            benefits=data.get("benefits", []),
            role=data.get("role", "reviewer"),
        )

        if not success:
            return (
                jsonify({"success": False, "error": "Failed to create evaluation"}),
                500,
            )

        return (
            jsonify({"success": True, "message": "Evaluation created successfully"}),
            200,
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/discussions/<int:discussion_id>/consensus", methods=["POST"])
@login_required
@admin_required
def create_consensus(discussion_id):
    """Create team consensus for a discussion"""
    try:
        from ai_bridge.team_discussion_engine import TeamDiscussionEngine

        data = request.get_json()
        proposal_id = data.get("proposal_id")

        if not proposal_id:
            return (
                jsonify({"success": False, "error": "Missing required field: proposal_id"}),
                400,
            )

        engine = TeamDiscussionEngine()
        consensus_id = engine.create_team_consensus(
            proposal_id=proposal_id,
            discussion_id=discussion_id,
            implementation_plan=data.get("implementation_plan"),
            priority_recommendation=data.get("priority_recommendation"),
        )

        if not consensus_id:
            return (
                jsonify({"success": False, "error": "Failed to create consensus"}),
                500,
            )

        _, stats = engine.calculate_consensus(discussion_id)
        engine.close_discussion(discussion_id, consensus_reached=True)

        return (
            jsonify(
                {
                    "success": True,
                    "consensus_id": consensus_id,
                    "consensus_score": stats.get("consensus_score", 0),
                    "final_recommendation": stats.get("final_recommendation", "needs_review"),
                    "message": "Team consensus created and discussion closed",
                }
            ),
            200,
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/discussions/<int:discussion_id>/summary", methods=["GET"])
@login_required
@admin_required
def get_discussion_summary(discussion_id):
    """Get complete summary of a discussion"""
    try:
        from ai_bridge.team_discussion_engine import TeamDiscussionEngine

        engine = TeamDiscussionEngine()
        summary = engine.get_discussion_summary(discussion_id)

        if not summary:
            return jsonify({"success": False, "error": "Discussion not found"}), 404

        return jsonify({"success": True, "summary": summary}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/discussions", methods=["GET"])
@login_required
@admin_required
def get_proposal_discussions(proposal_id):
    """Get all discussions for a proposal"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT
                d.id,
                d.topic,
                d.description,
                d.status,
                d.started_at::text,
                d.ended_at::text,
                d.consensus_reached,
                d.consensus_score,
                COALESCE(a.first_name || ' ' || a.last_name, a.name) as facilitator_name,
                (
                    SELECT COUNT(*)
                    FROM agent_discussion_messages
                    WHERE discussion_id = d.id
                ) as message_count,
                (
                    SELECT COUNT(*)
                    FROM proposal_evaluations
                    WHERE discussion_id = d.id
                ) as evaluation_count
            FROM agent_discussions d
            LEFT JOIN agents a ON d.facilitator_id = a.id
            WHERE d.proposal_id = %s
            ORDER BY d.started_at DESC
        """,
            (proposal_id,),
        )

        discussions = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({"success": True, "discussions": discussions}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# REPORT ROUTES
# ============================================================================


@improvements_bp.route("/discussions/<int:discussion_id>/reports/executive", methods=["GET"])
@login_required
@admin_required
def get_executive_report(discussion_id):
    """Generate executive summary report for management"""
    try:
        from ai_bridge.collaborative_report_generator import (
            CollaborativeReportGenerator,
        )

        generator = CollaborativeReportGenerator()
        report = generator.generate_executive_summary(discussion_id)

        if not report:
            return (
                jsonify({"success": False, "error": "Failed to generate executive report"}),
                500,
            )

        return jsonify({"success": True, "report": report}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/discussions/<int:discussion_id>/reports/technical", methods=["GET"])
@login_required
@admin_required
def get_technical_report(discussion_id):
    """Generate technical analysis report for developers"""
    try:
        from ai_bridge.collaborative_report_generator import (
            CollaborativeReportGenerator,
        )

        generator = CollaborativeReportGenerator()
        report = generator.generate_technical_report(discussion_id)

        if not report:
            return (
                jsonify({"success": False, "error": "Failed to generate technical report"}),
                500,
            )

        return jsonify({"success": True, "report": report}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/discussions/<int:discussion_id>/reports/visual", methods=["GET"])
@login_required
@admin_required
def get_visual_report(discussion_id):
    """Generate visualization data for consensus display"""
    try:
        from ai_bridge.collaborative_report_generator import (
            CollaborativeReportGenerator,
        )

        generator = CollaborativeReportGenerator()
        visual_data = generator.generate_consensus_visual(discussion_id)

        if not visual_data:
            return (
                jsonify({"success": False, "error": "Failed to generate visual data"}),
                500,
            )

        return jsonify({"success": True, "visual_data": visual_data}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/discussions/<int:discussion_id>/reports/notification", methods=["GET"])
@login_required
@admin_required
def get_notification_report(discussion_id):
    """Generate compact notification data"""
    try:
        from ai_bridge.collaborative_report_generator import (
            CollaborativeReportGenerator,
        )

        generator = CollaborativeReportGenerator()
        notification = generator.generate_notification_report(discussion_id)

        if not notification:
            return (
                jsonify({"success": False, "error": "Failed to generate notification data"}),
                500,
            )

        return jsonify({"success": True, "notification": notification}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/discussions/<int:discussion_id>/reports/full", methods=["GET"])
@login_required
@admin_required
def get_full_report(discussion_id):
    """Generate complete report with all sections"""
    try:
        from ai_bridge.collaborative_report_generator import (
            CollaborativeReportGenerator,
        )

        include_executive = request.args.get("executive", "true").lower() == "true"
        include_technical = request.args.get("technical", "true").lower() == "true"
        include_visual = request.args.get("visual", "true").lower() == "true"
        include_notification = request.args.get("notification", "true").lower() == "true"

        generator = CollaborativeReportGenerator()
        report = generator.generate_full_report(
            discussion_id,
            include_executive=include_executive,
            include_technical=include_technical,
            include_visual=include_visual,
            include_notification=include_notification,
        )

        if not report:
            return (
                jsonify({"success": False, "error": "Failed to generate full report"}),
                500,
            )

        return jsonify({"success": True, "report": report}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# TEAM EVALUATION ORCHESTRATION
# ============================================================================


@improvements_bp.route("/proposals/<int:proposal_id>/evaluate", methods=["POST"])
@login_required
@admin_required
def auto_evaluate_proposal(proposal_id):
    """Automatically orchestrate team evaluation for a proposal"""
    try:
        from ai_bridge.team_consensus_orchestrator import TeamConsensusOrchestrator

        data = request.get_json() or {}
        generate_report = data.get("generate_report", True)
        notify_admin = data.get("notify_admin", True)

        orchestrator = TeamConsensusOrchestrator()
        discussion_id = orchestrator.orchestrate_team_evaluation(
            proposal_id=proposal_id,
            auto_generate_report=generate_report,
            auto_notify_admin=notify_admin,
        )

        if not discussion_id:
            return (
                jsonify({"success": False, "error": "Failed to orchestrate team evaluation"}),
                500,
            )

        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT
                tc.id as consensus_id,
                tc.final_recommendation,
                tc.consensus_score
            FROM team_consensus tc
            WHERE tc.discussion_id = %s
        """,
            (discussion_id,),
        )

        consensus = cur.fetchone()
        cur.close()
        conn.close()

        return (
            jsonify(
                {
                    "success": True,
                    "discussion_id": discussion_id,
                    "consensus_id": consensus["consensus_id"] if consensus else None,
                    "recommendation": (consensus["final_recommendation"] if consensus else "pending"),
                    "consensus_score": (
                        float(consensus["consensus_score"]) if consensus and consensus["consensus_score"] else 0.0
                    ),
                    "message": "Team evaluation complete",
                }
            ),
            200,
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# LEARNING ROUTES
# ============================================================================


@improvements_bp.route("/proposals/<int:proposal_id>/learn", methods=["POST"])
@login_required
@admin_required
def learn_from_proposal(proposal_id):
    """Trigger learning from a completed proposal"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from improvement_learning import ImprovementLearning

        learning = ImprovementLearning()
        result = learning.learn_from_completion(proposal_id)

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/learning/insights", methods=["GET"])
@login_required
@admin_required
def get_learning_insights():
    """Get recent learning insights"""
    try:
        limit = request.args.get("limit", 20, type=int)

        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from improvement_learning import ImprovementLearning

        learning = ImprovementLearning()
        result = learning.get_learning_insights(limit=limit)

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/learning/stats", methods=["GET"])
@login_required
@admin_required
def get_learning_stats():
    """Get learning statistics"""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from improvement_learning import ImprovementLearning

        learning = ImprovementLearning()
        result = learning.get_learning_stats()

        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# COMPREHENSIVE STATS (from admin/routes.py line 8229)
# ============================================================================


@improvements_bp.route("/stats/comprehensive", methods=["GET"])
@login_required
@admin_required
def get_improvements_stats_comprehensive():
    """Get comprehensive improvement proposals statistics"""
    print("get_improvements_stats_comprehensive called")

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Overall stats by status
        cur.execute(
            """
            SELECT
                status,
                COUNT(*) as count,
                COUNT(*) FILTER (WHERE priority = 'high') as high_priority,
                COUNT(*) FILTER (WHERE priority = 'medium') as medium_priority,
                COUNT(*) FILTER (WHERE priority = 'low') as low_priority
            FROM improvement_proposals
            GROUP BY status
        """
        )
        status_breakdown = cur.fetchall()

        # Category breakdown
        cur.execute(
            """
            SELECT
                category,
                COUNT(*) as count,
                COUNT(*) FILTER (WHERE status IN ('implemented', 'completed')) as implemented,
                COUNT(*) FILTER (WHERE status = 'failed') as failed
            FROM improvement_proposals
            WHERE category IS NOT NULL
            GROUP BY category
            ORDER BY count DESC
        """
        )
        category_breakdown = cur.fetchall()

        # Failed improvements details
        cur.execute(
            """
            SELECT id, title, description, category, priority,
                   proposed_at
            FROM improvement_proposals
            WHERE status = 'failed'
            ORDER BY priority DESC, proposed_at DESC
        """
        )
        failed_improvements = cur.fetchall()

        # Implementation timeline (last 90 days)
        cur.execute(
            """
            SELECT
                DATE(implemented_at) as date,
                COUNT(*) as count,
                array_agg(title) as titles
            FROM improvement_proposals
            WHERE status IN ('implemented', 'completed')
            AND implemented_at >= NOW() - INTERVAL '90 days'
            GROUP BY DATE(implemented_at)
            ORDER BY date DESC
        """
        )
        implementation_timeline = cur.fetchall()

        # Success metrics
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status IN ('implemented', 'completed')) as implemented,
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                COUNT(*) FILTER (WHERE status IN ('proposed', 'pending_approval', 'pending')) as proposed,
                COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
                ROUND(
                    (COUNT(*) FILTER (WHERE status IN ('implemented', 'completed'))::numeric /
                     NULLIF(COUNT(*) FILTER (WHERE status IN ('implemented', 'completed', 'failed'))::numeric, 0)) * 100,
                    1
                ) as success_rate
            FROM improvement_proposals
        """
        )
        overall_metrics = cur.fetchone()

        # Recent activity (last 10)
        cur.execute(
            """
            SELECT id, title, status, category, priority,
                   proposed_at, implemented_at, approved_at
            FROM improvement_proposals
            ORDER BY
                CASE
                    WHEN status = 'proposed' THEN proposed_at
                    WHEN status IN ('implemented', 'completed') THEN implemented_at
                    ELSE proposed_at
                END DESC
            LIMIT 10
        """
        )
        recent_activity = cur.fetchall()

        cur.close()
        conn.close()

        # Convert dates to ISO format
        for item in failed_improvements:
            if item["proposed_at"]:
                item["proposed_at"] = item["proposed_at"].isoformat()

        for item in implementation_timeline:
            if item["date"]:
                item["date"] = item["date"].isoformat()

        for item in recent_activity:
            if item["proposed_at"]:
                item["proposed_at"] = item["proposed_at"].isoformat()
            if item["implemented_at"]:
                item["implemented_at"] = item["implemented_at"].isoformat()
            if item["approved_at"]:
                item["approved_at"] = item["approved_at"].isoformat()

        return jsonify(
            {
                "success": True,
                "stats": {
                    "overall": dict(overall_metrics),
                    "status_breakdown": [dict(s) for s in status_breakdown],
                    "category_breakdown": [dict(c) for c in category_breakdown],
                    "failed_improvements": [dict(f) for f in failed_improvements],
                    "implementation_timeline": [dict(t) for t in implementation_timeline],
                    "recent_activity": [dict(r) for r in recent_activity],
                },
            }
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# FILE MANAGEMENT (migrated from admin)
# ============================================================================


def check_path_allowed(path):
    """Security check for file operations"""
    abs_path = os.path.abspath(path)
    allowed = os.path.abspath(ALLOWED_BASE)
    return abs_path.startswith(allowed)


@improvements_bp.route("/files/read", methods=["POST"])
@login_required
@admin_required
def read_file():
    """Read file contents"""
    try:
        data = request.json
        path = data.get("path")

        if not path or not check_path_allowed(path):
            return jsonify({"error": "Access denied"}), 403

        if not os.path.exists(path):
            return jsonify({"error": "Not found"}), 404

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        return jsonify({"success": True, "content": content, "path": path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@improvements_bp.route("/files/write", methods=["POST"])
@login_required
@admin_required
def write_file():
    """Write file contents with backup"""
    try:
        data = request.json
        path = data.get("path")
        content = data.get("content")

        if not path or not check_path_allowed(path):
            return jsonify({"error": "Access denied"}), 403

        # Create backup if file exists
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                backup = f.read()
            with open(path + ".backup", "w", encoding="utf-8") as f:
                f.write(backup)

        # Write new content
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# API SETTINGS (migrated from admin)
# ============================================================================


@improvements_bp.route("/api-settings/agent-mapping", methods=["GET"])
@login_required
@admin_required
def api_settings_agent_mapping():
    """Get agent-to-API mapping to show which agents need which APIs"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get all agents with their models
        cur.execute(
            """
            SELECT id, name, first_name, last_name, department, worker_type, model, status
            FROM agents
            WHERE status = 'active'
            ORDER BY worker_type, department, name
        """
        )
        agents = cur.fetchall()

        # Get all API provider settings
        cur.execute(
            """
            SELECT provider, enabled, api_key
            FROM archie_api_settings
        """
        )
        providers = cur.fetchall()

        cur.close()
        conn.close()

        # Mask API keys
        for provider in providers:
            if provider["api_key"]:
                provider["api_key"] = "****" if len(provider["api_key"]) > 0 else None

        return jsonify(
            {
                "success": True,
                "agents": [dict(a) for a in agents],
                "providers": [dict(p) for p in providers],
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/api-settings/providers", methods=["GET"])
@login_required
@admin_required
def api_settings_providers():
    """Get all API provider settings"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT provider, enabled, is_default, api_key, endpoint_url,
                   model_name, priority
            FROM archie_api_settings
            ORDER BY priority DESC
        """
        )

        providers = cur.fetchall()
        cur.close()
        conn.close()

        # Mask API keys (show only last 4 chars)
        for provider in providers:
            if provider["api_key"]:
                key = provider["api_key"]
                if len(key) > 8:
                    provider["api_key"] = "****" + key[-4:]

        return jsonify({"success": True, "providers": [dict(p) for p in providers]})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/api-settings/toggle", methods=["POST"])
@login_required
@admin_required
def api_settings_toggle():
    """Toggle API provider enabled/disabled"""
    try:
        data = request.json
        provider = data.get("provider")
        enabled = data.get("enabled", False)

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE archie_api_settings
            SET enabled = %s, updated_at = NOW()
            WHERE provider = %s
        """,
            (enabled, provider),
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/api-settings/set-default", methods=["POST"])
@login_required
@admin_required
def api_settings_set_default():
    """Set default API provider"""
    try:
        data = request.json
        provider = data.get("provider")

        conn = get_db()
        cur = conn.cursor()

        # Clear all defaults
        cur.execute("UPDATE archie_api_settings SET is_default = FALSE")

        # Set new default
        cur.execute(
            """
            UPDATE archie_api_settings
            SET is_default = TRUE, updated_at = NOW()
            WHERE provider = %s
        """,
            (provider,),
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/api-settings/save", methods=["POST"])
@login_required
@admin_required
def api_settings_save():
    """Save API keys and settings"""
    try:
        data = request.json

        conn = get_db()
        cur = conn.cursor()

        # Save Claude API key
        if "claude_api_key" in data and data["claude_api_key"]:
            cur.execute(
                """
                UPDATE archie_api_settings
                SET api_key = %s, updated_at = NOW()
                WHERE provider = 'claude'
            """,
                (data["claude_api_key"],),
            )

        # Save OpenAI API key
        if "openai_api_key" in data and data["openai_api_key"]:
            cur.execute(
                """
                UPDATE archie_api_settings
                SET api_key = %s, updated_at = NOW()
                WHERE provider = 'openai'
            """,
                (data["openai_api_key"],),
            )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/api-settings/test/<provider>", methods=["GET"])
@login_required
@admin_required
def api_settings_test(provider):
    """Test API provider connection"""
    try:
        from ai_bridge.archie_bridge import test_model

        # Map provider to model ID
        provider_to_model = {
            "ollama": "qwen-coder",
            "claude": "claude-sonnet",
            "openai": "gpt-4",
        }

        model_id = provider_to_model.get(provider)
        if not model_id:
            return jsonify({"success": False, "error": "Unknown provider"})

        # Test the model
        result = test_model(model_id)

        if result.get("success"):
            return jsonify(
                {
                    "success": True,
                    "message": result.get("response", "Connection successful!"),
                }
            )
        else:
            return jsonify({"success": False, "error": result.get("error", "Connection failed")})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# TEST RETRY LOOP + CONTRACTOR ESCALATION ROUTES
# ============================================================================


@improvements_bp.route("/proposals/<int:proposal_id>/retry", methods=["POST"])
@login_required
@admin_required
def trigger_proposal_retry(proposal_id):
    """Manually trigger a test retry for a proposal"""
    try:
        from ai_bridge.test_retry_handler import get_retry_handler

        handler = get_retry_handler()

        # Get current test results to pass as context
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT test_results_summary, test_failure_context
            FROM improvement_proposals
            WHERE id = %s
        """,
            (proposal_id,),
        )

        proposal = cur.fetchone()
        cur.close()
        conn.close()

        if not proposal:
            return jsonify({"success": False, "error": "Proposal not found"}), 404

        # Trigger retry
        test_results = proposal.get("test_results_summary") or {}
        result = handler.handle_test_failure(proposal_id, test_results)

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/retry-status", methods=["GET"])
@login_required
@admin_required
def get_proposal_retry_status(proposal_id):
    """Get retry status and escalation info for a proposal"""
    try:
        from ai_bridge.test_retry_handler import get_retry_status

        status = get_retry_status(proposal_id)
        return jsonify(status)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/reset-retries", methods=["POST"])
@login_required
@admin_required
def reset_proposal_retries(proposal_id):
    """Reset retry count for a proposal (admin action)"""
    try:
        from ai_bridge.test_retry_handler import reset_proposal_retries

        result = reset_proposal_retries(proposal_id)
        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/escalated", methods=["GET"])
@login_required
@admin_required
def get_escalated_proposals():
    """Get all proposals that have been escalated to contractors"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT
                ip.id, ip.title, ip.category, ip.status,
                ip.escalation_status, ip.escalated_at,
                ip.test_retry_count, ip.contractor_agent_id,
                a.name as contractor_name,
                a.api_provider as contractor_provider
            FROM improvement_proposals ip
            LEFT JOIN agents a ON ip.contractor_agent_id = a.id
            WHERE ip.escalation_status IS NOT NULL
            AND ip.escalation_status != 'none'
            ORDER BY ip.escalated_at DESC
        """
        )

        proposals = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "proposals": [dict(p) for p in proposals],
                "count": len(proposals),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/contractor-chat", methods=["POST"])
@login_required
@admin_required
def send_contractor_chat(proposal_id):
    """Send a message to the contractor and get response"""
    try:
        from ai_bridge.chat_handler import get_chat_handler

        data = request.get_json() or {}
        message = data.get("message")

        if not message:
            return jsonify({"success": False, "error": "Message required"}), 400

        handler = get_chat_handler()
        result = handler.send_to_contractor(
            proposal_id=proposal_id,
            message=message,
            user_id=current_user.id,
            user_name=current_user.username or "Human",
        )

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/chat-history", methods=["GET"])
@login_required
@admin_required
def get_proposal_chat_history(proposal_id):
    """Get chat history for a proposal"""
    try:
        from ai_bridge.chat_handler import get_chat_handler

        handler = get_chat_handler()
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)

        result = handler.get_chat_history(proposal_id=proposal_id, limit=limit, offset=offset)

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/apply-contractor-fix", methods=["POST"])
@login_required
@admin_required
def apply_contractor_fix(proposal_id):
    """Apply the contractor's proposed fix to the proposal"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get contractor proposal
        cur.execute(
            """
            SELECT contractor_proposal, code_changes
            FROM improvement_proposals
            WHERE id = %s
        """,
            (proposal_id,),
        )

        proposal = cur.fetchone()
        if not proposal:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Proposal not found"}), 404

        contractor_proposal = proposal.get("contractor_proposal")
        if not contractor_proposal:
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": "No contractor proposal to apply"}),
                400,
            )

        # Extract code from contractor proposal
        if isinstance(contractor_proposal, str):
            contractor_proposal = json.loads(contractor_proposal)

        new_code = contractor_proposal.get("code_suggestion") or contractor_proposal.get("proposal", "")

        # Update proposal with contractor's code
        cur.execute(
            """
            UPDATE improvement_proposals
            SET
                code_changes = %s,
                escalation_status = 'resolved',
                status = 'code_generating',
                test_retry_count = 0
            WHERE id = %s
        """,
            (new_code, proposal_id),
        )

        # Log to chat
        from ai_bridge.chat_handler import get_chat_handler

        chat = get_chat_handler()
        chat.add_system_message(proposal_id, "Contractor fix applied. Ready for re-testing.", "action")

        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "message": "Contractor fix applied. Ready for re-testing.",
            }
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/escalate-to-human-only", methods=["POST"])
@login_required
@admin_required
def escalate_to_human_only(proposal_id):
    """Mark a proposal as requiring human-only investigation"""
    try:
        data = request.get_json() or {}
        reason = data.get("reason", "Too complex for automated resolution")

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE improvement_proposals
            SET
                escalation_status = 'human_only',
                status = 'escalated'
            WHERE id = %s
        """,
            (proposal_id,),
        )

        conn.commit()
        cur.close()
        conn.close()

        # Log to chat
        from ai_bridge.chat_handler import get_chat_handler

        chat = get_chat_handler()
        chat.add_system_message(
            proposal_id,
            f"Escalated to human-only investigation. Reason: {reason}",
            "action",
        )

        return jsonify({"success": True, "message": "Proposal marked for human-only investigation"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/proposals/<int:proposal_id>/try-another-contractor", methods=["POST"])
@login_required
@admin_required
def try_another_contractor(proposal_id):
    """Switch to a different contractor for consultation"""
    try:
        data = request.get_json() or {}
        preferred_provider = data.get("provider")  # Optional: claude, openai, etc.

        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get current contractor
        cur.execute(
            """
            SELECT contractor_agent_id FROM improvement_proposals WHERE id = %s
        """,
            (proposal_id,),
        )
        proposal = cur.fetchone()

        if not proposal:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Proposal not found"}), 404

        current_contractor = proposal.get("contractor_agent_id")

        # Find another contractor
        query = """
            SELECT id, name, api_provider, model
            FROM agents
            WHERE worker_type = 'contract'
            AND status = 'active'
            AND api_enabled = TRUE
        """
        params = []

        if current_contractor:
            query += " AND id != %s"
            params.append(current_contractor)

        if preferred_provider:
            query += " AND api_provider = %s"
            params.append(preferred_provider)

        query += " ORDER BY last_used ASC NULLS FIRST LIMIT 1"

        cur.execute(query, params)
        new_contractor = cur.fetchone()

        if not new_contractor:
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": "No other contractors available"}),
                400,
            )

        # Update proposal
        cur.execute(
            """
            UPDATE improvement_proposals
            SET contractor_agent_id = %s
            WHERE id = %s
        """,
            (new_contractor["id"], proposal_id),
        )

        conn.commit()
        cur.close()
        conn.close()

        # Log to chat
        from ai_bridge.chat_handler import get_chat_handler

        chat = get_chat_handler()
        chat.add_system_message(
            proposal_id,
            f"Switched to contractor: {new_contractor['name']} ({new_contractor['api_provider']})",
            "action",
        )

        return jsonify(
            {
                "success": True,
                "contractor": dict(new_contractor),
                "message": f"Now consulting with {new_contractor['name']}",
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@improvements_bp.route("/queue/status", methods=["GET"])
@login_required
@admin_required
def get_queue_status():
    """Get current processing queue status"""
    try:
        from sandbox_queue import get_proposal_queue_manager

        manager = get_proposal_queue_manager()
        status = manager.get_full_status()

        return jsonify({"success": True, **status})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# END OF ROUTES
# ============================================================================
