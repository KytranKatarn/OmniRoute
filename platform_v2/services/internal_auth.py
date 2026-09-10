"""ONE gate for the platform's machine-to-machine surface — per-caller keys, scoped (#6657).

WHY
    Every ``/api/internal/*`` route (44 of them in app.py) was guarded by plain
    equality against a single ``INTERNAL_API_KEY`` shared by SEVEN compose services
    plus media_hub and KSO, with three disagreeing implementations elsewhere (one
    non-constant-time, one that failed OPEN when its env var was unset). Holding
    the key anywhere — e.g. reading it off the engine's unauthenticated websocket
    — meant holding everything: Playwright session cookies, LinkedIn 2FA codes,
    owner mail bodies, and the two routes that clear a Tier-2 human approval.

WHAT
    * Each caller gets its OWN key from the environment (``CALLER_ENV``); the
      key that matches identifies the caller, and ``CALLER_SCOPES`` says which
      route FAMILIES it may reach. Nobody holds ``*``.
    * ``require_internal_scope(scope)`` is the only decorator; comparison is
      ``hmac.compare_digest``; both header forms are accepted
      (``Authorization: Bearer`` and ``X-Internal-Key``) so no caller changes code
      — compose maps each caller's existing env var NAME to its per-caller VALUE.
    * DB-free on purpose: ``notify`` must work while the database is down.
    * The legacy flat ``INTERNAL_API_KEY`` is still accepted as a FULL-scope key
      while ``INTERNAL_KEY_LEGACY_ACCEPT`` != ``"0"`` (default on), logging a
      WARNING per request so the rollout can be measured; the final PR flips the
      default and deletes the branch.
    * Keys are read at REQUEST time. An import-time read is exactly how
      ``account_center/notify_routes.py`` could not be rotated without a restart.
    * Fail CLOSED: an unset env var is skipped; no configured key ⇒ 401.

ROLLOUT — see the plan (#6657): platform first (all callers still legacy), then
one caller at a time with ``docker compose up -d --no-deps <svc>`` (restart does
not re-read env_file, KB #268829), proving from inside each container that an
in-scope route is 200 and an out-of-scope route is 403.
"""

from __future__ import annotations

import hmac
import logging
import os
from functools import wraps

from flask import g, jsonify, request

logger = logging.getLogger(__name__)

LEGACY_ENV = "INTERNAL_API_KEY"
# The account-center notify path historically compared against a DIFFERENT
# shared secret, ARCHIE_INTERNAL_KEY, which KBS (kbs_signal / kbs_call_center)
# presents to /tools/account-center/api/internal/notify. It is a real internal
# credential, not the flat key. Accept it as a SECOND legacy alias (same
# full-scope + WARNING + LEGACY_ACCEPT gating) so collapsing the four impls
# does not silently 401 KBS on the first platform recreate. Removed with the
# flat legacy key at the final cutover.
LEGACY_ENV_ALT = "ARCHIE_INTERNAL_KEY"
LEGACY_ACCEPT_ENV = "INTERNAL_KEY_LEGACY_ACCEPT"
LEGACY_CALLER = "legacy"

# caller name -> env var holding that caller's key. The NAME is the identity.
CALLER_ENV: dict[str, str] = {
    "archie_comms": "INTERNAL_API_KEY_ARCHIE_COMMS",
    "archie_engine": "INTERNAL_API_KEY_ARCHIE_ENGINE",
    "media_hub": "INTERNAL_API_KEY_MEDIA_HUB",
    "browser": "INTERNAL_API_KEY_BROWSER",  # archie_browser, archie_browser_login, archie_scraper
    "scripts": "INTERNAL_API_KEY_SCRIPTS",  # host cron: deploy_drift_check, streaming_watchdog
    "kbs": "INTERNAL_API_KEY_KBS",
    "kso": "INTERNAL_API_KEY_KSO",
    "watch": "INTERNAL_API_KEY_WATCH",  # WTF / gov / civic / legal / market products
}

# Route FAMILIES. Finer than the 5 verbs (approve is not "write"), coarser than
# per-route names (a caller that may read mail may read a mail message).
SCOPES: frozenset[str] = frozenset(
    {
        "dhq:chat",
        "coo",
        "mail",
        "approvals:read",
        "approvals:decide",
        "approvals:request",
        "delegation",
        "engine",
        "repair:read",
        "repair:write",
        "sessions",
        "fleet",
        "notify",
        "compliance",
        "agents:manage",  # cockpit agent lifecycle: create(Tier-2)/assign/shift-state/skills/budget (#6663 Phase 2)
        "cloud:code",  # cockpit ask-first cloud CODING lane: explicit, per-call, never auto-escalation (#6653 Phase 3a)
    }
)

