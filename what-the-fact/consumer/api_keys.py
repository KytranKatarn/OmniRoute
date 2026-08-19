"""API key storage + resolution (task #2138).

The DB half. All format/hash/compare decisions live in the stdlib-only
``api_key_policy`` so they are unit-tested without a database or Flask.

⚠️ TWO FAILURE DIRECTIONS, DELIBERATELY OPPOSITE.
``resolve_plan`` must fail toward LESS privilege: an unreadable database, a
malformed key or a revoked key all resolve to ``anonymous``, never to keyed.
The limiter as a whole fails OPEN (a limiter bug must not take the site down) —
but privilege must fail CLOSED, or an outage becomes an escalation.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import text

from . import api_key_policy

logger = logging.getLogger(__name__)

MAX_ACTIVE_KEYS_PER_USER = int(os.environ.get("WTF_MAX_API_KEYS_PER_USER", "5"))


def _schema() -> str:
    return os.environ.get("WTF_SCHEMA", "wtf")


def resolve_plan(engine, presented: str | None) -> tuple[str, str | None]:
    """Map a presented API key to ``(plan, key_prefix)``.

    Returns ``("anonymous", None)`` for absent/malformed/unknown/revoked keys —
    every uncertain input lands on the least privilege.
    """
    if not presented:
        return "anonymous", None
    parsed = api_key_policy.parse_key(presented)
    if not parsed:
        return "anonymous", None
    prefix, secret = parsed
    try:
        with engine.begin() as c:
            row = c.execute(
                text(
                    f"SELECT key_hash, plan FROM {_schema()}.api_keys "
                    "WHERE key_prefix = :p AND revoked_at IS NULL"
                ),
                {"p": prefix},
            ).first()
    except Exception as exc:
        # Never log the presented key. A DB blip must not upgrade the caller.
        logger.warning("[api_keys] lookup failed for prefix=%s: %s", prefix, exc)
        return "anonymous", None
    if not row:
        return "anonymous", None
    if not api_key_policy.verify_secret(secret, row[0]):
        return "anonymous", None
    plan = row[1] if row[1] in ("keyed", "paid") else "keyed"
    return plan, prefix


def touch(engine, prefix: str) -> None:
    """Record usage. Best-effort — accounting must never fail a served request."""
    if not prefix:
        return
    try:
        with engine.begin() as c:
            c.execute(
                text(
                    f"UPDATE {_schema()}.api_keys "
                    "SET last_used_at = now(), request_count = request_count + 1 "
                    "WHERE key_prefix = :p"
                ),
                {"p": prefix},
            )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[api_keys] touch failed for prefix=%s: %s", prefix, exc)


def create_key(engine, owner_email: str, label: str | None = None, plan: str = "keyed") -> dict:
    """Mint a key for a user. The full key is returned ONCE and never stored.

    Enforces a per-user cap so a compromised session cannot mint keys forever.
    """
    if not owner_email:
        raise ValueError("owner_email is required")
    if plan not in ("keyed", "paid"):
        plan = "keyed"
    label = (label or "").strip()[:80] or None

    with engine.begin() as c:
        active = c.execute(
            text(
                f"SELECT count(*) FROM {_schema()}.api_keys "
                "WHERE owner_email = :e AND revoked_at IS NULL"
            ),
            {"e": owner_email},
        ).scalar() or 0
        if active >= MAX_ACTIVE_KEYS_PER_USER:
            raise ValueError(
                f"key limit reached ({MAX_ACTIVE_KEYS_PER_USER} active). Revoke one first."
            )
        full, prefix, key_hash = api_key_policy.generate_key()
        c.execute(
            text(
                f"INSERT INTO {_schema()}.api_keys "
                "(key_prefix, key_hash, owner_email, label, plan) "
                "VALUES (:p, :h, :e, :l, :pl)"
            ),
            {"p": prefix, "h": key_hash, "e": owner_email, "l": label, "pl": plan},
        )
    # `key` is the ONLY time this value exists outside the caller's hands.
    return {"key": full, "prefix": prefix, "label": label, "plan": plan}


def list_keys(engine, owner_email: str) -> list[dict]:
    """A user's keys. Never returns key_hash — there is nothing useful in it and
    echoing it would turn a UI bug into a credential leak."""
    if not owner_email:
        return []
    with engine.begin() as c:
        rows = c.execute(
            text(
                f"SELECT key_prefix, label, plan, created_at, last_used_at, "
                f"request_count, revoked_at FROM {_schema()}.api_keys "
                "WHERE owner_email = :e ORDER BY created_at DESC LIMIT 50"
            ),
            {"e": owner_email},
        ).fetchall()
    return [
        {
            "prefix": r[0],
            "label": r[1],
            "plan": r[2],
            "created_at": r[3].isoformat() if r[3] else None,
            "last_used_at": r[4].isoformat() if r[4] else None,
            "request_count": r[5],
            "revoked": r[6] is not None,
        }
        for r in rows
    ]


def revoke_key(engine, owner_email: str, prefix: str) -> bool:
    """Soft-revoke. Scoped to the owner so a guessed prefix cannot kill someone
    else's key. Returns True if a row was actually revoked."""
    if not owner_email or not prefix:
        return False
    with engine.begin() as c:
        res = c.execute(
            text(
                f"UPDATE {_schema()}.api_keys SET revoked_at = now() "
                "WHERE key_prefix = :p AND owner_email = :e AND revoked_at IS NULL"
            ),
            {"p": prefix, "e": owner_email},
        )
        return (res.rowcount or 0) > 0
