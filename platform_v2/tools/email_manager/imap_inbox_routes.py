"""
Email Intelligence IMAP Inbox Routes — list, stats, bulk actions, detail.

Registered on the existing email_manager_bp blueprint.

Split out of imap_routes.py; see imap_routes for the compatibility re-exports.

Author: A.R.C.H.I.E. Platform
Created: 2026-02-17
"""

import logging
import sys
import time

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
            """SELECT COUNT(*) as total
            FROM email_inbox e
            JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE """
            + where_clause,
            params,
        )
        total = cur.fetchone()["total"]

        # Fetch
        cur.execute(
            """
            SELECT e.id, e.from_address, e.from_name, e.subject, e.received_at,
                   e.has_attachments, e.ai_category, e.ai_summary, e.ai_priority, e.ai_sentiment,
                   e.is_read, e.is_starred, e.crm_customer_id, e.kb_entry_id, e.created_at,
                   eis.name as account_name
            FROM email_inbox e
            JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE """
            + where_clause
            + """
            ORDER BY """
            + order_clause
            + """
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
            """SELECT e.ai_category, COUNT(*) as count
            FROM email_inbox e
            JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE e.is_archived = FALSE"""
            + acct_filter
            + """
            GROUP BY e.ai_category""",
            acct_params,
        )
        categories = {r["ai_category"]: r["count"] for r in cur.fetchall() if r["ai_category"]}

        # Unread count
        cur.execute(
            """SELECT COUNT(*) as c FROM email_inbox e
            JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE e.is_read = FALSE AND e.is_archived = FALSE"""
            + acct_filter,
            acct_params,
        )
        unread = cur.fetchone()["c"]

        # Starred count
        cur.execute(
            """SELECT COUNT(*) as c FROM email_inbox e
            JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE e.is_starred = TRUE AND e.is_archived = FALSE"""
            + acct_filter,
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
            """
            SELECT
                COUNT(*) as total,
                COUNT(e.ai_analyzed_at) as analyzed,
                COUNT(*) FILTER (WHERE e.is_read = FALSE AND e.is_archived = FALSE) as unread,
                COUNT(*) FILTER (WHERE e.is_archived = TRUE) as archived,
                COUNT(*) FILTER (WHERE e.is_starred = TRUE AND e.is_archived = FALSE) as starred
            FROM email_inbox e
            JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
            WHERE eis.user_id = %s"""
            + acct_filter,
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
                "UPDATE email_inbox SET is_read = TRUE WHERE id IN (" + placeholders + ")" + ownership,
                params_with_user,
            )
        elif action == "mark_unread":
            cur.execute(
                "UPDATE email_inbox SET is_read = FALSE WHERE id IN (" + placeholders + ")" + ownership,
                params_with_user,
            )
        elif action == "archive":
            cur.execute(
                "UPDATE email_inbox SET is_archived = TRUE WHERE id IN (" + placeholders + ")" + ownership,
                params_with_user,
            )
        elif action == "star":
            cur.execute(
                "UPDATE email_inbox SET is_starred = TRUE WHERE id IN (" + placeholders + ")" + ownership,
                params_with_user,
            )
        elif action == "unstar":
            cur.execute(
                "UPDATE email_inbox SET is_starred = FALSE WHERE id IN (" + placeholders + ")" + ownership,
                params_with_user,
            )
        elif action == "delete":
            cur.execute(
                "DELETE FROM email_inbox WHERE id IN (" + placeholders + ")" + ownership,
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
