"""
User Context Helper
===================
Provides data isolation utilities for per-user data access.
Ensures non-admin users only see their own data.

Usage:
    from user_context import get_user_filter, filter_query_by_user, require_ownership

Author: A.R.C.H.I.E. Platform
Date: 2026-01-12
"""

from functools import wraps
from flask import abort
from flask_login import current_user


def get_user_filter(table_alias: str = None, user_id_column: str = "user_id") -> str:
    """
    Get SQL WHERE clause for user data isolation.

    Args:
        table_alias: Optional table alias prefix (e.g., 'p' for 'p.user_id')
        user_id_column: Column name for user_id (default: 'user_id')

    Returns:
        SQL WHERE clause string or empty string for admins

    Example:
        filter = get_user_filter()  # Returns "user_id = 123" or ""
        filter = get_user_filter('p')  # Returns "p.user_id = 123" or ""
    """
    if not current_user.is_authenticated:
        return "1=0"  # Return no data for unauthenticated users

    # Admins see all data
    if getattr(current_user, "is_admin", False):
        return ""

    # Build the column reference
    column = f"{table_alias}.{user_id_column}" if table_alias else user_id_column

    return f"{column} = {current_user.id}"


def get_user_filter_params() -> tuple:
    """
    Get parameterized SQL filter for user data isolation.

    Returns:
        Tuple of (clause, params) for use with parameterized queries

    Example:
        clause, params = get_user_filter_params()
        query = f"SELECT * FROM projects WHERE {clause}"
        cursor.execute(query, params)
    """
    if not current_user.is_authenticated:
        return "1=0", []

    if getattr(current_user, "is_admin", False):
        return "1=1", []

    return "user_id = %s", [current_user.id]


def is_admin_user() -> bool:
    """Check if current user is an admin (can see all data)"""
    return current_user.is_authenticated and getattr(current_user, "is_admin", False)


def get_current_user_id() -> int:
    """Get current user's ID or None if not authenticated"""
    if current_user.is_authenticated:
        return current_user.id
    return None


def can_access_resource(resource_user_id: int) -> bool:
    """
    Check if current user can access a resource owned by another user.

    Args:
        resource_user_id: The user_id of the resource owner

    Returns:
        True if current user can access the resource
    """
    if not current_user.is_authenticated:
        return False

    # Admins can access everything
    if getattr(current_user, "is_admin", False):
        return True

    # Users can only access their own resources
    return current_user.id == resource_user_id


def require_ownership(resource_user_id: int, abort_code: int = 403):
    """
    Abort request if user doesn't own the resource.

    Args:
        resource_user_id: The user_id of the resource owner
        abort_code: HTTP status code to return (default: 403)

    Raises:
        HTTPException: If user doesn't have access
    """
    if not can_access_resource(resource_user_id):
        abort(abort_code)


