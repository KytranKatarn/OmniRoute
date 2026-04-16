"""Notification service — queries for system notifications, search, export, archival.

Owner: app.py notification API routes (/api/notifications/*)
Tables: system_notifications, notification_reads, task_execution_log,
        failed_logins, system_alerts, agents

Import:
    from services.notification_service import get_notifications, get_unread_count
"""

import logging

from psycopg2.extras import RealDictCursor
from database import get_db_connection

logger = logging.getLogger(__name__)


def _ts(dt):
    """Convert datetime to ISO 8601 string."""
    if dt is None:
        return None
    return dt.isoformat() + "Z" if dt.tzinfo is None else dt.isoformat()


def _visibility_filter(is_admin, user_id, table_alias="sn"):
    """Build visibility WHERE clause and params.

    Admins see ALL notifications.
    Regular users see only visibility='all' OR (visibility='user' AND target_user_id=their_id).

    Returns (sql_fragment, params_list).  sql_fragment may be empty string for admins.
    """
    if is_admin:
        return "", []
    return (
        f"AND ({table_alias}.visibility = 'all' OR ({table_alias}.visibility = 'user' AND {table_alias}.target_user_id = %s))",
        [user_id],
    )


# ---------------------------------------------------------------------------
# 1. GET /api/notifications — blended notifications list
# ---------------------------------------------------------------------------
def _unified_to_notif(a):
    """Convert a unified alert item to the legacy notification dict format."""
    return {
        "id": a["id"],
        "type": a.get("type", "info"),
        "title": a.get("title", ""),
        "message": a.get("message", ""),
        "source": a.get("source", "system"),
        "is_read": a.get("is_read", True),
        "priority": a.get("priority", "normal"),
        "created_at": a.get("timestamp"),
    }


def get_notifications(user_id, is_admin):
    """User-facing module notifications only (bell icon).

    Returns notifications targeted at the specific user from modules
    (e.g. email arrived, task completed, calendar reminder).
    System/ops alerts go to Mission Briefing via /api/alerts/unified instead.
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                SELECT sn.id, sn.title, sn.message, sn.source, sn.type,
                       sn.priority, sn.created_at,
                       CASE WHEN nr.notification_id IS NOT NULL THEN true ELSE false END as is_read
                FROM system_notifications sn
                LEFT JOIN notification_reads nr ON nr.notification_id = sn.id AND nr.user_id = %s
                WHERE sn.is_archived = FALSE
                  AND sn.created_at >= NOW() - INTERVAL '30 days'
                  AND (sn.visibility = 'user' AND sn.target_user_id = %s)
                ORDER BY sn.created_at DESC
                LIMIT 20
                """,
                [user_id, user_id],
            )
            return [
                {
                    "id": n["id"],
                    "type": n["type"] or "info",
                    "title": n["title"] or "Notification",
                    "message": n["message"],
                    "source": n["source"] or "module",
                    "is_read": n["is_read"],
                    "priority": n["priority"] or "normal",
                    "created_at": _ts(n["created_at"]),
                }
                for n in cur.fetchall()
            ]
        except Exception:
            logger.exception("get_notifications: query failed")
            return []
        finally:
            cur.close()


