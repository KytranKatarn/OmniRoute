"""
core/dashboard_stats.py -- Dashboard statistics aggregation API.

Aggregates data from active plugins for the tenant dashboard:
contacts, invoices, appointments, notifications, quick actions.
"""

import json
import logging
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify
from flask_login import login_required

from core.database import get_db_cursor, set_tenant_search_path

logger = logging.getLogger(__name__)

dashboard_stats_bp = Blueprint("dashboard_stats", __name__)


@dashboard_stats_bp.route("/api/dashboard/stats")
@login_required
def get_stats():
    """Aggregate dashboard stats from all active plugins."""
    tenant_id = g.tenant_id
    tenant = g.tenant
    settings = tenant.get("settings") or {}
    if isinstance(settings, str):
        settings = json.loads(settings)

    stats = {
        "tenant_name": tenant.get("name", ""),
        "tier": tenant.get("tier", "free"),
        "onboarding_complete": settings.get("onboarding_complete", False),
        "checklist": settings.get("onboarding_checklist", {}),
    }

    with get_db_cursor(dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)

        # Contact count
        try:
            cur.execute("SELECT COUNT(*) AS cnt FROM crm_contacts")
            stats["total_contacts"] = cur.fetchone()["cnt"]
        except Exception:
            stats["total_contacts"] = 0

        # Invoice stats
        try:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'unpaid' OR status = 'overdue') AS outstanding,
                    COALESCE(SUM(balance_due) FILTER (WHERE status IN ('unpaid', 'overdue')), 0) AS outstanding_amount
                FROM invoices
                """
            )
            inv = cur.fetchone()
            stats["total_invoices"] = inv["total"]
            stats["outstanding_invoices"] = inv["outstanding"]
            stats["outstanding_amount"] = float(inv["outstanding_amount"])
        except Exception:
            stats["total_invoices"] = 0
            stats["outstanding_invoices"] = 0
            stats["outstanding_amount"] = 0.0

        # Upcoming appointments (next 7 days)
        try:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM appointments
                WHERE start_time >= NOW() AND start_time <= NOW() + INTERVAL '7 days'
                    AND status != 'cancelled'
                """
            )
            stats["upcoming_appointments"] = cur.fetchone()["cnt"]
        except Exception:
            stats["upcoming_appointments"] = 0

        # Recent revenue (last 30 days)
        try:
            cur.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS revenue
                FROM invoice_payments
                WHERE created_at >= NOW() - INTERVAL '30 days'
                """
            )
            stats["revenue_30d"] = float(cur.fetchone()["revenue"])
        except Exception:
            stats["revenue_30d"] = 0.0

        # Open help desk tickets
        try:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM help_tickets WHERE status IN ('open', 'in_progress')"
            )
            stats["open_tickets"] = cur.fetchone()["cnt"]
        except Exception:
            stats["open_tickets"] = 0

    # Quick actions based on enabled plugins
    from core.tenant import get_enabled_modules

    enabled = get_enabled_modules()
    actions = []
    if "crm" in enabled:
        actions.append({"label": "Add Contact", "url": "/plugins/crm/contacts/new", "icon": "users"})
    if "invoicing" in enabled:
        actions.append({"label": "Create Invoice", "url": "/plugins/invoicing/new", "icon": "invoice"})
    if "appointments" in enabled:
        actions.append({"label": "Book Appointment", "url": "/plugins/appointments/new", "icon": "calendar"})
    if "website-builder" in enabled:
        actions.append({"label": "Edit Website", "url": "/plugins/website-builder/", "icon": "globe"})
    if "store" in enabled:
        actions.append({"label": "View Store", "url": "/plugins/store/", "icon": "store"})
    stats["quick_actions"] = actions

    return jsonify(stats)
