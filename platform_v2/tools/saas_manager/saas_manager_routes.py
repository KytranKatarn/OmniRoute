"""
A.R.C.H.I.E. Platform - SaaS Manager Routes
=============================================

Multi-tenant SaaS platform management:
- Organization CRUD
- Module provisioning (a la carte)
- Domain management (Hostinger DNS + NPM reverse proxy)
- Public IP monitoring
"""

import json

import logging

from flask import Blueprint, render_template, jsonify, request, redirect, url_for, flash
from flask_login import login_required, current_user
from functools import wraps
from database import get_db_cursor

logger = logging.getLogger(__name__)

saas_manager_bp = Blueprint("saas_manager", __name__, url_prefix="/tools/saas-manager")


def admin_required(f):
    """Require admin access. Redirects unauthenticated users to login."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        if not getattr(current_user, "is_admin", False):
            flash("Admin access required", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return decorated


# -- Dashboard ------------------------------------------------------------------


@saas_manager_bp.route("/")
@login_required
@admin_required
def dashboard():
    """SaaS Manager main page."""
    return render_template("tools/saas_manager.html")


# -- Organizations --------------------------------------------------------------


@saas_manager_bp.route("/orgs", methods=["GET"])
@admin_required
def list_orgs():
    """List all organizations."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT o.*,
                   COUNT(DISTINCT ou.user_id) AS user_count,
                   COUNT(DISTINCT om.id) FILTER (WHERE om.enabled) AS module_count,
                   COUNT(DISTINCT od.id) AS domain_count
            FROM organizations o
            LEFT JOIN org_users ou ON ou.org_id = o.id
            LEFT JOIN org_modules om ON om.org_id = o.id
            LEFT JOIN org_domains od ON od.org_id = o.id
            GROUP BY o.id
            ORDER BY o.created_at DESC
        """
        )
        orgs = cur.fetchall()
    return jsonify({"success": True, "orgs": [_serialize(o) for o in orgs]})


@saas_manager_bp.route("/orgs", methods=["POST"])
@admin_required
def create_org():
    """Create a new organization."""
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"success": False, "error": "Organization name required"}), 400

    slug = name.lower().replace(" ", "-").replace("_", "-")

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT id FROM organizations WHERE slug = %s", (slug,))
        if cur.fetchone():
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Organization '{slug}' already exists",
                    }
                ),
                409,
            )

        cur.execute(
            """
            INSERT INTO organizations (name, slug, owner_user_id, archie_user_id, status, settings, ai_config)
            VALUES (%s, %s, %s,
                    (SELECT id FROM users WHERE username = 'admin'),
                    'active', %s, %s)
            RETURNING id, name, slug, status, created_at
        """,
            (
                name,
                slug,
                data.get("owner_user_id"),
                json.dumps(data.get("settings", {})),
                json.dumps(data.get("ai_config", {})),
            ),
        )
        org = cur.fetchone()

        # Auto-add ARCHIE seat
        cur.execute(
            """
            INSERT INTO org_users (org_id, user_id, role, joined_at)
            SELECT %s, id, 'archie', NOW() FROM users WHERE username = 'admin'
            ON CONFLICT DO NOTHING
        """,
            (org["id"],),
        )

        # Add owner if specified
        if data.get("owner_user_id"):
            cur.execute(
                """
                INSERT INTO org_users (org_id, user_id, role, joined_at)
                VALUES (%s, %s, 'owner', NOW())
                ON CONFLICT DO NOTHING
            """,
                (org["id"], data["owner_user_id"]),
            )

    return jsonify({"success": True, "org": _serialize(org)}), 201


@saas_manager_bp.route("/orgs/<int:org_id>", methods=["GET"])
@admin_required
def get_org(org_id):
    """Get organization details with users, modules, domains."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM organizations WHERE id = %s", (org_id,))
        org = cur.fetchone()
        if not org:
            return jsonify({"success": False, "error": "Not found"}), 404

        cur.execute(
            """
            SELECT ou.*, u.username, u.email
            FROM org_users ou JOIN users u ON u.id = ou.user_id
            WHERE ou.org_id = %s
        """,
            (org_id,),
        )
        users = cur.fetchall()

        cur.execute(
            "SELECT * FROM org_modules WHERE org_id = %s ORDER BY module_key",
            (org_id,),
        )
        modules = cur.fetchall()

        cur.execute("SELECT * FROM org_domains WHERE org_id = %s ORDER BY domain", (org_id,))
        domains = cur.fetchall()

    return jsonify(
        {
            "success": True,
            "org": _serialize(org),
            "users": [_serialize(u) for u in users],
            "modules": [_serialize(m) for m in modules],
            "domains": [_serialize(d) for d in domains],
        }
    )


