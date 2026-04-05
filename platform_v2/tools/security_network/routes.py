"""
Security & Network Routes
=========================
Dashboard for security monitoring, network health, and system status.
"""

from flask import render_template, jsonify, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from functools import wraps
import os
import time
import logging
from datetime import datetime
from database import get_db_cursor

logger = logging.getLogger(__name__)

from . import security_network_bp
from .security_alerts import create_security_alert


def admin_required(f):
    """Decorator to require admin access"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        if not getattr(current_user, "is_admin", False):
            flash("Admin access required", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return decorated_function


def get_system_health():
    """Get system health metrics"""
    try:
        import psutil

        return {
            "cpu": {"percent": psutil.cpu_percent(interval=0.1)},
            "memory": {"percent": psutil.virtual_memory().percent},
            "disk": {"percent": psutil.disk_usage("/").percent},
        }
    except Exception as e:
        logger.debug("Failed to get system health metrics: %s", e)
        return {"cpu": {"percent": 0}, "memory": {"percent": 0}, "disk": {"percent": 0}}


@security_network_bp.route("/")
@login_required
@admin_required
def index():
    """Security & Network dashboard"""
    # Get security stats
    failed_logins_24h = 0
    active_sessions = 0

    try:
        with get_db_cursor() as (conn, cur):
            # Get failed logins in last 24 hours
            cur.execute(
                """
                SELECT COUNT(*) as count FROM audit_log
                WHERE action = 'login_failed'
                AND created_at > NOW() - INTERVAL '24 hours'
            """
            )
            result = cur.fetchone()
            failed_logins_24h = result["count"] if result else 0

            # Get active sessions (users logged in within last hour)
            cur.execute(
                """
                SELECT COUNT(DISTINCT user_id) as count FROM audit_log
                WHERE action = 'login_success'
                AND created_at > NOW() - INTERVAL '1 hour'
            """
            )
            result = cur.fetchone()
            active_sessions = result["count"] if result else 0

    except Exception as e:
        logger.warning("Error getting security stats: %s", e)
    return render_template(
        "tools/security_network.html",
        failed_logins_24h=failed_logins_24h,
        active_sessions=active_sessions,
        system_health=get_system_health(),
    )


@security_network_bp.route("/api/stats")
@login_required
@admin_required
def api_stats():
    """API endpoint for security statistics"""
    try:
        with get_db_cursor() as (conn, cur):
            # Failed logins (24h)
            cur.execute(
                """
                SELECT COUNT(*) as count FROM audit_log
                WHERE action = 'login_failed'
                AND created_at > NOW() - INTERVAL '24 hours'
            """
            )
            failed_logins = cur.fetchone()["count"]

            # Recent failed login attempts
            cur.execute(
                """
                SELECT details, created_at
                FROM audit_log
                WHERE action = 'login_failed'
                ORDER BY created_at DESC
                LIMIT 20
            """
            )
            recent_failures = cur.fetchall()

            return jsonify(
                {
                    "success": True,
                    "failed_logins_24h": failed_logins,
                    "recent_failures": [dict(r) for r in recent_failures],
                    "system_health": get_system_health(),
                }
            )
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/audit-log")
@login_required
@admin_required
def audit_log():
    """Get audit log entries"""
    try:
        with get_db_cursor() as (conn, cur):
            limit = request.args.get("limit", 50, type=int)
            offset = request.args.get("offset", 0, type=int)
            action_filter = request.args.get("action", "")

            query = "SELECT * FROM audit_log"
            params = []

            if action_filter:
                query += " WHERE action = %s"
                params.append(action_filter)

            query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            cur.execute(query, params)
            entries = cur.fetchall()

            return jsonify({"success": True, "entries": [dict(e) for e in entries]})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


# ============================================================================
# NETWORK & SECURITY ROUTES - Migrated from admin/routes.py
# ============================================================================

# Import stack integration (local containers)
# Note: Stack management is now handled by System Operations module
try:
    from .stack_integration import (
        check_external_tools_status,
        adguard_api,
        scanner_service,
    )

    STACK_AVAILABLE = True
except ImportError:
    STACK_AVAILABLE = False

# Import security service (internal protection)
try:
    from .security_service import (
        get_firewall_status,
        get_active_connections,
        analyze_failed_logins,
        get_auto_block_settings,
        update_auto_block_settings,
        block_ip,
        unblock_ip,
        get_blocked_ips,
        get_whitelisted_ips,
        auto_block_threats,
        get_security_events,
        resolve_security_event,
        check_ssl_certificate,
        add_ssl_monitor,
        get_ssl_monitors,
        refresh_ssl_monitors,
    )

    SECURITY_SERVICE_AVAILABLE = True
except ImportError:
    SECURITY_SERVICE_AVAILABLE = False

# Import report service
try:
    from .report_service import (
        generate_scan_report,
        generate_assessment_report,
        export_vulnerabilities,
        list_reports,
        REPORTS_DIR,
    )

    REPORT_SERVICE_AVAILABLE = True
except ImportError:
    REPORT_SERVICE_AVAILABLE = False

# Import AdGuard full service
try:
    from .adguard_service import AdGuardService

    adguard_service = AdGuardService()
    ADGUARD_SERVICE_AVAILABLE = True
except ImportError:
    adguard_service = None
    ADGUARD_SERVICE_AVAILABLE = False

# Import Hostinger DNS service
try:
    from .hostinger_service import HostingerService

    hostinger_service = HostingerService()
    HOSTINGER_SERVICE_AVAILABLE = hostinger_service.available
except ImportError:
    hostinger_service = None
    HOSTINGER_SERVICE_AVAILABLE = False

# Import NPM (Nginx Proxy Manager) service
try:
    from .npm_service import NPMService

    npm_service = NPMService()
    NPM_SERVICE_AVAILABLE = npm_service.available
except ImportError:
    npm_service = None
    NPM_SERVICE_AVAILABLE = False

# Import Home Assistant Surveillance service
try:
    from .ha_surveillance_service import HASurveillanceService

    surveillance_service = HASurveillanceService()
    SURVEILLANCE_SERVICE_AVAILABLE = surveillance_service.available
except ImportError:
    surveillance_service = None
    SURVEILLANCE_SERVICE_AVAILABLE = False

# Import Argus Reconnaissance service
try:
    from .argus_service import ArgusService

    argus_service = ArgusService()
    ARGUS_SERVICE_AVAILABLE = True
except ImportError:
    argus_service = None
    ARGUS_SERVICE_AVAILABLE = False

# Import Agent Automation service
try:
    from .agent_automation import AgentAutomationService

    agent_automation_service = AgentAutomationService()
    AGENT_AUTOMATION_AVAILABLE = True
except ImportError:
    agent_automation_service = None
    AGENT_AUTOMATION_AVAILABLE = False

# Import Device Registry service
try:
    from tools.security_network.device_registry_service import DeviceRegistryService

    device_registry = DeviceRegistryService()
    DEVICE_REGISTRY_AVAILABLE = True
except Exception as e:
    logger.debug("Device registry service unavailable: %s", e)
    device_registry = None
    DEVICE_REGISTRY_AVAILABLE = False


# ============================================================================
# DOCKER CONTAINER SECURITY API
# ============================================================================


def calculate_security_score(container_info):
    """Calculate security score (0-100) for a container"""
    score = 100
    warnings = []

    # Check privileged mode (-40)
    if container_info.get("privileged", False):
        score -= 40
        warnings.append("Privileged mode")

    # Check network mode (-20 for host)
    if container_info.get("network_mode") == "host":
        score -= 20
        warnings.append("Host network mode")

    # Check for writable host mounts (-15)
    for mount in container_info.get("mounts", []):
        if mount.get("is_host", False) and mount.get("rw", True):
            score -= 15
            warnings.append("Writable host mounts")
            break

    # Check if running as root (-10)
    if container_info.get("user", "root") in ("root", "", "0"):
        score -= 10
        warnings.append("Running as root")

    # Check if root filesystem is writable (-5)
    if not container_info.get("read_only_rootfs", False):
        score -= 5
        warnings.append("Writable root filesystem")

    return max(0, score), warnings


@security_network_bp.route("/api/docker/security")
@login_required
@admin_required
def docker_security():
    """Get Docker container security analysis"""
    try:
        import docker

        client = docker.from_env()
        containers = client.containers.list(all=True)

        container_data = []
        high_risk = 0
        medium_risk = 0
        low_risk = 0

        for container in containers:
            if container.status != "running":
                continue

            try:
                # Get container details
                attrs = container.attrs
                host_config = attrs.get("HostConfig", {})

                # Build container info
                container_info = {
                    "privileged": host_config.get("Privileged", False),
                    "network_mode": host_config.get("NetworkMode", "default"),
                    "user": attrs.get("Config", {}).get("User", "root"),
                    "read_only_rootfs": host_config.get("ReadonlyRootfs", False),
                    "mounts": [],
                }

                # Process mounts
                for mount in attrs.get("Mounts", []):
                    container_info["mounts"].append(
                        {
                            "source": mount.get("Source", ""),
                            "destination": mount.get("Destination", ""),
                            "rw": mount.get("RW", True),
                            "is_host": mount.get("Type", "") == "bind",
                        }
                    )

                # Calculate security score
                score, warnings = calculate_security_score(container_info)

                # Categorize risk
                if score < 50:
                    high_risk += 1
                elif score < 80:
                    medium_risk += 1
                else:
                    low_risk += 1

                container_data.append(
                    {
                        "name": container.name,
                        "image": (container.image.tags[0] if container.image.tags else container.image.short_id),
                        "security": {
                            "privileged": container_info["privileged"],
                            "network_mode": container_info["network_mode"],
                            "user": container_info["user"],
                            "read_only_rootfs": container_info["read_only_rootfs"],
                            "capabilities_add": host_config.get("CapAdd", []) or [],
                        },
                        "mounts": container_info["mounts"],
                        "security_score": score,
                        "security_warnings": warnings,
                    }
                )

            except Exception as e:
                logger.warning("Error processing container %s: %s", container.name, e)
                continue

        # Sort by security score (lowest first)
        container_data.sort(key=lambda x: x["security_score"])

        return jsonify(
            {
                "success": True,
                "containers": container_data,
                "summary": {
                    "total": len(container_data),
                    "high_risk": high_risk,
                    "medium_risk": medium_risk,
                    "low_risk": low_risk,
                },
            }
        )

    except ImportError:
        return jsonify({"success": False, "error": "Docker SDK not available"}), 503
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


# ============================================================================
# EXTERNAL TOOLS STATUS API (Updated for local stacks)
# ============================================================================


@security_network_bp.route("/api/external-tools/status")
@login_required
@admin_required
def external_tools_status():
    """Check connectivity to local stack tools"""
    if STACK_AVAILABLE:
        try:
            status = check_external_tools_status()
            # Format for UI compatibility
            tools = {
                "adguard": {
                    "online": status.get("adguard", {}).get("online", False),
                    "host": "localhost",
                    "port": 8053,
                    "type": "dns_filter",
                },
                "ntopng": {
                    "online": status.get("ntopng", {}).get("online", False),
                    "host": "localhost",
                    "port": 3001,
                    "type": "traffic_analysis",
                },
                "zap": {
                    "online": status.get("zap", {}).get("online", False),
                    "host": "localhost",
                    "port": 8090,
                    "type": "web_scanner",
                },
                "nagios": {
                    "online": False,  # Will check via stack status
                    "host": "localhost",
                    "port": 8082,
                    "type": "monitoring",
                },
            }

            # Update nagios from stack status
            stacks = status.get("stacks", {})
            monitoring = stacks.get("monitoring", {})
            if monitoring.get("status") == "running":
                tools["nagios"]["online"] = True

            return jsonify({"success": True, "tools": tools, "stacks": stacks})
        except Exception as e:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # Fallback to socket-based check for legacy setup
    import socket

    tools = {
        "adguard": {"host": "localhost", "port": 8053},
        "ntopng": {"host": "localhost", "port": 3001},
        "nagios": {"host": "localhost", "port": 8082},
        "zap": {"host": "localhost", "port": 8090},
    }

    results = {}
    timeout = 2

    for tool_name, config in tools.items():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((config["host"], config["port"]))
            sock.close()
            results[tool_name] = {
                "online": result == 0,
                "host": config["host"],
                "port": config["port"],
            }
        except Exception as e:
            results[tool_name] = {
                "online": False,
                "host": config["host"],
                "port": config["port"],
                "error": "Connection failed",
            }

    return jsonify({"success": True, "tools": results})


# ============================================================================
# STACK STATUS API (Deprecated - use System Operations)
# ============================================================================


@security_network_bp.route("/api/stacks/status")
@login_required
@admin_required
def stacks_status():
    """
    Get status of security-related stacks.
    NOTE: Stack management has moved to System Operations module.
    This endpoint proxies to /tools/system-operations/api/stacks/status
    """
    # Redirect clients to use System Operations API directly
    return jsonify(
        {
            "success": True,
            "message": "Stack management moved to System Operations",
            "redirect": "/tools/system-operations/api/stacks/status?names=monitoring,network-tools,security-scanner",
        }
    )


# ============================================================================
# HEALTH CHECK
# ============================================================================


@security_network_bp.route("/health")
def health_check():
    """Health check endpoint"""
    return jsonify(
        {
            "healthy": True,
            "module": "security_network",
            "stack_available": STACK_AVAILABLE,
            "security_service_available": SECURITY_SERVICE_AVAILABLE,
            "report_service_available": REPORT_SERVICE_AVAILABLE,
            "adguard_service_available": ADGUARD_SERVICE_AVAILABLE,
            "hostinger_service_available": HOSTINGER_SERVICE_AVAILABLE,
            "surveillance_service_available": SURVEILLANCE_SERVICE_AVAILABLE,
            "argus_service_available": ARGUS_SERVICE_AVAILABLE,
            "agent_automation_available": AGENT_AUTOMATION_AVAILABLE,
            "npm_service_available": NPM_SERVICE_AVAILABLE,
        }
    )


# ============================================================================
# SCANNER, SCAN RESULTS, ADGUARD (extracted to scanner_routes.py, adguard_routes.py)
# ============================================================================


# ============================================================================
# INTERNAL SECURITY - FIREWALL & CONNECTIONS
# ============================================================================


@security_network_bp.route("/api/firewall/status")
@login_required
@admin_required
def api_firewall_status():
    """Get firewall status"""
    if not SECURITY_SERVICE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

    try:
        status = get_firewall_status()
        return jsonify({"success": True, "firewall": status})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/firewall/rules")
@login_required
@admin_required
def api_firewall_rules():
    """Get firewall rules via host_command_client."""
    try:
        from tools.system_operations.host_command_client import submit_and_wait, is_queue_available

        if not is_queue_available():
            return jsonify({"success": True, "rules": []})
        result_data = submit_and_wait("firewall_rules", {}, timeout=10, submitted_by="security_network")
        cmd_result = result_data.get("result", {})
        if cmd_result.get("success"):
            return jsonify({"success": True, "rules": cmd_result.get("rules", [])})
        return jsonify({"success": True, "rules": []})
    except Exception as e:
        logger.exception("firewall rules error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/firewall/enable", methods=["POST"])
@login_required
@admin_required
def api_firewall_enable():
    """Enable firewall via host_command_client."""
    try:
        from tools.system_operations.host_command_client import submit_and_wait, is_queue_available

        if not is_queue_available():
            return jsonify({"success": False, "error": "Host command queue not available"}), 503
        result_data = submit_and_wait("firewall_enable", {}, timeout=10, submitted_by="security_network")
        return jsonify(result_data.get("result", {"success": False}))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/firewall/disable", methods=["POST"])
@login_required
@admin_required
def api_firewall_disable():
    """Disable firewall via host_command_client."""
    try:
        from tools.system_operations.host_command_client import submit_and_wait, is_queue_available

        if not is_queue_available():
            return jsonify({"success": False, "error": "Host command queue not available"}), 503
        result_data = submit_and_wait("firewall_disable", {}, timeout=10, submitted_by="security_network")
        return jsonify(result_data.get("result", {"success": False}))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/firewall/allow", methods=["POST"])
@login_required
@admin_required
def api_firewall_allow():
    """Add firewall allow rule via host_command_client."""
    data = request.get_json(silent=True) or {}
    try:
        from tools.system_operations.host_command_client import submit_and_wait, is_queue_available

        if not is_queue_available():
            return jsonify({"success": False, "error": "Host command queue not available"}), 503
        result_data = submit_and_wait("firewall_allow", data, timeout=10, submitted_by="security_network")
        return jsonify(result_data.get("result", {"success": False}))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/firewall/deny", methods=["POST"])
@login_required
@admin_required
def api_firewall_deny():
    """Add firewall deny rule via host_command_client."""
    data = request.get_json(silent=True) or {}
    try:
        from tools.system_operations.host_command_client import submit_and_wait, is_queue_available

        if not is_queue_available():
            return jsonify({"success": False, "error": "Host command queue not available"}), 503
        result_data = submit_and_wait("firewall_deny", data, timeout=10, submitted_by="security_network")
        return jsonify(result_data.get("result", {"success": False}))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/firewall/delete", methods=["DELETE"])
@login_required
@admin_required
def api_firewall_delete():
    """Delete firewall rule via host_command_client."""
    data = request.get_json(silent=True) or {}
    try:
        from tools.system_operations.host_command_client import submit_and_wait, is_queue_available

        if not is_queue_available():
            return jsonify({"success": False, "error": "Host command queue not available"}), 503
        result_data = submit_and_wait("firewall_delete", data, timeout=10, submitted_by="security_network")
        return jsonify(result_data.get("result", {"success": False}))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/connections/active")
@login_required
@admin_required
def api_active_connections():
    """Get active network connections"""
    if not SECURITY_SERVICE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

    try:
        connections = get_active_connections()
        return jsonify({"success": True, "connections": connections})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


# ============================================================================
# IP ACCESS CONTROL
# ============================================================================


@security_network_bp.route("/api/ip-access")
@login_required
@admin_required
def api_ip_access_list():
    """Get blocked and whitelisted IPs"""
    if not SECURITY_SERVICE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

    try:
        blocked = get_blocked_ips()
        whitelisted = get_whitelisted_ips()
        return jsonify({"success": True, "blocked": blocked, "whitelisted": whitelisted})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/ip-access/block", methods=["POST"])
@login_required
@admin_required
def api_block_ip():
    """Block an IP address"""
    if not SECURITY_SERVICE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

    data = request.get_json() or {}
    ip_address = data.get("ip_address", "")
    reason = data.get("reason", "Manually blocked")
    duration = data.get("duration_hours")

    if not ip_address:
        return jsonify({"success": False, "error": "IP address is required"}), 400

    try:
        result = block_ip(ip_address, reason, current_user.id, duration)
        if result.get("success"):
            create_security_alert(
                "block",
                f"IP Blocked: {ip_address}",
                f"IP {ip_address} blocked by {getattr(current_user, 'username', 'admin')}.\nReason: {reason}",
                priority="high",
            )
        return jsonify(result)
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/ip-access/unblock", methods=["POST"])
@login_required
@admin_required
def api_unblock_ip():
    """Unblock an IP address"""
    if not SECURITY_SERVICE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

    data = request.get_json() or {}
    ip_address = data.get("ip_address", "")

    if not ip_address:
        return jsonify({"success": False, "error": "IP address is required"}), 400

    try:
        result = unblock_ip(ip_address, current_user.id)
        return jsonify(result)
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


# ============================================================================
# AUTO-BLOCK SETTINGS
# ============================================================================


@security_network_bp.route("/api/auto-block/settings")
@login_required
@admin_required
def api_auto_block_settings():
    """Get auto-block settings"""
    if not SECURITY_SERVICE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

    try:
        settings = get_auto_block_settings()
        return jsonify({"success": True, "settings": settings})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/auto-block/settings", methods=["POST"])
@login_required
@admin_required
def api_update_auto_block_settings():
    """Update auto-block settings"""
    if not SECURITY_SERVICE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

    data = request.get_json() or {}

    try:
        success = update_auto_block_settings(data, current_user.id)
        if success:
            return jsonify({"success": True, "message": "Settings updated"})
        return jsonify({"success": False, "error": "Failed to update settings"}), 500
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/auto-block/analyze")
@login_required
@admin_required
def api_analyze_threats():
    """Analyze failed logins for threats"""
    if not SECURITY_SERVICE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

    hours = request.args.get("hours", 24, type=int)

    try:
        analysis = analyze_failed_logins(hours)
        return jsonify({"success": True, "analysis": analysis})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/auto-block/execute", methods=["POST"])
@login_required
@admin_required
def api_execute_auto_block():
    """Execute auto-block on detected threats"""
    if not SECURITY_SERVICE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

    try:
        result = auto_block_threats(current_user.id)
        blocked_count = result.get("blocked", 0)
        if blocked_count > 0:
            blocked_ips = result.get("blocked_ips", [])
            create_security_alert(
                "intrusion",
                f"Auto-Block: {blocked_count} IP(s) blocked",
                f"Auto-block detected and blocked {blocked_count} threat(s).\nIPs: {', '.join(blocked_ips[:10])}",
                priority="critical" if blocked_count >= 5 else "high",
            )
        return jsonify(result)
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


# ============================================================================
# SECURITY EVENTS
# ============================================================================


@security_network_bp.route("/api/events")
@login_required
@admin_required
def api_security_events():
    """Get security events"""
    if not SECURITY_SERVICE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

    status = request.args.get("status")
    severity = request.args.get("severity")
    event_type = request.args.get("type")
    limit = request.args.get("limit", 50, type=int)

    try:
        events = get_security_events(status, severity, event_type, limit)
        return jsonify({"success": True, "events": events})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/events/<int:event_id>/resolve", methods=["POST"])
@login_required
@admin_required
def api_resolve_event(event_id):
    """Resolve a security event"""
    if not SECURITY_SERVICE_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

    data = request.get_json() or {}
    notes = data.get("notes", "")

    try:
        result = resolve_security_event(event_id, current_user.id, notes)
        return jsonify(result)
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


# ============================================================================
# SSL CERTIFICATE MONITORING (extracted to scanner_routes.py)
# ============================================================================


# ============================================================================
# REPORT GENERATION
# ============================================================================


@security_network_bp.route("/api/reports")
@login_required
@admin_required
def api_list_reports():
    """List all generated reports from DB + filesystem"""
    from database import get_db_cursor

    try:
        db_reports = []
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, report_type, title, date_range_start, date_range_end,
                          format, file_path, created_at
                   FROM security_reports
                   ORDER BY created_at DESC
                   LIMIT 100"""
            )
            for row in cur.fetchall():
                db_reports.append(
                    {
                        "id": row[0],
                        "report_type": row[1],
                        "title": row[2],
                        "date_range_start": row[3].isoformat() if row[3] else None,
                        "date_range_end": row[4].isoformat() if row[4] else None,
                        "format": row[5],
                        "file_path": row[6],
                        "created_at": row[7].isoformat() if row[7] else None,
                        "source": "db",
                    }
                )

        # Also include filesystem reports if available
        file_reports = []
        if REPORT_SERVICE_AVAILABLE:
            try:
                for fr in list_reports():
                    fr["source"] = "file"
                    file_reports.append(fr)
            except Exception as e:
                logger.debug("Failed to list filesystem reports: %s", e)

        return jsonify({"success": True, "reports": db_reports, "file_reports": file_reports})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/reports/generate", methods=["POST"])
