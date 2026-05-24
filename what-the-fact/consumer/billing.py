"""WTF Consumer Stripe billing — Starter $19/mo CAD."""
import logging
import os

import stripe
from flask import Blueprint, jsonify, redirect, request, session

billing_bp = Blueprint("billing", __name__)
logger = logging.getLogger(__name__)

_STRIPE_KEY = os.environ.get("WTF_STRIPE_KEY", "")
_WEBHOOK_SECRET = os.environ.get("WTF_STRIPE_WEBHOOK_SECRET", "")
_APP_URL = os.environ.get("WTF_APP_URL", "https://what-the-fact.com")
_PRICE_STARTER = os.environ.get("WTF_STRIPE_PRICE_STARTER", "")

_SUBSCRIBED_TIERS = {"starter", "professional", "enterprise", "vip", "pro", "business", "kytran", "owner", "admin"}


def _get_beat_price_id(beat_slug: str) -> str:
    env_key = f"WTF_STRIPE_PRICE_BEAT_{beat_slug.upper().replace('-', '_')}"
    return os.environ.get(env_key, "")


def _upgrade_user(email, tier, stripe_customer_id=None, stripe_subscription_id=None):
    try:
        from .db import get_db
    except ImportError:
        from db import get_db

    conn = get_db()
    conn.execute(
        """
        INSERT INTO billing_subscriptions
            (email, tier, stripe_customer_id, stripe_subscription_id, status, updated_at)
        VALUES (?, ?, ?, ?, 'active', CURRENT_TIMESTAMP)
        ON CONFLICT(email) DO UPDATE SET
            tier                   = excluded.tier,
            stripe_customer_id     = COALESCE(excluded.stripe_customer_id, stripe_customer_id),
            stripe_subscription_id = COALESCE(excluded.stripe_subscription_id, stripe_subscription_id),
            status                 = 'active',
            updated_at             = CURRENT_TIMESTAMP
        """,
        (email, tier, stripe_customer_id, stripe_subscription_id),
    )
    conn.commit()
    conn.close()
    logger.info("WTF: upgraded %s to %s", email, tier)


def _downgrade_by_customer(stripe_customer_id):
    try:
        try:
            from .db import get_db
        except ImportError:
            from db import get_db

        conn = get_db()
        conn.execute(
            "UPDATE billing_subscriptions SET status='cancelled', tier='free', updated_at=CURRENT_TIMESTAMP"
            " WHERE stripe_customer_id = ?",
            (stripe_customer_id,),
        )
        conn.commit()
        conn.close()
    except Exception:
        logger.exception("WTF downgrade failed for customer %s", stripe_customer_id)


@billing_bp.route("/billing/checkout/starter")
def checkout():
    if not _PRICE_STARTER or not _STRIPE_KEY:
        return "Billing not configured — contact support@kytranempowerment.com", 503
    authenticated = session.get("wtf_authenticated")
    if not authenticated:
        return redirect(f"/login?next=/billing/checkout/starter")
    stripe.api_key = _STRIPE_KEY
    cs = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="subscription",
        line_items=[{"price": _PRICE_STARTER, "quantity": 1}],
        customer_email=session.get("wtf_email"),
        metadata={"tier": "starter", "email": session.get("wtf_email", "")},
        success_url=f"{_APP_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{_APP_URL}/billing/cancel",
    )
    return redirect(cs.url)


@billing_bp.route("/billing/success")
def success():
    session_id = request.args.get("session_id")
    if session_id and _STRIPE_KEY:
        stripe.api_key = _STRIPE_KEY
        try:
            cs = stripe.checkout.Session.retrieve(session_id)
            email = (cs.metadata or {}).get("email") or cs.customer_email
            tier = (cs.metadata or {}).get("tier", "starter")
            if email:
                _upgrade_user(email, tier, cs.customer, cs.subscription)
                # Update session tier immediately
                if session.get("wtf_email", "").lower() == email.lower():
                    session["wtf_tier"] = tier
        except Exception:
            logger.exception("WTF billing success verify failed")
    return redirect("/account?subscribed=1")


