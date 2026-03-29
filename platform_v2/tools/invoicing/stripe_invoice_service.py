"""
Stripe Invoice Service — create Stripe payment links for invoices.

Uses the PLATFORM's Stripe account (via stripe_service.py) to create
Stripe Invoices or Payment Links that customers can pay online.
When payment succeeds, the webhook handler records it in invoice_payments.
"""

import logging

import stripe
import stripe.error
from database import get_db_cursor
from services.stripe_service import get_or_create_customer, is_stripe_configured

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Create Stripe Invoice for a local invoice
# ---------------------------------------------------------------------------


def create_stripe_invoice(invoice_id, user_id):
    """Create a Stripe Invoice mirroring a local invoice.

    1. Look up the local invoice + items + customer
    2. Get-or-create the Stripe customer
    3. Create a Stripe Invoice with line items
    4. Finalize and return the hosted invoice URL

    Returns:
        dict with 'stripe_invoice_id', 'hosted_url', 'pdf_url' or raises.
    """
    if not is_stripe_configured():
        raise RuntimeError("Stripe is not configured on this platform")

    # Fetch invoice + customer
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT i.*, c.email as customer_email,
                   c.first_name, c.last_name, c.company_name
            FROM invoices i
            LEFT JOIN crm_customers c ON i.customer_id = c.id
            WHERE i.id = %s AND i.user_id = %s
            """,
            (invoice_id, user_id),
        )
        invoice = cur.fetchone()
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found")

        if not invoice["customer_email"]:
            raise ValueError("Customer has no email address")

        # Fetch line items
        cur.execute(
            "SELECT * FROM invoice_items WHERE invoice_id = %s ORDER BY sort_order",
            (invoice_id,),
        )
        items = cur.fetchall()

    if not items:
        raise ValueError("Invoice has no line items")

    # Get or create Stripe customer using platform account
    customer_name = (
        " ".join(
            filter(
                None,
                [
                    invoice.get("first_name"),
                    invoice.get("last_name"),
                    invoice.get("company_name"),
                ],
            )
        )
        or invoice["customer_email"]
    )

    # Use customer_id as a pseudo user_id for billing_customers
    # (CRM customers are not platform users, so we use negative IDs)
    pseudo_user_id = -invoice["customer_id"] if invoice["customer_id"] else None
    if not pseudo_user_id:
        raise ValueError("Invoice has no linked customer")

    # Check if we already have a Stripe customer for this CRM customer
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT stripe_customer_id FROM billing_customers WHERE user_id = %s",
            (pseudo_user_id,),
        )
        existing = cur.fetchone()

    if existing:
        stripe_customer_id = existing["stripe_customer_id"]
    else:
        # Create Stripe customer directly (can't use get_or_create_customer
        # because CRM customers aren't platform users)
        try:
            customer = stripe.Customer.create(
                email=invoice["customer_email"],
                name=customer_name,
                metadata={"crm_customer_id": str(invoice["customer_id"])},
            )
            stripe_customer_id = customer.id

            # Store mapping
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO billing_customers (user_id, stripe_customer_id, email, name)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE
                    SET stripe_customer_id = EXCLUDED.stripe_customer_id,
                        email = EXCLUDED.email
                    """,
                    (pseudo_user_id, stripe_customer_id, invoice["customer_email"], customer_name),
                )
        except stripe.error.StripeError as e:
            log.error("Failed to create Stripe customer for CRM customer %s: %s", invoice["customer_id"], e)
            raise

    # Create Stripe Invoice
    try:
        stripe_inv = stripe.Invoice.create(
            customer=stripe_customer_id,
            collection_method="send_invoice",
            days_until_due=30,
            metadata={
                "invoice_id": str(invoice_id),
                "invoice_number": invoice.get("invoice_number", ""),
            },
        )

        # Add line items
        for item in items:
            stripe.InvoiceItem.create(
                customer=stripe_customer_id,
                invoice=stripe_inv.id,
                amount=int(float(item["amount"]) * 100),
                currency=invoice.get("currency", "cad") or "cad",
                description=item["description"],
            )

        # Add tax if present
        tax_amount = invoice.get("tax")
        if tax_amount and float(tax_amount) > 0:
            stripe.InvoiceItem.create(
                customer=stripe_customer_id,
                invoice=stripe_inv.id,
                amount=int(float(tax_amount) * 100),
                currency=invoice.get("currency", "cad") or "cad",
                description=f"Tax ({invoice.get('tax_rate', 13)}%)",
            )

        # Finalize the invoice (makes it payable)
        stripe_inv = stripe.Invoice.finalize_invoice(stripe_inv.id)

        # Send the invoice via Stripe (sends email with payment link)
        stripe.Invoice.send_invoice(stripe_inv.id)

    except stripe.error.StripeError as e:
        log.error("Stripe Invoice creation failed for invoice %s: %s", invoice_id, e)
        raise

    # Update local invoice with Stripe references
    hosted_url = stripe_inv.hosted_invoice_url
    pdf_url = stripe_inv.invoice_pdf

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE invoices
            SET stripe_invoice_id = %s,
                invoice_pdf_url = %s,
                payment_method = 'stripe',
                updated_at = NOW()
            WHERE id = %s
            """,
            (stripe_inv.id, pdf_url, invoice_id),
        )

    log.info(
        "Stripe Invoice %s created for invoice %s (customer %s)",
        stripe_inv.id,
        invoice_id,
        stripe_customer_id,
    )

    return {
        "stripe_invoice_id": stripe_inv.id,
        "hosted_url": hosted_url,
        "pdf_url": pdf_url,
    }


# ---------------------------------------------------------------------------
# 2. Create simple Payment Link for an invoice
# ---------------------------------------------------------------------------


def create_payment_link(invoice_id, user_id):
    """Create a Stripe Payment Link for a one-off invoice payment.

    Simpler than a full Stripe Invoice — creates a single payment link
    for the invoice total. Good for quick "pay now" buttons.

    Returns:
        dict with 'payment_link_url'.
    """
    if not is_stripe_configured():
        raise RuntimeError("Stripe is not configured on this platform")

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT * FROM invoices WHERE id = %s AND user_id = %s",
            (invoice_id, user_id),
        )
        invoice = cur.fetchone()
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found")

    amount_cents = int(float(invoice["total"]) * 100)
    currency = invoice.get("currency", "cad") or "cad"

    try:
        # Create a price for this invoice
        price = stripe.Price.create(
            unit_amount=amount_cents,
            currency=currency,
            product_data={
                "name": f"Invoice {invoice.get('invoice_number', invoice_id)}",
            },
        )

        # Create payment link
        link = stripe.PaymentLink.create(
            line_items=[{"price": price.id, "quantity": 1}],
            metadata={
                "invoice_id": str(invoice_id),
                "invoice_number": invoice.get("invoice_number", ""),
            },
        )
    except stripe.error.StripeError as e:
        log.error("Payment link creation failed for invoice %s: %s", invoice_id, e)
        raise

    # Store the payment link in invoice metadata
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE invoices
            SET payment_reference = %s,
                payment_method = 'stripe_link',
                updated_at = NOW()
            WHERE id = %s
            """,
            (link.url, invoice_id),
        )

    log.info("Payment link created for invoice %s: %s", invoice_id, link.url)
    return {"payment_link_url": link.url}


