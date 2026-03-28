"""
core/team_management.py -- Team member invite, role, and removal for tenants.

Routes:
  POST   /api/team/invite       -- invite by email
  GET    /api/team              -- list team members
  PUT    /api/team/<id>/role    -- change role (owner only)
  DELETE /api/team/<id>         -- remove from tenant
  GET    /auth/accept-invite/<token> -- accept invite
"""

import logging
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, redirect, request, session, url_for
from flask_login import current_user, login_required

from core.database import get_db_cursor

logger = logging.getLogger(__name__)

team_bp = Blueprint("team", __name__)

VALID_ROLES = {"admin", "member", "viewer"}


@team_bp.route("/api/team/invite", methods=["POST"])
@login_required
def invite_member():
    """Invite a user to the current tenant by email."""
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    role = data.get("role", "member").strip().lower()

    if not email:
        return jsonify({"error": "email is required"}), 400

    if role not in VALID_ROLES:
        return jsonify({"error": f"Invalid role. Must be one of: {', '.join(sorted(VALID_ROLES))}"}), 400

    tenant_role = session.get("tenant_role", "")
    if tenant_role not in ("owner", "admin"):
        return jsonify({"error": "Only owners and admins can invite team members"}), 403

    tenant_id = g.tenant_id
    token = secrets.token_urlsafe(32)

    # Check for existing pending invite
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            "SELECT id FROM team_invites WHERE tenant_id = %s AND email = %s AND status = 'pending'",
            (tenant_id, email),
        )
        if cur.fetchone():
            return jsonify({"error": "An invite is already pending for this email"}), 409

    # Check if already a member
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT tu.user_id
            FROM tenant_users tu JOIN users u ON u.id = tu.user_id
            WHERE tu.tenant_id = %s AND u.email = %s
            """,
            (tenant_id, email),
        )
        if cur.fetchone():
            return jsonify({"error": "User is already a member of this workspace"}), 409

    # Create invite
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO team_invites (tenant_id, email, role, invited_by, token, status, expires_at)
            VALUES (%s, %s, %s, %s, %s, 'pending', NOW() + INTERVAL '7 days')
            RETURNING id
            """,
            (tenant_id, email, role, current_user.id, token),
        )
        invite_id = cur.fetchone()[0]

    invite_url = f"{request.host_url}auth/accept-invite/{token}"

    logger.info("Created team invite %s for %s (tenant %s)", invite_id, email, tenant_id)

    return jsonify({
        "status": "invited",
        "invite_id": invite_id,
        "email": email,
        "role": role,
        "invite_url": invite_url,
    })


@team_bp.route("/api/team", methods=["GET"])
@login_required
def list_members():
    """List all team members and pending invites for the current tenant."""
    tenant_id = g.tenant_id

    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT u.id, u.email, u.username AS name, tu.role, u.last_login, u.created_at
            FROM tenant_users tu JOIN users u ON u.id = tu.user_id
            WHERE tu.tenant_id = %s
            ORDER BY tu.role, u.username
            """,
            (tenant_id,),
        )
        members = []
        for row in cur.fetchall():
            members.append({
                "id": row["id"],
                "email": row["email"],
                "name": row["name"],
                "role": row["role"],
                "last_login": row["last_login"].isoformat() if row.get("last_login") else None,
                "joined": row["created_at"].isoformat() if row.get("created_at") else None,
            })

    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT id, email, role, created_at, expires_at
            FROM team_invites
            WHERE tenant_id = %s AND status = 'pending' AND expires_at > NOW()
            ORDER BY created_at DESC
            """,
            (tenant_id,),
        )
        invites = []
        for row in cur.fetchall():
            invites.append({
                "id": row["id"],
                "email": row["email"],
                "role": row["role"],
                "invited_at": row["created_at"].isoformat() if row.get("created_at") else None,
                "expires_at": row["expires_at"].isoformat() if row.get("expires_at") else None,
                "status": "pending",
            })

    return jsonify({"members": members, "pending_invites": invites})


@team_bp.route("/api/team/<int:user_id>/role", methods=["PUT"])
@login_required
def change_role(user_id):
    """Change a team member's role. Owner only."""
    data = request.get_json() or {}
    new_role = data.get("role", "").strip().lower()

    if new_role not in VALID_ROLES:
        return jsonify({"error": f"Invalid role. Must be one of: {', '.join(sorted(VALID_ROLES))}"}), 400

    if session.get("tenant_role", "") != "owner":
        return jsonify({"error": "Only the owner can change roles"}), 403

    if user_id == current_user.id:
        return jsonify({"error": "Cannot change your own role"}), 400

    tenant_id = g.tenant_id

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE tenant_users SET role = %s WHERE tenant_id = %s AND user_id = %s RETURNING user_id",
            (new_role, tenant_id, user_id),
        )
        if not cur.fetchone():
            return jsonify({"error": "User not found in this workspace"}), 404

    logger.info("Changed role of user %s to %s (tenant %s)", user_id, new_role, tenant_id)
    return jsonify({"status": "ok", "user_id": user_id, "role": new_role})


@team_bp.route("/api/team/<int:user_id>", methods=["DELETE"])
@login_required
def remove_member(user_id):
    """Remove a team member. Owner and admin only. Cannot remove the owner."""
    tenant_role = session.get("tenant_role", "")
    if tenant_role not in ("owner", "admin"):
        return jsonify({"error": "Only owners and admins can remove members"}), 403

    if user_id == current_user.id:
        return jsonify({"error": "Cannot remove yourself"}), 400

    tenant_id = g.tenant_id

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM tenant_users WHERE tenant_id = %s AND user_id = %s AND role != 'owner' RETURNING user_id",
            (tenant_id, user_id),
        )
        if not cur.fetchone():
            return jsonify({"error": "User not found or cannot remove the owner"}), 404

    logger.info("Removed user %s from tenant %s", user_id, tenant_id)
    return jsonify({"status": "removed", "user_id": user_id})


@team_bp.route("/auth/accept-invite/<token>")
def accept_invite(token):
    """Accept a team invite via token link."""
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            "SELECT id, tenant_id, email, role, expires_at FROM team_invites WHERE token = %s AND status = 'pending'",
            (token,),
        )
        invite = cur.fetchone()

    if not invite:
        return jsonify({"error": "Invalid or expired invite"}), 404

    if invite["expires_at"] and invite["expires_at"] < datetime.utcnow():
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("UPDATE team_invites SET status = 'expired' WHERE id = %s", (invite["id"],))
        return jsonify({"error": "This invite has expired"}), 410

    if current_user.is_authenticated:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO tenant_users (tenant_id, user_id, role)
                VALUES (%s, %s, %s)
                ON CONFLICT (tenant_id, user_id) DO UPDATE SET role = EXCLUDED.role
                """,
                (invite["tenant_id"], current_user.id, invite["role"]),
            )
            cur.execute(
                "UPDATE team_invites SET status = 'accepted', accepted_at = NOW() WHERE id = %s",
                (invite["id"],),
            )
        session["tenant_id"] = invite["tenant_id"]
        session["tenant_role"] = invite["role"]
        return redirect(url_for("dashboard"))

    session["pending_invite_token"] = token
    return redirect(url_for("auth.signup") + f"?invite={token}")
