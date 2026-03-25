"""
Shared database connection for AI Bridge modules.

All ai_bridge files should import from here instead of defining local get_db().

Usage:
    from db import get_db
    conn = get_db()
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor


def _get_db_password():
    """Read DB password from Docker secret file, fall back to env var."""
    secret_file = os.getenv("DB_PASSWORD_FILE", "/run/secrets/db_password")
    try:
        with open(secret_file, "r") as f:
            pw = f.read().strip()
            if pw:
                return pw
    except (FileNotFoundError, PermissionError):
        pass
    return os.getenv("DB_PASSWORD", "")


def get_db(cursor_factory=None):
    """Get database connection with optional cursor factory."""
    kwargs = {
        "host": os.getenv("DB_HOST", "archie_database"),
        "port": os.getenv("DB_PORT", "5432"),
        "database": os.getenv("DB_NAME", "archie"),
        "user": os.getenv("DB_USER", "archie"),
        "password": _get_db_password(),
    }
    if cursor_factory:
        kwargs["cursor_factory"] = cursor_factory
    return psycopg2.connect(**kwargs)


def get_db_dict():
    """Get database connection with RealDictCursor."""
    return get_db(cursor_factory=RealDictCursor)
