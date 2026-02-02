"""
Security & Network Routes
=========================
Dashboard for security monitoring, network health, and system status.
"""

from flask import render_template, jsonify, request, redirect, url_for, flash
from flask_login import login_required, current_user
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor
import os

from . import security_network_bp


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


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def get_system_health():
    """Get system health metrics"""
    try:
        import psutil

        return {
            "cpu": {"percent": psutil.cpu_percent(interval=0.1)},
            "memory": {"percent": psutil.virtual_memory().percent},
            "disk": {"percent": psutil.disk_usage("/").percent},
        }
    except Exception:
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
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

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

        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error getting security stats: {e}")

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
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

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

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "failed_logins_24h": failed_logins,
                "recent_failures": [dict(r) for r in recent_failures],
                "system_health": get_system_health(),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/auto-block", methods=["POST"])
@login_required
@admin_required
def auto_block():
    """Auto-block detected threats"""
    # Placeholder for threat blocking logic
    return jsonify({"success": True, "blocked": 0, "message": "No threats detected"})


@security_network_bp.route("/api/audit-log")
@login_required
@admin_required
def audit_log():
    """Get audit log entries"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

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

        cur.close()
        conn.close()

        return jsonify({"success": True, "entries": [dict(e) for e in entries]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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

# Legacy network integration (fallback)
try:
    from network_integration import get_network_overview, check_security_threats

    NETWORK_AVAILABLE = True
except ImportError:
    NETWORK_AVAILABLE = False


@security_network_bp.route("/api/network/overview", methods=["GET"])
@login_required
@admin_required
def network_overview():
    """Get network overview"""
    if not NETWORK_AVAILABLE:
        return jsonify({"success": False, "error": "Network integration not available"}), 503

    try:
        overview = get_network_overview()
        return jsonify({"success": True, "data": overview})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/security/threats", methods=["GET"])
@login_required
@admin_required
def security_threats():
    """Get security threats"""
    if not NETWORK_AVAILABLE:
        return jsonify({"success": False, "error": "Network integration not available"}), 503

    try:
        threats = check_security_threats()
        return jsonify({"success": True, "threats": threats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/security/auto-block", methods=["POST"])
@login_required
@admin_required
def security_auto_block():
    """Auto-block detected threats"""
    if not NETWORK_AVAILABLE:
        return jsonify({"success": False, "error": "Network integration not available"}), 503

    try:
        blocked = auto_block_threats()
        return jsonify({"success": True, "blocked": blocked})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
                        "image": container.image.tags[0] if container.image.tags else container.image.short_id,
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
                print(f"Error processing container {container.name}: {e}")
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
        return jsonify({"success": False, "error": str(e)}), 500


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
            return jsonify({"success": False, "error": str(e)}), 500

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
            results[tool_name] = {"online": result == 0, "host": config["host"], "port": config["port"]}
        except Exception as e:
            results[tool_name] = {"online": False, "host": config["host"], "port": config["port"], "error": str(e)}

    return jsonify({"success": True, "tools": results})


# ============================================================================
# STACK STATUS API (Deprecated - use System Operations)
# ============================================================================


@security_network_bp.route("/api/stacks/status")
@login_required
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
            "network_available": NETWORK_AVAILABLE,
            "stack_available": STACK_AVAILABLE,
        }
    )


# ============================================================================
# SCANNER API ENDPOINTS
# ============================================================================


@security_network_bp.route("/api/scanner/nmap", methods=["POST"])
@login_required
@admin_required
def run_nmap_scan():
    """Run nmap scan on target"""
    if not STACK_AVAILABLE:
        return jsonify({"success": False, "error": "Scanner not available"}), 503

    data = request.get_json() or {}
    target = data.get("target", "")
    scan_type = data.get("scan_type", "quick")

    if not target:
        return jsonify({"success": False, "error": "Target is required"}), 400

    # Safety check - don't scan internal without explicit flag
    internal_prefixes = ["127.", "localhost", "192.168.", "10.", "172."]
    if any(target.startswith(p) for p in internal_prefixes):
        if not data.get("confirm_internal", False):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Internal target detected. Set confirm_internal=true to proceed.",
                        "requires_confirmation": True,
                    }
                ),
                400,
            )

    try:
        result = scanner_service.run_nmap_scan(target, scan_type)

        # Log the scan
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO audit_log (action, user_id, details)
                   VALUES ('security_scan', %s, %s)""",
                (current_user.id, {"type": "nmap", "target": target, "scan_type": scan_type}),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/scanner/nikto", methods=["POST"])
