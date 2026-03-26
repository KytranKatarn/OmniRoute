"""
core/tenant.py — Tenant middleware for KBS.

Identifies the current tenant from the session, loads their data from the
public.tenants table, and gates access to plugins they haven't enabled.
"""

import functools

from flask import abort, g, jsonify, redirect, request, session, url_for

from core.database import get_db_cursor, set_tenant_search_path

# Routes that don't require a tenant to be loaded
PUBLIC_ROUTES = frozenset(
    [
        "auth.login",
        "auth.signup",
        "auth.logout",
        "auth.google_callback",
        "auth.sso",
        "static",
        "health",
    ]
)


def load_tenant():
    """
    Flask before_request hook.

    - Skips PUBLIC_ROUTES.
    - Reads tenant_id from session.
    - Loads the tenant row from public.tenants.
    - Sets g.tenant (dict) and g.tenant_id (int).
    - Returns a redirect / 401 if no tenant in session.
    - Clears session and redirects if tenant is inactive.
    """
    endpoint = request.endpoint or ""

    # Skip public routes (exact match and prefix for "static" blueprint)
    if endpoint in PUBLIC_ROUTES or endpoint.startswith("static"):
        return None

    tenant_id = session.get("tenant_id")
    if not tenant_id:
        if _wants_json():
            return jsonify({"error": "authentication required"}), 401
        return redirect(url_for("auth.login"))

    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        cur.execute(
            "SELECT id, name, slug, tier, is_active, settings FROM tenants WHERE id = %s",
            (tenant_id,),
        )
        tenant = cur.fetchone()

    if tenant is None:
        session.clear()
        if _wants_json():
            return jsonify({"error": "tenant not found"}), 401
        return redirect(url_for("auth.login"))

    if not tenant["is_active"]:
        session.clear()
        if _wants_json():
            return jsonify({"error": "tenant account is inactive"}), 403
        return redirect(url_for("auth.login"))

    g.tenant = dict(tenant)
    g.tenant_id = int(tenant["id"])
    return None


def set_tenant_db_context(conn, cur) -> None:
    """
    Set the PostgreSQL search_path for the current tenant.

    Call this at the start of any DB operation that should be scoped to the
    current tenant's schema.  Requires g.tenant_id to be set (i.e. load_tenant
    must have already run).
    """
    set_tenant_search_path(cur, g.tenant_id)


def get_enabled_modules() -> list[str]:
    """
    Return a list of enabled module slugs for the current tenant.

    Queries public.tenant_modules where enabled = TRUE for g.tenant_id.
    """
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT module_slug
            FROM tenant_modules
            WHERE tenant_id = %s AND enabled = TRUE
            """,
            (g.tenant_id,),
        )
        rows = cur.fetchall()
    return [row[0] for row in rows]


def require_module(slug: str):
    """
    Decorator factory — gates a route on a module being enabled for the tenant.

    Usage::

        @bp.route("/crm/contacts")
        @require_module("crm")
        def contacts():
            ...

    Aborts with 403 if the module is not enabled.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if slug not in get_enabled_modules():
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _wants_json() -> bool:
    """Return True if the client prefers a JSON response."""
    return request.is_json or "application/json" in request.headers.get("Accept", "")
