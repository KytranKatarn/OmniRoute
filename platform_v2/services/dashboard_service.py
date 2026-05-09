"""Dashboard service — queries for dashboard HUD, recent activity, and alerts.

Owner: app.py dashboard API routes
Tables: agents, task_execution_log, service_status, user_activity_log,
        governance_audit_log, knowledge_base, system_alerts, stack_health_alerts,
        failed_logins, ethics_alerts, notifications, agent_rest_cycles

Import:
    from services.dashboard_service import get_ai_status, get_recent_activity, get_alerts
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


def get_ai_status():
    """AI bridge status for dashboard HUD.
    Returns: dict with ai_online, active_agents, today_interactions, services
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT COUNT(*) as count FROM agents WHERE status = 'active'")
            agent_count = cur.fetchone()["count"]

            cur.execute(
                "SELECT COUNT(*) as count FROM task_execution_log " "WHERE created_at >= NOW() - INTERVAL '24 hours'"
            )
            today_interactions = cur.fetchone()["count"]

            cur.execute(
                "SELECT service_name, status FROM service_status "
                "WHERE service_name IN ('ollama', 'ai_bridge', 'consciousness')"
            )
            services = {row["service_name"]: row["status"] for row in cur.fetchall()}

            ai_online = services.get("ai_bridge") == "online" and agent_count > 0
            return {
                "ai_online": ai_online,
                "active_agents": agent_count,
                "today_interactions": today_interactions,
                "services": services,
            }
        finally:
            cur.close()


def get_recent_activity():
    """Blended recent activity from multiple sources.
    Returns: list of activity dicts sorted by timestamp desc, max 15
    """

    def _friendly_action(action):
        labels = {
            "login_success": "Logged in",
            "login_failed": "Failed login",
            "user_updated": "Updated profile",
            "session_revoked": "Revoked session",
            "subscription_changed": "Changed subscription",
            "2fa_enabled": "Enabled 2FA",
            "2fa_disabled": "Disabled 2FA",
        }
        return labels.get(action, action.replace("_", " ").title())

    def _friendly_module(module_source):
        labels = {
            "email_intelligence": "Email",
            "consciousness_linguistics": "Linguistics",
            "proactive_intelligence": "Proactive AI",
            "bridge_learning": "Bridge Learning",
        }
        return labels.get(module_source, (module_source or "bridge").replace("_", " ").title())

    def _friendly_capability(capability, agent, module, model=""):
        verbs = {
            "classify": "Classified email",
            "translate": "Translated text",
            "chat": "Handled conversation",
            "summarize": "Summarized content",
            "code": "Generated code",
            "detect_language": "Detected language",
            "embed": "Created embedding",
        }
        task_desc = verbs.get(capability, capability)
        if model:
            task_desc += f" via {model}"
        return f"{module}: {agent} \u2014 {task_desc}"

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            combined = []

            # 1. User activity
            cur.execute(
                """SELECT action, module, details, created_at, username
                   FROM user_activity_log
                   WHERE created_at >= NOW() - INTERVAL '7 days'
                   ORDER BY created_at DESC LIMIT 8"""
            )
            for a in cur.fetchall():
                user = a["username"] or ""
                combined.append(
                    {
                        "action": f"{user}: {_friendly_action(a['action'])}" if user else _friendly_action(a["action"]),
                        "module": (a["module"] or "").replace("_", " ").title(),
                        "details": a["details"],
                        "username": user,
                        "source": "user",
                        "timestamp": _ts(a["created_at"]),
                    }
                )

            # 2. AI bridge work
            cur.execute(
                """SELECT t.module_source, t.capability, t.agent_name,
                          t.model_used, t.created_at,
                          a.first_name, a.last_name, at.name as role_name
                   FROM task_execution_log t
                   LEFT JOIN agents a ON a.name = SPLIT_PART(t.agent_name, '\u2192', 1)
                   LEFT JOIN agent_types at ON a.type_id = at.id
                   WHERE t.created_at >= NOW() - INTERVAL '7 days'
                   ORDER BY t.created_at DESC LIMIT 15"""
            )
            for row in cur.fetchall():
                first = (row["first_name"] or "").strip()
                last = (row["last_name"] or "").strip()
                full_name = f"{first} {last}".strip()
                role = row["role_name"] or ""
                if full_name and role:
                    agent_label = f'{full_name} "{role}"'
                elif full_name:
                    agent_label = full_name
                elif role:
                    agent_label = role
                else:
                    agent_label = (row["agent_name"] or "Bridge").split("\u2192")[0].strip()
                module = _friendly_module(row["module_source"])
                model = (row["model_used"] or "").split(":")[0]
                combined.append(
                    {
                        "action": _friendly_capability(row["capability"], agent_label, module, model),
                        "module": module,
                        "details": f"{module} \u2192 {agent_label} \u2014 {row['capability']} via {row['model_used'] or 'bridge'}",
                        "username": agent_label,
                        "source": "bridge",
                        "timestamp": _ts(row["created_at"]),
                    }
                )

            # 3. Governance events
            cur.execute(
                """SELECT g.event_type, g.event_category, g.action, g.reason,
                          g.details, g.timestamp, u.username
                   FROM governance_audit_log g
                   LEFT JOIN users u ON g.user_id = u.id
                   WHERE g.timestamp >= NOW() - INTERVAL '7 days'
                   ORDER BY g.timestamp DESC LIMIT 8"""
            )
            for g in cur.fetchall():
                reason = g["reason"] or ""
                who = g["username"] or ""
                details_json = g["details"] or {}
                # For telegram_send entries, reason is always empty — use
                # the title from details JSON and the agent as actor instead.
                if g["event_category"] == "telegram_send":
                    title = details_json.get("title", "") if isinstance(details_json, dict) else ""
                    actor = g["action"] or "System"
                    action_text = f"{actor}: {title}" if title else f"{actor}: Sent notification"
                elif g["event_type"] == "dev_commit":
                    action_text = f"Committed: {reason}" if reason else "New commit"
                else:
                    display_reason = reason or (details_json.get("title", "") if isinstance(details_json, dict) else "")
                    action_text = f"{g['event_type'].replace('_', ' ').title()}: {display_reason}"
                if who and not action_text.startswith(who):
                    action_text = f"{who}: {action_text}"
                combined.append(
                    {
                        "action": action_text,
                        "module": (g["event_category"] or "").replace("_", " ").title(),
                        "details": reason,
                        "username": who,
                        "source": "governance",
                        "timestamp": _ts(g["timestamp"]),
                    }
                )

            # 4. Knowledge base updates
            cur.execute(
                """SELECT title, knowledge_type, category, updated_at
                   FROM knowledge_base
                   WHERE updated_at >= NOW() - INTERVAL '7 days'
                   ORDER BY updated_at DESC LIMIT 5"""
            )
            for k in cur.fetchall():
                ktype = (k["knowledge_type"] or "entry").replace("_", " ").title()
                combined.append(
                    {
                        "action": f"{ktype}: {k['title']}",
                        "module": (k["category"] or "knowledge").replace("_", " ").title(),
                        "details": k["title"],
                        "username": None,
                        "source": "knowledge",
                        "timestamp": _ts(k["updated_at"]),
                    }
                )

            combined.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
            return combined[:15]
        finally:
            cur.close()