CALLER_SCOPES: dict[str, frozenset[str]] = {
    # comms IS the owner's chat/Telegram approval surface — approve/deny is legitimate there.
    "archie_comms": frozenset(
        {
            "dhq:chat",
            "coo",
            "mail",
            "approvals:read",
            "approvals:decide",
            "delegation",
            "repair:read",
            "agents:manage",
            "cloud:code",
        }
    ),
    # the engine builds and reports; it never approves, never touches sessions or mail.
    "archie_engine": frozenset({"dhq:chat", "delegation", "engine", "repair:read", "repair:write"}),
    "media_hub": frozenset({"notify", "approvals:request", "fleet"}),
    "browser": frozenset({"sessions"}),
    "scripts": frozenset({"notify"}),
    "kbs": frozenset({"delegation", "notify"}),
    "kso": frozenset({"compliance"}),
    # WTF / gov / civic / legal / market products call /api/internal/notify for
    # ingest-freshness + drift alerts. (The earlier `access:check` grant was
    # dead — that endpoint uses X-Internal-Token/AC_INTERNAL_TOKEN, a separate
    # mechanism no require_internal_scope route enforces — so it bought watch
    # nothing and would have 403'd its real call on cutover.)
    "watch": frozenset({"notify"}),
}

# endpoint name -> scope, filled by the decorator at registration time. The
# completeness test walks app.url_map and fails on any /api/internal/ rule that
# is not in here — a future route cannot ship unscoped by accident.
_SCOPED_ENDPOINTS: dict[str, str] = {}


def _presented_token() -> str:
    auth = request.headers.get("Authorization", "")
    if auth:
        scheme, _, token = auth.strip().partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            return token.strip()
    return request.headers.get("X-Internal-Key", "").strip()


def _matches(presented: str, configured: str) -> bool:
    return bool(configured) and hmac.compare_digest(presented.encode(), configured.encode())


def legacy_accepted() -> bool:
    return os.getenv(LEGACY_ACCEPT_ENV, "1").strip() != "0"


def identify_caller(presented: str | None = None) -> tuple[str, frozenset[str]] | None:
    """(caller, scopes) for the key on this request, or None. Legacy → full scope + WARNING."""
    token = presented if presented is not None else _presented_token()
    if not token:
        return None
    for caller, env in CALLER_ENV.items():
        if _matches(token, os.getenv(env, "").strip()):
            return caller, CALLER_SCOPES[caller]
    if legacy_accepted():
        for legacy_env in (LEGACY_ENV, LEGACY_ENV_ALT):
            if _matches(token, os.getenv(legacy_env, "").strip()):
                logger.warning(
                    "legacy %s used caller_ip=%s %s %s — migrate this caller to its own key",
                    legacy_env,
                    request.headers.get("X-Forwarded-For", request.remote_addr),
                    request.method,
                    request.path,
                )
                return LEGACY_CALLER, SCOPES
    return None


def caller_has_scope(scope: str) -> bool:
    """Non-decorator form for routes that OR the key with a session (compliance)."""
    found = identify_caller()
    if not found:
        return False
    caller, scopes = found
    g.internal_caller = caller
    return scope in scopes


def require_internal_scope(scope: str):
    """401 without a recognised key, 403 with one that lacks ``scope``."""
    if scope not in SCOPES:
        raise ValueError(f"unknown internal scope {scope!r} — add it to SCOPES and a caller first")

    def decorator(f):
        _SCOPED_ENDPOINTS[f.__name__] = scope

        @wraps(f)
        def decorated(*args, **kwargs):
            found = identify_caller()
            if not found:
                return jsonify({"error": "unauthorized"}), 401
            caller, scopes = found
            g.internal_caller = caller
            if scope not in scopes:
                logger.warning(
                    "internal scope denied caller=%s required=%s %s %s", caller, scope, request.method, request.path
                )
                return jsonify({"error": "scope_denied", "required": scope, "caller": caller}), 403
            return f(*args, **kwargs)

        return decorated

    return decorator