def ownership_required(get_resource_user_id):
    """
    Decorator to require resource ownership for a route.

    Args:
        get_resource_user_id: Function that extracts user_id from request
                             Receives the same args/kwargs as the decorated function

    Example:
        @ownership_required(lambda resource_id: get_project(resource_id).user_id)
        def delete_project(resource_id):
            ...
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            resource_user_id = get_resource_user_id(*args, **kwargs)
            require_ownership(resource_user_id)
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def add_user_id_to_data(data: dict) -> dict:
    """
    Add current user's ID to a data dictionary for inserts.

    Args:
        data: Dictionary of data to insert

    Returns:
        Data dictionary with user_id added
    """
    if current_user.is_authenticated:
        data["user_id"] = current_user.id
    return data


# ============================================================================
# SQL QUERY HELPERS
# ============================================================================


def build_isolated_query(base_query: str, user_id_column: str = "user_id") -> str:
    """
    Build a query with user isolation.

    Args:
        base_query: SQL query with 'WHERE 1=1' placeholder
        user_id_column: Column name for user filtering

    Returns:
        Query with user filter appended if not admin

    Example:
        query = build_isolated_query("SELECT * FROM projects WHERE 1=1")
        # Returns "SELECT * FROM projects WHERE 1=1 AND user_id = 123" for non-admins
    """
    user_filter = get_user_filter(user_id_column=user_id_column)
    if user_filter:
        return f"{base_query} AND {user_filter}"
    return base_query


def get_list_query_with_isolation(
    table: str,
    columns: str = "*",
    order_by: str = "created_at DESC",
    user_id_column: str = "user_id",
) -> str:
    """
    Build a standard list query with user isolation.

    Args:
        table: Table name
        columns: Columns to select (default: *)
        order_by: ORDER BY clause (default: created_at DESC)
        user_id_column: Column for user filtering

    Returns:
        Complete SELECT query with user isolation
    """
    query = f"SELECT {columns} FROM {table} WHERE 1=1"
    user_filter = get_user_filter(user_id_column=user_id_column)
    if user_filter:
        query += f" AND {user_filter}"
    query += f" ORDER BY {order_by}"
    return query


# ============================================================================
# ACTIVITY LOGGING
# ============================================================================


def log_user_activity(
    action: str,
    module: str = None,
    details: dict = None,
    resource_type: str = None,
    resource_id: int = None,
):
    """
    Log user activity to the user_activity_log table.

    Args:
        action: Action performed (e.g., 'create', 'update', 'delete')
        module: Module name (e.g., 'app_builder', 'website_builder')
        details: Additional details as dict
        resource_type: Type of resource (e.g., 'project', 'page')
        resource_id: ID of the resource
    """
    try:
        from flask import request
        import psycopg2
        from psycopg2.extras import Json
        import os
        from database import _get_db_password

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO user_activity_log
            (user_id, username, action, module, resource_type, resource_id, details, ip_address, user_agent)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
            (
                current_user.id if current_user.is_authenticated else None,
                current_user.username if current_user.is_authenticated else None,
                action,
                module,
                resource_type,
                resource_id,
                Json(details) if details else None,
                request.remote_addr if hasattr(request, "remote_addr") else None,
                (request.headers.get("User-Agent", "")[:500] if hasattr(request, "headers") else None),
            ),
        )

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        # Don't fail the request if activity logging fails
        print(f"[UserContext] Activity logging failed: {e}")


# ============================================================================
# SUBSCRIPTION HELPERS
# ============================================================================


def get_user_subscription_tier() -> str:
    """Get current user's subscription tier"""
    if not current_user.is_authenticated:
        return "free"
    return getattr(current_user, "subscription_tier", "free") or "free"


def has_subscription_tier(required_tier: str) -> bool:
    """
    Check if user has at least the specified subscription tier.

    Tier hierarchy: free < pro < business < enterprise
    """
    tier_levels = {"free": 0, "pro": 1, "business": 2, "enterprise": 3}
    user_tier = get_user_subscription_tier()

    user_level = tier_levels.get(user_tier, 0)
    required_level = tier_levels.get(required_tier, 0)

    return user_level >= required_level


def check_resource_limit(resource_type: str, current_count: int = None) -> dict:
    """
    Check if user has reached their resource limit.

    Args:
        resource_type: Type of resource (e.g., 'app_projects', 'website_projects')
        current_count: Current count (will query if not provided)

    Returns:
        Dict with 'allowed', 'limit', 'current', 'remaining'
    """
    import psycopg2
    from psycopg2.extras import RealDictCursor
    import os
    from database import _get_db_password

    tier = get_user_subscription_tier()

    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get tier limits
        cur.execute("SELECT limits FROM subscription_tiers WHERE name = %s", (tier,))
        result = cur.fetchone()
        limits = result["limits"] if result else {}

        limit = limits.get(resource_type, 0)

        # -1 means unlimited
        if limit == -1:
            cur.close()
            conn.close()
            return {
                "allowed": True,
                "limit": -1,
                "current": current_count or 0,
                "remaining": -1,
                "unlimited": True,
            }

        # Get current count if not provided
        if current_count is None:
            table_map = {
                "app_projects": "app_builder_projects",
                "website_projects": "website_builder_projects",
            }
            table = table_map.get(resource_type)
            if table:
                cur.execute(
                    f"SELECT COUNT(*) as count FROM {table} WHERE user_id = %s",
                    (current_user.id,),
                )
                count_result = cur.fetchone()
                current_count = count_result["count"] if count_result else 0
            else:
                current_count = 0

        cur.close()
        conn.close()

        remaining = max(0, limit - current_count)

        return {
            "allowed": current_count < limit,
            "limit": limit,
            "current": current_count,
            "remaining": remaining,
            "unlimited": False,
        }

    except Exception as e:
        print(f"[UserContext] Error checking resource limit: {e}")
        return {
            "allowed": True,  # Allow on error to not block users
            "limit": 0,
            "current": 0,
            "remaining": 0,
            "error": str(e),
        }
