"""OAuth userinfo endpoint — returns user profile + subscription entitlements."""

import jwt
from flask import Blueprint, jsonify, request, current_app
from database import get_db_cursor

oauth_userinfo_bp = Blueprint("oauth_userinfo", __name__, url_prefix="/oauth")


@oauth_userinfo_bp.route("/userinfo", methods=["GET"])
def userinfo():
    """Return user profile + subscription entitlements. Requires Bearer token."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Bearer token required"}), 401

    token = auth_header[7:]

    try:
        secret = current_app.config.get("SECRET_KEY", "fallback-secret")
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401

    user_id = payload.get("sub")
    if not user_id:
        return jsonify({"error": "Invalid token payload"}), 401

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, username, email, role, language_preference FROM users WHERE id = %s AND is_active = TRUE",
            (user_id,),
        )
        user = cur.fetchone()

    if not user:
        return jsonify({"error": "User not found"}), 404

    entitlements = []
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT DISTINCT module FROM billing_subscriptions
               WHERE user_id = %s AND status = 'active'""",
            (user_id,),
        )
        rows = cur.fetchall()
        entitlements = [row["module"] for row in rows if row.get("module")]

    if user["role"] == "admin":
        entitlements = [
            "kso",
            "kbs",
            "archie-comms",
            "claude-terminal",
            "civic-watch",
            "legal-watch",
            "gov-watch",
            "news",
            "kytran-mail",
            "market-watch-viewer",
            "market-watch-ai",
            "news-watch",
        ]

    # Build per-product tier map from billing_subscriptions
    # Maps stripe_price_id patterns to tiers; admins get staff (Kytran internal)
    product_tiers = {}
    if user["role"] == "admin":
        for product in entitlements:
            product_tiers[product] = "staff"
    else:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT module, stripe_price_id FROM billing_subscriptions
                   WHERE user_id = %s AND status IN ('active', 'trialing')""",
                (user_id,),
            )
            for row in cur.fetchall():
                module = row.get("module", "")
                price_id = row.get("stripe_price_id", "")
                # Determine tier from price_id suffix convention: _pro, _business, _enterprise
                if "enterprise" in price_id.lower():
                    product_tiers[module] = "enterprise"
                elif "business" in price_id.lower():
                    product_tiers[module] = "business"
                else:
                    product_tiers[module] = "pro"
        # Any entitled product without a subscription row defaults to free
        for product in entitlements:
            if product not in product_tiers:
                product_tiers[product] = "free"

    stripe_customer_id = None
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT stripe_customer_id FROM billing_customers WHERE user_id = %s LIMIT 1",
            (user_id,),
        )
        row = cur.fetchone()
        if row:
            stripe_customer_id = row["stripe_customer_id"]

    return jsonify(
        {
            "sub": str(user["id"]),
            "username": user["username"],
            "email": user["email"] or "",
            "name": user["username"],
            "role": user["role"],
            "language_preference": user.get("language_preference") or "en",
            "entitlements": entitlements,
            "product_tiers": product_tiers,
            "stripe_customer_id": stripe_customer_id,
        }
    )
