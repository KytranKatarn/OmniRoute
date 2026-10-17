"""
Email Manager Routes — Templates & Settings
===========================================
Template CRUD and SMTP settings management.

Registered on the existing email_manager_bp blueprint.

Author: A.R.C.H.I.E. Platform
Date: 2026-01-17
"""

import json
import smtplib

from flask import current_app, jsonify, request
from flask_login import current_user, login_required
from psycopg2.extras import RealDictCursor

from .access_control import email_access_required
from .routes import email_manager_bp, get_db_connection


# ============================================================================
# TEMPLATES CRUD
# ============================================================================


@email_manager_bp.route("/api/templates", methods=["GET"])
@login_required
@email_access_required
def get_templates():
    """Get all email templates"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        template_type = request.args.get("type", "")

        if template_type:
            cur.execute(
                """
                SELECT * FROM email_templates
                WHERE template_type = %s AND is_active = true
                ORDER BY name
            """,
                (template_type,),
            )
        else:
            cur.execute(
                """
                SELECT * FROM email_templates
                WHERE is_active = true
                ORDER BY name
            """
            )
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


@email_manager_bp.route("/api/templates", methods=["POST"])
@login_required
def create_template():
    """Create a new email template"""
    try:
        data = request.get_json()

        if not data.get("name") or not data.get("subject"):
            return (
                jsonify({"success": False, "error": "Name and subject are required"}),
                400,
            )

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO email_templates
            (name, subject, body_html, body_text, template_type, variables, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                data["name"],
                data["subject"],
                data.get("body_html", ""),
                data.get("body_text", ""),
                data.get("template_type", "custom"),
                json.dumps(data.get("variables", {})),
                current_user.id,
            ),
        )
        template = cur.fetchone()

        conn.commit()

        return jsonify(
            {
                "success": True,
                "template": dict(template),
                "message": "Template created successfully",
            }
        )
    except Exception as e:
        current_app.logger.error(f"[EmailManager] Error creating template: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/templates/<int:template_id>", methods=["GET"])
@login_required
def get_template(template_id):
    """Get template details"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM email_templates WHERE id = %s", (template_id,))
        template = cur.fetchone()

        if not template:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Template not found"}), 404

        return jsonify({"success": True, "template": dict(template)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/templates/<int:template_id>", methods=["PUT"])
@login_required
def update_template(template_id):
    """Update email template"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE email_templates
            SET name = COALESCE(%s, name),
                subject = COALESCE(%s, subject),
                body_html = COALESCE(%s, body_html),
                body_text = COALESCE(%s, body_text),
                template_type = COALESCE(%s, template_type),
                variables = COALESCE(%s, variables),
                is_active = COALESCE(%s, is_active),
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
        """,
            (
                data.get("name"),
                data.get("subject"),
                data.get("body_html"),
                data.get("body_text"),
                data.get("template_type"),
                json.dumps(data["variables"]) if "variables" in data else None,
                data.get("is_active"),
                template_id,
            ),
        )
        template = cur.fetchone()

        if not template:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Template not found"}), 404

        conn.commit()

        return jsonify({"success": True, "template": dict(template)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/templates/<int:template_id>", methods=["DELETE"])
@login_required
def delete_template(template_id):
    """Delete email template (soft delete)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE email_templates
            SET is_active = false, updated_at = NOW()
            WHERE id = %s
            RETURNING name
        """,
            (template_id,),
        )
        template = cur.fetchone()

        if not template:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Template not found"}), 404

        conn.commit()

        return jsonify({"success": True, "message": f"Template '{template['name']}' deleted"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# SMTP SETTINGS
# ============================================================================


@email_manager_bp.route("/api/settings", methods=["GET"])
@login_required
@email_access_required
def get_settings():
    """Get SMTP settings"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, name, smtp_host, smtp_port, smtp_user, encryption,
                   from_email, from_name, reply_to, is_default, is_active,
                   test_result, test_message, tested_at
            FROM email_settings
            WHERE is_active = true
            ORDER BY is_default DESC, name
        """
        )
        settings = cur.fetchall()

        return jsonify({"success": True, "settings": [dict(s) for s in settings]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/settings", methods=["POST"])
@login_required
def create_settings():
    """Create new SMTP settings"""
    try:
        data = request.get_json()

        if not data.get("smtp_host") or not data.get("from_email"):
            return (
                jsonify({"success": False, "error": "SMTP host and from email are required"}),
                400,
            )

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # If this is marked as default, unset other defaults
        if data.get("is_default"):
            cur.execute("UPDATE email_settings SET is_default = false")

        cur.execute(
            """
            INSERT INTO email_settings
            (name, smtp_host, smtp_port, smtp_user, smtp_password_encrypted,
             encryption, from_email, from_name, reply_to, is_default)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, name, smtp_host, smtp_port, from_email, is_default
        """,
            (
                data.get("name", "SMTP Settings"),
                data["smtp_host"],
                data.get("smtp_port", 587),
                data.get("smtp_user", ""),
                data.get("smtp_password", ""),  # In production, encrypt this
                data.get("encryption", "tls"),
                data["from_email"],
                data.get("from_name", ""),
                data.get("reply_to", ""),
                data.get("is_default", False),
            ),
        )
        settings = cur.fetchone()

        conn.commit()

        return jsonify(
            {
                "success": True,
                "settings": dict(settings),
                "message": "SMTP settings created",
            }
        )
    except Exception as e:
        current_app.logger.error(f"[EmailManager] Error creating settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/settings/<int:settings_id>", methods=["PUT"])
@login_required
def update_settings(settings_id):
    """Update SMTP settings"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # If this is marked as default, unset other defaults
        if data.get("is_default"):
            cur.execute(
                "UPDATE email_settings SET is_default = false WHERE id != %s",
                (settings_id,),
            )

        # Build update query
        updates = []
        params = []
        field_map = {
            "name": "name",
            "smtp_host": "smtp_host",
            "smtp_port": "smtp_port",
            "smtp_user": "smtp_user",
            "encryption": "encryption",
            "from_email": "from_email",
            "from_name": "from_name",
            "reply_to": "reply_to",
            "is_default": "is_default",
        }

        for key, field in field_map.items():
            if key in data:
                updates.append(f"{field} = %s")
                params.append(data[key])

        if data.get("smtp_password"):
            updates.append("smtp_password_encrypted = %s")
            params.append(data["smtp_password"])

        if not updates:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        updates.append("updated_at = NOW()")
        params.append(settings_id)

        cur.execute(
            "UPDATE email_settings SET "
            + ", ".join(updates)
            + " WHERE id = %s RETURNING id, name, smtp_host, smtp_port, from_email, is_default",
            params,
        )
        settings = cur.fetchone()

        if not settings:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Settings not found"}), 404

        conn.commit()

        return jsonify({"success": True, "settings": dict(settings)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/settings/<int:settings_id>/test", methods=["POST"])
@login_required
def test_settings(settings_id):
    """Test SMTP connection"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM email_settings WHERE id = %s
        """,
            (settings_id,),
        )
        settings = cur.fetchone()

        if not settings:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Settings not found"}), 404

        test_result = "failed"
        test_message = ""

        try:
            # Try to connect to SMTP server
            if settings["encryption"] == "ssl":
                server = smtplib.SMTP_SSL(settings["smtp_host"], settings["smtp_port"], timeout=10)
            else:
                server = smtplib.SMTP(settings["smtp_host"], settings["smtp_port"], timeout=10)
                if settings["encryption"] == "tls":
                    server.starttls()

            if settings["smtp_user"] and settings["smtp_password_encrypted"]:
                server.login(settings["smtp_user"], settings["smtp_password_encrypted"])

            server.quit()
            test_result = "success"
            test_message = "Connection successful"

        except smtplib.SMTPAuthenticationError:
            test_message = "Authentication failed - check username and password"
        except smtplib.SMTPConnectError:
            test_message = "Could not connect to SMTP server"
        except Exception as e:
            test_message = f"Connection error: {str(e)}"

        # Update test result
        cur.execute(
            """
            UPDATE email_settings
            SET test_result = %s, test_message = %s, tested_at = NOW()
            WHERE id = %s
        """,
            (test_result, test_message, settings_id),
        )
        conn.commit()

        return jsonify(
            {
                "success": test_result == "success",
                "result": test_result,
                "message": test_message,
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
