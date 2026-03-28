"""LCARS-styled email templates for invoices and support tickets."""


def _base_html(title: str, body_content: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
</head>
<body style="font-family:'Segoe UI',Arial,sans-serif;background:#0d0d1a;color:#e0e0e0;padding:20px;margin:0;">
  <div class="container" style="max-width:600px;margin:0 auto;background:#1a1a2e;border-radius:8px;border:1px solid #00e5ff33;padding:30px;">
    {body_content}
  </div>
</body>
</html>"""


def _parse_total(total) -> str:
    """Normalize total to a formatted '$X,XXX.XX' string.

    Accepts either a numeric value or a pre-formatted string like '$1,356.00'.
    """
    if isinstance(total, str):
        cleaned = total.replace("$", "").replace(",", "").strip()
        return f"${float(cleaned):,.2f}"
    return f"${float(total):,.2f}"


def render_invoice_email(
    invoice_number: str,
    customer_name: str,
    total,
    due_date: str,
    business_name: str,
) -> tuple[str, str]:
    """Return (html, plain_text) for an invoice sent notification."""
    formatted_total = _parse_total(total)
    body = f"""
    <div class="header" style="color:#00e5ff;font-size:24px;font-weight:bold;margin-bottom:20px;">{business_name}</div>
    <p>Dear {customer_name},</p>
    <p>Your invoice has been created and is ready for review.</p>
    <p>
      <strong>Invoice Number:</strong>
      <span style="color:#00e5ff;font-weight:bold;">{invoice_number}</span>
    </p>
    <p>
      <strong>Amount Due:</strong>
      <span style="color:#00e5ff;font-size:28px;font-weight:bold;">{formatted_total}</span>
    </p>
    <p><strong>Due Date:</strong> <strong>{due_date}</strong></p>
    <p style="margin-top:24px;color:#a0a0c0;">Thank you for your business.</p>
    """
    html = _base_html(f"Invoice {invoice_number}", body)
    text = (
        f"{business_name}\n\n"
        f"Dear {customer_name},\n\n"
        f"Your invoice has been created and is ready for review.\n\n"
        f"Invoice Number: {invoice_number}\n"
        f"Amount Due: {formatted_total}\n"
        f"Due Date: {due_date}\n\n"
        f"Thank you for your business."
    )
    return html, text


def render_ticket_created_email(
    ticket_number: str,
    subject: str,
    customer_name: str,
    business_name: str,
) -> tuple[str, str]:
    """Return (html, plain_text) for a ticket creation confirmation."""
    body = f"""
    <div class="header" style="color:#00e5ff;font-size:24px;font-weight:bold;margin-bottom:20px;">{business_name} Support</div>
    <p>Dear {customer_name},</p>
    <p>Your support ticket has been received. We will get back to you shortly.</p>
    <p>
      <strong>Ticket Number:</strong>
      <span style="color:#00e5ff;font-weight:bold;">{ticket_number}</span>
    </p>
    <p><strong>Subject:</strong> {subject}</p>
    <p style="margin-top:24px;color:#a0a0c0;">We appreciate your patience.</p>
    """
    html = _base_html(f"Ticket {ticket_number} Created", body)
    text = (
        f"{business_name} Support\n\n"
        f"Dear {customer_name},\n\n"
        f"Your support ticket has been received.\n\n"
        f"Ticket Number: {ticket_number}\n"
        f"Subject: {subject}\n\n"
        f"We appreciate your patience."
    )
    return html, text


def render_ticket_updated_email(
    ticket_number: str,
    subject: str,
    status: str,
    comment: str,
    business_name: str,
) -> tuple[str, str]:
    """Return (html, plain_text) for a ticket update notification."""
    body = f"""
    <div class="header" style="color:#00e5ff;font-size:24px;font-weight:bold;margin-bottom:20px;">{business_name} Support</div>
    <p>Your support ticket has been updated.</p>
    <p>
      <strong>Ticket:</strong>
      <span style="color:#00e5ff;font-weight:bold;">{ticket_number}</span>
      &mdash; {subject}
    </p>
    <p>
      <strong>Status:</strong>
      <span style="display:inline-block;background:#00e5ff22;color:#00e5ff;padding:2px 10px;border-radius:4px;">{status}</span>
    </p>
    <div style="margin-top:16px;background:#0d0d1a;border-left:3px solid #00e5ff;padding:12px 16px;border-radius:4px;">
      <p style="margin:0;">{comment}</p>
    </div>
    <p style="margin-top:24px;color:#a0a0c0;">Thank you for contacting {business_name} Support.</p>
    """
    html = _base_html(f"Ticket {ticket_number} Updated", body)
    text = (
        f"{business_name} Support\n\n"
        f"Your support ticket has been updated.\n\n"
        f"Ticket: {ticket_number} — {subject}\n"
        f"Status: {status}\n\n"
        f"Update:\n{comment}\n\n"
        f"Thank you for contacting {business_name} Support."
    )
    return html, text
