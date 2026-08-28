"""
Security Service for Internal Protection
========================================
Provides firewall status, active connections, brute force detection,
SSL certificate monitoring, and auto-block functionality.
"""

import json
import socket
import ssl
from datetime import datetime, timedelta
from typing import Dict, Any, List
from psycopg2.extras import Json
from database import get_db_cursor

# ============================================================================
# FIREWALL STATUS
# ============================================================================


def get_firewall_status() -> Dict[str, Any]:
    """Get firewall status via host_command_client (UFW owned by System Operations).

    Uses the same ``submit_and_wait("firewall_status", ...)`` command that
    System Operations' firewall_routes.py uses, keeping a clean boundary:
    Security Network reads status but does NOT duplicate the Docker/iptables
    logic or import System Operations internals.
    """
    try:
        from tools.system_operations.host_command_client import (
            submit_and_wait,
            is_queue_available,
        )

        if not is_queue_available():
            return {"enabled": False, "rules": [], "status": "unknown"}

        result_data = submit_and_wait("firewall_status", {}, timeout=60, submitted_by="security_network")
        cmd_result = result_data.get("result", {})

        if cmd_result.get("success"):
            return {
                "enabled": cmd_result.get("active", False),
                "rules": [],
                "status": "active" if cmd_result.get("active") else "inactive",
            }
        return {"enabled": False, "rules": [], "status": "unknown"}
    except Exception as e:
        return {"enabled": False, "rules": [], "status": "error", "error": str(e)}


def get_active_connections() -> List[Dict[str, Any]]:
    """Get active network connections"""
    connections = []

    try:
        import docker

        client = docker.from_env()

        # Get connections from archie platform container
        container = client.containers.get("archie_platform")
        exec_result = container.exec_run(["netstat", "-tunapl"], demux=True)

        if exec_result.exit_code == 0 and exec_result.output[0]:
            lines = exec_result.output[0].decode().split("\n")
            for line in lines[2:]:  # Skip headers
                parts = line.split()
                if len(parts) >= 6:
                    connections.append(
                        {
                            "protocol": parts[0],
                            "recv_q": int(parts[1]) if parts[1].isdigit() else 0,
                            "send_q": int(parts[2]) if parts[2].isdigit() else 0,
                            "local_address": parts[3],
                            "foreign_address": parts[4],
                            "state": parts[5] if len(parts) > 5 else "",
                            "process": parts[6] if len(parts) > 6 else "",
                        }
                    )
    except Exception:
        # Fallback: try psutil if available
        try:
            import psutil

            for conn in psutil.net_connections(kind="inet"):
                connections.append(
                    {
                        "protocol": "tcp" if conn.type == socket.SOCK_STREAM else "udp",
                        "local_address": (f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else ""),
                        "foreign_address": (f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else ""),
                        "state": conn.status,
                        "pid": conn.pid,
                    }
                )
        except Exception:
            pass

    return connections


# ============================================================================
# BRUTE FORCE DETECTION
# ============================================================================


def analyze_failed_logins(hours: int = 24) -> Dict[str, Any]:
    """Analyze failed login attempts for brute force detection"""
    with get_db_cursor(commit=False) as (conn, cur):

        # Get failed logins grouped by IP
        cur.execute(
            """
            SELECT
                details->>'ip' as ip_address,
                COUNT(*) as attempt_count,
                MIN(created_at) as first_attempt,
                MAX(created_at) as last_attempt,
                array_agg(DISTINCT details->>'username') as usernames
            FROM audit_log
            WHERE action = 'login_failed'
              AND created_at > NOW() - (%s * INTERVAL '1 hour')
              AND details->>'ip' IS NOT NULL
            GROUP BY details->>'ip'
            ORDER BY attempt_count DESC
            LIMIT 50
        """,
            (hours,),
        )

        suspicious_ips = cur.fetchall()

        # Get auto-block settings
        cur.execute(
            """
            SELECT setting_key, setting_value
            FROM security_auto_block_settings
        """
        )
        settings = {row["setting_key"]: row["setting_value"] for row in cur.fetchall()}

        threshold = int(settings.get("failed_login_threshold", 5))
        window = int(settings.get("failed_login_window_minutes", 15))

        # Categorize threats
        threats = []
        for ip in suspicious_ips:
            if ip["attempt_count"] >= threshold:
                threats.append(
                    {
                        "ip_address": ip["ip_address"],
                        "attempts": ip["attempt_count"],
                        "first_seen": (ip["first_attempt"].isoformat() if ip["first_attempt"] else None),
                        "last_seen": (ip["last_attempt"].isoformat() if ip["last_attempt"] else None),
                        "usernames": ip["usernames"],
                        "severity": (
                            "critical"
                            if ip["attempt_count"] > threshold * 3
                            else ("high" if ip["attempt_count"] > threshold * 2 else "medium")
                        ),
                    }
                )

        return {
            "total_failures": sum(ip["attempt_count"] for ip in suspicious_ips),
            "unique_ips": len(suspicious_ips),
            "threats": threats,
            "threshold": threshold,
            "window_minutes": window,
        }


