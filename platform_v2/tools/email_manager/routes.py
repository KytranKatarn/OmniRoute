"""
Email Manager Routes
====================
Email communications hub for A.R.C.H.I.E. Business Tools.

Features:
- Email templates with variable substitution
- SMTP configuration management
- Send emails (single and bulk)
- Email tracking (sent, opened, clicked)
- Campaign management
- Integration with CRM and Invoicing

Author: A.R.C.H.I.E. Platform
Date: 2026-01-17
"""

from functools import wraps

from flask import Blueprint, render_template, request, jsonify, current_app, abort
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from database import _get_db_password
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    from rbac import Permission, has_permission
except ImportError:
    Permission = None
    has_permission = None


def admin_required(f):
    """Decorator to require admin access."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if has_permission and Permission:
            if not has_permission(Permission.ADMIN_ACCESS, current_user):
                abort(403)
        else:
            if not getattr(current_user, "is_admin", False):
                abort(403)
        return f(*args, **kwargs)

    return decorated_function


# Import user context helpers
try:
    from services.user_context import is_admin_user
except ImportError:

    def is_admin_user():
        return getattr(current_user, "is_admin", False)


# Create blueprint
email_manager_bp = Blueprint(
    "email_manager",
    __name__,
    url_prefix="/tools/email-manager",
    template_folder="../../templates/tools",
)


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def render_template_vars(template_str, variables):
    """Replace {{variable}} placeholders with actual values"""
    if not template_str:
        return template_str
    for key, value in variables.items():
        template_str = template_str.replace("{{" + key + "}}", str(value))
    return template_str


def get_smtp_for_sending(cur, account_id=None):
    """Resolve SMTP config: per-account first, then legacy fallback."""
    if account_id:
        cur.execute(
            """SELECT smtp_host, smtp_port, smtp_user, smtp_password_encrypted,
                      smtp_encryption AS encryption, from_email, from_name, reply_to
               FROM email_imap_settings
               WHERE id = %s AND smtp_host IS NOT NULL""",
            (account_id,),
        )
        smtp = cur.fetchone()
        if smtp:
            return dict(smtp)
    # Fallback to legacy email_settings
    cur.execute("SELECT * FROM email_settings WHERE is_default = true AND is_active = true")
    smtp = cur.fetchone()
    return dict(smtp) if smtp else None


# ============================================================================
# MAIN PAGE
# ============================================================================


@email_manager_bp.route("/")
@login_required
def index():
    """Main Email Manager dashboard"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get email stats (last 30 days)
        cur.execute(
            """
            SELECT
                COUNT(*) as total_sent,
                COUNT(*) FILTER (WHERE status = 'sent') as delivered,
                COUNT(*) FILTER (WHERE status = 'opened') as opened,
                COUNT(*) FILTER (WHERE status = 'clicked') as clicked,
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                COUNT(*) FILTER (WHERE status = 'bounced') as bounced
            FROM email_logs
            WHERE created_at > NOW() - INTERVAL '30 days'
        """
        )
        stats = cur.fetchone()

        # Get templates
        cur.execute(
            """
            SELECT id, name, subject, template_type, is_active, created_at
            FROM email_templates
            ORDER BY name
        """
        )
        templates = cur.fetchall()

        # Get recent emails
        cur.execute(
            """
            SELECT id, recipient, subject, status, sent_at, opened_at, created_at
            FROM email_logs
            ORDER BY created_at DESC
            LIMIT 10
        """
        )
        recent_emails = cur.fetchall()

        # Get campaigns
        cur.execute(
            """
            SELECT c.*, t.name as template_name
            FROM email_campaigns c
            LEFT JOIN email_templates t ON c.template_id = t.id
            ORDER BY c.created_at DESC
            LIMIT 5
        """
        )
        campaigns = cur.fetchall()

        # Get SMTP settings status
        cur.execute(
            """
            SELECT id, name, from_email, is_default, test_result
            FROM email_settings
            WHERE is_active = true
            LIMIT 1
        """
        )
        smtp_status = cur.fetchone()

        # Get unread inbox count for nav badge (only user's accounts)
        email_unread_count = 0
        try:
            cur.execute(
                """SELECT COUNT(*) as c FROM email_inbox e
                JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
                WHERE e.is_read = FALSE AND e.is_archived = FALSE AND eis.user_id = %s""",
                (current_user.id,),
            )
            email_unread_count = cur.fetchone()["c"]
        except Exception:
            email_unread_count = 0

        return render_template(
            "email_manager.html",
            stats=stats,
            templates=templates,
            recent_emails=recent_emails,
            campaigns=campaigns,
            smtp_status=smtp_status,
            is_admin=is_admin_user(),
            email_unread_count=email_unread_count,
        )
    except Exception as e:
        current_app.logger.error(f"[EmailManager] Error loading dashboard: {e}")
        return render_template(
            "email_manager.html",
            stats={
                "total_sent": 0,
                "delivered": 0,
                "opened": 0,
                "clicked": 0,
                "failed": 0,
                "bounced": 0,
            },
            templates=[],
            recent_emails=[],
            campaigns=[],
            smtp_status=None,
            error=str(e),
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# TEMPLATES CRUD
# ============================================================================


@email_manager_bp.route("/api/templates", methods=["GET"])
@login_required
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
            f"""
            UPDATE email_settings
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING id, name, smtp_host, smtp_port, from_email, is_default
        """,
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


# ============================================================================
# SEND EMAIL
# ============================================================================


@email_manager_bp.route("/api/send", methods=["POST"])
@login_required
def send_email():
    """Send an email"""
    try:
        data = request.get_json()

        recipient = data.get("recipient")
        subject = data.get("subject")
        body_html = data.get("body_html", "")
        body_text = data.get("body_text", "")
        template_id = data.get("template_id")
        variables = data.get("variables", {})
        account_id = data.get("account_id")

        if not recipient:
            return jsonify({"success": False, "error": "Recipient is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # If using template, fetch and render it
        if template_id:
            cur.execute("SELECT * FROM email_templates WHERE id = %s", (template_id,))
            template = cur.fetchone()
            if template:
                subject = render_template_vars(template["subject"], variables)
                body_html = render_template_vars(template["body_html"], variables)
                body_text = render_template_vars(template["body_text"], variables)

        if not subject:
            return jsonify({"success": False, "error": "Subject is required"}), 400

        # Get SMTP settings (per-account or fallback)
        smtp = get_smtp_for_sending(cur, account_id)

        if not smtp:
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": "No SMTP settings configured"}),
                400,
            )

        # Create email log entry
        cur.execute(
            """
            INSERT INTO email_logs
            (template_id, recipient, subject, body_preview, status, metadata, created_by)
            VALUES (%s, %s, %s, %s, 'pending', %s, %s)
            RETURNING id
        """,
            (
                template_id,
                recipient,
                subject,
                body_text[:500] if body_text else body_html[:500] if body_html else "",
                json.dumps(variables),
                current_user.id,
            ),
        )
        log_id = cur.fetchone()["id"]
        conn.commit()

        # Send the email
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{smtp['from_name']} <{smtp['from_email']}>" if smtp["from_name"] else smtp["from_email"]
            msg["To"] = recipient
            if smtp["reply_to"]:
                msg["Reply-To"] = smtp["reply_to"]

            if body_text:
                msg.attach(MIMEText(body_text, "plain"))
            if body_html:
                msg.attach(MIMEText(body_html, "html"))

            # Connect and send
            if smtp["encryption"] == "ssl":
                server = smtplib.SMTP_SSL(smtp["smtp_host"], smtp["smtp_port"])
            else:
                server = smtplib.SMTP(smtp["smtp_host"], smtp["smtp_port"])
                if smtp["encryption"] == "tls":
                    server.starttls()

            if smtp["smtp_user"] and smtp["smtp_password_encrypted"]:
                server.login(smtp["smtp_user"], smtp["smtp_password_encrypted"])

            server.sendmail(smtp["from_email"], recipient, msg.as_string())
            server.quit()

            # Update log
            cur.execute(
                """
                UPDATE email_logs
                SET status = 'sent', sent_at = NOW()
                WHERE id = %s
            """,
                (log_id,),
            )
            conn.commit()

            cur.close()
            conn.close()

            return jsonify(
                {
                    "success": True,
                    "message": f"Email sent to {recipient}",
                    "log_id": log_id,
                }
            )

        except Exception as e:
            # Log the error
            cur.execute(
                """
                UPDATE email_logs
                SET status = 'failed', error_message = %s
                WHERE id = %s
            """,
                (str(e), log_id),
            )
            conn.commit()
            cur.close()
            conn.close()

            return (
                jsonify({"success": False, "error": f"Failed to send: {str(e)}"}),
                500,
            )

    except Exception as e:
        current_app.logger.error(f"[EmailManager] Send error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/send-bulk", methods=["POST"])
@login_required
def send_bulk():
    """Queue bulk emails"""
    try:
        data = request.get_json()

        template_id = data.get("template_id")
        recipients = data.get("recipients", [])  # List of {email, variables}
        scheduled_for = data.get("scheduled_for")

        if not template_id:
            return jsonify({"success": False, "error": "Template ID is required"}), 400

        if not recipients:
            return jsonify({"success": False, "error": "Recipients are required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get template
        cur.execute("SELECT * FROM email_templates WHERE id = %s", (template_id,))
        template = cur.fetchone()

        if not template:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Template not found"}), 404

        # Queue emails
        queued = 0
        for recipient in recipients:
            email = recipient.get("email") if isinstance(recipient, dict) else recipient
            vars_data = recipient.get("variables", {}) if isinstance(recipient, dict) else {}

            cur.execute(
                """
                INSERT INTO email_queue
                (template_id, recipient, subject, body_html, variables, scheduled_for, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    template_id,
                    email,
                    template["subject"],
                    template["body_html"],
                    json.dumps(vars_data),
                    scheduled_for,
                    current_user.id,
                ),
            )
            queued += 1

        conn.commit()

        return jsonify(
            {
                "success": True,
                "queued": queued,
                "message": f"{queued} emails queued for sending",
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
# EMAIL LOGS
# ============================================================================


@email_manager_bp.route("/api/logs", methods=["GET"])
@login_required
def get_logs():
    """Get email logs"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        status = request.args.get("status", "")
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        offset = (page - 1) * per_page

        where_clauses = ["created_by = %s"]
        params = [current_user.id]

        if status:
            where_clauses.append("status = %s")
            params.append(status)

        where_sql = " AND ".join(where_clauses)

        # Get total count
        cur.execute(f"SELECT COUNT(*) FROM email_logs WHERE {where_sql}", params)
        total = cur.fetchone()["count"]

        # Get logs
        cur.execute(
            f"""
            SELECT l.*, t.name as template_name
            FROM email_logs l
            LEFT JOIN email_templates t ON l.template_id = t.id
            WHERE {where_sql}
            ORDER BY l.created_at DESC
            LIMIT %s OFFSET %s
        """,
            params + [per_page, offset],
        )
        logs = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "logs": [dict(l) for l in logs],
                "total": total,
                "page": page,
                "pages": (total + per_page - 1) // per_page,
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
# CAMPAIGNS
# ============================================================================


@email_manager_bp.route("/api/campaigns", methods=["GET"])
@login_required
def get_campaigns():
    """Get email campaigns"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT c.*, t.name as template_name, s.name as segment_name
            FROM email_campaigns c
            LEFT JOIN email_templates t ON c.template_id = t.id
            LEFT JOIN crm_segments s ON c.segment_id = s.id
            WHERE c.created_by = %s
            ORDER BY c.created_at DESC
        """,
            (current_user.id,),
        )
        campaigns = cur.fetchall()

        return jsonify({"success": True, "campaigns": [dict(c) for c in campaigns]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/campaigns", methods=["POST"])
@login_required
def create_campaign():
    """Create email campaign"""
    try:
        data = request.get_json()

        if not data.get("name") or not data.get("template_id"):
            return (
                jsonify({"success": False, "error": "Name and template are required"}),
                400,
            )

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO email_campaigns
            (name, template_id, segment_id, scheduled_for, created_by)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                data["name"],
                data["template_id"],
                data.get("segment_id"),
                data.get("scheduled_for"),
                current_user.id,
            ),
        )
        campaign = cur.fetchone()

        conn.commit()

        return jsonify({"success": True, "campaign": dict(campaign), "message": "Campaign created"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/campaigns/<int:campaign_id>/send", methods=["POST"])
@login_required
def send_campaign(campaign_id):
    """Start sending a campaign"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get campaign
        cur.execute("SELECT * FROM email_campaigns WHERE id = %s", (campaign_id,))
        campaign = cur.fetchone()

        if not campaign:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Campaign not found"}), 404

        if campaign["status"] not in ["draft", "scheduled"]:
            return jsonify({"success": False, "error": "Campaign cannot be sent"}), 400

        # Get segment customers
        if campaign["segment_id"]:
            cur.execute(
                """
                SELECT c.email, c.first_name, c.last_name
                FROM crm_customers c
                JOIN crm_segment_members sm ON c.id = sm.customer_id
                WHERE sm.segment_id = %s AND c.is_active = true
            """,
                (campaign["segment_id"],),
            )
        else:
            cur.execute(
                """
                SELECT email, first_name, last_name
                FROM crm_customers
                WHERE is_active = true
            """
            )
        customers = cur.fetchall()

        # Get template
        cur.execute("SELECT * FROM email_templates WHERE id = %s", (campaign["template_id"],))
        template = cur.fetchone()

        # Queue emails for each customer
        for customer in customers:
            variables = {
                "first_name": customer["first_name"] or "",
                "last_name": customer["last_name"] or "",
                "email": customer["email"],
            }

            cur.execute(
                """
                INSERT INTO email_queue
                (template_id, recipient, subject, body_html, variables, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    campaign["template_id"],
                    customer["email"],
                    template["subject"],
                    template["body_html"],
                    json.dumps(variables),
                    current_user.id,
                ),
            )

        # Update campaign status
        cur.execute(
            """
            UPDATE email_campaigns
            SET status = 'sending', total_recipients = %s, started_at = NOW()
            WHERE id = %s
        """,
            (len(customers), campaign_id),
        )

        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": f"Campaign started - {len(customers)} emails queued",
                "recipients": len(customers),
            }
        )
    except Exception as e:
        current_app.logger.error(f"[EmailManager] Campaign send error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# STATS & ANALYTICS
# ============================================================================


@email_manager_bp.route("/api/stats", methods=["GET"])
@login_required
def get_stats():
    """Get email statistics"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Overall stats (last 30 days, per user)
        cur.execute(
            """
            SELECT
                COUNT(*) as total_sent,
                COUNT(*) FILTER (WHERE status = 'sent') as delivered,
                COUNT(*) FILTER (WHERE status = 'opened') as opened,
                COUNT(*) FILTER (WHERE status = 'clicked') as clicked,
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                COUNT(*) FILTER (WHERE status = 'bounced') as bounced
            FROM email_logs
            WHERE created_at > NOW() - INTERVAL '30 days' AND created_by = %s
        """,
            (current_user.id,),
        )
        stats = cur.fetchone()

        # Daily trend
        cur.execute(
            """
            SELECT DATE(created_at) as date,
                   COUNT(*) as sent,
                   COUNT(*) FILTER (WHERE status = 'opened') as opened
            FROM email_logs
            WHERE created_at > NOW() - INTERVAL '30 days' AND created_by = %s
            GROUP BY DATE(created_at)
            ORDER BY date
        """,
            (current_user.id,),
        )
        daily_trend = cur.fetchall()

        # Template usage
        cur.execute(
            """
            SELECT t.name, COUNT(l.id) as send_count
            FROM email_templates t
            LEFT JOIN email_logs l ON t.id = l.template_id AND l.created_by = %s
            WHERE l.created_at > NOW() - INTERVAL '30 days' OR l.id IS NULL
            GROUP BY t.id, t.name
            ORDER BY send_count DESC
            LIMIT 10
        """,
            (current_user.id,),
        )
        template_usage = cur.fetchall()

        # Calculate rates
        total = stats["total_sent"] or 1
        stats["delivery_rate"] = round((stats["delivered"] / total) * 100, 1)
        stats["open_rate"] = round((stats["opened"] / total) * 100, 1)
        stats["click_rate"] = round((stats["clicked"] / total) * 100, 1)

        return jsonify(
            {
                "success": True,
                "stats": dict(stats),
                "daily_trend": [dict(d) for d in daily_trend],
                "template_usage": [dict(t) for t in template_usage],
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
# TRACKING ENDPOINTS
# ============================================================================


@email_manager_bp.route("/track/open/<int:log_id>")
def track_open(log_id):
    """Track email open (1x1 pixel)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE email_logs
            SET status = 'opened', opened_at = NOW()
            WHERE id = %s AND opened_at IS NULL
        """,
            (log_id,),
        )

        conn.commit()

    except Exception:
        pass

    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
    # Return 1x1 transparent GIF
    gif = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    return gif, 200, {"Content-Type": "image/gif"}


@email_manager_bp.route("/track/click/<int:log_id>")
def track_click(log_id):
    """Track email link click"""
    try:
        url = request.args.get("url", "/")

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE email_logs
            SET status = 'clicked', clicked_at = NOW()
            WHERE id = %s AND clicked_at IS NULL
        """,
            (log_id,),
        )

        conn.commit()

        return "", 302, {"Location": url}

    except Exception:
        return "", 302, {"Location": "/"}
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# STATUS ENDPOINT
# ============================================================================


@email_manager_bp.route("/api/status")
def status():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT COUNT(*) FROM email_templates WHERE is_active = true")
        template_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) FROM email_logs WHERE created_at > NOW() - INTERVAL '24 hours'")
        recent_emails = cur.fetchone()["count"]

        cur.execute("SELECT test_result FROM email_settings WHERE is_default = true AND is_active = true")
        smtp_status = cur.fetchone()

        return jsonify(
            {
                "module": "email_manager",
                "status": "healthy",
                "healthy": True,
                "templates": template_count,
                "recent_emails": recent_emails,
                "smtp_configured": smtp_status is not None,
                "smtp_tested": (smtp_status["test_result"] == "success" if smtp_status else False),
                "message": f"Email Manager operational with {template_count} templates",
            }
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "module": "email_manager",
                    "status": "error",
                    "healthy": False,
                    "message": str(e),
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
