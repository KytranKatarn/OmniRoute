"""
Domain Routes
=============
REST endpoints for multi-domain CRUD (org_domains + managed_dns_records),
domain overview, quick-setup, and Nginx configuration management via
host_command_client.
"""

import logging

from flask import jsonify, request
from flask_login import login_required, current_user
from database import get_db_cursor

logger = logging.getLogger(__name__)

# Import Hostinger DNS service (needed for domain overview and quick-setup)
try:
    from .hostinger_service import HostingerService

    _hostinger_service = HostingerService()
    _HOSTINGER_AVAILABLE = _hostinger_service.available
except ImportError:
    _hostinger_service = None
    _HOSTINGER_AVAILABLE = False


def register_domain_npm_routes(bp, admin_required_decorator):
    """Register all domain and nginx config endpoints."""

    @bp.route("/api/domains/certificates")
    @login_required
    @admin_required_decorator
    def api_domains_certificates():
        """SSL certificates for monitored domains (Domains > Certificates subtab).

        The UI (loadDomainCertificates) fetched a route that never existed (404).
        Surface the tracked security_ssl_monitors rows in the shape it expects.
        """
        try:
            from .security_service import get_ssl_monitors

            certs = []
            for m in get_ssl_monitors() or []:
                exp = m.get("valid_until")
                certs.append(
                    {
                        "domain_names": [m.get("domain")] if m.get("domain") else [],
                        "provider": m.get("issuer") or "custom",
                        "created_on": None,
                        "expires_on": exp.isoformat() if hasattr(exp, "isoformat") else exp,
                        "grade": m.get("grade"),
                        "days_left": m.get("days_until_expiry"),
                    }
                )
            return jsonify({"success": True, "certificates": certs})
        except Exception as exc:
            logger.error("Failed to load domain certificates: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================================================
    # DOMAIN OVERVIEW
    # ========================================================================

    @bp.route("/api/domains/overview")
    @login_required
    @admin_required_decorator
    def api_domains_overview():
        """Combined domain overview: DNS records + public IP + managed servers"""
        result = {"dns_records": [], "public_ip": None}

        # Get public IP via Hostinger service
        if _HOSTINGER_AVAILABLE and _hostinger_service:
            try:
                result["public_ip"] = _hostinger_service.get_public_ip()
            except Exception as e:
                logger.debug("Failed to get public IP: %s", e)

        # Get DNS records
        if _HOSTINGER_AVAILABLE and _hostinger_service:
            try:
                records = _hostinger_service.get_dns_records()
                if isinstance(records, list):
                    result["dns_records"] = records
            except Exception as e:
                logger.debug("Failed to get DNS records for domain overview: %s", e)

        # Get managed servers (hub + remote nodes)
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT node_name, hostname, public_ip, vpn_ip, status,
                              gpu_available, description
                       FROM remote_nodes ORDER BY id"""
                )
                result["servers"] = [dict(r) for r in cur.fetchall()]

                # IP change history
                cur.execute(
                    """SELECT ip_address, detected_at
                       FROM org_ip_history ORDER BY detected_at DESC LIMIT 10"""
                )
                result["ip_history"] = [
                    {
                        "ip": r["ip_address"],
                        "detected_at": r["detected_at"].isoformat() if r["detected_at"] else None,
                    }
                    for r in cur.fetchall()
                ]
        except Exception as e:
            logger.debug("Failed to get servers/IP history: %s", e)

        return jsonify({"success": True, **result})

    @bp.route("/api/domains/quick-setup", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_domains_quick_setup():
        """One-click subdomain setup: create a DNS A record pointing at the public IP."""
        if not _HOSTINGER_AVAILABLE or not _hostinger_service:
            return jsonify({"success": False, "error": "Hostinger service not available"}), 503

        data = request.get_json() or {}
        subdomain = data.get("subdomain", "").strip()

        if not subdomain:
            return jsonify({"success": False, "error": "Subdomain is required"}), 400

        root_domain = _hostinger_service.domain
        full_domain = f"{subdomain}.{root_domain}"
        steps = {"dns": None}

        # Step 1: Get public IP
        public_ip = _hostinger_service.get_public_ip()
        if not public_ip:
            return jsonify({"success": False, "error": "Could not determine public IP"}), 500

        # Step 2: Create DNS A record
        try:
            dns_result = _hostinger_service.add_dns_record(
                record_type="A",
                name=subdomain,
                value=public_ip,
                ttl=3600,
            )
            if isinstance(dns_result, dict) and "error" in dns_result:
                steps["dns"] = {"success": False, "error": dns_result["error"]}
                return (
                    jsonify({"success": False, "error": f"DNS failed: {dns_result['error']}", "steps": steps}),
                    500,
                )
            steps["dns"] = {"success": True, "record": f"{subdomain} A {public_ip}"}
        except Exception as e:
            steps["dns"] = {"success": False, "error": "DNS operation failed"}
            return jsonify({"success": False, "error": "DNS failed", "steps": steps}), 500

        return jsonify(
            {
                "success": True,
                "message": f"Subdomain {full_domain} created successfully",
                "domain": full_domain,
                "steps": steps,
            }
        )

    # ========================================================================
    # MULTI-DOMAIN MANAGEMENT (org_domains CRUD + per-domain DNS records)
    # ========================================================================

    @bp.route("/api/domains")
    @login_required
    @admin_required_decorator
    def api_domains_list():
        """List all managed domains for the current user."""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, org_id, domain, subdomain, root_domain, target_module,
                              target_port, ssl_status, dns_status, dns_provider,
                              registrar, nameservers, notes, created_at, updated_at, verified_at
                       FROM org_domains
                       WHERE user_id = %s
                       ORDER BY root_domain, subdomain""",
                    (current_user.id,),
                )
                rows = cur.fetchall()
                domains = []
                for r in rows:
                    d = dict(r)  # RealDictCursor rows; dict(zip(cols,r)) yielded {col: col}
                    d["created_at"] = str(d["created_at"]) if d["created_at"] else None
                    d["updated_at"] = str(d["updated_at"]) if d["updated_at"] else None
                    d["verified_at"] = str(d["verified_at"]) if d["verified_at"] else None
                    domains.append(d)
            return jsonify({"success": True, "domains": domains})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/domains", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_domains_create():
        """Add a new managed domain."""
        data = request.get_json() or {}
        domain = data.get("domain", "").strip().lower()
        if not domain:
            return jsonify({"success": False, "error": "Domain is required"}), 400

        registrar = data.get("registrar", "").strip() or None
        nameservers = data.get("nameservers") or None  # expect list
        if isinstance(nameservers, str):
            nameservers = [ns.strip() for ns in nameservers.split(",") if ns.strip()]
        dns_provider = data.get("dns_provider", "manual").strip()
        if dns_provider not in ("hostinger", "cloudflare", "manual"):
            return (
                jsonify({"success": False, "error": "dns_provider must be hostinger, cloudflare, or manual"}),
                400,
            )
        notes = data.get("notes", "").strip() or None

        # Parse subdomain/root_domain from the domain string
        parts = domain.split(".")
        if len(parts) > 2:
            subdomain = ".".join(parts[:-2])
            root_domain = ".".join(parts[-2:])
        else:
            subdomain = None
            root_domain = domain

        target_module = data.get("target_module", "").strip() or None
        target_port = data.get("target_port", 3000)

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO org_domains
                       (org_id, user_id, domain, subdomain, root_domain, target_module,
                        target_port, dns_provider, registrar, nameservers, notes, created_at, updated_at)
                       VALUES (
                           (SELECT COALESCE(
                               (SELECT org_id FROM org_members WHERE user_id = %s LIMIT 1),
                               1
                           )),
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                       )
                       ON CONFLICT (domain) DO NOTHING
                       RETURNING id""",
                    (
                        current_user.id,
                        current_user.id,
                        domain,
                        subdomain,
                        root_domain,
                        target_module,
                        int(target_port),
                        dns_provider,
                        registrar,
                        nameservers,
                        notes,
                    ),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"success": False, "error": "Domain already exists"}), 409
                domain_id = row[0]
            return jsonify({"success": True, "domain_id": domain_id, "message": f"Domain {domain} added"})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/domains/<int:domain_id>", methods=["PUT"])
    @login_required
    @admin_required_decorator
    def api_domains_update(domain_id):
        """Update a managed domain's metadata."""
        data = request.get_json() or {}
        allowed = {
            "registrar",
            "nameservers",
            "dns_provider",
            "target_module",
            "target_port",
            "notes",
            "ssl_status",
            "dns_status",
        }
        updates = {}
        for key in allowed:
            if key in data:
                val = data[key]
                if key == "nameservers" and isinstance(val, str):
                    val = [ns.strip() for ns in val.split(",") if ns.strip()]
                if key == "dns_provider" and val not in ("hostinger", "cloudflare", "manual"):
                    return (
                        jsonify({"success": False, "error": "dns_provider must be hostinger, cloudflare, or manual"}),
                        400,
                    )
                if key == "target_port":
                    val = int(val)
                updates[key] = val
        if not updates:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        try:
            set_clause = ", ".join(f"{k} = %s" for k in updates)
            values = list(updates.values())
            values.extend([domain_id, current_user.id])

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE org_domains SET " + set_clause + ", updated_at = NOW() WHERE id = %s AND user_id = %s",
                    values,
                )
                if cur.rowcount == 0:
                    return jsonify({"success": False, "error": "Domain not found or not owned by you"}), 404
            return jsonify({"success": True, "message": "Domain updated"})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/domains/<int:domain_id>", methods=["DELETE"])
    @login_required
    @admin_required_decorator
    def api_domains_delete(domain_id):
        """Remove a managed domain and its DNS records."""
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                # Delete linked DNS records first
                cur.execute("DELETE FROM managed_dns_records WHERE domain_id = %s", (domain_id,))
                deleted_records = cur.rowcount
                # Delete domain (user_id scoped)
                cur.execute(
                    "DELETE FROM org_domains WHERE id = %s AND user_id = %s",
                    (domain_id, current_user.id),
                )
                if cur.rowcount == 0:
                    return jsonify({"success": False, "error": "Domain not found or not owned by you"}), 404
            return jsonify({"success": True, "message": "Domain deleted", "deleted_records": deleted_records})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # --- Per-Domain DNS Records ---

    @bp.route("/api/domains/<int:domain_id>/records")
    @login_required
    @admin_required_decorator
    def api_domain_records_list(domain_id):
        """List DNS records for a specific domain."""
        try:
            with get_db_cursor() as (conn, cur):
                # Verify ownership
                cur.execute(
                    "SELECT domain FROM org_domains WHERE id = %s AND user_id = %s",
                    (domain_id, current_user.id),
                )
                owner_row = cur.fetchone()
                if not owner_row:
                    return jsonify({"success": False, "error": "Domain not found"}), 404

                cur.execute(
                    """SELECT id, domain, record_type, name, value, ttl, priority,
                              status, error_message, created_at, updated_at
                       FROM managed_dns_records
                       WHERE domain_id = %s
                       ORDER BY record_type, name""",
                    (domain_id,),
                )
                rows = cur.fetchall()
                records = []
                for r in rows:
                    rec = dict(r)  # RealDictCursor rows; dict(zip(cols,r)) yielded {col: col}
                    rec["created_at"] = str(rec["created_at"]) if rec["created_at"] else None
                    rec["updated_at"] = str(rec["updated_at"]) if rec["updated_at"] else None
                    records.append(rec)
            return jsonify({"success": True, "domain": owner_row[0], "records": records})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/domains/<int:domain_id>/records", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_domain_records_create(domain_id):
        """Add a DNS record for a specific domain."""
        data = request.get_json() or {}
        record_type = data.get("record_type", "").strip().upper()
        name = data.get("name", "").strip()
        value = data.get("value", "").strip()
        ttl = data.get("ttl", 3600)
        priority = data.get("priority")

        if not record_type or not value:
            return jsonify({"success": False, "error": "record_type and value are required"}), 400
        if record_type not in ("A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV", "CAA"):
            return jsonify({"success": False, "error": f"Unsupported record type: {record_type}"}), 400

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                # Verify ownership and get domain name
                cur.execute(
                    "SELECT domain FROM org_domains WHERE id = %s AND user_id = %s",
                    (domain_id, current_user.id),
                )
                owner_row = cur.fetchone()
                if not owner_row:
                    return jsonify({"success": False, "error": "Domain not found"}), 404

                domain_name = owner_row[0]
                cur.execute(
                    """INSERT INTO managed_dns_records
                       (domain_id, domain, record_type, name, value, ttl, priority, status, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', NOW(), NOW())
                       RETURNING id""",
                    (domain_id, domain_name, record_type, name, value, int(ttl), priority),
                )
                record_id = cur.fetchone()[0]
            return jsonify({"success": True, "record_id": record_id, "message": f"{record_type} record added"})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/domains/<int:domain_id>/records/<int:record_id>", methods=["PUT"])
    @login_required
    @admin_required_decorator
    def api_domain_records_update(domain_id, record_id):
        """Update a DNS record for a specific domain."""
        data = request.get_json() or {}
        allowed = {"name", "value", "ttl", "priority", "status"}
        updates = {}
        for key in allowed:
            if key in data:
                val = data[key]
                if key == "ttl":
                    val = int(val)
                updates[key] = val
        if not updates:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                # Verify domain ownership
                cur.execute(
                    "SELECT id FROM org_domains WHERE id = %s AND user_id = %s",
                    (domain_id, current_user.id),
                )
                if not cur.fetchone():
                    return jsonify({"success": False, "error": "Domain not found"}), 404

                set_clause = ", ".join(f"{k} = %s" for k in updates)
                values = list(updates.values())
                values.extend([record_id, domain_id])
                cur.execute(
                    "UPDATE managed_dns_records SET "
                    + set_clause
                    + ", updated_at = NOW() WHERE id = %s AND domain_id = %s",
                    values,
                )
                if cur.rowcount == 0:
                    return jsonify({"success": False, "error": "Record not found"}), 404
            return jsonify({"success": True, "message": "Record updated"})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/domains/<int:domain_id>/records/<int:record_id>", methods=["DELETE"])
    @login_required
    @admin_required_decorator
    def api_domain_records_delete(domain_id, record_id):
        """Delete a DNS record for a specific domain."""
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                # Verify domain ownership
                cur.execute(
                    "SELECT id FROM org_domains WHERE id = %s AND user_id = %s",
                    (domain_id, current_user.id),
                )
                if not cur.fetchone():
                    return jsonify({"success": False, "error": "Domain not found"}), 404

                cur.execute(
                    "DELETE FROM managed_dns_records WHERE id = %s AND domain_id = %s",
                    (record_id, domain_id),
                )
                if cur.rowcount == 0:
                    return jsonify({"success": False, "error": "Record not found"}), 404
            return jsonify({"success": True, "message": "Record deleted"})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # NGINX CONFIGURATION MANAGEMENT (via host_command_client)
    # ========================================================================

    def _nginx_cmd(command_type, params=None, timeout=30):
        """Submit an nginx command via host_command_client and return the result."""
        from tools.system_operations.host_command_client import (
            submit_and_wait,
            HostCommandError,
        )

        try:
            result = submit_and_wait(
                command_type,
                params or {},
                timeout=timeout,
                submitted_by=getattr(current_user, "username", "admin"),
                user_id=getattr(current_user, "id", None),
            )
            return result.get("result", result)
        except HostCommandError as e:
            return {"success": False, "error": str(e)}

    @bp.route("/api/nginx/configs")
    @login_required
    @admin_required_decorator
    def api_nginx_list_configs():
        """List available Nginx configuration files."""
        try:
            result = _nginx_cmd("nginx_list_configs")
            if not result.get("success"):
                return jsonify(result), 502
            return jsonify(result)
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nginx/configs/<name>")
    @login_required
    @admin_required_decorator
    def api_nginx_get_config(name):
        """Get the content of a specific Nginx config file."""
        import re

        if not re.match(r"^[a-zA-Z0-9_.\-]+$", name):
            return jsonify({"success": False, "error": "Invalid config name"}), 400
        try:
            result = _nginx_cmd("nginx_get_config", {"name": name})
            if not result.get("success"):
                return jsonify(result), 404 if "not found" in result.get("error", "") else 502
            return jsonify(result)
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nginx/test", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_nginx_test():
        """Run nginx -t to validate configuration."""
        try:
            result = _nginx_cmd("nginx_test")
            if not result.get("success"):
                return jsonify(result), 400
            return jsonify(result)
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nginx/reload", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_nginx_reload():
        """Reload Nginx (tests config first, aborts if invalid)."""
        try:
            result = _nginx_cmd("nginx_reload")
            if not result.get("success"):
                return jsonify(result), 400
            return jsonify(result)
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500
