"""
Billing Routes — Stripe webhook, checkout, portal, and product API endpoints.

Blueprint: billing_bp, mounted at /api/billing.
init_billing(app) registers the blueprint and calls init_stripe().
"""

import logging

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from database import get_db_cursor
from services.billing_webhook import process_webhook
from services.stripe_service import (
    create_checkout_session,
    create_portal_session,
    get_customer,
    get_or_create_customer,
    get_publishable_key,
    init_stripe,
    list_module_products,
)

logger = logging.getLogger(__name__)

billing_bp = Blueprint("billing", __name__, url_prefix="/api/billing")


# ---------------------------------------------------------------------------
# 1. Webhook (no auth — verified by Stripe signature)
# ---------------------------------------------------------------------------


@billing_bp.route("/webhook", methods=["POST"])
def webhook():
    """Receive Stripe webhook events.

    No login required — authenticity is verified via Stripe signature header.
    Always returns 200 to prevent Stripe retry floods.
    """
    payload = request.get_data(as_text=False)
    sig_header = request.headers.get("Stripe-Signature", "")

    status_code, body = process_webhook(payload, sig_header)
    return jsonify(body), status_code


# ---------------------------------------------------------------------------
# 2. Publishable key
# ---------------------------------------------------------------------------


@billing_bp.route("/publishable-key", methods=["GET"])
@login_required
def publishable_key():
    """Return the Stripe publishable key for frontend checkout."""
    key = get_publishable_key()
    if not key:
        return jsonify({"error": "Stripe not configured"}), 503
    return jsonify({"publishable_key": key})


# ---------------------------------------------------------------------------
# 3. Customer — GET (lookup)
# ---------------------------------------------------------------------------


@billing_bp.route("/customer", methods=["GET"])
@login_required
def customer_get():
    """Return the current user's billing customer record."""
    record = get_customer(current_user.id)
    if not record:
        return jsonify({"customer": None}), 200
    return jsonify(
        {
            "customer": {
                "stripe_customer_id": record["stripe_customer_id"],
                "email": record["email"],
                "name": record["name"],
            }
        }
    )


# ---------------------------------------------------------------------------
# 4. Customer — POST (create / get-or-create)
# ---------------------------------------------------------------------------


@billing_bp.route("/customer", methods=["POST"])
@login_required
def customer_create():
    """Create (or retrieve) a Stripe customer for the current user."""
    try:
        customer_id = get_or_create_customer(
            user_id=current_user.id,
            email=current_user.email,
            name=getattr(current_user, "display_name", current_user.email),
        )
    except Exception as exc:
        logger.error("Customer creation failed for user %s: %s", current_user.id, exc)
        return jsonify({"error": "Failed to create billing customer"}), 502

    return jsonify({"stripe_customer_id": customer_id}), 201


# ---------------------------------------------------------------------------
# 5. Checkout session
# ---------------------------------------------------------------------------


@billing_bp.route("/checkout", methods=["POST"])
@login_required
def checkout():
    """Create a Stripe Checkout Session.

    Expects JSON: {price_id, success_url, cancel_url}.
    Returns: {url} — the Stripe-hosted checkout page URL.
    """
    data = request.get_json(silent=True) or {}
    price_id = data.get("price_id")
    success_url = data.get("success_url")
    cancel_url = data.get("cancel_url")

    if not all([price_id, success_url, cancel_url]):
        return (
            jsonify({"error": "price_id, success_url, and cancel_url are required"}),
            400,
        )

    # Ensure customer exists
    try:
        customer_id = get_or_create_customer(
            user_id=current_user.id,
            email=current_user.email,
            name=getattr(current_user, "display_name", current_user.email),
        )
    except Exception as exc:
        logger.error("Customer lookup/create failed: %s", exc)
        return jsonify({"error": "Failed to resolve billing customer"}), 502

    try:
        url = create_checkout_session(
            customer_id=customer_id,
            price_id=price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"user_id": str(current_user.id)},
        )
    except Exception as exc:
        logger.error("Checkout session creation failed: %s", exc)
        return jsonify({"error": "Failed to create checkout session"}), 502

    return jsonify({"url": url})


# ---------------------------------------------------------------------------
# 6. Customer portal
# ---------------------------------------------------------------------------


@billing_bp.route("/portal", methods=["POST"])
@login_required
def portal():
    """Create a Stripe Billing Portal session.

    Expects optional JSON: {return_url}.  Defaults to referer or '/'.
    Returns: {url} — the portal URL.
    """
    data = request.get_json(silent=True) or {}
    return_url = data.get("return_url") or request.referrer or "/"

    # Must have an existing customer
    record = get_customer(current_user.id)
    if not record:
        return jsonify({"error": "No billing customer found — create one first"}), 404

    try:
        url = create_portal_session(
            customer_id=record["stripe_customer_id"],
            return_url=return_url,
        )
    except Exception as exc:
        logger.error("Portal session creation failed: %s", exc)
        return jsonify({"error": "Failed to create portal session"}), 502

    return jsonify({"url": url})


# ---------------------------------------------------------------------------
# 7. Products per module
# ---------------------------------------------------------------------------


@billing_bp.route("/products/<module>", methods=["GET"])
@login_required
def products(module):
    """List active billing products for a given module slug."""
    rows = list_module_products(module)
    return jsonify(
        {
            "module": module,
            "products": [
                {
                    "stripe_product_id": r["stripe_product_id"],
                    "stripe_price_id": r["stripe_price_id"],
                    "name": r["name"],
                    "amount_cents": r["amount_cents"],
                    "currency": r["currency"],
                    "interval": r["interval"],
                    "description": r.get("description"),
                }
                for r in rows
            ],
        }
    )


# ---------------------------------------------------------------------------
# 8. Recent webhook events (admin debugging)
# ---------------------------------------------------------------------------


@billing_bp.route("/events", methods=["GET"])
@login_required
def events():
    """List recent billing webhook events (admin only, for debugging)."""
    if getattr(current_user, "role", "") != "admin":
        return jsonify({"error": "admin required"}), 403
    limit = min(int(request.args.get("limit", 50)), 200)
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT id, stripe_event_id, event_type, processed,
                      handler_result, created_at
                 FROM billing_events
                ORDER BY created_at DESC
                LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()

    return jsonify(
        {
            "events": [
                {
                    "id": r["id"],
                    "stripe_event_id": r["stripe_event_id"],
                    "event_type": r["event_type"],
                    "processed": r["processed"],
                    "handler_result": r["handler_result"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ]
        }
    )


# ---------------------------------------------------------------------------
# init_billing — called from app.py
# ---------------------------------------------------------------------------


def init_billing(app):
    """Register the billing blueprint and initialise Stripe SDK."""
    ok = init_stripe()
    app.register_blueprint(billing_bp)
    if ok:
        logger.info("Billing routes registered (Stripe configured)")
    else:
        logger.warning(
            "Billing routes registered but Stripe NOT configured — "
            "webhook and checkout will fail until keys are provided"
        )
