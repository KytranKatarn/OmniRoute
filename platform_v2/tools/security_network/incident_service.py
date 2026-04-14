"""
Incident Correlation Service
=============================
Correlate security alerts into incidents for triage and resolution.
"""

import logging
import re
from collections import defaultdict

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Matches IPv4 addresses in notification titles/messages
_IP_PATTERN = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")


class IncidentService:
    """Group related security alerts into actionable incidents."""

    def correlate_alerts(self):
        """Find recent security alerts and group by device IP into incidents.

        Runs periodically.  For each device IP with 3+ unlinked alerts in
        the last hour, creates a security_incidents row linking them.
        """
        with get_db_cursor(commit=True) as (conn, cur):
            # Fetch security_network alerts from last 2 hours that are
            # not already linked to an incident.
            cur.execute(
                """
                SELECT sn.id, sn.title, sn.message, sn.type, sn.created_at
                FROM system_notifications sn
                WHERE sn.source = 'security_network'
                  AND sn.created_at > NOW() - INTERVAL '2 hours'
                  AND NOT EXISTS (
                      SELECT 1 FROM security_incidents si
                      WHERE sn.id = ANY(si.alert_ids)
                  )
                ORDER BY sn.created_at DESC
                """
            )
            alerts = cur.fetchall()

        if not alerts:
            return {"incidents_created": 0}

        # Group alerts by extracted device IP
        ip_groups = defaultdict(list)
        for alert in alerts:
            text = f"{alert['title']} {alert.get('message', '')}"
            match = _IP_PATTERN.search(text)
            if match:
                ip_groups[match.group(1)].append(alert)

        # Filter to IPs with 3+ alerts within a 1-hour window
        created = 0
        for ip, group_alerts in ip_groups.items():
            if len(group_alerts) < 3:
                continue

            # Use the most recent 1-hour window
            group_alerts.sort(key=lambda a: a["created_at"], reverse=True)
            window_start = group_alerts[0]["created_at"]
            correlated = [a for a in group_alerts if (window_start - a["created_at"]).total_seconds() <= 3600]
            if len(correlated) < 3:
                continue

            severity = self._highest_severity([a["type"] for a in correlated])
            alert_ids = [a["id"] for a in correlated]
            title = f"Correlated incident: {len(correlated)} alerts from {ip}"

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO security_incidents
                        (title, severity, device_ip, alert_ids, status)
                    VALUES (%s, %s, %s, %s, 'open')
                    RETURNING id
                    """,
                    (title, severity, ip, alert_ids),
                )
                created += 1

        logger.info("Alert correlation: %d incidents created", created)
        return {"incidents_created": created}

    def get_incidents(self, status="open", limit=50):
        """Return incidents filtered by status."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT * FROM security_incidents
                WHERE status = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (status, limit),
            )
            return cur.fetchall()

    def resolve_incident(self, incident_id, notes=None):
        """Mark an incident as resolved."""
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE security_incidents
                SET status = 'resolved', resolved_at = NOW(), notes = %s
                WHERE id = %s AND status != 'resolved'
                """,
                (notes, incident_id),
            )
            return cur.rowcount > 0

    def get_incident_detail(self, incident_id):
        """Return a single incident with its linked alert messages."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT * FROM security_incidents WHERE id = %s",
                (incident_id,),
            )
            incident = cur.fetchone()
            if not incident:
                return None

            alert_ids = incident.get("alert_ids") or []
            alerts = []
            if alert_ids:
                cur.execute(
                    """
                    SELECT id, title, message, type, created_at
                    FROM system_notifications
                    WHERE id = ANY(%s)
                    ORDER BY created_at DESC
                    """,
                    (alert_ids,),
                )
                alerts = cur.fetchall()

            result = dict(incident)
            result["alerts"] = [dict(a) for a in alerts]
            return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _highest_severity(levels):
        """Return the highest severity from a list of notification levels."""
        priority = {"error": 4, "alert": 3, "warning": 2, "info": 1}
        best = "info"
        best_score = 0
        for lvl in levels:
            score = priority.get(lvl, 0)
            if score > best_score:
                best_score = score
                best = lvl
        # Map notification levels to incident severity
        severity_map = {"error": "critical", "alert": "high", "warning": "medium", "info": "low"}
        return severity_map.get(best, "normal")
