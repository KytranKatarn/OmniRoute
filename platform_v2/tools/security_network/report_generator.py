"""Weekly security report generator.

Produces a structured report dict (and optional HTML) summarizing:
  - Bandwidth by user/device
  - Top blocked domains
  - Anomaly detection findings
  - New devices discovered
  - Compliance score trend
  - V.I.G.I.L. threat summary
  - Speed test trend (if available)
"""

import logging
from datetime import datetime

from database import get_db_cursor

logger = logging.getLogger(__name__)


def _safe_int(val):
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


def _fmt_bytes(b):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(b) < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def generate_weekly_report():
    """Generate a comprehensive weekly security report.

    Returns dict with all report sections.
    """
    report = {
        "generated_at": datetime.now().isoformat(),
        "period": "7 days",
        "sections": {},
    }

    try:
        with get_db_cursor() as (conn, cur):
            # --- 1. Bandwidth by user ---
            cur.execute(
                """
                SELECT
                    COALESCE(ndu.user_name, 'Unknown') AS user_name,
                    COUNT(DISTINCT nts.device_ip) AS device_count,
                    SUM(nts.bytes_in) AS bytes_in,
                    SUM(nts.bytes_out) AS bytes_out,
                    SUM(nts.bytes_in + nts.bytes_out) AS bytes_total
                FROM network_traffic_stats nts
                LEFT JOIN network_device_users ndu ON ndu.mac_address = nts.device_mac
                WHERE nts.hour_bucket >= NOW() - INTERVAL '7 days'
                GROUP BY COALESCE(ndu.user_name, 'Unknown')
                ORDER BY bytes_total DESC
            """
            )
            users = []
            for row in cur.fetchall():
                users.append(
                    {
                        "user": row["user_name"],
                        "devices": row["device_count"],
                        "download": _fmt_bytes(_safe_int(row["bytes_in"])),
                        "upload": _fmt_bytes(_safe_int(row["bytes_out"])),
                        "total": _fmt_bytes(_safe_int(row["bytes_total"])),
                        "total_bytes": _safe_int(row["bytes_total"]),
                    }
                )
            report["sections"]["bandwidth_by_user"] = users

            # --- 2. Top bandwidth devices ---
            cur.execute(
                """
                SELECT
                    nts.device_ip,
                    COALESCE(ndu.device_label, nts.device_ip) AS label,
                    COALESCE(ndu.user_name, 'Unknown') AS user_name,
                    SUM(nts.bytes_in + nts.bytes_out) AS bytes_total
                FROM network_traffic_stats nts
                LEFT JOIN network_device_users ndu ON ndu.mac_address = nts.device_mac
                WHERE nts.hour_bucket >= NOW() - INTERVAL '7 days'
                GROUP BY nts.device_ip, ndu.device_label, ndu.user_name
                ORDER BY bytes_total DESC
                LIMIT 10
            """
            )
            top_devices = []
            for row in cur.fetchall():
                top_devices.append(
                    {
                        "ip": row["device_ip"],
                        "label": row["label"],
                        "user": row["user_name"],
                        "total": _fmt_bytes(_safe_int(row["bytes_total"])),
                    }
                )
            report["sections"]["top_devices"] = top_devices

            # --- 3. Top blocked domains ---
            cur.execute(
                """
                SELECT domain, SUM(query_count) AS blocked_count
                FROM device_dns_history
                WHERE blocked = true
                  AND hour_bucket >= NOW() - INTERVAL '7 days'
                GROUP BY domain
                ORDER BY blocked_count DESC
                LIMIT 15
            """
            )
            blocked = [{"domain": row["domain"], "count": int(row["blocked_count"])} for row in cur.fetchall()]
            report["sections"]["top_blocked_domains"] = blocked

            # --- 4. Anomaly summary ---
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM system_notifications
                WHERE source = 'security_network'
                  AND title LIKE 'Anomaly Digest%%'
                  AND created_at >= NOW() - INTERVAL '7 days'
            """
            )
            row = cur.fetchone()
            anomaly_digests = _safe_int(row["cnt"]) if row else 0

            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM system_notifications
                WHERE source = 'security_network'
                  AND title LIKE '%%exfiltration%%'
                  AND created_at >= NOW() - INTERVAL '7 days'
            """
            )
            row = cur.fetchone()
            exfil_alerts = _safe_int(row["cnt"]) if row else 0

            report["sections"]["anomalies"] = {
                "digest_count": anomaly_digests,
                "exfiltration_alerts": exfil_alerts,
            }

            # --- 5. New devices ---
            cur.execute(
                """
                SELECT device_ip, device_mac,
                       MIN(detected_at) AS first_seen
                FROM device_presence_log
                WHERE event_type = 'online'
                  AND detected_at >= NOW() - INTERVAL '7 days'
                GROUP BY device_ip, device_mac
                HAVING MIN(detected_at) >= NOW() - INTERVAL '7 days'
                ORDER BY first_seen DESC
                LIMIT 20
            """
            )
            new_devices = [
                {
                    "ip": row["device_ip"],
                    "mac": row["device_mac"],
                    "first_seen": row["first_seen"].isoformat() if row["first_seen"] else None,
                }
                for row in cur.fetchall()
            ]
            report["sections"]["new_devices"] = new_devices

            # --- 6. Compliance score ---
            cur.execute(
                """
                SELECT score, started_at
                FROM compliance_scans
                WHERE completed_at IS NOT NULL
                ORDER BY started_at DESC
                LIMIT 5
            """
            )
            scores = [{"score": float(row["score"]), "date": row["started_at"].isoformat()} for row in cur.fetchall()]
            report["sections"]["compliance_trend"] = scores

            # --- 7. Security incidents ---
            cur.execute(
                """
                SELECT COUNT(*) FILTER (WHERE status = 'open') AS open_incidents,
                       COUNT(*) FILTER (WHERE status = 'resolved') AS resolved_incidents,
                       COUNT(*) AS total_incidents
                FROM security_incidents
                WHERE created_at >= NOW() - INTERVAL '7 days'
            """
            )
            row = cur.fetchone()
            report["sections"]["incidents"] = {
                "open": _safe_int(row["open_incidents"]) if row else 0,
                "resolved": _safe_int(row["resolved_incidents"]) if row else 0,
                "total": _safe_int(row["total_incidents"]) if row else 0,
            }

            # --- 8. Threat intel hits ---
            cur.execute(
                """
                SELECT COUNT(*) AS hit_count
                FROM threat_intel_hits
                WHERE detected_at >= NOW() - INTERVAL '7 days'
            """
            )
            row = cur.fetchone()
            report["sections"]["threat_intel_hits"] = _safe_int(row["hit_count"]) if row else 0

            # --- 9. Speed test trend ---
            cur.execute(
                """
                SELECT download_mbps, upload_mbps, ping_ms, tested_at
                FROM speed_test_results
                WHERE tested_at >= NOW() - INTERVAL '7 days'
                ORDER BY tested_at DESC
                LIMIT 10
            """
            )
            speed_tests = [
                {
                    "download": float(row["download_mbps"]) if row["download_mbps"] else 0,
                    "upload": float(row["upload_mbps"]) if row["upload_mbps"] else 0,
                    "ping": float(row["ping_ms"]) if row["ping_ms"] else 0,
                    "date": row["tested_at"].isoformat(),
                }
                for row in cur.fetchall()
            ]
            report["sections"]["speed_tests"] = speed_tests

            # --- 10. DNS summary ---
            cur.execute(
                """
                SELECT
                    COUNT(DISTINCT device_ip) AS active_devices,
                    SUM(query_count) AS total_queries,
                    SUM(CASE WHEN blocked THEN query_count ELSE 0 END) AS blocked_queries,
                    COUNT(DISTINCT domain) AS unique_domains
                FROM device_dns_history
                WHERE hour_bucket >= NOW() - INTERVAL '7 days'
            """
            )
            row = cur.fetchone()
            report["sections"]["dns_summary"] = {
                "active_devices": _safe_int(row["active_devices"]) if row else 0,
                "total_queries": _safe_int(row["total_queries"]) if row else 0,
                "blocked_queries": _safe_int(row["blocked_queries"]) if row else 0,
                "unique_domains": _safe_int(row["unique_domains"]) if row else 0,
            }

    except Exception as e:
        logger.error("[ReportGenerator] Failed to generate weekly report: %s", e)
        report["error"] = str(e)

    return report


