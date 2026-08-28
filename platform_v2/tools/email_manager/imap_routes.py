"""
Email Intelligence IMAP Routes — Inbox, Settings, Analysis, Drafts

Registered on the existing email_manager_bp blueprint.

Author: A.R.C.H.I.E. Platform
Created: 2026-02-17
"""

import logging
import os
from database import _get_db_password
import sys
import time

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import jsonify, request
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
        password=_get_db_password(),
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
                   auto_analyze, auto_file_kb, created_at,
                   smtp_host, smtp_port, smtp_user, smtp_encryption,
                   from_email, from_name, reply_to,
                   smtp_test_result, smtp_test_message, smtp_tested_at
            FROM email_imap_settings
            WHERE user_id = %s
            ORDER BY id
            """,
            (current_user.id,),
        )
        settings = [dict(r) for r in cur.fetchall()]
        return jsonify({"success": True, "settings": settings})
    except Exception as e:
        logger.error(f"Failed to get IMAP settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/imap/settings", methods=["POST"])
@login_required
def create_imap_setting():
    """Create a new IMAP setting."""
    try:
        data = request.get_json() or {}
        if not data:
            return jsonify({"success": False, "error": "Request body required"}), 400

        # Validate required fields
        missing = [f for f in ("imap_host", "imap_user", "imap_password") if not data.get(f)]
        if missing:
            return jsonify({"success": False, "error": f"Missing required fields: {', '.join(missing)}"}), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            INSERT INTO email_imap_settings
            (name, imap_host, imap_port, imap_user, imap_password,
             encryption, folder, check_interval_minutes, auto_analyze, auto_file_kb,
             smtp_host, smtp_port, smtp_user, smtp_password,
             smtp_encryption, from_email, from_name, reply_to, user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                data.get("smtp_host"),
                data.get("smtp_port"),
                data.get("smtp_user"),
                data.get("smtp_password"),
                data.get("smtp_encryption"),
                data.get("from_email"),
                data.get("from_name"),
                data.get("reply_to"),
                current_user.id,
            ),
        )
        setting_id = cur.fetchone()["id"]
        conn.commit()
        return jsonify({"success": True, "id": setting_id})
    except Exception as e:
        logger.error(f"Failed to create IMAP setting: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/imap/settings/<int:setting_id>", methods=["PUT"])
@login_required
def update_imap_setting(setting_id):
    """Update an IMAP setting."""
    try:
        data = request.get_json() or {}
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
            "smtp_host",
            "smtp_port",
            "smtp_user",
            "smtp_encryption",
            "from_email",
            "from_name",
            "reply_to",
        ]:
            if field in data:
                updates.append(f"{field} = %s")
                params.append(data[field])

        if "imap_password" in data and data["imap_password"]:
            updates.append("imap_password = %s")
            params.append(data["imap_password"])

        if "smtp_password" in data and data["smtp_password"]:
            updates.append("smtp_password = %s")
            params.append(data["smtp_password"])

        if not updates:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        updates.append("updated_at = NOW()")
        params.extend([setting_id, current_user.id])

        cur.execute(
            f"UPDATE email_imap_settings SET {', '.join(updates)} WHERE id = %s AND user_id = %s RETURNING id",
            params,
        )
        result = cur.fetchone()
        conn.commit()

        if not result:
            return jsonify({"success": False, "error": "Setting not found"}), 404
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Failed to update IMAP setting: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/imap/settings/<int:setting_id>", methods=["DELETE"])
@login_required
def delete_imap_setting(setting_id):
    """Delete an IMAP setting (only if no emails reference it)."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership first
        cur.execute(
            "SELECT id FROM email_imap_settings WHERE id = %s AND user_id = %s",
            (setting_id, current_user.id),
        )
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Setting not found"}), 404

        # Check for dependent emails
        cur.execute(
            "SELECT COUNT(*) as cnt FROM email_inbox WHERE imap_setting_id = %s",
            (setting_id,),
        )
        count = cur.fetchone()["cnt"]
        if count > 0:
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Cannot delete: {count} emails reference this mailbox. Remove emails first.",
                    }
                ),
                409,
            )

        cur.execute(
            "DELETE FROM email_imap_settings WHERE id = %s AND user_id = %s RETURNING id",
            (setting_id, current_user.id),
        )
        result = cur.fetchone()
        conn.commit()

        if not result:
            return jsonify({"success": False, "error": "Setting not found"}), 404
        return jsonify({"success": True, "message": "IMAP setting deleted"})
    except Exception as e:
        logger.error(f"Failed to delete IMAP setting: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/imap/settings/<int:setting_id>/test", methods=["POST"])
