"""Agent-as-a-Service (AaaS) — order intake + concierge build API.

Project #297, task #2475. Thin HTTP layer over services/aaas_service.py:

  POST /api/aaas/orders                 create an order (intake)      [PUBLIC + anti-spam]
  GET  /api/aaas/orders[?status=]       list orders                   [admin]
  GET  /api/aaas/orders/<id>            get one order                 [admin]
  POST /api/aaas/orders/<id>/status     advance lifecycle status      [admin]
  POST /api/aaas/orders/<id>/build      concierge build trigger       [admin]

CSRF: the blueprint is exempted at registration in app.py (csrf.exempt(aaas_bp)) —
this is a JSON API, not a CSRF-token form (same-origin fetch from /commission).

PUBLIC INTAKE (#2474): create_order is PUBLIC so the commissioning page accepts
anonymous submissions. Anti-spam: a hidden honeypot field (`company_website`) +
per-IP rate limit (services.auth_service.check_ip_rate_limit). The public path only
honors {contact_email, contact_name, company_name, tier, brief} — pricing (build_fee/
monthly) and org_id/status are owner/concierge-set and IGNORED here so a client can't
zero the price or self-assign tenancy. Real CAPTCHA + durable cross-worker rate-limit
+ Stripe checkout are deferred to #4587. All admin reads/transitions stay login+admin.
"""

import json
import logging

from flask import Blueprint, request, Response
from flask_login import login_required

from rbac import require_permission, Permission
from services import aaas_service
from services.auth_service import check_ip_rate_limit

logger = logging.getLogger(__name__)

aaas_bp = Blueprint("aaas", __name__, url_prefix="/api/aaas")
admin_required = require_permission(Permission.ADMIN_ACCESS)

# Cap the unauthenticated write surface (defense-in-depth on the public intake path).
_MAX_FIELD_LEN = 2000  # any single contact/brief string
_MAX_BRIEF_BYTES = 16_000  # serialized brief JSONB


def _json(payload, status=200):
    """psycopg2-safe JSON response (datetimes/Decimals via default=str, KB #269068)."""
    return Response(json.dumps(payload, default=str), status=status, mimetype="application/json")


@aaas_bp.route("/orders", methods=["POST"])
def create_order_route():
    """Create an AaaS commissioning order (PUBLIC). Body: {contact_email, tier?, brief?, ...}.

    Anti-spam (#2474): a filled `company_website` honeypot is silently accepted (bot
    drop, no row); the request is per-IP rate-limited. Only contact/tier/brief fields
    are honored — pricing + org_id + status come from the concierge flow, never the
    client. See module docstring.
    """
    data = request.get_json(silent=True) or {}

    # Honeypot — real users never see/fill this. Pretend success, create nothing.
    if (data.get("company_website") or "").strip():
        logger.info("AaaS intake honeypot tripped (ip=%s)", request.remote_addr)
        return _json({"success": True, "order_id": None, "status": "submitted"})

    # Per-IP rate limit (in-memory; loopback + Docker bridge exempt). #4587 hardens this.
    limited, wait = check_ip_rate_limit(request.remote_addr or "")
    if limited:
        return _json({"success": False, "error": "rate_limited", "retry_after": wait}, 429)

    email = (data.get("contact_email") or "").strip()
    if not email or "@" not in email or len(email) > _MAX_FIELD_LEN:
        return _json({"success": False, "error": "a valid contact_email is required"}, 400)

    tier = (data.get("tier") or "starter").strip()
    if tier not in aaas_service.TIER_MODEL:
        return _json(
            {"success": False, "error": f"invalid tier '{tier}' (valid: {list(aaas_service.TIER_MODEL)})"},
            400,
        )

    # Field allowlist + size caps (unauthenticated write surface).
    contact_name = (data.get("contact_name") or "").strip()[:_MAX_FIELD_LEN] or None
    company_name = (data.get("company_name") or "").strip()[:_MAX_FIELD_LEN] or None
    brief = data.get("brief")
    if brief is not None:
        if not isinstance(brief, dict):
            return _json({"success": False, "error": "brief must be an object"}, 400)
        if len(json.dumps(brief)) > _MAX_BRIEF_BYTES:
            return _json({"success": False, "error": "brief too large"}, 400)

    try:
        # NOTE: org_id / build_fee_cents / monthly_cents / status are intentionally
        # NOT passed — owner sets them during concierge review (defaults: NULL pricing,
        # NULL org, status 'submitted').
        order_id = aaas_service.create_order(
            email,
            tier=tier,
            brief=brief,
            contact_name=contact_name,
            company_name=company_name,
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
