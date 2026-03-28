"""
core/marketplace.py -- Plugin marketplace API and UI.

Provides browsing, activation, trial, and deactivation of plugins
for the current tenant.
"""

import json
import logging
import os
from datetime import datetime, timedelta

from flask import Blueprint, abort, g, jsonify, render_template, request, session
from flask_login import current_user, login_required

from core.database import get_db_cursor
from core.stripe_billing import activate_module, deactivate_module, get_modules_for_tier

logger = logging.getLogger(__name__)

marketplace_bp = Blueprint(
    "marketplace", __name__, template_folder="../shared/templates"
)


# ---------------------------------------------------------------------------
# UI route
# ---------------------------------------------------------------------------


@marketplace_bp.route("/")
@login_required
def index():
    """Render the marketplace page."""
    return render_template("marketplace.html")


# ---------------------------------------------------------------------------
# API: List all plugins
# ---------------------------------------------------------------------------


@marketplace_bp.route("/api/plugins")
@login_required
def list_plugins():
    """Return all plugins from module_catalog with activation status for current tenant."""
    tenant_id = g.tenant_id
    tenant_tier = g.tenant.get("tier", "free")

    # Get all catalog entries
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT slug, name, description, category, tier_required,
                   icon, price_monthly, features, version
            FROM module_catalog
            ORDER BY category, name
            """
        )
        catalog = cur.fetchall()

    # Get tenant's enabled modules
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT module_slug, source, activated_at, trial_ends_at
            FROM tenant_modules
            WHERE tenant_id = %s AND enabled = TRUE
            """,
            (tenant_id,),
        )
        enabled = {r["module_slug"]: dict(r) for r in cur.fetchall()}

    tier_modules = get_modules_for_tier(tenant_tier)

    plugins = []
    for row in catalog:
        slug = row["slug"]
        activation = enabled.get(slug)
        is_active = activation is not None
        source = activation["source"] if activation else None

        # Determine availability
        included_in_tier = slug in tier_modules
        tier_required = row.get("tier_required", "free")
        needs_upgrade = not included_in_tier and tier_required != "addon"

        # Check trial status
        trial_active = False
        trial_ends = None
        if activation and activation.get("trial_ends_at"):
            trial_ends = activation["trial_ends_at"]
            if isinstance(trial_ends, str):
                trial_ends = datetime.fromisoformat(trial_ends)
            trial_active = trial_ends > datetime.utcnow()

        plugins.append({
            "slug": slug,
            "name": row["name"],
            "description": row.get("description", ""),
            "category": row.get("category", ""),
            "icon": row.get("icon", "box"),
            "tier_required": tier_required,
            "price_monthly": float(row["price_monthly"]) if row.get("price_monthly") else None,
            "features": row.get("features") or [],
            "version": row.get("version", "1.0.0"),
            "is_active": is_active,
            "source": source,
            "included_in_tier": included_in_tier,
            "needs_upgrade": needs_upgrade,
            "trial_active": trial_active,
            "trial_ends_at": trial_ends.isoformat() if trial_ends else None,
        })

    return jsonify({"plugins": plugins, "current_tier": tenant_tier})


# ---------------------------------------------------------------------------
# API: Plugin detail
# ---------------------------------------------------------------------------


@marketplace_bp.route("/api/plugins/<slug>")
@login_required
def plugin_detail(slug):
    """Return detailed info for a single plugin."""
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT slug, name, description, category, tier_required,
                   icon, price_monthly, features, version
            FROM module_catalog
            WHERE slug = %s
            """,
            (slug,),
        )
        row = cur.fetchone()

    if not row:
        return jsonify({"error": "Plugin not found"}), 404

    # Check activation status
    tenant_id = g.tenant_id
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT module_slug, source, activated_at, trial_ends_at
            FROM tenant_modules
            WHERE tenant_id = %s AND module_slug = %s AND enabled = TRUE
            """,
            (tenant_id, slug),
        )
        activation = cur.fetchone()

    tenant_tier = g.tenant.get("tier", "free")
    tier_modules = get_modules_for_tier(tenant_tier)
    included_in_tier = slug in tier_modules

    # Dependencies
    from flask import current_app
    plugin_meta = current_app.extensions.get("kbs_plugins", {}).get(slug, {})
    dependencies = plugin_meta.get("dependencies", [])

    result = {
        "slug": row["slug"],
        "name": row["name"],
        "description": row.get("description", ""),
        "category": row.get("category", ""),
        "icon": row.get("icon", "box"),
        "tier_required": row.get("tier_required", "free"),
        "price_monthly": float(row["price_monthly"]) if row.get("price_monthly") else None,
        "features": row.get("features") or [],
        "version": row.get("version", "1.0.0"),
        "is_active": activation is not None,
        "source": activation["source"] if activation else None,
        "included_in_tier": included_in_tier,
        "dependencies": dependencies,
    }

    return jsonify(result)