@login_required
@admin_required
def api_generate_report():
    """Generate a security report and store in DB"""
    from database import get_db_cursor
    from psycopg2.extras import Json

    data = request.get_json() or {}

    # Handle daily_device / daily_user reports via ReportService
    report_type = data.get("type") or data.get("report_type", "daily_summary")
    if report_type in ("daily_device", "daily_user"):
        try:
            from .report_service import ReportService

            svc = ReportService()
            report_date = data.get("date")
            if report_type == "daily_device":
                result = svc.generate_daily_device_report(report_date)
            else:
                result = svc.generate_daily_user_report(report_date)
            return jsonify({"success": True, "data": result})
        except Exception as e:
            logger.exception("Report generation error: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    date_start = data.get("date_start")
    date_end = data.get("date_end")

    valid_types = ["daily_summary", "weekly_report", "device_audit", "dns_analysis"]
    if report_type not in valid_types:
        return jsonify({"success": False, "error": f"Invalid report type: {report_type}"}), 400

    type_labels = {
        "daily_summary": "Daily Summary",
        "weekly_report": "Weekly Report",
        "device_audit": "Device Audit",
        "dns_analysis": "DNS Analysis",
    }
    title = f"{type_labels[report_type]} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    try:
        # Gather report content based on type
        content = _gather_report_content(report_type, date_start, date_end)

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO security_reports
                   (report_type, title, date_range_start, date_range_end, content, format)
                   VALUES (%s, %s, %s, %s, %s, 'json')
                   RETURNING id""",
                (
                    report_type,
                    title,
                    date_start,
                    date_end,
                    Json(content),
                ),
            )
            report_id = cur.fetchone()[0]

        return jsonify({"success": True, "id": report_id, "title": title})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/reports/<int:report_id>")
@login_required
@admin_required
def api_view_report(report_id):
    """View a single report from DB"""
    from database import get_db_cursor

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, report_type, title, date_range_start, date_range_end,
                          content, format, created_at
                   FROM security_reports WHERE id = %s""",
                (report_id,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Report not found"}), 404

            return jsonify(
                {
                    "success": True,
                    "report": {
                        "id": row[0],
                        "report_type": row[1],
                        "title": row[2],
                        "date_range_start": row[3].isoformat() if row[3] else None,
                        "date_range_end": row[4].isoformat() if row[4] else None,
                        "content": row[5],
                        "format": row[6],
                        "created_at": row[7].isoformat() if row[7] else None,
                    },
                }
            )
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/reports/scan/<filename>", methods=["POST"])
@login_required
@admin_required
def api_generate_scan_report(filename):
    """Generate report for a single scan"""
    if not REPORT_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Report service not available"}), 503

    try:
        result = generate_scan_report(filename)
        return jsonify(result)
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/reports/assessment", methods=["POST"])
@login_required
@admin_required
def api_generate_assessment_report():
    """Generate combined assessment report"""
    if not REPORT_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Report service not available"}), 503

    data = request.get_json() or {}
    scan_files = data.get("scans", [])
    client_name = data.get("client", "Assessment")
    assessment_name = data.get("name", "Security Assessment")

    if not scan_files:
        return jsonify({"success": False, "error": "No scan files specified"}), 400

    try:
        result = generate_assessment_report(scan_files, client_name, assessment_name)
        return jsonify(result)
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/reports/export/<filename>")
@login_required
@admin_required
def api_export_vulnerabilities(filename):
    """Export vulnerabilities from a scan"""
    if not REPORT_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Report service not available"}), 503

    format = request.args.get("format", "json")

    try:
        result = export_vulnerabilities(filename, format)

        if result.get("success") and format == "csv":
            from flask import Response

            return Response(
                result["csv"],
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename.rsplit('.', 1)[0]}_vulns.csv"},
            )

        return jsonify(result)
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/reports/download/<filename>")
@login_required
@admin_required
def api_download_report(filename):
    """Download a generated report"""
    if not REPORT_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Report service not available"}), 503

    import os

    # Security: validate filename
    if ".." in filename or "/" in filename or "\\" in filename:
        return jsonify({"success": False, "error": "Invalid filename"}), 400

    filepath = os.path.join(REPORTS_DIR, filename)

    if not os.path.exists(filepath):
        return jsonify({"success": False, "error": "Report not found"}), 404

    try:
        from flask import send_file

        return send_file(filepath, as_attachment=True)
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


# ============================================================================
# REPORT CONTENT GATHERING
# ============================================================================


def _gather_report_content(report_type, date_start=None, date_end=None):
    """Gather report content based on type by querying relevant DB data."""
    from database import get_db_cursor

    content = {"report_type": report_type, "generated_at": datetime.now().isoformat()}

    with get_db_cursor() as (conn, cur):
        date_filter = ""
        date_params = []
        if date_start:
            date_filter += " AND created_at >= %s"
            date_params.append(date_start)
        if date_end:
            date_filter += " AND created_at <= %s"
            date_params.append(date_end)

        if report_type == "daily_summary":
            # Security events from last 24h (or date range)
            df = date_filter if date_start else " AND created_at >= NOW() - INTERVAL '24 hours'"
            dp = date_params if date_start else []
            try:
                cur.execute(
                    f"""SELECT severity, COUNT(*) as cnt
                        FROM security_events
                        WHERE 1=1 {df}
                        GROUP BY severity ORDER BY cnt DESC""",
                    dp,
                )
                content["events_by_severity"] = [{"severity": r[0], "count": r[1]} for r in cur.fetchall()]
            except Exception as e:
                logger.debug("Report query failed (events_by_severity): %s", e)
                conn.rollback()
                content["events_by_severity"] = []

            try:
                cur.execute(
                    f"""SELECT event_type, description, severity, status, created_at
                        FROM security_events
                        WHERE 1=1 {df}
                        ORDER BY created_at DESC LIMIT 50""",
                    dp,
                )
                content["recent_events"] = [
                    {
                        "type": r[0],
                        "description": r[1],
                        "severity": r[2],
                        "status": r[3],
                        "created_at": r[4].isoformat() if r[4] else None,
                    }
                    for r in cur.fetchall()
                ]
            except Exception as e:
                logger.debug("Report query failed (recent_events): %s", e)
                conn.rollback()
                content["recent_events"] = []

        elif report_type == "weekly_report":
            df = date_filter if date_start else " AND created_at >= NOW() - INTERVAL '7 days'"
            dp = date_params if date_start else []
            try:
                cur.execute(
                    f"""SELECT DATE(created_at) as day, severity, COUNT(*)
                        FROM security_events
                        WHERE 1=1 {df}
                        GROUP BY day, severity ORDER BY day DESC""",
                    dp,
                )
                daily = {}
                for r in cur.fetchall():
                    day_str = r[0].isoformat()
                    if day_str not in daily:
                        daily[day_str] = {}
                    daily[day_str][r[1]] = r[2]
                content["daily_breakdown"] = daily
            except Exception as e:
                logger.debug("Report query failed (daily_breakdown): %s", e)
                conn.rollback()
                content["daily_breakdown"] = {}

            try:
                cur.execute(
                    f"""SELECT COUNT(*) FROM security_events WHERE 1=1 {df}""",
                    dp,
                )
                content["total_events"] = cur.fetchone()[0]
            except Exception as e:
                logger.debug("Report query failed (total_events): %s", e)
                conn.rollback()
                content["total_events"] = 0

            # Scan results summary
            try:
                cur.execute(
                    f"""SELECT severity, COUNT(*) FROM security_scan_results
                        WHERE 1=1 {df}
                        GROUP BY severity ORDER BY COUNT(*) DESC""",
                    dp,
                )
                content["scan_findings"] = [{"severity": r[0], "count": r[1]} for r in cur.fetchall()]
            except Exception as e:
                logger.debug("Report query failed (scan_findings): %s", e)
                conn.rollback()
                content["scan_findings"] = []

        elif report_type == "device_audit":
            try:
                cur.execute(
                    """SELECT hostname, ip_address::text, mac_address, device_type,
                              status, security_zone, is_registered, last_seen_at
                       FROM network_devices
                       ORDER BY last_seen_at DESC NULLS LAST LIMIT 200"""
                )
                content["devices"] = [
                    {
                        "hostname": r[0],
                        "ip": r[1],
                        "mac": r[2],
                        "type": r[3],
                        "status": r[4],
                        "zone": r[5],
                        "registered": r[6],
                        "last_seen": r[7].isoformat() if r[7] else None,
                    }
                    for r in cur.fetchall()
                ]
                content["total_devices"] = len(content["devices"])
            except Exception as e:
                logger.debug("Report query failed (devices): %s", e)
                conn.rollback()
                content["devices"] = []
                content["total_devices"] = 0

            # Zone summary
            try:
                cur.execute(
                    """SELECT security_zone, COUNT(*) FROM network_devices
                       GROUP BY security_zone ORDER BY COUNT(*) DESC"""
                )
                content["zone_summary"] = [{"zone": r[0], "count": r[1]} for r in cur.fetchall()]
            except Exception as e:
                logger.debug("Report query failed (zone_summary): %s", e)
                conn.rollback()
                content["zone_summary"] = []

        elif report_type == "dns_analysis":
            df = date_filter if date_start else " AND created_at >= NOW() - INTERVAL '7 days'"
            dp = date_params if date_start else []
            # DNS changes
            try:
                cur.execute(
                    f"""SELECT source, action, domain, changed_by, created_at
                        FROM security_dns_changes
                        WHERE 1=1 {df}
                        ORDER BY created_at DESC LIMIT 100""",
                    dp,
                )
                content["dns_changes"] = [
                    {
                        "source": r[0],
                        "action": r[1],
                        "domain": r[2],
                        "changed_by": r[3],
                        "created_at": r[4].isoformat() if r[4] else None,
                    }
                    for r in cur.fetchall()
                ]
            except Exception as e:
                logger.debug("Report query failed (dns_changes): %s", e)
                conn.rollback()
                content["dns_changes"] = []

            # DNS providers
            try:
                cur.execute(
                    """SELECT provider_name, provider_type, is_active
                       FROM dns_providers ORDER BY provider_name"""
                )
                content["dns_providers"] = [{"name": r[0], "type": r[1], "active": r[2]} for r in cur.fetchall()]
            except Exception as e:
                logger.debug("Report query failed (dns_providers): %s", e)
                conn.rollback()
                content["dns_providers"] = []

    return content


# ============================================================================
# SERVICE HEALTH HELPERS
# ============================================================================


def _check_npm_health():
    """Check if Nginx Proxy Manager is reachable."""
    try:
        import requests as req

        npm_url = os.getenv("NPM_API_URL", "http://192.168.1.200:81/api")
        r = req.get(f"{npm_url.rstrip('/api')}/", timeout=3)
        return r.status_code < 500
    except Exception as e:
        logger.debug("NPM health check failed: %s", e)
        return False


def _check_ssh_health():
    """Check if SSH is reachable by connecting to port 22 on the host."""
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(("192.168.1.200", 22))
        s.close()
        return True
    except Exception as e:
        logger.debug("SSH health check failed: %s", e)
        return False


def _check_fail2ban_health():
    """Check if fail2ban is running by checking its log file freshness."""
    try:
        log_file = "/mnt/archie_brain/host_monitor_data.json"
        if not os.path.exists(log_file):
            return False
        # If host_monitor is running, fail2ban is likely running too
        # (we installed it alongside SSH hardening)
        age = time.time() - os.path.getmtime(log_file)
        return age < 120  # host_monitor updates every ~60s
    except Exception as e:
        logger.debug("fail2ban health check failed: %s", e)
        return False


def _check_ddns_health():
    """Check if DDNS updater ran recently (last IP file updated within 10 min)."""
    try:
        ip_file = "/mnt/archie_brain/scripts/.ddns_last_ip"
        if not os.path.exists(ip_file):
            return False
        age = time.time() - os.path.getmtime(ip_file)
        return age < 600  # Updated within last 10 minutes
    except Exception as e:
        logger.debug("DDNS health check failed: %s", e)
        return False


# ============================================================================
# DASHBOARD AGGREGATION API
# ============================================================================


@security_network_bp.route("/api/dashboard/stats")
@login_required
@admin_required
def api_dashboard_stats():
    """Aggregated stats from all services for the dashboard"""
    stats = {}

    # AdGuard DNS stats
    try:
        if ADGUARD_SERVICE_AVAILABLE and adguard_service:
            ag_stats = adguard_service.get_stats()
            ag_status = adguard_service.get_status()
            stats["dns"] = {
                "available": True,
                "total_queries": ag_stats.get("num_dns_queries", 0) if ag_stats else 0,
                "blocked_queries": ag_stats.get("num_blocked_filtering", 0) if ag_stats else 0,
                "protection_enabled": ag_status.get("protection_enabled", False) if ag_status else False,
            }
        else:
            stats["dns"] = {"available": False}
    except Exception as e:
        logger.debug("Dashboard DNS stats failed: %s", e)
        stats["dns"] = {"available": False}

    # Surveillance camera count
    try:
        if SURVEILLANCE_SERVICE_AVAILABLE and surveillance_service:
            cameras = surveillance_service.get_cameras()
            online_count = sum(1 for c in cameras if c.get("state") != "unavailable")
            stats["cameras"] = {
                "available": True,
                "total": len(cameras),
                "online": online_count,
            }
        else:
            stats["cameras"] = {"available": False}
    except Exception as e:
        logger.debug("Dashboard camera stats failed: %s", e)
        stats["cameras"] = {"available": False}

    # Agent automation pending suggestions
    try:
        if AGENT_AUTOMATION_AVAILABLE and agent_automation_service:
            pending = agent_automation_service.get_pending_suggestions(limit=100)
            config = agent_automation_service.get_config()
            stats["agent"] = {
                "available": True,
                "pending_suggestions": len(pending),
                "mode": config.get("mode", "suggest"),
                "paused": config.get("paused", False),
            }
        else:
            stats["agent"] = {"available": False}
    except Exception as e:
        logger.debug("Dashboard agent stats failed: %s", e)
        stats["agent"] = {"available": False}

    # Argus recent scan count
    try:
        if ARGUS_SERVICE_AVAILABLE and argus_service:
            history = argus_service.get_scan_history(limit=10)
            stats["recon"] = {
                "available": True,
                "recent_scans": len(history),
                "module_count": argus_service.get_module_count(),
            }
        else:
            stats["recon"] = {"available": False}
    except Exception as e:
        logger.debug("Dashboard recon stats failed: %s", e)
        stats["recon"] = {"available": False}

    # Hostinger DNS
    try:
        if HOSTINGER_SERVICE_AVAILABLE and hostinger_service:
            stats["hostinger"] = {"available": True}
        else:
            stats["hostinger"] = {"available": False}
    except Exception as e:
        logger.debug("Dashboard hostinger stats failed: %s", e)
        stats["hostinger"] = {"available": False}

    # Flatten for dashboard JS consumption
    dns = stats.get("dns", {})
    cameras = stats.get("cameras", {})
    agent = stats.get("agent", {})
    recon = stats.get("recon", {})

    # Build recent activity feed from multiple security sources
    recent_activity = []
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (_conn, _cur):
            # Security notifications
            _cur.execute(
                """SELECT type, title, message, created_at FROM system_notifications
                   WHERE source = 'security_network' AND is_archived = FALSE
                   ORDER BY created_at DESC LIMIT 5"""
            )
            for row in _cur.fetchall():
                recent_activity.append(
                    {
                        "text": row["title"] or row["message"],
                        "time": row["created_at"].isoformat() if row["created_at"] else "",
                        "type": row["type"],
                    }
                )

            # Recent security scans
            _cur.execute(
                """SELECT module_name, target, status, started_at FROM security_recon_scans
                   ORDER BY started_at DESC LIMIT 3"""
            )
            for row in _cur.fetchall():
                recent_activity.append(
                    {
                        "text": f"{row['module_name']} scan on {row['target']} — {row['status']}",
                        "time": row["started_at"].strftime("%Y-%m-%d %H:%M") if row["started_at"] else "",
                        "type": "info",
                    }
                )

            # Recent IP blocks
            _cur.execute(
                """SELECT ip_address, access_type, reason, created_at FROM security_ip_access
                   ORDER BY created_at DESC LIMIT 3"""
            )
            for row in _cur.fetchall():
                recent_activity.append(
                    {
                        "text": f"IP {row['access_type']}: {row['ip_address']} — {row['reason'] or 'manual'}",
                        "time": row["created_at"].isoformat() if row["created_at"] else "",
                        "type": "warning" if row["access_type"] == "block" else "info",
                    }
                )

            # DNS changes
            _cur.execute(
                """SELECT action, domain, details, created_at FROM security_dns_changes
                   ORDER BY created_at DESC LIMIT 3"""
            )
            for row in _cur.fetchall():
                details = row["details"] or {}
                record_info = details.get("name", row["domain"] or "")
                recent_activity.append(
                    {
                        "text": f"DNS {row['action']}: {record_info}",
                        "time": row["created_at"].isoformat() if row["created_at"] else "",
                        "type": "info",
                    }
                )

        # Sort all by time descending, take top 10
        recent_activity.sort(key=lambda x: x.get("time", ""), reverse=True)
        recent_activity = recent_activity[:10]
    except Exception as e:
        logger.debug("Failed to fetch recent activity for dashboard: %s", e)

    # If still empty, add a status message
    if not recent_activity:
        recent_activity.append(
            {
                "text": "Security module active — monitoring DNS, cameras, and network",
                "time": "",
                "type": "info",
            }
        )

    return jsonify(
        {
            "success": True,
            "dns_queries_24h": dns.get("total_queries", 0),
            "dns_blocked_24h": dns.get("blocked_queries", 0),
            "dns_protection_enabled": dns.get("protection_enabled", False),
            "camera_count": cameras.get("total", 0),
            "pending_suggestions": agent.get("pending_suggestions", 0),
            "recent_activity": recent_activity,
            "services": {
                "adguard": dns.get("available", False),
                "hostinger": stats.get("hostinger", {}).get("available", False),
                "surveillance": cameras.get("available", False),
                "npm": _check_npm_health(),
                "ssh": _check_ssh_health(),
                "fail2ban": _check_fail2ban_health(),
                "ddns": _check_ddns_health(),
                "argus": recon.get("available", False),
                "agent": agent.get("available", False),
            },
            "stats": stats,
        }
    )


# ============================================================================
# DNS MANAGEMENT - HOSTINGER (extracted to hostinger_routes.py)
# ============================================================================


# ============================================================================
# SURVEILLANCE - HOME ASSISTANT CAMERAS (extracted to surveillance_routes.py)
# ============================================================================


# ============================================================================
# RECONNAISSANCE - ARGUS (extracted to scanner_routes.py)
# ============================================================================


# ============================================================================
# AGENT AUTOMATION
# ============================================================================


@security_network_bp.route("/api/agent/config")
@login_required
@admin_required
def api_agent_config_get():
    """Get agent automation configuration"""
    if not AGENT_AUTOMATION_AVAILABLE or not agent_automation_service:
        return jsonify({"success": False, "error": "Agent automation service not available"}), 503

    try:
        config = agent_automation_service.get_config()
        return jsonify({"success": True, "config": config})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/agent/config", methods=["PUT"])
@login_required
@admin_required
def api_agent_config_update():
    """Update agent automation configuration"""
    if not AGENT_AUTOMATION_AVAILABLE or not agent_automation_service:
        return jsonify({"success": False, "error": "Agent automation service not available"}), 503

    data = request.get_json() or {}

    try:
        config = agent_automation_service.get_config()

        # Update mode if provided
        if "mode" in data:
            config["mode"] = data["mode"]

        # Update categories if provided
        if "categories" in data:
            for cat_name, cat_data in data["categories"].items():
                if cat_name in config.get("categories", {}):
                    if "auto_enabled" in cat_data:
                        config["categories"][cat_name]["auto_enabled"] = cat_data["auto_enabled"]

        success = agent_automation_service.save_config(config)
        if success:
            return jsonify({"success": True, "config": config})
        return jsonify({"success": False, "error": "Failed to save configuration"}), 500
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/agent/suggestions")
@login_required
@admin_required
def api_agent_suggestions():
    """Get pending agent suggestions"""
    if not AGENT_AUTOMATION_AVAILABLE or not agent_automation_service:
        return jsonify({"success": False, "error": "Agent automation service not available"}), 503

    limit = request.args.get("limit", 50, type=int)
    category = request.args.get("category")

    try:
        suggestions = agent_automation_service.get_pending_suggestions(category, limit)
        return jsonify({"success": True, "suggestions": suggestions})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/agent/suggestions/<int:suggestion_id>/approve", methods=["POST"])
@login_required
@admin_required
def api_agent_approve_suggestion(suggestion_id):
    """Approve an agent suggestion"""
    if not AGENT_AUTOMATION_AVAILABLE or not agent_automation_service:
        return jsonify({"success": False, "error": "Agent automation service not available"}), 503

    try:
        success = agent_automation_service.approve_suggestion(suggestion_id)
        if success:
            return jsonify({"success": True, "message": f"Suggestion {suggestion_id} approved"})
        return jsonify({"success": False, "error": "Suggestion not found or already processed"}), 404
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/agent/suggestions/<int:suggestion_id>/dismiss", methods=["POST"])
@login_required
@admin_required
def api_agent_dismiss_suggestion(suggestion_id):
    """Dismiss an agent suggestion"""
    if not AGENT_AUTOMATION_AVAILABLE or not agent_automation_service:
        return jsonify({"success": False, "error": "Agent automation service not available"}), 503

    data = request.get_json() or {}
    reason = data.get("reason", "Dismissed by admin")

    try:
        success = agent_automation_service.dismiss_suggestion(suggestion_id)
        if success:
            return jsonify({"success": True, "message": f"Suggestion {suggestion_id} dismissed"})
        return jsonify({"success": False, "error": "Suggestion not found or already processed"}), 404
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/agent/actions")
@login_required
@admin_required
def api_agent_action_history():
    """Get agent action history"""
    if not AGENT_AUTOMATION_AVAILABLE or not agent_automation_service:
        return jsonify({"success": False, "error": "Agent automation service not available"}), 503

    limit = request.args.get("limit", 100, type=int)

    try:
        actions = agent_automation_service.get_action_history(limit)
        return jsonify({"success": True, "actions": actions})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/agent/pause", methods=["POST"])
@login_required
@admin_required
def api_agent_pause():
    """Pause agent automation"""
    if not AGENT_AUTOMATION_AVAILABLE or not agent_automation_service:
        return jsonify({"success": False, "error": "Agent automation service not available"}), 503

    try:
        success = agent_automation_service.set_paused(True)
        if success:
            return jsonify({"success": True, "message": "Agent automation paused"})
        return jsonify({"success": False, "error": "Failed to pause automation"}), 500
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/agent/resume", methods=["POST"])
@login_required
@admin_required
def api_agent_resume():
    """Resume agent automation"""
    if not AGENT_AUTOMATION_AVAILABLE or not agent_automation_service:
        return jsonify({"success": False, "error": "Agent automation service not available"}), 503

    try:
        success = agent_automation_service.set_paused(False)
        if success:
            return jsonify({"success": True, "message": "Agent automation resumed"})
        return jsonify({"success": False, "error": "Failed to resume automation"}), 500
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


# ============================================================================
# DOMAIN MANAGEMENT - NPM, MULTI-DOMAIN, PER-DOMAIN DNS (extracted to domain_npm_routes.py)
# ============================================================================


# ============================================================================
# DEVICE REGISTRY
# ============================================================================


@security_network_bp.route("/api/devices")
@login_required
@admin_required
def api_devices_list():
    """List all devices with optional filters"""
    if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
        return jsonify({"success": False, "error": "Device registry not available"}), 503
    try:
        zone = request.args.get("zone")
        device_type = request.args.get("device_type")
        owner = request.args.get("owner")
        online = request.args.get("online")
        if online is not None:
            online = online.lower() == "true"
        status = request.args.get("status")
        devices = device_registry.get_devices(
            zone=zone,
            device_type=device_type,
            owner=owner,
            online=online,
            status=status,
        )
        return jsonify({"success": True, "devices": devices})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/devices/stats")
@login_required
@admin_required
def api_devices_stats():
    """Get device registry statistics"""
    if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
        return jsonify({"success": False, "error": "Device registry not available"}), 503
    try:
        stats = device_registry.get_stats()
        return jsonify({"success": True, "stats": stats})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/devices/unregistered")
@login_required
@admin_required
def api_devices_unregistered():
    """Get unregistered devices from AdGuard"""
    if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
        return jsonify({"success": False, "error": "Device registry not available"}), 503
    try:
        unregistered = device_registry.get_unregistered()
        return jsonify({"success": True, "devices": unregistered})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/devices/<int:device_id>")
@login_required
@admin_required
def api_devices_get(device_id):
    """Get a single device by ID"""
    if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
        return jsonify({"success": False, "error": "Device registry not available"}), 503
    try:
        device = device_registry.get_device(device_id)
        if not device:
            return jsonify({"success": False, "error": "Device not found"}), 404
        return jsonify({"success": True, "device": device})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/devices/register", methods=["POST"])
@login_required
@admin_required
def api_devices_register():
    """Register or update a device"""
    if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
        return jsonify({"success": False, "error": "Device registry not available"}), 503
    try:
        data = request.get_json() or {}
        result = device_registry.register_device(
            device_id=data.get("id"),
            friendly_name=data.get("friendly_name"),
            device_type=data.get("device_type"),
            owner=data.get("owner"),
            security_zone=data.get("security_zone"),
            notes=data.get("notes"),
        )
        return jsonify({"success": True, "device": result})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/devices/<int:device_id>", methods=["PUT"])
@login_required
@admin_required
def api_devices_update(device_id):
    """Update device fields"""
    if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
        return jsonify({"success": False, "error": "Device registry not available"}), 503
    try:
        data = request.get_json() or {}
        result = device_registry.update_device(device_id, data)
        if not result:
            return jsonify({"success": False, "error": "Device not found"}), 404
        return jsonify({"success": True, "device": result})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/devices/<int:device_id>", methods=["DELETE"])
@login_required
@admin_required
def api_devices_delete(device_id):
    """Delete a device from the registry"""
    if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
        return jsonify({"success": False, "error": "Device registry not available"}), 503
    try:
        result = device_registry.delete_device(device_id)
        if not result:
            return jsonify({"success": False, "error": "Device not found"}), 404
        return jsonify({"success": True, "message": f"Device {device_id} deleted"})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/devices/sync", methods=["POST"])
@login_required
@admin_required
def api_devices_sync():
    """Force full AdGuard sync"""
    if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
        return jsonify({"success": False, "error": "Device registry not available"}), 503
    try:
        result = device_registry.sync()
        return jsonify({"success": True, "sync": result})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/devices/<int:device_id>/dns-report")
@login_required
@admin_required
def api_device_dns_report(device_id):
    """Per-device DNS activity report"""
    if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
        return jsonify({"success": False, "error": "Device registry not available"}), 503
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503
    try:
        device = device_registry.get_device(device_id)
        if not device:
            return jsonify({"success": False, "error": "Device not found"}), 404
        ip_address = device.get("ip_address", "")
        if not ip_address:
            return jsonify({"success": False, "error": "Device has no IP address"}), 400
        report = adguard_service.get_client_report(ip_address)
        return jsonify(
            {
                "success": True,
                "device_name": device.get("friendly_name") or device.get("hostname", "Unknown"),
                "ip_address": ip_address,
                "report": report,
            }
        )
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


# ============================================================================
# SECURITY ALERT CONFIGURATION
# ============================================================================


@security_network_bp.route("/api/security/alert-config")
@login_required
@admin_required
def api_get_alert_config():
    """Get current security alert configuration"""
    from .security_alerts import _get_alert_config

    try:
        config = _get_alert_config()
        return jsonify({"success": True, "config": config})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@security_network_bp.route("/api/security/alert-config", methods=["POST"])
@login_required
@admin_required
def api_update_alert_config():
    """Update security alert configuration.

    Expects JSON body with alert type keys, e.g.:
    {
        "block": {"enabled": true, "telegram": true},
        "scan_result": {"enabled": true, "telegram": false},
        ...
    }
    """
    import json as json_lib
    from .security_alerts import VALID_ALERT_TYPES, _get_alert_config

    data = request.get_json() or {}

    # Merge with existing config
    config = _get_alert_config()
    for alert_type, settings in data.items():
        if alert_type not in VALID_ALERT_TYPES:
            return (
                jsonify({"success": False, "error": f"Invalid alert type: {alert_type}"}),
                400,
            )
        if not isinstance(settings, dict):
            continue
        if alert_type not in config:
            config[alert_type] = {}
        if "enabled" in settings:
            config[alert_type]["enabled"] = bool(settings["enabled"])
        if "telegram" in settings:
            config[alert_type]["telegram"] = bool(settings["telegram"])

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO security_auto_block_settings (setting_key, setting_value, description, updated_by, updated_at)
                VALUES ('alert_config', %s, 'Security alert Telegram/notification config', %s, NOW())
                ON CONFLICT (setting_key) DO UPDATE
                SET setting_value = EXCLUDED.setting_value,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = NOW()
                """,
                (json_lib.dumps(config), current_user.id),
            )

        return jsonify({"success": True, "config": config})
    except Exception as e:
        logger.exception("Route error: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


# ============================================================================
# NGINX CONFIGURATION MANAGEMENT (extracted to domain_npm_routes.py)
# ============================================================================
