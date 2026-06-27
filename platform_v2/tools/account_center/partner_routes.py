"""Partner/Collaborator admin routes."""

import re
import secrets
from datetime import timedelta

from flask import current_app, request
from flask_login import current_user

from database import get_db_cursor
from services.time_utils import now_utc


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
        """Create partner profile and send invite."""
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

        # NPM proxy provisioning removed (Beacon/Caddy is the front door now).
        npm_host_id = None

        # 2. Send invite via existing user_invites system
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
        """Deactivate partner: disable user."""
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

        return {"revoked": True, "partner_id": partner_id}
