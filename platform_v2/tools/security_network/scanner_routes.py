"""
Scanner & Reconnaissance Routes
================================
REST endpoints for security scanning (nmap, nikto, nuclei, SSL, ZAP),
scan result management, SSL certificate monitoring, and Argus recon.
"""

import logging
import json as json_mod

from flask import jsonify, request
from flask_login import login_required, current_user
from database import get_db_cursor
from .security_alerts import create_security_alert
from .scan_input_validator import ScanInputError as _ScanInputError
from .scan_input_validator import validate_target as _validate_scan_target


def _scan_target_or_error(data):
    """Validate the request ``target`` for argument-injection + SSRF.

    Returns ``(target, None)`` on success, or ``(None, (response, status))``
    when the target is unsafe. Internal / sensitive targets (loopback, RFC1918,
    the 100.64.0.0/10 mesh, cloud metadata) require ``confirm_internal=true``.
    """
    raw = (data or {}).get("target", "")
    allow_internal = bool((data or {}).get("confirm_internal", False))
    try:
        return _validate_scan_target(raw, allow_internal=allow_internal), None
    except _ScanInputError as exc:
        msg = str(exc)
        internal = "internal/sensitive" in msg
        return None, (
            jsonify(
                {
                    "success": False,
                    "error": (
                        f"Internal target requires confirmation ({msg}). Set confirm_internal=true."
                        if internal
                        else f"Invalid target: {msg}"
                    ),
                    "requires_confirmation": internal,
                }
            ),
            400,
        )


logger = logging.getLogger(__name__)

# ============================================================================
# SCAN PROFILES — predefined configs per scanner
# ============================================================================
SCAN_PROFILES = {
    "nmap": {
        "quick": {"flags": "-F", "label": "Quick (Top 100 ports)", "timeout": 120},
        "standard": {"flags": "-sV --open", "label": "Standard (Service detection)", "timeout": 300},
        "full": {"flags": "-A -p-", "label": "Full (All ports + OS detect)", "timeout": 900},
    },
    "nikto": {
        "quick": {"flags": "-Tuning 1", "label": "Quick (Interesting files)", "timeout": 300},
        "standard": {"flags": "", "label": "Standard (Default tests)", "timeout": 600},
        "full": {"flags": "-Tuning 123456789abc", "label": "Full (All tests)", "timeout": 1200},
    },
    "nuclei": {
        "quick": {
            "templates": "cves,default-logins",
            "severity": "high,critical",
            "label": "Quick (Critical CVEs)",
            "timeout": 300,
        },
        "standard": {
            "templates": "cves,dast,http,ssl",
            "severity": "medium,high,critical",
            "label": "Standard (Common vulns)",
            "timeout": 600,
        },
        "full": {
            "templates": "cves,dast,dns,http,network,ssl,vulnerabilities,exposures,misconfiguration,default-logins",
            "severity": "low,medium,high,critical",
            "label": "Full (All templates)",
            "timeout": 1200,
        },
    },
    "ssl": {
        "quick": {"flags": "--fast", "label": "Quick (Fast check)", "timeout": 120},
        "standard": {"flags": "", "label": "Standard (Default analysis)", "timeout": 300},
        "full": {"flags": "--full", "label": "Full (All ciphers + vulns)", "timeout": 600},
    },
    "zap": {
        "quick": {"scan_type": "spider", "label": "Quick (Spider only)", "timeout": 120},
        "standard": {"scan_type": "active", "label": "Standard (Spider + Active)", "timeout": 600},
        "full": {"scan_type": "ajax", "label": "Full (Spider + Active + Ajax)", "timeout": 1200},
    },
}