@saas_manager_bp.route("/orgs/<int:org_id>", methods=["PUT"])
@admin_required
def update_org(org_id):
    """Update organization settings."""
    data = request.get_json() or {}
    with get_db_cursor() as (conn, cur):
        fields = []
        values = []
        for key in ("name", "status", "settings", "ai_config"):
            if key in data:
                fields.append(f"{key} = %s")
                val = data[key]
                if key in ("settings", "ai_config"):
                    val = json.dumps(val)
                values.append(val)

        if not fields:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        values.append(org_id)
        cur.execute(
            f"UPDATE organizations SET {', '.join(fields)} WHERE id = %s RETURNING *",
            values,
        )
        org = cur.fetchone()
        if not org:
            return jsonify({"success": False, "error": "Not found"}), 404

    return jsonify({"success": True, "org": _serialize(org)})


@saas_manager_bp.route("/orgs/<int:org_id>", methods=["DELETE"])
@admin_required
def delete_org(org_id):
    """Soft-delete (suspend) an organization."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """UPDATE organizations SET status = 'suspended', updated_at = NOW()
               WHERE id = %s AND status != 'suspended'
               RETURNING id, name, slug, status""",
            (org_id,),
        )
        org = cur.fetchone()
        if not org:
            return jsonify({"success": False, "error": "Organization not found or already suspended"}), 404

    return jsonify({"success": True, "org": _serialize(org)})


# -- Module Management ----------------------------------------------------------


@saas_manager_bp.route("/orgs/<int:org_id>/modules", methods=["POST"])
@admin_required
def manage_org_modules(org_id):
    """Enable or disable modules for an organization."""
    data = request.get_json() or {}
    module_key = data.get("module_key", "").strip()
    enabled = data.get("enabled", True)

    if not module_key:
        return jsonify({"success": False, "error": "module_key required"}), 400

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            INSERT INTO org_modules (org_id, module_key, enabled, config)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (org_id, module_key)
            DO UPDATE SET enabled = EXCLUDED.enabled,
                config = COALESCE(
                    NULLIF(EXCLUDED.config::text, '{}')::jsonb,
                    org_modules.config
                )
            RETURNING *
        """,
            (org_id, module_key, enabled, json.dumps(data.get("config", {}))),
        )
        mod = cur.fetchone()

    return jsonify({"success": True, "module": _serialize(mod)})


# -- User Management ------------------------------------------------------------


@saas_manager_bp.route("/orgs/<int:org_id>/users", methods=["POST"])
@admin_required
def add_org_user(org_id):
    """Add a user to an organization."""
    data = request.get_json() or {}
    user_id = data.get("user_id")
    role = data.get("role", "member")

    if not user_id:
        return jsonify({"success": False, "error": "user_id required"}), 400

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            INSERT INTO org_users (org_id, user_id, role, joined_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (org_id, user_id) DO UPDATE SET role = EXCLUDED.role
            RETURNING *
        """,
            (org_id, user_id, role),
        )
        membership = cur.fetchone()

    return jsonify({"success": True, "membership": _serialize(membership)})


@saas_manager_bp.route("/orgs/<int:org_id>/users/<int:user_id>", methods=["DELETE"])
@admin_required
def remove_org_user(org_id, user_id):
    """Remove a user from an organization."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "DELETE FROM org_users WHERE org_id = %s AND user_id = %s RETURNING id",
            (org_id, user_id),
        )
        deleted = cur.fetchone()

    if not deleted:
        return jsonify({"success": False, "error": "Membership not found"}), 404
    return jsonify({"success": True})


