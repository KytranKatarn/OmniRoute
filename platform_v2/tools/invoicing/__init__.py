"""
Invoicing Module — invoice management with Stripe payment integration.
"""

from flask import Blueprint

invoicing_bp = Blueprint("invoicing", __name__, url_prefix="/tools/invoicing")

from . import routes  # noqa: E402

# Register Stripe webhook handler for invoice.paid events
try:
    from services.billing_webhook import register_billing_handler
    from tools.invoicing.stripe_invoice_service import handle_invoice_paid_webhook

    def _handle_invoice_paid(event):
        stripe_inv_id = event["data"]["object"].get("id", "")
        return handle_invoice_paid_webhook(stripe_inv_id)

    register_billing_handler("invoice.paid", _handle_invoice_paid)
except Exception:
    pass  # billing_webhook may not be initialized yet