# ---------------------------------------------------------------------------
# API: Activate plugin
# ---------------------------------------------------------------------------


@marketplace_bp.route("/api/plugins/<slug>/activate", methods=["POST"])
@login_required
def activate_plugin(slug):
    """Activate a plugin for the current tenant.

    If the plugin is included in the tenant's tier, activates immediately.
    If it's an add-on, returns a Stripe checkout URL.
    """
    tenant_id = g.tenant_id
    tenant_tier = g.tenant.get("tier", "free")
    tier_modules = get_modules_for_tier(tenant_tier)

    # Verify plugin exists
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute("SELECT slug, tier_required FROM module_catalog WHERE slug = %s", (slug,))
        plugin = cur.fetchone()

    if not plugin:
        return jsonify({"error": "Plugin not found"}), 404

    # If included in current tier, activate immediately
    if slug in tier_modules:
        activate_module(tenant_id, slug, source="tier_included")
        return jsonify({"status": "activated", "source": "tier_included"})

    # Check if tier upgrade is needed vs add-on purchase
    tier_required = plugin.get("tier_required", "free")
    if tier_required in ("business", "enterprise") and tier_required != "addon":
        return jsonify({
            "status": "upgrade_required",
            "required_tier": tier_required,
            "message": f"Upgrade to {tier_required.title()} to access this plugin.",
        }), 402

    # Add-on -- create Stripe checkout
    try:
        from core.stripe_checkout import create_addon_checkout

        result = create_addon_checkout(
            tenant_id=tenant_id,
            plugin_slug=slug,
            customer_email=current_user.email,
        )
        return jsonify({"status": "checkout", "checkout_url": result["url"]})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


# ---------------------------------------------------------------------------
# API: Start trial
# ---------------------------------------------------------------------------


@marketplace_bp.route("/api/plugins/<slug>/trial", methods=["POST"])
@login_required
def start_trial(slug):
    """Start a 14-day trial of a plugin."""
    tenant_id = g.tenant_id

    # Verify plugin exists
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute("SELECT slug FROM module_catalog WHERE slug = %s", (slug,))
        if not cur.fetchone():
            return jsonify({"error": "Plugin not found"}), 404

    # Check if already active
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT module_slug, source, trial_ends_at
            FROM tenant_modules
            WHERE tenant_id = %s AND module_slug = %s
            """,
            (tenant_id, slug),
        )
        existing = cur.fetchone()

    if existing and existing.get("source") == "trial":
        return jsonify({"error": "Trial already used for this plugin"}), 409

    if existing and existing.get("source") in ("tier_included", "addon_purchase"):
        return jsonify({"error": "Plugin is already active"}), 409

    # Activate with trial source
    trial_end = datetime.utcnow() + timedelta(days=14)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO tenant_modules (tenant_id, module_slug, enabled, source, activated_at, trial_ends_at)
            VALUES (%s, %s, TRUE, 'trial', NOW(), %s)
            ON CONFLICT (tenant_id, module_slug)
            DO UPDATE SET
                enabled = TRUE,
                source = 'trial',
                activated_at = NOW(),
                trial_ends_at = %s,
                deactivated_at = NULL
            """,
            (tenant_id, slug, trial_end, trial_end),
        )

    logger.info("Started 14-day trial of %s for tenant %s", slug, tenant_id)

    return jsonify({
        "status": "trial_started",
        "plugin": slug,
        "trial_ends_at": trial_end.isoformat(),
    })


# ---------------------------------------------------------------------------
# API: Deactivate plugin
# ---------------------------------------------------------------------------


@marketplace_bp.route("/api/plugins/<slug>/deactivate", methods=["POST"])
@login_required
def deactivate_plugin(slug):
    """Deactivate a plugin for the current tenant."""
    tenant_id = g.tenant_id

    # Don't allow deactivating tier-included modules
    tenant_tier = g.tenant.get("tier", "free")
    tier_modules = get_modules_for_tier(tenant_tier)
    if slug in tier_modules:
        return jsonify({
            "error": "Cannot deactivate a module included in your tier.",
        }), 400

    deactivate_module(tenant_id, slug)
    logger.info("Deactivated plugin %s for tenant %s", slug, tenant_id)

    return jsonify({"status": "deactivated", "plugin": slug})
