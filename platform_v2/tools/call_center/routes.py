"""
Call Center Routes
==================
Phone system and AI call handling for businesses.

Dual-purpose module:
- Admin: Manages ARCHIE company phone system and AI agents
- Users: Set up their own phone system with their own providers

Author: A.R.C.H.I.E. Platform
Date: 2026-01-12
"""

from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import os
import json

# Import user context helpers
try:
    from services.user_context import (
        get_user_filter,
        can_access_resource,
        require_ownership,
        add_user_id_to_data,
        is_admin_user,
        log_user_activity,
    )
except ImportError:

    def get_user_filter(*args, **kwargs):
        return f"user_id = {current_user.id}" if current_user.is_authenticated else "1=0"

    def can_access_resource(user_id):
        return current_user.is_authenticated and (
            current_user.id == user_id or getattr(current_user, "is_admin", False)
        )

    def is_admin_user():
        return getattr(current_user, "is_admin", False)


# Create blueprint
call_center_bp = Blueprint(
    "call_center",
    __name__,
    url_prefix="/tools/call-center",
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


@call_center_bp.route("/")
@login_required
def index():
    """Main Call Center interface"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get user's phone numbers
        if is_admin_user():
            cur.execute(
                """
                SELECT pn.*, p.name as provider_name
                FROM user_phone_numbers pn
                LEFT JOIN providers p ON pn.provider_id = p.id
                ORDER BY pn.created_at DESC
            """
            )
        else:
            cur.execute(
                """
                SELECT pn.*, p.name as provider_name
                FROM user_phone_numbers pn
                LEFT JOIN providers p ON pn.provider_id = p.id
                WHERE pn.user_id = %s
                ORDER BY pn.created_at DESC
            """,
                (current_user.id,),
            )

        phone_numbers = cur.fetchall()

        # Get call stats (last 30 days)
        if is_admin_user():
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_calls,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE status = 'escalated') as escalated,
                    AVG(duration_seconds) as avg_duration,
                    AVG(customer_satisfaction) as avg_satisfaction
                FROM conversations
                WHERE start_time > NOW() - INTERVAL '30 days'
            """
            )
        else:
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_calls,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE status = 'escalated') as escalated,
                    AVG(duration_seconds) as avg_duration,
                    AVG(customer_satisfaction) as avg_satisfaction
                FROM conversations
                WHERE user_id = %s AND start_time > NOW() - INTERVAL '30 days'
            """,
                (current_user.id,),
            )

        call_stats = cur.fetchone()

        # Get recent calls
        if is_admin_user():
            cur.execute(
                """
                SELECT c.*, cust.name as customer_name, cust.phone_number as customer_phone
                FROM conversations c
                LEFT JOIN customers cust ON c.customer_id = cust.id
                ORDER BY c.start_time DESC
                LIMIT 10
            """
            )
        else:
            cur.execute(
                """
                SELECT c.*, cust.name as customer_name, cust.phone_number as customer_phone
                FROM conversations c
                LEFT JOIN customers cust ON c.customer_id = cust.id
                WHERE c.user_id = %s
                ORDER BY c.start_time DESC
                LIMIT 10
            """,
                (current_user.id,),
            )

        recent_calls = cur.fetchall()

        # Get pending escalations
        if is_admin_user():
            cur.execute(
                """
                SELECT e.*, c.caller_number, cust.name as customer_name
                FROM escalations e
                JOIN conversations c ON e.conversation_id = c.id
                LEFT JOIN customers cust ON c.customer_id = cust.id
                WHERE e.resolved_at IS NULL
                ORDER BY e.escalated_at DESC
                LIMIT 10
            """
            )
        else:
            cur.execute(
                """
                SELECT e.*, c.caller_number, cust.name as customer_name
                FROM escalations e
                JOIN conversations c ON e.conversation_id = c.id
                LEFT JOIN customers cust ON c.customer_id = cust.id
                WHERE e.user_id = %s AND e.resolved_at IS NULL
                ORDER BY e.escalated_at DESC
                LIMIT 10
            """,
                (current_user.id,),
            )

        escalations = cur.fetchall()

        # Get user's telephony integrations
        cur.execute(
            """
            SELECT * FROM user_integrations
            WHERE user_id = %s AND service IN ('twilio', 'telnyx')
        """,
            (current_user.id,),
        )
        integrations = {row["service"]: row for row in cur.fetchall()}

        return render_template(
            "call_center.html",
            phone_numbers=phone_numbers,
            call_stats=call_stats,
            recent_calls=recent_calls,
            escalations=escalations,
            integrations=integrations,
            is_admin=is_admin_user(),
        )
    except Exception as e:
        current_app.logger.error(f"[CallCenter] Error loading: {e}")
        return render_template(
            "call_center.html",
            phone_numbers=[],
            call_stats={"total_calls": 0, "completed": 0, "escalated": 0},
            recent_calls=[],
            escalations=[],
            integrations={},
            error=str(e),
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# PHONE NUMBERS
# ============================================================================


@call_center_bp.route("/api/numbers", methods=["GET"])
@login_required
def get_numbers():
    """Get user's phone numbers"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if is_admin_user() and request.args.get("all") == "true":
            cur.execute(
                """
                SELECT pn.*, p.name as provider_name, u.username as owner_name
                FROM user_phone_numbers pn
                LEFT JOIN providers p ON pn.provider_id = p.id
                LEFT JOIN users u ON pn.user_id = u.id
                ORDER BY pn.created_at DESC
            """
            )
        else:
            cur.execute(
                """
                SELECT pn.*, p.name as provider_name
                FROM user_phone_numbers pn
                LEFT JOIN providers p ON pn.provider_id = p.id
                WHERE pn.user_id = %s
                ORDER BY pn.created_at DESC
            """,
                (current_user.id,),
            )

        numbers = cur.fetchall()

        return jsonify({"success": True, "numbers": [dict(n) for n in numbers]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@call_center_bp.route("/api/numbers", methods=["POST"])
@login_required
def provision_number():
    """Provision a new phone number"""
    try:
        data = request.get_json()

        if not data.get("phone_number"):
            return jsonify({"success": False, "error": "Phone number is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get user's provider
        cur.execute(
            """
            SELECT p.id FROM providers p
            JOIN user_integrations ui ON p.user_id = ui.user_id
            WHERE ui.user_id = %s AND ui.service IN ('twilio', 'telnyx') AND ui.status = 'active'
            LIMIT 1
        """,
            (current_user.id,),
        )
        provider = cur.fetchone()

        cur.execute(
            """
            INSERT INTO user_phone_numbers
            (user_id, provider_id, phone_number, friendly_name, capabilities, ai_agent_enabled, ai_agent_config)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                current_user.id,
                provider["id"] if provider else None,
                data["phone_number"],
                data.get("friendly_name", data["phone_number"]),
                json.dumps(data.get("capabilities", {"voice": True, "sms": False})),
                data.get("ai_agent_enabled", True),
                json.dumps(data.get("ai_agent_config", {})),
            ),
        )

        number = cur.fetchone()
        conn.commit()

        try:
            log_user_activity(
                "create",
                "call_center",
                {"phone": data["phone_number"]},
                "phone_number",
                number["id"],
            )
        except:
            pass

        return jsonify(
            {
                "success": True,
                "message": "Phone number provisioned",
                "number": dict(number),
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


@call_center_bp.route("/api/numbers/<int:number_id>", methods=["PUT"])
@login_required
def update_number(number_id):
    """Update phone number settings"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute("SELECT user_id FROM user_phone_numbers WHERE id = %s", (number_id,))
        number = cur.fetchone()

        if not number or not can_access_resource(number["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        updates = []
        values = []
        allowed = [
            "friendly_name",
            "ai_agent_enabled",
            "ai_agent_config",
            "business_hours",
            "forwarding_number",
            "voicemail_enabled",
        ]

        for field in allowed:
            if field in data:
                updates.append(f"{field} = %s")
                val = (
                    json.dumps(data[field])
                    if field in ["ai_agent_config", "business_hours", "capabilities"]
                    else data[field]
                )
                values.append(val)

        if not updates:
            return jsonify({"success": False, "error": "No valid fields"}), 400

        updates.append("updated_at = NOW()")
        values.append(number_id)

        cur.execute(
            f"""
            UPDATE user_phone_numbers
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING *
        """,
            values,
        )

        updated = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": "Phone number updated",
                "number": dict(updated),
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


@call_center_bp.route("/api/numbers/<int:number_id>", methods=["DELETE"])
@login_required
def release_number(number_id):
    """Release a phone number"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute(
            "SELECT user_id, phone_number FROM user_phone_numbers WHERE id = %s",
            (number_id,),
        )
        number = cur.fetchone()

        if not number or not can_access_resource(number["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        # Mark as released instead of deleting
        cur.execute(
            """
            UPDATE user_phone_numbers
            SET status = 'released', updated_at = NOW()
            WHERE id = %s
        """,
            (number_id,),
        )
        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": f'Phone number {number["phone_number"]} released',
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
# CALLS
# ============================================================================


@call_center_bp.route("/api/calls", methods=["GET"])
@login_required
def get_calls():
    """Get call history"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
        status = request.args.get("status")

        query = """
            SELECT c.*, cust.name as customer_name, cust.phone_number as customer_phone
            FROM conversations c
            LEFT JOIN customers cust ON c.customer_id = cust.id
        """

        params = []
        conditions = []

        if not is_admin_user():
            conditions.append("c.user_id = %s")
            params.append(current_user.id)

        if status:
            conditions.append("c.status = %s")
            params.append(status)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY c.start_time DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(query, params)
        calls = cur.fetchall()

        return jsonify({"success": True, "calls": [dict(c) for c in calls]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@call_center_bp.route("/api/calls/<call_id>", methods=["GET"])
@login_required
def get_call(call_id):
    """Get call details with transcript"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT c.*, cust.name as customer_name, cust.phone_number as customer_phone,
                   p.name as provider_name
            FROM conversations c
            LEFT JOIN customers cust ON c.customer_id = cust.id
            LEFT JOIN providers p ON c.provider_id = p.id
            WHERE c.id = %s
        """,
            (call_id,),
        )

        call = cur.fetchone()

        if not call:
            return jsonify({"success": False, "error": "Call not found"}), 404

        if call.get("user_id") and not can_access_resource(call["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        # Get conversation turns (transcript)
        cur.execute(
            """
            SELECT * FROM conversation_turns
            WHERE conversation_id = %s
            ORDER BY turn_number
        """,
            (call_id,),
        )
        transcript = cur.fetchall()

        # Get any escalations
        cur.execute(
            """
            SELECT * FROM escalations
            WHERE conversation_id = %s
        """,
            (call_id,),
        )
        escalations = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "call": dict(call),
                "transcript": [dict(t) for t in transcript],
                "escalations": [dict(e) for e in escalations],
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


@call_center_bp.route("/api/calls/stats", methods=["GET"])
@login_required
def get_call_stats():
    """Get call statistics"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        days = int(request.args.get("days", 30))

        if is_admin_user():
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_calls,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE status = 'escalated') as escalated,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed,
                    COUNT(*) FILTER (WHERE status = 'active') as active,
                    AVG(duration_seconds)::INTEGER as avg_duration,
                    AVG(customer_satisfaction) as avg_satisfaction,
                    COUNT(*) FILTER (WHERE direction = 'inbound') as inbound,
                    COUNT(*) FILTER (WHERE direction = 'outbound') as outbound
                FROM conversations
                WHERE start_time > NOW() - (%s * INTERVAL '1 day')
            """,
                (days,),
            )
        else:
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_calls,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE status = 'escalated') as escalated,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed,
                    COUNT(*) FILTER (WHERE status = 'active') as active,
                    AVG(duration_seconds)::INTEGER as avg_duration,
                    AVG(customer_satisfaction) as avg_satisfaction,
                    COUNT(*) FILTER (WHERE direction = 'inbound') as inbound,
                    COUNT(*) FILTER (WHERE direction = 'outbound') as outbound
                FROM conversations
                WHERE user_id = %s AND start_time > NOW() - (%s * INTERVAL '1 day')
            """,
                (current_user.id, days),
            )

        stats = cur.fetchone()

        return jsonify({"success": True, "stats": dict(stats) if stats else {}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# ESCALATIONS
# ============================================================================


@call_center_bp.route("/api/escalations", methods=["GET"])
@login_required
def get_escalations():
    """Get escalation queue"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        show_resolved = request.args.get("resolved") == "true"

        if is_admin_user():
            if show_resolved:
                cur.execute(
                    """
                    SELECT e.*, c.caller_number, cust.name as customer_name
                    FROM escalations e
                    JOIN conversations c ON e.conversation_id = c.id
                    LEFT JOIN customers cust ON c.customer_id = cust.id
                    ORDER BY e.escalated_at DESC
                    LIMIT 50
                """
                )
            else:
                cur.execute(
                    """
                    SELECT e.*, c.caller_number, cust.name as customer_name
                    FROM escalations e
                    JOIN conversations c ON e.conversation_id = c.id
                    LEFT JOIN customers cust ON c.customer_id = cust.id
                    WHERE e.resolved_at IS NULL
                    ORDER BY e.escalated_at DESC
                """
                )
        else:
            if show_resolved:
                cur.execute(
                    """
                    SELECT e.*, c.caller_number, cust.name as customer_name
                    FROM escalations e
                    JOIN conversations c ON e.conversation_id = c.id
                    LEFT JOIN customers cust ON c.customer_id = cust.id
                    WHERE e.user_id = %s
                    ORDER BY e.escalated_at DESC
                    LIMIT 50
                """,
                    (current_user.id,),
                )
            else:
                cur.execute(
                    """
                    SELECT e.*, c.caller_number, cust.name as customer_name
                    FROM escalations e
                    JOIN conversations c ON e.conversation_id = c.id
                    LEFT JOIN customers cust ON c.customer_id = cust.id
                    WHERE e.user_id = %s AND e.resolved_at IS NULL
                    ORDER BY e.escalated_at DESC
                """,
                    (current_user.id,),
                )

        escalations = cur.fetchall()

        return jsonify({"success": True, "escalations": [dict(e) for e in escalations]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@call_center_bp.route("/api/escalations/<escalation_id>", methods=["PUT"])
@login_required
def resolve_escalation(escalation_id):
    """Resolve an escalation"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify access
        cur.execute("SELECT user_id FROM escalations WHERE id = %s", (escalation_id,))
        escalation = cur.fetchone()

        if not escalation:
            return jsonify({"success": False, "error": "Escalation not found"}), 404

        if escalation.get("user_id") and not can_access_resource(escalation["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        cur.execute(
            """
            UPDATE escalations
            SET resolved_at = NOW(),
                resolution_notes = %s,
                was_necessary = %s
            WHERE id = %s
            RETURNING *
        """,
            (
                data.get("resolution_notes", ""),
                data.get("was_necessary", True),
                escalation_id,
            ),
        )

        updated = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": "Escalation resolved",
                "escalation": dict(updated),
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
# TELEPHONY INTEGRATIONS
# ============================================================================


@call_center_bp.route("/api/integrations", methods=["GET"])
@login_required
def get_integrations():
    """Get user's telephony integrations"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, service, status, settings, last_verified_at, created_at
            FROM user_integrations
            WHERE user_id = %s AND service IN ('twilio', 'telnyx')
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
            pass


@call_center_bp.route("/api/integrations/<service>", methods=["POST"])
@login_required
def connect_integration(service):
    """Connect a telephony provider"""
    try:
        allowed_services = ["twilio", "telnyx"]
        if service not in allowed_services:
            return jsonify({"success": False, "error": "Invalid service"}), 400

        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Create user-specific provider
        cur.execute(
            """
            INSERT INTO providers (user_id, name, type, status, authentication)
            VALUES (%s, %s, %s, 'active', %s)
            ON CONFLICT (name) DO UPDATE SET
                authentication = EXCLUDED.authentication,
                status = 'active',
                updated_at = NOW()
            RETURNING id
        """,
            (
                current_user.id,
                f"{service}_{current_user.id}",
                service,
                json.dumps(data.get("credentials", {})),
            ),
        )

        provider = cur.fetchone()

        # Also save to user_integrations
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
                json.dumps(data.get("credentials", {})),
                json.dumps(data.get("settings", {})),
            ),
        )

        integration = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": f"{service.title()} connected",
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
            pass


# ============================================================================
# AI AGENT CONFIGURATION
# ============================================================================


@call_center_bp.route("/api/agents", methods=["GET"])
@login_required
def get_ai_agents():
    """Get user's AI agent configurations"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get phone numbers with their AI configs
        cur.execute(
            """
            SELECT id, phone_number, friendly_name, ai_agent_enabled, ai_agent_config
            FROM user_phone_numbers
            WHERE user_id = %s AND status = 'active'
        """,
            (current_user.id,),
        )

        agents = cur.fetchall()

        return jsonify({"success": True, "agents": [dict(a) for a in agents]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@call_center_bp.route("/api/agents/<int:number_id>", methods=["PUT"])
@login_required
def update_ai_agent(number_id):
    """Update AI agent configuration for a phone number"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute("SELECT user_id FROM user_phone_numbers WHERE id = %s", (number_id,))
        number = cur.fetchone()

        if not number or not can_access_resource(number["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        cur.execute(
            """
            UPDATE user_phone_numbers
            SET ai_agent_enabled = %s,
                ai_agent_config = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
        """,
            (
                data.get("ai_agent_enabled", True),
                json.dumps(data.get("ai_agent_config", {})),
                number_id,
            ),
        )

        updated = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": "AI agent configuration updated",
                "agent": dict(updated),
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
# PROVIDERS API (migrated from admin routes)
# ============================================================================


@call_center_bp.route("/api/providers", methods=["GET"])
@login_required
def get_providers():
    """Get all telephony providers (migrated from admin routes)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Admin sees all providers, users see only their own or system providers
        if is_admin_user():
            cur.execute(
                """
                SELECT id, name, type, status, capabilities, cost_per_minute,
                       quality_score, created_at
                FROM providers
                ORDER BY quality_score DESC, name
            """
            )
        else:
            cur.execute(
                """
                SELECT id, name, type, status, capabilities, cost_per_minute,
                       quality_score, created_at
                FROM providers
                WHERE user_id IS NULL OR user_id = %s
                ORDER BY quality_score DESC, name
            """,
                (current_user.id,),
            )

        providers = cur.fetchall()

        providers_list = []
        for p in providers:
            providers_list.append(
                {
                    "id": str(p["id"]),
                    "name": p["name"],
                    "type": p["type"],
                    "status": p["status"],
                    "capabilities": p["capabilities"],
                    "cost_per_minute": (float(p["cost_per_minute"]) if p["cost_per_minute"] else 0),
                    "quality_score": p["quality_score"],
                    "created_at": (p["created_at"].isoformat() if p["created_at"] else None),
                }
            )

        return jsonify({"success": True, "providers": providers_list})

    except Exception as e:
        current_app.logger.error(f"[CallCenter] Error getting providers: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# CONVERSATIONS API (migrated from admin routes)
# ============================================================================


@call_center_bp.route("/api/conversations", methods=["GET"])
@login_required
def get_conversations():
    """Get conversations with optional filtering (migrated from admin routes)"""
    try:
        status = request.args.get("status", "all")
        limit = int(request.args.get("limit", 50))

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT
                c.id, c.call_sid, c.direction, c.status, c.intent,
                c.agent_type, c.start_time, c.end_time, c.duration_seconds,
                c.outcome, c.customer_satisfaction, c.cost,
                cust.name as customer_name, cust.phone_number,
                p.name as provider_name, p.type as provider_type,
                a.name as agent_name
            FROM conversations c
            LEFT JOIN customers cust ON c.customer_id = cust.id
            LEFT JOIN providers p ON c.provider_id = p.id
            LEFT JOIN agents a ON c.assigned_agent_id = a.id
        """

        params = []
        conditions = []

        # Non-admins can only see their own conversations
        if not is_admin_user():
            conditions.append("c.user_id = %s")
            params.append(current_user.id)

        if status != "all":
            conditions.append("c.status = %s")
            params.append(status)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY c.start_time DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        conversations = cur.fetchall()

        convs_list = []
        for conv in conversations:
            convs_list.append(
                {
                    "id": str(conv["id"]),
                    "call_sid": conv["call_sid"],
                    "direction": conv["direction"],
                    "status": conv["status"],
                    "intent": conv["intent"],
                    "agent_type": conv["agent_type"],
                    "start_time": (conv["start_time"].isoformat() if conv["start_time"] else None),
                    "end_time": (conv["end_time"].isoformat() if conv["end_time"] else None),
                    "duration_seconds": conv["duration_seconds"],
                    "outcome": conv["outcome"],
                    "customer_satisfaction": (
                        float(conv["customer_satisfaction"]) if conv["customer_satisfaction"] else None
                    ),
                    "cost": float(conv["cost"]) if conv["cost"] else 0,
                    "customer_name": conv["customer_name"],
                    "phone_number": conv["phone_number"],
                    "provider_name": conv["provider_name"],
                    "provider_type": conv["provider_type"],
                    "agent_name": conv["agent_name"],
                }
            )

        return jsonify({"success": True, "conversations": convs_list})

    except Exception as e:
        current_app.logger.error(f"[CallCenter] Error getting conversations: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@call_center_bp.route("/api/conversations/<conversation_id>", methods=["GET"])
@login_required
def get_conversation_detail(conversation_id):
    """Get detailed conversation information including turns (migrated from admin routes)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get conversation details
        cur.execute(
            """
            SELECT c.*,
                   cust.name as customer_name, cust.phone_number, cust.email,
                   p.name as provider_name, p.type as provider_type,
                   a.name as agent_name
            FROM conversations c
            LEFT JOIN customers cust ON c.customer_id = cust.id
            LEFT JOIN providers p ON c.provider_id = p.id
            LEFT JOIN agents a ON c.assigned_agent_id = a.id
            WHERE c.id = %s
        """,
            (conversation_id,),
        )

        conversation = cur.fetchone()

        if not conversation:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Conversation not found"}), 404

        # Check access - non-admins can only see their own conversations
        if conversation.get("user_id") and not can_access_resource(conversation["user_id"]):
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Access denied"}), 403

        # Get conversation turns
        cur.execute(
            """
            SELECT id, turn_number, role, content, timestamp, duration_seconds,
                   confidence_score, intent, sentiment, ai_source, tokens_used,
                   processing_time_ms
            FROM conversation_turns
            WHERE conversation_id = %s
            ORDER BY turn_number
        """,
            (conversation_id,),
        )

        turns = cur.fetchall()

        # Format conversation
        conv_data = dict(conversation)
        if conv_data.get("start_time"):
            conv_data["start_time"] = conv_data["start_time"].isoformat()
        if conv_data.get("end_time"):
            conv_data["end_time"] = conv_data["end_time"].isoformat()
        if conv_data.get("created_at"):
            conv_data["created_at"] = conv_data["created_at"].isoformat()
        if conv_data.get("updated_at"):
            conv_data["updated_at"] = conv_data["updated_at"].isoformat()
        conv_data["id"] = str(conv_data["id"])

        # Format turns
        turns_list = []
        for turn in turns:
            turn_data = dict(turn)
            turn_data["id"] = str(turn_data["id"])
            if turn_data.get("timestamp"):
                turn_data["timestamp"] = turn_data["timestamp"].isoformat()
            turns_list.append(turn_data)

        return jsonify({"success": True, "conversation": conv_data, "turns": turns_list})

    except Exception as e:
        current_app.logger.error(f"[CallCenter] Error getting conversation detail: {e}")
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


@call_center_bp.route("/health")
def health_check():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM conversations")
        count = cur.fetchone()[0]

        return jsonify({"healthy": True, "module": "call_center", "total_calls": count})
    except Exception as e:
        return (
            jsonify({"healthy": False, "module": "call_center", "error": str(e)}),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# TELUS SETUP WIZARD
# ============================================================================


@call_center_bp.route("/api/telus/setup", methods=["GET"])
@login_required
def get_telus_setup():
    """Get TELUS 1-800 setup configuration"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get TELUS provider
        cur.execute(
            """
            SELECT * FROM providers WHERE name = 'telus_business_connect'
        """
        )
        provider = cur.fetchone()

        # Get TELUS phone numbers for user
        cur.execute(
            """
            SELECT pn.*, p.name as provider_name
            FROM user_phone_numbers pn
            JOIN providers p ON pn.provider_id = p.id
            WHERE p.name = 'telus_business_connect'
            AND (pn.user_id = %s OR %s)
            ORDER BY pn.created_at DESC
        """,
            (current_user.id, is_admin_user()),
        )

        numbers = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "provider": dict(provider) if provider else None,
                "numbers": [dict(n) for n in numbers],
                "is_configured": len(numbers) > 0,
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


@call_center_bp.route("/api/telus/setup", methods=["POST"])
@login_required
def update_telus_setup():
    """Update TELUS 1-800 configuration"""
    try:
        data = request.get_json()
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        number_id = data.get("number_id")

        if number_id:
            # Update existing number
            updates = []
            values = []

            if "phone_number" in data:
                updates.append("phone_number = %s")
                values.append(data["phone_number"])

            if "friendly_name" in data:
                updates.append("friendly_name = %s")
                values.append(data["friendly_name"])

            if "ai_agent_config" in data:
                updates.append("ai_agent_config = %s")
                values.append(json.dumps(data["ai_agent_config"]))

            if "business_hours" in data:
                updates.append("business_hours = %s")
                values.append(json.dumps(data["business_hours"]))

            if "forwarding_number" in data:
                updates.append("forwarding_number = %s")
                values.append(data["forwarding_number"])

            if "ai_agent_enabled" in data:
                updates.append("ai_agent_enabled = %s")
                values.append(data["ai_agent_enabled"])

            updates.append("updated_at = NOW()")
            values.append(number_id)

            cur.execute(
                f"""
                UPDATE user_phone_numbers
                SET {', '.join(updates)}
                WHERE id = %s
                RETURNING *
            """,
                values,
            )

            result = cur.fetchone()

        else:
            # Create new TELUS number
            cur.execute("SELECT id FROM providers WHERE name = 'telus_business_connect'")
            provider = cur.fetchone()

            if not provider:
                return (
                    jsonify({"success": False, "error": "TELUS provider not configured"}),
                    400,
                )

            cur.execute(
                """
                INSERT INTO user_phone_numbers (
                    user_id, provider_id, phone_number, friendly_name,
                    country_code, capabilities, ai_agent_enabled,
                    ai_agent_config, business_hours, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
                RETURNING *
            """,
                (
                    current_user.id,
                    provider["id"],
                    data.get("phone_number", "+18001234567"),
                    data.get("friendly_name", "Business Line"),
                    "+1",
                    json.dumps(
                        data.get(
                            "capabilities",
                            {
                                "inbound_calls": True,
                                "outbound_calls": True,
                                "call_recording": True,
                            },
                        )
                    ),
                    data.get("ai_agent_enabled", True),
                    json.dumps(data.get("ai_agent_config", {})),
                    json.dumps(data.get("business_hours", {})),
                ),
            )

            result = cur.fetchone()

        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": "TELUS configuration updated",
                "number": dict(result) if result else None,
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


@call_center_bp.route("/api/crm/lookup", methods=["POST"])
@login_required
def crm_customer_lookup():
    """Look up customer in CRM by phone number (for incoming calls)"""
    try:
        data = request.get_json()
        phone = data.get("phone_number", "").replace(" ", "").replace("-", "")

        if not phone:
            return jsonify({"success": False, "error": "Phone number required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Search in CRM customers
        cur.execute(
            """
            SELECT
                c.id, c.name, c.email, c.phone, c.company,
                c.customer_type, c.status, c.subscription_tier,
                c.total_spent, c.lifetime_value, c.notes,
                c.created_at,
                COUNT(DISTINCT i.id) as total_interactions
            FROM crm_customers c
            LEFT JOIN crm_interactions i ON c.id = i.customer_id
            WHERE c.phone LIKE %s OR c.phone LIKE %s
            GROUP BY c.id
            LIMIT 1
        """,
            (f"%{phone[-10:]}%", phone),
        )

        customer = cur.fetchone()

        if customer:
            # Get recent interactions
            cur.execute(
                """
                SELECT type, subject, created_at
                FROM crm_interactions
                WHERE customer_id = %s
                ORDER BY created_at DESC
                LIMIT 5
            """,
                (customer["id"],),
            )
            interactions = cur.fetchall()

            # Get recent orders
            cur.execute(
                """
                SELECT id, total, status, created_at
                FROM invoices
                WHERE customer_id = %s
                ORDER BY created_at DESC
                LIMIT 5
            """,
                (customer["id"],),
            )
            orders = cur.fetchall()

            # Get scheduled appointments
            cur.execute(
                """
                SELECT title, start_time, status
                FROM calendar_events
                WHERE customer_id = %s AND start_time > NOW()
                ORDER BY start_time
                LIMIT 3
            """,
                (customer["id"],),
            )
            appointments = cur.fetchall()

            cur.close()
            conn.close()

            return jsonify(
                {
                    "success": True,
                    "found": True,
                    "customer": dict(customer),
                    "recent_interactions": [dict(i) for i in interactions],
                    "recent_orders": [dict(o) for o in orders],
                    "upcoming_appointments": [dict(a) for a in appointments],
                }
            )

        return jsonify({"success": True, "found": False, "message": "Customer not found in CRM"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@call_center_bp.route("/api/status")
def api_status():
    """Get module status"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get active numbers
        cur.execute("SELECT COUNT(*) as count FROM user_phone_numbers WHERE status = 'active'")
        active_numbers = cur.fetchone()["count"]

        # Get TELUS status
        cur.execute(
            """
            SELECT COUNT(*) as count FROM user_phone_numbers pn
            JOIN providers p ON pn.provider_id = p.id
            WHERE p.name = 'telus_business_connect' AND pn.status = 'active'
        """
        )
        telus_numbers = cur.fetchone()["count"]

        # Get today's calls
        cur.execute(
            """
            SELECT COUNT(*) as count FROM conversations
            WHERE start_time::date = CURRENT_DATE
        """
        )
        today_calls = cur.fetchone()["count"]

        return jsonify(
            {
                "module": "call_center",
                "status": "operational",
                "healthy": True,
                "active_numbers": active_numbers,
                "telus_numbers": telus_numbers,
                "today_calls": today_calls,
                "telus_configured": telus_numbers > 0,
            }
        )

    except Exception as e:
        return (
            jsonify(
                {
                    "module": "call_center",
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
            pass