@login_required
@admin_required
def run_nikto_scan():
    """Run nikto web vulnerability scan"""
    if not STACK_AVAILABLE:
        return jsonify({"success": False, "error": "Scanner not available"}), 503

    data = request.get_json() or {}
    target = data.get("target", "")

    if not target:
        return jsonify({"success": False, "error": "Target is required"}), 400

    try:
        result = scanner_service.run_nikto_scan(target)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/scanner/nuclei", methods=["POST"])
@login_required
@admin_required
def run_nuclei_scan():
    """Run nuclei vulnerability scan"""
    if not STACK_AVAILABLE:
        return jsonify({"success": False, "error": "Scanner not available"}), 503

    data = request.get_json() or {}
    target = data.get("target", "")
    templates = data.get("templates", "cves")

    if not target:
        return jsonify({"success": False, "error": "Target is required"}), 400

    try:
        result = scanner_service.run_nuclei_scan(target, templates)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/scanner/ssl", methods=["POST"])
@login_required
@admin_required
def run_ssl_scan():
    """Run SSL/TLS analysis"""
    if not STACK_AVAILABLE:
        return jsonify({"success": False, "error": "Scanner not available"}), 503

    data = request.get_json() or {}
    domain = data.get("domain", "")

    if not domain:
        return jsonify({"success": False, "error": "Domain is required"}), 400

    try:
        result = scanner_service.run_ssl_scan(domain)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/scanner/zap", methods=["POST"])
@login_required
@admin_required
def run_zap_scan():
    """Start ZAP web application scan"""
    if not STACK_AVAILABLE:
        return jsonify({"success": False, "error": "Scanner not available"}), 503

    data = request.get_json() or {}
    target = data.get("target", "")
    scan_type = data.get("scan_type", "spider")

    if not target:
        return jsonify({"success": False, "error": "Target is required"}), 400

    try:
        result = scanner_service.start_zap_scan(target, scan_type)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/scanner/status")
