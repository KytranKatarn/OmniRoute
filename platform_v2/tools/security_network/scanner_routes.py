"""
Scanner & Reconnaissance Routes
================================
REST endpoints for security scanning (nmap, nikto, nuclei, SSL, ZAP),
scan result management, SSL certificate monitoring, and Argus recon.
"""

import logging

from flask import jsonify, request
from flask_login import login_required, current_user
from database import get_db_cursor
from .security_alerts import create_security_alert

logger = logging.getLogger(__name__)

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

    @bp.route("/api/scanner/nmap", methods=["POST"])
    @login_required
    @admin_required_decorator
    def run_nmap_scan():
        """Run nmap scan on target"""
        if not SCANNER_AVAILABLE:
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
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """INSERT INTO audit_log (action, user_id, details)
                           VALUES ('security_scan', %s, %s)""",
                        (
                            current_user.id,
                            {"type": "nmap", "target": target, "scan_type": scan_type},
                        ),
                    )
            except Exception as e:
                logger.debug("Failed to log security scan to audit_log: %s", e)

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
        target = data.get("target", "")
        templates = data.get("templates", "cves")

        if not target:
            return jsonify({"success": False, "error": "Target is required"}), 400

        try:
            result = scanner_service.run_nuclei_scan(target, templates)
            return jsonify(result)
        except Exception as e:
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
        domain = data.get("domain", "")

        if not domain:
            return jsonify({"success": False, "error": "Domain is required"}), 400

        try:
            result = scanner_service.run_ssl_scan(domain)
            return jsonify(result)
        except Exception as e:
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
        target = data.get("target", "")
        scan_type = data.get("scan_type", "spider")

        if not target:
            return jsonify({"success": False, "error": "Target is required"}), 400

        try:
            result = scanner_service.start_zap_scan(target, scan_type)
            return jsonify(result)
        except Exception as e:
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
    # SCAN RESULTS API
    # ========================================================================

    @bp.route("/api/scans")
    @login_required
    @admin_required_decorator
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
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/scans/<filename>")
    @login_required
    @admin_required_decorator
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
