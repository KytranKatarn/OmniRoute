"""Cross-Watch proxy routes for WTF consumer.

All requests are forwarded to the hub at CROSS_WATCH_HUB_URL via the
Headscale mesh (http://100.64.0.4:3000) — NEVER the public hostname.

This layer adds, server-side only:
  - Authorization: Bearer CROSS_WATCH_SERVICE_TOKEN
  - X-User-Email: <session wtf_email>

Security: this module NEVER forwards CROSS_WATCH_SERVICE_TOKEN to the
browser.  All hub calls are server-to-server only.

AUTH (fixed 2026-08-18, task #5747).  Every route here used to be reachable
anonymously.  Measured live from the public internet: the six public GETs
answered 200 with real data, and the five user-scoped routes failed closed only
BY ACCIDENT — at the hub, because an empty ``X-User-Email`` resolved to no user
(``platform_v2/tools/cross_watch/routes.py`` ``_auth_gate``), which also echoed
``{"email": ""}`` back to the caller.  Any change to that hub-side resolver would
have silently opened them.  The gate now lives here, at the edge:

  @_user_api    session required -> 401 immediately, the hub is never called
  @_public_api  stays anonymous (public accountability data) but rate-limited

Bounding the public reads matters because each one is a hub DB query, and
``/search`` fans out across four product tables — an unmetered anonymous path
into the machine that runs the whole platform.
"""

import logging
import os
import urllib.parse
from functools import wraps

import requests as _req
from flask import Blueprint, jsonify, request, session

from .rate_limit import check as _rate_check

logger = logging.getLogger(__name__)

cross_watch_bp = Blueprint("cross_watch", __name__)

_HUB = os.getenv("CROSS_WATCH_HUB_URL", "http://100.64.0.4:3000")
_TOKEN = os.getenv("CROSS_WATCH_SERVICE_TOKEN", "")
_TIMEOUT = 5

# Clamp caller-supplied values before they reach the hub. `limit` used to be
# forwarded verbatim, so ?limit=100000 became the hub's problem.
_MAX_LIMIT = 50
_DEFAULT_LIMIT = 5
_MAX_TITLE = 300
_MAX_QUERY = 200


def _hub_headers() -> dict:
    email = session.get("wtf_email", "")
    return {
        "Authorization": f"Bearer {_TOKEN}",
        "X-User-Email": email,
        "Content-Type": "application/json",
    }


# ── gates ─────────────────────────────────────────────────────────────────────

def _rate_limited():
    """Return a 429 response if the caller is over budget, else None."""
    allowed, retry, limit, window = _rate_check(request.path)
    if allowed:
        return None
    resp = jsonify({
        "error": "rate_limited",
        "retry_after": retry,
        "limit": limit,
        "window_seconds": window,
    })
    resp.status_code = 429
    resp.headers["Retry-After"] = str(retry)
    return resp


def _require_session():
    """Return a 401 response if there is no logged-in user, else None.

    Deliberately does NOT echo the email or say whether a user exists — the hub's
    404 used to leak `{"email": ""}`, which documents the auth model for free.
    """
    if not session.get("wtf_email"):
        return jsonify({"error": "authentication_required"}), 401
    return None


def _public_api(fn):
    """Anonymous but bounded."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        limited = _rate_limited()
        if limited is not None:
            return limited
        return fn(*args, **kwargs)
    return wrapper


def _user_api(fn):
    """Session required. Rejects at the edge — the hub is never contacted."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        denied = _require_session()
        if denied is not None:
            return denied
        limited = _rate_limited()
        if limited is not None:
            return limited
        return fn(*args, **kwargs)
    return wrapper


def _clamp_limit(raw: str) -> str:
    """Bound a caller-supplied ?limit= to something the hub can afford."""
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return str(_DEFAULT_LIMIT)
    return str(max(1, min(n, _MAX_LIMIT)))


# ── proxy helpers ─────────────────────────────────────────────────────────────

def _proxy_get(path: str):
    try:
        r = _req.get(f"{_HUB}{path}", headers=_hub_headers(), timeout=_TIMEOUT)
        return jsonify(r.json()), r.status_code
    except Exception as exc:
        logger.error("[cross_watch] proxy GET %s failed: %s", path, exc)
        return jsonify({"error": "hub unavailable"}), 503


