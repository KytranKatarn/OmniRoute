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

# Import network integration if available
try:
    from network_integration import get_network_overview, check_security_threats, auto_block_threats

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
# EXTERNAL TOOLS STATUS API
# ============================================================================


@security_network_bp.route("/api/external-tools/status")
@login_required
@admin_required
def external_tools_status():
    """Check connectivity to external network tools"""
    import socket

    tools = {
        "adguard": {"host": "192.168.1.250", "port": 5354},
        "ntopng": {"host": "192.168.1.250", "port": 3001},
        "nagios": {"host": "192.168.1.250", "port": 8082},
        "nginx": {"host": "192.168.1.250", "port": 81},
    }

    results = {}
    timeout = 2  # 2 second timeout

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
# HEALTH CHECK
# ============================================================================


@security_network_bp.route("/health")
def health_check():
    """Health check endpoint"""
    return jsonify({"healthy": True, "module": "security_network", "network_available": NETWORK_AVAILABLE})
