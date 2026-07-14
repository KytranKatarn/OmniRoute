"""Kytran product access gating — shared pattern for all standalone products.

Usage:
    from .access import require_product_access

    @bp.get("/premium-content")
    @require_product_access("wtf-premium")
    def premium_content():
        ...

The decorator checks session["wtf_tier"] (set by OAuth callback in auth.py).
For products that need stricter platform-level verification, set
KYTRAN_PLATFORM_URL + KYTRAN_INTERNAL_KEY env vars to call the access check API.
"""
import logging
import os
import urllib.request
import urllib.parse
from functools import wraps
from flask import redirect, request, session

logger = logging.getLogger(__name__)

# Canonical subscribed-tier set — shared single source of truth (tiers.py).
# The old private copy here also omitted kytran/owner/admin (the owner got gated).
try:
    from .tiers import SUBSCRIBED_TIERS as _SUBSCRIBED_TIERS
except ImportError:  # script-style import (gunicorn runs the package flat)
    from tiers import SUBSCRIBED_TIERS as _SUBSCRIBED_TIERS

_PLATFORM = os.environ.get("WTF_PLATFORM_URL", "https://platform.kytranempowerment.com")
_INTERNAL_KEY = os.environ.get("ARCHIE_INTERNAL_KEY", "")


def is_authenticated() -> bool:
    return bool(session.get("wtf_authenticated"))


def get_tier() -> str:
    return session.get("wtf_tier", "free")


def user_has_bundle(product_id: str) -> bool:
    """Return True if session entitlements include the given product_id.

    wtf_entitlements is a list of product IDs injected by the OAuth /userinfo
    callback (e.g. ['civic-watch', 'wtf-starter'] for intelligence_bundle holders).
    """
    entitlements = session.get("wtf_entitlements", [])
    return product_id in entitlements


def has_paid_tier() -> bool:
    """Return True if the user has any paid access to WTF content.

    Checks (in order):
    1. Session wtf_tier is a known subscribed tier (direct WTF subscription).
    2. Session wtf_entitlements contains 'wtf-starter' (bundle access via OAuth).
    """
    if get_tier() in _SUBSCRIBED_TIERS:
        return True
    # Bundle holders get 'wtf-starter' injected into wtf_entitlements by OAuth
    if user_has_bundle("wtf-starter"):
        return True
    return False


def user_has_beat_access(beat_slug: str) -> bool:
    """True if user has a full paid tier OR a beat subscription for this slug."""
    if has_paid_tier():
        return True
    email = session.get("wtf_email", "")
    if not email:
        return False
    try:
        # Check session cache first
        cached = session.get("wtf_beats", [])
        if beat_slug in cached:
            return True
        # Fall back to DB
        try:
            from .db import get_user_beats
        except ImportError:
            from db import get_user_beats
        beats = get_user_beats(email)
        session["wtf_beats"] = beats  # refresh cache
        return beat_slug in beats
    except Exception:
        return False


def check_platform_access(user_id: int, product_slug: str) -> bool:
    """Call platform_v2 /api/access/check for a hard access_grants verification.

    Returns True if the platform says the user has access.
    Falls back to False on any error so gating fails safely.
    """
    if not _INTERNAL_KEY:
        return False
    try:
        url = (
            f"{_PLATFORM}/tools/account-center/api/access/check"
            f"?user_id={user_id}&product={urllib.parse.quote(product_slug)}"
        )
        req = urllib.request.Request(url, headers={"X-Internal-Key": _INTERNAL_KEY})
        with urllib.request.urlopen(req, timeout=5) as resp:
            import json
            data = json.loads(resp.read())
            return bool(data.get("has_access"))
    except Exception as exc:
        logger.warning("[access] platform check failed for %s/%s: %s", user_id, product_slug, exc)
        return False


def require_product_access(product_slug: str, redirect_to: str = "/login"):
    """Decorator: gate a route behind product subscription.

    Unauthenticated → redirect to login.
    Authenticated free tier → render 402 JSON or redirect to upgrade page.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not is_authenticated():
                return redirect(redirect_to + "?next=" + urllib.parse.quote(request.path))
            if not has_paid_tier():
                from flask import jsonify, make_response
                resp = make_response(
                    jsonify({
                        "error": "subscription_required",
                        "product": product_slug,
                        "upgrade_url": f"{_PLATFORM}/subscription",
                    }),
                    402,
                )
                return resp
            return fn(*args, **kwargs)
        return wrapper
    return decorator
