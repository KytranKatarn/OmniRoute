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


def render_appointment_confirmation_email(
    customer_name: str,
    service_name: str,
    appointment_date: str,
    appointment_time: str,
    duration_minutes: int,
    business_name: str,
    booking_slug: str,
    cancel_token: str | None = None,
) -> tuple[str, str]:
    """Render appointment booking confirmation email. Returns (html, plain_text)."""
    cancel_section_html = ""
    cancel_section_text = ""
    if cancel_token:
        cancel_section_html = f"""
  <p style="margin-top: 20px;">
    Need to cancel?
    <a href="https://book.kytranempowerment.com/{booking_slug}/cancel?token={cancel_token}"
       style="color: #ef4444;">Cancel this appointment</a>
  </p>"""
        cancel_section_text = (
            f"\nNeed to cancel? Visit: "
            f"https://book.kytranempowerment.com/{booking_slug}/cancel?token={cancel_token}"
        )

    body = f"""
    <div class="header" style="color:#00e5ff;font-size:24px;font-weight:bold;margin-bottom:20px;">{business_name}</div>
    <p>Hi {customer_name},</p>
    <p>Your appointment has been <span style="color:#00e5ff;font-weight:bold;">confirmed</span>!</p>
    <div style="background:#0d0d1a;border-radius:6px;padding:16px;margin:20px 0;border-left:3px solid #00e5ff;">
      <div style="margin:8px 0;"><span style="color:#888;display:inline-block;width:100px;">Service:</span> <strong>{service_name}</strong></div>
      <div style="margin:8px 0;"><span style="color:#888;display:inline-block;width:100px;">Date:</span> <strong>{appointment_date}</strong></div>
      <div style="margin:8px 0;"><span style="color:#888;display:inline-block;width:100px;">Time:</span> <strong>{appointment_time}</strong></div>
      <div style="margin:8px 0;"><span style="color:#888;display:inline-block;width:100px;">Duration:</span> <strong>{duration_minutes} minutes</strong></div>
    </div>
    <p>We look forward to seeing you!</p>{cancel_section_html}
    <p style="margin-top:30px;padding-top:20px;border-top:1px solid #333;font-size:12px;color:#888;">Booked via {business_name}</p>
    """
    html = _base_html(f"Appointment Confirmed — {service_name}", body)
    text = (
        f"Hi {customer_name},\n\n"
        f"Your appointment has been confirmed!\n\n"
        f"Service:  {service_name}\n"
        f"Date:     {appointment_date}\n"
        f"Time:     {appointment_time}\n"
        f"Duration: {duration_minutes} minutes\n\n"
        f"We look forward to seeing you!\n"
        f"{cancel_section_text}\n"
        f"— {business_name}"
    )
    return html, text


def render_payment_received_email(
    invoice_number: str,
    customer_name: str,
    amount: float,
    payment_method: str,
    payment_reference: str,
    business_name: str,
) -> tuple[str, str]:
    """Render payment confirmation email. Returns (html, plain_text)."""
    amount_str = f"${amount:,.2f}"

    body = f"""
    <div class="header" style="color:#00e5ff;font-size:24px;font-weight:bold;margin-bottom:20px;">{business_name}</div>
    <div style="display:inline-block;background:#10b98122;color:#10b981;padding:4px 12px;border-radius:4px;font-weight:bold;font-size:14px;margin-bottom:16px;">Payment Received</div>
    <p>Hi {customer_name},</p>
    <p>We've received your payment. Thank you!</p>
    <p style="text-align:center;">
      <span style="color:#10b981;font-size:32px;font-weight:bold;">{amount_str}</span>
    </p>
    <div style="background:#0d0d1a;border-radius:6px;padding:16px;margin:20px 0;border-left:3px solid #10b981;">
      <div style="margin:8px 0;"><span style="color:#888;display:inline-block;width:140px;">Invoice</span> <strong>{invoice_number}</strong></div>
      <div style="margin:8px 0;"><span style="color:#888;display:inline-block;width:140px;">Payment Method</span> <strong>{payment_method.title()}</strong></div>
      <div style="margin:8px 0;"><span style="color:#888;display:inline-block;width:140px;">Reference</span> <strong>{payment_reference}</strong></div>
    </div>
    <p>If you have any questions about this payment, please contact us.</p>
    <p style="margin-top:24px;color:#a0a0c0;">Best regards,<br>{business_name}</p>
    """
    html = _base_html(f"Payment Received - {invoice_number}", body)
    text = (
        f"Payment Received\n\n"
        f"Hi {customer_name},\n\n"
        f"We've received your payment of {amount_str}.\n\n"
        f"Invoice: {invoice_number}\n"
        f"Payment Method: {payment_method.title()}\n"
        f"Reference: {payment_reference}\n\n"
        f"Thank you for your business.\n\n"
        f"{business_name}"
    )
    return html, text


def render_appointment_reminder_email(
    customer_name: str,
    service_name: str,
    appointment_date: str,
    appointment_time: str,
    duration_minutes: int,
    business_name: str,
    hours_until: int,
) -> tuple[str, str]:
    """Render appointment reminder email. Returns (html, plain_text)."""
    hour_word = "hour" if hours_until == 1 else "hours"

    body = f"""
    <div class="header" style="color:#00e5ff;font-size:24px;font-weight:bold;margin-bottom:20px;">{business_name}</div>
    <div style="display:inline-block;background:#fbbf24;color:#0d0d1a;padding:4px 12px;border-radius:4px;font-weight:bold;font-size:14px;margin-bottom:16px;">Reminder: {hours_until} {hour_word} away</div>
    <p>Hi {customer_name},</p>
    <p>This is a friendly reminder about your upcoming appointment:</p>
    <div style="background:#0d0d1a;border-radius:6px;padding:16px;margin:20px 0;border-left:3px solid #fbbf24;">
      <div style="margin:8px 0;"><span style="color:#888;display:inline-block;width:100px;">Service:</span> <strong>{service_name}</strong></div>
      <div style="margin:8px 0;"><span style="color:#888;display:inline-block;width:100px;">Date:</span> <strong>{appointment_date}</strong></div>
      <div style="margin:8px 0;"><span style="color:#888;display:inline-block;width:100px;">Time:</span> <strong>{appointment_time}</strong></div>
      <div style="margin:8px 0;"><span style="color:#888;display:inline-block;width:100px;">Duration:</span> <strong>{duration_minutes} minutes</strong></div>
    </div>
    <p>We look forward to seeing you!</p>
    <p style="margin-top:30px;padding-top:20px;border-top:1px solid #333;font-size:12px;color:#888;">Sent by {business_name}</p>
    """
    html = _base_html(f"Appointment Reminder — {service_name}", body)
    text = (
        f"Hi {customer_name},\n\n"
        f"Reminder: Your appointment is in {hours_until} {hour_word}!\n\n"
        f"Service:  {service_name}\n"
        f"Date:     {appointment_date}\n"
        f"Time:     {appointment_time}\n"
        f"Duration: {duration_minutes} minutes\n\n"
        f"We look forward to seeing you!\n\n"
        f"— {business_name}"
    )
    return html, text
