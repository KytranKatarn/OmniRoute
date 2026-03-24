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
from .host_command_client import (
    submit_host_command,
    submit_and_wait,
    get_queue_status,
    get_result as get_command_result,
    HostCommandTimeout,
    HostCommandQueueUnavailable,
)
from .helpers import (
    BASE_DIR,
    HOST_DATA_FILE,
    load_host_monitor_data,
    get_db,
    audit_log,
    record_metric,
    require_reauth,
    parse_compose_host_port,
    find_compose_file,
)
import json as json_lib
import time as time_mod


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

        # Record metrics for history (per-device for multi-GPU/CPU support)
        record_metric("cpu", data["cpu"]["usage_percent"])
        record_metric("cpu_0", data["cpu"]["usage_percent"])  # Primary CPU aggregate
        record_metric("memory", data["memory"]["usage_percent"])

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

            # GPU: use host data (container can't see GPU) - supports multiple GPUs
            host_gpus = host_data.get("gpu")
            if host_gpus and len(host_gpus) > 0:
                # Build array of all GPUs
                gpus_array = []
                for idx, gpu in enumerate(host_gpus):
                    vram_total = gpu.get("vram_total_mb")
                    vram_used = gpu.get("vram_used_mb")
                    vram_pct = None
                    if vram_total and vram_used is not None and vram_total > 0:
                        vram_pct = round((vram_used / vram_total) * 100, 1)

                    gpu_data = {
                        "index": idx,
                        "available": True,
                        "model": gpu.get("model", "Unknown"),
                        "vendor": gpu.get("vendor"),
                        "temperature": gpu.get("temperature"),
                        "vram_total_mb": vram_total,
                        "vram_used_mb": vram_used,
                        "vram_percent": vram_pct,
                        "usage_percent": gpu.get("utilization_percent"),
                        "driver": gpu.get("driver"),
                        "has_detailed_stats": vram_total is not None,
                    }
                    gpus_array.append(gpu_data)
                    # Record per-GPU compute utilization metric for history
                    if gpu_data["usage_percent"] is not None:
                        record_metric(f"gpu_{idx}", gpu_data["usage_percent"])
                        if idx == 0:
                            record_metric("gpu", gpu_data["usage_percent"])  # Backward compat
                    # Record per-GPU VRAM metric for history
                    if vram_pct is not None:
                        record_metric(f"gpu_vram_{idx}", vram_pct)
                        if idx == 0:
                            record_metric("gpu_vram", vram_pct)  # Backward compat

                # Store array of all GPUs
                data["gpus"] = gpus_array
                # Keep backward compatible single gpu field (first GPU)
                data["gpu"] = gpus_array[0]

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


@system_operations_bp.route("/api/memory-hardware")
@login_required
@admin_required
def api_memory_hardware():
    """Get physical memory hardware (DIMM) info from host monitor"""
    try:
        host_data, host_age = load_host_monitor_data()
        if host_data and host_data.get("memory_hardware"):
            mem_hw = host_data["memory_hardware"]
            return jsonify(
                {
                    "success": True,
                    "data": mem_hw,
                    "source": "host",
                    "data_age": int(host_age) if host_age else None,
                }
            )
        else:
            return jsonify(
                {
                    "success": False,
                    "error": "Memory hardware info not available. Host monitor may need to be restarted.",
                    "data": None,
                }
            )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/hardware")