def get_alerts(user_id):
    """Blended system alerts for mission briefing — wraps the unified alert service.

    Splits unified alerts into service_issues (source='service_status') and
    general alerts (everything else).  Falls back to legacy direct-query
    implementation on any exception.

    Returns: dict with alerts list and service_issues list
    """
    try:
        from services.alert_service import get_unified_alerts

        unified = get_unified_alerts(user_id, is_admin=True)

        alerts = []
        service_issues = []

        all_items = list(unified.get("critical", []))
        for items in unified.get("categories", {}).values():
            all_items.extend(items)

        seen_ids = set()
        for item in all_items:
            item_id = item.get("id")
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            if item.get("source") == "service_status":
                service_issues.append(
                    {
                        "service": item.get("title", ""),
                        "status": item.get("type", "unknown"),
                        "error": item.get("message", ""),
                    }
                )
            else:
                alerts.append(
                    {
                        "type": item.get("type", "info"),
                        "title": item.get("title", ""),
                        "message": item.get("message", ""),
                        "priority": item.get("priority", "normal"),
                        "timestamp": item.get("timestamp"),
                    }
                )

        return {"alerts": alerts[:20], "service_issues": service_issues[:10]}
    except Exception:
        logger.exception("get_alerts: unified alert service failed, falling back to legacy")
        return _get_alerts_legacy(user_id)


