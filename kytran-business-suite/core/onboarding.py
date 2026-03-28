"""
core/onboarding.py -- Multi-step onboarding wizard for new tenants.

Steps:
  1. Business profile (name, industry, timezone, logo)
  2. Industry recommendation (auto-suggest bundle)
  3. Pick tier (pricing comparison)
  4. Stripe checkout (or skip for free)
  5. Guided setup checklist
"""

import json
import logging
from datetime import datetime

from flask import Blueprint, g, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from core.database import get_db_cursor

logger = logging.getLogger(__name__)

onboarding_bp = Blueprint(
    "onboarding", __name__, template_folder="../shared/templates"
)

# Industry -> recommended bundle mapping
INDUSTRY_BUNDLES = {
    "salon": {
        "name": "Salon Suite",
        "tier": "business",
        "plugins": ["appointments", "crm", "invoicing", "salon"],
        "description": "Everything a salon needs: online booking, client management, and invoicing.",
    },
    "electrical": {
        "name": "Electrical Contractor Suite",
        "tier": "business",
        "plugins": ["crm", "invoicing", "electrical", "contracts"],
        "description": "Job tracking, quoting, invoicing, and contract management.",
    },
    "plumbing": {
        "name": "Plumbing Suite",
        "tier": "business",
        "plugins": ["crm", "invoicing", "plumbing", "contracts"],
        "description": "Dispatch, invoicing, and contract management for plumbers.",
    },
    "photography": {
        "name": "Photography Suite",
        "tier": "business",
        "plugins": ["crm", "invoicing", "photography", "appointments"],
        "description": "Booking, client galleries, invoicing, and CRM.",
    },
    "construction": {
        "name": "Construction Suite",
        "tier": "business",
        "plugins": ["crm", "invoicing", "construction", "contracts"],
        "description": "Project management, quoting, and contract tracking.",
    },
    "limo": {
        "name": "Limo & Transport Suite",
        "tier": "business",
        "plugins": ["crm", "invoicing", "limo", "appointments"],
        "description": "Reservation management, dispatch, and billing.",
    },
    "mechanical": {
        "name": "Mechanical Services Suite",
        "tier": "business",
        "plugins": ["crm", "invoicing", "mechanical", "contracts"],
        "description": "Work orders, quoting, and service tracking.",
    },
    "retail": {
        "name": "Retail Starter",
        "tier": "business",
        "plugins": ["crm", "invoicing", "store"],
        "description": "Online store, inventory, and customer management.",
    },
    "consulting": {
        "name": "Consulting Starter",
        "tier": "business",
        "plugins": ["crm", "invoicing", "appointments", "contracts"],
        "description": "Client management, scheduling, and invoicing.",
    },
    "other": {
        "name": "General Business",
        "tier": "free",
        "plugins": ["crm", "invoicing"],
        "description": "Core CRM and invoicing to get started.",
    },
}


@onboarding_bp.route("/")
@login_required
def index():
    """Render the onboarding wizard."""
    return render_template("onboarding.html")


@onboarding_bp.route("/api/progress", methods=["GET"])
@login_required
def get_progress():
    """Return the tenant's current onboarding progress."""
    tenant = g.tenant
    settings = tenant.get("settings") or {}
    if isinstance(settings, str):
        settings = json.loads(settings)

    return jsonify({
        "current_step": settings.get("onboarding_step", 1),
        "complete": settings.get("onboarding_complete", False),
        "industry": settings.get("industry", ""),
        "timezone": settings.get("timezone", ""),
        "logo_url": settings.get("logo_url", ""),
        "checklist": settings.get("onboarding_checklist", {}),
    })