@login_required
def test_imap_setting(setting_id):
    """Test IMAP connection."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT * FROM email_imap_settings WHERE id = %s AND user_id = %s",
            (setting_id, current_user.id),
        )
        setting = cur.fetchone()

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

        mailbox.login(setting["imap_user"], setting["imap_password"])
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
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/imap/settings/<int:setting_id>/test-smtp", methods=["POST"])
@login_required
def test_smtp_setting(setting_id):
    """Test SMTP connection for an IMAP account."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT smtp_host, smtp_port, smtp_user, smtp_password,
                      smtp_encryption, from_email
               FROM email_imap_settings WHERE id = %s AND user_id = %s""",
            (setting_id, current_user.id),
        )
        setting = cur.fetchone()

        if not setting:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Setting not found"}), 404

        if not setting.get("smtp_host"):
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "No SMTP host configured for this account",
                    }
                ),
                400,
            )

        import smtplib

        test_result = "failed"
        test_message = ""

        try:
            encryption = setting.get("smtp_encryption", "tls")
            if encryption == "ssl":
                server = smtplib.SMTP_SSL(setting["smtp_host"], setting["smtp_port"], timeout=10)
            else:
                server = smtplib.SMTP(setting["smtp_host"], setting["smtp_port"], timeout=10)
                if encryption == "tls":
                    server.starttls()

            if setting.get("smtp_user") and setting.get("smtp_password"):
                server.login(setting["smtp_user"], setting["smtp_password"])

            server.quit()
            test_result = "success"
            test_message = "SMTP connection successful"

        except smtplib.SMTPAuthenticationError:
            test_message = "Authentication failed - check username and password"
        except smtplib.SMTPConnectError:
            test_message = "Could not connect to SMTP server"
        except Exception as e:
            test_message = f"Connection error: {str(e)}"

        # Update test result columns
        cur.execute(
            """UPDATE email_imap_settings
               SET smtp_test_result = %s, smtp_test_message = %s, smtp_tested_at = NOW()
               WHERE id = %s AND user_id = %s""",
            (test_result, test_message, setting_id, current_user.id),
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
        logger.error(f"SMTP test failed for setting {setting_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/smtp-accounts", methods=["GET"])
@login_required
def get_smtp_accounts():
    """Get IMAP accounts that have SMTP configured (for From dropdown)."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, name, from_email, from_name, smtp_test_result
            FROM email_imap_settings
            WHERE is_active = true AND smtp_host IS NOT NULL AND from_email IS NOT NULL
              AND user_id = %s
            ORDER BY id
            """,
            (current_user.id,),
        )
        accounts = [dict(r) for r in cur.fetchall()]
        return jsonify({"success": True, "accounts": accounts})
    except Exception as e:
        logger.error(f"Failed to get SMTP accounts: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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
        sort = request.args.get("sort", "date_desc")
        offset = (page - 1) * per_page

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        where = [
            "e.is_archived = FALSE",
            "eis.user_id = %s",
        ]
        params = [current_user.id]

        if category:
            where.append("e.ai_category = %s")
            params.append(category)
        if is_read is not None:
            where.append("e.is_read = %s")
            params.append(is_read.lower() == "true")
        if is_starred is not None:
            where.append("e.is_starred = %s")
            params.append(is_starred.lower() == "true")
        account = request.args.get("account")
        if account:
            where.append("e.imap_setting_id = %s")
            params.append(int(account))
        if search:
            where.append("(e.subject ILIKE %s OR e.from_address ILIKE %s OR e.from_name ILIKE %s)")
            params.extend([f"%{search}%"] * 3)

        where_clause = " AND ".join(where) if where else "TRUE"

        sort_map = {
            "date_desc": "e.received_at DESC",
            "date_asc": "e.received_at ASC",
            "priority_asc": "COALESCE(e.ai_priority, 99) ASC, e.received_at DESC",
            "unread_first": "e.is_read ASC, e.received_at DESC",
            "sentiment": "CASE e.ai_sentiment WHEN 'negative' THEN 1 WHEN 'mixed' THEN 2 WHEN 'neutral' THEN 3 WHEN 'positive' THEN 4 ELSE 5 END, e.received_at DESC",
        }
        order_clause = sort_map.get(sort, "e.received_at DESC")

        # Count
        cur.execute(
            f"""SELECT COUNT(*) as total
            FROM email_inbox e
            JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE {where_clause}""",
            params,
        )
        total = cur.fetchone()["total"]

        # Fetch
        cur.execute(
            f"""
            SELECT e.id, e.from_address, e.from_name, e.subject, e.received_at,
                   e.has_attachments, e.ai_category, e.ai_summary, e.ai_priority, e.ai_sentiment,
                   e.is_read, e.is_starred, e.crm_customer_id, e.kb_entry_id, e.created_at,
                   eis.name as account_name
            FROM email_inbox e
            JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE {where_clause}
            ORDER BY {order_clause}
            LIMIT %s OFFSET %s
            """,
            params + [per_page, offset],
        )
        emails = [dict(r) for r in cur.fetchall()]

        # Category counts (respect account filter + user ownership)
        acct_filter = " AND eis.user_id = %s"
        acct_params = [current_user.id]
        if account:
            acct_filter += " AND e.imap_setting_id = %s"
            acct_params.append(int(account))

        cur.execute(
            f"""SELECT e.ai_category, COUNT(*) as count
            FROM email_inbox e
            JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE e.is_archived = FALSE{acct_filter}
            GROUP BY e.ai_category""",
            acct_params,
        )
        categories = {r["ai_category"]: r["count"] for r in cur.fetchall() if r["ai_category"]}

        # Unread count
        cur.execute(
            f"""SELECT COUNT(*) as c FROM email_inbox e
            JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE e.is_read = FALSE AND e.is_archived = FALSE{acct_filter}""",
            acct_params,
        )
        unread = cur.fetchone()["c"]

        # Starred count
        cur.execute(
            f"""SELECT COUNT(*) as c FROM email_inbox e
            JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE e.is_starred = TRUE AND e.is_archived = FALSE{acct_filter}""",
            acct_params,
        )
        starred = cur.fetchone()["c"]

        # Account counts (only user's accounts)
        cur.execute(
            """
            SELECT eis.id, eis.name, COUNT(*) as count
            FROM email_inbox e
            JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE e.is_archived = FALSE AND eis.user_id = %s
            GROUP BY eis.id, eis.name
            ORDER BY eis.name
        """,
            (current_user.id,),
        )
        accounts = [dict(r) for r in cur.fetchall()]

        return jsonify(
            {
                "success": True,
                "emails": emails,
                "total": total,
                "page": page,
                "per_page": per_page,
                "categories": categories,
                "unread": unread,
                "starred": starred,
                "accounts": accounts,
            }
        )
    except Exception as e:
        logger.error(f"Failed to get inbox: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/inbox/stats", methods=["GET"])
@login_required
def get_inbox_stats():
    """Get inbox stats: total fetched, analyzed, unread."""
    try:
        account = request.args.get("account")
        acct_filter = ""
        acct_params = [current_user.id]
        if account:
            acct_filter = " AND e.imap_setting_id = %s"
            acct_params.append(int(account))

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            f"""
            SELECT
                COUNT(*) as total,
                COUNT(e.ai_analyzed_at) as analyzed,
                COUNT(*) FILTER (WHERE e.is_read = FALSE AND e.is_archived = FALSE) as unread,
                COUNT(*) FILTER (WHERE e.is_archived = TRUE) as archived,
                COUNT(*) FILTER (WHERE e.is_starred = TRUE AND e.is_archived = FALSE) as starred
            FROM email_inbox e
            JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE eis.user_id = %s{acct_filter}
        """,
            acct_params,
        )
        stats = dict(cur.fetchone())
        return jsonify({"success": True, **stats})
    except Exception as e:
        logger.error(f"Failed to get inbox stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/inbox/batch-analyze", methods=["POST"])
@login_required
def batch_analyze():
    """Analyze a batch of unanalyzed emails (5 at a time)."""
    try:
        from email_intelligence import EmailIntelligence

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id FROM email_inbox
            WHERE ai_analyzed_at IS NULL
            ORDER BY received_at DESC
            LIMIT 5
        """
        )
        rows = cur.fetchall()

        if not rows:
            return jsonify({"success": True, "analyzed": 0, "remaining": 0})

        ei = EmailIntelligence()
        analyzed = 0
        for row in rows:
            try:
                ei.analyze_email(row["id"])
                analyzed += 1
                time.sleep(1)  # GPU safety
            except Exception as e:
                logger.warning(f"Batch analysis failed for #{row['id']}: {e}")

        # Get remaining count
        conn2 = get_db()
        cur2 = conn2.cursor(cursor_factory=RealDictCursor)
        cur2.execute("SELECT COUNT(*) as remaining FROM email_inbox WHERE ai_analyzed_at IS NULL")
        remaining = cur2.fetchone()["remaining"]
        cur2.close()
        conn2.close()

        return jsonify({"success": True, "analyzed": analyzed, "remaining": remaining})
    except Exception as e:
        logger.error(f"Batch analysis failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/inbox/bulk", methods=["POST"])