# ---------------------------------------------------------------------------
# 3. Handle Stripe invoice.paid webhook
# ---------------------------------------------------------------------------


def handle_invoice_paid_webhook(stripe_invoice_id):
    """Process a paid Stripe Invoice — record payment in invoice_payments.

    Called by the billing webhook dispatcher when 'invoice.paid' fires.

    Returns:
        str result description.
    """
    # Find the local invoice by stripe_invoice_id
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT id, total, user_id FROM invoices WHERE stripe_invoice_id = %s",
            (stripe_invoice_id,),
        )
        invoice = cur.fetchone()

    if not invoice:
        return f"No local invoice found for stripe_invoice_id={stripe_invoice_id}"

    invoice_id = invoice["id"]

    # Record the payment
    with get_db_cursor(commit=True) as (conn, cur):
        # Check if already recorded (idempotency)
        cur.execute(
            """
            SELECT id FROM invoice_payments
            WHERE invoice_id = %s AND payment_reference = %s
            """,
            (invoice_id, stripe_invoice_id),
        )
        if cur.fetchone():
            return f"Payment already recorded for invoice {invoice_id}"

        cur.execute(
            """
            INSERT INTO invoice_payments
                (invoice_id, amount, payment_method, payment_reference, notes, created_by)
            VALUES (%s, %s, 'stripe', %s, 'Auto-recorded from Stripe webhook', %s)
            """,
            (invoice_id, invoice["total"], stripe_invoice_id, invoice["user_id"]),
        )

        # Mark invoice as paid
        cur.execute(
            """
            UPDATE invoices
            SET status = 'paid', paid_at = NOW(), updated_at = NOW()
            WHERE id = %s
            """,
            (invoice_id,),
        )

    log.info("Invoice %s marked paid via Stripe webhook", invoice_id)
    return f"Invoice {invoice_id} marked paid"