@onboarding_bp.route("/api/profile", methods=["POST"])
@login_required
def save_profile():
    """Step 1: Save business profile (name, industry, timezone)."""
    data = request.get_json() or {}
    industry = data.get("industry", "other").lower().strip()
    timezone = data.get("timezone", "America/Toronto").strip()
    business_name = data.get("business_name", "").strip()

    tenant_id = g.tenant_id

    with get_db_cursor(commit=True) as (conn, cur):
        updates = {
            "industry": industry,
            "timezone": timezone,
            "onboarding_step": 2,
        }
        if business_name:
            cur.execute(
                "UPDATE tenants SET name = %s, updated_at = NOW() WHERE id = %s",
                (business_name, tenant_id),
            )
        cur.execute(
            """
            UPDATE tenants
            SET settings = COALESCE(settings, '{}'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE id = %s
            """,
            (json.dumps(updates), tenant_id),
        )

    return jsonify({"status": "ok", "step": 2})


@onboarding_bp.route("/api/recommendation", methods=["GET"])
@login_required
def get_recommendation():
    """Step 2: Return industry-based bundle recommendation."""
    settings = g.tenant.get("settings") or {}
    if isinstance(settings, str):
        settings = json.loads(settings)

    industry = settings.get("industry", "other")
    bundle = INDUSTRY_BUNDLES.get(industry, INDUSTRY_BUNDLES["other"])

    return jsonify({
        "industry": industry,
        "bundle": bundle,
        "all_industries": list(INDUSTRY_BUNDLES.keys()),
    })


@onboarding_bp.route("/api/select-tier", methods=["POST"])
@login_required
def select_tier():
    """Step 3: Select a tier. Returns checkout URL for paid tiers, or activates free."""
    data = request.get_json() or {}
    tier = data.get("tier", "free").lower().strip()
    tenant_id = g.tenant_id

    # Update onboarding step
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE tenants
            SET settings = COALESCE(settings, '{}'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE id = %s
            """,
            (json.dumps({"onboarding_step": 4, "selected_tier": tier}), tenant_id),
        )

    if tier == "free":
        # Skip checkout, go to step 5
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE tenants
                SET settings = COALESCE(settings, '{}'::jsonb) || '{"onboarding_step": 5}'::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (tenant_id,),
            )
        return jsonify({"status": "ok", "step": 5, "tier": "free"})

    # Create Stripe checkout
    try:
        from core.stripe_checkout import create_subscription_checkout

        result = create_subscription_checkout(
            tenant_id=tenant_id,
            tier=tier,
            customer_email=current_user.email,
            success_url=f"{request.host_url}onboarding?step=5&payment=success",
            cancel_url=f"{request.host_url}onboarding?step=3&payment=cancelled",
        )
        return jsonify({"status": "checkout", "checkout_url": result["url"], "tier": tier})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@onboarding_bp.route("/api/checklist", methods=["POST"])
@login_required
def update_checklist():
    """Step 5: Update a checklist item completion status."""
    data = request.get_json() or {}
    item = data.get("item", "")
    done = data.get("done", False)
    tenant_id = g.tenant_id

    if not item:
        return jsonify({"error": "item is required"}), 400

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        cur.execute("SELECT settings FROM tenants WHERE id = %s", (tenant_id,))
        row = cur.fetchone()
        settings = row["settings"] if row and row["settings"] else {}
        if isinstance(settings, str):
            settings = json.loads(settings)

        checklist = settings.get("onboarding_checklist", {})
        checklist[item] = done
        settings["onboarding_checklist"] = checklist

        cur.execute(
            "UPDATE tenants SET settings = %s::jsonb, updated_at = NOW() WHERE id = %s",
            (json.dumps(settings), tenant_id),
        )

    return jsonify({"status": "ok", "checklist": checklist})


@onboarding_bp.route("/api/complete", methods=["POST"])
@login_required
def complete_onboarding():
    """Mark onboarding as complete."""
    tenant_id = g.tenant_id

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE tenants
            SET settings = COALESCE(settings, '{}'::jsonb)
                || '{"onboarding_complete": true, "onboarding_step": 6}'::jsonb,
                updated_at = NOW()
            WHERE id = %s
            """,
            (tenant_id,),
        )

    return jsonify({"status": "ok", "complete": True})
