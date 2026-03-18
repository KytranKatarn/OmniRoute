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


def get_db(cursor_factory=None):
    """Get database connection with optional cursor factory."""
    kwargs = {
        "host": os.getenv("DB_HOST", "archie_database"),
        "port": os.getenv("DB_PORT", "5432"),
        "database": os.getenv("DB_NAME", "archie"),
        "user": os.getenv("DB_USER", "archie"),
        "password": os.getenv("DB_PASSWORD", ""),
    }
    if cursor_factory:
        kwargs["cursor_factory"] = cursor_factory
    return psycopg2.connect(**kwargs)


def get_db_dict():
    """Get database connection with RealDictCursor."""
    return get_db(cursor_factory=RealDictCursor)
