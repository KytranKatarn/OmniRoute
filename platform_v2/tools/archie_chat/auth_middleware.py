"""
ARCHIE Chat — Dual Authentication Middleware
Supports session cookies (browser) and bearer tokens (API).
"""

import hashlib
import secrets
import time
from collections import defaultdict
from functools import wraps

from flask import request, jsonify, g
from flask_login import current_user

from database import get_db_cursor

# In-memory rate limiter store: user_id -> list of timestamps
_rate_limit_store = defaultdict(list)


def _check_bearer_token():
    """Validate bearer token from Authorization header.

    Hashes token with SHA-256, looks up in chat_api_keys,
    updates last_used_at, returns user dict or None.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    raw_token = auth_header[7:].strip()
    if not raw_token:
        return None

    key_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                SELECT k.id, k.user_id, k.scopes, k.rate_limit,
                       u.username, u.is_admin
                FROM chat_api_keys k
                JOIN users u ON u.id = k.user_id
                WHERE k.key_hash = %s AND k.is_active = TRUE
                """,
                (key_hash,),
            )
            row = cur.fetchone()
            if not row:
                return None

            # Update last_used_at
            cur.execute(
                "UPDATE chat_api_keys SET last_used_at = NOW() WHERE id = %s",
                (row["id"],),
            )

            user_dict = {
                "id": row["user_id"],
                "username": row["username"],
                "is_admin": bool(row["is_admin"]),
                "auth_method": "api_key",
                "scopes": row["scopes"] if row["scopes"] else ["chat"],
                "rate_limit": row["rate_limit"] or 30,
            }
            # C.R.E.E.D. privacy event — PIPEDA: accountability + safeguards
            try:
                from services.creed_privacy_logger import log_api_key_access

                log_api_key_access(
                    scope=",".join(user_dict["scopes"]),
                    endpoint=request.path,
                    granted=True,
                    key_id=row["id"],
                )
            except Exception:
                pass
            return user_dict
    except Exception:
        return None


def chat_auth_required(f):
    """Decorator: try bearer token first, fall back to session cookie.

    Sets g.chat_user with keys: id, username, is_admin, auth_method, scopes, rate_limit.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        # Try bearer token first
        user = _check_bearer_token()
        if user:
            g.chat_user = user
            return f(*args, **kwargs)

        # Fall back to session cookie (flask_login)
        if current_user and current_user.is_authenticated:
            g.chat_user = {
                "id": current_user.id,
                "username": current_user.username,
                "is_admin": getattr(current_user, "is_admin", False),
                "auth_method": "session",
                "scopes": ["chat", "admin"] if getattr(current_user, "is_admin", False) else ["chat"],
                "rate_limit": 60,
            }
            return f(*args, **kwargs)

        return (
            jsonify(
                {
                    "success": False,
                    "error": {
                        "code": "AUTH_FAILED",
                        "message": "Authentication required",
                    },
                }
            ),
            401,
        )

    return decorated


def get_chat_user():
    """Returns the current authenticated chat user from g.chat_user."""
    return getattr(g, "chat_user", None)


def require_scope(scope):
    """Decorator: enforce a required scope on API-key callers.

    Session-authenticated users (browser) always pass — scopes only restrict
    bearer-token keys. Stacks with @chat_auth_required (must come after).

    Usage:
        @chat_auth_required
        @require_scope("admin")
        def my_route(): ...
    """

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = getattr(g, "chat_user", None)
            if user and user.get("auth_method") == "api_key":
                scopes = user.get("scopes") or []
                if scope not in scopes:
                    # C.R.E.E.D. privacy event — PIPEDA: accountability (scope gate)
                    try:
                        from services.creed_privacy_logger import log_privacy_event

                        log_privacy_event(
                            event_type="access_control_check",
                            action="scope_check",
                            outcome="denied",
                            data_category="system",
                            description=(f"API key scope denied: required={scope} " f"granted={scopes}"),
                            details={
                                "required_scope": scope,
                                "granted_scopes": scopes,
                                "endpoint": request.path,
                                "pipeda_principle": "accountability",
                            },
                        )
                    except Exception:
                        pass
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": {
                                    "code": "SCOPE_DENIED",
                                    "message": f"API key missing required scope: {scope}",
                                    "required": scope,
                                    "granted": scopes,
                                },
                            }
                        ),
                        403,
                    )
            return f(*args, **kwargs)

        return decorated

    return decorator


def generate_api_key(user_id, name, rate_limit=30):
    """Create a new API key. Returns the raw key (shown once).

    Format: archie_{48 hex chars}
    Stores SHA-256 hash + first 12 chars as prefix in DB.
    """
    raw_key = "archie_" + secrets.token_hex(24)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO chat_api_keys (user_id, key_hash, key_prefix, name, rate_limit)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (user_id, key_hash, key_prefix, name, rate_limit),
        )
        key_id = cur.fetchone()[0]

    return {"key": raw_key, "key_id": key_id, "prefix": key_prefix}


def check_rate_limit(user_id, limit):
    """Simple in-memory rate limiter. 60-second sliding window.

    Returns True if the request is allowed, False if rate-limited.
    """
    now = time.time()
    window_start = now - 60

    # Prune old entries
    timestamps = _rate_limit_store[user_id]
    _rate_limit_store[user_id] = [t for t in timestamps if t > window_start]

    if len(_rate_limit_store[user_id]) >= limit:
        return False

    _rate_limit_store[user_id].append(now)
    return True