def get_auto_block_settings() -> Dict[str, Any]:
    """Get auto-block configuration"""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT setting_key, setting_value FROM security_auto_block_settings")
        settings = {}
        for row in cur.fetchall():
            value = row["setting_value"]
            # Try to parse JSON values
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                # Try to parse as number
                if value.isdigit():
                    value = int(value)
                elif value.lower() in ("true", "false"):
                    value = value.lower() == "true"
            settings[row["setting_key"]] = value

        return settings


def update_auto_block_settings(settings: Dict[str, Any], user_id: int) -> bool:
    """Update auto-block configuration"""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            for key, value in settings.items():
                if isinstance(value, (list, dict)):
                    value = json.dumps(value)
                else:
                    value = str(value)

                cur.execute(
                    """
                    UPDATE security_auto_block_settings
                    SET setting_value = %s, updated_by = %s, updated_at = NOW()
                    WHERE setting_key = %s
                """,
                    (value, user_id, key),
                )

        return True
    except Exception:
        return False


# ============================================================================
# IP ACCESS CONTROL
# ============================================================================


def block_ip(ip_address: str, reason: str, user_id: int = None, duration_hours: int = None) -> Dict[str, Any]:
    """Block an IP address"""
    try:
        expires_at = None
        if duration_hours:
            expires_at = datetime.now() + timedelta(hours=duration_hours)

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO security_ip_access (ip_address, access_type, reason, source, expires_at, created_by)
                VALUES (%s::inet, 'block', %s, 'manual', %s, %s)
                ON CONFLICT (ip_address) DO UPDATE
                SET access_type = 'block',
                    reason = EXCLUDED.reason,
                    expires_at = EXCLUDED.expires_at,
                    is_active = TRUE,
                    updated_at = NOW()
                RETURNING *
            """,
                (ip_address, reason, expires_at, user_id),
            )

            result = cur.fetchone()

            # Log the action
            cur.execute(
                """
                INSERT INTO audit_log (action, user_id, details)
                VALUES ('ip_blocked', %s, %s)
            """,
                (user_id, Json({"ip": ip_address, "reason": reason})),
            )

            # Create security event
            cur.execute(
                """
                INSERT INTO security_events (event_type, severity, source_ip, description, status)
                VALUES ('ip_blocked', 'medium', %s::inet, %s, 'resolved')
            """,
                (ip_address, f"IP blocked: {reason}"),
            )

        return {"success": True, "blocked": dict(result) if result else None}
    except Exception as e:
        return {"success": False, "error": str(e)}


def unblock_ip(ip_address: str, user_id: int = None) -> Dict[str, Any]:
    """Unblock an IP address"""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE security_ip_access
                SET is_active = FALSE, updated_at = NOW()
                WHERE ip_address = %s::inet AND is_active = TRUE
            """,
                (ip_address,),
            )

            affected = cur.rowcount

            if affected > 0:
                cur.execute(
                    """
                    INSERT INTO audit_log (action, user_id, details)
                    VALUES ('ip_unblocked', %s, %s)
                """,
                    (user_id, Json({"ip": ip_address})),
                )

        return {"success": True, "unblocked": affected > 0}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_blocked_ips() -> List[Dict[str, Any]]:
    """Get list of currently blocked IPs"""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT ip_address::text, access_type, reason, source,
                   expires_at, blocked_count, created_at
            FROM security_ip_access
            WHERE access_type = 'block' AND is_active = TRUE
            ORDER BY created_at DESC
        """
        )
        return [dict(row) for row in cur.fetchall()]


def get_whitelisted_ips() -> List[Dict[str, Any]]:
    """Get list of whitelisted IPs"""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT ip_address::text, reason, created_at
            FROM security_ip_access
            WHERE access_type IN ('allow', 'whitelist') AND is_active = TRUE
            ORDER BY created_at DESC
        """
        )
        return [dict(row) for row in cur.fetchall()]


