"""
Device Fingerprint Routes
=========================
REST endpoints for device fingerprinting (nmap OS/service detection),
port change tracking, and Wake-on-LAN.
"""

import json
import logging
import re
import socket
import subprocess

from flask import jsonify
from flask_login import login_required

from database import get_db_cursor

logger = logging.getLogger(__name__)

IP_PATTERN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
MAC_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$")


def _validate_ip(ip):
    """Validate IP address format."""
    if not IP_PATTERN.match(ip):
        return False
    parts = ip.split(".")
    return all(0 <= int(p) <= 255 for p in parts)


def _validate_mac(mac):
    """Validate MAC address format."""
    return bool(MAC_PATTERN.match(mac))


def _parse_nmap_output(output):
    """Parse nmap -O -sV output into structured data."""
    os_info = None
    ports = []

    for line in output.splitlines():
        line = line.strip()

        # OS detection
        if line.startswith("OS details:"):
            os_info = line.replace("OS details:", "").strip()
        elif line.startswith("Running:") and os_info is None:
            os_info = line.replace("Running:", "").strip()

        # Open ports: e.g. "22/tcp  open  ssh  OpenSSH 8.9"
        port_match = re.match(r"(\d+)/tcp\s+open\s+(\S+)\s*(.*)", line)
        if port_match:
            ports.append(
                {
                    "port": int(port_match.group(1)),
                    "protocol": "tcp",
                    "service": port_match.group(2),
                    "version": port_match.group(3).strip() or None,
                }
            )

    return os_info, ports


