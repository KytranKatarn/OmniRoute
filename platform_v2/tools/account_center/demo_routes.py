"""Demo session routes — magic-link guest access."""

import secrets
from datetime import timedelta

from flask import redirect, render_template, request, session
from flask_login import current_user, login_user

from database import get_db_cursor
from services.time_utils import now_utc


def register_demo_routes(bp, admin_required):
    """Register demo session routes on the account_center blueprint."""

    @bp.route("/demo")
    def demo_entry():
        """Public — validates token, creates or reuses ephemeral user, logs them in."""
        token = request.args.get("token", "").strip()
        if not token:
            return render_template("demo_expired.html"), 404

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, label, expires_at, ephemeral_user_id
                FROM demo_sessions
                WHERE token = %s AND is_active = TRUE AND expires_at > NOW()
                """,
                (token,),
            )
            row = cur.fetchone()

        if not row:
            return render_template("demo_expired.html"), 410

        session_id = row["id"]
        expires_at = row["expires_at"]
        existing_uid = row["ephemeral_user_id"]

        with get_db_cursor(commit=True) as (conn, cur):
            if existing_uid:
                cur.execute("SELECT id FROM users WHERE id = %s", (existing_uid,))
                if not cur.fetchone():
                    existing_uid = None

            if not existing_uid:
                email = f"demo-{session_id}@kytranempowerment.com"
                cur.execute(
                    """
                    INSERT INTO users
                        (email, username, role, subscription_tier, is_active, password_hash)
                    VALUES (%s, %s, 'GUEST', 'guest', TRUE, 'demo-no-login')
                    ON CONFLICT (email) DO UPDATE SET is_active = TRUE
                    RETURNING id
                    """,
                    (email, f"demo-{session_id}"),
                )
                existing_uid = cur.fetchone()["id"]
                cur.execute(
                    "UPDATE demo_sessions SET ephemeral_user_id = %s WHERE id = %s",
                    (existing_uid, session_id),
                )

            cur.execute(
                "UPDATE demo_sessions SET used_count = used_count + 1 WHERE id = %s",
                (session_id,),
            )

        from app import load_user as _load_user  # noqa: PLC0415

        user = _load_user(str(existing_uid))
        if not user:
            return render_template("demo_expired.html"), 500

        login_user(user, remember=False)
        session["demo_session_id"] = session_id
        session["demo_expires"] = expires_at.isoformat()

        return redirect("/")

    @bp.route("/api/admin/demo/link", methods=["POST"])
    @admin_required
    def demo_create_link():
        """Generate a new demo link."""
        data = request.get_json(silent=True) or {}
        label = (data.get("label") or "").strip()[:200]
        try:
            expires_hours = max(1, min(int(data.get("expires_hours", 24)), 720))
        except (TypeError, ValueError):
            expires_hours = 24

        token = secrets.token_urlsafe(32)
        expires_at = now_utc() + timedelta(hours=expires_hours)

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO demo_sessions (token, label, expires_at, created_by)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (token, label or None, expires_at, current_user.id),
            )
            new_id = cur.fetchone()["id"]

        base = request.host_url.rstrip("/")
        url = f"{base}/tools/account-center/demo?token={token}"

        return {
            "token": token,
            "url": url,
            "label": label,
            "expires_at": expires_at.isoformat(),
            "id": new_id,
        }

    @bp.route("/api/admin/demo/links")
    @admin_required
    def demo_list_links():
        """List all demo sessions ordered by newest first."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, token, label, expires_at, used_count, is_active, created_at
                FROM demo_sessions
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()

        return {
            "links": [
                {
                    "id": r["id"],
                    "label": r["label"],
                    "token": r["token"],
                    "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
                    "used_count": r["used_count"],
                    "is_active": r["is_active"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ]
        }

    @bp.route("/api/admin/demo/link/<int:link_id>", methods=["DELETE"])
    @admin_required
    def demo_revoke_link(link_id):
        """Deactivate a demo session."""
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE demo_sessions SET is_active = FALSE WHERE id = %s RETURNING id",
                (link_id,),
            )
            row = cur.fetchone()
        if not row:
            return {"error": "not found"}, 404
        return {"revoked": True, "id": link_id}