SCANNER_META = {
    "nmap": {
        "icon": "network",
        "color": "#00ffff",
        "label": "Nmap",
        "subtitle": "Port Scanner",
        "description": "Discover open ports and running services on any host or network range",
        "container": "security_nmap",
    },
    "nikto": {
        "icon": "bug",
        "color": "#ffaa00",
        "label": "Nikto",
        "subtitle": "Web Vuln Scanner",
        "description": "Scan web servers for dangerous files, outdated software, and misconfigurations",
        "container": "security_nikto",
    },
    "nuclei": {
        "icon": "atom",
        "color": "#00ff41",
        "label": "Nuclei",
        "subtitle": "Template Scanner",
        "description": "Fast template-based vulnerability detection for CVEs, misconfigs, and exposures",
        "container": "security_nuclei",
    },
    "ssl": {
        "icon": "lock",
        "color": "#0ea5e9",
        "label": "SSL/TLS",
        "subtitle": "Certificate Check",
        "description": "Analyze SSL/TLS certificates, cipher suites, and protocol vulnerabilities",
        "container": "security_testssl",
    },
    "zap": {
        "icon": "zap",
        "color": "#ff6b6b",
        "label": "ZAP",
        "subtitle": "Web App Scanner",
        "description": "OWASP web application security testing with spider crawling and active scanning",
        "container": "security_zap",
    },
}

# Import stack integration (scanner_service)
try:
    from .stack_integration import scanner_service

    SCANNER_AVAILABLE = True
except ImportError:
    scanner_service = None
    SCANNER_AVAILABLE = False

# Import security service (SSL monitoring)
try:
    from .security_service import (
        check_ssl_certificate,
        add_ssl_monitor,
        get_ssl_monitors,
        refresh_ssl_monitors,
    )

    SSL_SERVICE_AVAILABLE = True
except ImportError:
    SSL_SERVICE_AVAILABLE = False

# Import Argus Reconnaissance service
try:
    from .argus_service import ArgusService

    argus_service = ArgusService()
    ARGUS_SERVICE_AVAILABLE = True
except ImportError:
    argus_service = None
    ARGUS_SERVICE_AVAILABLE = False


