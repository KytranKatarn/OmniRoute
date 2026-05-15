"""WTF Consumer — Kytran OAuth SSO + subscription gating."""
import json
import logging
import os
import urllib.parse
import urllib.request

from flask import Blueprint, redirect, request, session

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

_PLATFORM = os.environ.get("WTF_PLATFORM_URL", "https://platform.kytranempowerment.com")
_CLIENT_ID = os.environ.get("WTF_CLIENT_ID", "wtf-consumer")
_CLIENT_SECRET = os.environ.get("WTF_CLIENT_SECRET", "")
_CALLBACK_URL = os.environ.get("WTF_CALLBACK_URL", "")
_SUBSCRIBED_TIERS = {"starter", "professional", "enterprise", "vip", "pro", "business", "kytran", "owner", "admin"}


def is_subscriber() -> bool:
    """True if the current session has a paid subscription tier."""
    if session.get("wtf_tier") in _SUBSCRIBED_TIERS:
        return True
    # Check local Stripe billing subscription as fallback
    email = session.get("wtf_email", "")
    if email:
        try:
            try:
                from .db import get_billing_tier
            except ImportError:
                from db import get_billing_tier
            return get_billing_tier(email) in _SUBSCRIBED_TIERS
        except Exception:
            pass
    return False


def current_username() -> str | None:
    return session.get("wtf_username")


@auth_bp.get("/login")
def login():
    next_url = request.args.get("next", "/")
    session["wtf_next"] = next_url
    callback_url = _CALLBACK_URL or (request.url_root.rstrip("/") + "/auth/callback")
    authorize_url = (
        f"{_PLATFORM}/oauth/authorize"
        f"?client_id={urllib.parse.quote(_CLIENT_ID)}"
        f"&redirect_uri={urllib.parse.quote(callback_url)}"
        f"&response_type=code"
    )
    return redirect(authorize_url)


@auth_bp.get("/auth/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return redirect("/")

    callback_url = _CALLBACK_URL or (request.url_root.rstrip("/") + "/auth/callback")
    try:
        payload = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": callback_url,
                "client_id": _CLIENT_ID,
                "client_secret": _CLIENT_SECRET,
            }
        ).encode()
        req = urllib.request.Request(
            f"{_PLATFORM}/oauth/token",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            token_data = json.loads(resp.read())
    except Exception:
        logger.exception("WTF OAuth token exchange failed")
        return redirect("/")

    user = token_data.get("user") or {}
    session["wtf_username"] = user.get("username") or token_data.get("username")
    session["wtf_email"] = user.get("email", "")
    session["wtf_tier"] = user.get("subscription_tier") or "free"
    session["wtf_authenticated"] = True

    return redirect(session.pop("wtf_next", "/"))


@auth_bp.get("/logout")
def logout():
    session.pop("wtf_username", None)
    session.pop("wtf_tier", None)
    session.pop("wtf_authenticated", None)
    return redirect("/")
