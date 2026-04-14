"""Alert service — unified alerts from all platform sources.

Owner: dashboard API routes
Tables: system_notifications, service_status, task_execution_log,
        system_alerts, stack_health_alerts, agent_rest_cycles,
        failed_logins, unified_alert_reads, agents

Import:
    from services.alert_service import get_unified_alerts, mark_alert_read, mark_all_alerts_read
"""

import logging

import psycopg2.extras
from psycopg2.extras import RealDictCursor
from database import get_db_connection

logger = logging.getLogger(__name__)


def _ts(dt):
    """Convert datetime to ISO 8601 string."""
    if dt is None:
        return None
    return dt.isoformat() + "Z" if dt.tzinfo is None else dt.isoformat()


def _empty_response():
    return {
        "critical": [],
        "categories": {
            "infrastructure": [],
            "agents": [],
            "security": [],
            "jobs": [],
        },
        "counts": {"total": 0, "unread": 0, "critical": 0},
    }


def get_unified_alerts(user_id, is_admin):
    """Return all platform alerts normalized into a categorized response.

    Non-admin users see a limited subset (system_notifications only, filtered by visibility).
    Read state is tracked per-user via the unified_alert_reads table.

    Returns dict with keys: critical, categories, counts
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # ----------------------------------------------------------------
            # Load read keys for this user upfront
            # ----------------------------------------------------------------
            cur.execute(
                "SELECT alert_key FROM unified_alert_reads WHERE user_id = %s",
                (user_id,),
            )
            read_keys = {row["alert_key"] for row in cur.fetchall()}

            all_alerts = []

            # ----------------------------------------------------------------
            # 1. system_notifications — last 7 days, unarchived
            # ----------------------------------------------------------------
            if is_admin:
                vis_clause = ""
                vis_params = []
            else:
                vis_clause = "AND (sn.visibility = 'all' " "OR (sn.visibility = 'user' AND sn.target_user_id = %s))"
                vis_params = [user_id]

            cur.execute(
                f"""
                SELECT
                    MAX(sn.id) AS id,
                    sn.title,
                    sn.source,
                    sn.type,
                    sn.priority,
                    MAX(sn.created_at) AS created_at,
                    COUNT(*) AS occurrence_count
                FROM system_notifications sn
                WHERE sn.is_archived = FALSE
                  AND sn.created_at >= NOW() - INTERVAL '7 days'
                  {vis_clause}
                GROUP BY sn.title, sn.source, sn.type, sn.priority
                """,
                vis_params,
            )
            for row in cur.fetchall():
                alert_type = row["type"] or "info"
                if alert_type in ("error", "warning", "alert"):
                    category = "infrastructure"
                else:
                    category = "jobs"

                key = f"sn-{row['id']}"
                all_alerts.append(
                    {
                        "id": key,
                        "title": row["title"],
                        "source": row["source"],
                        "type": alert_type,
                        "priority": row["priority"] or "medium",
                        "category": category,
                        "timestamp": _ts(row["created_at"]),
                        "occurrence_count": row["occurrence_count"],
                        "is_read": key in read_keys,
                    }
                )

            # ----------------------------------------------------------------
            # Admin-only sources below
            # ----------------------------------------------------------------
            if is_admin:
                # 2. service_status — non-online services
                cur.execute(
                    """
                    SELECT id, service_name, status, last_checked
                    FROM service_status
                    WHERE status != 'online'
                    """
                )
                for row in cur.fetchall():
                    key = f"svc-{row['id']}"
                    if row["status"] in ("down", "error", "offline"):
                        alert_type = "error"
                        priority = "critical"
                    else:
                        alert_type = "warning"
                        priority = "high"
                    all_alerts.append(
                        {
                            "id": key,
                            "title": f"Service degraded: {row['service_name']} ({row['status']})",
                            "source": "service_status",
                            "type": alert_type,
                            "priority": priority,
                            "category": "infrastructure",
                            "timestamp": _ts(row["last_checked"]),
                            "is_read": key in read_keys,
                        }
                    )

                # 3. task_execution_log — failed jobs in last 24h
                cur.execute(
                    """
                    SELECT
                        MAX(tel.id) AS id,
                        tel.module_source,
                        tel.capability,
                        LEFT(tel.error_message, 120) AS error_summary,
                        COUNT(*) AS failure_count,
                        MAX(tel.created_at) AS latest_at,
                        a.display_name AS agent_name
                    FROM task_execution_log tel
                    LEFT JOIN agents a ON a.name = tel.agent_name
                    WHERE tel.success = FALSE
                      AND tel.created_at >= NOW() - INTERVAL '24 hours'
                    GROUP BY tel.module_source, tel.capability, LEFT(tel.error_message, 120), a.display_name
                    ORDER BY latest_at DESC LIMIT 10
                    """
                )
                for row in cur.fetchall():
                    key = f"job-{row['id']}"
                    priority = "high" if (row["failure_count"] or 0) >= 10 else "medium"
                    agent_label = row["agent_name"] or row["module_source"] or "unknown"
                    all_alerts.append(
                        {
                            "id": key,
                            "title": (
                                f"Job failures: {row['capability'] or 'unknown'} "
                                f"({row['failure_count']}x) — {agent_label}"
                            ),
                            "source": row["module_source"] or "task_execution_log",
                            "type": "error",
                            "priority": priority,
                            "category": "jobs",
                            "timestamp": _ts(row["latest_at"]),
                            "error_summary": row["error_summary"],
                            "is_read": key in read_keys,
                        }
                    )

                # 4. system_alerts — unresolved
                cur.execute(
                    """
                    SELECT id, alert_type, severity, message, created_at
                    FROM system_alerts
                    WHERE resolved = FALSE
                    ORDER BY created_at DESC LIMIT 10
                    """
                )
                for row in cur.fetchall():
                    key = f"sa-{row['id']}"
                    severity = row["severity"] or "warning"
                    all_alerts.append(
                        {
                            "id": key,
                            "title": (row["alert_type"] or "Alert").replace("_", " ").title(),
                            "message": row["message"] or "",
                            "source": "system_alerts",
                            "type": severity if severity in ("error", "warning", "info") else "warning",
                            "priority": "high" if severity in ("critical", "error") else "medium",
                            "category": "infrastructure",
                            "timestamp": _ts(row["created_at"]),
                            "is_read": key in read_keys,
                        }
                    )

                # 5. stack_health_alerts — unresolved
                cur.execute(
                    """
                    SELECT id, stack_name, container_name, alert_type, severity, message, created_at
                    FROM stack_health_alerts
                    WHERE resolved = FALSE
                    ORDER BY created_at DESC LIMIT 10
                    """
                )
                for row in cur.fetchall():
                    key = f"sh-{row['id']}"
                    name = row["container_name"] or row["stack_name"]
                    severity = row["severity"] or "warning"
                    all_alerts.append(
                        {
                            "id": key,
                            "title": f"{name}: {(row['alert_type'] or 'alert').replace('_', ' ')}",
                            "message": row["message"] or "",
                            "source": "stack_health_alerts",
                            "type": severity if severity in ("error", "warning", "info") else "warning",
                            "priority": "high" if severity in ("critical", "error") else "medium",
                            "category": "infrastructure",
                            "timestamp": _ts(row["created_at"]),
                            "is_read": key in read_keys,
                        }
                    )

                # 6. agent_rest_cycles — last 24h
                cur.execute(
                    """
                    SELECT arc.id, arc.started_at, arc.reason, a.display_name AS agent_name
                    FROM agent_rest_cycles arc
                    LEFT JOIN agents a ON a.id = arc.agent_id
                    WHERE arc.started_at >= NOW() - INTERVAL '24 hours'
                    """
                )
                for row in cur.fetchall():
                    key = f"arc-{row['id']}"
                    name = row["agent_name"] or "Unknown agent"
                    all_alerts.append(
                        {
                            "id": key,
                            "title": f"Agent rest cycle: {name}",
                            "source": "agent_rest_cycles",
                            "type": "info",
                            "priority": "low",
                            "category": "agents",
                            "timestamp": _ts(row["started_at"]),
                            "reason": row["reason"],
                            "is_read": key in read_keys,
                        }
                    )

                # 7. failed_logins — last 24h, grouped, ≥3 attempts
                cur.execute(
                    """
                    SELECT
                        username,
                        COUNT(*) AS attempts,
                        MAX(attempted_at) AS latest_at
                    FROM failed_logins
                    WHERE attempted_at >= NOW() - INTERVAL '24 hours'
                    GROUP BY username
                    HAVING COUNT(*) >= 3
                    """
                )
                for row in cur.fetchall():
                    key = f"fl-{row['username']}"
                    attempts = row["attempts"] or 0
                    priority = "high" if attempts >= 10 else "medium"
                    all_alerts.append(
                        {
                            "id": key,
                            "title": f"Failed logins: {row['username']} ({attempts} attempts)",
                            "source": "failed_logins",
                            "type": "warning",
                            "priority": priority,
                            "category": "security",
                            "timestamp": _ts(row["latest_at"]),
                            "attempts": attempts,
                            "is_read": key in read_keys,
                        }
                    )

            # ----------------------------------------------------------------
            # Build response
            # ----------------------------------------------------------------
            categories = {"infrastructure": [], "agents": [], "security": [], "jobs": []}
            for alert in all_alerts:
                cat = alert.get("category", "infrastructure")
                if cat in categories:
                    categories[cat].append(alert)

            # Sort each category by timestamp DESC (None last)
            for cat in categories:
                categories[cat].sort(key=lambda a: a["timestamp"] or "", reverse=True)

            # Critical = unread + (type error OR priority critical/high)
            critical = [
                a
                for a in all_alerts
                if not a["is_read"] and (a["type"] == "error" or a["priority"] in ("critical", "high"))
            ]
            critical.sort(key=lambda a: a["timestamp"] or "", reverse=True)

            unread_count = sum(1 for a in all_alerts if not a["is_read"])

            return {
                "critical": critical,
                "categories": categories,
                "counts": {
                    "total": len(all_alerts),
                    "unread": unread_count,
                    "critical": len(critical),
                },
            }

    except Exception:
        logger.exception("get_unified_alerts failed for user_id=%s", user_id)
        return _empty_response()


def mark_alert_read(user_id, alert_key):
    """Mark a single alert as read for a user.

    Returns True on success, False on failure.
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO unified_alert_reads (user_id, alert_key)
                VALUES (%s, %s)
                ON CONFLICT (user_id, alert_key) DO NOTHING
                """,
                (user_id, alert_key),
            )
            conn.commit()
            return True
    except Exception:
        logger.exception("mark_alert_read failed user_id=%s key=%s", user_id, alert_key)
        return False


def mark_all_alerts_read(user_id, is_admin):
    """Mark all current alerts as read for a user.

    Fetches current alert set, bulk-inserts read records.
    Returns count of newly marked alerts.
    """
    try:
        data = get_unified_alerts(user_id, is_admin)
        all_items = []
        for cat_alerts in data["categories"].values():
            all_items.extend(cat_alerts)

        unread = [(user_id, a["id"]) for a in all_items if not a["is_read"]]
        if not unread:
            return 0

        with get_db_connection() as conn:
            cur = conn.cursor()
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO unified_alert_reads (user_id, alert_key)
                VALUES %s
                ON CONFLICT (user_id, alert_key) DO NOTHING
                """,
                unread,
            )
            conn.commit()
            return len(unread)
    except Exception:
        logger.exception("mark_all_alerts_read failed user_id=%s", user_id)
        return 0