def format_report_telegram(report):
    """Format a report dict into a Telegram-friendly text message."""
    sections = report.get("sections", {})
    lines = ["📊 Weekly Security Report", ""]

    # Bandwidth
    users = sections.get("bandwidth_by_user", [])
    if users:
        lines.append("💾 Bandwidth by User:")
        for u in users[:5]:
            lines.append(f"  {u['user']}: {u['total']} ({u['devices']} devices)")
        lines.append("")

    # Top blocked
    blocked = sections.get("top_blocked_domains", [])
    if blocked:
        lines.append("🚫 Top Blocked Domains:")
        for b in blocked[:5]:
            lines.append(f"  {b['domain']}: {b['count']}")
        lines.append("")

    # Anomalies
    anomalies = sections.get("anomalies", {})
    lines.append(
        f"⚠️ Anomalies: {anomalies.get('digest_count', 0)} digests, "
        f"{anomalies.get('exfiltration_alerts', 0)} exfil alerts"
    )

    # Incidents
    incidents = sections.get("incidents", {})
    lines.append(f"🔒 Incidents: {incidents.get('open', 0)} open, " f"{incidents.get('resolved', 0)} resolved")

    # Threat intel
    hits = sections.get("threat_intel_hits", 0)
    lines.append(f"🎯 Threat Intel Hits: {hits}")

    # New devices
    new_devs = sections.get("new_devices", [])
    lines.append(f"📱 New Devices: {len(new_devs)}")

    # Compliance
    scores = sections.get("compliance_trend", [])
    if scores:
        lines.append(f"✅ Compliance: {scores[0]['score']}%")

    # DNS
    dns = sections.get("dns_summary", {})
    lines.append(
        f"🌐 DNS: {dns.get('total_queries', 0):,} queries, "
        f"{dns.get('blocked_queries', 0):,} blocked, "
        f"{dns.get('unique_domains', 0):,} domains"
    )

    return "\n".join(lines)
