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

_SUBSCRIBED_TIERS = {"starter", "professional", "enterprise", "vip", "pro", "business"}

_PLATFORM = os.environ.get("WTF_PLATFORM_URL", "https://platform.kytranempowerment.com")
_INTERNAL_KEY = os.environ.get("ARCHIE_INTERNAL_KEY", "")


def is_authenticated() -> bool:
    return bool(session.get("wtf_authenticated"))


def get_tier() -> str:
    return session.get("wtf_tier", "free")


def has_paid_tier() -> bool:
    return get_tier() in _SUBSCRIBED_TIERS


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