def register_fingerprint_routes(bp, admin_required_decorator):
    """Register all device fingerprint endpoints."""

    @bp.route("/api/devices/fingerprint/<device_ip>")
    @login_required
    @admin_required_decorator
    def api_device_fingerprint(device_ip):
        """Return stored fingerprint for a device IP."""
        if not _validate_ip(device_ip):
            return jsonify({"success": False, "error": "Invalid IP address format"}), 400

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT id, device_ip, os_fingerprint, open_ports,
                           services, last_scanned
                    FROM device_fingerprints
                    WHERE device_ip = %s
                    """,
                    (device_ip,),
                )
                row = cur.fetchone()

            if not row:
                return jsonify({"success": True, "fingerprint": None, "message": "No fingerprint found for this IP"})

            fingerprint = {
                "id": row["id"],
                "device_ip": row["device_ip"],
                "os_fingerprint": row["os_fingerprint"],
                "open_ports": row["open_ports"],
                "services": row["services"],
                "last_scanned": row["last_scanned"].isoformat() if row["last_scanned"] else None,
            }

            return jsonify({"success": True, "fingerprint": fingerprint})
        except Exception as e:
            logger.error("Device fingerprint lookup error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/devices/fingerprint/<device_ip>/scan", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_device_fingerprint_scan(device_ip):
        """Trigger nmap scan for a device and store fingerprint."""
        if not _validate_ip(device_ip):
            return jsonify({"success": False, "error": "Invalid IP address format"}), 400

        try:
            result = subprocess.run(
                ["nmap", "-O", "-sV", "--host-timeout", "60", device_ip],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0 and not result.stdout:
                stderr = result.stderr.strip() if result.stderr else "Unknown error"
                return jsonify({"success": False, "error": f"nmap scan failed: {stderr}"}), 500

            os_info, ports = _parse_nmap_output(result.stdout)

            port_list = [p["port"] for p in ports]
            service_list = list({p["service"] for p in ports})

            with get_db_cursor(commit=True) as (conn, cur):
                # Upsert device fingerprint
                cur.execute(
                    """
                    INSERT INTO device_fingerprints
                        (device_ip, os_fingerprint, open_ports, services, last_scanned)
                    VALUES (%s, %s, %s::jsonb, %s::jsonb, NOW())
                    ON CONFLICT (device_ip) DO UPDATE SET
                        os_fingerprint = EXCLUDED.os_fingerprint,
                        open_ports = EXCLUDED.open_ports,
                        services = EXCLUDED.services,
                        last_scanned = EXCLUDED.last_scanned
                    RETURNING id, last_scanned
                    """,
                    (
                        device_ip,
                        os_info,
                        json.dumps(port_list),
                        json.dumps(service_list),
                    ),
                )
                fp_row = cur.fetchone()

                # Upsert each port into port_scan_history
                for p in ports:
                    cur.execute(
                        """
                        INSERT INTO port_scan_history
                            (device_ip, port, protocol, service, version, state, first_seen, last_seen)
                        VALUES (%s, %s, %s, %s, %s, 'open', NOW(), NOW())
                        ON CONFLICT (device_ip, port, protocol) DO UPDATE SET
                            service = EXCLUDED.service,
                            version = EXCLUDED.version,
                            state = 'open',
                            last_seen = NOW()
                        """,
                        (device_ip, p["port"], p["protocol"], p["service"], p["version"]),
                    )

            scan_result = {
                "id": fp_row["id"],
                "device_ip": device_ip,
                "os_fingerprint": os_info,
                "open_ports": port_list,
                "services": service_list,
                "ports_detail": ports,
                "last_scanned": fp_row["last_scanned"].isoformat() if fp_row["last_scanned"] else None,
            }

            return jsonify({"success": True, "result": scan_result})

        except FileNotFoundError:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "nmap is not installed. Install with: apt install nmap",
                    }
                ),
                503,
            )
        except subprocess.TimeoutExpired:
            return jsonify({"success": False, "error": "nmap scan timed out after 120 seconds"}), 504
        except Exception as e:
            logger.error("Device fingerprint scan error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/devices/port-changes")
    @login_required
    @admin_required_decorator
    def api_device_port_changes():
        """Find ports that appeared or disappeared in the last 7 days."""
        try:
            with get_db_cursor() as (conn, cur):
                # Newly discovered ports (first seen in last 7 days)
                cur.execute(
                    """
                    SELECT device_ip, port, protocol, service, state,
                           first_seen, last_seen
                    FROM port_scan_history
                    WHERE first_seen = last_seen
                      AND first_seen >= NOW() - INTERVAL '7 days'
                    ORDER BY first_seen DESC
                    """
                )
                new_ports = cur.fetchall()

                # Ports that disappeared (last_seen older than latest scan per device)
                cur.execute(
                    """
                    SELECT p.device_ip, p.port, p.protocol, p.service,
                           p.state, p.first_seen, p.last_seen
                    FROM port_scan_history p
                    INNER JOIN (
                        SELECT device_ip, MAX(last_seen) AS latest
                        FROM port_scan_history
                        GROUP BY device_ip
                    ) latest_scan ON p.device_ip = latest_scan.device_ip
                    WHERE p.last_seen < latest_scan.latest
                      AND p.last_seen >= NOW() - INTERVAL '7 days'
                    ORDER BY p.last_seen DESC
                    """
                )
                disappeared_ports = cur.fetchall()

            def _format_port(r):
                return {
                    "device_ip": r["device_ip"],
                    "port": r["port"],
                    "protocol": r["protocol"],
                    "service": r["service"],
                    "state": r["state"],
                    "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
                    "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
                }

            return jsonify(
                {
                    "success": True,
                    "new_ports": [_format_port(r) for r in new_ports],
                    "disappeared_ports": [_format_port(r) for r in disappeared_ports],
                    "new_count": len(new_ports),
                    "disappeared_count": len(disappeared_ports),
                }
            )
        except Exception as e:
            logger.error("Port changes error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/devices/wol/<mac_address>", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_device_wol(mac_address):
        """Send Wake-on-LAN magic packet to a device."""
        if not _validate_mac(mac_address):
            return jsonify({"success": False, "error": "Invalid MAC address format. Use XX:XX:XX:XX:XX:XX"}), 400

        try:
            # Normalize MAC to bytes
            mac_clean = mac_address.replace(":", "").replace("-", "")
            mac_bytes = bytes.fromhex(mac_clean)

            # Build magic packet: 6x 0xFF + 16x MAC
            magic_packet = b"\xff" * 6 + mac_bytes * 16

            # Send via UDP broadcast
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:
                sock.sendto(magic_packet, ("255.255.255.255", 9))
            finally:
                sock.close()

            logger.info("Wake-on-LAN packet sent to %s", mac_address)
            return jsonify({"success": True, "message": f"Wake-on-LAN packet sent to {mac_address}"})
        except Exception as e:
            logger.error("Wake-on-LAN error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500
