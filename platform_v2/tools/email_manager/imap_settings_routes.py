"""
Email Intelligence IMAP Routes — Inbox, Settings, Analysis, Drafts

Registered on the existing email_manager_bp blueprint.

This module holds the database helper and the IMAP/SMTP settings routes.
The inbox and email-action routes live in imap_inbox_routes and
imap_actions_routes. imap_routes re-exports everything for compatibility.

Author: A.R.C.H.I.E. Platform
Created: 2026-02-17
"""

import logging
import os
import sys

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import jsonify, request
from flask_login import current_user, login_required

from database import _get_db_password

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
            "UPDATE email_imap_settings SET " + ", ".join(updates) + " WHERE id = %s AND user_id = %s RETURNING id",
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
