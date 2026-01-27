"""
System Operations Routes
API endpoints for system monitoring and management
"""

from flask import render_template, jsonify, request, redirect, url_for, flash
from flask_login import login_required, current_user
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor, Json
import os
from datetime import datetime

from . import system_operations_bp
from .system_service import get_system_service
import json as json_lib
import time as time_mod

BASE_DIR = os.environ.get("ARCHIE_BASE_DIR", "/mnt/archie_brain")
HOST_DATA_FILE = os.path.join(BASE_DIR, "host_monitor_data.json")


def load_host_monitor_data():
    """Load host monitor data from JSON file. Returns (data, age_seconds) or (None, None)."""
    try:
        if not os.path.exists(HOST_DATA_FILE):
            return None, None
        age = time_mod.time() - os.path.getmtime(HOST_DATA_FILE)
        with open(HOST_DATA_FILE, "r") as f:
            data = json_lib.load(f)
        return data, age
    except Exception:
        return None, None


# ============================================================================
# DECORATORS
# ============================================================================


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


# ============================================================================
# HELPERS
# ============================================================================


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def audit_log(action_type: str, target: str, details: dict = None, success: bool = True, error_message: str = None):
    """Log system operation to audit table"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO system_operations_audit
            (user_id, action_type, target, details, success, error_message, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                current_user.id if current_user.is_authenticated else None,
                action_type,
                target,
                Json(details) if details else None,
                success,
                error_message,
                request.remote_addr,
            ),
        )
        audit_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return audit_id
    except Exception as e:
        print(f"Audit log error: {e}")
        return None


def record_metric(metric_type: str, value: float, details: dict = None):
    """Record a system metric for historical tracking"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO system_metrics_history (metric_type, value, details)
            VALUES (%s, %s, %s)
        """,
            (metric_type, value, Json(details) if details else None),
        )
        conn.commit()

        # Run cleanup (delete records older than 7 days) - every 100th insert
        import random

        if random.randint(1, 100) == 1:
            cur.execute("SELECT cleanup_old_system_metrics()")
            conn.commit()

        cur.close()
        conn.close()
    except Exception as e:
        print(f"Metric recording error: {e}")


def require_reauth():
    """Check if user has recently re-authenticated (within 5 minutes).
    Returns None if OK, or a JSON error response if re-auth needed."""
    from flask import session

    reauth_time = session.get("reauth_timestamp")
    if reauth_time and (time_mod.time() - reauth_time) < 300:
        return None
    return (
        jsonify({"success": False, "error": "Re-authentication required for this operation", "requires_reauth": True}),
        401,
    )


# ============================================================================
# PAGE ROUTES
# ============================================================================


@system_operations_bp.route("/")
@login_required
@admin_required
def index():
    """Main System Operations dashboard"""
    return render_template("tools/system_operations.html")


# ============================================================================
# READ-ONLY API ENDPOINTS
# ============================================================================


@system_operations_bp.route("/api/overview")
@login_required
@admin_required
def api_overview():
    """Get complete system overview - merges container metrics with host monitor data"""
    try:
        service = get_system_service()
        data = service.get_overview()

        # Record metrics for history
        record_metric("cpu", data["cpu"]["usage_percent"])
        record_metric("memory", data["memory"]["usage_percent"])
        if data["gpu"]["available"]:
            record_metric("gpu", data["gpu"]["usage_percent"])

        # Merge host monitor data for accurate host-level info
        host_data, host_age = load_host_monitor_data()
        if host_data:
            data["host_data_age"] = int(host_age) if host_age else None
            data["host_data_stale"] = host_age > 300 if host_age else True

            # System info: prefer host data over container psutil
            host_sys = host_data.get("system")
            if host_sys:
                data["system"] = {
                    "hostname": host_sys.get("hostname", data["system"].get("hostname", "--")),
                    "distribution": host_sys.get("distribution", data["system"].get("distribution", "--")),
                    "release": host_sys.get("kernel", data["system"].get("release", "--")),
                    "architecture": host_sys.get("architecture", data["system"].get("architecture", "--")),
                    "uptime_seconds": host_sys.get("uptime_seconds", data["system"].get("uptime_seconds", 0)),
                    "boot_time": host_sys.get("boot_time", ""),
                    "process_count": host_sys.get("process_count", data["system"].get("process_count", 0)),
                    "users_logged_in": host_sys.get("users_logged_in", 0),
                    "load_average": host_sys.get("load_average"),
                }

            # CPU: keep real-time usage from psutil, overlay host model/cores/temp
            host_cpu = host_data.get("cpu")
            if host_cpu:
                data["cpu"]["model"] = host_cpu.get("model", data["cpu"].get("model"))
                data["cpu"]["physical_cores"] = host_cpu.get("physical_cores")
                data["cpu"]["logical_cores"] = host_cpu.get("logical_cores")
                if host_cpu.get("temperature") is not None:
                    data["cpu"]["temperature"] = host_cpu["temperature"]
                if host_cpu.get("temperatures"):
                    data["cpu"]["core_temperatures"] = host_cpu["temperatures"]
                # Use host load average (host has real process count)
                host_load = host_sys.get("load_average") if host_sys else None
                if host_load:
                    data["cpu"]["load_avg"] = host_load

            # GPU: use host data (container can't see GPU)
            host_gpus = host_data.get("gpu")
            if host_gpus and len(host_gpus) > 0:
                gpu = host_gpus[0]
                data["gpu"] = {
                    "available": True,
                    "model": gpu.get("model", "Unknown"),
                    "vendor": gpu.get("vendor"),
                    "temperature": gpu.get("temperature"),
                    "vram_total_mb": gpu.get("vram_total_mb"),
                    "vram_used_mb": gpu.get("vram_used_mb"),
                    "usage_percent": gpu.get("utilization_percent"),
                    "driver": gpu.get("driver"),
                    "has_detailed_stats": gpu.get("vram_total_mb") is not None,
                }

            # Network: use host primary IP
            host_net = host_data.get("network")
            if host_net and host_net.get("primary_ip"):
                data["network"]["primary_ip"] = host_net["primary_ip"]
                data["network"]["host_hostname"] = host_net.get("hostname")

            # Disks: add host disk summary for dashboard
            host_disks = host_data.get("disks")
            if host_disks:
                data["host_disks"] = host_disks

        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/cpu")
@login_required
@admin_required
def api_cpu():
    """Get CPU details"""
    try:
        service = get_system_service()
        data = service.get_cpu_info()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/memory")
@login_required
@admin_required
def api_memory():
    """Get memory details"""
    try:
        service = get_system_service()
        data = service.get_memory_info()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/disks")
@login_required
@admin_required
def api_disks():
    """Get disk information"""
    try:
        service = get_system_service()
        data = service.get_disk_info()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/processes")
@login_required
@admin_required
def api_processes():
    """Get running processes - prefers host data over container psutil"""
    try:
        sort_by = request.args.get("sort", "cpu")
        limit = int(request.args.get("limit", 50))

        # Try host monitor data first (shows real host processes)
        host_data, host_age = load_host_monitor_data()
        if host_data and host_data.get("processes"):
            processes = host_data["processes"]
            # Mark as host processes
            for p in processes:
                p["from_host"] = True

            # Sort
            if sort_by == "cpu":
                processes.sort(key=lambda x: x.get("cpu_percent", 0), reverse=True)
            elif sort_by == "memory":
                processes.sort(key=lambda x: x.get("memory_percent", 0), reverse=True)
            elif sort_by == "name":
                processes.sort(key=lambda x: (x.get("name") or "").lower())

            return jsonify(
                {
                    "success": True,
                    "data": processes[:limit],
                    "count": len(processes),
                    "source": "host",
                    "data_age": int(host_age) if host_age else None,
                }
            )

        # Fall back to container psutil
        service = get_system_service()
        data = service.get_process_list(sort_by=sort_by, limit=limit)
        return jsonify({"success": True, "data": data, "count": len(data), "source": "container"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/services")
@login_required
@admin_required
def api_services():
    """Get systemd services"""
    try:
        filter_type = request.args.get("filter", "all")

        service = get_system_service()
        data = service.get_services_list(filter_type=filter_type)
        return jsonify({"success": True, "data": data, "count": len(data)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/docker")
@login_required
@admin_required
def api_docker():
    """Get Docker containers"""
    try:
        service = get_system_service()
        data = service.get_docker_containers()
        return jsonify({"success": True, "data": data, "count": len(data)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/network")
@login_required
@admin_required
def api_network():
    """Get network information - merges host monitor data with container network"""
    try:
        service = get_system_service()
        data = service.get_network_info()

        # Merge host monitor network data
        host_data, host_age = load_host_monitor_data()
        if host_data:
            host_net = host_data.get("network") or {}
            data["host_data_age"] = int(host_age) if host_age else None

            # Override hostname with real host hostname
            if host_net.get("hostname"):
                data["host_hostname"] = host_net["hostname"]

            # Host IP and gateway from host monitor
            if host_net.get("primary_ip"):
                data["host_ip"] = host_net["primary_ip"]
            if host_net.get("gateway"):
                data["gateway"] = host_net["gateway"]
            if host_net.get("dns_servers"):
                data["host_dns_servers"] = host_net["dns_servers"]

            # Real host interfaces replace the guessed ones
            if host_net.get("interfaces"):
                data["host_interfaces"] = [
                    {**iface, "type": "host", "note": "Host interface"} for iface in host_net["interfaces"]
                ]

            # Host listening ports and connections
            if host_net.get("listening_ports"):
                data["host_listening_ports"] = host_net["listening_ports"]
            if host_net.get("connections"):
                data["host_connections"] = host_net["connections"]

        # Add port-to-stack context (inline, lightweight)
        try:
            import yaml

            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT name, compose_directory, color, web_ui_ports FROM docker_stacks ORDER BY name")
            stack_rows = cur.fetchall()
            cur.close()
            conn.close()

            port_to_stack = {}
            stacks_summary = []
            for sr in stack_rows:
                compose_dir = sr.get("compose_directory") or ""
                stack_ports = []
                compose_file = None
                for fname in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]:
                    candidate = os.path.join(compose_dir, fname)
                    if os.path.exists(candidate):
                        compose_file = candidate
                        break
                if compose_file:
                    try:
                        with open(compose_file, "r") as f:
                            parsed = yaml.safe_load(f) or {}
                        for svc_name, svc_config in (parsed.get("services") or {}).items():
                            for port_entry in svc_config.get("ports") or []:
                                port_str = str(port_entry).split("/")[0]
                                parts = port_str.split(":")
                                try:
                                    host_port = int(parts[0]) if len(parts) <= 2 else int(parts[1])
                                except (ValueError, IndexError):
                                    continue
                                port_to_stack[str(host_port)] = sr["name"]
                                stack_ports.append(host_port)
                    except (yaml.YAMLError, OSError):
                        pass
                stacks_summary.append(
                    {
                        "name": sr["name"],
                        "color": sr.get("color") or "#888888",
                        "ports": stack_ports,
                        "web_ui_ports": sr.get("web_ui_ports") or [],
                    }
                )
            data["port_to_stack"] = port_to_stack
            data["stacks_summary"] = stacks_summary
        except Exception:
            data["port_to_stack"] = {}
            data["stacks_summary"] = []

        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/network/port-map")
@login_required
@admin_required
def api_network_port_map():
    """Get port-to-stack mapping by cross-referencing compose files with listening ports"""
    try:
        import yaml

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT id, name, compose_directory, color, is_system, web_ui_ports FROM docker_stacks ORDER BY name"
        )
        stacks_rows = cur.fetchall()
        cur.close()
        conn.close()

        # Get host listening ports
        host_data, _ = load_host_monitor_data()
        host_ports_list = []
        if host_data:
            host_ports_list = (host_data.get("network") or {}).get("listening_ports", [])
        listening_port_set = {p["port"] for p in host_ports_list}

        port_to_stack = {}
        stacks = []

        for stack_row in stacks_rows:
            stack_name = stack_row["name"]
            compose_dir = stack_row.get("compose_directory") or ""
            color = stack_row.get("color") or "#888888"
            web_ui_ports = stack_row.get("web_ui_ports") or []
            stack_ports = []

            # Parse compose file for port mappings
            compose_file = None
            for fname in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]:
                candidate = os.path.join(compose_dir, fname)
                if os.path.exists(candidate):
                    compose_file = candidate
                    break

            if compose_file:
                try:
                    with open(compose_file, "r") as f:
                        parsed = yaml.safe_load(f) or {}
                    for svc_name, svc_config in (parsed.get("services") or {}).items():
                        for port_entry in svc_config.get("ports") or []:
                            port_str = str(port_entry)
                            # Parse formats: "3000:3000", "0.0.0.0:3000:3000", "3000:3000/tcp"
                            port_str = port_str.split("/")[0]  # strip protocol
                            parts = port_str.split(":")
                            try:
                                if len(parts) == 1:
                                    host_port = int(parts[0])
                                elif len(parts) == 2:
                                    host_port = int(parts[0])
                                else:
                                    host_port = int(parts[1])
                            except (ValueError, IndexError):
                                continue

                            is_open = host_port in listening_port_set
                            # Find process info from host ports
                            process_info = None
                            for hp in host_ports_list:
                                if hp["port"] == host_port:
                                    process_info = hp.get("process")
                                    break

                            stack_ports.append(
                                {
                                    "port": host_port,
                                    "service": svc_name,
                                    "open": is_open,
                                    "process": process_info,
                                }
                            )
                            port_to_stack[str(host_port)] = stack_name
                except (yaml.YAMLError, OSError):
                    pass

            stacks.append(
                {
                    "name": stack_name,
                    "color": color,
                    "is_system": stack_row.get("is_system", False),
                    "ports": stack_ports,
                    "web_ui_ports": web_ui_ports,
                }
            )

        # Build unassigned ports list
        assigned_ports = {p["port"] for s in stacks for p in s["ports"]}
        unassigned = [
            {"port": p["port"], "process": p.get("process"), "ip": p.get("ip", "0.0.0.0")}
            for p in host_ports_list
            if p["port"] not in assigned_ports
        ]

        return jsonify(
            {
                "success": True,
                "stacks": stacks,
                "unassigned_ports": unassigned,
                "port_to_stack": port_to_stack,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/network/bandwidth")
@login_required
@admin_required
def api_network_bandwidth():
    """Get bandwidth data: historical samples + current interface/container stats"""
    try:
        bandwidth_file = os.path.join(BASE_DIR, "bandwidth_history.json")
        samples = []
        if os.path.exists(bandwidth_file):
            try:
                with open(bandwidth_file, "r") as f:
                    history = json_lib.load(f)
                samples = history.get("samples", [])
            except (json_lib.JSONDecodeError, OSError):
                pass

        host_data, host_age = load_host_monitor_data()
        interfaces = []
        containers = []
        if host_data:
            net = host_data.get("network") or {}
            interfaces = net.get("bandwidth_interfaces", [])
            containers = host_data.get("container_bandwidth", [])

        return jsonify(
            {
                "success": True,
                "samples": samples,
                "current": {
                    "interfaces": interfaces,
                    "containers": containers,
                    "data_age": int(host_age) if host_age else None,
                },
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/stacks/<stack_name>/web-ui-ports", methods=["PUT"])
@login_required
@admin_required
def api_update_web_ui_ports(stack_name):
    """Update web UI port definitions for a stack"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT id, name, is_system FROM docker_stacks WHERE name = %s",
            (stack_name,),
        )
        stack = cur.fetchone()
        if not stack:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Stack not found"}), 404

        # System stack requires re-auth
        if stack["is_system"]:
            reauth = require_reauth()
            if reauth is not None:
                cur.close()
                conn.close()
                return reauth

        data = request.get_json() or {}
        web_ui_ports = data.get("web_ui_ports", [])

        # Validate structure
        if not isinstance(web_ui_ports, list):
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "web_ui_ports must be an array"}), 400

        for entry in web_ui_ports:
            if not isinstance(entry, dict) or "port" not in entry:
                cur.close()
                conn.close()
                return jsonify({"success": False, "error": "Each entry must have a 'port' field"}), 400
            if not isinstance(entry["port"], int):
                cur.close()
                conn.close()
                return jsonify({"success": False, "error": "Port must be an integer"}), 400

        cur.execute(
            "UPDATE docker_stacks SET web_ui_ports = %s WHERE name = %s",
            (Json(web_ui_ports), stack_name),
        )
        conn.commit()
        cur.close()
        conn.close()

        audit_log("update_web_ui_ports", stack_name, {"web_ui_ports": web_ui_ports})

        return jsonify({"success": True, "web_ui_ports": web_ui_ports})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/history")
