"""Monitoring Service — Nagios status.dat parser, DB sync, alerting, and config generation.

Reads Nagios status.dat (mounted at /opt/nagios-data/status.dat), parses host and
service check results, syncs state to monitoring_checks table, and fires Telegram
alerts on critical state changes with cooldown deduplication.

Import:
    from services.monitoring_service import (
        parse_status_dat, get_unified_health, get_host_checks,
        sync_checks_to_db, process_alerts,
        generate_node_config, remove_node_config, reload_nagios,
    )
"""

import logging
import os
import re
import subprocess
import time
from datetime import datetime, timezone

from jinja2 import Environment, FileSystemLoader

from database import get_db_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STATUS_DAT_PATH = "/opt/nagios-data/status.dat"
NAGIOS_TEMPLATE_DIR = "/mnt/archie_brain/monitoring/nagios-templates"
NAGIOS_CONF_DIR = "/mnt/archie_brain/monitoring/nagios-conf.d"

STATE_MAP = {0: "ok", 1: "warning", 2: "critical", 3: "unknown"}

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache = {"data": None, "ts": 0}
_CACHE_TTL = 15  # seconds


# ---------------------------------------------------------------------------
# 1. parse_status_dat
# ---------------------------------------------------------------------------


def parse_status_dat():
    """Parse Nagios status.dat and return host + service check data.

    Returns:
        dict: {"hosts": {name: {...}}, "services": {"host:service": {...}}}
    """
    now = time.time()
    if _cache["data"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["data"]

    result = {"hosts": {}, "services": {}}

    try:
        with open(STATUS_DAT_PATH, "r") as f:
            content = f.read()
    except FileNotFoundError:
        logger.warning("status.dat not found at %s", STATUS_DAT_PATH)
        return result
    except Exception as exc:
        logger.error("Failed to read status.dat: %s", exc)
        return result

    # Match hoststatus and servicestatus blocks
    block_re = re.compile(r"(hoststatus|servicestatus)\s*\{([^}]+)\}", re.DOTALL)

    for match in block_re.finditer(content):
        block_type = match.group(1)
        body = match.group(2)

        # Parse key=value pairs
        fields = {}
        for line in body.strip().splitlines():
            line = line.strip()
            if "=" in line:
                key, _, value = line.partition("=")
                fields[key.strip()] = value.strip()

        # Map numeric state to string
        raw_state = int(fields.get("current_state", 3))
        fields["status"] = STATE_MAP.get(raw_state, "unknown")

        if block_type == "hoststatus":
            host_name = fields.get("host_name", "unknown")
            result["hosts"][host_name] = fields
        else:
            host_name = fields.get("host_name", "unknown")
            svc_desc = fields.get("service_description", "unknown")
            key = f"{host_name}:{svc_desc}"
            result["services"][key] = fields

    _cache["data"] = result
    _cache["ts"] = now
    return result


# ---------------------------------------------------------------------------
# 2. get_unified_health
# ---------------------------------------------------------------------------


def get_unified_health():
    """Group Nagios checks by host with summary status.

    Returns:
        dict: keyed by host_name, each with "host", "services", and "summary".
    """
    data = parse_status_dat()
    nodes = {}

    # Seed with host checks
    for host_name, host_fields in data["hosts"].items():
        nodes[host_name] = {
            "host": host_fields,
            "services": [],
            "summary": host_fields.get("status", "unknown"),
        }

    # Attach service checks
    for key, svc_fields in data["services"].items():
        host_name = svc_fields.get("host_name", "unknown")
        if host_name not in nodes:
            nodes[host_name] = {
                "host": {},
                "services": [],
                "summary": "unknown",
            }
        nodes[host_name]["services"].append(svc_fields)

    # Compute summary: worst status wins
    priority = {"critical": 4, "warning": 3, "unknown": 2, "ok": 1}
    for host_name, node in nodes.items():
        worst = priority.get(node["host"].get("status", "unknown"), 0)
        for svc in node["services"]:
            svc_p = priority.get(svc.get("status", "unknown"), 0)
            if svc_p > worst:
                worst = svc_p
        # Reverse lookup
        for label, val in priority.items():
            if val == worst:
                node["summary"] = label
                break

    return nodes


# ---------------------------------------------------------------------------
# 3. get_host_checks
# ---------------------------------------------------------------------------


def get_host_checks(node_id):
    """Return checks for a specific host.

    Args:
        node_id: The host_name to look up.

    Returns:
        dict or None: The host entry from get_unified_health(), or None.
    """
    health = get_unified_health()
    return health.get(node_id)


# ---------------------------------------------------------------------------
# 4. sync_checks_to_db
# ---------------------------------------------------------------------------


def sync_checks_to_db():
    """Upsert all Nagios check states into monitoring_checks table.

    Returns:
        list: State changes as [{"node_id", "check_name", "old", "new", "output"}].
    """
    data = parse_status_dat()
    changes = []

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            # Fetch current DB state for comparison
            cur.execute("SELECT node_id, check_name, status FROM monitoring_checks")
            existing = {(row[0], row[1]): row[2] for row in cur.fetchall()}

            # Upsert host checks
            for host_name, fields in data["hosts"].items():
                status = fields.get("status", "unknown")
                output = fields.get("plugin_output", "")
                last_check = _parse_nagios_ts(fields.get("last_check"))
                next_check = _parse_nagios_ts(fields.get("next_check"))
                attempts = int(fields.get("current_attempt", 0))

                old_status = existing.get((host_name, "HOST"))
                if old_status and old_status != status:
                    changes.append(
                        {
                            "node_id": host_name,
                            "check_name": "HOST",
                            "old": old_status,
                            "new": status,
                            "output": output,
                        }
                    )

                cur.execute(
                    """INSERT INTO monitoring_checks
                           (node_id, check_name, check_type, status, output,
                            last_check, next_check, attempts, updated_at)
                       VALUES (%s, %s, 'host', %s, %s, %s, %s, %s, NOW())
                       ON CONFLICT (node_id, check_name) DO UPDATE SET
                           status     = EXCLUDED.status,
                           output     = EXCLUDED.output,
                           last_check = EXCLUDED.last_check,
                           next_check = EXCLUDED.next_check,
                           attempts   = EXCLUDED.attempts,
                           updated_at = NOW()
                    """,
                    (
                        host_name,
                        "HOST",
                        status,
                        output,
                        last_check,
                        next_check,
                        attempts,
                    ),
                )

            # Upsert service checks
            for key, fields in data["services"].items():
                host_name = fields.get("host_name", "unknown")
                svc_desc = fields.get("service_description", "unknown")
                status = fields.get("status", "unknown")
                output = fields.get("plugin_output", "")
                last_check = _parse_nagios_ts(fields.get("last_check"))
                next_check = _parse_nagios_ts(fields.get("next_check"))
                attempts = int(fields.get("current_attempt", 0))

                old_status = existing.get((host_name, svc_desc))
                if old_status and old_status != status:
                    changes.append(
                        {
                            "node_id": host_name,
                            "check_name": svc_desc,
                            "old": old_status,
                            "new": status,
                            "output": output,
                        }
                    )

                cur.execute(
                    """INSERT INTO monitoring_checks
                           (node_id, check_name, check_type, status, output,
                            last_check, next_check, attempts, updated_at)
                       VALUES (%s, %s, 'service', %s, %s, %s, %s, %s, NOW())
                       ON CONFLICT (node_id, check_name) DO UPDATE SET
                           status     = EXCLUDED.status,
                           output     = EXCLUDED.output,
                           last_check = EXCLUDED.last_check,
                           next_check = EXCLUDED.next_check,
                           attempts   = EXCLUDED.attempts,
                           updated_at = NOW()
                    """,
                    (
                        host_name,
                        svc_desc,
                        status,
                        output,
                        last_check,
                        next_check,
                        attempts,
                    ),
                )

    except Exception as exc:
        logger.error("sync_checks_to_db failed: %s", exc)
        return []

    if changes:
        logger.info("sync_checks_to_db: %d state change(s)", len(changes))
    return changes


# ---------------------------------------------------------------------------
# 5. process_alerts
# ---------------------------------------------------------------------------


def process_alerts(changes):
    """Process state changes and fire alerts with cooldown dedup.

    Args:
        changes: list of dicts from sync_checks_to_db().
    """
    from services.telegram_service import send_system

    for change in changes:
        node_id = change["node_id"]
        check_name = change["check_name"]
        old = change["old"]
        new = change["new"]
        output = change.get("output", "")

        if _is_in_cooldown(node_id, check_name):
            logger.debug(
                "Alert suppressed (cooldown): %s/%s %s->%s",
                node_id,
                check_name,
                old,
                new,
            )
            continue

        is_critical = new == "critical"
        is_recovery = old == "critical" and new == "ok"

        if is_critical or is_recovery:
            emoji = "\u2757" if is_critical else "\u2705"
            title = f"{emoji} {node_id} / {check_name}"
            msg = f"Status: {old} \u2192 {new}\n{output}"
            try:
                send_system(title, msg)
            except Exception as exc:
                logger.error("Telegram alert failed: %s", exc)
            _record_alert(
                node_id,
                check_name,
                old,
                new,
                via="telegram",
                message=msg,
                cooldown_minutes=5,
            )
        elif new == "warning":
            msg = f"Status: {old} \u2192 {new}\n{output}"
            _record_alert(
                node_id,
                check_name,
                old,
                new,
                via="email",
                message=msg,
                cooldown_minutes=60,
            )


# ---------------------------------------------------------------------------
# 6. _is_in_cooldown (private)
# ---------------------------------------------------------------------------


def _is_in_cooldown(node_id, check_name):
    """Check if an alert is within its cooldown window.

    Returns:
        bool: True if still in cooldown.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT 1 FROM monitoring_alerts
                   WHERE node_id = %s AND check_name = %s
                     AND cooldown_until > NOW()
                   LIMIT 1
                """,
                (node_id, check_name),
            )
            return cur.fetchone() is not None
    except Exception as exc:
        logger.error("_is_in_cooldown check failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# 7. _record_alert (private)
# ---------------------------------------------------------------------------


def _record_alert(node_id, check_name, old_status, new_status, via, message, cooldown_minutes):
    """Insert an alert record with computed cooldown_until.

    Args:
        node_id: Host identifier.
        check_name: Check or service name.
        old_status: Previous status string.
        new_status: New status string.
        via: Alert channel ('telegram' or 'email').
        message: Alert message body.
        cooldown_minutes: Minutes until next alert of same type is allowed.
    """
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO monitoring_alerts
                       (node_id, check_name, old_status, new_status,
                        alerted_via, message, alerted_at, cooldown_until)
                   VALUES (%s, %s, %s, %s, %s, %s, NOW(),
                           NOW() + INTERVAL '%s minutes')
                """,
                (
                    node_id,
                    check_name,
                    old_status,
                    new_status,
                    via,
                    message,
                    cooldown_minutes,
                ),
            )
    except Exception as exc:
        logger.error("_record_alert failed: %s", exc)


# ---------------------------------------------------------------------------
# 8. generate_node_config
# ---------------------------------------------------------------------------


def generate_node_config(node):
    """Render a Nagios config file for a node from a Jinja2 template.

    Args:
        node: dict with keys: node_id, node_name, hostname, deployment_mode.

    Returns:
        str: Path to the generated config file, or None on failure.
    """
    deployment_mode = node.get("deployment_mode", "starship")
    template_file = f"{deployment_mode}.cfg.j2"

    try:
        env = Environment(
            loader=FileSystemLoader(NAGIOS_TEMPLATE_DIR),
            keep_trailing_newline=True,
        )
        template = env.get_template(template_file)
    except Exception as exc:
        logger.error("Failed to load Nagios template %s: %s", template_file, exc)
        return None

    rendered = template.render(
        node_id=node.get("node_id", "unknown"),
        node_name=node.get("node_name", "unknown"),
        hostname=node.get("hostname", "127.0.0.1"),
    )

    os.makedirs(NAGIOS_CONF_DIR, exist_ok=True)
    out_path = os.path.join(NAGIOS_CONF_DIR, f"{node['node_id']}.cfg")

    try:
        with open(out_path, "w") as f:
            f.write(rendered)
        logger.info("Generated Nagios config: %s", out_path)
        return out_path
    except Exception as exc:
        logger.error("Failed to write Nagios config %s: %s", out_path, exc)
        return None


# ---------------------------------------------------------------------------
# 9. remove_node_config
# ---------------------------------------------------------------------------


def remove_node_config(node_id):
    """Delete the Nagios config file for a node.

    Args:
        node_id: The node identifier.

    Returns:
        bool: True if deleted (or already absent), False on error.
    """
    cfg_path = os.path.join(NAGIOS_CONF_DIR, f"{node_id}.cfg")
    try:
        if os.path.exists(cfg_path):
            os.remove(cfg_path)
            logger.info("Removed Nagios config: %s", cfg_path)
        return True
    except Exception as exc:
        logger.error("Failed to remove Nagios config %s: %s", cfg_path, exc)
        return False


# ---------------------------------------------------------------------------
# 10. reload_nagios
# ---------------------------------------------------------------------------


def reload_nagios():
    """Validate Nagios config and send SIGHUP to reload.

    Returns:
        dict: {"ok": bool, "message": str}
    """
    # Validate config
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "monitoring_nagios",
                "/opt/nagios/bin/nagios",
                "-v",
                "/opt/nagios/etc/nagios.cfg",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            msg = f"Nagios config validation failed:\n{result.stdout}\n{result.stderr}"
            logger.error(msg)
            return {"ok": False, "message": msg}
    except subprocess.TimeoutExpired:
        msg = "Nagios config validation timed out (30s)"
        logger.error(msg)
        return {"ok": False, "message": msg}
    except Exception as exc:
        msg = f"Nagios config validation error: {exc}"
        logger.error(msg)
        return {"ok": False, "message": msg}

    # Send SIGHUP to reload
    try:
        result = subprocess.run(
            ["docker", "exec", "monitoring_nagios", "kill", "-HUP", "1"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            msg = f"Nagios reload failed: {result.stderr}"
            logger.error(msg)
            return {"ok": False, "message": msg}
    except Exception as exc:
        msg = f"Nagios reload error: {exc}"
        logger.error(msg)
        return {"ok": False, "message": msg}

    logger.info("Nagios config reloaded successfully")
    return {"ok": True, "message": "Nagios reloaded"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_nagios_ts(value):
    """Convert a Nagios epoch timestamp string to a timezone-aware datetime.

    Returns:
        datetime or None
    """
    if not value or value == "0":
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (ValueError, TypeError):
        return None
