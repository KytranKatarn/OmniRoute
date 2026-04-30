"""
Access grant/revoke/check API.
Called by KBS after Stripe events to control product access per user.
Internal endpoints — require X-Internal-Token header.
"""

import hmac
import os
import logging
from flask import Blueprint, request, jsonify
from database import get_db_cursor

logger = logging.getLogger(__name__)
access_bp = Blueprint("access", __name__, url_prefix="/api/access")

_INTERNAL_TOKEN = os.getenv("AC_INTERNAL_TOKEN", "")


def _check_token():
    if not _INTERNAL_TOKEN:
        logger.warning("AC_INTERNAL_TOKEN not set — access API running unauthenticated")
        return True
    token = request.headers.get("X-Internal-Token", "")
    return hmac.compare_digest(token, _INTERNAL_TOKEN)


@access_bp.route("/grant", methods=["POST"])
def grant_access():
    if not _check_token():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    try:
        user_id = int(data.get("user_id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "user_id must be an integer"}), 400
    product_slug = data.get("product_slug")
    source = data.get("source", "stripe")
    if not user_id or not product_slug:
        return jsonify({"error": "user_id and product_slug required"}), 400
    try:
        with get_db_cursor(commit=True) as (_, cur):
            cur.execute(
                """
                INSERT INTO access_grants (user_id, product_slug, source, valid_until)
                VALUES (%s, %s, %s, NULL)
                ON CONFLICT (user_id, product_slug)
                DO UPDATE SET source = EXCLUDED.source, updated_at = NOW()
                """,
                (user_id, product_slug, source),
            )
    except Exception as exc:
        logger.error("access.grant DB error: %s", exc)
        return jsonify({"error": "internal error"}), 500
    logger.info("access.grant: user=%s product=%s source=%s", user_id, product_slug, source)
    return jsonify({"granted": True, "user_id": user_id, "product_slug": product_slug})


@access_bp.route("/revoke", methods=["POST"])
def revoke_access():
    if not _check_token():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    try:
        user_id = int(data.get("user_id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "user_id must be an integer"}), 400
    product_slug = data.get("product_slug")
    if not user_id or not product_slug:
        return jsonify({"error": "user_id and product_slug required"}), 400
    try:
        with get_db_cursor(commit=True) as (_, cur):
            cur.execute(
                """
                UPDATE access_grants SET valid_until = NOW(), updated_at = NOW()
                WHERE user_id = %s AND product_slug = %s
                  AND (valid_until IS NULL OR valid_until > NOW())
                """,
                (user_id, product_slug),
            )
    except Exception as exc:
        logger.error("access.revoke DB error: %s", exc)
        return jsonify({"error": "internal error"}), 500
    logger.info("access.revoke: user=%s product=%s", user_id, product_slug)
    return jsonify({"revoked": True, "user_id": user_id, "product_slug": product_slug})


@access_bp.route("/check", methods=["GET"])
def check_access():
    user_id = request.args.get("user_id", type=int)
    product_slug = request.args.get("product")
    if not user_id or not product_slug:
        return jsonify({"error": "user_id and product required"}), 400
    try:
        with get_db_cursor() as (_, cur):
            cur.execute(
                """
                SELECT 1 FROM access_grants
                WHERE user_id = %s AND product_slug = %s
                  AND (valid_until IS NULL OR valid_until > NOW())
                LIMIT 1
                """,
                (user_id, product_slug),
            )
            has_access = cur.fetchone() is not None
    except Exception as exc:
        logger.error("access.check DB error: %s", exc)
        return jsonify({"error": "internal error"}), 500
    return jsonify({"has_access": has_access, "user_id": user_id, "product_slug": product_slug})


@access_bp.route("/list", methods=["GET"])
def list_access():
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    try:
        with get_db_cursor() as (_, cur):
            cur.execute(
                """
                SELECT product_slug, source, valid_from, valid_until
                FROM access_grants
                WHERE user_id = %s
                  AND (valid_until IS NULL OR valid_until > NOW())
                ORDER BY valid_from
                """,
                (user_id,),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("access.list DB error: %s", exc)
        return jsonify({"error": "internal error"}), 500
    products = [r["product_slug"] for r in rows]
    grants = [
        {
            "product_slug": r["product_slug"],
            "source": r["source"],
            "valid_from": r["valid_from"].isoformat() if r["valid_from"] else None,
            "valid_until": r["valid_until"].isoformat() if r["valid_until"] else None,
        }
        for r in rows
    ]
    return jsonify({"user_id": user_id, "products": products, "grants": grants})