@login_required
@admin_required
def scanner_status():
    """Get scanner service status"""
    if not STACK_AVAILABLE:
        return jsonify({"success": False, "error": "Scanner not available"}), 503

    try:
        zap_status = scanner_service.get_zap_status()
        return jsonify(
            {
                "success": True,
                "zap": {
                    "online": zap_status is not None,
                    "version": zap_status.get("version") if zap_status else None,
                },
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# SCAN RESULTS API
# ============================================================================


@security_network_bp.route("/api/scans")
@login_required
@admin_required
def list_scans():
    """List all scan results"""
    import os
    import glob

    scans_dir = "/mnt/archie_brain/security_scans"
    scans = []

    try:
        for pattern in ["*.xml", "*.json"]:
            for filepath in glob.glob(os.path.join(scans_dir, pattern)):
                filename = os.path.basename(filepath)
                stat = os.stat(filepath)

                # Parse scan type from filename
                scan_type = "unknown"
                if filename.startswith("nmap_"):
                    scan_type = "nmap"
                elif filename.startswith("nikto_"):
                    scan_type = "nikto"
                elif filename.startswith("nuclei_"):
                    scan_type = "nuclei"
                elif filename.startswith("ssl_"):
                    scan_type = "ssl"
                elif filename.startswith("zap_"):
                    scan_type = "zap"

                scans.append(
                    {
                        "filename": filename,
                        "scan_type": scan_type,
                        "size": stat.st_size,
                        "created_at": stat.st_mtime,
                    }
                )

        # Sort by creation time, newest first
        scans.sort(key=lambda x: x["created_at"], reverse=True)

        return jsonify({"success": True, "scans": scans[:50]})  # Limit to 50
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/scans/<filename>")
@login_required
@admin_required
def get_scan_result(filename):
    """Get scan result contents"""
    import os

    scans_dir = "/mnt/archie_brain/security_scans"

    # Security: validate filename
    if ".." in filename or "/" in filename or "\\" in filename:
        return jsonify({"success": False, "error": "Invalid filename"}), 400

    filepath = os.path.join(scans_dir, filename)

    if not os.path.exists(filepath):
        return jsonify({"success": False, "error": "Scan not found"}), 404

    try:
        with open(filepath, "r") as f:
            content = f.read()

        # Try to parse as JSON if it's a JSON file
        if filename.endswith(".json"):
            import json

            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                pass

        return jsonify({"success": True, "filename": filename, "content": content})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# ADGUARD INTEGRATION
# ============================================================================


@security_network_bp.route("/api/adguard/stats")
@login_required
@admin_required
def adguard_stats():
    """Get AdGuard statistics"""
    if not STACK_AVAILABLE:
        return jsonify({"success": False, "error": "Stack not available"}), 503

    try:
        stats = adguard_api.get_stats()
        if stats:
            return jsonify({"success": True, "stats": stats})
        return jsonify({"success": False, "error": "Could not connect to AdGuard"}), 503
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/adguard/block", methods=["POST"])
@login_required
@admin_required
def adguard_block_domain():
    """Block a domain in AdGuard"""
    if not STACK_AVAILABLE:
        return jsonify({"success": False, "error": "Stack not available"}), 503

    data = request.get_json() or {}
    domain = data.get("domain", "")

    if not domain:
        return jsonify({"success": False, "error": "Domain is required"}), 400

    try:
        success = adguard_api.block_domain(domain)
        if success:
            return jsonify({"success": True, "message": f"Domain {domain} blocked"})
        return jsonify({"success": False, "error": "Failed to block domain"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# INTERNAL SECURITY - FIREWALL & CONNECTIONS
# ============================================================================


@security_network_bp.route("/api/firewall/status")
@login_required
@admin_required
def api_firewall_status():
    """Get firewall status"""
    if not SECURITY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Security service not available"}), 503

    try:
        status = get_firewall_status()
        return jsonify({"success": True, "firewall": status})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/connections/active")
@login_required
@admin_required
def api_active_connections():
    """Get active network connections"""
    if not SECURITY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Security service not available"}), 503

    try:
        connections = get_active_connections()
        return jsonify({"success": True, "connections": connections})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# IP ACCESS CONTROL
# ============================================================================


@security_network_bp.route("/api/ip-access")
@login_required
@admin_required
def api_ip_access_list():
    """Get blocked and whitelisted IPs"""
    if not SECURITY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Security service not available"}), 503

    try:
        blocked = get_blocked_ips()
        whitelisted = get_whitelisted_ips()
        return jsonify({"success": True, "blocked": blocked, "whitelisted": whitelisted})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/ip-access/block", methods=["POST"])
@login_required
@admin_required
def api_block_ip():
    """Block an IP address"""
    if not SECURITY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Security service not available"}), 503

    data = request.get_json() or {}
    ip_address = data.get("ip_address", "")
    reason = data.get("reason", "Manually blocked")
    duration = data.get("duration_hours")

    if not ip_address:
        return jsonify({"success": False, "error": "IP address is required"}), 400

    try:
        result = block_ip(ip_address, reason, current_user.id, duration)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/ip-access/unblock", methods=["POST"])
@login_required
@admin_required
def api_unblock_ip():
    """Unblock an IP address"""
    if not SECURITY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Security service not available"}), 503

    data = request.get_json() or {}
    ip_address = data.get("ip_address", "")

    if not ip_address:
        return jsonify({"success": False, "error": "IP address is required"}), 400

    try:
        result = unblock_ip(ip_address, current_user.id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# AUTO-BLOCK SETTINGS
# ============================================================================


@security_network_bp.route("/api/auto-block/settings")
@login_required
@admin_required
def api_auto_block_settings():
    """Get auto-block settings"""
    if not SECURITY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Security service not available"}), 503

    try:
        settings = get_auto_block_settings()
        return jsonify({"success": True, "settings": settings})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/auto-block/settings", methods=["POST"])
@login_required
@admin_required
def api_update_auto_block_settings():
    """Update auto-block settings"""
    if not SECURITY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Security service not available"}), 503

    data = request.get_json() or {}

    try:
        success = update_auto_block_settings(data, current_user.id)
        if success:
            return jsonify({"success": True, "message": "Settings updated"})
        return jsonify({"success": False, "error": "Failed to update settings"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/auto-block/analyze")
@login_required
@admin_required
def api_analyze_threats():
    """Analyze failed logins for threats"""
    if not SECURITY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Security service not available"}), 503

    hours = request.args.get("hours", 24, type=int)

    try:
        analysis = analyze_failed_logins(hours)
        return jsonify({"success": True, "analysis": analysis})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/auto-block/execute", methods=["POST"])
@login_required
@admin_required
def api_execute_auto_block():
    """Execute auto-block on detected threats"""
    if not SECURITY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Security service not available"}), 503

    try:
        result = auto_block_threats(current_user.id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# SECURITY EVENTS
# ============================================================================


@security_network_bp.route("/api/events")
@login_required
@admin_required
def api_security_events():
    """Get security events"""
    if not SECURITY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Security service not available"}), 503

    status = request.args.get("status")
    severity = request.args.get("severity")
    event_type = request.args.get("type")
    limit = request.args.get("limit", 50, type=int)

    try:
        events = get_security_events(status, severity, event_type, limit)
        return jsonify({"success": True, "events": events})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/events/<int:event_id>/resolve", methods=["POST"])
@login_required
@admin_required
def api_resolve_event(event_id):
    """Resolve a security event"""
    if not SECURITY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Security service not available"}), 503

    data = request.get_json() or {}
    notes = data.get("notes", "")

    try:
        result = resolve_security_event(event_id, current_user.id, notes)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# SSL CERTIFICATE MONITORING
# ============================================================================


@security_network_bp.route("/api/ssl/check", methods=["POST"])
@login_required
@admin_required
def api_check_ssl():
    """Check SSL certificate for a domain"""
    if not SECURITY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Security service not available"}), 503

    data = request.get_json() or {}
    domain = data.get("domain", "")
    port = data.get("port", 443)

    if not domain:
        return jsonify({"success": False, "error": "Domain is required"}), 400

    try:
        result = check_ssl_certificate(domain, port)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/ssl/monitors")
@login_required
@admin_required
def api_ssl_monitors():
    """Get SSL monitors"""
    if not SECURITY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Security service not available"}), 503

    try:
        monitors = get_ssl_monitors()
        return jsonify({"success": True, "monitors": monitors})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/ssl/monitors", methods=["POST"])
@login_required
@admin_required
def api_add_ssl_monitor():
    """Add SSL monitor for a domain"""
    if not SECURITY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Security service not available"}), 503

    data = request.get_json() or {}
    domain = data.get("domain", "")
    alert_days = data.get("alert_days", 30)

    if not domain:
        return jsonify({"success": False, "error": "Domain is required"}), 400

    try:
        result = add_ssl_monitor(domain, current_user.id, alert_days)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/ssl/refresh", methods=["POST"])
@login_required
@admin_required
def api_refresh_ssl_monitors():
    """Refresh all SSL monitors"""
    if not SECURITY_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Security service not available"}), 503

    try:
        result = refresh_ssl_monitors()
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# REPORT GENERATION
# ============================================================================


@security_network_bp.route("/api/reports")
@login_required
@admin_required
def api_list_reports():
    """List all generated reports"""
    if not REPORT_SERVICE_AVAILABLE:
        return jsonify({"success": False, "error": "Report service not available"}), 503

    try:
        reports = list_reports()
        return jsonify({"success": True, "reports": reports})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
        return jsonify({"success": False, "error": str(e)}), 500


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
        return jsonify({"success": False, "error": str(e)}), 500


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
        return jsonify({"success": False, "error": str(e)}), 500


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
        return jsonify({"success": False, "error": str(e)}), 500
