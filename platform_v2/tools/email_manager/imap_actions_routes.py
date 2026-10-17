"""
Email Intelligence IMAP Action Routes — analysis, drafts, send.

Registered on the existing email_manager_bp blueprint.

Split out of imap_routes.py; see imap_routes for the compatibility re-exports.

Author: A.R.C.H.I.E. Platform
Created: 2026-02-17
"""

import logging
import sys

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import jsonify, request
from flask_login import current_user, login_required

from .routes import email_manager_bp
from .imap_settings_routes import get_db

logger = logging.getLogger("email_imap")

# Add ai_bridge to path for EmailIntelligence
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")


# ============================================================================
# AI Analysis
# ============================================================================


@email_manager_bp.route("/api/inbox/<int:email_id>/analyze", methods=["POST"])
@login_required
def analyze_email(email_id):
    """Run AI analysis on a single email."""
    try:
        from email_intelligence import EmailIntelligence

        ei = EmailIntelligence()
        result = ei.analyze_email(email_id)
        return jsonify({"success": True, "analysis": result})
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@email_manager_bp.route("/api/inbox/<int:email_id>/draft", methods=["POST"])
@login_required
def generate_draft(email_id):
    """Generate an AI draft reply."""
    try:
        from email_intelligence import EmailIntelligence

        ei = EmailIntelligence()
        instructions = (request.get_json() or {}).get("instructions", "") if request.json else ""
        draft_id = ei.generate_draft_reply(email_id, instructions)
        if draft_id:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT id, to_address, subject, body_html, body_text, status FROM email_drafts WHERE id = %s",
                (draft_id,),
            )
            draft = cur.fetchone()
            cur.close()
            conn.close()
            return jsonify(
                {
                    "success": True,
                    "draft_id": draft_id,
                    "draft": dict(draft) if draft else None,
                }
            )
        return jsonify({"success": False, "error": "Draft generation failed"}), 500
    except Exception as e:
        logger.error(f"Draft generation failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/inbox/<int:email_id>/file-to-kb", methods=["POST"])
@login_required
def file_to_kb(email_id):
    """File an email to the knowledge base."""
    try:
        from email_intelligence import EmailIntelligence

        ei = EmailIntelligence()
        kb_id = ei.file_to_knowledge_base(email_id)
        if kb_id:
            return jsonify({"success": True, "kb_entry_id": kb_id})
        return jsonify({"success": False, "error": "Filing failed"}), 500
    except Exception as e:
        logger.error(f"KB filing failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@email_manager_bp.route("/api/inbox/check", methods=["POST"])
@login_required
def check_inbox_now():
    """Manually trigger inbox check."""
    try:
        from email_intelligence import EmailIntelligence

        ei = EmailIntelligence()
        data = request.get_json(silent=True, force=True) or {}
        setting_id = data.get("setting_id")

        # If specific setting requested, verify ownership
        if setting_id:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT id FROM email_imap_settings WHERE id = %s AND user_id = %s",
                (setting_id, current_user.id),
            )
            if not cur.fetchone():
                cur.close()
                conn.close()
                return jsonify({"success": False, "error": "Setting not found"}), 404
            cur.close()
            conn.close()

        result = ei.check_inbox(setting_id)
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"Inbox check failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Drafts
# ============================================================================


