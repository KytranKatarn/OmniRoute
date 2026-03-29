"""
Store Builder — RETIRED. Redirects to Kytran Business Suite.

All store features have been consolidated into the KBS kbs_store plugin:
- Product/order/category CRUD
- Stripe checkout (per-tenant keys + platform fallback)
- Printful sync + auto-fulfillment on order.paid
- Embed code generation + storefront config
- Webhook handlers (Stripe + Printful)
- Revenue + customer analytics

See: kytran-business-suite/plugins/kbs_store/
Decisions: #333, #334
"""

import os

from flask import Blueprint, redirect
from flask_login import login_required

store_builder_bp = Blueprint(
    "store_builder",
    __name__,
    url_prefix="/tools/store-builder",
)


@store_builder_bp.route("/")
@login_required
def index():
    """Redirect to KBS Store plugin."""
    KBS_URL = os.getenv("KBS_BASE_URL", "http://192.168.1.200:8091")
    return redirect(f"{KBS_URL}/plugins/store/")


@store_builder_bp.route("/health")
def health_check():
    return {"status": "retired", "redirect": "kbs_store"}, 200
