"""
Email Manager Routes — Send, Logs & Campaigns
=============================================
Single/bulk email sending, log viewing, and campaign management.

Registered on the existing email_manager_bp blueprint.

Author: A.R.C.H.I.E. Platform
Date: 2026-01-17
"""

import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app, jsonify, request
from psycopg2.extras import RealDictCursor
from flask_login import current_user, login_required

from .access_control import email_access_required
from .routes import (
    email_manager_bp,
    get_db_connection,
    get_smtp_for_sending,
    render_template_vars,
)


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
@email_access_required
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
        cur.execute("SELECT COUNT(*) FROM email_logs WHERE " + where_sql, params)
        total = cur.fetchone()["count"]

        # Get logs
        cur.execute(
            """
            SELECT l.*, t.name as template_name
            FROM email_logs l
            LEFT JOIN email_templates t ON l.template_id = t.id
            WHERE """
            + where_sql
            + """
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
