"""
Security & Network Routes
=========================
Dashboard for security monitoring, network health, and system status.
"""

from flask import render_template, jsonify, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor
import os

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

    except Exception as e:
        print(f"Error getting security stats: {e}")

    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
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
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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

        return jsonify({"success": True, "entries": [dict(e) for e in entries]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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


@security_network_bp.route("/api/network/overview", methods=["GET"])
@login_required
@admin_required
def network_overview():
    """Get network overview"""
    if not NETWORK_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Network integration not available"}),
            503,
        )

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
        return (
            jsonify({"success": False, "error": "Network integration not available"}),
            503,
        )

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
        return (
            jsonify({"success": False, "error": "Network integration not available"}),
            503,
        )

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
                "error": str(e),
            }

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
                (
                    current_user.id,
                    {"type": "nmap", "target": target, "scan_type": scan_type},
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass

        # Security alert for scan completion
        create_security_alert(
            "scan_result",
            f"Nmap scan completed: {target}",
            f"Nmap {scan_type} scan on {target} completed.",
            priority="normal",
            telegram=False,
        )

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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

        # Security alert for scan completion
        create_security_alert(
            "scan_result",
            f"Nikto scan completed: {target}",
            f"Nikto web vulnerability scan on {target} completed.",
            priority="normal",
            telegram=False,
        )

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
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

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
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

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
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

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
        return jsonify({"success": False, "error": str(e)}), 500


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
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

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
        return jsonify({"success": False, "error": str(e)}), 500


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
        return jsonify({"success": False, "error": str(e)}), 500


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
        return jsonify({"success": False, "error": str(e)}), 500


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
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

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
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

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
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

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
        return (
            jsonify({"success": False, "error": "Security service not available"}),
            503,
        )

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
    except Exception:
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
    except Exception:
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
    except Exception:
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
    except Exception:
        stats["recon"] = {"available": False}

    # Hostinger DNS
    try:
        if HOSTINGER_SERVICE_AVAILABLE and hostinger_service:
            stats["hostinger"] = {"available": True}
        else:
            stats["hostinger"] = {"available": False}
    except Exception:
        stats["hostinger"] = {"available": False}

    return jsonify({"success": True, "stats": stats})


# ============================================================================
# DNS MANAGEMENT - ADGUARD (Full API)
# ============================================================================


@security_network_bp.route("/api/dns/adguard/stats")
@login_required
@admin_required
def api_dns_adguard_stats():
    """Full AdGuard statistics"""
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503

    try:
        stats = adguard_service.get_stats()
        status = adguard_service.get_status()
        if stats is None and status is None:
            return jsonify({"success": False, "error": "Could not connect to AdGuard"}), 503
        return jsonify(
            {
                "success": True,
                "stats": stats,
                "status": status,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/adguard/querylog")
@login_required
@admin_required
def api_dns_adguard_querylog():
    """AdGuard query log"""
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503

    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    search = request.args.get("search")
    response_status = request.args.get("response_status")

    try:
        result = adguard_service.get_query_log(limit, offset, search, response_status)
        if result is None:
            return jsonify({"success": False, "error": "Could not fetch query log"}), 503
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/adguard/filters")
@login_required
@admin_required
def api_dns_adguard_filters_get():
    """List AdGuard filter lists"""
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503

    try:
        result = adguard_service.get_filtering_status()
        if result is None:
            return jsonify({"success": False, "error": "Could not fetch filters"}), 503
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/adguard/filters", methods=["POST"])
@login_required
@admin_required
def api_dns_adguard_filters_add():
    """Add an AdGuard filter list"""
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503

    data = request.get_json() or {}
    name = data.get("name", "")
    url = data.get("url", "")
    enabled = data.get("enabled", True)

    if not name or not url:
        return jsonify({"success": False, "error": "Name and URL are required"}), 400

    try:
        result = adguard_service.add_filter(name, url, enabled)
        if result is None:
            return jsonify({"success": False, "error": "Failed to add filter"}), 500
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/adguard/filters/<path:url>", methods=["PUT"])
@login_required
@admin_required
def api_dns_adguard_filters_toggle(url):
    """Toggle an AdGuard filter on/off"""
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503

    data = request.get_json() or {}
    enabled = data.get("enabled", True)

    try:
        result = adguard_service.toggle_filter(url, enabled)
        if result is None:
            return jsonify({"success": False, "error": "Failed to toggle filter"}), 500
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/adguard/filters/<path:url>", methods=["DELETE"])
@login_required
@admin_required
def api_dns_adguard_filters_remove(url):
    """Remove an AdGuard filter list"""
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503

    try:
        result = adguard_service.remove_filter(url)
        if result is None:
            return jsonify({"success": False, "error": "Failed to remove filter"}), 500
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/adguard/filters/refresh", methods=["POST"])
@login_required
@admin_required
def api_dns_adguard_filters_refresh():
    """Refresh all AdGuard filter lists"""
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503

    try:
        result = adguard_service.refresh_filters()
        if result is None:
            return jsonify({"success": False, "error": "Failed to refresh filters"}), 500
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/adguard/rewrites")
@login_required
@admin_required
def api_dns_adguard_rewrites_get():
    """List DNS rewrites"""
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503

    try:
        result = adguard_service.get_rewrites()
        if result is None:
            return jsonify({"success": False, "error": "Could not fetch rewrites"}), 503
        return jsonify({"success": True, "rewrites": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/adguard/rewrites", methods=["POST"])
@login_required
@admin_required
def api_dns_adguard_rewrites_add():
    """Add a DNS rewrite"""
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503

    data = request.get_json() or {}
    domain = data.get("domain", "")
    answer = data.get("answer", "")

    if not domain or not answer:
        return jsonify({"success": False, "error": "Domain and answer are required"}), 400

    try:
        result = adguard_service.add_rewrite(domain, answer)
        if result is None:
            return jsonify({"success": False, "error": "Failed to add rewrite"}), 500
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/adguard/rewrites", methods=["DELETE"])
@login_required
@admin_required
def api_dns_adguard_rewrites_delete():
    """Delete a DNS rewrite"""
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503

    data = request.get_json() or {}
    domain = data.get("domain", "")
    answer = data.get("answer", "")

    if not domain or not answer:
        return jsonify({"success": False, "error": "Domain and answer are required"}), 400

    try:
        result = adguard_service.delete_rewrite(domain, answer)
        if result is None:
            return jsonify({"success": False, "error": "Failed to delete rewrite"}), 500
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/adguard/clients")
@login_required
@admin_required
def api_dns_adguard_clients():
    """Get AdGuard client statistics"""
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503

    try:
        result = adguard_service.get_clients()
        if result is None:
            return jsonify({"success": False, "error": "Could not fetch clients"}), 503
        return jsonify({"success": True, "clients": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/adguard/rules")
@login_required
@admin_required
def api_dns_adguard_rules_get():
    """Get AdGuard user rules"""
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503

    try:
        result = adguard_service.get_user_rules()
        if result is None:
            return jsonify({"success": False, "error": "Could not fetch rules"}), 503
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/adguard/rules", methods=["POST"])
@login_required
@admin_required
def api_dns_adguard_rules_set():
    """Set AdGuard user rules"""
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503

    data = request.get_json() or {}
    rules = data.get("rules")

    if rules is None:
        return jsonify({"success": False, "error": "Rules are required"}), 400

    # Accept rules as a string (newline-separated) or list
    if isinstance(rules, str):
        rules = [r for r in rules.split("\n") if r.strip()]

    try:
        result = adguard_service.set_user_rules(rules)
        if result is None:
            return jsonify({"success": False, "error": "Failed to set rules"}), 500
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/adguard/block", methods=["POST"])
@login_required
@admin_required
def api_dns_adguard_block():
    """Block a domain via AdGuard"""
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503

    data = request.get_json() or {}
    domain = data.get("domain", "")

    if not domain:
        return jsonify({"success": False, "error": "Domain is required"}), 400

    try:
        success = adguard_service.block_domain(domain)
        if success:
            return jsonify({"success": True, "message": f"Domain {domain} blocked"})
        return jsonify({"success": False, "error": "Failed to block domain"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/adguard/unblock", methods=["POST"])
@login_required
@admin_required
def api_dns_adguard_unblock():
    """Unblock a domain via AdGuard"""
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503

    data = request.get_json() or {}
    domain = data.get("domain", "")

    if not domain:
        return jsonify({"success": False, "error": "Domain is required"}), 400

    try:
        success = adguard_service.unblock_domain(domain)
        if success:
            return jsonify({"success": True, "message": f"Domain {domain} unblocked"})
        return jsonify({"success": False, "error": "Failed to unblock domain"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/adguard/protection", methods=["POST"])
@login_required
@admin_required
def api_dns_adguard_protection():
    """Toggle AdGuard protection on/off"""
    if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
        return jsonify({"success": False, "error": "AdGuard service not available"}), 503

    data = request.get_json() or {}
    enabled = data.get("enabled", True)

    try:
        result = adguard_service.set_protection(enabled)
        if result is None:
            return jsonify({"success": False, "error": "Failed to toggle protection"}), 500
        return jsonify({"success": True, "protection_enabled": enabled})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# DNS MANAGEMENT - HOSTINGER
# ============================================================================


@security_network_bp.route("/api/dns/hostinger/records")
@login_required
@admin_required
def api_dns_hostinger_records_get():
    """List Hostinger DNS records"""
    if not HOSTINGER_SERVICE_AVAILABLE or not hostinger_service:
        return jsonify({"success": False, "error": "Hostinger service not available"}), 503

    domain = request.args.get("domain")

    try:
        result = hostinger_service.get_dns_records(domain)
        if result is None:
            return jsonify({"success": False, "error": "Could not fetch DNS records"}), 503
        if isinstance(result, dict) and "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 500
        return jsonify({"success": True, "records": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/hostinger/records", methods=["POST"])
@login_required
@admin_required
def api_dns_hostinger_records_add():
    """Add a Hostinger DNS record"""
    if not HOSTINGER_SERVICE_AVAILABLE or not hostinger_service:
        return jsonify({"success": False, "error": "Hostinger service not available"}), 503

    data = request.get_json() or {}
    record_type = data.get("record_type", "")
    name = data.get("name", "")
    content = data.get("content", "")
    ttl = data.get("ttl", 3600)
    domain = data.get("domain")

    if not record_type or not name or not content:
        return jsonify({"success": False, "error": "record_type, name, and content are required"}), 400

    try:
        result = hostinger_service.add_dns_record(record_type, name, content, ttl, domain)
        if result is None:
            return jsonify({"success": False, "error": "Failed to add DNS record"}), 500
        if isinstance(result, dict) and "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 500

        create_security_alert(
            "dns_change",
            f"DNS Record Added: {name}",
            f"New {record_type} record added: {name} -> {content} (TTL: {ttl})",
            priority="normal",
        )

        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/hostinger/records/<record_id>", methods=["PUT"])
@login_required
@admin_required
def api_dns_hostinger_records_update(record_id):
    """Update a Hostinger DNS record"""
    if not HOSTINGER_SERVICE_AVAILABLE or not hostinger_service:
        return jsonify({"success": False, "error": "Hostinger service not available"}), 503

    data = request.get_json() or {}
    domain = data.get("domain")
    record_type = data.get("record_type", "")
    name = data.get("name", "")
    content = data.get("content", "")
    ttl = data.get("ttl", 3600)

    if not record_type or not name or not content:
        return jsonify({"success": False, "error": "record_type, name, and content are required"}), 400

    try:
        records = [{"type": record_type, "name": name, "content": content, "ttl": ttl}]
        result = hostinger_service.update_dns_records(records, overwrite=False, domain=domain)
        if result is None:
            return jsonify({"success": False, "error": "Failed to update DNS record"}), 500
        if isinstance(result, dict) and "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 500

        create_security_alert(
            "dns_change",
            f"DNS Record Updated: {name}",
            f"Updated {record_type} record: {name} -> {content}",
            priority="normal",
        )

        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/hostinger/records/<record_id>", methods=["DELETE"])
@login_required
@admin_required
def api_dns_hostinger_records_delete(record_id):
    """Delete a Hostinger DNS record"""
    if not HOSTINGER_SERVICE_AVAILABLE or not hostinger_service:
        return jsonify({"success": False, "error": "Hostinger service not available"}), 503

    data = request.get_json() or {}
    domain = data.get("domain")
    record_type = data.get("record_type")
    name = data.get("name")

    try:
        result = hostinger_service.delete_dns_records(record_type, name, domain)
        if result is None:
            return jsonify({"success": False, "error": "Failed to delete DNS record"}), 500
        if isinstance(result, dict) and "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 500
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/dns/hostinger/domains")
@login_required
@admin_required
def api_dns_hostinger_domains():
    """List Hostinger domain portfolio"""
    if not HOSTINGER_SERVICE_AVAILABLE or not hostinger_service:
        return jsonify({"success": False, "error": "Hostinger service not available"}), 503

    try:
        result = hostinger_service.get_domain_list()
        if result is None:
            return jsonify({"success": False, "error": "Could not fetch domain list"}), 503
        if isinstance(result, dict) and "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 500
        return jsonify({"success": True, "domains": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# SURVEILLANCE - HOME ASSISTANT CAMERAS
# ============================================================================


@security_network_bp.route("/api/surveillance/cameras")
@login_required
@admin_required
def api_surveillance_cameras():
    """Get all camera states via auto-discovery"""
    if not SURVEILLANCE_SERVICE_AVAILABLE or not surveillance_service:
        return (
            jsonify({"success": False, "error": "Surveillance service not configured"}),
            503,
        )

    try:
        cameras = surveillance_service.get_cameras()
        alarm_state = surveillance_service.get_alarm_state()
        return jsonify(
            {
                "success": True,
                "cameras": cameras,
                "alarm": alarm_state,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/surveillance/camera/<path:entity_id>/snapshot")
@login_required
@admin_required
def api_surveillance_snapshot(entity_id):
    """Proxy camera snapshot image from HA"""
    if not SURVEILLANCE_SERVICE_AVAILABLE or not surveillance_service:
        return (
            jsonify({"success": False, "error": "Surveillance service not configured"}),
            503,
        )

    try:
        image_bytes = surveillance_service.get_camera_snapshot(entity_id)
        if image_bytes is None:
            return (
                jsonify({"success": False, "error": "Could not fetch snapshot"}),
                404,
            )
        return Response(
            image_bytes,
            mimetype="image/jpeg",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/surveillance/camera/<path:entity_id>/stream")
@login_required
@admin_required
def api_surveillance_stream(entity_id):
    """Get camera MJPEG stream URL"""
    if not SURVEILLANCE_SERVICE_AVAILABLE or not surveillance_service:
        return (
            jsonify({"success": False, "error": "Surveillance service not configured"}),
            503,
        )

    try:
        stream_url = surveillance_service.get_camera_stream_url(entity_id)
        if stream_url is None:
            return (
                jsonify({"success": False, "error": "Invalid camera entity"}),
                404,
            )
        return jsonify({"success": True, "stream_url": stream_url})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/surveillance/status")
@login_required
@admin_required
def api_surveillance_status():
    """HA connection status + camera count"""
    if not SURVEILLANCE_SERVICE_AVAILABLE or not surveillance_service:
        return jsonify(
            {
                "success": True,
                "status": {
                    "connected": False,
                    "error": "HA_API_TOKEN not configured",
                    "camera_count": 0,
                },
            }
        )

    try:
        health = surveillance_service.check_health()
        return jsonify({"success": True, "status": health})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/surveillance/system/arm", methods=["POST"])
@login_required
@admin_required
def api_surveillance_arm():
    """Arm the surveillance system"""
    if not SURVEILLANCE_SERVICE_AVAILABLE or not surveillance_service:
        return (
            jsonify({"success": False, "error": "Surveillance service not configured"}),
            503,
        )

    try:
        success = surveillance_service.arm_system()
        if success:
            return jsonify({"success": True, "message": "System armed"})
        return (
            jsonify({"success": False, "error": "Failed to arm system"}),
            500,
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/surveillance/system/disarm", methods=["POST"])
@login_required
@admin_required
def api_surveillance_disarm():
    """Disarm the surveillance system"""
    if not SURVEILLANCE_SERVICE_AVAILABLE or not surveillance_service:
        return (
            jsonify({"success": False, "error": "Surveillance service not configured"}),
            503,
        )

    try:
        success = surveillance_service.disarm_system()
        if success:
            return jsonify({"success": True, "message": "System disarmed"})
        return (
            jsonify({"success": False, "error": "Failed to disarm system"}),
            500,
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/surveillance/events")
@login_required
@admin_required
def api_surveillance_events():
    """Get recent surveillance events"""
    if not SURVEILLANCE_SERVICE_AVAILABLE or not surveillance_service:
        return (
            jsonify({"success": False, "error": "Surveillance service not configured"}),
            503,
        )

    hours = request.args.get("hours", 24, type=int)

    try:
        events = surveillance_service.get_recent_events(hours)
        return jsonify({"success": True, "events": events})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# RECONNAISSANCE - ARGUS
# ============================================================================


@security_network_bp.route("/api/recon/modules")
@login_required
@admin_required
def api_recon_modules():
    """Get available Argus reconnaissance modules"""
    if not ARGUS_SERVICE_AVAILABLE or not argus_service:
        return jsonify({"success": False, "error": "Argus service not available"}), 503

    try:
        modules = argus_service.get_modules()
        return jsonify(
            {
                "success": True,
                "modules": modules,
                "total_count": argus_service.get_module_count(),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/recon/scan", methods=["POST"])
@login_required
@admin_required
def api_recon_start_scan():
    """Start an Argus reconnaissance scan"""
    if not ARGUS_SERVICE_AVAILABLE or not argus_service:
        return jsonify({"success": False, "error": "Argus service not available"}), 503

    data = request.get_json() or {}
    module_name = data.get("module_name", "")
    target = data.get("target", "")
    options = data.get("options", {})

    if not module_name or not target:
        return jsonify({"success": False, "error": "module_name and target are required"}), 400

    try:
        triggered_by = getattr(current_user, "username", "user")
        scan_id = argus_service.start_scan(module_name, target, options, triggered_by)
        if scan_id is None:
            return jsonify({"success": False, "error": "Failed to start scan"}), 500
        return jsonify({"success": True, "scan_id": scan_id, "message": "Scan started"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/recon/scan/<int:scan_id>")
@login_required
@admin_required
def api_recon_scan_status(scan_id):
    """Get scan status and results"""
    if not ARGUS_SERVICE_AVAILABLE or not argus_service:
        return jsonify({"success": False, "error": "Argus service not available"}), 503

    try:
        scan = argus_service.get_scan(scan_id)
        if scan is None:
            return jsonify({"success": False, "error": "Scan not found"}), 404
        return jsonify({"success": True, "scan": scan})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/recon/history")
@login_required
@admin_required
def api_recon_history():
    """Get reconnaissance scan history"""
    if not ARGUS_SERVICE_AVAILABLE or not argus_service:
        return jsonify({"success": False, "error": "Argus service not available"}), 503

    limit = request.args.get("limit", 50, type=int)

    try:
        history = argus_service.get_scan_history(limit)
        return jsonify({"success": True, "history": history})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/recon/scan/<int:scan_id>", methods=["DELETE"])
@login_required
@admin_required
def api_recon_delete_scan(scan_id):
    """Delete a reconnaissance scan"""
    if not ARGUS_SERVICE_AVAILABLE or not argus_service:
        return jsonify({"success": False, "error": "Argus service not available"}), 503

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM security_recon_scans WHERE id = %s", (scan_id,))
        affected = cur.rowcount
        conn.commit()

        if affected == 0:
            return jsonify({"success": False, "error": "Scan not found"}), 404
        return jsonify({"success": True, "message": f"Scan {scan_id} deleted"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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
        return jsonify({"success": False, "error": str(e)}), 500


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
        return jsonify({"success": False, "error": str(e)}), 500


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
        return jsonify({"success": False, "error": str(e)}), 500


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
        return jsonify({"success": False, "error": str(e)}), 500


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
        return jsonify({"success": False, "error": str(e)}), 500


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
        return jsonify({"success": False, "error": str(e)}), 500


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
        return jsonify({"success": False, "error": str(e)}), 500


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
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# DOMAIN MANAGEMENT - NPM PROXY HOSTS
# ============================================================================


@security_network_bp.route("/api/domains/proxy-hosts")
@login_required
@admin_required
def api_domains_proxy_hosts_list():
    """List all NPM proxy hosts"""
    if not NPM_SERVICE_AVAILABLE or not npm_service:
        return jsonify({"success": False, "error": "NPM service not available"}), 503

    try:
        hosts = npm_service.list_proxy_hosts()
        return jsonify({"success": True, "proxy_hosts": hosts})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/domains/proxy-hosts", methods=["POST"])
@login_required
@admin_required
def api_domains_proxy_hosts_create():
    """Create a new NPM proxy host"""
    if not NPM_SERVICE_AVAILABLE or not npm_service:
        return jsonify({"success": False, "error": "NPM service not available"}), 503

    data = request.get_json() or {}
    domain = data.get("domain", "")
    forward_host = data.get("forward_host", "192.168.1.200")
    forward_port = data.get("forward_port", 3000)
    ssl = data.get("ssl", True)

    if not domain:
        return jsonify({"success": False, "error": "Domain is required"}), 400

    try:
        result = npm_service.create_proxy_host(
            domain=domain,
            forward_host=forward_host,
            forward_port=int(forward_port),
            ssl=ssl,
        )
        if isinstance(result, dict) and "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 500
        return jsonify({"success": True, "proxy_host": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/domains/proxy-hosts/<int:host_id>", methods=["DELETE"])
@login_required
@admin_required
def api_domains_proxy_hosts_delete(host_id):
    """Delete a NPM proxy host"""
    if not NPM_SERVICE_AVAILABLE or not npm_service:
        return jsonify({"success": False, "error": "NPM service not available"}), 503

    try:
        result = npm_service.delete_proxy_host(host_id)
        if isinstance(result, dict) and "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 500
        return jsonify({"success": True, "message": f"Proxy host {host_id} deleted"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/domains/proxy-hosts/<int:host_id>", methods=["PUT"])
@login_required
@admin_required
def api_domains_proxy_hosts_update(host_id):
    """Update a NPM proxy host"""
    if not NPM_SERVICE_AVAILABLE or not npm_service:
        return jsonify({"success": False, "error": "NPM service not available"}), 503

    try:
        data = request.get_json()
        update_data = {}
        if "forward_host" in data:
            update_data["forward_host"] = data["forward_host"]
        if "forward_port" in data:
            update_data["forward_port"] = int(data["forward_port"])
        if not update_data:
            return jsonify({"success": False, "error": "No fields to update"}), 400
        result = npm_service.update_proxy_host(host_id, update_data)
        if isinstance(result, dict) and "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 500
        return jsonify({"success": True, "message": f"Proxy host {host_id} updated"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@security_network_bp.route("/api/domains/overview")
@login_required
@admin_required
def api_domains_overview():
    """Combined domain overview: DNS records + NPM proxy hosts + public IP"""
    result = {"dns_records": [], "proxy_hosts": [], "public_ip": None}

    # Get public IP via Hostinger service
    if HOSTINGER_SERVICE_AVAILABLE and hostinger_service:
        try:
            result["public_ip"] = hostinger_service.get_public_ip()
        except Exception:
            pass

    # Get DNS records
    if HOSTINGER_SERVICE_AVAILABLE and hostinger_service:
        try:
            records = hostinger_service.get_dns_records()
            if isinstance(records, list):
                result["dns_records"] = records
        except Exception:
            pass

    # Get NPM proxy hosts
    if NPM_SERVICE_AVAILABLE and npm_service:
        try:
            hosts = npm_service.list_proxy_hosts()
            if isinstance(hosts, list):
                result["proxy_hosts"] = hosts
        except Exception:
            pass

    return jsonify({"success": True, **result})


@security_network_bp.route("/api/domains/quick-setup", methods=["POST"])
@login_required
@admin_required
def api_domains_quick_setup():
    """One-click subdomain setup: DNS A record + NPM proxy + SSL"""
    if not HOSTINGER_SERVICE_AVAILABLE or not hostinger_service:
        return jsonify({"success": False, "error": "Hostinger service not available"}), 503
    if not NPM_SERVICE_AVAILABLE or not npm_service:
        return jsonify({"success": False, "error": "NPM service not available"}), 503

    data = request.get_json() or {}
    subdomain = data.get("subdomain", "").strip()
    forward_host = data.get("forward_host", "192.168.1.200").strip()
    forward_port = data.get("forward_port", 3000)

    if not subdomain:
        return jsonify({"success": False, "error": "Subdomain is required"}), 400

    root_domain = hostinger_service.domain
    full_domain = f"{subdomain}.{root_domain}"
    steps = {"dns": None, "proxy": None, "ssl": None}

    # Step 1: Get public IP
    public_ip = hostinger_service.get_public_ip()
    if not public_ip:
        return jsonify({"success": False, "error": "Could not determine public IP"}), 500

    # Step 2: Create DNS A record
    try:
        dns_result = hostinger_service.add_dns_record(
            record_type="A",
            name=subdomain,
            value=public_ip,
            ttl=3600,
        )
        if isinstance(dns_result, dict) and "error" in dns_result:
            steps["dns"] = {"success": False, "error": dns_result["error"]}
            return jsonify({"success": False, "error": f"DNS failed: {dns_result['error']}", "steps": steps}), 500
        steps["dns"] = {"success": True, "record": f"{subdomain} A {public_ip}"}
    except Exception as e:
        steps["dns"] = {"success": False, "error": str(e)}
        return jsonify({"success": False, "error": f"DNS failed: {e}", "steps": steps}), 500

    # Step 3: Create NPM proxy host (with SSL)
    try:
        proxy_result = npm_service.create_proxy_host(
            domain=full_domain,
            forward_host=forward_host,
            forward_port=int(forward_port),
            ssl=True,
        )
        if isinstance(proxy_result, dict) and "error" in proxy_result:
            steps["proxy"] = {"success": False, "error": proxy_result["error"]}
            return jsonify({"success": False, "error": f"Proxy failed: {proxy_result['error']}", "steps": steps}), 500
        steps["proxy"] = {"success": True, "proxy_host_id": proxy_result.get("id")}
        steps["ssl"] = {"success": True}
    except Exception as e:
        steps["proxy"] = {"success": False, "error": str(e)}
        return jsonify({"success": False, "error": f"Proxy failed: {e}", "steps": steps}), 500

    return jsonify(
        {
            "success": True,
            "message": f"Subdomain {full_domain} created successfully",
            "domain": full_domain,
            "steps": steps,
        }
    )


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
        return jsonify({"success": False, "error": str(e)}), 500


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
        conn = get_db()
        cur = conn.cursor()
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
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "config": config})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
