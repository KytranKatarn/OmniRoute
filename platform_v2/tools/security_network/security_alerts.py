"""Security alert helper — creates system_notifications and optionally forwards to Telegram.

Supports two delivery modes:
  1. Immediate — one Telegram message per alert (default for critical/high)
  2. Digest   — multiple findings batched into one Telegram summary message
     Use ``create_security_digest()`` to send a single grouped notification.
"""

import logging
from database import get_db_cursor

logger = logging.getLogger(__name__)

# Priority → notification type mapping
PRIORITY_TYPE_MAP = {
    "critical": "error",
    "high": "warning",
    "normal": "info",
    "low": "info",
}

# Valid alert types
VALID_ALERT_TYPES = {
    "intrusion",
    "block",
    "recommendation",
    "ssl_expiry",
    "dns_change",
    "motion",
    "scan_result",
    "new_device",
}


def _get_alert_config():
    """Load alert config from security_auto_block_settings table.

    Returns dict of alert_type -> {"enabled": bool, "telegram": bool}.
    Defaults to all enabled with Telegram for high/critical.
    """
    defaults = {
        "intrusion": {"enabled": True, "telegram": True, "digest": True},
        "block": {"enabled": True, "telegram": True, "digest": False},
        "ssl_expiry": {"enabled": True, "telegram": True, "digest": False},
        "dns_change": {"enabled": True, "telegram": False, "digest": True},
        "motion": {"enabled": True, "telegram": True, "digest": False},
        "scan_result": {"enabled": True, "telegram": False, "digest": True},
        "new_device": {"enabled": True, "telegram": True, "digest": True},
    }

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT setting_value FROM security_auto_block_settings WHERE setting_key = 'alert_config'")
            row = cur.fetchone()

            if row:
                import json

                return json.loads(row["setting_value"])
    except Exception as e:
        logger.warning(f"[SecurityAlerts] Failed to load alert config: {e}")

    return defaults


def create_security_alert(alert_type, title, message, priority="high", telegram=True):
    """
    Create a security alert notification.

    alert_type: 'intrusion', 'block', 'ssl_expiry', 'dns_change', 'motion', 'scan_result'
    priority: 'low', 'normal', 'high', 'critical'
    telegram: whether to forward to Telegram (can be overridden by config)
    """
    if alert_type not in VALID_ALERT_TYPES:
        logger.warning(f"[SecurityAlerts] Unknown alert_type: {alert_type}")

    notif_type = PRIORITY_TYPE_MAP.get(priority, "info")

    # Check per-type config
    config = _get_alert_config()
    type_config = config.get(alert_type, {"enabled": True, "telegram": telegram})

    if not type_config.get("enabled", True):
        logger.debug(f"[SecurityAlerts] Alert type '{alert_type}' disabled by config")
        return None

    # Override telegram flag from config
    send_telegram = telegram and type_config.get("telegram", telegram)
    # Always send Telegram for critical/high if telegram param is True
    if priority in ("critical", "high") and telegram:
        send_telegram = True

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            # Insert notification — Telegram daemon picks up rows where telegram_forwarded=false
            cur.execute(
                """
                INSERT INTO system_notifications
                    (type, title, message, source, visibility, priority, telegram_forwarded)
                VALUES (%s, %s, %s, 'security_network', 'admin', %s, %s)
                RETURNING id
                """,
                (
                    notif_type,
                    title[:255],
                    message,
                    priority,
                    not send_telegram,  # false = daemon will forward; true = skip
                ),
            )
            row = cur.fetchone()

            notif_id = row["id"] if row else None
            logger.info(
                f"[SecurityAlerts] Created alert #{notif_id}: {alert_type} / {priority} — "
                f"telegram={'pending' if send_telegram else 'skipped'}"
            )
            return notif_id

    except Exception as e:
        logger.error(f"[SecurityAlerts] Failed to create alert: {e}")
        return None


def create_security_digest(alert_type, title, findings, priority="high", telegram=True):
    """Create ONE notification that summarises multiple findings.

    Each finding in *findings* is a dict with at least ``"line"`` (str) —
    a single human-readable summary line.  Optional keys: ``"device_ip"``,
    ``"detail"`` (extra context shown only in the DB row, not Telegram).

    The Telegram message looks like:
        🔒 Anomaly Digest — 12 findings
        • Bandwidth spike: 192.168.1.42 (8.3x)
        • DNS tunneling suspect: 192.168.1.15
        …

    All individual findings are still stored in the ``message`` column for
    full dashboard inspection.
    """
    if not findings:
        return None

    # Build a concise body (max 30 lines for Telegram readability)
    lines = [f.get("line", str(f)) for f in findings]
    summary_lines = lines[:30]
    if len(lines) > 30:
        summary_lines.append(f"… and {len(lines) - 30} more")

    message = "\n".join(f"• {l}" for l in summary_lines)
    full_title = f"{title} — {len(findings)} finding{'s' if len(findings) != 1 else ''}"

    return create_security_alert(
        alert_type=alert_type,
        title=full_title,
        message=message,
        priority=priority,
        telegram=telegram,
    )
