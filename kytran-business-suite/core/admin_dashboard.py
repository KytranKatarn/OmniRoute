"""
core/admin_dashboard.py -- Platform admin metrics for Kytran Empowerment.

Routes require the 'owner' role (platform-level admin).
"""

import functools
import json
import logging
from datetime import datetime, timedelta

from flask import Blueprint, abort, g, jsonify, render_template, session
from flask_login import current_user, login_required

from core.database import get_db_cursor

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, template_folder="../shared/templates")


def _require_owner(fn):
    """Decorator: require tenant_role == 'owner'."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        role = session.get("tenant_role", "")
        if role != "owner":
            abort(403)
        return fn(*args, **kwargs)

    return wrapper


@admin_bp.route("/dashboard")
@login_required
@_require_owner
def dashboard():
    return render_template("admin_dashboard.html")


@admin_bp.route("/api/metrics")
@login_required
@_require_owner
def metrics():
    """Return platform-wide metrics."""
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        # Total tenants
        cur.execute("SELECT COUNT(*) AS cnt FROM tenants WHERE is_active = TRUE")
        total_tenants = cur.fetchone()["cnt"]

        # New signups (last 30 days)
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM tenants WHERE created_at >= NOW() - INTERVAL '30 days'"
        )
        new_signups_30d = cur.fetchone()["cnt"]

        # Tier breakdown
        cur.execute(
            """
            SELECT tier, COUNT(*) AS cnt
            FROM tenants
            WHERE is_active = TRUE
            GROUP BY tier
            ORDER BY tier
            """
        )
        tier_breakdown = {r["tier"]: r["cnt"] for r in cur.fetchall()}

        # MRR calculation
        tier_prices = {"free": 0, "business": 49, "enterprise": 149}
        mrr = sum(tier_prices.get(t, 0) * c for t, c in tier_breakdown.items())

        # Add-on count
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM tenant_modules
            WHERE source = 'addon_purchase' AND enabled = TRUE
            """
        )
        addon_count = cur.fetchone()["cnt"]
        addon_mrr = addon_count * 29  # average add-on price

        # Churn (tenants deactivated in last 30 days)
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM tenants
            WHERE is_active = FALSE
                AND updated_at >= NOW() - INTERVAL '30 days'
            """
        )
        churned_30d = cur.fetchone()["cnt"]

        # Plugin activation heatmap
        cur.execute(
            """
            SELECT module_slug, COUNT(*) AS cnt
            FROM tenant_modules
            WHERE enabled = TRUE
            GROUP BY module_slug
            ORDER BY cnt DESC
            """
        )
        plugin_heatmap = [{"slug": r["module_slug"], "count": r["cnt"]} for r in cur.fetchall()]

        # Client health
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE last_login >= NOW() - INTERVAL '7 days') AS active_7d,
                COUNT(*) FILTER (WHERE last_login >= NOW() - INTERVAL '30 days') AS active_30d,
                COUNT(*) FILTER (WHERE last_login < NOW() - INTERVAL '30 days' OR last_login IS NULL) AS inactive
            FROM users
            WHERE is_active = TRUE
            """
        )
        health_row = cur.fetchone()
        client_health = {
            "active_7d": health_row["active_7d"] if health_row else 0,
            "active_30d": health_row["active_30d"] if health_row else 0,
            "inactive": health_row["inactive"] if health_row else 0,
        }

        # Active trials
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM tenants WHERE trial_ends_at IS NOT NULL AND trial_ends_at > NOW()"
        )
        active_trials = cur.fetchone()["cnt"]

    return jsonify({
        "total_tenants": total_tenants,
        "new_signups_30d": new_signups_30d,
        "tier_breakdown": tier_breakdown,
        "mrr": mrr,
        "addon_mrr": addon_mrr,
        "total_mrr": mrr + addon_mrr,
        "churned_30d": churned_30d,
        "churn_rate": round(churned_30d / max(total_tenants, 1) * 100, 1),
        "plugin_heatmap": plugin_heatmap,
        "client_health": client_health,
        "active_trials": active_trials,
    })