def auto_block_threats(user_id: int = None) -> Dict[str, Any]:
    """Automatically block detected threats based on settings"""
    settings = get_auto_block_settings()

    if not settings.get("enabled", True):
        return {"success": True, "blocked": 0, "message": "Auto-block is disabled"}

    analysis = analyze_failed_logins(hours=1)
    whitelist = settings.get("whitelist_ips", [])
    duration = int(settings.get("block_duration_hours", 24))

    blocked_count = 0
    blocked_ips = []

    for threat in analysis.get("threats", []):
        ip = threat["ip_address"]

        # Skip whitelisted IPs
        if ip in whitelist:
            continue

        # Block the IP
        result = block_ip(ip, f"Auto-blocked: {threat['attempts']} failed logins", user_id, duration)

        if result.get("success"):
            blocked_count += 1
            blocked_ips.append(ip)

    return {
        "success": True,
        "blocked": blocked_count,
        "blocked_ips": blocked_ips,
        "analyzed_threats": len(analysis.get("threats", [])),
    }


# ============================================================================
# SECURITY EVENTS
# ============================================================================


def get_security_events(
    status: str = None, severity: str = None, event_type: str = None, limit: int = 50
) -> List[Dict[str, Any]]:
    """Get security events with filters"""
    with get_db_cursor(commit=False) as (conn, cur):
        query = "SELECT * FROM security_events WHERE 1=1"
        params = []

        if status:
            query += " AND status = %s"
            params.append(status)
        if severity:
            query += " AND severity = %s"
            params.append(severity)
        if event_type:
            query += " AND event_type = %s"
            params.append(event_type)

        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        events = cur.fetchall()

        return [dict(e) for e in events]


def create_security_event(
    event_type: str,
    severity: str,
    description: str,
    source_ip: str = None,
    target_ip: str = None,
    raw_data: dict = None,
) -> Dict[str, Any]:
    """Create a security event"""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO security_events
                (event_type, severity, description, source_ip, target_ip, raw_data)
                VALUES (%s, %s, %s, %s::inet, %s::inet, %s)
                RETURNING *
            """,
                (
                    event_type,
                    severity,
                    description,
                    source_ip,
                    target_ip,
                    Json(raw_data) if raw_data else None,
                ),
            )

            event = cur.fetchone()

        return {"success": True, "event": dict(event) if event else None}
    except Exception as e:
        return {"success": False, "error": str(e)}


def resolve_security_event(event_id: int, user_id: int, notes: str = None) -> Dict[str, Any]:
    """Resolve a security event"""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE security_events
                SET status = 'resolved', resolved_by = %s, resolved_at = NOW(), resolution_notes = %s
                WHERE id = %s
            """,
                (user_id, notes, event_id),
            )

            resolved = cur.rowcount > 0

        return {"success": True, "resolved": resolved}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# SSL CERTIFICATE MONITORING
# ============================================================================