# -- Domain Management ----------------------------------------------------------


@saas_manager_bp.route("/orgs/<int:org_id>/domains", methods=["GET"])
@admin_required
def list_org_domains(org_id):
    """List domains for an organization."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM org_domains WHERE org_id = %s ORDER BY domain", (org_id,))
        domains = cur.fetchall()
    return jsonify({"success": True, "domains": [_serialize(d) for d in domains]})


@saas_manager_bp.route("/orgs/<int:org_id>/domains", methods=["POST"])
@admin_required
def add_org_domain(org_id):
    """Add a domain to an organization. Triggers DNS + NPM setup."""
    data = request.get_json() or {}
    domain = data.get("domain", "").strip().lower()
    target_module = data.get("target_module", "dashboard")

    if not domain:
        return jsonify({"success": False, "error": "domain required"}), 400

    # Parse subdomain and root
    parts = domain.split(".", 1)
    subdomain = parts[0] if len(parts) > 1 else None
    root_domain = parts[1] if len(parts) > 1 else domain

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            INSERT INTO org_domains (org_id, domain, subdomain, root_domain, target_module, dns_provider)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                org_id,
                domain,
                subdomain,
                root_domain,
                target_module,
                data.get("dns_provider", "hostinger"),
            ),
        )
        dom = cur.fetchone()

    # Trigger DNS + NPM setup asynchronously
    setup_result = None
    try:
        from .domain_service import setup_domain
        from .ip_monitor import get_public_ip

        public_ip = get_public_ip()
        setup_result = setup_domain(dom, public_ip)

        # Update domain record with NPM proxy host ID and statuses
        with get_db_cursor() as (conn, cur):
            dns_status = "verified" if setup_result.get("dns", {}).get("success") else "pending"
            ssl_status = "active" if setup_result.get("ssl", {}).get("success") else "pending"
            npm_id = setup_result.get("proxy", {}).get("proxy_host_id")
            cur.execute(
                """UPDATE org_domains
                   SET dns_status = %s, ssl_status = %s, npm_proxy_host_id = %s
                   WHERE id = %s RETURNING *""",
                (dns_status, ssl_status, npm_id, dom["id"]),
            )
            dom = cur.fetchone()
    except Exception as e:
        logger.error("Domain setup failed for %s: %s", domain, e)
        setup_result = {"error": str(e)}

    return (
        jsonify(
            {
                "success": True,
                "domain": _serialize(dom),
                "setup": setup_result,
            }
        ),
        201,
    )


@saas_manager_bp.route("/orgs/<int:org_id>/domains/<int:domain_id>", methods=["DELETE"])
@admin_required
def remove_org_domain(org_id, domain_id):
    """Remove a domain. Cleans up DNS + NPM."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "DELETE FROM org_domains WHERE id = %s AND org_id = %s RETURNING domain, npm_proxy_host_id",
            (domain_id, org_id),
        )
        deleted = cur.fetchone()

    if not deleted:
        return jsonify({"success": False, "error": "Domain not found"}), 404

    # Clean up NPM proxy host
    try:
        from .domain_service import cleanup_domain

        cleanup_domain(deleted["domain"], deleted.get("npm_proxy_host_id"))
    except Exception as e:
        logger.warning("Domain cleanup for %s: %s", deleted["domain"], e)

    return jsonify({"success": True, "removed": deleted["domain"]})


