"""
Email Intelligence IMAP Routes — Inbox, Settings, Analysis, Drafts

Registered on the existing email_manager_bp blueprint.

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

from .routes import email_manager_bp

logger = logging.getLogger("email_imap")

# Add ai_bridge to path for EmailIntelligence
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
# IMAP Settings
# ============================================================================


@email_manager_bp.route("/api/imap/settings", methods=["GET"])
@login_required
def get_imap_settings():
    """Get all IMAP settings."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, name, imap_host, imap_port, imap_user, encryption, folder,
                   is_active, last_uid, last_check_at, check_interval_minutes,
                   auto_analyze, auto_file_kb, created_at
            FROM email_imap_settings
            ORDER BY id
            """
        )
        settings = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify({"success": True, "settings": settings})
    except Exception as e:
        logger.error(f"Failed to get IMAP settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@email_manager_bp.route("/api/imap/settings", methods=["POST"])
@login_required
def create_imap_setting():
    """Create a new IMAP setting."""
    try:
        data = request.json
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            INSERT INTO email_imap_settings
            (name, imap_host, imap_port, imap_user, imap_password_encrypted,
             encryption, folder, check_interval_minutes, auto_analyze, auto_file_kb)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                data.get("name", "Default"),
                data["imap_host"],
                data.get("imap_port", 993),
                data["imap_user"],
                data["imap_password"],
                data.get("encryption", "ssl"),
                data.get("folder", "INBOX"),
                data.get("check_interval_minutes", 5),
                data.get("auto_analyze", True),
                data.get("auto_file_kb", False),
            ),
        )
        setting_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "id": setting_id})
    except Exception as e:
        logger.error(f"Failed to create IMAP setting: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@email_manager_bp.route("/api/imap/settings/<int:setting_id>", methods=["PUT"])
@login_required
def update_imap_setting(setting_id):
    """Update an IMAP setting."""
    try:
        data = request.json
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        updates = []
        params = []
        for field in [
            "name",
            "imap_host",
            "imap_port",
            "imap_user",
            "encryption",
            "folder",
            "is_active",
            "check_interval_minutes",
            "auto_analyze",
            "auto_file_kb",
        ]:
            if field in data:
                updates.append(f"{field} = %s")
                params.append(data[field])

        if "imap_password" in data and data["imap_password"]:
            updates.append("imap_password_encrypted = %s")
            params.append(data["imap_password"])

        if not updates:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        updates.append("updated_at = NOW()")
        params.append(setting_id)

        cur.execute(
            f"UPDATE email_imap_settings SET {', '.join(updates)} WHERE id = %s RETURNING id",
            params,
        )
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not result:
            return jsonify({"success": False, "error": "Setting not found"}), 404
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Failed to update IMAP setting: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@email_manager_bp.route("/api/imap/settings/<int:setting_id>/test", methods=["POST"])
@login_required
def test_imap_setting(setting_id):
    """Test IMAP connection."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM email_imap_settings WHERE id = %s", (setting_id,))
        setting = cur.fetchone()
        cur.close()
        conn.close()

        if not setting:
            return jsonify({"success": False, "error": "Setting not found"}), 404

        import imaplib

        encryption = setting.get("encryption", "ssl")
        if encryption == "ssl":
            mailbox = imaplib.IMAP4_SSL(setting["imap_host"], setting["imap_port"], timeout=15)
        else:
            mailbox = imaplib.IMAP4(setting["imap_host"], setting["imap_port"], timeout=15)
            if encryption == "tls":
                mailbox.starttls()

        mailbox.login(setting["imap_user"], setting["imap_password_encrypted"])
        status, data = mailbox.select(setting.get("folder", "INBOX"), readonly=True)
        message_count = int(data[0]) if status == "OK" else 0
        mailbox.close()
        mailbox.logout()

        return jsonify(
            {
                "success": True,
                "message": f"Connection successful. {message_count} messages in {setting.get('folder', 'INBOX')}.",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": f"Connection failed: {str(e)}"}), 400


# ============================================================================
# Inbox
# ============================================================================


@email_manager_bp.route("/api/inbox", methods=["GET"])
@login_required
def get_inbox():
    """Get inbox emails with filtering and pagination."""
    try:
        page = int(request.args.get("page", 1))
        per_page = min(int(request.args.get("per_page", 25)), 100)
        category = request.args.get("category")
        is_read = request.args.get("is_read")
        is_starred = request.args.get("is_starred")
        search = request.args.get("search")
        offset = (page - 1) * per_page

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        where = ["is_archived = FALSE"]
        params = []

        if category:
            where.append("ai_category = %s")
            params.append(category)
        if is_read is not None:
            where.append("is_read = %s")
            params.append(is_read.lower() == "true")
        if is_starred is not None:
            where.append("is_starred = %s")
            params.append(is_starred.lower() == "true")
        if search:
            where.append("(subject ILIKE %s OR from_address ILIKE %s OR from_name ILIKE %s)")
            params.extend([f"%{search}%"] * 3)

        where_clause = " AND ".join(where) if where else "TRUE"

        # Count
        cur.execute(f"SELECT COUNT(*) as total FROM email_inbox WHERE {where_clause}", params)
        total = cur.fetchone()["total"]

        # Fetch
        cur.execute(
            f"""
            SELECT id, from_address, from_name, subject, received_at,
                   has_attachments, ai_category, ai_summary, ai_priority, ai_sentiment,
                   is_read, is_starred, crm_customer_id, kb_entry_id, created_at
            FROM email_inbox
            WHERE {where_clause}
            ORDER BY received_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [per_page, offset],
        )
        emails = [dict(r) for r in cur.fetchall()]

        # Category counts
        cur.execute(
            """
            SELECT ai_category, COUNT(*) as count
            FROM email_inbox WHERE is_archived = FALSE
            GROUP BY ai_category
            """
        )
        categories = {r["ai_category"]: r["count"] for r in cur.fetchall() if r["ai_category"]}

        # Unread count
        cur.execute("SELECT COUNT(*) as c FROM email_inbox WHERE is_read = FALSE AND is_archived = FALSE")
        unread = cur.fetchone()["c"]

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "emails": emails,
                "total": total,
                "page": page,
                "per_page": per_page,
                "categories": categories,
                "unread": unread,
            }
        )
    except Exception as e:
        logger.error(f"Failed to get inbox: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@email_manager_bp.route("/api/inbox/<int:email_id>", methods=["GET"])
@login_required
def get_email_detail(email_id):
    """Get full email details."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM email_inbox WHERE id = %s", (email_id,))
        email_row = cur.fetchone()

        if not email_row:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Email not found"}), 404

        # Mark as read
        if not email_row["is_read"]:
            cur.execute("UPDATE email_inbox SET is_read = TRUE WHERE id = %s", (email_id,))
            conn.commit()

        # Get drafts
        cur.execute(
            "SELECT * FROM email_drafts WHERE inbox_email_id = %s ORDER BY created_at DESC",
            (email_id,),
        )
        drafts = [dict(r) for r in cur.fetchall()]

        cur.close()
        conn.close()

        result = dict(email_row)
        result["drafts"] = drafts
        return jsonify({"success": True, "email": result})
    except Exception as e:
        logger.error(f"Failed to get email detail: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@email_manager_bp.route("/api/inbox/<int:email_id>/star", methods=["POST"])
@login_required
def toggle_star(email_id):
    """Toggle star on an email."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "UPDATE email_inbox SET is_starred = NOT is_starred WHERE id = %s RETURNING is_starred",
            (email_id,),
        )
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "is_starred": result["is_starred"] if result else False})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@email_manager_bp.route("/api/inbox/<int:email_id>/archive", methods=["POST"])
@login_required
def archive_email(email_id):
    """Archive an email."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE email_inbox SET is_archived = TRUE WHERE id = %s", (email_id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
        instructions = request.json.get("instructions", "") if request.json else ""
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
            return jsonify({"success": True, "draft_id": draft_id, "draft": dict(draft) if draft else None})
        return jsonify({"success": False, "error": "Draft generation failed"}), 500
    except Exception as e:
        logger.error(f"Draft generation failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


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
        setting_id = request.get_json(silent=True, force=True) or {}
        setting_id = setting_id.get("setting_id")
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
            WHERE d.status = %s
            ORDER BY d.created_at DESC
            LIMIT 50
            """,
            (status_filter,),
        )
        drafts = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify({"success": True, "drafts": drafts})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@email_manager_bp.route("/api/drafts/<int:draft_id>", methods=["PUT"])
@login_required
def update_draft(draft_id):
    """Update a draft (edit body, subject)."""
    try:
        data = request.json
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        updates = []
        params = []
        for field in ["subject", "body_html", "body_text", "to_address"]:
            if field in data:
                updates.append(f"{field} = %s")
                params.append(data[field])

        if updates:
            updates.append("edited_by = %s")
            params.append(current_user.id)
            updates.append("updated_at = NOW()")
            params.append(draft_id)
            cur.execute(
                f"UPDATE email_drafts SET {', '.join(updates)} WHERE id = %s RETURNING id",
                params,
            )

        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@email_manager_bp.route("/api/drafts/<int:draft_id>/send", methods=["POST"])
@login_required
def send_draft(draft_id):
    """Queue a draft for sending (goes through approval for tier 2)."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM email_drafts WHERE id = %s AND status = 'draft'", (draft_id,))
        draft = cur.fetchone()

        if not draft:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Draft not found"}), 404

        # Submit to approval queue
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
        cur.close()
        conn.close()

        return jsonify({"success": True, "approval_id": approval_id, "message": "Draft queued for approval"})
    except Exception as e:
        logger.error(f"Draft send failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
