"""
Database Schema Helper
Handles automatic schema switching based on sandbox mode
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import session, g
import os
from database import _get_db_password


def get_db_connection(cursor_factory=RealDictCursor):
    """
    Get database connection with automatic schema switching
    Checks session['db_schema'] and sets search_path accordingly

    Usage:
        conn = get_db_connection()
        cur = conn.cursor()
        # Queries will automatically use sandbox or public schema
    """
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )

    # Set schema based on session or g object
    schema = None

    # Try to get schema from flask session
    try:
        from flask import has_request_context

        if has_request_context():
            schema = session.get("db_schema", "public")
    except Exception:
        schema = "public"

    # If not in session, try g object
    if not schema or schema == "public":
        try:
            schema = getattr(g, "db_schema", "public")
        except Exception:
            schema = "public"

    # Set search_path at connection level
    cur = conn.cursor()
    if schema == "sandbox":
        # Sandbox mode: search sandbox first, then public for system tables
        cur.execute("SET search_path TO sandbox, public")
    else:
        # Production mode: only public schema
        cur.execute("SET search_path TO public")
    cur.close()

    return conn


def get_current_schema():
    """
    Get the current database schema being used
    Returns 'sandbox' or 'public'
    """
    try:
        from flask import has_request_context

        if has_request_context():
            return session.get("db_schema", "public")
    except Exception:
        pass

    try:
        return getattr(g, "db_schema", "public")
    except Exception:
        return "public"


def is_sandbox_mode():
    """Check if currently in sandbox mode"""
    return get_current_schema() == "sandbox"


def set_sandbox_mode(enabled=True):
    """Enable or disable sandbox mode for current session"""
    schema = "sandbox" if enabled else "public"

    try:
        from flask import has_request_context

        if has_request_context():
            session["db_schema"] = schema
            session["sandbox_mode"] = enabled
    except Exception:
        pass

    try:
        g.db_schema = schema
        g.sandbox_mode = enabled
    except Exception:
        pass


# Convenience function for backward compatibility
def get_db():
    """Alias for get_db_connection for backward compatibility"""
    return get_db_connection()
