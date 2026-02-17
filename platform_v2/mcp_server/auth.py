"""
A.R.C.H.I.E. MCP Server - Authentication Module
Phase 50: AI Integration Hub

Handles API key authentication, rate limiting, and permission checking.
"""

import os
import hashlib
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

logger = logging.getLogger("archie_mcp.auth")

# Database configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": os.getenv("DB_PASSWORD", "archie_secure_2024"),
}


class MCPAuthenticator:
    """
    Handles authentication and authorization for MCP requests

    Features:
    - API key validation
    - Rate limiting (per minute and per hour)
    - Permission checking
    - Session management
    """

    def __init__(self):
        self._key_cache: Dict[str, Dict] = {}  # Cache validated keys
        self._cache_ttl = 300  # 5 minutes cache

    def _get_db_connection(self):
        """Get database connection"""
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor

            conn = psycopg2.connect(**DB_CONFIG)
            return conn, conn.cursor(cursor_factory=RealDictCursor)
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            return None, None

    @staticmethod
    def generate_api_key() -> Tuple[str, str]:
        """
        Generate a new API key

        Returns:
            Tuple of (full_key, key_hash)
        """
        # Generate 32 random bytes = 64 hex chars
        key_bytes = secrets.token_bytes(32)
        full_key = f"archie-mcp-{key_bytes.hex()}"
        key_hash = hashlib.sha256(full_key.encode()).hexdigest()
        return full_key, key_hash

    @staticmethod
    def hash_key(api_key: str) -> str:
        """Hash an API key for storage/lookup"""
        return hashlib.sha256(api_key.encode()).hexdigest()

    def validate_api_key(self, api_key: str) -> Optional[Dict]:
        """
        Validate an API key and return key info if valid

        Args:
            api_key: The API key to validate

        Returns:
            Key info dict if valid, None if invalid
        """
        if not api_key:
            return None

        # Check cache first
        key_hash = self.hash_key(api_key)
        if key_hash in self._key_cache:
            cached = self._key_cache[key_hash]
            if cached["cached_at"] > datetime.now() - timedelta(seconds=self._cache_ttl):
                return cached["data"]

        # Query database
        conn, cur = self._get_db_connection()
        if not conn:
            logger.error("Cannot validate API key - database unavailable")
            return None

        try:
            cur.execute(
                """
                SELECT id, user_id, name, permissions, allowed_tools,
                       rate_limit_per_minute, rate_limit_per_hour,
                       is_active, expires_at
                FROM mcp_api_keys
                WHERE key_hash = %s
            """,
                (key_hash,),
            )

            row = cur.fetchone()
            cur.close()
            conn.close()

            if not row:
                logger.warning(f"Invalid API key attempted: {api_key[:16]}...")
                return None

            if not row["is_active"]:
                logger.warning(f"Inactive API key used: {row['name']}")
                return None

            if row["expires_at"] and row["expires_at"] < datetime.now():
                logger.warning(f"Expired API key used: {row['name']}")
                return None

            # Cache the result
            key_info = dict(row)
            self._key_cache[key_hash] = {"data": key_info, "cached_at": datetime.now()}

            # Update last_used_at
            self._update_last_used(row["id"])

            return key_info

        except Exception as e:
            logger.error(f"Error validating API key: {e}")
            if conn:
                conn.close()
            return None

    def _update_last_used(self, key_id: int):
        """Update last_used_at timestamp for a key"""
        conn, cur = self._get_db_connection()
        if not conn:
            return

        try:
            cur.execute(
                """
                UPDATE mcp_api_keys SET last_used_at = NOW()
                WHERE id = %s
            """,
                (key_id,),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"Error updating last_used_at: {e}")
            if conn:
                conn.close()

    def check_rate_limit(self, key_id: int, limit_per_minute: int, limit_per_hour: int) -> Tuple[bool, str]:
        """
        Check if request is within rate limits

        Args:
            key_id: API key ID
            limit_per_minute: Max requests per minute
            limit_per_hour: Max requests per hour

        Returns:
            Tuple of (allowed, reason)
        """
        conn, cur = self._get_db_connection()
        if not conn:
            # If database unavailable, allow request but log warning
            logger.warning("Rate limit check skipped - database unavailable")
            return True, "ok"

        try:
            cur.execute(
                "SELECT check_mcp_rate_limit(%s, %s, %s)",
                (key_id, limit_per_minute, limit_per_hour),
            )
            allowed = cur.fetchone()[0]
            cur.close()
            conn.close()

            if not allowed:
                return False, "Rate limit exceeded"

            return True, "ok"

        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            if conn:
                conn.close()
            return True, "ok"  # Allow on error

    def increment_rate_limit(self, key_id: int):
        """Increment rate limit counters for a key"""
        conn, cur = self._get_db_connection()
        if not conn:
            return

        try:
            cur.execute("SELECT increment_mcp_rate_limit(%s)", (key_id,))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"Error incrementing rate limit: {e}")
            if conn:
                conn.close()

    def check_permission(self, key_info: Dict, required_permission: str) -> bool:
        """
        Check if key has required permission

        Args:
            key_info: Key info from validate_api_key
            required_permission: Permission to check ('read', 'write', 'admin')

        Returns:
            True if permission granted
        """
        permissions = key_info.get("permissions", [])
        if isinstance(permissions, str):
            import json

            permissions = json.loads(permissions)

        # Admin has all permissions
        if "admin" in permissions:
            return True

        # Write includes read
        if required_permission == "read" and "write" in permissions:
            return True

        return required_permission in permissions

    def check_tool_access(self, key_info: Dict, tool_name: str) -> bool:
        """
        Check if key is allowed to use a specific tool

        Args:
            key_info: Key info from validate_api_key
            tool_name: Name of the tool

        Returns:
            True if access granted
        """
        allowed_tools = key_info.get("allowed_tools", [])
        if isinstance(allowed_tools, str):
            import json

            allowed_tools = json.loads(allowed_tools)

        # Empty list means all tools allowed
        if not allowed_tools:
            return True

        return tool_name in allowed_tools

    def create_api_key(
        self,
        user_id: int,
        name: str,
        permissions: List[str] = None,
        allowed_tools: List[str] = None,
        rate_limit_per_minute: int = 60,
        rate_limit_per_hour: int = 1000,
        expires_days: int = None,
    ) -> Optional[str]:
        """
        Create a new API key

        Args:
            user_id: User ID to associate key with
            name: Key name/description
            permissions: List of permissions ['read', 'write', 'admin']
            allowed_tools: List of allowed tool names (empty = all)
            rate_limit_per_minute: Rate limit per minute
            rate_limit_per_hour: Rate limit per hour
            expires_days: Days until expiration (None = never)

        Returns:
            Full API key string, or None on error
        """
        import json

        conn, cur = self._get_db_connection()
        if not conn:
            logger.error("Cannot create API key - database unavailable")
            return None

        try:
            full_key, key_hash = self.generate_api_key()
            key_prefix = full_key[:16]

            expires_at = None
            if expires_days:
                expires_at = datetime.now() + timedelta(days=expires_days)

            cur.execute(
                """
                INSERT INTO mcp_api_keys
                (user_id, key_hash, key_prefix, name, permissions, allowed_tools,
                 rate_limit_per_minute, rate_limit_per_hour, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    user_id,
                    key_hash,
                    key_prefix,
                    name,
                    json.dumps(permissions or ["read"]),
                    json.dumps(allowed_tools or []),
                    rate_limit_per_minute,
                    rate_limit_per_hour,
                    expires_at,
                ),
            )

            key_id = cur.fetchone()["id"]
            conn.commit()
            cur.close()
            conn.close()

            logger.info(f"Created API key '{name}' (ID: {key_id}) for user {user_id}")
            return full_key

        except Exception as e:
            logger.error(f"Error creating API key: {e}")
            if conn:
                conn.rollback()
                conn.close()
            return None

    def revoke_api_key(self, key_id: int) -> bool:
        """
        Revoke (deactivate) an API key

        Args:
            key_id: Key ID to revoke

        Returns:
            True if successful
        """
        conn, cur = self._get_db_connection()
        if not conn:
            return False

        try:
            cur.execute(
                """
                UPDATE mcp_api_keys SET is_active = FALSE
                WHERE id = %s
            """,
                (key_id,),
            )
            conn.commit()
            cur.close()
            conn.close()

            # Clear from cache
            self._key_cache = {k: v for k, v in self._key_cache.items() if v["data"].get("id") != key_id}

            logger.info(f"Revoked API key ID: {key_id}")
            return True

        except Exception as e:
            logger.error(f"Error revoking API key: {e}")
            if conn:
                conn.close()
            return False

    def list_api_keys(self, user_id: int = None) -> List[Dict]:
        """
        List API keys, optionally filtered by user

        Args:
            user_id: Optional user ID to filter by

        Returns:
            List of key info dicts (without sensitive data)
        """
        conn, cur = self._get_db_connection()
        if not conn:
            return []

        try:
            if user_id:
                cur.execute(
                    """
                    SELECT id, user_id, key_prefix, name, permissions, allowed_tools,
                           rate_limit_per_minute, rate_limit_per_hour,
                           is_active, created_at, last_used_at, expires_at
                    FROM mcp_api_keys
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                """,
                    (user_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, user_id, key_prefix, name, permissions, allowed_tools,
                           rate_limit_per_minute, rate_limit_per_hour,
                           is_active, created_at, last_used_at, expires_at
                    FROM mcp_api_keys
                    ORDER BY created_at DESC
                """
                )

            rows = cur.fetchall()
            cur.close()
            conn.close()

            return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Error listing API keys: {e}")
            if conn:
                conn.close()
            return []