def register_scanner_routes(bp, admin_required_decorator):
    """Register all scanner, recon, and SSL monitoring endpoints."""

    # ========================================================================
    # SCANNER API ENDPOINTS
    # ========================================================================

    # ========================================================================
    # Shared: track scan in DB + log findings after completion
    # ========================================================================

    def _track_scan_start(scanner_type, target, profile="standard"):
        """Insert a running scan record and return its DB id"""
        try:
            import psycopg2.extras

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO security_recon_scans (module_name, target, options, status, triggered_by)
                    VALUES (%s, %s, %s, 'running', %s) RETURNING id
                """,
                    (
                        scanner_type,
                        target,
                        psycopg2.extras.Json({"profile": profile}),
                        getattr(current_user, "username", "user"),
                    ),
                )
                return cur.fetchone()[0]
        except Exception as e:
            logger.debug("Failed to track scan start: %s", e)
            return None

    def _track_scan_complete(scan_id, status="completed", results=None):
        """Mark a scan record as completed"""
        if scan_id is None:
            return
        try:
            import psycopg2.extras

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE security_recon_scans
                    SET status = %s, results = %s, completed_at = NOW()
                    WHERE id = %s
                """,
                    (status, psycopg2.extras.Json(results) if results else None, scan_id),
                )
        except Exception as e:
            logger.debug("Failed to track scan complete: %s", e)

    def _store_findings(scanner_type, target, scan_id, findings_list):
        """Insert parsed findings into security_scan_results"""
        if not findings_list:
            return
        try:
            import psycopg2.extras

            with get_db_cursor(commit=True) as (conn, cur):
                for f in findings_list[:500]:  # Cap at 500 findings per scan
                    cur.execute(
                        """
                        INSERT INTO security_scan_results (scanner, target, severity, finding, details, scan_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                        (
                            scanner_type,
                            target,
                            f.get("severity", "info"),
                            f.get("finding", ""),
                            psycopg2.extras.Json(f.get("details", {})),
                            scan_id,
                        ),
                    )
        except Exception as e:
            logger.debug("Failed to store findings: %s", e)

    def _parse_nmap_findings(result):
        """Extract findings from nmap scan result"""
        findings = []
        output = result.get("output", "") if isinstance(result, dict) else ""
        for line in output.split("\n"):
            if "/tcp" in line and "open" in line:
                parts = line.strip().split()
                port = parts[0] if parts else ""
                service = parts[2] if len(parts) > 2 else ""
                version = " ".join(parts[3:]) if len(parts) > 3 else ""
                findings.append(
                    {
                        "severity": "info",
                        "finding": f"Open port {port} ({service})",
                        "details": {"port": port, "service": service, "version": version},
                    }
                )
        return findings

    def _parse_nuclei_findings(result):
        """Extract findings from nuclei scan result"""
        findings = []
        output = result.get("output", "") if isinstance(result, dict) else ""
        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            try:
                item = json_mod.loads(line)
                findings.append(
                    {
                        "severity": item.get("info", {}).get("severity", "info"),
                        "finding": item.get("info", {}).get("name", item.get("template-id", "Unknown")),
                        "details": {
                            "template": item.get("template-id"),
                            "matched": item.get("matched-at"),
                            "type": item.get("type"),
                        },
                    }
                )
            except json_mod.JSONDecodeError:
                continue
        return findings

    # ========================================================================
    # SCANNER SCAN ENDPOINTS (with profile support + DB tracking)
    # ========================================================================

    @bp.route("/api/scanner/nmap", methods=["POST"])
    @login_required
    @admin_required_decorator
    def run_nmap_scan():
        """Run nmap scan on target"""
        if not SCANNER_AVAILABLE:
            return jsonify({"success": False, "error": "Scanner not available"}), 503

        data = request.get_json() or {}
        profile = data.get("profile", data.get("scan_type", "quick"))

        # Argument-injection + SSRF guard. Internal targets need confirm_internal.
        target, err = _scan_target_or_error(data)
        if err:
            resp, status = err
            return resp, status

        scan_id = _track_scan_start("nmap", target, profile)

        try:
            # Map profile to scan_type for backward compat
            scan_type = profile if profile in ("quick", "full", "stealth") else "quick"
            result = scanner_service.run_nmap_scan(target, scan_type)

            findings = _parse_nmap_findings(result)
            _track_scan_complete(scan_id, "completed", result)
            _store_findings("nmap", target, scan_id, findings)

            # Audit log
            try:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """INSERT INTO audit_log (action, user_id, details)
                           VALUES ('security_scan', %s, %s)""",
                        (current_user.id, {"type": "nmap", "target": target, "profile": profile}),
                    )
            except Exception as e:
                logger.debug("Failed to log security scan: %s", e)

            create_security_alert(
                "scan_result",
                f"Nmap scan completed: {target}",
                f"Nmap {profile} scan on {target} completed. {len(findings)} findings.",
                priority="normal",
                telegram=False,
            )

            result["scan_id"] = scan_id
            result["findings_count"] = len(findings)
            return jsonify(result)
        except Exception as e:
            _track_scan_complete(scan_id, "failed", {"error": str(e)})
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/scanner/nikto", methods=["POST"])
    @login_required
    @admin_required_decorator
    def run_nikto_scan():
        """Run nikto web vulnerability scan"""
        if not SCANNER_AVAILABLE:
            return jsonify({"success": False, "error": "Scanner not available"}), 503

        data = request.get_json() or {}
        profile = data.get("profile", "standard")

        target, err = _scan_target_or_error(data)
        if err:
            resp, status = err
            return resp, status

        scan_id = _track_scan_start("nikto", target, profile)

        try:
            result = scanner_service.run_nikto_scan(target)

            # Parse nikto findings from output
            findings = []
            output = result.get("output", "") if isinstance(result, dict) else ""
            for line in output.split("\n"):
                line = line.strip()
                if line.startswith("+") and ":" in line:
                    findings.append({"severity": "medium", "finding": line.lstrip("+ "), "details": {}})

            _track_scan_complete(scan_id, "completed", result)
            _store_findings("nikto", target, scan_id, findings)

            create_security_alert(
                "scan_result",
                f"Nikto scan completed: {target}",
                f"Nikto scan on {target} completed. {len(findings)} findings.",
                priority="normal",
                telegram=False,
            )

            result["scan_id"] = scan_id
            result["findings_count"] = len(findings)
            return jsonify(result)
        except Exception as e:
            _track_scan_complete(scan_id, "failed", {"error": str(e)})
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/scanner/nuclei", methods=["POST"])
    @login_required
    @admin_required_decorator
    def run_nuclei_scan():
        """Run nuclei vulnerability scan"""
        if not SCANNER_AVAILABLE:
            return jsonify({"success": False, "error": "Scanner not available"}), 503

        data = request.get_json() or {}
        profile = data.get("profile", "standard")
        templates = data.get("templates", SCAN_PROFILES["nuclei"].get(profile, {}).get("templates", "cves"))

        target, err = _scan_target_or_error(data)
        if err:
            resp, status = err
            return resp, status

        scan_id = _track_scan_start("nuclei", target, profile)

        try:
            result = scanner_service.run_nuclei_scan(target, templates)

            findings = _parse_nuclei_findings(result)
            _track_scan_complete(scan_id, "completed", result)
            _store_findings("nuclei", target, scan_id, findings)

            result["scan_id"] = scan_id
            result["findings_count"] = len(findings)
            return jsonify(result)
        except Exception as e:
            _track_scan_complete(scan_id, "failed", {"error": str(e)})
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/scanner/ssl", methods=["POST"])
    @login_required
    @admin_required_decorator
    def run_ssl_scan():
        """Run SSL/TLS analysis"""
        if not SCANNER_AVAILABLE:
            return jsonify({"success": False, "error": "Scanner not available"}), 503

        data = request.get_json() or {}
        profile = data.get("profile", "standard")

        domain, err = _scan_target_or_error(
            {"target": data.get("domain", ""), "confirm_internal": data.get("confirm_internal", False)}
        )
        if err:
            resp, status = err
            return resp, status

        scan_id = _track_scan_start("ssl", domain, profile)

        try:
            result = scanner_service.run_ssl_scan(domain)

            findings = []
            if isinstance(result, dict) and result.get("output"):
                findings.append(
                    {
                        "severity": "info",
                        "finding": f"SSL/TLS analysis for {domain}",
                        "details": {"output_length": len(result.get("output", ""))},
                    }
                )

            _track_scan_complete(scan_id, "completed", result)
            _store_findings("ssl", domain, scan_id, findings)

            result["scan_id"] = scan_id
            result["findings_count"] = len(findings)
            return jsonify(result)
        except Exception as e:
            _track_scan_complete(scan_id, "failed", {"error": str(e)})
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/scanner/zap", methods=["POST"])
    @login_required
    @admin_required_decorator
    def run_zap_scan():
        """Start ZAP web application scan"""
        if not SCANNER_AVAILABLE:
            return jsonify({"success": False, "error": "Scanner not available"}), 503

        data = request.get_json() or {}
        profile = data.get("profile", "quick")
        scan_type = data.get("scan_type", SCAN_PROFILES["zap"].get(profile, {}).get("scan_type", "spider"))

        target, err = _scan_target_or_error(data)
        if err:
            resp, status = err
            return resp, status

        scan_id = _track_scan_start("zap", target, profile)

        try:
            result = scanner_service.start_zap_scan(target, scan_type)

            _track_scan_complete(scan_id, "completed", result)

            result["scan_id"] = scan_id
            return jsonify(result)
        except Exception as e:
            _track_scan_complete(scan_id, "failed", {"error": str(e)})
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/scanner/status")
    @login_required
    @admin_required_decorator
    def scanner_status():
        """Get scanner service status"""
        if not SCANNER_AVAILABLE:
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
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # SCANNER SUMMARY, PROFILES, RUNNING, FINDINGS
    # ========================================================================

    @bp.route("/api/scanner/profiles")
    @login_required
    @admin_required_decorator
    def scanner_profiles():
        """Get available scan profiles for all scanners"""
        return jsonify({"success": True, "profiles": SCAN_PROFILES, "scanners": SCANNER_META})

    @bp.route("/api/scanner/summary")
    @login_required
    @admin_required_decorator
    def scanner_summary():
        """Get per-scanner summary: container status, last scan, finding counts"""
        import subprocess

        summaries = {}
        for scanner_id, meta in SCANNER_META.items():
            container = meta["container"]
            # Check container status
            try:
                result = subprocess.run(
                    ["docker", "inspect", "--format", "{{.State.Status}}", container],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                container_status = result.stdout.strip() if result.returncode == 0 else "not_found"
            except Exception:
                container_status = "unknown"

            # Last scan from DB (recon_scans) + filesystem
            last_scan = None
            try:
                with get_db_cursor() as (conn, cur):
                    # Check DB scans
                    cur.execute(
                        """
                        SELECT id, target, status, started_at, completed_at
                        FROM security_recon_scans
                        WHERE module_name LIKE %s
                        ORDER BY started_at DESC LIMIT 1
                    """,
                        (f"{scanner_id}%",),
                    )
                    row = cur.fetchone()
                    if row:
                        last_scan = {
                            "id": row[0],
                            "target": row[1],
                            "status": row[2],
                            "started_at": row[3].isoformat() if row[3] else None,
                            "completed_at": row[4].isoformat() if row[4] else None,
                        }

                    # Finding counts from security_scan_results
                    cur.execute(
                        """
                        SELECT severity, COUNT(*) FROM security_scan_results
                        WHERE scanner = %s
                        GROUP BY severity
                    """,
                        (scanner_id,),
                    )
                    findings = {r[0]: r[1] for r in cur.fetchall()}
            except Exception as e:
                logger.debug("Scanner summary DB error: %s", e)
                findings = {}

            # If no DB scan, check filesystem
            if not last_scan:
                import os
                import glob as globmod

                scans_dir = os.path.join(os.getenv("ARCHIE_BASE_DIR", "/mnt/archie_brain"), "security_scans")
                files = sorted(
                    globmod.glob(os.path.join(scans_dir, f"{scanner_id}_*")), key=os.path.getmtime, reverse=True
                )
                if files:
                    from datetime import datetime

                    f = files[0]
                    last_scan = {
                        "target": os.path.basename(f).replace(f"{scanner_id}_", "").rsplit("_", 1)[0],
                        "status": "completed",
                        "started_at": datetime.fromtimestamp(os.path.getmtime(f)).isoformat(),
                        "source": "file",
                    }

            summaries[scanner_id] = {
                **meta,
                "container_status": container_status,
                "last_scan": last_scan,
                "findings": findings,
                "total_findings": sum(findings.values()),
                "profiles": SCAN_PROFILES.get(scanner_id, {}),
            }

        return jsonify({"success": True, "scanners": summaries})

    @bp.route("/api/scanner/running")
    @login_required
    @admin_required_decorator
    def scanner_running():
        """Get currently running scans with elapsed time"""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT id, module_name, target, started_at,
                           EXTRACT(EPOCH FROM (NOW() - started_at))::int AS elapsed_seconds
                    FROM security_recon_scans
                    WHERE status = 'running'
                    ORDER BY started_at DESC
                """
                )
                running = []
                for row in cur.fetchall():
                    running.append(
                        {
                            "id": row[0],
                            "scanner": row[1],
                            "target": row[2],
                            "started_at": row[3].isoformat() if row[3] else None,
                            "elapsed_seconds": row[4] or 0,
                        }
                    )
            return jsonify({"success": True, "running": running})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/scanner/findings")
    @login_required
    @admin_required_decorator
    def scanner_findings():
        """Get scan findings with optional filters"""
        scanner = request.args.get("scanner", "")
        severity = request.args.get("severity", "")
        limit = request.args.get("limit", 100, type=int)

        try:
            with get_db_cursor() as (conn, cur):
                query = "SELECT id, scanner, target, severity, finding, details, scan_id, created_at FROM security_scan_results WHERE 1=1"
                params = []
                if scanner:
                    query += " AND scanner = %s"
                    params.append(scanner)
                if severity:
                    query += " AND severity = %s"
                    params.append(severity)
                query += " ORDER BY created_at DESC LIMIT %s"
                params.append(limit)

                cur.execute(query, params)
                findings = []
                for row in cur.fetchall():
                    findings.append(
                        {
                            "id": row[0],
                            "scanner": row[1],
                            "target": row[2],
                            "severity": row[3],
                            "finding": row[4],
                            "details": row[5],
                            "scan_id": row[6],
                            "created_at": row[7].isoformat() if row[7] else None,
                        }
                    )

            return jsonify({"success": True, "findings": findings, "count": len(findings)})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # SCAN RESULTS API
    # ========================================================================

    @bp.route("/api/scans")
    @login_required
    @admin_required_decorator
    def list_scans():
        """List all scan results"""
        import os
        import glob

        scans_dir = os.path.join(os.getenv("ARCHIE_BASE_DIR", "/mnt/archie_brain"), "security_scans")
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
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/scans/<filename>")
    @login_required
    @admin_required_decorator
    def get_scan_result(filename):
        """Get scan result contents"""
        import os

        scans_dir = os.path.join(os.getenv("ARCHIE_BASE_DIR", "/mnt/archie_brain"), "security_scans")

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
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # SSL CERTIFICATE MONITORING
    # ========================================================================

    @bp.route("/api/ssl/check", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_check_ssl():
        """Check SSL certificate for a domain"""
        if not SSL_SERVICE_AVAILABLE:
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
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/ssl/monitors")
    @login_required
    @admin_required_decorator
    def api_ssl_monitors():
        """Get SSL monitors"""
        if not SSL_SERVICE_AVAILABLE:
            return (
                jsonify({"success": False, "error": "Security service not available"}),
                503,
            )

        try:
            monitors = get_ssl_monitors()
            return jsonify({"success": True, "monitors": monitors})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/ssl/monitors", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_add_ssl_monitor():
        """Add SSL monitor for a domain"""
        if not SSL_SERVICE_AVAILABLE:
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
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/ssl/refresh", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_refresh_ssl_monitors():
        """Refresh all SSL monitors"""
        if not SSL_SERVICE_AVAILABLE:
            return (
                jsonify({"success": False, "error": "Security service not available"}),
                503,
            )

        try:
            result = refresh_ssl_monitors()
            return jsonify(result)
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # RECONNAISSANCE - ARGUS
    # ========================================================================

    @bp.route("/api/recon/modules")
    @login_required
    @admin_required_decorator
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
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/recon/scan", methods=["POST"])
    @login_required
    @admin_required_decorator
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
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/recon/scan/<int:scan_id>")
    @login_required
    @admin_required_decorator
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
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/recon/history")
    @login_required
    @admin_required_decorator
    def api_recon_history():
        """Get reconnaissance scan history"""
        if not ARGUS_SERVICE_AVAILABLE or not argus_service:
            return jsonify({"success": False, "error": "Argus service not available"}), 503

        limit = request.args.get("limit", 50, type=int)

        try:
            history = argus_service.get_scan_history(limit)
            return jsonify({"success": True, "history": history})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/recon/scan/<int:scan_id>", methods=["DELETE"])
    @login_required
    @admin_required_decorator
    def api_recon_delete_scan(scan_id):
        """Delete a reconnaissance scan"""
        if not ARGUS_SERVICE_AVAILABLE or not argus_service:
            return jsonify({"success": False, "error": "Argus service not available"}), 503

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("DELETE FROM security_recon_scans WHERE id = %s", (scan_id,))
                affected = cur.rowcount

                if affected == 0:
                    return jsonify({"success": False, "error": "Scan not found"}), 404
                return jsonify({"success": True, "message": f"Scan {scan_id} deleted"})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # SCAN CAMPAIGNS — batch scans under a client engagement
    # ========================================================================

    @bp.route("/api/scanner/campaign", methods=["POST"])
    @login_required
    @admin_required_decorator
    def create_campaign():
        """Create a scan campaign: batch-launch multiple scanners for a client"""
        import threading

        data = request.get_json() or {}
        client_name = data.get("client_name", "").strip()
        target = data.get("target", "").strip()
        profile = data.get("profile", "standard")
        scanners = data.get("scanners", [])
        recon_modules = data.get("recon_modules", [])

        if not client_name:
            return jsonify({"success": False, "error": "Client name is required"}), 400
        if not target:
            return jsonify({"success": False, "error": "Target is required"}), 400
        # Argument-injection + SSRF guard (internal targets need confirm_internal).
        target, err = _scan_target_or_error(data)
        if err:
            resp, status = err
            return resp, status
        if not scanners and not recon_modules:
            return jsonify({"success": False, "error": "Select at least one scanner or module"}), 400

        all_tools = list(scanners) + list(recon_modules)
        triggered_by = getattr(current_user, "username", "user")

        try:
            import psycopg2.extras

            # Create campaign record
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO scan_campaigns (client_name, target, profile, scanners, status, created_by)
                       VALUES (%s, %s, %s, %s, 'running', %s) RETURNING id""",
                    (client_name, target, profile, psycopg2.extras.Json(all_tools), triggered_by),
                )
                campaign_id = cur.fetchone()[0]

            # Launch each scanner in background threads
            scan_ids = []

            def _run_vuln_scan(scanner_type, camp_id, tgt, prof):
                """Run a vulnerability scanner and link to campaign"""
                try:
                    scan_id = None
                    with get_db_cursor(commit=True) as (conn, cur):
                        cur.execute(
                            """INSERT INTO security_recon_scans
                               (module_name, target, options, status, triggered_by, campaign_id)
                               VALUES (%s, %s, %s, 'running', %s, %s) RETURNING id""",
                            (
                                scanner_type,
                                tgt,
                                psycopg2.extras.Json({"profile": prof, "campaign": camp_id}),
                                triggered_by,
                                camp_id,
                            ),
                        )
                        scan_id = cur.fetchone()[0]

                    # Execute the scan
                    result = None
                    if scanner_type == "nmap" and SCANNER_AVAILABLE:
                        st = "quick" if prof == "quick" else ("full" if prof == "full" else "quick")
                        result = scanner_service.run_nmap_scan(tgt, st)
                    elif scanner_type == "nikto" and SCANNER_AVAILABLE:
                        result = scanner_service.run_nikto_scan(tgt)
                    elif scanner_type == "nuclei" and SCANNER_AVAILABLE:
                        templates = SCAN_PROFILES.get("nuclei", {}).get(prof, {}).get("templates", "cves")
                        result = scanner_service.run_nuclei_scan(tgt, templates)
                    elif scanner_type == "ssl" and SCANNER_AVAILABLE:
                        result = scanner_service.run_ssl_scan(tgt)
                    elif scanner_type == "zap" and SCANNER_AVAILABLE:
                        scan_t = SCAN_PROFILES.get("zap", {}).get(prof, {}).get("scan_type", "spider")
                        result = scanner_service.start_zap_scan(tgt, scan_t)

                    # Mark complete
                    with get_db_cursor(commit=True) as (conn, cur):
                        cur.execute(
                            """UPDATE security_recon_scans
                               SET status = 'completed', results = %s, completed_at = NOW()
                               WHERE id = %s""",
                            (psycopg2.extras.Json(result) if result else None, scan_id),
                        )

                    # Parse and store findings
                    if result and scanner_type == "nmap":
                        findings = _parse_nmap_findings(result)
                        _store_findings("nmap", tgt, scan_id, findings)
                    elif result and scanner_type == "nuclei":
                        findings = _parse_nuclei_findings(result)
                        _store_findings("nuclei", tgt, scan_id, findings)

                except Exception as e:
                    logger.exception("Campaign scan %s failed: %s", scanner_type, e)
                    if scan_id:
                        try:
                            with get_db_cursor(commit=True) as (conn, cur):
                                cur.execute(
                                    """UPDATE security_recon_scans
                                       SET status = 'failed', completed_at = NOW()
                                       WHERE id = %s""",
                                    (scan_id,),
                                )
                        except Exception:
                            pass

            def _run_recon_scan(module_name, camp_id, tgt):
                """Run a recon module and link to campaign"""
                try:
                    if ARGUS_SERVICE_AVAILABLE and argus_service:
                        scan_id = argus_service.start_scan(module_name, tgt, {}, triggered_by)
                        if scan_id:
                            with get_db_cursor(commit=True) as (conn, cur):
                                cur.execute(
                                    "UPDATE security_recon_scans SET campaign_id = %s WHERE id = %s",
                                    (camp_id, scan_id),
                                )
                except Exception as e:
                    logger.exception("Campaign recon %s failed: %s", module_name, e)

            # Launch all scans in parallel threads
            threads = []
            for s in scanners:
                if s in SCANNER_META:
                    t = threading.Thread(target=_run_vuln_scan, args=(s, campaign_id, target, profile), daemon=True)
                    t.start()
                    threads.append(t)

            for m in recon_modules:
                t = threading.Thread(target=_run_recon_scan, args=(m, campaign_id, target), daemon=True)
                t.start()
                threads.append(t)

            # Monitor completion in background
            def _monitor_campaign(camp_id, thread_list):
                for t in thread_list:
                    t.join(timeout=1200)
                try:
                    with get_db_cursor(commit=True) as (conn, cur):
                        cur.execute(
                            "UPDATE scan_campaigns SET status = 'completed', completed_at = NOW() WHERE id = %s",
                            (camp_id,),
                        )
                        # Collect scan_ids
                        cur.execute(
                            "SELECT array_agg(id) FROM security_recon_scans WHERE campaign_id = %s",
                            (camp_id,),
                        )
                        row = cur.fetchone()
                        if row and row[0]:
                            import psycopg2.extras

                            cur.execute(
                                "UPDATE scan_campaigns SET scan_ids = %s WHERE id = %s",
                                (psycopg2.extras.Json(list(row[0])), camp_id),
                            )
                except Exception as e:
                    logger.debug("Campaign monitor error: %s", e)

            mon = threading.Thread(target=_monitor_campaign, args=(campaign_id, threads), daemon=True)
            mon.start()

            return jsonify(
                {
                    "success": True,
                    "campaign_id": campaign_id,
                    "message": f"Campaign started: {len(scanners)} scanners + {len(recon_modules)} recon modules",
                    "scanners_launched": scanners,
                    "recon_launched": recon_modules,
                }
            )

        except Exception as e:
            logger.exception("Campaign creation error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/scanner/campaign/<int:campaign_id>")
    @login_required
    @admin_required_decorator
    def get_campaign(campaign_id):
        """Get campaign status and consolidated results"""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, client_name, target, profile, scanners, status,
                              scan_ids, created_by, created_at, completed_at
                       FROM scan_campaigns WHERE id = %s""",
                    (campaign_id,),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"success": False, "error": "Campaign not found"}), 404

                campaign = {
                    "id": row[0],
                    "client_name": row[1],
                    "target": row[2],
                    "profile": row[3],
                    "scanners": row[4],
                    "status": row[5],
                    "scan_ids": row[6],
                    "created_by": row[7],
                    "created_at": row[8].isoformat() if row[8] else None,
                    "completed_at": row[9].isoformat() if row[9] else None,
                }

                # Get all scans for this campaign
                cur.execute(
                    """SELECT id, module_name, target, status, results,
                              started_at, completed_at
                       FROM security_recon_scans WHERE campaign_id = %s
                       ORDER BY started_at""",
                    (campaign_id,),
                )
                scans = []
                for r in cur.fetchall():
                    scans.append(
                        {
                            "id": r[0],
                            "scanner": r[1],
                            "target": r[2],
                            "status": r[3],
                            "results": r[4],
                            "started_at": r[5].isoformat() if r[5] else None,
                            "completed_at": r[6].isoformat() if r[6] else None,
                        }
                    )

                # Get findings for this campaign
                cur.execute(
                    """SELECT sr.scanner, sr.severity, sr.finding, sr.target, sr.details
                       FROM security_scan_results sr
                       JOIN security_recon_scans srs ON sr.scan_id = srs.id
                       WHERE srs.campaign_id = %s
                       ORDER BY CASE sr.severity
                           WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                           WHEN 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5 END""",
                    (campaign_id,),
                )
                findings = []
                for r in cur.fetchall():
                    findings.append(
                        {
                            "scanner": r[0],
                            "severity": r[1],
                            "finding": r[2],
                            "target": r[3],
                            "details": r[4],
                        }
                    )

                return jsonify(
                    {
                        "success": True,
                        "campaign": campaign,
                        "scans": scans,
                        "findings": findings,
                    }
                )
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/scanner/campaigns")
    @login_required
    @admin_required_decorator
    def list_campaigns():
        """List all scan campaigns"""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, client_name, target, profile, scanners, status,
                              created_at, completed_at
                       FROM scan_campaigns ORDER BY created_at DESC LIMIT 50"""
                )
                campaigns = []
                for r in cur.fetchall():
                    campaigns.append(
                        {
                            "id": r[0],
                            "client_name": r[1],
                            "target": r[2],
                            "profile": r[3],
                            "scanners": r[4],
                            "status": r[5],
                            "created_at": r[6].isoformat() if r[6] else None,
                            "completed_at": r[7].isoformat() if r[7] else None,
                        }
                    )
                return jsonify({"success": True, "campaigns": campaigns})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500
