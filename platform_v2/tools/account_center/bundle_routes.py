"""
Bundle Routes
=============
Flask routes for Watch Series bundle pricing.

Registered under account_center_bp (no extra url_prefix).

Routes:
  GET  /api/bundles                   — list bundles + their products
  GET  /subscribe/bundle/<bundle_id>  — initiate Stripe checkout (login required)
  POST /billing/webhook/bundle        — Stripe webhook for bundle checkout.session.completed
"""

import logging
import os

import stripe
from flask import jsonify, redirect, request
from flask_login import current_user, login_required

from .bundle_checkout_service import (
    BUNDLE_CATALOG,
    activate_bundle,
    create_bundle_checkout_session,
    get_bundle_products,
)

logger = logging.getLogger(__name__)

_APP_URL = os.getenv("APP_URL", "http://192.168.1.200:3000")
_WEBHOOK_SECRET = os.getenv("STRIPE_BUNDLE_WEBHOOK_SECRET", "")


def register_bundle_routes(bp, admin_required):  # noqa: ARG001 — admin_required kept for pattern consistency
    """Register bundle routes onto the account_center Blueprint."""

    @bp.route("/api/bundles")
    def list_bundles():
        """Return bundle catalog with product lists."""
        result = []
        for bundle_id, info in BUNDLE_CATALOG.items():
            result.append(
                {
                    "bundle_id": bundle_id,
                    "name": info["name"],
                    "description": info["description"],
                    "price_cad": info["price_cad"],
                    "products": get_bundle_products(bundle_id),
                }
            )
        return jsonify({"bundles": result})

    @bp.route("/subscribe/bundle/<bundle_id>")
    @login_required
    def subscribe_bundle(bundle_id):
        """Initiate Stripe Checkout for a bundle subscription."""
        if bundle_id not in BUNDLE_CATALOG:
            return jsonify({"error": "unknown_bundle"}), 404

        success_url = f"{_APP_URL}/tools/account-center?bundle_success=1&bundle_id={bundle_id}"
        cancel_url = f"{_APP_URL}/tools/account-center?bundle_cancel=1"

        email = getattr(current_user, "email", None) or ""
        if not email:
            return jsonify({"error": "no_email_on_account"}), 400

        checkout_url = create_bundle_checkout_session(
            bundle_id=bundle_id,
            email=email,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        if not checkout_url:
            logger.warning("bundle_routes: checkout session creation failed for %s / %s", email, bundle_id)
            return jsonify({"error": "billing_not_configured"}), 503

        return redirect(checkout_url)

    @bp.route("/billing/webhook/bundle", methods=["POST"])
    def bundle_webhook():
        """Stripe webhook — handles checkout.session.completed for bundles.

        For bundle checkouts, tier sync happens via OAuth /oauth/userinfo entitlements
        on the user's next login. This webhook only records the activation in the DB.
        """
        payload = request.get_data()
        sig = request.headers.get("Stripe-Signature", "")

        if not _WEBHOOK_SECRET:
            logger.warning("bundle_routes: STRIPE_BUNDLE_WEBHOOK_SECRET not set — rejecting webhook")
            return jsonify({"error": "webhook not configured"}), 503

        try:
            event = stripe.Webhook.construct_event(payload, sig, _WEBHOOK_SECRET)
        except stripe.error.SignatureVerificationError as exc:
            logger.warning("bundle_routes: webhook signature error: %s", exc)
            return jsonify({"error": "invalid signature"}), 400
        except Exception as exc:
            logger.warning("bundle_routes: webhook parse error: %s", exc)
            return jsonify({"error": "bad payload"}), 400

        et = event["type"]
        obj = event["data"]["object"]

        if et == "checkout.session.completed":
            metadata = obj.get("metadata") or {}
            if metadata.get("subscription_type") != "bundle":
                # Not a bundle checkout — ignore silently, let other webhooks handle it
                return jsonify({"received": True})

            email = metadata.get("email") or obj.get("customer_email", "")
            bundle_id = metadata.get("bundle_id", "")

            if email and bundle_id:
                activate_bundle(
                    email=email,
                    bundle_id=bundle_id,
                    stripe_sub_id=obj.get("subscription"),
                    stripe_customer_id=obj.get("customer"),
                )
                logger.info("bundle_routes: activated bundle %s for %s via webhook", bundle_id, email)
            else:
                logger.warning(
                    "bundle_routes: webhook checkout.session.completed missing email or bundle_id: %s",
                    metadata,
                )

        # All other event types are silently acknowledged
        return jsonify({"received": True})