# ============================================================================
# Convenience Functions
# ============================================================================

_authenticator = None


def get_authenticator() -> MCPAuthenticator:
    """Get or create the global authenticator instance"""
    global _authenticator
    if _authenticator is None:
        _authenticator = MCPAuthenticator()
    return _authenticator


def validate_request(
    api_key: str, tool_name: str, required_permission: str = "read"
) -> Tuple[bool, str, Optional[Dict]]:
    """
    Validate an MCP request

    Args:
        api_key: API key from request
        tool_name: Tool being called
        required_permission: Required permission level

    Returns:
        Tuple of (valid, error_message, key_info)
    """
    auth = get_authenticator()

    # Validate API key
    key_info = auth.validate_api_key(api_key)
    if not key_info:
        return False, "Invalid or expired API key", None

    # Check rate limit
    allowed, reason = auth.check_rate_limit(
        key_info["id"],
        key_info["rate_limit_per_minute"],
        key_info["rate_limit_per_hour"],
    )
    if not allowed:
        return False, reason, key_info

    # Check permission
    if not auth.check_permission(key_info, required_permission):
        return False, f"Permission denied: requires '{required_permission}'", key_info

    # Check tool access
    if not auth.check_tool_access(key_info, tool_name):
        return False, f"Access denied to tool: {tool_name}", key_info

    # Increment rate limit counter
    auth.increment_rate_limit(key_info["id"])

    return True, "ok", key_info