def _proxy_post(path: str, body: dict | None = None):
    try:
        r = _req.post(
            f"{_HUB}{path}",
            headers=_hub_headers(),
            json=body or request.get_json(silent=True) or {},
            timeout=_TIMEOUT,
        )
        return jsonify(r.json()), r.status_code
    except Exception as exc:
        logger.error("[cross_watch] proxy POST %s failed: %s", path, exc)
        return jsonify({"error": "hub unavailable"}), 503


def _proxy_delete(path: str):
    try:
        r = _req.delete(f"{_HUB}{path}", headers=_hub_headers(), timeout=_TIMEOUT)
        return jsonify(r.json()), r.status_code
    except Exception as exc:
        logger.error("[cross_watch] proxy DELETE %s failed: %s", path, exc)
        return jsonify({"error": "hub unavailable"}), 503


def _title_query(extra: dict | None = None) -> str:
    """Shared ?title=&limit= query builder with clamps applied."""
    params = {
        "title": request.args.get("title", "")[:_MAX_TITLE],
        "limit": _clamp_limit(request.args.get("limit", _DEFAULT_LIMIT)),
    }
    if extra:
        params.update(extra)
    return urllib.parse.urlencode(params)


# ── user-scoped routes (session required) ─────────────────────────────────────

@cross_watch_bp.route("/api/cross-watch/alerts")
@_user_api
def alerts():
    return _proxy_get("/api/cross-watch/alerts")


@cross_watch_bp.route("/api/cross-watch/alerts/<int:alert_id>/read", methods=["POST"])
@_user_api
def mark_read(alert_id: int):
    return _proxy_post(f"/api/cross-watch/alerts/{alert_id}/read")


@cross_watch_bp.route("/api/cross-watch/follow", methods=["POST"])
@_user_api
def follow():
    return _proxy_post("/api/cross-watch/follow")


@cross_watch_bp.route("/api/cross-watch/follow/<int:entity_id>", methods=["DELETE"])
@_user_api
def unfollow(entity_id: int):
    return _proxy_delete(f"/api/cross-watch/follow/{entity_id}")


@cross_watch_bp.route("/api/cross-watch/following")
@_user_api
def following():
    return _proxy_get("/api/cross-watch/following")


# ── public routes (anonymous, rate-limited) ───────────────────────────────────

@cross_watch_bp.route("/api/cross-watch/entities")
@_public_api
def entities():
    return _proxy_get("/api/cross-watch/entities")


@cross_watch_bp.route("/api/cross-watch/procurement")
@_public_api
def procurement():
    """Proxy: recent gov_watch tenders matching an article title's entities."""
    return _proxy_get(f"/api/cross-watch/procurement?{_title_query()}")


@cross_watch_bp.route("/api/cross-watch/parliament-votes")
@_public_api
def parliament_votes():
    """Proxy: recent civic_watch parliament votes matching article title entities."""
    return _proxy_get(f"/api/cross-watch/parliament-votes?{_title_query()}")


@cross_watch_bp.route("/api/cross-watch/legal-rulings")
@_public_api
def legal_rulings():
    """Proxy: recent legal_watch rulings matching an article title's entities.
    Covers SCC decisions, regulations, and ethics rulings.
    """
    return _proxy_get(f"/api/cross-watch/legal-rulings?{_title_query()}")


@cross_watch_bp.route("/api/cross-watch/civic-events")
@_public_api
def civic_events():
    """Proxy: recent civic_watch municipal events matching an article title.
    Matches on Canadian city/municipality names; covers council decisions,
    bylaws, permits, and spending.
    """
    return _proxy_get(f"/api/cross-watch/civic-events?{_title_query()}")


@cross_watch_bp.route("/api/cross-watch/search")
@_public_api
def unified_search():
    """Proxy: unified free-text search across all signal types (#3128).

    The most expensive route here — the hub fans out across four product tables —
    so the query string is length-clamped before it is forwarded.
    Returns {query, results:{procurement,parliament_vote,legal_ruling,civic_event}, total}.
    """
    params = {}
    q = request.args.get("q", "").strip()[:_MAX_QUERY]
    if q:
        params["q"] = q
    types_ = request.args.get("types", "").strip()[:200]
    if types_:
        params["types"] = types_
    limit = request.args.get("limit", "").strip()
    if limit:
        params["limit"] = _clamp_limit(limit)
    return _proxy_get(f"/api/cross-watch/search?{urllib.parse.urlencode(params)}")