@login_required
def bulk_action():
    """Perform bulk actions on selected emails."""
    try:
        data = request.get_json(force=True)
        ids = data.get("ids", [])
        action = data.get("action")

        if not ids or not action:
            return jsonify({"success": False, "error": "Missing ids or action"}), 400

        if len(ids) > 200:
            return (
                jsonify({"success": False, "error": "Max 200 emails per bulk action"}),
                400,
            )

        valid_actions = [
            "mark_read",
            "mark_unread",
            "archive",
            "star",
            "unstar",
            "delete",
        ]
        if action not in valid_actions:
            return (
                jsonify({"success": False, "error": f"Invalid action: {action}"}),
                400,
            )

        conn = get_db()
        cur = conn.cursor()

        placeholders = ",".join(["%s"] * len(ids))
        ownership = " AND imap_setting_id IN (SELECT id FROM email_imap_settings WHERE user_id = %s)"
        params_with_user = ids + [current_user.id]

        if action == "mark_read":
            cur.execute(
                f"UPDATE email_inbox SET is_read = TRUE WHERE id IN ({placeholders}){ownership}",
                params_with_user,
            )
        elif action == "mark_unread":
            cur.execute(
                f"UPDATE email_inbox SET is_read = FALSE WHERE id IN ({placeholders}){ownership}",
                params_with_user,
            )
        elif action == "archive":
            cur.execute(
                f"UPDATE email_inbox SET is_archived = TRUE WHERE id IN ({placeholders}){ownership}",
                params_with_user,
            )
        elif action == "star":
            cur.execute(
                f"UPDATE email_inbox SET is_starred = TRUE WHERE id IN ({placeholders}){ownership}",
                params_with_user,
            )
        elif action == "unstar":
            cur.execute(
                f"UPDATE email_inbox SET is_starred = FALSE WHERE id IN ({placeholders}){ownership}",
                params_with_user,
            )
        elif action == "delete":
            cur.execute(
                f"DELETE FROM email_inbox WHERE id IN ({placeholders}){ownership}",
                params_with_user,
            )

        affected = cur.rowcount
        conn.commit()

        return jsonify({"success": True, "affected": affected})
    except Exception as e:
        logger.error(f"Bulk action failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/inbox/<int:email_id>", methods=["GET"])