@saas_manager_bp.route("/orgs/<int:org_id>/domains/<int:domain_id>/verify", methods=["POST"])
@admin_required
def verify_domain(org_id, domain_id):
    """Check DNS propagation and SSL status for a domain."""
    import socket

    from .ip_monitor import get_public_ip as detect_public_ip

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM org_domains WHERE id = %s AND org_id = %s",
            (domain_id, org_id),
        )
        dom = cur.fetchone()
        if not dom:
            return jsonify({"success": False, "error": "Domain not found"}), 404

        dns_ok = False
        resolved_ip = None
        try:
            resolved_ip = socket.gethostbyname(dom["domain"])
            public_ip = detect_public_ip()
            dns_ok = resolved_ip == public_ip
        except Exception:
            pass

        new_dns_status = "verified" if dns_ok else "failed"
        cur.execute(
            "UPDATE org_domains SET dns_status = %s, verified_at = NOW() WHERE id = %s",
            (new_dns_status, domain_id),
        )

    return jsonify(
        {
            "success": True,
            "domain": dom["domain"],
            "dns_status": new_dns_status,
            "resolved_ip": resolved_ip,
            "dns_ok": dns_ok,
        }
    )


# -- Network / IP Monitoring ---------------------------------------------------


@saas_manager_bp.route("/network/public-ip", methods=["GET"])
@admin_required
def get_public_ip():
    """Get current public IP and change history."""
    from .ip_monitor import get_public_ip as detect_public_ip

    try:
        current_ip = detect_public_ip()
    except Exception as e:
        return (
            jsonify({"success": False, "error": f"Could not detect public IP: {e}"}),
            500,
        )

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT ip_address FROM org_ip_history ORDER BY detected_at DESC LIMIT 1")
        last = cur.fetchone()
        ip_changed = last is None or last["ip_address"] != current_ip

        if ip_changed:
            cur.execute("INSERT INTO org_ip_history (ip_address) VALUES (%s)", (current_ip,))

        cur.execute("SELECT * FROM org_ip_history ORDER BY detected_at DESC LIMIT 20")
        history = cur.fetchall()

    return jsonify(
        {
            "success": True,
            "current_ip": current_ip,
            "changed": ip_changed,
            "history": [_serialize(h) for h in history],
        }
    )


@saas_manager_bp.route("/network/check-ports", methods=["POST"])
@admin_required
def check_ports():
    """Verify ports 80/443 are accessible from outside."""
    import urllib.request

    from .ip_monitor import get_public_ip as detect_public_ip

    results = {}
    for port in [80, 443]:
        try:
            public_ip = detect_public_ip()
            proto = "https" if port == 443 else "http"
            url = f"{proto}://{public_ip}:{port}/"
            req = urllib.request.Request(url, method="HEAD")
            resp = urllib.request.urlopen(req, timeout=5)
            results[port] = {"open": True, "status": resp.status}
        except Exception as e:
            results[port] = {"open": False, "error": str(e)}

    return jsonify({"success": True, "ports": results})


# -- Available Modules List -----------------------------------------------------


@saas_manager_bp.route("/available-modules", methods=["GET"])
@admin_required
def available_modules():
    """List all modules available for assignment to organizations."""
    from module_registry import get_enabled_modules

    modules = []
    for m in get_enabled_modules():
        modules.append(
            {
                "key": m.id,
                "name": m.name,
                "description": m.description,
                "category": m.category.value if m.category else None,
                "icon": m.icon,
            }
        )
    return jsonify({"success": True, "modules": modules})


# -- Helpers --------------------------------------------------------------------


def _serialize(row):
    """Convert a RealDictRow to a JSON-safe dict."""
    if row is None:
        return None
    from datetime import datetime, date

    result = dict(row)
    for k, v in result.items():
        if isinstance(v, (datetime, date)):
            result[k] = v.isoformat()
    return result