def _get_notifications_legacy(user_id, is_admin):
    """Blended notifications — grouped system_notifications + bridge alerts + security.

    Returns list of notification dicts sorted: unread first, then by timestamp DESC.
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            notifications_list = []

            # 1. System notifications — grouped by title+source (last 7 days)
            vis_sql, vis_params = _visibility_filter(is_admin, user_id)

            cur.execute(
                f"""
                SELECT title, source, type, priority,
                       MAX(message) as message,
                       MAX(sn.id) as id,
                       COUNT(*) as group_count,
                       MAX(sn.created_at) as latest,
                       COUNT(*) FILTER (WHERE nr.notification_id IS NULL) = 0 as all_read
                FROM system_notifications sn
                LEFT JOIN notification_reads nr ON nr.notification_id = sn.id AND nr.user_id = %s
                WHERE sn.is_archived = FALSE
                  AND sn.created_at >= NOW() - INTERVAL '7 days'
                  {vis_sql}
                GROUP BY title, source, type, priority
                ORDER BY MAX(sn.created_at) DESC
                LIMIT 20
            """,
                [user_id] + vis_params,
            )
            for n in cur.fetchall():
                count = n["group_count"]
                title = n["title"] or "Notification"
                if count > 1:
                    title = f"{title} ({count}x)"
                notifications_list.append(
                    {
                        "id": n["id"],
                        "type": n["type"] or "info",
                        "title": title,
                        "message": n["message"],
                        "source": n["source"] or "system",
                        "is_read": n["all_read"],
                        "priority": n["priority"] or "normal",
                        "created_at": _ts(n["latest"]),
                    }
                )

            # 2-4. Admin-only blended sources
            if is_admin:

                # 2. Failed bridge jobs (last 24h) — grouped by module+capability
                cur.execute(
                    """
                    SELECT t.module_source, t.capability,
                           LEFT(t.error_message, 120) as error_summary,
                           COUNT(*) as fail_count, MAX(t.created_at) as latest,
                           a.first_name, a.last_name
                    FROM task_execution_log t
                    LEFT JOIN agents a ON a.name = SPLIT_PART(t.agent_name, '\u2192', 1)
                    WHERE t.success = false AND t.created_at >= NOW() - INTERVAL '24 hours'
                    GROUP BY t.module_source, t.capability,
                             LEFT(t.error_message, 120), a.first_name, a.last_name
                    ORDER BY latest DESC
                    LIMIT 3
                """
                )
                for row in cur.fetchall():
                    first = (row["first_name"] or "").strip()
                    last = (row["last_name"] or "").strip()
                    agent = f"{first} {last}".strip() or "Bridge"
                    module = (row["module_source"] or "bridge").replace("_", " ").title()
                    count = row["fail_count"]
                    notifications_list.append(
                        {
                            "id": 0,
                            "type": "warning" if count < 10 else "error",
                            "title": f"{module}: {count} failed {row['capability']}",
                            "message": f"{agent} \u2014 {row['error_summary'] or 'Unknown error'}",
                            "source": "bridge",
                            "is_read": True,
                            "priority": "high" if count >= 10 else "medium",
                            "created_at": _ts(row["latest"]),
                        }
                    )

                # 3. Failed logins (last 24h) — grouped by username
                cur.execute(
                    """
                    SELECT username, COUNT(*) as attempts, MAX(attempted_at) as latest,
                           (array_agg(DISTINCT ip_address))[1:2] as ips
                    FROM failed_logins
                    WHERE attempted_at >= NOW() - INTERVAL '24 hours'
                    GROUP BY username
                    ORDER BY attempts DESC
                    LIMIT 3
                """
                )
                for row in cur.fetchall():
                    count = row["attempts"]
                    ips = ", ".join(row["ips"]) if row["ips"] else "unknown"
                    notifications_list.append(
                        {
                            "id": 0,
                            "type": "warning" if count < 5 else "error",
                            "title": f"{count} failed login{'s' if count > 1 else ''} \u2014 {row['username']}",
                            "message": f"From IP: {ips}",
                            "source": "security",
                            "is_read": True,
                            "priority": "high" if count >= 5 else "medium",
                            "created_at": _ts(row["latest"]),
                        }
                    )

                # 4. Unresolved system alerts
                cur.execute(
                    """
                    SELECT alert_type, severity, message, created_at
                    FROM system_alerts
                    WHERE resolved = false
                    ORDER BY created_at DESC
                    LIMIT 3
                """
                )
                for row in cur.fetchall():
                    notifications_list.append(
                        {
                            "id": 0,
                            "type": "error" if row["severity"] in ("critical", "error") else "warning",
                            "title": row["alert_type"].replace("_", " ").title(),
                            "message": row["message"],
                            "source": "system",
                            "is_read": True,
                            "priority": row["severity"],
                            "created_at": _ts(row["created_at"]),
                        }
                    )

            # Sort: unread first, then by timestamp DESC
            unread = [n for n in notifications_list if not n["is_read"]]
            read = [n for n in notifications_list if n["is_read"]]
            unread.sort(key=lambda n: n.get("created_at") or "", reverse=True)
            read.sort(key=lambda n: n.get("created_at") or "", reverse=True)

            return (unread + read)[:30]
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# 2. POST /api/notifications/mark-read/<id>
# ---------------------------------------------------------------------------
def mark_read(notification_id, user_id):
    """Mark a notification and its group as read for the given user.

    Returns True on success.
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            # Find the notification's title+source to mark entire group
            cur.execute(
                "SELECT title, source FROM system_notifications WHERE id = %s",
                (notification_id,),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    INSERT INTO notification_reads (notification_id, user_id, read_at)
                    SELECT id, %s, NOW()
                    FROM system_notifications
                    WHERE title = %s AND source = %s AND is_archived = FALSE
                    ON CONFLICT (notification_id, user_id) DO NOTHING
                """,
                    (user_id, row["title"], row["source"]),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO notification_reads (notification_id, user_id, read_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (notification_id, user_id) DO NOTHING
                """,
                    (notification_id, user_id),
                )
            conn.commit()
            return True
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# 3. POST /api/notifications/mark-all-read
# ---------------------------------------------------------------------------
def mark_all_read(user_id, is_admin):
    """Mark all visible notifications as read for the given user.

    Returns True on success.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            vis_sql, vis_params = _visibility_filter(is_admin, user_id, table_alias="")
            # Strip table alias prefix for bare table query
            vis_sql_bare = vis_sql.replace(".", "") if vis_sql else ""

            cur.execute(
                f"""
                INSERT INTO notification_reads (notification_id, user_id, read_at)
                SELECT id, %s, NOW()
                FROM system_notifications
                WHERE is_archived = FALSE
                  AND created_at >= NOW() - INTERVAL '7 days'
                  AND id NOT IN (SELECT notification_id FROM notification_reads WHERE user_id = %s)
                  {vis_sql_bare}
                ON CONFLICT (notification_id, user_id) DO NOTHING
            """,
                [user_id, user_id] + vis_params,
            )
            conn.commit()
            return True
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# 4. POST /api/notifications — create with dedup
# ---------------------------------------------------------------------------
def create_notification(
    notification_type="info",
    title="Notification",
    message="",
    source="dashboard",
    priority="normal",
    source_icon="",
    related_action=None,
    visibility="all",
    target_user_id=None,
):
    """Create a new notification with deduplication.

    If a duplicate exists within 5 minutes, increments grouped_count instead.
    Returns dict with 'id' (new) or 'grouped' + 'count' (deduped).
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            # DEDUPLICATION: Check for duplicate in last 5 minutes
            cur.execute(
                """
                SELECT id, grouped_count FROM system_notifications
                WHERE message = %s
                AND type = %s
                AND source = %s
                AND created_at > NOW() - INTERVAL '5 minutes'
                AND is_read = FALSE
                ORDER BY created_at DESC
                LIMIT 1
            """,
                (message, notification_type, source),
            )
            existing = cur.fetchone()

            if existing:
                cur.execute(
                    """
                    UPDATE system_notifications
                    SET grouped_count = grouped_count + 1,
                        created_at = NOW()
                    WHERE id = %s
                """,
                    (existing["id"],),
                )
                conn.commit()
                return {"grouped": True, "count": existing["grouped_count"] + 1}

            # Create new notification
            cur.execute(
                """
                INSERT INTO system_notifications
                    (type, title, message, source, priority,
                     source_icon, related_action, is_read, visibility, target_user_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, %s, %s, NOW())
                RETURNING id
            """,
                (
                    notification_type,
                    title,
                    message,
                    source,
                    priority,
                    source_icon,
                    related_action,
                    visibility,
                    target_user_id,
                ),
            )
            notification_id = cur.fetchone()["id"]
            conn.commit()
            return {"id": notification_id}
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# 5. GET /api/notifications/count — unread count
# ---------------------------------------------------------------------------
def get_unread_count(user_id, is_admin):
    """Get unread notification count — user-targeted module notifications only (bell icon).

    Returns dict with 'unread', 'critical', 'errors' counts.
    System alerts are counted separately in Mission Briefing.
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE nr.notification_id IS NULL) as unread,
                    COUNT(*) FILTER (WHERE sn.priority = 'critical' AND nr.notification_id IS NULL) as critical,
                    COUNT(*) FILTER (WHERE sn.type = 'error' AND nr.notification_id IS NULL) as errors
                FROM system_notifications sn
                LEFT JOIN notification_reads nr ON nr.notification_id = sn.id AND nr.user_id = %s
                WHERE sn.is_archived = FALSE
                  AND sn.created_at >= NOW() - INTERVAL '30 days'
                  AND sn.visibility = 'user' AND sn.target_user_id = %s
            """,
                [user_id, user_id],
            )
            counts = cur.fetchone()
            return {
                "unread": counts["unread"] or 0,
                "critical": counts["critical"] or 0,
                "errors": counts["errors"] or 0,
            }
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# 6. GET /api/notifications/search — search with filters
# ---------------------------------------------------------------------------
def search_notifications(
    user_id,
    is_admin,
    filter_type="all",
    notification_type="all",
    priority="all",
    source="all",
    search_query="",
    date_range="all",
    page=1,
    per_page=20,
):
    """Search and filter notifications with pagination.

    Returns dict with 'notifications', 'total', 'page', 'per_page', 'total_pages'.
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            # Build WHERE clauses
            where_clauses = ["is_archived = FALSE"]
            params = []

            # Visibility filter
            if not is_admin:
                where_clauses.append("(visibility = 'all' OR (visibility = 'user' AND target_user_id = %s))")
                params.append(user_id)

            if filter_type == "unread":
                where_clauses.append("id NOT IN (SELECT notification_id FROM notification_reads WHERE user_id = %s)")
                params.append(user_id)
            elif filter_type == "read":
                where_clauses.append("id IN (SELECT notification_id FROM notification_reads WHERE user_id = %s)")
                params.append(user_id)

            if notification_type != "all":
                where_clauses.append("type = %s")
                params.append(notification_type)

            if priority != "all":
                where_clauses.append("priority = %s")
                params.append(priority)

            if source != "all":
                where_clauses.append("source = %s")
                params.append(source)

            if search_query:
                where_clauses.append("(message ILIKE %s OR title ILIKE %s)")
                params.extend([f"%{search_query}%", f"%{search_query}%"])

            if date_range == "24h":
                where_clauses.append("created_at > NOW() - INTERVAL '24 hours'")
            elif date_range == "7d":
                where_clauses.append("created_at > NOW() - INTERVAL '7 days'")
            elif date_range == "30d":
                where_clauses.append("created_at > NOW() - INTERVAL '30 days'")

            where_sql = " AND ".join(where_clauses)

            # Get total count
            cur.execute(
                f"SELECT COUNT(*) as total FROM system_notifications WHERE {where_sql}",
                params,
            )
            total = cur.fetchone()["total"]

            # Get paginated results
            offset = (page - 1) * per_page
            query_params = params + [per_page, offset]

            cur.execute(
                f"""
                SELECT id, type, title, message, source, source_icon, priority,
                       grouped_count, related_action, is_read, created_at
                FROM system_notifications
                WHERE {where_sql}
                ORDER BY
                    CASE priority
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'normal' THEN 3
                        WHEN 'low' THEN 4
                    END,
                    created_at DESC
                LIMIT %s OFFSET %s
            """,
                query_params,
            )

            notifications = cur.fetchall()

            return {
                "notifications": [dict(n) for n in notifications],
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": (total + per_page - 1) // per_page,
            }
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# 7. GET /api/notifications/export — export all (admin only)
# ---------------------------------------------------------------------------
def export_notifications():
    """Export all non-archived notifications (up to 1000).

    Returns list of notification dicts.
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                SELECT id, type, title, message, source, priority, is_read, created_at
                FROM system_notifications
                WHERE is_archived = FALSE
                ORDER BY created_at DESC
                LIMIT 1000
            """
            )
            return [dict(n) for n in cur.fetchall()]
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# 8. POST /api/notifications/archive-old — archive old (admin only)
# ---------------------------------------------------------------------------
def archive_old(days=7):
    """Archive all notifications older than the specified number of days.

    Days is clamped to 1-90.
    Returns the number of archived notifications.
    """
    days = max(1, min(days, 90))
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE system_notifications
                SET is_archived = TRUE
                WHERE created_at < NOW() - make_interval(days => %s)
                AND is_archived = FALSE
            """,
                (days,),
            )
            archived_count = cur.rowcount
            conn.commit()
            return archived_count
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# 9. POST /api/notifications/dismiss/<id>
# ---------------------------------------------------------------------------
def dismiss_notification(notification_id, user_id):
    """Dismiss (archive) a single notification and its group.

    Returns dict with 'archived' count, or None if notification not found.
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                "SELECT title, source FROM system_notifications WHERE id = %s",
                (notification_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            # Mark as read for this user
            cur.execute(
                """
                INSERT INTO notification_reads (notification_id, user_id, read_at)
                SELECT id, %s, NOW()
                FROM system_notifications
                WHERE title = %s AND source = %s AND is_archived = FALSE
                ON CONFLICT (notification_id, user_id) DO NOTHING
            """,
                (user_id, row["title"], row["source"]),
            )

            # Archive the group
            cur.execute(
                """
                UPDATE system_notifications
                SET is_archived = TRUE
                WHERE title = %s AND source = %s AND is_archived = FALSE
            """,
                (row["title"], row["source"]),
            )

            archived_count = cur.rowcount
            conn.commit()
            return {"archived": archived_count}
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# 10. POST /api/notifications/clear-all — clear all (admin only)
# ---------------------------------------------------------------------------
def clear_all(user_id):
    """Archive all visible (non-archived) notifications.
    Also marks them as read for the given user.

    Returns the number of archived notifications.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            # First mark all as read for this user
            cur.execute(
                """
                INSERT INTO notification_reads (notification_id, user_id, read_at)
                SELECT id, %s, NOW()
                FROM system_notifications
                WHERE is_archived = FALSE
                  AND id NOT IN (SELECT notification_id FROM notification_reads WHERE user_id = %s)
                ON CONFLICT (notification_id, user_id) DO NOTHING
            """,
                (user_id, user_id),
            )

            # Then archive everything
            cur.execute(
                """
                UPDATE system_notifications
                SET is_archived = TRUE
                WHERE is_archived = FALSE
            """
            )

            archived_count = cur.rowcount
            conn.commit()
            return archived_count
        finally:
            cur.close()