@login_required
def get_email_detail(email_id):
    """Get full email details."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT e.*, eis.name as account_name
            FROM email_inbox e
            JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE e.id = %s AND eis.user_id = %s""",
            (email_id, current_user.id),
        )
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

        result = dict(email_row)
        result["drafts"] = drafts
        return jsonify({"success": True, "email": result})
    except Exception as e:
        logger.error(f"Failed to get email detail: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/inbox/<int:email_id>/thread", methods=["GET"])
@login_required
def get_email_thread(email_id):
    """Get all emails in the same conversation thread."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Get thread_id for this email (with ownership check)
        cur.execute(
            """SELECT e.thread_id FROM email_inbox e
            JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE e.id = %s AND eis.user_id = %s""",
            (email_id, current_user.id),
        )
        row = cur.fetchone()
        if not row or not row.get("thread_id"):
            return jsonify({"success": True, "thread": [], "count": 0})

        # Get all emails in this thread (only user's emails)
        cur.execute(
            """
            SELECT e.id, e.from_address, e.from_name, e.subject, e.received_at, e.is_read, e.ai_summary,
                   LEFT(e.body_text, 200) as preview
            FROM email_inbox e
            JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE e.thread_id = %s AND eis.user_id = %s
            ORDER BY e.received_at ASC
        """,
            (row["thread_id"], current_user.id),
        )
        thread = cur.fetchall()

        # Convert timestamps for JSON serialization
        for t in thread:
            if t.get("received_at"):
                t["received_at"] = t["received_at"].isoformat()

        return jsonify({"success": True, "thread": thread, "count": len(thread)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@email_manager_bp.route("/api/inbox/<int:email_id>/star", methods=["POST"])
@login_required
def toggle_star(email_id):
    """Toggle star on an email."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """UPDATE email_inbox SET is_starred = NOT is_starred
            WHERE id = %s AND imap_setting_id IN (SELECT id FROM email_imap_settings WHERE user_id = %s)
            RETURNING is_starred""",
            (email_id, current_user.id),
        )
        result = cur.fetchone()
        conn.commit()
        return jsonify({"success": True, "is_starred": result["is_starred"] if result else False})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@email_manager_bp.route("/api/inbox/<int:email_id>/read", methods=["POST"])
@login_required
def toggle_read(email_id):
    """Toggle read/unread on an email."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """UPDATE email_inbox SET is_read = NOT is_read, updated_at = NOW()
            WHERE id = %s AND imap_setting_id IN (SELECT id FROM email_imap_settings WHERE user_id = %s)
            RETURNING is_read""",
            (email_id, current_user.id),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "error": "Email not found"}), 404
        conn.commit()
        return jsonify({"success": True, "is_read": row["is_read"]})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@email_manager_bp.route("/api/inbox/<int:email_id>/archive", methods=["POST"])
@login_required
def archive_email(email_id):
    """Archive an email."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """UPDATE email_inbox SET is_archived = TRUE
            WHERE id = %s AND imap_setting_id IN (SELECT id FROM email_imap_settings WHERE user_id = %s)""",
            (email_id, current_user.id),
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


@email_manager_bp.route("/api/inbox/<int:email_id>/delete", methods=["DELETE"])
@login_required
def delete_email(email_id):
    """Permanently delete an email."""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """DELETE FROM email_inbox
            WHERE id = %s AND imap_setting_id IN (SELECT id FROM email_imap_settings WHERE user_id = %s)""",
            (email_id, current_user.id),
        )
        if cur.rowcount == 0:
            return jsonify({"success": False, "error": "Email not found"}), 404
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


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
