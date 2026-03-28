"""API key generation, validation, and rate limiting for Enterprise tenants.

Keys are stored as SHA-256 hashes. The raw key is returned only once on creation.
Rate limiting uses a sliding-window counter per minute.
"""

import hashlib
import logging
import secrets
from datetime import datetime

from core.database import get_db_cursor

logger = logging.getLogger(__name__)


def _hash_key(raw_key: str) -> str:
    """SHA-256 hash of the raw API key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key(
    tenant_id: int,
    name: str,
    permissions: list | None = None,
    rate_limit: int = 1000,
) -> dict:
    """Generate a new API key for a tenant.

    Returns:
        Dict with 'id', 'key' (raw, shown once), 'name', 'permissions', 'rate_limit'.
    """
    from psycopg2.extras import Json

    raw_key = f"kbs_{secrets.token_urlsafe(32)}"
    key_hash = _hash_key(raw_key)
    key_prefix = raw_key[:12]
    perms = permissions or ["read"]

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO api_keys (tenant_id, key_hash, key_prefix, name, permissions, rate_limit)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, tenant_id, key_prefix, name, permissions, rate_limit, created_at
            """,
            (tenant_id, key_hash, key_prefix, name, Json(perms), rate_limit),
        )
        row = cur.fetchone()

    return {**row, "key": raw_key}


def validate_api_key(raw_key: str) -> dict | None:
    """Validate an API key. Returns key metadata if valid, None if invalid/revoked."""
    key_hash = _hash_key(raw_key)

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT id, tenant_id, name, permissions, rate_limit
            FROM api_keys
            WHERE key_hash = %s AND is_active = TRUE
            """,
            (key_hash,),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE api_keys SET last_used_at = NOW() WHERE id = %s",
                (row["id"],),
            )
    return row


def revoke_api_key(key_id: int) -> bool:
    """Revoke an API key by setting is_active = FALSE."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE api_keys SET is_active = FALSE WHERE id = %s RETURNING id",
            (key_id,),
        )
        return cur.fetchone() is not None


def list_api_keys(tenant_id: int) -> list:
    """List all API keys for a tenant (prefix only, no raw key)."""
    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT id, key_prefix, name, permissions, rate_limit,
                   is_active, last_used_at, created_at
            FROM api_keys
            WHERE tenant_id = %s
            ORDER BY created_at DESC
            """,
            (tenant_id,),
        )
        return cur.fetchall()


def check_rate_limit(key_id: int, rate_limit: int) -> dict:
    """Check and increment the rate limit counter for this minute.

    Returns:
        Dict with 'allowed' (bool) and 'remaining' (int).
    """
    window_key = datetime.utcnow().strftime("%Y%m%d%H%M")

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO api_rate_limits (key_id, window_key, count)
            VALUES (%s, %s, 1)
            ON CONFLICT (key_id, window_key)
            DO UPDATE SET count = api_rate_limits.count + 1
            RETURNING count
            """,
            (key_id, window_key),
        )
        row = cur.fetchone()
        current_count = row["count"]

    remaining = max(0, rate_limit - current_count)
    return {
        "allowed": current_count <= rate_limit,
        "remaining": remaining,
        "limit": rate_limit,
    }
