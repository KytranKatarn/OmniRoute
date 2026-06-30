"""Agent-as-a-Service (AaaS) — order intake + concierge build API.

Project #297, task #2475. Thin HTTP layer over services/aaas_service.py:

  POST /api/aaas/orders                 create an order (intake)      [login_required]
  GET  /api/aaas/orders[?status=]       list orders                   [admin]
  GET  /api/aaas/orders/<id>            get one order                 [admin]
  POST /api/aaas/orders/<id>/status     advance lifecycle status      [admin]
  POST /api/aaas/orders/<id>/build      concierge build trigger       [admin]

CSRF: the blueprint is exempted at registration in app.py (csrf.exempt(aaas_bp)) —
this is a JSON API authed by the login session, not a CSRF-token form.

NOTE (follow-up, ties to #2474): intake is login_required for now. When the public
commissioning page lands it gets relaxed to public + rate-limit/validation/captcha.
"""

import json
import logging

from flask import Blueprint, request, Response
from flask_login import login_required

from rbac import require_permission, Permission
from services import aaas_service

logger = logging.getLogger(__name__)

aaas_bp = Blueprint("aaas", __name__, url_prefix="/api/aaas")
admin_required = require_permission(Permission.ADMIN_ACCESS)


def _json(payload, status=200):
    """psycopg2-safe JSON response (datetimes/Decimals via default=str, KB #269068)."""
    return Response(json.dumps(payload, default=str), status=status, mimetype="application/json")


@aaas_bp.route("/orders", methods=["POST"])
@login_required
def create_order_route():
    """Create an AaaS commissioning order. Body: {contact_email, tier?, brief?, ...}."""
    data = request.get_json(silent=True) or {}
    email = (data.get("contact_email") or "").strip()
    if not email:
        return _json({"success": False, "error": "contact_email is required"}, 400)
    tier = (data.get("tier") or "starter").strip()
    if tier not in aaas_service.TIER_MODEL:
        return _json(
            {"success": False, "error": f"invalid tier '{tier}' (valid: {list(aaas_service.TIER_MODEL)})"},
            400,
        )
    try:
        order_id = aaas_service.create_order(
            email,
            tier=tier,
            brief=data.get("brief"),
            contact_name=data.get("contact_name"),
            company_name=data.get("company_name"),
            org_id=data.get("org_id"),
            build_fee_cents=data.get("build_fee_cents"),
            monthly_cents=data.get("monthly_cents"),
        )
        return _json({"success": True, "order_id": order_id, "status": "submitted"})
    except ValueError as exc:
        return _json({"success": False, "error": str(exc)}, 400)
    except Exception as exc:  # noqa: BLE001
        logger.exception("AaaS create_order failed")
        return _json({"success": False, "error": str(exc)}, 500)


@aaas_bp.route("/orders", methods=["GET"])
@login_required
@admin_required
def list_orders_route():
    """List orders, newest first, optionally filtered by ?status=."""
    status = request.args.get("status")
    if status and status not in aaas_service.VALID_STATUSES:
        return _json({"success": False, "error": f"invalid status '{status}'"}, 400)
    orders = aaas_service.list_orders(status=status)
    return _json({"success": True, "count": len(orders), "orders": orders})


@aaas_bp.route("/orders/<int:order_id>", methods=["GET"])
@login_required
@admin_required
def get_order_route(order_id):
    """Get a single order."""
    order = aaas_service.get_order(order_id)
    if not order:
        return _json({"success": False, "error": "order_not_found"}, 404)
    return _json({"success": True, "order": order})


@aaas_bp.route("/orders/<int:order_id>/status", methods=["POST"])
@login_required
@admin_required
def advance_status_route(order_id):
    """Advance an order's lifecycle status. Body: {status}.

    Used by the owner to walk an order through the concierge flow manually until
    Stripe intake lands (e.g. submitted -> quoted -> paid_build before /build).
    """
    data = request.get_json(silent=True) or {}
    status = (data.get("status") or "").strip()
    if status not in aaas_service.VALID_STATUSES:
        return _json(
            {"success": False, "error": f"invalid status '{status}' (valid: {sorted(aaas_service.VALID_STATUSES)})"},
            400,
        )
    if not aaas_service.get_order(order_id):
        return _json({"success": False, "error": "order_not_found"}, 404)
    aaas_service.advance_status(order_id, status)
    return _json({"success": True, "order_id": order_id, "status": status})


@aaas_bp.route("/orders/<int:order_id>/build", methods=["POST"])
@login_required
@admin_required
def build_order_route(order_id):
    """Concierge build trigger (owner-only). Order must be in 'paid_build' (ADR #870)."""
    result = aaas_service.build_order(order_id)
    code = 200 if result.get("ok") else 400
    return _json({"success": result.get("ok", False), **result}, code)