def _get_alerts_legacy(user_id):
    """Blended system alerts for mission briefing (legacy direct-query implementation).
    Returns: dict with alerts list and service_issues list
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            alerts = []
            service_issues = []

            # 1. Service issues
            cur.execute(
                "SELECT service_name, status, error_message, last_checked "
                "FROM service_status WHERE status != 'online'"
            )
            for s in cur.fetchall():
                service_issues.append(
                    {
                        "service": s["service_name"],
                        "status": s["status"],
                        "error": s["error_message"],
                    }
                )

            # 2. Failed bridge jobs (24h)
            cur.execute(
                """SELECT t.module_source, t.capability,
                          LEFT(t.error_message, 120) as error_summary,
                          COUNT(*) as fail_count, MAX(t.created_at) as latest,
                          a.first_name, a.last_name
                   FROM task_execution_log t
                   LEFT JOIN agents a ON a.name = SPLIT_PART(t.agent_name, '\u2192', 1)
                   WHERE t.success = false AND t.created_at >= NOW() - INTERVAL '24 hours'
                   GROUP BY t.module_source, t.capability,
                            LEFT(t.error_message, 120), a.first_name, a.last_name
                   ORDER BY latest DESC LIMIT 5"""
            )
            for row in cur.fetchall():
                first = (row["first_name"] or "").strip()
                last = (row["last_name"] or "").strip()
                agent = f"{first} {last}".strip() or "Bridge"
                module = (row["module_source"] or "bridge").replace("_", " ").title()
                count = row["fail_count"]
                alerts.append(
                    {
                        "type": "job_failure",
                        "title": f"{module}: {count} failed {row['capability']} call{'s' if count > 1 else ''}",
                        "message": f"{agent} \u2014 {row['error_summary'] or 'Unknown error'}",
                        "priority": "high" if count >= 10 else "medium",
                        "timestamp": _ts(row["latest"]),
                    }
                )

            # 3. Agent welfare
            cur.execute(
                """SELECT a.first_name, a.last_name, a.name as codename,
                          r.reason, r.started_at
                   FROM agent_rest_cycles r
                   JOIN agents a ON a.id = r.agent_id
                   WHERE r.started_at >= NOW() - INTERVAL '24 hours'
                   ORDER BY r.started_at DESC LIMIT 3"""
            )
            for row in cur.fetchall():
                first = (row["first_name"] or "").strip()
                last = (row["last_name"] or "").strip()
                agent = f"{first} {last}".strip() or row["codename"]
                alerts.append(
                    {
                        "type": "welfare",
                        "title": f"{agent} entered rest cycle",
                        "message": row["reason"] or "Scheduled rest",
                        "priority": "low",
                        "timestamp": _ts(row["started_at"]),
                    }
                )

            # 4. System alerts
            cur.execute(
                """SELECT alert_type, severity, message, created_at
                   FROM system_alerts WHERE resolved = false
                   ORDER BY created_at DESC LIMIT 5"""
            )
            for row in cur.fetchall():
                alerts.append(
                    {
                        "type": "system",
                        "title": row["alert_type"].replace("_", " ").title(),
                        "message": row["message"],
                        "priority": row["severity"],
                        "timestamp": _ts(row["created_at"]),
                    }
                )

            # 5. Stack health
            cur.execute(
                """SELECT stack_name, container_name, alert_type, severity, message, created_at
                   FROM stack_health_alerts WHERE resolved = false
                   ORDER BY created_at DESC LIMIT 5"""
            )
            for row in cur.fetchall():
                name = row["container_name"] or row["stack_name"]
                alerts.append(
                    {
                        "type": "stack_health",
                        "title": f"{name}: {row['alert_type'].replace('_', ' ')}",
                        "message": row["message"],
                        "priority": row["severity"] or "warning",
                        "timestamp": _ts(row["created_at"]),
                    }
                )

            # 6. Failed logins (24h)
            cur.execute(
                """SELECT username, COUNT(*) as attempts, MAX(attempted_at) as latest,
                          (array_agg(DISTINCT ip_address))[1:2] as ips
                   FROM failed_logins
                   WHERE attempted_at >= NOW() - INTERVAL '24 hours'
                   GROUP BY username ORDER BY attempts DESC LIMIT 3"""
            )
            for row in cur.fetchall():
                count = row["attempts"]
                ips = ", ".join(row["ips"]) if row["ips"] else "unknown"
                alerts.append(
                    {
                        "type": "security",
                        "title": f"{count} failed login{'s' if count > 1 else ''} for {row['username']}",
                        "message": f"From IP: {ips}",
                        "priority": "high" if count >= 5 else "medium",
                        "timestamp": _ts(row["latest"]),
                    }
                )

            # 7. Ethics alerts
            cur.execute(
                """SELECT alert_type, severity, description, created_at
                   FROM ethics_alerts WHERE status != 'resolved'
                   ORDER BY created_at DESC LIMIT 3"""
            )
            for row in cur.fetchall():
                alerts.append(
                    {
                        "type": "ethics",
                        "title": f"Ethics: {row['alert_type'].replace('_', ' ').title()}",
                        "message": row["description"],
                        "priority": row["severity"] or "warning",
                        "timestamp": _ts(row["created_at"]),
                    }
                )

            # 8. User notifications (unread)
            cur.execute(
                """SELECT type, title, message, priority, created_at
                   FROM notifications
                   WHERE user_id = %s AND is_read = FALSE
                   ORDER BY created_at DESC LIMIT 5""",
                (user_id,),
            )
            for n in cur.fetchall():
                alerts.append(
                    {
                        "type": n["type"],
                        "title": n["title"],
                        "message": n["message"],
                        "priority": n["priority"] or "normal",
                        "timestamp": _ts(n["created_at"]),
                    }
                )

            # Sort by priority
            prio_weight = {"critical": 0, "high": 1, "medium": 2, "normal": 3, "low": 4}
            alerts.sort(key=lambda a: prio_weight.get(a["priority"], 3))

            return {"alerts": alerts[:10], "service_issues": service_issues}
        finally:
            cur.close()
