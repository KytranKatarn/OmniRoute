"""Partner/Collaborator admin routes."""

import json
import re
import secrets
import urllib.error
import urllib.request
from datetime import timedelta

from flask import current_app, request
from flask_login import current_user

from database import get_db_cursor
from services.time_utils import now_utc


def _npm_token():
    """Get NPM JWT token using env credentials."""
    import os

    email = os.getenv("NPM_ADMIN_EMAIL", "")
    password = os.getenv("NPM_ADMIN_PASSWORD", "")
    data = json.dumps({"identity": email, "secret": password}).encode()
    req = urllib.request.Request(
        "http://nginx_proxy_manager:81/api/tokens",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read())["token"]


def _npm_create_proxy_host(slug):
    """Create NPM proxy host for {slug}.kytranempowerment.com -> port 3000."""
    tok = _npm_token()
    headers = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    payload = {
        "domain_names": [f"{slug}.kytranempowerment.com"],
        "forward_scheme": "http",
        "forward_host": "192.168.1.200",
        "forward_port": 3000,
        "ssl_forced": False,
        "allow_websocket_upgrade": True,
    }
    req = urllib.request.Request(
        "http://nginx_proxy_manager:81/api/nginx/proxy-hosts",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
    return resp.get("id")


def _npm_delete_proxy_host(host_id):
    """Delete an NPM proxy host by ID."""
    try:
        tok = _npm_token()
        req = urllib.request.Request(
            f"http://nginx_proxy_manager:81/api/nginx/proxy-hosts/{host_id}",
            headers={"Authorization": f"Bearer {tok}"},
            method="DELETE",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        current_app.logger.warning("NPM delete host %s failed: %s", host_id, e)


def register_partner_routes(bp, admin_required):
    """Register partner admin routes on the account_center blueprint."""

    @bp.route("/api/admin/partners/check-slug")
    @admin_required
    def partner_check_slug():
        slug = request.args.get("slug", "").strip().lower()
        if not re.match(r"^[a-z0-9-]{2,50}$", slug):
            return {"available": False, "reason": "Slug must be 2-50 lowercase letters, numbers, or hyphens"}
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT id FROM partner_profiles WHERE slug = %s", (slug,))
            exists = cur.fetchone()
        return {"available": not exists}

    @bp.route("/api/admin/partners", methods=["POST"])
    @admin_required
    def partner_create():
        """Create partner profile, provision NPM subdomain, send invite."""
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        display_name = (data.get("display_name") or "").strip()[:100]
        slug = (data.get("slug") or "").strip().lower()

        if not email or "@" not in email:
            return {"error": "Valid email required"}, 400
        if not display_name:
            return {"error": "Display name required"}, 400
        if not re.match(r"^[a-z0-9-]{2,50}$", slug):
            return {"error": "Slug must be 2-50 lowercase letters, numbers, or hyphens"}, 400

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT id FROM partner_profiles WHERE slug = %s", (slug,))
            if cur.fetchone():
                return {"error": "Slug already taken"}, 409

        # 1. Create partner_profiles stub (user_id null until invite accepted)
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO partner_profiles (slug, display_name, invited_by)
                   VALUES (%s, %s, %s) RETURNING id""",
                (slug, display_name, current_user.id),
            )
            profile_id = cur.fetchone()["id"]

        # 2. Provision NPM proxy host (non-fatal if fails)
        npm_host_id = None
        try:
            npm_host_id = _npm_create_proxy_host(slug)
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE partner_profiles SET npm_proxy_host_id = %s WHERE id = %s",
                    (npm_host_id, profile_id),
                )
        except Exception as e:
            current_app.logger.warning("NPM host creation failed for %s: %s", slug, e)

        # 3. Send invite via existing user_invites system
        token = secrets.token_urlsafe(32)
        expires_at = now_utc() + timedelta(days=7)
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO user_invites
                       (email, role, subscription_tier, token, expires_at, invited_by,
                        status, partner_profile_id)
                   VALUES (%s, 'COLLABORATOR', 'guest', %s, %s, %s, 'pending', %s)
                   RETURNING id""",
                (email, token, expires_at, current_user.id, profile_id),
            )

        # 4. Send invite email
        email_sent = False
        try:
            from tools.account_center.routes import _send_invite_email  # noqa: PLC0415

            base_url = request.host_url.rstrip("/")
            invite_link = f"{base_url}/accept-invite?token={token}"
            ok, _ = _send_invite_email(
                to_email=email,
                invite_link=invite_link,
                inviter_name=current_user.username,
                message=(
                    f"You've been invited to collaborate on the A.R.C.H.I.E. platform. "
                    f"Your workspace will be at {slug}.kytranempowerment.com"
                ),
            )
            email_sent = bool(ok)
        except Exception as e:
            current_app.logger.error("Invite email failed for %s: %s", email, e)

        return {
            "partner_profile_id": profile_id,
            "subdomain": f"{slug}.kytranempowerment.com",
            "npm_host_id": npm_host_id,
            "invite_sent": email_sent,
        }

    @bp.route("/api/admin/partners")
    @admin_required
    def partner_list():
        """List all partner profiles with user info."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT p.id, p.slug, p.display_name, p.npm_proxy_host_id,
                       p.fleet_node_id, p.onboarding_complete, p.created_at,
                       u.email, u.last_login, u.is_active
                FROM partner_profiles p
                LEFT JOIN users u ON p.user_id = u.id
                ORDER BY p.created_at DESC
                """
            )
            rows = cur.fetchall()
        return {
            "partners": [
                {
                    "id": r["id"],
                    "slug": r["slug"],
                    "display_name": r["display_name"],
                    "subdomain": f"{r['slug']}.kytranempowerment.com",
                    "email": r["email"],
                    "last_login": r["last_login"].isoformat() if r["last_login"] else None,
                    "is_active": r["is_active"],
                    "onboarding_complete": r["onboarding_complete"],
                    "fleet_node_id": r["fleet_node_id"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ]
        }

    @bp.route("/api/admin/partners/<int:partner_id>", methods=["PATCH"])
    @admin_required
    def partner_update(partner_id):
        """Link a fleet node to a partner profile."""
        data = request.get_json(silent=True) or {}
        fleet_node_id = data.get("fleet_node_id")
        if fleet_node_id is None:
            return {"error": "fleet_node_id required"}, 400
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE partner_profiles SET fleet_node_id = %s WHERE id = %s RETURNING id",
                (fleet_node_id, partner_id),
            )
            if not cur.fetchone():
                return {"error": "Partner not found"}, 404
        return {"updated": True, "partner_id": partner_id}

    @bp.route("/api/admin/partners/<int:partner_id>", methods=["DELETE"])
    @admin_required
    def partner_revoke(partner_id):
        """Deactivate partner: disable user, delete NPM host."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT user_id, npm_proxy_host_id FROM partner_profiles WHERE id = %s",
                (partner_id,),
            )
            row = cur.fetchone()
        if not row:
            return {"error": "Partner not found"}, 404

        if row["user_id"]:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("UPDATE users SET is_active = FALSE WHERE id = %s", (row["user_id"],))

        if row["npm_proxy_host_id"]:
            _npm_delete_proxy_host(row["npm_proxy_host_id"])

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE partner_profiles SET npm_proxy_host_id = NULL WHERE id = %s",
                (partner_id,),
            )

        return {"revoked": True, "partner_id": partner_id}
