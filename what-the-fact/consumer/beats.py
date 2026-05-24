"""WTF Beat (topic) micro-subscription routes — $2/mo CAD per beat (#3015)."""
import logging
import os

import stripe
from flask import Blueprint, abort, jsonify, redirect, render_template, request, session
from sqlalchemy import create_engine, text

try:
    from .access import has_paid_tier, user_has_beat_access
    from .db import get_user_beats
except ImportError:
    from access import has_paid_tier, user_has_beat_access
    from db import get_user_beats

beats_bp = Blueprint("beats", __name__)
logger = logging.getLogger(__name__)

_STRIPE_KEY = os.environ.get("WTF_STRIPE_KEY", "")
_APP_URL = os.environ.get("WTF_APP_URL", "https://what-the-fact.com")
_S = "wtf"

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    return _engine


def _get_beat_price_id(beat_slug: str) -> str:
    env_key = f"WTF_STRIPE_PRICE_BEAT_{beat_slug.upper().replace('-', '_')}"
    return os.environ.get(env_key, "")


@beats_bp.route("/beat/<slug>")
def beat_landing(slug):
    """Public beat landing page — free preview + subscribe CTA."""
    try:
        with _get_engine().connect() as c:
            beat = c.execute(
                text(f"SELECT slug, name, description, stripe_price_id FROM {_S}.beats WHERE slug = :s AND active = TRUE"),
                {"s": slug},
            ).fetchone()
    except Exception:
        logger.exception("beats: DB error fetching beat slug=%s", slug)
        abort(500)

    if not beat:
        abort(404)

    try:
        with _get_engine().connect() as c:
            rows = c.execute(
                text(f"""
                    SELECT a.id, a.title, a.url, a.published_at,
                           s.name AS source_name, s.slug AS source_slug,
                           a.bias_band, a.summary
                    FROM {_S}.articles a
                    LEFT JOIN {_S}.sources s ON s.id = a.source_id
                    WHERE a.beat = :beat
                    ORDER BY a.published_at DESC NULLS LAST
                    LIMIT 10
                """),
                {"beat": slug},
            ).fetchall()
    except Exception:
        logger.exception("beats: DB error fetching articles beat=%s", slug)
        rows = []

    has_access = user_has_beat_access(slug)
    full_sub = has_paid_tier()

    return render_template(
        "beat_landing.html",
        beat=beat,
        articles=rows,
        has_access=has_access,
        full_sub=full_sub,
    )


@beats_bp.route("/subscribe/beat/<slug>")
def subscribe_beat(slug):
    """Create a Stripe Checkout session for a beat micro-subscription."""
    if not session.get("wtf_authenticated"):
        return redirect(f"/login?next=/subscribe/beat/{slug}")

    if not _STRIPE_KEY:
        return "Billing not configured — contact support@kytranempowerment.com", 503

    price_id = _get_beat_price_id(slug)
    if not price_id:
        # Fall back to stripe_price_id stored in wtf.beats if env not set
        try:
            with _get_engine().connect() as c:
                row = c.execute(
                    text(f"SELECT stripe_price_id FROM {_S}.beats WHERE slug = :s AND active = TRUE"),
                    {"s": slug},
                ).fetchone()
            if row and row[0]:
                price_id = row[0]
        except Exception:
            logger.exception("beats: DB error fetching price_id for beat=%s", slug)

    if not price_id:
        logger.warning("beats: no stripe_price_id configured for beat=%s", slug)
        return "This beat is not yet available for subscription — check back soon.", 503

    email = session.get("wtf_email", "")
    stripe.api_key = _STRIPE_KEY
    try:
        cs = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=email or None,
            metadata={
                "subscription_type": "beat",
                "beat_slug": slug,
                "email": email,
                "price_id": price_id,
            },
            success_url=f"{_APP_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{_APP_URL}/beat/{slug}",
        )
        return redirect(cs.url)
    except Exception:
        logger.exception("beats: Stripe checkout session creation failed beat=%s", slug)
        return redirect(f"/beat/{slug}?checkout_error=1")


@beats_bp.route("/account/beats")
def account_beats():
    """List user's active beat subscriptions."""
    if not session.get("wtf_authenticated"):
        return redirect("/login?next=/account/beats")

    email = session.get("wtf_email", "")
    beat_slugs = get_user_beats(email)

    # Enrich with beat names from postgres
    beats = []
    if beat_slugs:
        try:
            placeholders = ", ".join(f":s{i}" for i in range(len(beat_slugs)))
            params = {f"s{i}": v for i, v in enumerate(beat_slugs)}
            with _get_engine().connect() as c:
                rows = c.execute(
                    text(f"SELECT slug, name, description FROM {_S}.beats WHERE slug IN ({placeholders})"),
                    params,
                ).fetchall()
            beats = list(rows)
        except Exception:
            logger.exception("beats: DB error enriching beat slugs for account page")

    return render_template("account_beats.html", beats=beats)


@beats_bp.route("/account/beats/<slug>/cancel", methods=["POST"])
def cancel_beat(slug):
    """Cancel a beat subscription via Stripe + mark local record cancelled."""
    if not session.get("wtf_authenticated"):
        return redirect("/login?next=/account/beats")

    email = session.get("wtf_email", "")
    if not email:
        return redirect("/account/beats")

    try:
        try:
            from .db import get_db, cancel_beat_by_stripe_sub
        except ImportError:
            from db import get_db, cancel_beat_by_stripe_sub

        conn = get_db()
        row = conn.execute(
            "SELECT stripe_subscription_id FROM beat_subscriptions"
            " WHERE LOWER(email)=LOWER(?) AND beat_slug=? AND status='active'",
            (email, slug),
        ).fetchone()
        conn.close()

        if row and row["stripe_subscription_id"] and _STRIPE_KEY:
            stripe.api_key = _STRIPE_KEY
            try:
                stripe.Subscription.cancel(row["stripe_subscription_id"])
            except Exception:
                logger.exception("beats: Stripe cancel failed for sub=%s", row["stripe_subscription_id"])
            cancel_beat_by_stripe_sub(row["stripe_subscription_id"])
        elif row:
            # No Stripe key or no sub ID — cancel locally anyway
            cancel_beat_by_stripe_sub(row["stripe_subscription_id"] or "")

        # Invalidate session cache
        session.pop("wtf_beats", None)

    except Exception:
        logger.exception("beats: cancel_beat failed email=%s slug=%s", email, slug)

    return redirect("/account/beats?cancelled=1")