@email_manager_bp.route("/api/drafts", methods=["GET"])
@login_required
def get_drafts():
    """Get all drafts."""
    try:
        status_filter = request.args.get("status", "draft")
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT d.*, e.from_address, e.subject as original_subject
            FROM email_drafts d
            LEFT JOIN email_inbox e ON d.inbox_email_id = e.id
            LEFT JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE d.status = %s AND (eis.user_id = %s OR d.inbox_email_id IS NULL)
            ORDER BY d.created_at DESC
            LIMIT 50
            """,
            (status_filter, current_user.id),
        )
        drafts = [dict(r) for r in cur.fetchall()]
        return jsonify({"success": True, "drafts": drafts})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/drafts/<int:draft_id>", methods=["PUT"])
@login_required
def update_draft(draft_id):
    """Update a draft (edit body, subject)."""
    try:
        data = request.get_json() or {}
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        updates = []
        params = []
        for field in ["subject", "body_html", "body_text", "to_address"]:
            if field in data:
                updates.append(field + " = %s")
                params.append(data[field])

        if updates:
            updates.append("edited_by = %s")
            params.append(current_user.id)
            updates.append("updated_at = NOW()")
            params.append(draft_id)
            cur.execute(
                "UPDATE email_drafts SET " + ", ".join(updates) + " WHERE id = %s RETURNING id",
                params,
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


@email_manager_bp.route("/api/drafts/<int:draft_id>/send", methods=["POST"])
@login_required
def send_draft(draft_id):
    """Send a draft directly via SMTP or queue for approval."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM email_drafts WHERE id = %s AND status = 'draft'", (draft_id,))
        draft = cur.fetchone()
        if not draft:
            return (
                jsonify({"success": False, "error": "Draft not found or already sent"}),
                404,
            )

        # Get SMTP settings — prefer the account that received the original email
        account_id = None
        if draft.get("inbox_email_id"):
            cur.execute(
                "SELECT imap_setting_id FROM email_inbox WHERE id = %s",
                (draft["inbox_email_id"],),
            )
            inbox_row = cur.fetchone()
            if inbox_row:
                account_id = inbox_row.get("imap_setting_id")

        # Try per-account SMTP, fallback to legacy
        smtp = None
        if account_id:
            cur.execute(
                """SELECT smtp_host, smtp_port, smtp_user, smtp_password,
                          smtp_encryption AS encryption, from_email, from_name, reply_to
                   FROM email_imap_settings
                   WHERE id = %s AND smtp_host IS NOT NULL""",
                (account_id,),
            )
            smtp = cur.fetchone()

        if not smtp:
            cur.execute("SELECT * FROM email_settings WHERE is_default = TRUE AND is_active = TRUE LIMIT 1")
            smtp = cur.fetchone()

        if not smtp:
            return (
                jsonify({"success": False, "error": "No SMTP configured"}),
                400,
            )

        direct = False
        if request.is_json:
            direct = (request.get_json() or {}).get("direct", False)

        if direct:
            # Direct send via SMTP
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            msg = MIMEMultipart("alternative")
            msg["From"] = f"{smtp['from_name']} <{smtp['from_email']}>"
            msg["To"] = draft["to_address"]
            msg["Subject"] = draft["subject"]
            if draft.get("body_text"):
                msg.attach(MIMEText(draft["body_text"], "plain"))
            if draft.get("body_html"):
                msg.attach(MIMEText(draft["body_html"], "html"))

            # Add In-Reply-To header if replying
            if draft.get("inbox_email_id"):
                cur.execute(
                    "SELECT message_id FROM email_inbox WHERE id = %s",
                    (draft["inbox_email_id"],),
                )
                orig = cur.fetchone()
                if orig and orig.get("message_id"):
                    msg["In-Reply-To"] = orig["message_id"]
                    msg["References"] = orig["message_id"]

            if smtp["encryption"] == "ssl":
                server = smtplib.SMTP_SSL(smtp["smtp_host"], smtp["smtp_port"])
            else:
                server = smtplib.SMTP(smtp["smtp_host"], smtp["smtp_port"])
                if smtp["encryption"] == "tls":
                    server.starttls()
            try:
                server.login(smtp["smtp_user"], smtp["smtp_password"])
                server.send_message(msg)
            finally:
                server.quit()

            cur.execute(
                "UPDATE email_drafts SET status = 'sent', updated_at = NOW() WHERE id = %s",
                (draft_id,),
            )

            # Log the send
            cur.execute(
                """
                INSERT INTO email_logs (recipient, subject, body_preview, status, sent_at, created_by, created_at)
                VALUES (%s, %s, %s, 'sent', NOW(), %s, NOW())
            """,
                (
                    draft["to_address"],
                    draft["subject"],
                    (draft.get("body_text") or "")[:200],
                    current_user.id,
                ),
            )

            conn.commit()
            return jsonify(
                {
                    "success": True,
                    "message": "Email sent successfully",
                    "method": "direct",
                }
            )
        else:
            # Approval flow
            from agent_loop import request_approval

            approval_id = request_approval(
                action_type="send_email",
                action_data={
                    "recipient": draft["to_address"],
                    "subject": draft["subject"],
                    "body_html": draft["body_html"] or draft["body_text"],
                    "draft_id": draft_id,
                },
                reason=f"Send email reply to {draft['to_address']}: {draft['subject']}",
                requested_by="email_intelligence",
                tier=2,
            )

            cur.execute(
                "UPDATE email_drafts SET status = 'queued', approval_id = %s, updated_at = NOW() WHERE id = %s",
                (approval_id, draft_id),
            )
            conn.commit()
            return jsonify(
                {
                    "success": True,
                    "message": "Queued for approval",
                    "approval_id": approval_id,
                    "method": "approval",
                }
            )
    except Exception as e:
        conn.rollback()
        logger.error(f"Send draft failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()