@login_required
@admin_required
def api_hardware():
    """Get comprehensive hardware info with upgrade potential for Hardware tab"""
    try:
        host_data, host_age = load_host_monitor_data()
        if not host_data:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Host monitor data not available. Ensure host_monitor.py is running.",
                    }
                ),
                503,
            )

        # Gather hardware data from host monitor
        cpu_hardware = host_data.get("cpu_hardware", {})
        cpu_info = host_data.get("cpu", {})
        motherboard = host_data.get("motherboard", {})
        memory_hardware = host_data.get("memory_hardware", {})
        gpu = host_data.get("gpu", [])
        pci_slots = host_data.get("pci_slots", [])
        sata_ports = host_data.get("sata_ports", {})

        # Merge cpu_info model into cpu_hardware if available
        if cpu_info.get("model") and not cpu_hardware.get("processors"):
            cpu_hardware["model"] = cpu_info.get("model")
        if cpu_info.get("physical_cores"):
            cpu_hardware["physical_cores"] = cpu_info.get("physical_cores")
        if cpu_info.get("logical_cores"):
            cpu_hardware["logical_cores"] = cpu_info.get("logical_cores")

        # Compute upgrade summary
        upgrade_summary = _compute_upgrade_summary(cpu_hardware, memory_hardware, pci_slots, sata_ports)

        # Add memory configuration analysis
        memory_config = _analyze_memory_config(memory_hardware)

        result = {
            "cpu": cpu_hardware,
            "motherboard": motherboard,
            "memory": memory_hardware,
            "memory_config": memory_config,
            "gpu": gpu if gpu else [],
            "pci_slots": pci_slots,
            "sata_ports": sata_ports,
            "upgrade_summary": upgrade_summary,
        }

        return jsonify(
            {
                "success": True,
                "data": result,
                "source": "host",
                "data_age": int(host_age) if host_age else None,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _compute_upgrade_summary(cpu, memory, pci_slots, sata_ports=None):
    """Compute upgrade potential based on current hardware"""
    summary = {
        "memory": {
            "current_gb": 0,
            "max_gb": None,
            "expandable_gb": None,
            "empty_slots": 0,
            "total_slots": 0,
        },
        "pci": {
            "available_slots": 0,
            "total_slots": 0,
            "available_by_type": {},
        },
        "cpu": {
            "socket_type": None,
            "populated": 0,
            "max_sockets": 0,
            "can_add_cpu": False,
        },
        "sata": {
            "total_ports": 0,
            "used_ports": 0,
            "available_ports": 0,
        },
    }

    # Memory upgrade potential
    if memory:
        summary["memory"]["current_gb"] = memory.get("total_capacity_gb", 0)
        summary["memory"]["max_gb"] = memory.get("max_capacity_gb")
        summary["memory"]["total_slots"] = memory.get("total_slots", 0)
        summary["memory"]["empty_slots"] = summary["memory"]["total_slots"] - memory.get("populated_slots", 0)
        if summary["memory"]["max_gb"] and summary["memory"]["current_gb"]:
            summary["memory"]["expandable_gb"] = summary["memory"]["max_gb"] - summary["memory"]["current_gb"]

    # PCI slot availability
    if pci_slots:
        summary["pci"]["total_slots"] = len(pci_slots)
        for slot in pci_slots:
            usage = slot.get("current_usage", "").lower()
            if usage == "available" or usage == "empty":
                summary["pci"]["available_slots"] += 1
                slot_type = slot.get("type", "Unknown")
                # Simplify slot type for grouping
                if "x16" in slot_type.lower():
                    key = "PCIe x16"
                elif "x8" in slot_type.lower():
                    key = "PCIe x8"
                elif "x4" in slot_type.lower():
                    key = "PCIe x4"
                elif "x1" in slot_type.lower():
                    key = "PCIe x1"
                elif "pci" in slot_type.lower() and "express" not in slot_type.lower():
                    key = "PCI"
                else:
                    key = slot_type[:20] if slot_type else "Unknown"
                summary["pci"]["available_by_type"][key] = summary["pci"]["available_by_type"].get(key, 0) + 1

    # CPU socket info with upgrade recommendations
    if cpu:
        socket_type = cpu.get("socket_type", "")
        summary["cpu"]["socket_type"] = socket_type
        summary["cpu"]["populated"] = cpu.get("populated_sockets", 0)
        summary["cpu"]["max_sockets"] = cpu.get("max_processors", 0)
        summary["cpu"]["can_add_cpu"] = (
            summary["cpu"]["max_sockets"] > summary["cpu"]["populated"] if summary["cpu"]["max_sockets"] else False
        )

        # Add CPU upgrade recommendations based on socket type
        current_model = ""
        if cpu.get("processors"):
            current_model = cpu["processors"][0].get("model", "") if cpu["processors"] else ""

        cpu_upgrades = _get_cpu_upgrade_info(socket_type, current_model)
        summary["cpu"]["current_model"] = current_model
        summary["cpu"]["max_supported"] = cpu_upgrades.get("max_cpu")
        summary["cpu"]["upgrade_note"] = cpu_upgrades.get("note")
        summary["cpu"]["max_tdp"] = cpu_upgrades.get("max_tdp")

    # SATA port info
    if sata_ports:
        summary["sata"]["total_ports"] = sata_ports.get("total_ports", 0)
        summary["sata"]["used_ports"] = sata_ports.get("used_ports", 0)
        summary["sata"]["available_ports"] = sata_ports.get("available_ports", 0)

    # Add GPU/PCIe slot upgrade info
    summary["pci"]["gpu_slot_info"] = _get_gpu_slot_info(pci_slots)

    return summary


def _get_cpu_upgrade_info(socket_type, current_model):
    """Get CPU upgrade recommendations based on socket type"""
    info = {
        "max_cpu": None,
        "note": None,
        "max_tdp": None,
    }

    socket_lower = (socket_type or "").lower()

    # LGA2011 (Sandy Bridge-EP / Ivy Bridge-EP)
    if "lga2011" in socket_lower and "v3" not in socket_lower:
        info["max_tdp"] = 150
        # Check if current CPU is v1 or v2
        if "v2" in current_model.lower():
            info["max_cpu"] = "Xeon E5-2697 v2 (12C/24T, 2.7GHz)"
            info["note"] = "Ivy Bridge-EP. Top v2 Xeon for single-socket workstations."
        else:
            info["max_cpu"] = "Xeon E5-2690 (8C/16T, 2.9GHz) or upgrade to v2 series"
            info["note"] = "Sandy Bridge-EP. Consider v2 CPUs for more cores."

    # LGA2011-3 (Haswell-EP / Broadwell-EP)
    elif "lga2011-3" in socket_lower or "lga2011 v3" in socket_lower:
        info["max_tdp"] = 145
        if "v4" in current_model.lower():
            info["max_cpu"] = "Xeon E5-2699 v4 (22C/44T, 2.2GHz)"
            info["note"] = "Broadwell-EP. Maximum cores available."
        else:
            info["max_cpu"] = "Xeon E5-2699 v3 (18C/36T, 2.3GHz) or v4 series"
            info["note"] = "Haswell-EP. Consider v4 for more cores."

    # LGA1151 (Coffee Lake / etc)
    elif "lga1151" in socket_lower:
        info["max_tdp"] = 95
        info["max_cpu"] = "Core i9-9900K (8C/16T, 3.6GHz)"
        info["note"] = "Consumer socket. Limited to 8 cores max."

    # LGA1200 (10th/11th gen)
    elif "lga1200" in socket_lower:
        info["max_tdp"] = 125
        info["max_cpu"] = "Core i9-11900K (8C/16T, 3.5GHz)"
        info["note"] = "11th gen max. Consider LGA1700 for newer CPUs."

    # LGA1700 (12th/13th/14th gen)
    elif "lga1700" in socket_lower:
        info["max_tdp"] = 253
        info["max_cpu"] = "Core i9-14900K (24C/32T, 3.2GHz)"
        info["note"] = "Latest Intel consumer socket."

    # AM4 (Ryzen)
    elif "am4" in socket_lower:
        info["max_tdp"] = 142
        info["max_cpu"] = "Ryzen 9 5950X (16C/32T, 3.4GHz)"
        info["note"] = "Check motherboard BIOS for Zen 3 support."

    # AM5 (Ryzen 7000+)
    elif "am5" in socket_lower:
        info["max_tdp"] = 170
        info["max_cpu"] = "Ryzen 9 9950X (16C/32T, 4.3GHz)"
        info["note"] = "Latest AMD consumer socket."

    return info


def _get_gpu_slot_info(pci_slots):
    """Get GPU slot upgrade information"""
    info = {
        "primary_slot": None,
        "max_length": 'Full-length (10.5")',
        "pcie_version": None,
        "lanes": None,
        "power_note": "Check PSU for GPU power connectors",
    }

    if not pci_slots:
        return info

    # Find the primary GPU slot (first x16 PCIe slot, preferably PCIe 3.0+)
    for slot in pci_slots:
        slot_type = slot.get("type", "").lower()
        if "x16" in slot_type and "pci express" in slot_type:
            info["primary_slot"] = slot.get("designation")
            info["lanes"] = 16

            # Extract PCIe version
            if "3" in slot_type:
                info["pcie_version"] = "3.0"
                info["bandwidth"] = "~16 GB/s"
            elif "4" in slot_type:
                info["pcie_version"] = "4.0"
                info["bandwidth"] = "~32 GB/s"
            elif "5" in slot_type:
                info["pcie_version"] = "5.0"
                info["bandwidth"] = "~64 GB/s"
            else:
                info["pcie_version"] = "2.0"
                info["bandwidth"] = "~8 GB/s"

            # Check if slot is in use
            if slot.get("current_usage", "").lower() == "in use":
                info["current_device"] = slot.get("device")
            break

    return info


def _analyze_memory_config(memory):
    """Analyze memory configuration for optimal setup recommendations"""
    config = {
        "current": {
            "populated": 0,
            "total_slots": 0,
            "capacity_gb": 0,
            "description": "",
        },
        "optimal": {
            "description": "",
            "recommendation": "",
        },
        "channel_mode": "Unknown",
    }

    if not memory:
        return config

    total_slots = memory.get("total_slots", 0)
    populated = memory.get("populated_slots", 0)
    capacity = memory.get("total_capacity_gb", 0)
    channels = memory.get("channels", "")

    config["current"]["populated"] = populated
    config["current"]["total_slots"] = total_slots
    config["current"]["capacity_gb"] = capacity
    config["current"]["description"] = f"{populated} of {total_slots} slots populated ({capacity} GB)"
    config["channel_mode"] = channels

    # Determine optimal configuration based on slot count
    # For quad-channel (8 slots): optimal is 4 or 8 DIMMs
    # For dual-channel (4 slots): optimal is 2 or 4 DIMMs
    if total_slots == 8:
        # Quad-channel system
        if populated == 8:
            config["optimal"]["description"] = "8 of 8 (Quad Channel - Maximum)"
            config["optimal"]["recommendation"] = "Fully populated - optimal for quad-channel"
        elif populated == 4:
            config["optimal"]["description"] = "4 of 8 (Quad Channel)"
            config["optimal"]["recommendation"] = "Good for quad-channel. Add 4 more DIMMs for maximum capacity."
        elif populated < 4:
            config["optimal"]["description"] = "4 of 8 or 8 of 8 recommended"
            config["optimal"][
                "recommendation"
            ] = f"Add {4 - populated} DIMMs for quad-channel, or {8 - populated} for maximum."
        else:
            config["optimal"]["description"] = "8 of 8 recommended"
            config["optimal"]["recommendation"] = f"Add {8 - populated} DIMMs for balanced quad-channel."
    elif total_slots == 4:
        # Dual-channel system
        if populated == 4:
            config["optimal"]["description"] = "4 of 4 (Dual Channel - Maximum)"
            config["optimal"]["recommendation"] = "Fully populated - optimal configuration"
        elif populated == 2:
            config["optimal"]["description"] = "2 of 4 (Dual Channel)"
            config["optimal"]["recommendation"] = "Good for dual-channel. Add 2 more DIMMs for maximum capacity."
        else:
            config["optimal"]["description"] = "2 of 4 or 4 of 4 recommended"
            config["optimal"]["recommendation"] = "Install DIMMs in pairs for dual-channel mode."
    elif total_slots == 2:
        if populated == 2:
            config["optimal"]["description"] = "2 of 2 (Dual Channel - Maximum)"
            config["optimal"]["recommendation"] = "Fully populated - optimal configuration"
        else:
            config["optimal"]["description"] = "2 of 2 recommended"
            config["optimal"]["recommendation"] = "Add 1 DIMM for dual-channel mode."
    else:
        config["optimal"]["description"] = f"{total_slots} of {total_slots}"
        config["optimal"]["recommendation"] = "Check motherboard manual for optimal configuration."

    return config


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


# Process and service endpoints extracted to process_routes.py


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
                compose_file = find_compose_file(compose_dir)
                if compose_file:
                    try:
                        with open(compose_file, "r") as f:
                            parsed = yaml.safe_load(f) or {}
                        for svc_name, svc_config in (parsed.get("services") or {}).items():
                            for port_entry in svc_config.get("ports") or []:
                                host_port = parse_compose_host_port(port_entry)
                                if host_port is None:
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
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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
            compose_file = find_compose_file(compose_dir)

            if compose_file:
                try:
                    with open(compose_file, "r") as f:
                        parsed = yaml.safe_load(f) or {}
                    for svc_name, svc_config in (parsed.get("services") or {}).items():
                        for port_entry in svc_config.get("ports") or []:
                            host_port = parse_compose_host_port(port_entry)
                            if host_port is None:
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
            {
                "port": p["port"],
                "process": p.get("process"),
                "ip": p.get("ip", "0.0.0.0"),
            }
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
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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


@system_operations_bp.route("/api/network/port-usage")
@login_required
@admin_required
def api_port_usage():
    """Get comprehensive port usage for conflict detection"""
    try:
        host_data, host_age = load_host_monitor_data()
        if not host_data:
            return (
                jsonify({"success": False, "error": "Host monitor data not available"}),
                503,
            )

        port_usage = host_data.get("port_usage", {})

        # Known ports for planned services (for highlighting)
        planned_ports = {
            "home_assistant": [8123, 1900, 5353],
            "plex": [32400, 32469, 1900, 3005, 8324, 32410, 32411, 32412, 32413, 32414],
            "adguard": [53, 80, 443, 3000, 853, 784, 8853],
            "ntopng": [3000, 5556],
        }

        # Check for conflicts with planned services
        conflicts = []
        for service, ports in planned_ports.items():
            for port in ports:
                if str(port) in port_usage or port in port_usage:
                    port_info = port_usage.get(str(port)) or port_usage.get(port, {})
                    conflicts.append(
                        {
                            "port": port,
                            "planned_service": service,
                            "current_usage": port_info,
                        }
                    )

        return jsonify(
            {
                "success": True,
                "ports": port_usage,
                "planned_conflicts": conflicts,
                "data_age": int(host_age) if host_age else None,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/docker/health")
@login_required
@admin_required
def api_docker_health():
    """Get Docker container health status and resource usage"""
    try:
        host_data, host_age = load_host_monitor_data()
        if not host_data:
            return (
                jsonify({"success": False, "error": "Host monitor data not available"}),
                503,
            )

        docker_health = host_data.get("docker_health", [])

        # Aggregate by stack using compose_project label (preferred) or container name prefix (fallback)
        stacks = {}
        for container in docker_health:
            name = container.get("name", "")
            # Use compose_project label if available, otherwise fall back to name prefix
            stack_name = container.get("compose_project", "")
            if not stack_name:
                # Fallback: extract prefix before first underscore
                stack_name = name.split("_")[0] if "_" in name else name

            if stack_name not in stacks:
                stacks[stack_name] = {
                    "name": stack_name,
                    "containers": [],
                    "total_cpu": 0.0,
                    "total_mem": 0.0,
                    "health_summary": "healthy",
                    "restart_total": 0,
                }

            stacks[stack_name]["containers"].append(container)
            stacks[stack_name]["total_cpu"] += container.get("cpu_percent", 0)
            stacks[stack_name]["total_mem"] += container.get("mem_percent", 0)
            stacks[stack_name]["restart_total"] += container.get("restart_count", 0)

            # Update health summary (worst status wins)
            health = container.get("health", "none")
            current = stacks[stack_name]["health_summary"]
            if health == "unhealthy":
                stacks[stack_name]["health_summary"] = "unhealthy"
            elif health == "starting" and current != "unhealthy":
                stacks[stack_name]["health_summary"] = "starting"
            elif container.get("state") != "running" and current not in [
                "unhealthy",
                "starting",
            ]:
                stacks[stack_name]["health_summary"] = "degraded"

        return jsonify(
            {
                "success": True,
                "containers": docker_health,
                "stacks": list(stacks.values()),
                "data_age": int(host_age) if host_age else None,
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
            return (
                jsonify({"success": False, "error": "web_ui_ports must be an array"}),
                400,
            )

        for entry in web_ui_ports:
            if not isinstance(entry, dict) or "port" not in entry:
                cur.close()
                conn.close()
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Each entry must have a 'port' field",
                        }
                    ),
                    400,
                )
            if not isinstance(entry["port"], int):
                cur.close()
                conn.close()
                return (
                    jsonify({"success": False, "error": "Port must be an integer"}),
                    400,
                )

        cur.execute(
            "UPDATE docker_stacks SET web_ui_ports = %s WHERE name = %s",
            (Json(web_ui_ports), stack_name),
        )
        conn.commit()

        audit_log("update_web_ui_ports", stack_name, {"web_ui_ports": web_ui_ports})

        return jsonify({"success": True, "web_ui_ports": web_ui_ports})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@system_operations_bp.route("/api/history")
@login_required
@admin_required
def api_history():
    """Get historical metrics for graphs"""
    try:
        metric_type = request.args.get("type", "cpu")
        hours = int(request.args.get("hours", 1))

        # Validate hours (max 720 = 30 days)
        hours = min(max(hours, 1), 720)

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # For windows > 24h, downsample to hourly averages
        if hours > 24:
            cur.execute(
                """
                SELECT AVG(value) as value, date_trunc('hour', recorded_at) as recorded_at
                FROM system_metrics_history
                WHERE metric_type = %s
                  AND recorded_at > NOW() - (%s * INTERVAL '1 hour')
                GROUP BY date_trunc('hour', recorded_at)
                ORDER BY recorded_at ASC
                LIMIT 720
            """,
                (metric_type, hours),
            )
        else:
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

        # Send ISO timestamps — frontend formats in user's local timezone
        labels = [row["recorded_at"].strftime("%Y-%m-%dT%H:%M:%SZ") for row in data]
        values = [round(float(row["value"]), 1) for row in data]

        return jsonify(
            {
                "success": True,
                "data": {
                    "labels": labels,
                    "values": values,
                    "metric_type": metric_type,
                    "count": len(values),
                    "hours": hours,
                },
            }
        )
    except Exception as e:
        import traceback

        print(f"History API error: {e}")
        print(traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@system_operations_bp.route("/api/history/multi")
@login_required
@admin_required
def api_history_multi():
    """Get historical metrics for multiple devices (e.g., gpu_0, gpu_1)"""
    try:
        base_type = request.args.get("type", "gpu")  # 'gpu', 'gpu_vram', or 'cpu'
        hours = int(request.args.get("hours", 1))
        hours = min(max(hours, 1), 720)  # Max 30 days

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Find all metric types matching pattern (e.g., gpu_0, gpu_1 but NOT gpu_vram_0)
        cur.execute(
            """
            SELECT DISTINCT metric_type
            FROM system_metrics_history
            WHERE metric_type ~ %s
              AND recorded_at > NOW() - (%s * INTERVAL '1 hour')
            ORDER BY metric_type
        """,
            (f"^{base_type}_\\d+$", hours),
        )
        device_types = [row["metric_type"] for row in cur.fetchall()]

        if not device_types:
            # Fall back to base type (backward compat - single device)
            device_types = [base_type]

        # Fetch data for each device (downsample for windows > 24h)
        devices = {}
        for metric_type in device_types:
            if hours > 24:
                cur.execute(
                    """
                    SELECT AVG(value) as value, date_trunc('hour', recorded_at) as recorded_at
                    FROM system_metrics_history
                    WHERE metric_type = %s
                      AND recorded_at > NOW() - (%s * INTERVAL '1 hour')
                    GROUP BY date_trunc('hour', recorded_at)
                    ORDER BY recorded_at ASC
                    LIMIT 720
                """,
                    (metric_type, hours),
                )
            else:
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
            if data:
                devices[metric_type] = {
                    "labels": [row["recorded_at"].strftime("%Y-%m-%dT%H:%M:%SZ") for row in data],
                    "values": [round(float(row["value"]), 1) for row in data],
                }

        return jsonify(
            {
                "success": True,
                "data": {
                    "devices": devices,
                    "base_type": base_type,
                    "device_count": len(devices),
                },
            }
        )
    except Exception as e:
        import traceback

        print(f"Multi-history API error: {e}")
        print(traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# ACTION API ENDPOINTS (Require confirmation)
# ============================================================================


# Kill process and service action endpoints extracted to process_routes.py


@system_operations_bp.route("/api/docker/<container_id>/action", methods=["POST"])
@login_required
@admin_required
def api_docker_action(container_id):
    """Perform action on a Docker container"""
    try:
        data = request.get_json() or {}

        # Require confirmation
        if not data.get("confirm"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Confirmation required",
                        "requires_confirm": True,
                    }
                ),
                400,
            )

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
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Confirmation required",
                        "requires_confirm": True,
                    }
                ),
                400,
            )

        action = data.get("action", "up")
        allowed_actions = ["up", "down", "restart", "pull"]
        if action not in allowed_actions:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Invalid action. Allowed: {allowed_actions}",
                    }
                ),
                400,
            )

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

        return jsonify(
            {
                "success": success,
                "output": result.stdout,
                "error": result.stderr if not success else None,
            }
        )
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
            ["docker", "logs", "--tail", tail, container_id],
            capture_output=True,
            text=True,
            timeout=30,
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
                    ["docker", "ps", "--format", "{{.Names}}"],
                    capture_output=True,
                    text=True,
                    timeout=10,
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
            {
                "success": True,
                "content": content,
                "modified": modified,
                "services": services,
                "file": compose_file,
            }
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
            return (
                jsonify({"success": False, "error": "File not allowed to be edited"}),
                403,
            )

        # Validate YAML syntax
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as ye:
            return (
                jsonify({"success": False, "error": f"Invalid YAML syntax: {str(ye)}"}),
                400,
            )

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

        return jsonify(
            {
                "success": True,
                "content": content,
                "modified": modified,
                "file": env_file,
            }
        )
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
            return (
                jsonify({"success": False, "error": "File not allowed to be edited"}),
                403,
            )

        # Create backup
        backup_file = f"{filename}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if os.path.exists(filename):
            import shutil

            shutil.copy2(filename, backup_file)

        # Write new content
        with open(filename, "w") as f:
            f.write(content)

        # Audit log
        audit_log(
            action_type="env_file_edit",
            target=filename,
            details={"backup_file": backup_file},
            success=True,
        )

        return jsonify(
            {
                "success": True,
                "message": "Environment file saved",
                "backup": backup_file,
            }
        )
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
            container_list = []

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

                        # Build container list for display
                        for c in containers:
                            container_list.append(
                                {
                                    "name": c.get("Service") or c.get("Name", "unknown"),
                                    "state": c.get("State", "unknown").lower(),
                                    "status": c.get("Status", ""),
                                }
                            )
                    else:
                        status = "stopped"
                except (subprocess.TimeoutExpired, Exception):
                    status = "unknown"

            stack_data["status"] = status
            stack_data["containers_running"] = containers_running
            stack_data["containers_total"] = containers_total
            stack_data["containers"] = container_list
            results.append(stack_data)

        return jsonify({"success": True, "data": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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
                jsonify(
                    {
                        "success": False,
                        "error": f"Stack directory already exists: {stack_dir}",
                    }
                ),
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
            jsonify(
                {
                    "success": False,
                    "error": f"A stack with name '{name}' already exists",
                }
            ),
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
        audit_log(
            "stack_create",
            data.get("name", "unknown"),
            success=False,
            error_message=str(e),
        )
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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
                jsonify(
                    {
                        "success": False,
                        "error": "Confirmation required",
                        "requires_confirm": True,
                    }
                ),
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
            return (
                jsonify({"success": False, "error": "Cannot delete system stack"}),
                403,
            )

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
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Invalid action. Allowed: {allowed_actions}",
                    }
                ),
                400,
            )

        if not confirm:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Confirmation required",
                        "requires_confirm": True,
                    }
                ),
                400,
            )

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
            return (
                jsonify({"success": False, "error": "Compose file not found for this stack"}),
                404,
            )

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
            return (
                jsonify({"success": False, "error": "Command timed out after 120 seconds"}),
                500,
            )

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
            "stack_action",
            stack_name,
            details={"action": data.get("action")},
            success=False,
            error_message=str(e),
        )
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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
            return (
                jsonify({"success": False, "error": f"Invalid YAML syntax: {str(ye)}"}),
                400,
            )

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
            details={
                "backup_file": backup_file,
                "file": compose_file,
                "content_length": len(content),
            },
            success=True,
        )

        return jsonify({"success": True, "message": "Compose file saved", "backup": backup_file})
    except Exception as e:
        audit_log("stack_compose_edit", stack_name, success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Invalid file path - directory traversal not allowed",
                    }
                ),
                403,
            )

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
            details={
                "filename": filename,
                "file": real_target,
                "backup_file": backup_file,
            },
            success=True,
        )

        return jsonify(
            {
                "success": True,
                "message": "Environment file saved",
                "backup": backup_file,
            }
        )
    except Exception as e:
        audit_log("stack_env_edit", stack_name, success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@system_operations_bp.route("/api/disk/<path:device>/mount", methods=["POST"])
@login_required
@admin_required
def api_mount_disk(device):
    """Mount a disk via host command queue"""
    try:
        data = request.get_json() or {}

        if not data.get("confirm"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Confirmation required",
                        "requires_confirm": True,
                    }
                ),
                400,
            )

        mountpoint = data.get("mountpoint")
        if not mountpoint:
            return jsonify({"success": False, "error": "Mountpoint required"}), 400

        params = {"device": f"/dev/{device}", "mountpoint": mountpoint}
        if data.get("fstype"):
            params["fstype"] = data["fstype"]
        # Persist mount to fstab using UUID (prevents device letter shifting issues)
        params["persist"] = data.get("persist", True)

        user_id = current_user.id if current_user.is_authenticated else None
        username = getattr(current_user, "username", "unknown")

        result_data = submit_and_wait("disk_mount", params, timeout=60, submitted_by=username, user_id=user_id)
        cmd_result = result_data.get("result", {})

        audit_log(
            action_type="disk_mount",
            target=device,
            details={
                "mountpoint": mountpoint,
                "command_id": result_data.get("command_id"),
            },
            success=cmd_result.get("success", False),
            error_message=cmd_result.get("error"),
        )

        if cmd_result.get("success"):
            return jsonify(
                {
                    "success": True,
                    "message": cmd_result.get("message", f"Mounted /dev/{device} at {mountpoint}"),
                }
            )
        else:
            return (
                jsonify({"success": False, "error": cmd_result.get("error", "mount failed")}),
                500,
            )

    except HostCommandQueueUnavailable as e:
        return (
            jsonify({"success": False, "error": str(e), "queue_unavailable": True}),
            503,
        )
    except HostCommandTimeout as e:
        audit_log("disk_mount", device, success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 504
    except Exception as e:
        audit_log("disk_mount", device, success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/disk/<path:device>/unmount", methods=["POST"])
@login_required
@admin_required
def api_unmount_disk(device):
    """Unmount a disk via host command queue"""
    try:
        data = request.get_json() or {}

        if not data.get("confirm"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Confirmation required",
                        "requires_confirm": True,
                    }
                ),
                400,
            )

        params = {"device": f"/dev/{device}"}
        if data.get("force"):
            params["force"] = True
        # Remove fstab entry when unmounting (prevents stale entries)
        params["remove_persist"] = data.get("remove_persist", True)

        user_id = current_user.id if current_user.is_authenticated else None
        username = getattr(current_user, "username", "unknown")

        result_data = submit_and_wait("disk_unmount", params, timeout=60, submitted_by=username, user_id=user_id)
        cmd_result = result_data.get("result", {})

        audit_log(
            action_type="disk_unmount",
            target=device,
            details={"command_id": result_data.get("command_id")},
            success=cmd_result.get("success", False),
            error_message=cmd_result.get("error"),
        )

        if cmd_result.get("success"):
            return jsonify(
                {
                    "success": True,
                    "message": cmd_result.get("message", f"Unmounted /dev/{device}"),
                }
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": cmd_result.get("error", "umount failed"),
                    }
                ),
                500,
            )

    except HostCommandQueueUnavailable as e:
        return (
            jsonify({"success": False, "error": str(e), "queue_unavailable": True}),
            503,
        )
    except HostCommandTimeout as e:
        audit_log("disk_unmount", device, success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 504
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
    """Extend an LVM logical volume via host command queue"""
    try:
        data = request.get_json() or {}

        # Require confirmation
        if not data.get("confirm"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Confirmation required",
                        "requires_confirm": True,
                    }
                ),
                400,
            )

        size_gb = data.get("size_gb")
        extend_all = data.get("extend_all", False)

        if not size_gb and not extend_all:
            return (
                jsonify({"success": False, "error": "Must specify size_gb or extend_all"}),
                400,
            )

        params = {"vg_name": vg_name, "lv_name": lv_name}
        if extend_all:
            params["extend_all"] = True
        elif size_gb:
            params["size_gb"] = size_gb

        user_id = current_user.id if current_user.is_authenticated else None
        username = getattr(current_user, "username", "unknown")

        result_data = submit_and_wait("lvm_extend", params, timeout=120, submitted_by=username, user_id=user_id)
        cmd_result = result_data.get("result", {})

        # Audit log
        audit_id = audit_log(
            action_type="lvm_extend",
            target=f"{vg_name}/{lv_name}",
            details={
                "size_gb": size_gb,
                "extend_all": extend_all,
                "command_id": result_data.get("command_id"),
            },
            success=cmd_result.get("success", False),
            error_message=cmd_result.get("error"),
        )

        cmd_result["audit_id"] = audit_id
        return jsonify(cmd_result)

    except HostCommandQueueUnavailable:
        # Fallback to direct execution (container-side) if queue is unavailable
        try:
            service = get_system_service()
            result = service.extend_lvm(vg_name, lv_name, size_gb=size_gb, extend_all=extend_all)
            result["fallback"] = True
            audit_id = audit_log(
                action_type="lvm_extend",
                target=f"{vg_name}/{lv_name}",
                details={
                    "size_gb": size_gb,
                    "extend_all": extend_all,
                    "fallback": True,
                },
                success=result["success"],
                error_message=result.get("error"),
            )
            result["audit_id"] = audit_id
            return jsonify(result)
        except Exception as inner_e:
            audit_log(
                "lvm_extend",
                f"{vg_name}/{lv_name}",
                success=False,
                error_message=str(inner_e),
            )
            return jsonify({"success": False, "error": str(inner_e)}), 500
    except HostCommandTimeout as e:
        audit_log("lvm_extend", f"{vg_name}/{lv_name}", success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 504
    except Exception as e:
        audit_log("lvm_extend", f"{vg_name}/{lv_name}", success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/filesystem/resize", methods=["POST"])
@login_required
@admin_required
def api_filesystem_resize():
    """Resize a filesystem to fill its container (partition/LV).

    Useful when lvextend succeeded but resize2fs failed (e.g., device was busy).
    """
    try:
        from .host_command_client import (
            submit_and_wait,
            is_queue_available,
            HostCommandTimeout,
            HostCommandQueueUnavailable,
        )

        data = request.get_json() or {}
        device = data.get("device")

        if not device:
            return jsonify({"success": False, "error": "Device path required"}), 400

        # Validate device path format
        import re

        if not re.match(r"^/dev/[a-zA-Z0-9_/\-]+$", device):
            return jsonify({"success": False, "error": "Invalid device path"}), 400

        if not is_queue_available():
            return (
                jsonify({"success": False, "error": "Host command queue not available"}),
                503,
            )

        result_data = submit_and_wait("filesystem_resize", {"device": device}, timeout=120)
        result = result_data.get("result", {"success": False, "error": "No result from host"})

        audit_log(
            action_type="filesystem_resize",
            target=device,
            details={"device": device},
            success=result.get("success", False),
            error_message=result.get("error"),
        )

        return jsonify(result)

    except HostCommandTimeout as e:
        audit_log("filesystem_resize", device, success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 504
    except HostCommandQueueUnavailable:
        return (
            jsonify({"success": False, "error": "Host command queue not available"}),
            503,
        )
    except Exception as e:
        audit_log(
            "filesystem_resize",
            data.get("device", "unknown"),
            success=False,
            error_message=str(e),
        )
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
# HOST COMMAND QUEUE ENDPOINTS
# ============================================================================

# Commands that require re-authentication before submission
DANGEROUS_COMMAND_TYPES = {
    "lvm_shrink",
    "disk_format",
    "partition_create",
    "pv_create_vg_extend",
    "vg_create",
    "convert_to_lvm",
    "lvm_snapshot",
    "disk_prepare",
    "disk_prepare_lvm",
    "disk_wipe",
}


@system_operations_bp.route("/api/host-command/status")
@login_required
@admin_required
def api_host_command_status():
    """Get host command queue health status"""
    try:
        status = get_queue_status()
        return jsonify({"success": True, **status})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/host-command/submit", methods=["POST"])
@login_required
@admin_required
def api_host_command_submit():
    """Submit a command to the host command queue"""
    try:
        data = request.get_json() or {}
        command_type = data.get("command_type")
        params = data.get("params", {})
        confirm = data.get("confirm", False)

        if not command_type:
            return jsonify({"success": False, "error": "command_type is required"}), 400

        if not confirm:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Confirmation required",
                        "requires_confirm": True,
                    }
                ),
                400,
            )

        # Dangerous commands require re-authentication
        if command_type in DANGEROUS_COMMAND_TYPES:
            reauth = require_reauth()
            if reauth is not None:
                return reauth

        # Submit to queue
        user_id = current_user.id if current_user.is_authenticated else None
        username = getattr(current_user, "username", "unknown")
        command_id = submit_host_command(
            command_type,
            params,
            submitted_by=username,
            user_id=user_id,
        )

        # Audit log
        audit_log(
            action_type=f"host_command_{command_type}",
            target=command_type,
            details={"command_id": command_id, "params": params},
            success=True,
        )

        return jsonify({"success": True, "command_id": command_id})

    except HostCommandQueueUnavailable as e:
        return (
            jsonify({"success": False, "error": str(e), "queue_unavailable": True}),
            503,
        )
    except Exception as e:
        audit_log(
            action_type="host_command_submit",
            target=data.get("command_type", "unknown"),
            success=False,
            error_message=str(e),
        )
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/host-command/<command_id>/result")
@login_required
@admin_required
def api_host_command_result(command_id):
    """Poll for a host command result.
    Returns 200 with result if completed, 202 if still pending, 404 if unknown."""
    try:
        # Validate command_id format (UUID)
        import re as re_mod

        if not re_mod.match(r"^[0-9a-f\-]{36}$", command_id):
            return (
                jsonify({"success": False, "error": "Invalid command ID format"}),
                400,
            )

        result = get_command_result(command_id)
        if result is not None:
            # Completed
            return jsonify({"success": True, "status": "completed", "data": result})
        else:
            # Check if it's still pending
            pending_path = os.path.join(
                os.environ.get("ARCHIE_BASE_DIR", "/mnt/archie_brain"),
                "host_commands",
                "pending",
                f"{command_id}.json",
            )
            if os.path.exists(pending_path):
                return jsonify({"success": True, "status": "pending"}), 202
            else:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Command not found",
                            "status": "unknown",
                        }
                    ),
                    404,
                )

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
            return (
                jsonify({"success": False, "error": "Host monitor data not available"}),
                503,
            )

        disks = host_data.get("disks", [])
        lvm = host_data.get("lvm")
        raid = host_data.get("raid")
        docker_mounts = host_data.get("docker_mounts", {})

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

        # Get SMART details and capacity alerts
        smart_details = host_data.get("smart_details", {})
        capacity_alerts = host_data.get("capacity_alerts", [])

        return jsonify(
            {
                "success": True,
                "data": {
                    "disks": disks,
                    "lvm": lvm,
                    "raid": raid,
                    "vg_free": vg_free,
                    "managed_mounts": managed,
                    "docker_mounts": docker_mounts,
                    "smart_details": smart_details,
                    "capacity_alerts": capacity_alerts,
                    "data_age": int(age) if age else None,
                },
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
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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

        audit_log(
            "storage_mount_register",
            device,
            details={
                "mount_point": data.get("mount_point"),
                "label": data.get("label"),
            },
        )

        return jsonify({"success": True, "data": dict(result)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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


@system_operations_bp.route("/api/storage/docker-mounts")
@login_required
@admin_required
def api_storage_docker_mounts():
    """Get Docker stack volume mappings to show which stacks use which paths"""
    try:
        import yaml

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT name, display_name, compose_directory, color FROM docker_stacks")
        stacks = cur.fetchall()

        # Map of host_path -> [stack info]
        path_to_stacks = {}

        for stack in stacks:
            compose_dir = stack.get("compose_directory", "")
            compose_file = os.path.join(compose_dir, "docker-compose.yml") if compose_dir else ""

            if not compose_file or not os.path.exists(compose_file):
                continue

            try:
                with open(compose_file, "r") as f:
                    compose = yaml.safe_load(f)

                if not compose or "services" not in compose:
                    continue

                for service_name, service in compose.get("services", {}).items():
                    volumes = service.get("volumes", [])
                    for vol in volumes:
                        if isinstance(vol, str) and ":" in vol:
                            # Format: host_path:container_path or host_path:container_path:mode
                            parts = vol.split(":")
                            host_path = parts[0]
                            container_path = parts[1] if len(parts) > 1 else ""

                            # Skip named volumes (no / at start)
                            if not host_path.startswith("/") and not host_path.startswith("."):
                                continue

                            # Resolve relative paths
                            if host_path.startswith("."):
                                host_path = os.path.normpath(os.path.join(compose_dir, host_path))

                            # Get the mount point this path belongs to
                            real_path = os.path.realpath(host_path) if os.path.exists(host_path) else host_path

                            if real_path not in path_to_stacks:
                                path_to_stacks[real_path] = []

                            path_to_stacks[real_path].append(
                                {
                                    "stack_name": stack["name"],
                                    "display_name": stack.get("display_name") or stack["name"],
                                    "color": stack.get("color", "#6366f1"),
                                    "service": service_name,
                                    "container_path": container_path,
                                }
                            )
                        elif isinstance(vol, dict):
                            # Long-form volume definition
                            source = vol.get("source", "")
                            target = vol.get("target", "")
                            vol_type = vol.get("type", "volume")

                            if vol_type == "bind" and source:
                                if source.startswith("."):
                                    source = os.path.normpath(os.path.join(compose_dir, source))

                                real_path = os.path.realpath(source) if os.path.exists(source) else source

                                if real_path not in path_to_stacks:
                                    path_to_stacks[real_path] = []

                                path_to_stacks[real_path].append(
                                    {
                                        "stack_name": stack["name"],
                                        "display_name": stack.get("display_name") or stack["name"],
                                        "color": stack.get("color", "#6366f1"),
                                        "service": service_name,
                                        "container_path": target,
                                    }
                                )
            except Exception:
                # Skip stacks with parse errors
                continue

        # Group by mount point (find which partition each path belongs to)
        # This will be matched on the frontend with partition mountpoints
        return jsonify(
            {
                "success": True,
                "data": {"path_mappings": path_to_stacks, "stack_count": len(stacks)},
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


@system_operations_bp.route("/api/storage/preflight", methods=["POST"])
@login_required
@admin_required
def api_storage_preflight():
    """Pre-flight check before storage operations to detect potential issues"""
    try:
        import subprocess

        data = request.get_json() or {}
        device = data.get("device", "")
        mountpoint = data.get("mountpoint", "")
        operation = data.get("operation", "")  # extend, shrink, resize, unmount

        warnings = []

        # Check 1: Find containers using the mount path
        if mountpoint:
            try:
                # Get list of running containers
                result = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True, timeout=10)
                container_ids = result.stdout.strip().split("\n") if result.stdout.strip() else []

                containers_using_mount = []
                for cid in container_ids:
                    if not cid:
                        continue
                    # Inspect container mounts
                    inspect = subprocess.run(
                        ["docker", "inspect", "--format", "{{json .Mounts}}", cid],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if inspect.returncode == 0 and mountpoint in inspect.stdout:
                        # Get container name
                        name_result = subprocess.run(
                            ["docker", "inspect", "--format", "{{.Name}}", cid],
                            capture_output=True,
                            text=True,
                            timeout=5,
                        )
                        container_name = name_result.stdout.strip().lstrip("/") if name_result.returncode == 0 else cid
                        containers_using_mount.append(container_name)

                if containers_using_mount:
                    warnings.append(
                        {
                            "type": "containers",
                            "severity": "info",
                            "message": f"{len(containers_using_mount)} container(s) will be temporarily stopped",
                            "details": containers_using_mount,
                        }
                    )
            except Exception:
                # Don't fail preflight if container check fails
                pass

        # Check 2: Stale mount detection (device path doesn't exist but mount is active)
        # NOTE: This check runs inside the Docker container where LVM device symlinks
        # (e.g. /dev/ubuntu-vg/ubuntu-lv) are NOT visible. Skip the os.path.exists()
        # check for LVM paths since the actual operations run on the host via the
        # command queue where devices are accessible.
        is_lvm_device = device and (device.startswith("/dev/mapper/") or len(device.split("/")) >= 4)
        if device and mountpoint and not is_lvm_device:
            try:
                # Check if device path exists
                device_exists = os.path.exists(device)

                # Check if mountpoint is mounted
                result = subprocess.run(
                    ["findmnt", "-n", "-o", "SOURCE", mountpoint],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                is_mounted = result.returncode == 0 and result.stdout.strip()
                mounted_device = result.stdout.strip() if is_mounted else None

                if is_mounted and not device_exists:
                    warnings.append(
                        {
                            "type": "stale_mount",
                            "severity": "high",
                            "message": "Stale mount detected - device path may have changed after rename",
                            "details": f"Mount shows {mounted_device} but {device} does not exist",
                        }
                    )
                elif is_mounted and mounted_device and mounted_device != device:
                    warnings.append(
                        {
                            "type": "device_mismatch",
                            "severity": "warning",
                            "message": "Mount device differs from expected",
                            "details": f"Expected {device}, found {mounted_device}",
                        }
                    )
            except Exception:
                pass

        # Check 3: Device busy check
        if device:
            try:
                # Use lsof to check if device is in use
                result = subprocess.run(["lsof", device], capture_output=True, text=True, timeout=10)
                if result.returncode == 0 and result.stdout.strip():
                    lines = result.stdout.strip().split("\n")
                    process_count = len(lines) - 1  # Subtract header
                    if process_count > 0:
                        warnings.append(
                            {
                                "type": "busy",
                                "severity": "info",
                                "message": f"Device has {process_count} open file handle(s)",
                                "details": "These will be released when containers stop",
                            }
                        )
            except FileNotFoundError:
                pass  # lsof not installed
            except Exception:
                pass

        # Check 4: For shrink operations, verify used space
        if operation == "shrink" and mountpoint:
            try:
                result = subprocess.run(
                    ["df", "-BG", "--output=used", mountpoint],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    if len(lines) > 1:
                        used_str = lines[1].strip().rstrip("G")
                        try:
                            used_gb = int(used_str)
                            if used_gb > 0:
                                warnings.append(
                                    {
                                        "type": "shrink_info",
                                        "severity": "info",
                                        "message": f"Minimum size: {used_gb} GB (current usage)",
                                        "details": "Cannot shrink below used space",
                                    }
                                )
                        except ValueError:
                            pass
            except Exception:
                pass

        # Determine if operation can proceed
        high_severity = [w for w in warnings if w.get("severity") == "high"]
        can_proceed = len(high_severity) == 0

        return jsonify(
            {
                "success": True,
                "warnings": warnings,
                "can_proceed": can_proceed,
                "warning_count": len(warnings),
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

        if not user:
            audit_log(
                "reauth_attempt",
                "verify",
                success=False,
                error_message="User not found",
            )
            return jsonify({"success": False, "error": "User not found"}), 404

        if not check_password_hash(user["password_hash"], password):
            audit_log(
                "reauth_attempt",
                "verify",
                success=False,
                error_message=f"Invalid password for user {current_user.username}",
            )
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Invalid password for user '{current_user.username}'",
                    }
                ),
                401,
            )

        # Store re-auth timestamp in session (valid for 5 minutes)
        session["reauth_timestamp"] = time_mod.time()

        audit_log("reauth_attempt", "verify", success=True)

        return jsonify(
            {
                "success": True,
                "message": "Re-authentication successful",
                "valid_for": 300,
            }
        )
    except Exception as e:
        audit_log("reauth_attempt", "verify", success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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

        # Convert datetime objects
        for row in data:
            if row["created_at"]:
                row["created_at"] = row["created_at"].isoformat()

        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


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
# HEALTH ALERTS API
# ============================================================================


@system_operations_bp.route("/api/health/alerts")
@login_required
@admin_required
def get_health_alerts():
    """Get active health alerts"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        include_resolved = request.args.get("include_resolved", "false").lower() == "true"
        stack_name = request.args.get("stack")
        limit = request.args.get("limit", 50, type=int)

        query = """
            SELECT id, stack_name, container_name, alert_type, severity, message,
                   details, acknowledged, acknowledged_by, acknowledged_at,
                   resolved, resolved_at, created_at
            FROM stack_health_alerts
            WHERE 1=1
        """
        params = []

        if not include_resolved:
            query += " AND resolved = FALSE"

        if stack_name:
            query += " AND stack_name = %s"
            params.append(stack_name)

        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        alerts = cur.fetchall()

        # Get counts by severity
        cur.execute(
            """
            SELECT severity, COUNT(*) as count
            FROM stack_health_alerts
            WHERE resolved = FALSE
            GROUP BY severity
        """
        )
        counts = {row["severity"]: row["count"] for row in cur.fetchall()}

        return jsonify(
            {
                "success": True,
                "alerts": [dict(a) for a in alerts],
                "counts": {
                    "critical": counts.get("critical", 0),
                    "warning": counts.get("warning", 0),
                    "info": counts.get("info", 0),
                    "total": sum(counts.values()),
                },
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


@system_operations_bp.route("/api/health/alerts/<int:alert_id>/acknowledge", methods=["POST"])
@login_required
@admin_required
def acknowledge_health_alert(alert_id):
    """Acknowledge a health alert"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE stack_health_alerts
            SET acknowledged = TRUE,
                acknowledged_by = %s,
                acknowledged_at = CURRENT_TIMESTAMP
            WHERE id = %s AND acknowledged = FALSE
            RETURNING id
        """,
            (current_user.id, alert_id),
        )

        result = cur.fetchone()
        conn.commit()

        if result:
            return jsonify({"success": True, "message": "Alert acknowledged"})
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Alert not found or already acknowledged",
                    }
                ),
                404,
            )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@system_operations_bp.route("/api/health/alerts/<int:alert_id>/resolve", methods=["POST"])
@login_required
@admin_required
def resolve_health_alert(alert_id):
    """Resolve a health alert"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE stack_health_alerts
            SET resolved = TRUE,
                resolved_at = CURRENT_TIMESTAMP
            WHERE id = %s AND resolved = FALSE
            RETURNING id
        """,
            (alert_id,),
        )

        result = cur.fetchone()
        conn.commit()

        if result:
            return jsonify({"success": True, "message": "Alert resolved"})
        else:
            return (
                jsonify({"success": False, "error": "Alert not found or already resolved"}),
                404,
            )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@system_operations_bp.route("/api/health/config")
@login_required
@admin_required
def get_health_config():
    """Get health alert configuration"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, stack_name, metric_type, threshold_warning, threshold_critical,
                   enabled, cooldown_minutes, updated_at
            FROM stack_health_config
            ORDER BY stack_name NULLS FIRST, metric_type
        """
        )
        configs = cur.fetchall()

        return jsonify({"success": True, "configs": [dict(c) for c in configs]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@system_operations_bp.route("/api/health/config", methods=["POST"])
@login_required
@admin_required
def update_health_config():
    """Update health alert configuration"""
    try:
        data = request.get_json()
        stack_name = data.get("stack_name")  # None for global
        metric_type = data.get("metric_type")
        threshold_warning = data.get("threshold_warning")
        threshold_critical = data.get("threshold_critical")
        enabled = data.get("enabled", True)
        cooldown_minutes = data.get("cooldown_minutes", 15)

        if not metric_type:
            return jsonify({"success": False, "error": "metric_type required"}), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO stack_health_config
            (stack_name, metric_type, threshold_warning, threshold_critical, enabled, cooldown_minutes)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (stack_name, metric_type)
            DO UPDATE SET
                threshold_warning = EXCLUDED.threshold_warning,
                threshold_critical = EXCLUDED.threshold_critical,
                enabled = EXCLUDED.enabled,
                cooldown_minutes = EXCLUDED.cooldown_minutes
            RETURNING id
        """,
            (
                stack_name,
                metric_type,
                threshold_warning,
                threshold_critical,
                enabled,
                cooldown_minutes,
            ),
        )

        result = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "id": result[0]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@system_operations_bp.route("/api/health/webhooks")
@login_required
@admin_required
def get_health_webhooks():
    """Get health alert webhooks"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, name, url, event_types, stack_filter, active,
                   created_at, last_triggered, last_status, last_error
            FROM health_alert_webhooks
            ORDER BY created_at DESC
        """
        )
        webhooks = cur.fetchall()

        return jsonify({"success": True, "webhooks": [dict(w) for w in webhooks]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@system_operations_bp.route("/api/health/webhooks", methods=["POST"])
@login_required
@admin_required
def create_health_webhook():
    """Create a health alert webhook"""
    try:
        data = request.get_json()
        name = data.get("name")
        url = data.get("url")
        event_types = data.get("event_types", ["container_crash", "health_warning", "health_critical"])
        stack_filter = data.get("stack_filter")  # None for all stacks
        active = data.get("active", True)
        secret_key = data.get("secret_key")

        if not name or not url:
            return jsonify({"success": False, "error": "name and url required"}), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO health_alert_webhooks
            (name, url, event_types, stack_filter, active, secret_key)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (name, url, event_types, stack_filter, active, secret_key),
        )

        result = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "id": result[0]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@system_operations_bp.route("/api/health/webhooks/<int:webhook_id>", methods=["DELETE"])
@login_required
@admin_required
def delete_health_webhook(webhook_id):
    """Delete a health alert webhook"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "DELETE FROM health_alert_webhooks WHERE id = %s RETURNING id",
            (webhook_id,),
        )
        result = cur.fetchone()
        conn.commit()

        if result:
            return jsonify({"success": True, "message": "Webhook deleted"})
        else:
            return jsonify({"success": False, "error": "Webhook not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@system_operations_bp.route("/api/health/webhooks/<int:webhook_id>/test", methods=["POST"])
@login_required
@admin_required
def test_health_webhook(webhook_id):
    """Test a health alert webhook"""
    import requests as req_lib

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM health_alert_webhooks WHERE id = %s", (webhook_id,))
        webhook = cur.fetchone()

        if not webhook:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Webhook not found"}), 404

        # Send test payload
        payload = {
            "event_type": "test",
            "message": "Test alert from A.R.C.H.I.E. Health Monitoring",
            "timestamp": datetime.utcnow().isoformat(),
            "test": True,
        }

        headers = {"Content-Type": "application/json"}
        if webhook.get("secret_key"):
            headers["X-Webhook-Secret"] = webhook["secret_key"]

        try:
            response = req_lib.post(webhook["url"], json=payload, headers=headers, timeout=10)
            status_code = response.status_code
            success = 200 <= status_code < 300
            error_msg = None if success else response.text[:500]
        except req_lib.RequestException as e:
            status_code = 0
            success = False
            error_msg = str(e)

        # Update webhook status
        cur.execute(
            """
            UPDATE health_alert_webhooks
            SET last_triggered = CURRENT_TIMESTAMP,
                last_status = %s,
                last_error = %s
            WHERE id = %s
        """,
            (status_code, error_msg, webhook_id),
        )
        conn.commit()

        return jsonify({"success": success, "status_code": status_code, "error": error_msg})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# FIREWALL (UFW) MANAGEMENT
# ============================================================================


def parse_ufw_rules(output):
    """Parse UFW numbered output into structured data.

    Example input:
    Status: active
         To                         Action      From
         --                         ------      ----
    [ 1] 22/tcp                     ALLOW IN    Anywhere
    [ 2] 80/tcp                     ALLOW IN    Anywhere
    [ 3] 443/tcp                    ALLOW IN    Anywhere

    Returns list of dicts with: number, port, action, direction, from_addr
    """
    import re

    rules = []
    for line in output.split("\n"):
        # Match lines like: [ 1] 22/tcp                     ALLOW IN    Anywhere
        match = re.match(r"\[\s*(\d+)\]\s+(\S+)\s+(ALLOW|DENY|REJECT|LIMIT)\s*(IN|OUT)?\s*(.*)", line)
        if match:
            rule_num = int(match.group(1))
            port_proto = match.group(2)
            action = match.group(3)
            direction = match.group(4) or "IN"
            from_addr = match.group(5).strip() or "Anywhere"

            rules.append(
                {
                    "number": rule_num,
                    "port": port_proto,
                    "action": action,
                    "direction": direction,
                    "from": from_addr,
                }
            )
    return rules


@system_operations_bp.route("/api/firewall/status")
@login_required
@admin_required
def api_firewall_status():
    """Get UFW firewall status"""
    try:
        user_id = current_user.id if current_user.is_authenticated else None
        username = getattr(current_user, "username", "unknown")

        result_data = submit_and_wait("firewall_status", {}, timeout=30, submitted_by=username, user_id=user_id)
        cmd_result = result_data.get("result", {})

        if cmd_result.get("success"):
            return jsonify(
                {
                    "success": True,
                    "active": cmd_result.get("active", False),
                    "output": cmd_result.get("output", ""),
                }
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": cmd_result.get("error", "Failed to get status"),
                    }
                ),
                500,
            )

    except HostCommandQueueUnavailable as e:
        return (
            jsonify({"success": False, "error": str(e), "queue_unavailable": True}),
            503,
        )
    except HostCommandTimeout as e:
        return jsonify({"success": False, "error": str(e)}), 504
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/firewall/rules")
@login_required
@admin_required
def api_firewall_rules():
    """Get numbered list of UFW firewall rules (works even when inactive)"""
    try:
        user_id = current_user.id if current_user.is_authenticated else None
        username = getattr(current_user, "username", "unknown")

        result_data = submit_and_wait("firewall_rules", {}, timeout=30, submitted_by=username, user_id=user_id)
        cmd_result = result_data.get("result", {})

        if cmd_result.get("success"):
            output = cmd_result.get("output", "")
            from_config = cmd_result.get("from_config", False)

            # If rules came from config (UFW inactive), use those directly
            if from_config and cmd_result.get("rules"):
                rules = cmd_result.get("rules", [])
            else:
                # Parse from ufw status numbered output
                rules = parse_ufw_rules(output)

            return jsonify(
                {
                    "success": True,
                    "rules": rules,
                    "raw_output": output,
                    "from_config": from_config,
                }
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": cmd_result.get("error", "Failed to get rules"),
                    }
                ),
                500,
            )

    except HostCommandQueueUnavailable as e:
        return (
            jsonify({"success": False, "error": str(e), "queue_unavailable": True}),
            503,
        )
    except HostCommandTimeout as e:
        return jsonify({"success": False, "error": str(e)}), 504
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/firewall/enable", methods=["POST"])
@login_required
@admin_required
def api_firewall_enable():
    """Enable UFW firewall"""
    try:
        # Re-auth check for dangerous operation
        reauth_error = require_reauth()
        if reauth_error:
            return reauth_error

        user_id = current_user.id if current_user.is_authenticated else None
        username = getattr(current_user, "username", "unknown")

        result_data = submit_and_wait("firewall_enable", {}, timeout=60, submitted_by=username, user_id=user_id)
        cmd_result = result_data.get("result", {})

        audit_log(
            action_type="firewall_enable",
            target="ufw",
            details={"command_id": result_data.get("command_id")},
            success=cmd_result.get("success", False),
            error_message=cmd_result.get("error"),
        )

        if cmd_result.get("success"):
            return jsonify(
                {
                    "success": True,
                    "message": cmd_result.get("message", "Firewall enabled"),
                }
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": cmd_result.get("error", "Failed to enable"),
                    }
                ),
                500,
            )

    except HostCommandQueueUnavailable as e:
        return (
            jsonify({"success": False, "error": str(e), "queue_unavailable": True}),
            503,
        )
    except HostCommandTimeout as e:
        audit_log("firewall_enable", "ufw", success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 504
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/firewall/disable", methods=["POST"])
@login_required
@admin_required
def api_firewall_disable():
    """Disable UFW firewall"""
    try:
        # Re-auth check for dangerous operation
        reauth_error = require_reauth()
        if reauth_error:
            return reauth_error

        user_id = current_user.id if current_user.is_authenticated else None
        username = getattr(current_user, "username", "unknown")

        result_data = submit_and_wait("firewall_disable", {}, timeout=60, submitted_by=username, user_id=user_id)
        cmd_result = result_data.get("result", {})

        audit_log(
            action_type="firewall_disable",
            target="ufw",
            details={"command_id": result_data.get("command_id")},
            success=cmd_result.get("success", False),
            error_message=cmd_result.get("error"),
        )

        if cmd_result.get("success"):
            return jsonify(
                {
                    "success": True,
                    "message": cmd_result.get("message", "Firewall disabled"),
                }
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": cmd_result.get("error", "Failed to disable"),
                    }
                ),
                500,
            )

    except HostCommandQueueUnavailable as e:
        return (
            jsonify({"success": False, "error": str(e), "queue_unavailable": True}),
            503,
        )
    except HostCommandTimeout as e:
        audit_log("firewall_disable", "ufw", success=False, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 504
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/firewall/allow", methods=["POST"])
@login_required
@admin_required
def api_firewall_allow():
    """Allow a port through the firewall"""
    try:
        data = request.get_json() or {}
        port = data.get("port")
        protocol = data.get("protocol", "tcp")

        # Validate port
        if not port or not isinstance(port, int) or not (1 <= port <= 65535):
            return (
                jsonify({"success": False, "error": "Invalid port. Must be integer 1-65535"}),
                400,
            )

        # Validate protocol
        if protocol not in ("tcp", "udp"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Invalid protocol. Must be 'tcp' or 'udp'",
                    }
                ),
                400,
            )

        user_id = current_user.id if current_user.is_authenticated else None
        username = getattr(current_user, "username", "unknown")

        result_data = submit_and_wait(
            "firewall_allow",
            {"port": port, "protocol": protocol},
            timeout=60,
            submitted_by=username,
            user_id=user_id,
        )
        cmd_result = result_data.get("result", {})

        audit_log(
            action_type="firewall_allow",
            target=f"{port}/{protocol}",
            details={
                "port": port,
                "protocol": protocol,
                "command_id": result_data.get("command_id"),
            },
            success=cmd_result.get("success", False),
            error_message=cmd_result.get("error"),
        )

        if cmd_result.get("success"):
            return jsonify(
                {
                    "success": True,
                    "message": cmd_result.get("message", f"Allowed {port}/{protocol}"),
                }
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": cmd_result.get("error", "Failed to allow port"),
                    }
                ),
                500,
            )

    except HostCommandQueueUnavailable as e:
        return (
            jsonify({"success": False, "error": str(e), "queue_unavailable": True}),
            503,
        )
    except HostCommandTimeout as e:
        return jsonify({"success": False, "error": str(e)}), 504
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/firewall/deny", methods=["POST"])
@login_required
@admin_required
def api_firewall_deny():
    """Deny a port through the firewall"""
    try:
        data = request.get_json() or {}
        port = data.get("port")
        protocol = data.get("protocol", "tcp")

        # Validate port
        if not port or not isinstance(port, int) or not (1 <= port <= 65535):
            return (
                jsonify({"success": False, "error": "Invalid port. Must be integer 1-65535"}),
                400,
            )

        # Validate protocol
        if protocol not in ("tcp", "udp"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Invalid protocol. Must be 'tcp' or 'udp'",
                    }
                ),
                400,
            )

        user_id = current_user.id if current_user.is_authenticated else None
        username = getattr(current_user, "username", "unknown")

        result_data = submit_and_wait(
            "firewall_deny",
            {"port": port, "protocol": protocol},
            timeout=60,
            submitted_by=username,
            user_id=user_id,
        )
        cmd_result = result_data.get("result", {})

        audit_log(
            action_type="firewall_deny",
            target=f"{port}/{protocol}",
            details={
                "port": port,
                "protocol": protocol,
                "command_id": result_data.get("command_id"),
            },
            success=cmd_result.get("success", False),
            error_message=cmd_result.get("error"),
        )

        if cmd_result.get("success"):
            return jsonify(
                {
                    "success": True,
                    "message": cmd_result.get("message", f"Denied {port}/{protocol}"),
                }
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": cmd_result.get("error", "Failed to deny port"),
                    }
                ),
                500,
            )

    except HostCommandQueueUnavailable as e:
        return (
            jsonify({"success": False, "error": str(e), "queue_unavailable": True}),
            503,
        )
    except HostCommandTimeout as e:
        return jsonify({"success": False, "error": str(e)}), 504
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/firewall/update", methods=["PUT"])
@login_required
@admin_required
def api_firewall_update():
    """Update an existing firewall rule"""
    try:
        data = request.get_json() or {}
        old_port = data.get("old_port")
        old_protocol = data.get("old_protocol", "tcp")
        new_port = data.get("new_port")
        new_protocol = data.get("new_protocol", "tcp")
        action = data.get("action", "allow")

        # Validate ports
        if not old_port or not isinstance(old_port, int) or not (1 <= old_port <= 65535):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Invalid old_port. Must be integer 1-65535",
                    }
                ),
                400,
            )
        if not new_port or not isinstance(new_port, int) or not (1 <= new_port <= 65535):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Invalid new_port. Must be integer 1-65535",
                    }
                ),
                400,
            )

        # Validate protocols
        if old_protocol not in ("tcp", "udp") or new_protocol not in ("tcp", "udp"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Invalid protocol. Must be 'tcp' or 'udp'",
                    }
                ),
                400,
            )

        # Validate action
        if action not in ("allow", "deny"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Invalid action. Must be 'allow' or 'deny'",
                    }
                ),
                400,
            )

        user_id = current_user.id if current_user.is_authenticated else None
        username = getattr(current_user, "username", "unknown")

        result_data = submit_and_wait(
            "firewall_update",
            {
                "old_port": old_port,
                "old_protocol": old_protocol,
                "new_port": new_port,
                "new_protocol": new_protocol,
                "action": action,
            },
            timeout=60,
            submitted_by=username,
            user_id=user_id,
        )
        cmd_result = result_data.get("result", {})

        audit_log(
            action_type="firewall_update",
            target=f"{old_port}/{old_protocol} -> {new_port}/{new_protocol}",
            details={
                "old_port": old_port,
                "old_protocol": old_protocol,
                "new_port": new_port,
                "new_protocol": new_protocol,
                "action": action,
                "command_id": result_data.get("command_id"),
            },
            success=cmd_result.get("success", False),
            error_message=cmd_result.get("error"),
        )

        if cmd_result.get("success"):
            return jsonify({"success": True, "message": cmd_result.get("message", "Rule updated")})
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": cmd_result.get("error", "Failed to update rule"),
                    }
                ),
                500,
            )

    except HostCommandQueueUnavailable as e:
        return (
            jsonify({"success": False, "error": str(e), "queue_unavailable": True}),
            503,
        )
    except HostCommandTimeout as e:
        return jsonify({"success": False, "error": str(e)}), 504
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@system_operations_bp.route("/api/firewall/delete", methods=["DELETE"])
@login_required
@admin_required
def api_firewall_delete():
    """Delete a firewall rule by number"""
    try:
        # Re-auth check for dangerous operation
        reauth_error = require_reauth()
        if reauth_error:
            return reauth_error

        data = request.get_json() or {}
        rule_number = data.get("rule_number")

        # Validate rule number
        if not rule_number or not isinstance(rule_number, int) or rule_number < 1:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Invalid rule_number. Must be integer >= 1",
                    }
                ),
                400,
            )

        user_id = current_user.id if current_user.is_authenticated else None
        username = getattr(current_user, "username", "unknown")

        result_data = submit_and_wait(
            "firewall_delete",
            {"rule_number": rule_number},
            timeout=60,
            submitted_by=username,
            user_id=user_id,
        )
        cmd_result = result_data.get("result", {})

        audit_log(
            action_type="firewall_delete",
            target=f"rule #{rule_number}",
            details={
                "rule_number": rule_number,
                "command_id": result_data.get("command_id"),
            },
            success=cmd_result.get("success", False),
            error_message=cmd_result.get("error"),
        )

        if cmd_result.get("success"):
            return jsonify(
                {
                    "success": True,
                    "message": cmd_result.get("message", f"Deleted rule #{rule_number}"),
                }
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": cmd_result.get("error", "Failed to delete rule"),
                    }
                ),
                500,
            )

    except HostCommandQueueUnavailable as e:
        return (
            jsonify({"success": False, "error": str(e), "queue_unavailable": True}),
            503,
        )
    except HostCommandTimeout as e:
        audit_log(
            "firewall_delete",
            f"rule #{rule_number}",
            success=False,
            error_message=str(e),
        )
        return jsonify({"success": False, "error": str(e)}), 504
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# SHARED STACK STATUS API (for cross-module use)
# ============================================================================


@system_operations_bp.route("/api/stacks/status")
@login_required
def api_stacks_status():
    """
    Lightweight stack status endpoint for cross-module use.
    Returns essential status info without requiring admin privileges.
    Used by Security & Network module to show stack status.

    Query params:
        names: comma-separated list of stack names to filter (optional)
    """
    try:
        import subprocess

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get optional filter
        names_filter = request.args.get("names", "")
        filter_names = [n.strip() for n in names_filter.split(",") if n.strip()] if names_filter else None

        if filter_names:
            cur.execute(
                """
                SELECT id, name, display_name, color, compose_directory
                FROM docker_stacks
                WHERE name = ANY(%s)
                ORDER BY display_name ASC
                """,
                (filter_names,),
            )
        else:
            cur.execute(
                """
                SELECT id, name, display_name, color, compose_directory
                FROM docker_stacks
                ORDER BY is_system DESC, display_name ASC
                """
            )
        stacks = cur.fetchall()

        results = []
        for stack in stacks:
            compose_dir = stack.get("compose_directory", "")
            compose_file = find_compose_file(compose_dir) if compose_dir else None

            # Get live container status
            containers_running = 0
            containers_total = 0
            status = "unknown"

            if compose_file and os.path.exists(compose_file):
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

            results.append(
                {
                    "name": stack["name"],
                    "display_name": stack["display_name"],
                    "color": stack["color"],
                    "status": status,
                    "containers_running": containers_running,
                    "containers_total": containers_total,
                }
            )

        return jsonify({"success": True, "stacks": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# FULL SYSTEM HEALTH (moved from Blueprint/Mission Control 2026-02-04)
# ============================================================================

try:
    from tools.blueprint.blueprint_intelligence import get_system_health

    BLUEPRINT_HEALTH_AVAILABLE = True
except ImportError:
    BLUEPRINT_HEALTH_AVAILABLE = False


@system_operations_bp.route("/api/system-health-full")
@login_required
def api_system_health_full():
    """Full system health check (moved from Blueprint/Mission Control)."""
    if not BLUEPRINT_HEALTH_AVAILABLE:
        return jsonify({"error": "Health check not available"}), 500
    try:
        health = get_system_health()
        return jsonify(health)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# HEALTH CHECK
# ============================================================================


@system_operations_bp.route("/health")
def health_check():
    """Health check endpoint (no auth required)"""
    return jsonify({"healthy": True, "module": "system_operations"})


# Temporary registration until __init__.py is updated (Task 9)
from .process_routes import register_process_routes

register_process_routes(system_operations_bp, admin_required)
