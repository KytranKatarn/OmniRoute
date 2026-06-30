"""Agent-as-a-Service (AaaS) — public commissioning page (#2474).

A PUBLIC, marketing-styled page where a prospective client commissions a custom
hosted ARCHIE agent. The multi-step form POSTs to the public intake API
(`POST /api/aaas/orders` in aaas_api.py) — same origin, no CORS (ADR #870 §10.2:
platform-hosted form, linked from a kytranempowerment.com marketing CTA).

Page-only blueprint (no url_prefix) so the route is a clean `/commission`. No auth
decorator — matches the public-page pattern in app.py (index/login/subscribe).
"""

import logging

from flask import Blueprint, render_template

from services import aaas_service

logger = logging.getLogger(__name__)

aaas_page_bp = Blueprint("aaas_page", __name__)


@aaas_page_bp.route("/commission", methods=["GET"])
def commission_page():
    """Public commissioning landing page + multi-step order form."""
    try:
        tiers = aaas_service.get_public_tiers()
    except Exception:  # noqa: BLE001 — page must render even if pricing read fails
        logger.exception("commission_page: get_public_tiers failed")
        tiers = []
    return render_template("aaas_commission.html", tiers=tiers)