@billing_bp.route("/billing/cancel")
def cancel():
    return redirect("/join#pricing")


@billing_bp.route("/billing/portal")
def portal():
    """Redirect to Stripe Customer Portal for subscription management."""
    if not _STRIPE_KEY:
        return "Billing not configured — contact support@kytranempowerment.com", 503
    email = session.get("wtf_email")
    if not email:
        return redirect("/login?next=/billing/portal")
    try:
        try:
            from .db import get_db
        except ImportError:
            from db import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT stripe_customer_id FROM billing_subscriptions"
            " WHERE LOWER(email) = LOWER(?) AND status = 'active'",
            (email,),
        ).fetchone()
        conn.close()
    except Exception:
        logger.exception("WTF portal: DB lookup failed")
        row = None

    if not row or not row[0]:
        return redirect("/billing/checkout/starter")

    stripe.api_key = _STRIPE_KEY
    try:
        ps = stripe.billing_portal.Session.create(
            customer=row[0],
            return_url=f"{_APP_URL}/account",
        )
        return redirect(ps.url)
    except Exception:
        logger.exception("WTF billing portal session failed")
        return redirect("/account?portal_error=1")


@billing_bp.route("/billing/webhook", methods=["POST"])
def webhook():
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")
    if not _WEBHOOK_SECRET:
        return jsonify({"error": "webhook not configured"}), 503
    try:
        event = stripe.Webhook.construct_event(payload, sig, _WEBHOOK_SECRET)
    except Exception as exc:
        logger.warning("WTF webhook signature error: %s", exc)
        return jsonify({"error": "invalid signature"}), 400

    et = event["type"]
    obj = event["data"]["object"]

    if et == "checkout.session.completed":
        meta = obj.get("metadata") or {}
        email = meta.get("email") or obj.get("customer_email")
        # Beat micro-subscription checkout
        if meta.get("subscription_type") == "beat":
            beat_slug = meta.get("beat_slug", "")
            if email and beat_slug:
                try:
                    try:
                        from .db import upsert_beat_subscription
                    except ImportError:
                        from db import upsert_beat_subscription
                    upsert_beat_subscription(
                        email, beat_slug,
                        obj.get("subscription", ""),
                        meta.get("price_id", ""),
                        "active"
                    )
                    logger.info("WTF webhook: beat subscription activated beat=%s email=%s", beat_slug, email)
                except Exception:
                    logger.exception("WTF webhook: beat upsert failed beat=%s email=%s", beat_slug, email)
            return jsonify({"received": True})
        # Bundle checkouts: tier sync happens via OAuth entitlements on next login.
        # Just log and return 200 — do not call _upgrade_user for bundle purchases.
        if meta.get("subscription_type") == "bundle":
            bundle_id = meta.get("bundle_id", "unknown")
            logger.info("WTF webhook: bundle checkout completed bundle=%s email=%s — tier sync deferred to OAuth", bundle_id, email)
            return jsonify({"received": True})
        tier = meta.get("tier", "starter")
        if email:
            _upgrade_user(email, tier, obj.get("customer"), obj.get("subscription"))

    elif et in ("customer.subscription.deleted", "customer.subscription.paused"):
        # Cancel any beat subscription tied to this Stripe subscription ID
        try:
            try:
                from .db import cancel_beat_by_stripe_sub
            except ImportError:
                from db import cancel_beat_by_stripe_sub
            cancel_beat_by_stripe_sub(obj.get("id", ""))
        except Exception:
            logger.exception("WTF webhook: cancel_beat_by_stripe_sub failed sub=%s", obj.get("id"))
        _downgrade_by_customer(obj.get("customer"))

    return jsonify({"received": True})
