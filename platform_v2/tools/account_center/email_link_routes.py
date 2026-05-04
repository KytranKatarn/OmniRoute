"""Account Center — alternate email linking routes (Project #311)."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template, request, session
from flask_login import login_required

from database import get_db_cursor
from services import account_link_service

logger = logging.getLogger(__name__)

# Public blueprint — no url_prefix so the verify URL is /account/verify-alternate
account_link_verify_bp = Blueprint("account_link_verify", __name__)


def _current_user_id() -> int | None:
    return session.get("user_id")


def _get_user_alternates(user_id: int) -> dict:
    """Return ``{"verified": [...], "pending": [{email, expires_at}]}``."""
    with get_db_cursor() as (_conn, cur):
        cur.execute("SELECT alternate_emails FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        verified = list(row["alternate_emails"] or []) if row else []

        cur.execute(
            """SELECT alternate_email, expires_at
                 FROM alternate_email_verifications
                WHERE user_id = %s AND used_at IS NULL AND expires_at > NOW()
                ORDER BY created_at DESC""",
            (user_id,),
        )
        pending = [
            {
                "email": r["alternate_email"],
                "expires_at": r["expires_at"].isoformat(),
            }
            for r in cur.fetchall()
        ]
    return {"verified": verified, "pending": pending}


def register_email_link_routes(bp):
    """Register authenticated routes on the Account Center blueprint.

    The public verify endpoint lives on a separate ``account_link_verify_bp``
    registered directly on the Flask app in app.py — it must NOT inherit the
    /tools/account-center prefix or login_required.
    """

    @bp.route("/api/alternate-emails", methods=["GET"])
    @login_required
    def list_alternate_emails():
        uid = _current_user_id()
        return jsonify(_get_user_alternates(uid))

    @bp.route("/api/alternate-emails", methods=["POST"])
    @login_required
    def add_alternate_email():
        uid = _current_user_id()
        data = request.get_json(force=True, silent=True) or {}
        email = (data.get("email") or "").strip()
        result = account_link_service.request_alternate_email(uid, email)
        if not result.get("success"):
            return jsonify(result), 400
        return jsonify(result), 202

    @bp.route("/api/alternate-emails/<path:email>", methods=["DELETE"])
    @login_required
    def delete_alternate_email(email):
        uid = _current_user_id()
        result = account_link_service.remove_alternate_email(uid, email)
        return jsonify(result), 200


# Public verify route — on the separate no-prefix blueprint
@account_link_verify_bp.route("/account/verify-alternate", methods=["GET"])
def verify_alternate_endpoint():
    """One-shot email verification link (no auth required)."""
    token = request.args.get("token", "")
    result = account_link_service.verify_alternate_email(token)
    if result.get("success"):
        return (
            render_template(
                "account/verify_alternate.html",
                state="success",
                email=result["alternate_email"],
            ),
            200,
        )
    # Map error → 410 if expired/used, else 400.
    err = (result.get("error") or "").lower()
    status = 410 if ("expired" in err or "used" in err) else 400
    return (
        render_template(
            "account/verify_alternate.html",
            state="error",
            error=result.get("error"),
        ),
        status,
    )