@login_required
@admin_required
def api_history():
    """Get historical metrics for graphs"""
    try:
        metric_type = request.args.get("type", "cpu")
        hours = int(request.args.get("hours", 1))

        # Validate hours (max 168 = 7 days)
        hours = min(max(hours, 1), 168)

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Use interval multiplication instead of string interpolation
        cur.execute(
            """
            SELECT value, recorded_at
            FROM system_metrics_history
            WHERE metric_type = %s
              AND recorded_at > NOW() - (%s * INTERVAL '1 hour')
            ORDER BY recorded_at ASC
            LIMIT 720
        """,
            (metric_type, hours),
        )

        data = cur.fetchall()
        cur.close()
        conn.close()

        # Convert to chart format
        labels = [row["recorded_at"].strftime("%H:%M") for row in data]
        values = [float(row["value"]) for row in data]

        return jsonify(
            {
                "success": True,
                "data": {"labels": labels, "values": values, "metric_type": metric_type, "count": len(values)},
            }
        )
    except Exception as e:
        import traceback

        print(f"History API error: {e}")
        print(traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# ACTION API ENDPOINTS (Require confirmation)
# ============================================================================


@system_operations_bp.route("/api/process/<int:pid>/kill", methods=["POST"])
@login_required
@admin_required
def api_kill_process(pid):
    """Kill a process"""
    try:
        data = request.get_json() or {}

        # Require confirmation
        if not data.get("confirm"):
            return jsonify({"success": False, "error": "Confirmation required", "requires_confirm": True}), 400

        signal = data.get("signal", "SIGTERM")
        service = get_system_service()
        result = service.kill_process(pid, signal)

        # Audit log
        audit_id = audit_log(
            action_type="process_kill",
            target=str(pid),
            details={"signal": signal},
            success=result["success"],
            error_message=result.get("error"),
        )

        result["audit_id"] = audit_id
        return jsonify(result)
    except Exception as e:
        audit_log("process_kill", str(pid), success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/service/<service_name>/action", methods=["POST"])
@login_required
@admin_required
def api_service_action(service_name):
    """Perform action on a systemd service"""
    try:
        data = request.get_json() or {}

        # Require confirmation
        if not data.get("confirm"):
            return jsonify({"success": False, "error": "Confirmation required", "requires_confirm": True}), 400

        action = data.get("action", "restart")
        service = get_system_service()
        result = service.service_action(service_name, action)

        # Audit log
        audit_id = audit_log(
            action_type="service_action",
            target=service_name,
            details={"action": action},
            success=result["success"],
            error_message=result.get("error"),
        )

        result["audit_id"] = audit_id
        return jsonify(result)
    except Exception as e:
        audit_log("service_action", service_name, success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/docker/<container_id>/action", methods=["POST"])
@login_required
@admin_required
def api_docker_action(container_id):
    """Perform action on a Docker container"""
    try:
        data = request.get_json() or {}

        # Require confirmation
        if not data.get("confirm"):
            return jsonify({"success": False, "error": "Confirmation required", "requires_confirm": True}), 400

        action = data.get("action", "restart")
        service = get_system_service()
        result = service.docker_action(container_id, action)

        # Audit log
        audit_id = audit_log(
            action_type="docker_action",
            target=container_id,
            details={"action": action},
            success=result["success"],
            error_message=result.get("error"),
        )

        result["audit_id"] = audit_id
        return jsonify(result)
    except Exception as e:
        audit_log("docker_action", container_id, success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/docker/compose", methods=["POST"])
@login_required
@admin_required
def api_docker_compose():
    """Execute docker-compose commands"""
    try:
        data = request.get_json() or {}

        if not data.get("confirm"):
            return jsonify({"success": False, "error": "Confirmation required", "requires_confirm": True}), 400

        action = data.get("action", "up")
        allowed_actions = ["up", "down", "restart", "pull"]
        if action not in allowed_actions:
            return jsonify({"success": False, "error": f"Invalid action. Allowed: {allowed_actions}"}), 400

        import subprocess

        compose_file = os.path.join(BASE_DIR, "docker-compose.yml")

        cmd_map = {
            "up": ["docker-compose", "-f", compose_file, "up", "-d"],
            "down": ["docker-compose", "-f", compose_file, "down"],
            "restart": ["docker-compose", "-f", compose_file, "restart"],
            "pull": ["docker-compose", "-f", compose_file, "pull"],
        }

        result = subprocess.run(cmd_map[action], capture_output=True, text=True, timeout=120)

        success = result.returncode == 0
        audit_log(
            action_type="docker_compose",
            target=action,
            details={"stdout": result.stdout[:500], "stderr": result.stderr[:500]},
            success=success,
            error_message=result.stderr if not success else None,
        )

        return jsonify({"success": success, "output": result.stdout, "error": result.stderr if not success else None})
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Command timed out"}), 500
    except Exception as e:
        audit_log("docker_compose", "error", success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/docker/<container_id>/logs", methods=["GET"])
@login_required
@admin_required
def api_docker_logs(container_id):
    """Get container logs"""
    try:
        import subprocess

        tail = request.args.get("tail", "100")

        result = subprocess.run(
            ["docker", "logs", "--tail", tail, container_id], capture_output=True, text=True, timeout=30
        )

        # Return as plain text
        from flask import Response

        logs = result.stdout + result.stderr
        return Response(logs, mimetype="text/plain")
    except Exception as e:
        return f"Error fetching logs: {str(e)}", 500


# ============================================================================
# STACK MANAGEMENT ENDPOINTS
# ============================================================================


@system_operations_bp.route("/api/stack/compose", methods=["GET"])
@login_required
@admin_required
def api_get_compose():
    """Get docker-compose.yml content and parse services"""
    try:
        import yaml

        compose_file = os.path.join(BASE_DIR, "docker-compose.yml")

        if not os.path.exists(compose_file):
            return jsonify({"success": False, "error": "Compose file not found"}), 404

        # Read file content
        with open(compose_file, "r") as f:
            content = f.read()

        # Get file modification time
        stat = os.stat(compose_file)
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

        # Parse services
        services = []
        try:
            parsed = yaml.safe_load(content)
            if parsed and "services" in parsed:
                # Get running containers to check status
                import subprocess

                result = subprocess.run(
                    ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=10
                )
                running_containers = set(result.stdout.strip().split("\n")) if result.stdout.strip() else set()

                for name, config in parsed["services"].items():
                    services.append(
                        {
                            "name": name,
                            "image": config.get("image", ""),
                            "running": name in running_containers
                            or f"archie_brain-{name}-1" in running_containers
                            or f"archie_brain_{name}_1" in running_containers,
                        }
                    )
        except yaml.YAMLError:
            # YAML parse error - still return content but note the error
            pass

        return jsonify(
            {"success": True, "content": content, "modified": modified, "services": services, "file": compose_file}
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/stack/compose", methods=["PUT"])
@login_required
@admin_required
def api_save_compose():
    """Save docker-compose.yml content"""
    try:
        import yaml

        data = request.get_json() or {}
        content = data.get("content", "")

        if not content:
            return jsonify({"success": False, "error": "No content provided"}), 400

        compose_file = data.get("file", os.path.join(BASE_DIR, "docker-compose.yml"))

        # Security: Only allow specific files to be edited
        allowed_files = [
            os.path.join(BASE_DIR, "docker-compose.yml"),
            os.path.join(BASE_DIR, ".env"),
            os.path.join(BASE_DIR, "platform_v2", ".env"),
        ]

        if compose_file not in allowed_files:
            return jsonify({"success": False, "error": "File not allowed to be edited"}), 403

        # Validate YAML syntax
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as ye:
            return jsonify({"success": False, "error": f"Invalid YAML syntax: {str(ye)}"}), 400

        # Create backup
        backup_file = f"{compose_file}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if os.path.exists(compose_file):
            import shutil

            shutil.copy2(compose_file, backup_file)

        # Write new content
        with open(compose_file, "w") as f:
            f.write(content)

        # Audit log
        audit_log(
            action_type="compose_file_edit",
            target=compose_file,
            details={"backup_file": backup_file, "content_length": len(content)},
            success=True,
        )

        return jsonify({"success": True, "message": "Compose file saved", "backup": backup_file})
    except Exception as e:
        audit_log("compose_file_edit", compose_file, success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/stack/env", methods=["GET"])
@login_required
@admin_required
def api_get_env():
    """Get environment file content"""
    try:
        filename = request.args.get("file", ".env")

        # Security: Only allow specific env files
        allowed_files = {
            ".env": os.path.join(BASE_DIR, ".env"),
            "platform_v2/.env": os.path.join(BASE_DIR, "platform_v2", ".env"),
        }

        if filename not in allowed_files:
            return jsonify({"success": False, "error": "File not allowed"}), 403

        env_file = allowed_files[filename]

        if not os.path.exists(env_file):
            return jsonify({"success": False, "error": "File not found"}), 404

        with open(env_file, "r") as f:
            content = f.read()

        stat = os.stat(env_file)
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

        return jsonify({"success": True, "content": content, "modified": modified, "file": env_file})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/stack/env", methods=["PUT"])
@login_required
@admin_required
def api_save_env():
    """Save environment file content"""
    try:
        data = request.get_json() or {}
        content = data.get("content", "")
        filename = data.get("file", "")

        # Security: Only allow specific env files
        allowed_files = [
            os.path.join(BASE_DIR, ".env"),
            os.path.join(BASE_DIR, "platform_v2", ".env"),
        ]

        if filename not in allowed_files:
            return jsonify({"success": False, "error": "File not allowed to be edited"}), 403

        # Create backup
        backup_file = f"{filename}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if os.path.exists(filename):
            import shutil

            shutil.copy2(filename, backup_file)

        # Write new content
        with open(filename, "w") as f:
            f.write(content)

        # Audit log
        audit_log(action_type="env_file_edit", target=filename, details={"backup_file": backup_file}, success=True)

        return jsonify({"success": True, "message": "Environment file saved", "backup": backup_file})
    except Exception as e:
        audit_log("env_file_edit", filename, success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# MULTI-STACK MANAGEMENT ENDPOINTS
# ============================================================================


@system_operations_bp.route("/api/stacks")
@login_required
@admin_required
def api_list_stacks():
    """List all Docker stacks with live container status"""
    try:
        import subprocess

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, name, display_name, description, color, compose_directory,
                   is_system, created_at, updated_at
            FROM docker_stacks
            ORDER BY is_system DESC, display_name ASC
        """
        )
        stacks = cur.fetchall()
        cur.close()
        conn.close()

        results = []
        for stack in stacks:
            stack_data = dict(stack)
            compose_dir = stack_data.get("compose_directory", "")
            compose_file = os.path.join(compose_dir, "docker-compose.yml") if compose_dir else ""

            # Convert datetime fields
            if stack_data.get("created_at"):
                stack_data["created_at"] = stack_data["created_at"].isoformat()
            if stack_data.get("updated_at"):
                stack_data["updated_at"] = stack_data["updated_at"].isoformat()

            # Get live container status
            containers_running = 0
            containers_total = 0
            status = "unknown"

            if compose_dir and compose_file and os.path.exists(compose_file):
                try:
                    result = subprocess.run(
                        [
                            "docker",
                            "compose",
                            "-f",
                            compose_file,
                            "--project-directory",
                            compose_dir,
                            "ps",
                            "--format",
                            "json",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        containers = []
                        for line in result.stdout.strip().splitlines():
                            line = line.strip()
                            if line:
                                try:
                                    containers.append(json_lib.loads(line))
                                except json_lib.JSONDecodeError:
                                    pass
                        containers_total = len(containers)
                        containers_running = sum(1 for c in containers if c.get("State", "").lower() == "running")
                        if containers_total > 0 and containers_running == containers_total:
                            status = "running"
                        elif containers_running > 0:
                            status = "partial"
                        else:
                            status = "stopped"
                    else:
                        status = "stopped"
                except (subprocess.TimeoutExpired, Exception):
                    status = "unknown"

            stack_data["status"] = status
            stack_data["containers_running"] = containers_running
            stack_data["containers_total"] = containers_total
            results.append(stack_data)

        return jsonify({"success": True, "data": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/stacks", methods=["POST"])
@login_required
@admin_required
def api_create_stack():
    """Create a new Docker stack"""
    conn = None
    cur = None
    stack_dir = None
    try:
        import re
        import yaml

        data = request.get_json() or {}
        name = data.get("name", "").strip()
        display_name = data.get("display_name", "").strip()
        description = data.get("description", "").strip()
        color = data.get("color", "#6366f1").strip()
        compose_content = data.get("compose_content", "").strip()
        env_content = data.get("env_content", "").strip()

        # Validate name
        if not name:
            return jsonify({"success": False, "error": "Stack name is required"}), 400

        if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", name):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Invalid name. Use lowercase letters, numbers, "
                        "and hyphens. Must start/end with alphanumeric.",
                    }
                ),
                400,
            )

        if not display_name:
            display_name = name.replace("-", " ").title()

        # Stack directory
        stack_dir = f"/mnt/stacks/{name}"
        if os.path.exists(stack_dir):
            return (
                jsonify({"success": False, "error": f"Stack directory already exists: {stack_dir}"}),
                409,
            )

        os.makedirs(stack_dir, exist_ok=False)

        # Write compose file if provided
        if compose_content:
            try:
                yaml.safe_load(compose_content)
            except yaml.YAMLError as ye:
                # Clean up directory on validation failure
                import shutil

                shutil.rmtree(stack_dir, ignore_errors=True)
                stack_dir = None
                return (
                    jsonify({"success": False, "error": f"Invalid YAML: {str(ye)}"}),
                    400,
                )
            with open(os.path.join(stack_dir, "docker-compose.yml"), "w") as f:
                f.write(compose_content)

        # Write env file if provided
        if env_content:
            with open(os.path.join(stack_dir, ".env"), "w") as f:
                f.write(env_content)

        # Insert into database
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            INSERT INTO docker_stacks (name, display_name, description, color, compose_directory, is_system)
            VALUES (%s, %s, %s, %s, %s, FALSE)
            RETURNING id, name, display_name, description, color, compose_directory, is_system, created_at, updated_at
        """,
            (name, display_name, description, color, stack_dir),
        )
        stack = dict(cur.fetchone())
        conn.commit()
        cur.close()
        conn.close()
        conn = None
        cur = None

        # Convert datetime fields
        if stack.get("created_at"):
            stack["created_at"] = stack["created_at"].isoformat()
        if stack.get("updated_at"):
            stack["updated_at"] = stack["updated_at"].isoformat()

        audit_log(
            "stack_create",
            name,
            details={"display_name": display_name, "directory": stack_dir},
        )

        return jsonify({"success": True, "data": stack}), 201

    except psycopg2.IntegrityError:
        if conn:
            conn.rollback()
        if cur:
            cur.close()
        if conn:
            conn.close()
        return (
            jsonify({"success": False, "error": f"A stack with name '{name}' already exists"}),
            409,
        )
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        # Clean up directory on error if we created it
        if stack_dir and os.path.exists(stack_dir):
            import shutil

            shutil.rmtree(stack_dir, ignore_errors=True)
        audit_log("stack_create", data.get("name", "unknown"), success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/stacks/<stack_name>")
@login_required
@admin_required
def api_get_stack(stack_name):
    """Get detailed information for a single Docker stack"""
    try:
        import subprocess

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, name, display_name, description, color, compose_directory,
                   is_system, created_at, updated_at
            FROM docker_stacks
            WHERE name = %s
        """,
            (stack_name,),
        )
        stack = cur.fetchone()
        cur.close()
        conn.close()

        if not stack:
            return jsonify({"success": False, "error": "Stack not found"}), 404

        stack_data = dict(stack)
        compose_dir = stack_data.get("compose_directory", "")
        compose_file = os.path.join(compose_dir, "docker-compose.yml") if compose_dir else ""

        # Convert datetime fields
        if stack_data.get("created_at"):
            stack_data["created_at"] = stack_data["created_at"].isoformat()
        if stack_data.get("updated_at"):
            stack_data["updated_at"] = stack_data["updated_at"].isoformat()

        # Get container details
        containers = []
        containers_running = 0
        containers_total = 0

        if compose_dir and compose_file and os.path.exists(compose_file):
            try:
                result = subprocess.run(
                    [
                        "docker",
                        "compose",
                        "-f",
                        compose_file,
                        "--project-directory",
                        compose_dir,
                        "ps",
                        "--format",
                        "json",
                        "-a",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    for line in result.stdout.strip().splitlines():
                        line = line.strip()
                        if line:
                            try:
                                containers.append(json_lib.loads(line))
                            except json_lib.JSONDecodeError:
                                pass
                    containers_total = len(containers)
                    containers_running = sum(1 for c in containers if c.get("State", "").lower() == "running")
            except (subprocess.TimeoutExpired, Exception):
                pass

        stack_data["containers"] = containers
        stack_data["containers_running"] = containers_running
        stack_data["containers_total"] = containers_total

        return jsonify({"success": True, "data": stack_data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/stacks/<stack_name>", methods=["DELETE"])
@login_required
@admin_required
def api_delete_stack(stack_name):
    """Delete a Docker stack"""
    try:
        import subprocess

        data = request.get_json() or {}

        if not data.get("confirm"):
            return (
                jsonify({"success": False, "error": "Confirmation required", "requires_confirm": True}),
                400,
            )

        remove_files = data.get("remove_files", False)

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, name, display_name, compose_directory, is_system
            FROM docker_stacks
            WHERE name = %s
        """,
            (stack_name,),
        )
        stack = cur.fetchone()

        if not stack:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Stack not found"}), 404

        if stack["is_system"]:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Cannot delete system stack"}), 403

        compose_dir = stack.get("compose_directory", "")
        compose_file = os.path.join(compose_dir, "docker-compose.yml") if compose_dir else ""

        # Stop containers first
        if compose_dir and compose_file and os.path.exists(compose_file):
            try:
                subprocess.run(
                    [
                        "docker",
                        "compose",
                        "-f",
                        compose_file,
                        "--project-directory",
                        compose_dir,
                        "down",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except (subprocess.TimeoutExpired, Exception):
                pass  # Best effort stop

        # Delete from database
        cur.execute("DELETE FROM docker_stacks WHERE name = %s", (stack_name,))
        conn.commit()
        cur.close()
        conn.close()

        # Optionally remove files
        files_removed = False
        if remove_files and compose_dir and compose_dir.startswith("/mnt/stacks/"):
            import shutil

            if os.path.exists(compose_dir):
                shutil.rmtree(compose_dir)
                files_removed = True

        audit_log(
            "stack_delete",
            stack_name,
            details={
                "display_name": stack["display_name"],
                "directory": compose_dir,
                "files_removed": files_removed,
            },
        )

        return jsonify(
            {
                "success": True,
                "message": f"Stack '{stack_name}' deleted",
                "files_removed": files_removed,
            }
        )
    except Exception as e:
        audit_log("stack_delete", stack_name, success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# PER-STACK ACTION, COMPOSE, ENV, AND LOGS ENDPOINTS
# ============================================================================


@system_operations_bp.route("/api/stacks/<stack_name>/action", methods=["POST"])
@login_required
@admin_required
def api_stack_action(stack_name):
    """Execute a docker compose action on a stack (up/down/restart/pull)"""
    try:
        import subprocess

        data = request.get_json() or {}
        action = data.get("action", "")
        confirm = data.get("confirm", False)

        allowed_actions = ["up", "down", "restart", "pull"]
        if action not in allowed_actions:
            return jsonify({"success": False, "error": f"Invalid action. Allowed: {allowed_actions}"}), 400

        if not confirm:
            return jsonify({"success": False, "error": "Confirmation required", "requires_confirm": True}), 400

        # Look up stack from DB
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, name, display_name, compose_directory, is_system
            FROM docker_stacks
            WHERE name = %s
        """,
            (stack_name,),
        )
        stack = cur.fetchone()
        cur.close()
        conn.close()

        if not stack:
            return jsonify({"success": False, "error": "Stack not found"}), 404

        # System stack + destructive action requires re-auth
        destructive_actions = ["down", "restart", "pull"]
        if stack["is_system"] and action in destructive_actions:
            reauth = require_reauth()
            if reauth is not None:
                return reauth

        compose_dir = stack["compose_directory"]
        compose_file = os.path.join(compose_dir, "docker-compose.yml")

        if not os.path.exists(compose_file):
            return jsonify({"success": False, "error": "Compose file not found for this stack"}), 404

        # Build command
        cmd = [
            "docker",
            "compose",
            "-f",
            compose_file,
            "--project-directory",
            compose_dir,
            action,
        ]
        if action == "up":
            cmd.append("-d")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            audit_log(
                "stack_action",
                stack_name,
                details={"action": action},
                success=False,
                error_message="Command timed out after 120 seconds",
            )
            return jsonify({"success": False, "error": "Command timed out after 120 seconds"}), 500

        success = result.returncode == 0
        audit_log(
            action_type="stack_action",
            target=stack_name,
            details={
                "action": action,
                "stdout": result.stdout[:500] if result.stdout else "",
                "stderr": result.stderr[:500] if result.stderr else "",
            },
            success=success,
            error_message=result.stderr if not success else None,
        )

        return jsonify(
            {
                "success": success,
                "output": result.stdout,
                "error": result.stderr if not success else None,
            }
        )
    except Exception as e:
        audit_log(
            "stack_action", stack_name, details={"action": data.get("action")}, success=False, error_message=str(e)
        )
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/stacks/<stack_name>/compose")
@login_required
@admin_required
def api_get_stack_compose(stack_name):
    """Get docker-compose.yml content and service status for a stack"""
    try:
        import yaml
        import subprocess

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, name, compose_directory, is_system
            FROM docker_stacks
            WHERE name = %s
        """,
            (stack_name,),
        )
        stack = cur.fetchone()
        cur.close()
        conn.close()

        if not stack:
            return jsonify({"success": False, "error": "Stack not found"}), 404

        compose_dir = stack["compose_directory"]
        compose_file = os.path.join(compose_dir, "docker-compose.yml")

        if not os.path.exists(compose_file):
            return jsonify({"success": False, "error": "Compose file not found"}), 404

        # Read file content
        with open(compose_file, "r") as f:
            content = f.read()

        # Get modification time
        stat = os.stat(compose_file)
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

        # Parse YAML and extract services
        services = []
        try:
            parsed = yaml.safe_load(content)
            if parsed and "services" in parsed:
                # Get running containers to check status
                result = subprocess.run(
                    ["docker", "ps", "--format", "{{.Names}}"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                running_containers = set(result.stdout.strip().split("\n")) if result.stdout.strip() else set()

                for svc_name, svc_config in parsed["services"].items():
                    # Check multiple name patterns
                    name_patterns = [
                        svc_name,
                        f"{stack_name}-{svc_name}-1",
                        f"{stack_name}_{svc_name}_1",
                    ]
                    # For system stack, also check archie_brain patterns
                    if stack["is_system"]:
                        name_patterns.append(f"archie_brain-{svc_name}-1")
                        name_patterns.append(f"archie_brain_{svc_name}_1")

                    is_running = any(p in running_containers for p in name_patterns)

                    # Extract ports
                    ports = svc_config.get("ports", [])
                    port_strings = [str(p) for p in ports] if ports else []

                    services.append(
                        {
                            "name": svc_name,
                            "image": svc_config.get("image", ""),
                            "ports": port_strings,
                            "running": is_running,
                        }
                    )
        except yaml.YAMLError:
            pass  # Still return content even if YAML is invalid

        return jsonify(
            {
                "success": True,
                "content": content,
                "modified": modified,
                "services": services,
                "file": compose_file,
                "is_system": stack["is_system"],
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/stacks/<stack_name>/compose", methods=["PUT"])
@login_required
@admin_required
def api_save_stack_compose(stack_name):
    """Save docker-compose.yml content for a stack"""
    try:
        import yaml

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, name, compose_directory, is_system
            FROM docker_stacks
            WHERE name = %s
        """,
            (stack_name,),
        )
        stack = cur.fetchone()
        cur.close()
        conn.close()

        if not stack:
            return jsonify({"success": False, "error": "Stack not found"}), 404

        # System stack requires re-auth
        if stack["is_system"]:
            reauth = require_reauth()
            if reauth is not None:
                return reauth

        data = request.get_json() or {}
        content = data.get("content", "")

        if not content:
            return jsonify({"success": False, "error": "No content provided"}), 400

        # Validate YAML syntax
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as ye:
            return jsonify({"success": False, "error": f"Invalid YAML syntax: {str(ye)}"}), 400

        compose_dir = stack["compose_directory"]
        compose_file = os.path.join(compose_dir, "docker-compose.yml")

        # Create backup with timestamp
        backup_file = f"{compose_file}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if os.path.exists(compose_file):
            import shutil

            shutil.copy2(compose_file, backup_file)

        # Write new content
        with open(compose_file, "w") as f:
            f.write(content)

        audit_log(
            action_type="stack_compose_edit",
            target=stack_name,
            details={"backup_file": backup_file, "file": compose_file, "content_length": len(content)},
            success=True,
        )

        return jsonify({"success": True, "message": "Compose file saved", "backup": backup_file})
    except Exception as e:
        audit_log("stack_compose_edit", stack_name, success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/stacks/<stack_name>/env")
@login_required
@admin_required
def api_get_stack_env(stack_name):
    """Get environment files for a stack"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, name, compose_directory, is_system
            FROM docker_stacks
            WHERE name = %s
        """,
            (stack_name,),
        )
        stack = cur.fetchone()
        cur.close()
        conn.close()

        if not stack:
            return jsonify({"success": False, "error": "Stack not found"}), 404

        compose_dir = stack["compose_directory"]
        env_files = []

        # Read .env from stack directory
        env_path = os.path.join(compose_dir, ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                env_content = f.read()
            stat = os.stat(env_path)
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            env_files.append(
                {
                    "filename": ".env",
                    "path": env_path,
                    "content": env_content,
                    "modified": modified,
                }
            )

        # For system stack, also read platform_v2/.env
        if stack["is_system"]:
            platform_env_path = os.path.join(compose_dir, "platform_v2", ".env")
            if os.path.exists(platform_env_path):
                with open(platform_env_path, "r") as f:
                    platform_env_content = f.read()
                stat = os.stat(platform_env_path)
                modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                env_files.append(
                    {
                        "filename": "platform_v2/.env",
                        "path": platform_env_path,
                        "content": platform_env_content,
                        "modified": modified,
                    }
                )

        return jsonify(
            {
                "success": True,
                "data": env_files,
                "is_system": stack["is_system"],
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/stacks/<stack_name>/env", methods=["PUT"])
@login_required
@admin_required
def api_save_stack_env(stack_name):
    """Save an environment file for a stack"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, name, compose_directory, is_system
            FROM docker_stacks
            WHERE name = %s
        """,
            (stack_name,),
        )
        stack = cur.fetchone()
        cur.close()
        conn.close()

        if not stack:
            return jsonify({"success": False, "error": "Stack not found"}), 404

        # System stack requires re-auth
        if stack["is_system"]:
            reauth = require_reauth()
            if reauth is not None:
                return reauth

        data = request.get_json() or {}
        content = data.get("content", "")
        filename = data.get("filename", ".env")

        if not content:
            return jsonify({"success": False, "error": "No content provided"}), 400

        compose_dir = stack["compose_directory"]

        # Security: verify resolved path is within stack directory
        target_path = os.path.join(compose_dir, filename)
        real_target = os.path.realpath(target_path)
        real_compose_dir = os.path.realpath(compose_dir)

        if not real_target.startswith(real_compose_dir + os.sep) and real_target != real_compose_dir:
            return jsonify({"success": False, "error": "Invalid file path - directory traversal not allowed"}), 403

        # Create backup with timestamp
        backup_file = f"{real_target}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if os.path.exists(real_target):
            import shutil

            shutil.copy2(real_target, backup_file)

        # Write new content
        with open(real_target, "w") as f:
            f.write(content)

        audit_log(
            action_type="stack_env_edit",
            target=stack_name,
            details={"filename": filename, "file": real_target, "backup_file": backup_file},
            success=True,
        )

        return jsonify({"success": True, "message": "Environment file saved", "backup": backup_file})
    except Exception as e:
        audit_log("stack_env_edit", stack_name, success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/stacks/<stack_name>/logs")
@login_required
@admin_required
def api_stack_logs(stack_name):
    """Get docker compose logs for a stack"""
    try:
        import subprocess
        from flask import Response

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, name, compose_directory, is_system
            FROM docker_stacks
            WHERE name = %s
        """,
            (stack_name,),
        )
        stack = cur.fetchone()
        cur.close()
        conn.close()

        if not stack:
            return jsonify({"success": False, "error": "Stack not found"}), 404

        compose_dir = stack["compose_directory"]
        compose_file = os.path.join(compose_dir, "docker-compose.yml")

        if not os.path.exists(compose_file):
            return jsonify({"success": False, "error": "Compose file not found"}), 404

        tail = request.args.get("tail", "100")
        service = request.args.get("service", "")

        cmd = [
            "docker",
            "compose",
            "-f",
            compose_file,
            "--project-directory",
            compose_dir,
            "logs",
            "--tail",
            tail,
            "--no-color",
        ]
        if service:
            cmd.append(service)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        logs = result.stdout + result.stderr
        return Response(logs, mimetype="text/plain")
    except Exception as e:
        return Response(f"Error fetching logs: {str(e)}", status=500, mimetype="text/plain")


@system_operations_bp.route("/api/disk/<path:device>/mount", methods=["POST"])
@login_required
@admin_required
def api_mount_disk(device):
    """Mount a disk"""
    try:
        data = request.get_json() or {}

        if not data.get("confirm"):
            return jsonify({"success": False, "error": "Confirmation required", "requires_confirm": True}), 400

        mountpoint = data.get("mountpoint")
        if not mountpoint:
            return jsonify({"success": False, "error": "Mountpoint required"}), 400

        # Execute mount
        import subprocess

        result = subprocess.run(
            ["sudo", "mount", f"/dev/{device}", mountpoint], capture_output=True, text=True, timeout=30
        )

        success = result.returncode == 0
        audit_log(
            action_type="disk_mount",
            target=device,
            details={"mountpoint": mountpoint},
            success=success,
            error_message=result.stderr if not success else None,
        )

        if success:
            return jsonify({"success": True, "message": f"Mounted /dev/{device} at {mountpoint}"})
        else:
            return jsonify({"success": False, "error": result.stderr}), 500

    except Exception as e:
        audit_log("disk_mount", device, success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/disk/<path:device>/unmount", methods=["POST"])
@login_required
@admin_required
def api_unmount_disk(device):
    """Unmount a disk"""
    try:
        data = request.get_json() or {}

        if not data.get("confirm"):
            return jsonify({"success": False, "error": "Confirmation required", "requires_confirm": True}), 400

        # Execute unmount
        import subprocess

        result = subprocess.run(["sudo", "umount", f"/dev/{device}"], capture_output=True, text=True, timeout=30)

        success = result.returncode == 0
        audit_log(
            action_type="disk_unmount",
            target=device,
            success=success,
            error_message=result.stderr if not success else None,
        )

        if success:
            return jsonify({"success": True, "message": f"Unmounted /dev/{device}"})
        else:
            return jsonify({"success": False, "error": result.stderr}), 500

    except Exception as e:
        audit_log("disk_unmount", device, success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# LVM EXTEND ENDPOINT
# ============================================================================


@system_operations_bp.route("/api/lvm/<vg_name>/<lv_name>/extend", methods=["POST"])
@login_required
@admin_required
def api_extend_lvm(vg_name, lv_name):
    """Extend an LVM logical volume"""
    try:
        data = request.get_json() or {}

        # Require confirmation
        if not data.get("confirm"):
            return jsonify({"success": False, "error": "Confirmation required", "requires_confirm": True}), 400

        size_gb = data.get("size_gb")
        extend_all = data.get("extend_all", False)

        if not size_gb and not extend_all:
            return jsonify({"success": False, "error": "Must specify size_gb or extend_all"}), 400

        service = get_system_service()
        result = service.extend_lvm(vg_name, lv_name, size_gb=size_gb, extend_all=extend_all)

        # Audit log
        audit_id = audit_log(
            action_type="lvm_extend",
            target=f"{vg_name}/{lv_name}",
            details={"size_gb": size_gb, "extend_all": extend_all},
            success=result["success"],
            error_message=result.get("error"),
        )

        result["audit_id"] = audit_id
        return jsonify(result)
    except Exception as e:
        audit_log("lvm_extend", f"{vg_name}/{lv_name}", success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/lvm")
@login_required
@admin_required
def api_lvm_info():
    """Get LVM information"""
    try:
        service = get_system_service()
        data = service._get_lvm_info()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# STORAGE API ENDPOINTS
# ============================================================================


@system_operations_bp.route("/api/storage/drives")
@login_required
@admin_required
def api_storage_drives():
    """Get storage drives with partition details for treemap visualization"""
    try:
        host_data, age = load_host_monitor_data()
        if not host_data:
            return jsonify({"success": False, "error": "Host monitor data not available"}), 503

        disks = host_data.get("disks", [])
        lvm = host_data.get("lvm")
        raid = host_data.get("raid")

        # Merge LVM VG free space into disk data
        vg_free = {}
        if lvm and lvm.get("vgs"):
            for vg in lvm["vgs"]:
                vg_free[vg.get("vg_name")] = {
                    "free_gb": vg.get("vg_free_gb", 0),
                    "size_gb": vg.get("vg_size_gb", 0),
                    "name": vg.get("vg_name"),
                }

        # Get managed mounts from DB
        managed = {}
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT device, label, is_managed FROM storage_mounts WHERE is_managed = TRUE")
            for row in cur.fetchall():
                managed[row["device"]] = row
            cur.close()
            conn.close()
        except Exception:
            pass

        return jsonify(
            {
                "success": True,
                "data": {
                    "disks": disks,
                    "lvm": lvm,
                    "raid": raid,
                    "vg_free": vg_free,
                    "managed_mounts": managed,
                    "data_age": int(age) if age else None,
                },
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/storage/mounts")
@login_required
@admin_required
def api_storage_mounts():
    """Get managed storage mounts for Docker bridge"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, device, mount_point, filesystem, label, capacity_gb,
                   drive_model, is_managed, created_at, updated_at
            FROM storage_mounts
            ORDER BY device
        """
        )
        mounts = cur.fetchall()
        cur.close()
        conn.close()

        for m in mounts:
            if m.get("created_at"):
                m["created_at"] = m["created_at"].isoformat()
            if m.get("updated_at"):
                m["updated_at"] = m["updated_at"].isoformat()
            if m.get("capacity_gb"):
                m["capacity_gb"] = float(m["capacity_gb"])

        return jsonify({"success": True, "data": mounts})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/storage/mounts", methods=["POST"])
@login_required
@admin_required
def api_register_storage_mount():
    """Register or update a managed storage mount"""
    try:
        data = request.get_json() or {}
        device = data.get("device")
        if not device:
            return jsonify({"success": False, "error": "Device path required"}), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            INSERT INTO storage_mounts (device, mount_point, filesystem, label, capacity_gb, drive_model, is_managed)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (device) DO UPDATE SET
                mount_point = EXCLUDED.mount_point,
                filesystem = EXCLUDED.filesystem,
                label = EXCLUDED.label,
                capacity_gb = EXCLUDED.capacity_gb,
                drive_model = EXCLUDED.drive_model,
                is_managed = EXCLUDED.is_managed,
                updated_at = NOW()
            RETURNING id, device, mount_point, label
        """,
            (
                device,
                data.get("mount_point"),
                data.get("filesystem"),
                data.get("label"),
                data.get("capacity_gb"),
                data.get("drive_model"),
                data.get("is_managed", True),
            ),
        )
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        audit_log(
            "storage_mount_register",
            device,
            details={"mount_point": data.get("mount_point"), "label": data.get("label")},
        )

        return jsonify({"success": True, "data": dict(result)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/storage/browse")
@login_required
@admin_required
def api_storage_browse():
    """Browse directory listing for a mount point"""
    try:
        path = request.args.get("path", "")
        if not path:
            return jsonify({"success": False, "error": "Path required"}), 400

        # Security: only allow specific path prefixes
        allowed_prefixes = ("/mnt/", "/home/", "/var/", "/opt/", "/srv/", "/tmp/")
        if not any(path.startswith(p) for p in allowed_prefixes):
            return jsonify({"success": False, "error": "Path not allowed"}), 403

        # Resolve to prevent directory traversal
        real_path = os.path.realpath(path)
        if not any(real_path.startswith(p) for p in allowed_prefixes):
            return jsonify({"success": False, "error": "Path not allowed"}), 403

        if not os.path.isdir(real_path):
            return jsonify({"success": False, "error": "Path is not a directory"}), 400

        entries = []
        try:
            for entry in sorted(os.scandir(real_path), key=lambda e: (not e.is_dir(), e.name.lower())):
                try:
                    stat = entry.stat()
                    entries.append(
                        {
                            "name": entry.name,
                            "is_dir": entry.is_dir(),
                            "size": stat.st_size if not entry.is_dir() else None,
                            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        }
                    )
                except (PermissionError, OSError):
                    entries.append(
                        {
                            "name": entry.name,
                            "is_dir": entry.is_dir(),
                            "size": None,
                            "modified": None,
                            "error": "Permission denied",
                        }
                    )
                if len(entries) >= 200:
                    break
        except PermissionError:
            return jsonify({"success": False, "error": "Permission denied"}), 403

        return jsonify(
            {
                "success": True,
                "data": {
                    "path": real_path,
                    "entries": entries,
                    "count": len(entries),
                    "truncated": len(entries) >= 200,
                },
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# RE-AUTHENTICATION ENDPOINT
# ============================================================================


@system_operations_bp.route("/api/auth/verify", methods=["POST"])
@login_required
@admin_required
def api_auth_verify():
    """Verify user password for re-authentication of destructive operations"""
    try:
        from flask import session
        from werkzeug.security import check_password_hash

        data = request.get_json() or {}
        password = data.get("password", "")

        if not password:
            return jsonify({"success": False, "error": "Password required"}), 400

        # Get user's password hash from DB
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT password_hash FROM users WHERE id = %s", (current_user.id,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if not user:
            audit_log("reauth_attempt", "verify", success=False, error_message="User not found")
            return jsonify({"success": False, "error": "User not found"}), 404

        if not check_password_hash(user["password_hash"], password):
            audit_log("reauth_attempt", "verify", success=False, error_message="Invalid password")
            return jsonify({"success": False, "error": "Invalid password"}), 401

        # Store re-auth timestamp in session (valid for 5 minutes)
        session["reauth_timestamp"] = time_mod.time()

        audit_log("reauth_attempt", "verify", success=True)

        return jsonify({"success": True, "message": "Re-authentication successful", "valid_for": 300})
    except Exception as e:
        audit_log("reauth_attempt", "verify", success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# AUDIT LOG ENDPOINT
# ============================================================================


@system_operations_bp.route("/api/audit-log")
@login_required
@admin_required
def api_audit_log():
    """Get system operations audit log"""
    try:
        limit = int(request.args.get("limit", 50))

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                soa.id,
                soa.action_type,
                soa.target,
                soa.details,
                soa.success,
                soa.error_message,
                soa.ip_address,
                soa.created_at,
                u.username
            FROM system_operations_audit soa
            LEFT JOIN users u ON soa.user_id = u.id
            ORDER BY soa.created_at DESC
            LIMIT %s
        """,
            (limit,),
        )

        data = cur.fetchall()
        cur.close()
        conn.close()

        # Convert datetime objects
        for row in data:
            if row["created_at"]:
                row["created_at"] = row["created_at"].isoformat()

        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# HOST DATA ENDPOINT
# ============================================================================


@system_operations_bp.route("/api/host-data")
@login_required
@admin_required
def api_host_data():
    """Get host system data from host monitor"""
    try:
        data, age = load_host_monitor_data()
        if data is None:
            return jsonify(
                {
                    "success": False,
                    "error": "Host monitor data not available",
                    "hint": "Run scripts/host_monitor.py on the host machine",
                }
            )

        data["data_age_seconds"] = int(age) if age else None
        data["is_stale"] = age > 300 if age else True

        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# HEALTH CHECK
# ============================================================================


@system_operations_bp.route("/health")
def health_check():
    """Health check endpoint (no auth required)"""
    return jsonify({"healthy": True, "module": "system_operations"})
