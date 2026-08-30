"""WTF Consumer — Kytran OAuth SSO + subscription gating."""
import hmac
import json
import logging
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request

from flask import Blueprint, jsonify, redirect, request, session

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

# Browser-facing: users' browsers navigate here for the authorize page.
_PLATFORM = os.environ.get("WTF_PLATFORM_URL", "https://platform.kytranempowerment.com")
# Server-side only: VPS→hub token exchange uses mesh (never CDN — 60s cap, bypasses queue).
_TOKEN_PLATFORM = os.environ.get("WTF_TOKEN_PLATFORM_URL", "http://100.64.0.4:3000")
_CLIENT_ID = os.environ.get("WTF_CLIENT_ID", "wtf-consumer")
_CLIENT_SECRET = os.environ.get("WTF_CLIENT_SECRET", "")
# Explicit default prevents http:// mismatches when Flask runs behind Caddy proxy.
_CALLBACK_URL = os.environ.get("WTF_CALLBACK_URL", "https://what-the-fact.com/auth/callback")
# Canonical subscribed-tier set — shared single source of truth (tiers.py).
# The old private copy here omitted solo/team/agency → paying subscribers paywalled.
try:
    from .tiers import SUBSCRIBED_TIERS as _SUBSCRIBED_TIERS
except ImportError:  # script-style import (gunicorn runs the package flat)
    from tiers import SUBSCRIBED_TIERS as _SUBSCRIBED_TIERS


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


# Owner / admin identity — the platform owner's logged-in session is admin across the
# consumer's admin endpoints (no separate key needed in the browser).
_OWNER_EMAILS = {e.strip().lower() for e in os.environ.get(
    "WTF_OWNER_EMAILS", "kytranempowerment@gmail.com,kytran@kytranempowerment.com"
).split(",") if e.strip()}
_OWNER_TIERS = {"owner", "admin", "kytran"}


def is_owner() -> bool:
    """True if the logged-in session belongs to the platform owner (Kytran) / an admin."""
    if not session.get("wtf_authenticated"):
        return False
    if (session.get("wtf_tier") or "").lower() in _OWNER_TIERS:
        return True
    return (session.get("wtf_email") or "").strip().lower() in _OWNER_EMAILS


def admin_gate():
    """Shared admin gate for consumer admin endpoints. Grants access to the owner's logged-in
    session OR a matching X-Admin-Key header. FAILS CLOSED (no allow-if-unset). Returns a
    Flask (json, status) error tuple to abort the request, or None when access is granted."""
    if is_owner():
        return None
    key = os.getenv("WTF_ADMIN_KEY", "")
    if not key:
        return jsonify({"error": "admin not configured — log in as owner or set WTF_ADMIN_KEY"}), 503
    if request.headers.get("X-Admin-Key") != key:
        return jsonify({"error": "unauthorized"}), 401
    return None


def current_username() -> str | None:
    return session.get("wtf_username")


def _safe_next(target: str | None, default: str = "/") -> str:
    """Return ``target`` only if it is a same-site relative path.

    Anything a browser would resolve to a foreign origin falls back to
    ``default``: absolute URLs (``https://evil.com``), protocol-relative
    (``//evil.com``) and backslash-normalised (``/\\evil.com``) — browsers
    normalise the backslash to ``/``, so it must be folded BEFORE the check.
    """
    if not target or not isinstance(target, str):
        return default
    candidate = target.strip().replace("\\", "/")
    if not candidate.startswith("/") or candidate.startswith("//"):
        return default
    return candidate


@auth_bp.get("/login")
def login():
    # Sanitise on the way IN so a hostile value never reaches the session.
    # It is sanitised again on the way out (defence in depth: an existing
    # cookie may already carry a pre-fix value).
    next_url = _safe_next(request.args.get("next"))
    session["wtf_next"] = next_url
    # CSRF: mint a single-use state. The platform authorize endpoint echoes it
    # back on the callback redirect (oauth_provider.py), and the callback
    # REQUIRES it to match — without this there is nothing to validate and any
    # attacker-supplied code logs the victim into the attacker's account.
    state = secrets.token_urlsafe(32)
    session["wtf_oauth_state"] = state
    callback_url = _CALLBACK_URL or (request.url_root.rstrip("/") + "/auth/callback")
    authorize_url = (
        f"{_PLATFORM}/oauth/authorize"
        f"?client_id={urllib.parse.quote(_CLIENT_ID)}"
        f"&redirect_uri={urllib.parse.quote(callback_url)}"
        f"&response_type=code"
        f"&state={urllib.parse.quote(state)}"
    )
    return redirect(authorize_url)


@auth_bp.get("/auth/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return redirect("/")

    # CSRF: the state must be PRESENT and match the one /login minted.
    # Both halves are load-bearing. Comparing two absent values authorises a
    # forged callback -- the state-omission bypass that hit the shared
    # kytran_auth client across the fleet (KB #299307). popping it makes the
    # state single-use, so a captured callback URL cannot be replayed.
    state = request.args.get("state")
    expected = session.pop("wtf_oauth_state", None)
    if not state or not expected or not hmac.compare_digest(state, expected):
        logger.warning(
            "WTF OAuth callback rejected: state %s",
            "missing" if not state else ("no session state" if not expected else "mismatched"),
        )
        # Distinct destination on purpose: a token-exchange failure also
        # redirects to "/", so without this marker an acceptance probe cannot
        # tell "rejected at the state check" from "got past it and failed
        # later" -- which is exactly how a vulnerable build reads as fixed.
        return redirect("/?login=state_error")

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
            f"{_TOKEN_PLATFORM}/oauth/token",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error("WTF OAuth token exchange HTTP %s: %s", e.code, body)
        return redirect("/")
    except Exception:
        logger.exception("WTF OAuth token exchange failed")
        return redirect("/")

    user = token_data.get("user") or {}
    session["wtf_username"] = user.get("username") or token_data.get("username")
    session["wtf_email"] = user.get("email", "")
    # T3027: product_tiers["wtf"] from billing (canonical source) takes precedence
    _pt = user.get("product_tiers") or {}
    session["wtf_tier"] = _pt.get("wtf") or user.get("subscription_tier") or "free"
    # Bundle entitlements — list of product_ids the user has active subscriptions for.
    # Used by access.py user_has_bundle() to gate bundle-purchased products (#3025).
    session["wtf_entitlements"] = user.get("entitlements") or []
    session["wtf_authenticated"] = True

    return redirect(_safe_next(session.pop("wtf_next", "/")))


@auth_bp.get("/logout")
def logout():
    session.pop("wtf_username", None)
    session.pop("wtf_email", None)
    session.pop("wtf_tier", None)
    session.pop("wtf_entitlements", None)
    session.pop("wtf_beats", None)
    session.pop("wtf_authenticated", None)
    return redirect("/")