def check_ssl_certificate(domain: str, port: int = 443) -> Dict[str, Any]:
    """Check SSL certificate for a domain"""
    try:
        context = ssl.create_default_context()

        with socket.create_connection((domain, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                cipher = ssock.cipher()
                version = ssock.version()

        # Parse certificate dates
        not_before = datetime.strptime(cert["notBefore"], "%b %d %H:%M:%S %Y %Z")
        not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
        days_until_expiry = (not_after - datetime.now()).days

        # Get subject and issuer
        subject = dict(x[0] for x in cert.get("subject", []))
        issuer = dict(x[0] for x in cert.get("issuer", []))

        # Determine grade
        grade = "A"
        if days_until_expiry < 30:
            grade = "B"
        if days_until_expiry < 7:
            grade = "C"
        if version in ("TLSv1", "TLSv1.1"):
            grade = "D"

        return {
            "success": True,
            "domain": domain,
            "valid": True,
            "issuer": issuer.get("organizationName", issuer.get("commonName", "Unknown")),
            "subject": subject.get("commonName", domain),
            "valid_from": not_before.isoformat(),
            "valid_until": not_after.isoformat(),
            "days_until_expiry": days_until_expiry,
            "protocol_version": version,
            "cipher_suite": cipher[0] if cipher else None,
            "grade": grade,
        }
    except ssl.SSLCertVerificationError as e:
        return {
            "success": True,
            "domain": domain,
            "valid": False,
            "error": str(e),
            "grade": "F",
        }
    except Exception as e:
        return {"success": False, "domain": domain, "error": str(e)}


def add_ssl_monitor(domain: str, user_id: int, alert_days: int = 30) -> Dict[str, Any]:
    """Add a domain to SSL monitoring"""
    # First check the certificate
    check_result = check_ssl_certificate(domain)

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO security_ssl_monitors
                (domain, issuer, subject, valid_from, valid_until, days_until_expiry,
                 protocol_version, cipher_suite, grade, alert_days_before, created_by, last_checked_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (domain) DO UPDATE
                SET issuer = EXCLUDED.issuer,
                    subject = EXCLUDED.subject,
                    valid_from = EXCLUDED.valid_from,
                    valid_until = EXCLUDED.valid_until,
                    days_until_expiry = EXCLUDED.days_until_expiry,
                    protocol_version = EXCLUDED.protocol_version,
                    cipher_suite = EXCLUDED.cipher_suite,
                    grade = EXCLUDED.grade,
                    last_checked_at = NOW(),
                    updated_at = NOW()
                RETURNING *
            """,
                (
                    domain,
                    check_result.get("issuer"),
                    check_result.get("subject"),
                    check_result.get("valid_from"),
                    check_result.get("valid_until"),
                    check_result.get("days_until_expiry"),
                    check_result.get("protocol_version"),
                    check_result.get("cipher_suite"),
                    check_result.get("grade", "F"),
                    alert_days,
                    user_id,
                ),
            )

            monitor = cur.fetchone()

        return {
            "success": True,
            "monitor": dict(monitor) if monitor else None,
            "check": check_result,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_ssl_monitors() -> List[Dict[str, Any]]:
    """Get all SSL monitors"""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT * FROM security_ssl_monitors
            WHERE is_active = TRUE
            ORDER BY days_until_expiry ASC
        """
        )
        return [dict(row) for row in cur.fetchall()]


def refresh_ssl_monitors() -> Dict[str, Any]:
    """Refresh all SSL monitors"""
    monitors = get_ssl_monitors()
    updated = 0
    alerts = []

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            for monitor in monitors:
                check = check_ssl_certificate(monitor["domain"])

                if check.get("success"):
                    cur.execute(
                        """
                        UPDATE security_ssl_monitors
                        SET issuer = %s, subject = %s, valid_from = %s, valid_until = %s,
                            days_until_expiry = %s, protocol_version = %s, cipher_suite = %s,
                            grade = %s, last_checked_at = NOW(), updated_at = NOW()
                        WHERE domain = %s
                    """,
                        (
                            check.get("issuer"),
                            check.get("subject"),
                            check.get("valid_from"),
                            check.get("valid_until"),
                            check.get("days_until_expiry"),
                            check.get("protocol_version"),
                            check.get("cipher_suite"),
                            check.get("grade", "F"),
                            monitor["domain"],
                        ),
                    )
                    updated += 1

                    # Check if alert needed
                    days = check.get("days_until_expiry", 0)
                    if days <= monitor.get("alert_days_before", 30):
                        alerts.append(
                            {
                                "domain": monitor["domain"],
                                "days_until_expiry": days,
                                "grade": check.get("grade"),
                            }
                        )

        return {"success": True, "updated": updated, "alerts": alerts}
    except Exception as e:
        return {"success": False, "error": str(e)}
