"""
Telegram Gateway Routes — Bot status, user linking, notification rules

Registered on the autonomy_bp blueprint.

Author: A.R.C.H.I.E. Platform
Created: 2026-02-17
"""

import json
import logging
import os
import sys

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import current_app, jsonify, request
from flask_login import current_user, login_required

from . import autonomy_bp

logger = logging.getLogger("telegram_routes")

sys.path.insert(0, "/mnt/archie_brain/ai_bridge")


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", "archiepass"),
    )


# ============================================================================
# Bot Status
# ============================================================================


@autonomy_bp.route("/api/telegram/status")
@login_required
def telegram_status():
    """Get Telegram bot status."""
    try:
        gateway = current_app.config.get("TELEGRAM_GATEWAY")
        bot_running = gateway.is_running if gateway else False
        bot_configured = bool(os.getenv("TELEGRAM_BOT_TOKEN"))

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT COUNT(*) as c FROM telegram_users WHERE is_authorized = TRUE")
        authorized_users = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) as c FROM telegram_messages WHERE created_at > NOW() - INTERVAL '24 hours'")
        messages_24h = cur.fetchone()["c"]

        return jsonify(
            {
                "success": True,
                "bot_configured": bot_configured,
                "bot_running": bot_running,
                "authorized_users": authorized_users,
                "messages_24h": messages_24h,
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
# User Linking
# ============================================================================


@autonomy_bp.route("/api/telegram/link-code", methods=["POST"])
@login_required
def generate_link_code():
    """Generate a one-time code for linking Telegram account."""
    try:
        from telegram_gateway import generate_link_code as gen_code

        code = gen_code(current_user.id)
        if code:
            return jsonify(
                {
                    "success": True,
                    "code": code,
                    "expires_in": "15 minutes",
                    "instructions": f"Send '/link {code}' to the ARCHIE Telegram bot",
                }
            )
        return jsonify({"success": False, "error": "Failed to generate code"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/telegram/users")
@login_required
def get_telegram_users():
    """Get linked Telegram users."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT tu.id, tu.telegram_id, tu.telegram_username, tu.first_name,
                   tu.is_authorized, tu.created_at, u.username as archie_username
            FROM telegram_users tu
            LEFT JOIN users u ON tu.user_id = u.id
            ORDER BY tu.created_at DESC
            """
        )
        users = [dict(r) for r in cur.fetchall()]
        return jsonify({"success": True, "users": users})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@autonomy_bp.route("/api/telegram/users/<int:tu_id>/authorize", methods=["POST"])
@login_required
def authorize_telegram_user(tu_id):
    """Authorize/deauthorize a Telegram user."""
    try:
        authorize = (request.get_json() or {}).get("authorize", True) if request.json else True
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE telegram_users SET is_authorized = %s, updated_at = NOW() WHERE id = %s",
            (authorize, tu_id),
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
# Notification Rules
# ============================================================================


@autonomy_bp.route("/api/telegram/rules")
@login_required
def get_notification_rules():
    """Get notification forwarding rules."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT tnr.*, tu.telegram_username
            FROM telegram_notification_rules tnr
            JOIN telegram_users tu ON tnr.telegram_user_id = tu.id
            ORDER BY tnr.created_at DESC
            """
        )
        rules = [dict(r) for r in cur.fetchall()]
        return jsonify({"success": True, "rules": rules})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@autonomy_bp.route("/api/telegram/rules", methods=["POST"])
@login_required
def create_notification_rule():
    """Create a notification forwarding rule."""
    try:
        data = request.get_json() or {}
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            INSERT INTO telegram_notification_rules
            (telegram_user_id, notification_type, priority_min, source_filter,
             quiet_hours_start, quiet_hours_end)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                data["telegram_user_id"],
                data.get("notification_type"),
                data.get("priority_min", "normal"),
                data.get("source_filter"),
                data.get("quiet_hours_start"),
                data.get("quiet_hours_end"),
            ),
        )
        rule_id = cur.fetchone()["id"]
        conn.commit()
        return jsonify({"success": True, "id": rule_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@autonomy_bp.route("/api/telegram/rules/<int:rule_id>", methods=["DELETE"])
@login_required
def delete_notification_rule(rule_id):
    """Delete a notification rule."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM telegram_notification_rules WHERE id = %s", (rule_id,))
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
