# KBS Wave 1 Plan A: Core Plugin Completion

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the core KBS plugins (Invoicing, Help Desk, CRM, Store) with PDF generation, email delivery, and email-to-ticket intake so they're production-ready.

**Architecture:** Each plugin follows the same pattern: Blueprint routes in `plugins/{slug}/routes.py`, database access via `get_db_cursor()` + `set_tenant_search_path()`, event emission via `event_bus.emit()`. New features wire into the existing `mail_client.send_email()` for transactional email. PDF generation uses ReportLab (lightweight, no external dependencies).

**Tech Stack:** Flask, PostgreSQL, psycopg2, ReportLab (PDF), pytest

**Spec:** `docs/superpowers/specs/2026-03-28-kbs-completion-saas-resale-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `core/pdf_generator.py` | Invoice PDF generation using ReportLab |
| Create | `core/email_templates.py` | HTML email templates for transactional emails |
| Create | `core/inbound_email.py` | Parse inbound email → create help desk ticket |
| Modify | `plugins/kbs_invoicing/routes.py` | Add send, PDF download, payment recording, recurring |
| Modify | `plugins/kbs_help_desk/routes.py` | Add email intake endpoint, SLA deadline tracking |
| Modify | `plugins/kbs_crm/routes.py` | Add search endpoint, segment filtering |
| Modify | `plugins/kbs_store/routes.py` | Verify CRUD, add inventory tracking |
| Create | `tests/test_pdf_generator.py` | PDF generation tests |
| Create | `tests/test_email_templates.py` | Email template rendering tests |
| Create | `tests/test_invoicing_send.py` | Invoice send + email delivery tests |
| Create | `tests/test_helpdesk_email_intake.py` | Inbound email → ticket tests |
| Create | `tests/test_crm_search.py` | CRM search and segment filter tests |
| Modify | `requirements.txt` | Add reportlab |

---

## Task 1: Add ReportLab Dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add reportlab to requirements**

```bash
echo "reportlab>=4.1" >> /mnt/archie_brain/kytran-business-suite/requirements.txt
```

- [ ] **Step 2: Install in container**

```bash
docker exec kbs_app pip install reportlab>=4.1
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add requirements.txt
git commit -m "chore: add reportlab for PDF invoice generation"
```

---

## Task 2: Invoice PDF Generator

**Files:**
- Create: `core/pdf_generator.py`
- Create: `tests/test_pdf_generator.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pdf_generator.py`:

```python
"""Tests for PDF invoice generation."""

import io
import pytest


def test_generate_invoice_pdf_returns_bytes():
    from core.pdf_generator import generate_invoice_pdf

    invoice = {
        "invoice_number": "INV-0001",
        "created_at": "2026-03-28T10:00:00",
        "due_date": "2026-04-28",
        "status": "draft",
        "customer_name": "Jane Smith",
        "customer_email": "jane@example.com",
        "notes": "Thank you for your business",
        "items": [
            {"description": "Web Design", "quantity": 1, "unit_price": 500.00, "amount": 500.00},
            {"description": "Hosting (monthly)", "quantity": 3, "unit_price": 29.99, "amount": 89.97},
        ],
        "subtotal": 589.97,
        "tax_rate": 13.0,
        "tax_amount": 76.70,
        "total": 666.67,
    }

    business = {
        "name": "Kytran Empowerment Inc.",
        "email": "billing@kytranempowerment.com",
        "phone": "",
        "address": "",
    }

    pdf_bytes = generate_invoice_pdf(invoice, business)

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 100
    assert pdf_bytes[:5] == b"%PDF-"


def test_generate_invoice_pdf_with_no_items():
    from core.pdf_generator import generate_invoice_pdf

    invoice = {
        "invoice_number": "INV-0002",
        "created_at": "2026-03-28T10:00:00",
        "due_date": "2026-04-28",
        "status": "draft",
        "customer_name": "Test Client",
        "customer_email": "test@example.com",
        "notes": "",
        "items": [],
        "subtotal": 0,
        "tax_rate": 0,
        "tax_amount": 0,
        "total": 0,
    }

    business = {"name": "Test Biz", "email": "", "phone": "", "address": ""}

    pdf_bytes = generate_invoice_pdf(invoice, business)
    assert pdf_bytes[:5] == b"%PDF-"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec kbs_app python -m pytest tests/test_pdf_generator.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.pdf_generator'`

- [ ] **Step 3: Write the implementation**

Create `core/pdf_generator.py`:

```python
"""Generate PDF invoices using ReportLab."""

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def generate_invoice_pdf(invoice: dict, business: dict) -> bytes:
    """Generate a PDF invoice and return raw bytes.

    Args:
        invoice: Dict with keys: invoice_number, created_at, due_date, status,
                 customer_name, customer_email, notes, items (list of dicts with
                 description, quantity, unit_price, amount), subtotal, tax_rate,
                 tax_amount, total.
        business: Dict with keys: name, email, phone, address.

    Returns:
        PDF file content as bytes.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    elements = []

    # -- Header --
    header_style = ParagraphStyle("InvHeader", parent=styles["Heading1"], fontSize=20, textColor=colors.HexColor("#00e5ff"))
    elements.append(Paragraph(business.get("name", ""), header_style))
    if business.get("address"):
        elements.append(Paragraph(business["address"], styles["Normal"]))
    if business.get("email"):
        elements.append(Paragraph(business["email"], styles["Normal"]))
    if business.get("phone"):
        elements.append(Paragraph(business["phone"], styles["Normal"]))
    elements.append(Spacer(1, 0.3 * inch))

    # -- Invoice meta --
    meta_data = [
        ["Invoice #:", invoice.get("invoice_number", "")],
        ["Date:", _format_date(invoice.get("created_at", ""))],
        ["Due Date:", _format_date(invoice.get("due_date", ""))],
        ["Status:", (invoice.get("status") or "draft").upper()],
        ["Bill To:", invoice.get("customer_name", "")],
    ]
    if invoice.get("customer_email"):
        meta_data.append(["", invoice["customer_email"]])

    meta_table = Table(meta_data, colWidths=[1.2 * inch, 4 * inch])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 0.3 * inch))

    # -- Line items --
    items = invoice.get("items") or []
    table_data = [["Description", "Qty", "Unit Price", "Amount"]]
    for item in items:
        table_data.append([
            item.get("description", ""),
            str(item.get("quantity", 0)),
            f"${item.get('unit_price', 0):,.2f}",
            f"${item.get('amount', 0):,.2f}",
        ])

    if not items:
        table_data.append(["No items", "", "", "$0.00"])

    item_table = Table(table_data, colWidths=[3.5 * inch, 0.8 * inch, 1.2 * inch, 1.2 * inch])
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#00e5ff")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#333355")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#0d0d1a"), colors.HexColor("#141428")]),
        ("TEXTCOLOR", (0, 1), (-1, -1), colors.white),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(item_table)
    elements.append(Spacer(1, 0.2 * inch))

    # -- Totals --
    totals_data = [
        ["Subtotal:", f"${invoice.get('subtotal', 0):,.2f}"],
    ]
    tax_rate = invoice.get("tax_rate", 0)
    if tax_rate:
        totals_data.append([f"Tax ({tax_rate}%):", f"${invoice.get('tax_amount', 0):,.2f}"])
    totals_data.append(["Total:", f"${invoice.get('total', 0):,.2f}"])

    totals_table = Table(totals_data, colWidths=[5.3 * inch, 1.4 * inch])
    totals_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 12),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#00e5ff")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(totals_table)

    # -- Notes --
    if invoice.get("notes"):
        elements.append(Spacer(1, 0.3 * inch))
        elements.append(Paragraph("<b>Notes:</b>", styles["Normal"]))
        elements.append(Paragraph(invoice["notes"], styles["Normal"]))

    doc.build(elements)
    return buf.getvalue()


def _format_date(date_str: str) -> str:
    """Format an ISO date string to a human-readable format."""
    if not date_str:
        return ""
    try:
        dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        return dt.strftime("%B %d, %Y")
    except (ValueError, TypeError):
        return str(date_str)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_pdf_generator.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/pdf_generator.py tests/test_pdf_generator.py
git commit -m "feat(invoicing): add PDF invoice generator with LCARS-styled output"
```

---

## Task 3: Email Templates

**Files:**
- Create: `core/email_templates.py`
- Create: `tests/test_email_templates.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_email_templates.py`:

```python
"""Tests for email template rendering."""

import pytest


def test_invoice_email_template_contains_key_fields():
    from core.email_templates import render_invoice_email

    html, text = render_invoice_email(
        invoice_number="INV-0001",
        customer_name="Jane Smith",
        total=666.67,
        due_date="April 28, 2026",
        business_name="Kytran Empowerment Inc.",
    )

    assert "INV-0001" in html
    assert "Jane Smith" in html
    assert "666.67" in html
    assert "April 28, 2026" in html
    assert "Kytran Empowerment" in html

    assert "INV-0001" in text
    assert "Jane Smith" in text


def test_ticket_created_email_template():
    from core.email_templates import render_ticket_created_email

    html, text = render_ticket_created_email(
        ticket_number="HD-0042",
        subject="Login not working",
        customer_name="Bob Jones",
        business_name="Kytran Empowerment Inc.",
    )

    assert "HD-0042" in html
    assert "Login not working" in html
    assert "HD-0042" in text


def test_ticket_updated_email_template():
    from core.email_templates import render_ticket_updated_email

    html, text = render_ticket_updated_email(
        ticket_number="HD-0042",
        subject="Login not working",
        status="in_progress",
        comment="We're looking into this now.",
        business_name="Kytran Empowerment Inc.",
    )

    assert "HD-0042" in html
    assert "in_progress" in html.lower() or "In Progress" in html
    assert "looking into this" in html
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec kbs_app python -m pytest tests/test_email_templates.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `core/email_templates.py`:

```python
"""HTML + plain-text email templates for KBS transactional emails."""


def render_invoice_email(
    invoice_number: str,
    customer_name: str,
    total: float,
    due_date: str,
    business_name: str,
) -> tuple[str, str]:
    """Render invoice sent email. Returns (html, plain_text)."""
    html = f"""<!DOCTYPE html>
<html>
<head><style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0d0d1a; color: #e0e0e0; margin: 0; padding: 20px; }}
  .container {{ max-width: 600px; margin: 0 auto; background: #1a1a2e; border-radius: 8px; border: 1px solid #00e5ff33; padding: 30px; }}
  .header {{ color: #00e5ff; font-size: 24px; font-weight: bold; margin-bottom: 20px; }}
  .highlight {{ color: #00e5ff; font-weight: bold; }}
  .total {{ font-size: 28px; color: #00e5ff; font-weight: bold; margin: 20px 0; }}
  .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #333; font-size: 12px; color: #888; }}
</style></head>
<body>
<div class="container">
  <div class="header">{business_name}</div>
  <p>Hi {customer_name},</p>
  <p>Invoice <span class="highlight">{invoice_number}</span> has been sent to you.</p>
  <div class="total">${total:,.2f}</div>
  <p>Due by: <strong>{due_date}</strong></p>
  <p>Please remit payment at your earliest convenience.</p>
  <div class="footer">This invoice was generated by {business_name}.</div>
</div>
</body>
</html>"""

    text = f"""Hi {customer_name},

Invoice {invoice_number} has been sent to you.

Amount Due: ${total:,.2f}
Due Date: {due_date}

Please remit payment at your earliest convenience.

— {business_name}"""

    return html, text


def render_ticket_created_email(
    ticket_number: str,
    subject: str,
    customer_name: str,
    business_name: str,
) -> tuple[str, str]:
    """Render ticket creation confirmation email. Returns (html, plain_text)."""
    html = f"""<!DOCTYPE html>
<html>
<head><style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0d0d1a; color: #e0e0e0; margin: 0; padding: 20px; }}
  .container {{ max-width: 600px; margin: 0 auto; background: #1a1a2e; border-radius: 8px; border: 1px solid #00e5ff33; padding: 30px; }}
  .header {{ color: #00e5ff; font-size: 24px; font-weight: bold; margin-bottom: 20px; }}
  .ticket-id {{ color: #00e5ff; font-weight: bold; font-size: 18px; }}
</style></head>
<body>
<div class="container">
  <div class="header">{business_name} Support</div>
  <p>Hi {customer_name},</p>
  <p>Your support ticket has been created:</p>
  <p class="ticket-id">{ticket_number}: {subject}</p>
  <p>We'll get back to you as soon as possible.</p>
</div>
</body>
</html>"""

    text = f"""Hi {customer_name},

Your support ticket has been created:

{ticket_number}: {subject}

We'll get back to you as soon as possible.

— {business_name} Support"""

    return html, text


def render_ticket_updated_email(
    ticket_number: str,
    subject: str,
    status: str,
    comment: str,
    business_name: str,
) -> tuple[str, str]:
    """Render ticket update notification email. Returns (html, plain_text)."""
    status_display = status.replace("_", " ").title()

    html = f"""<!DOCTYPE html>
<html>
<head><style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0d0d1a; color: #e0e0e0; margin: 0; padding: 20px; }}
  .container {{ max-width: 600px; margin: 0 auto; background: #1a1a2e; border-radius: 8px; border: 1px solid #00e5ff33; padding: 30px; }}
  .header {{ color: #00e5ff; font-size: 24px; font-weight: bold; margin-bottom: 20px; }}
  .status {{ display: inline-block; padding: 4px 12px; background: #00e5ff22; color: #00e5ff; border-radius: 4px; font-weight: bold; }}
  .comment {{ background: #0d0d1a; padding: 15px; border-radius: 6px; border-left: 3px solid #00e5ff; margin: 15px 0; }}
</style></head>
<body>
<div class="container">
  <div class="header">{business_name} Support</div>
  <p>Update on your ticket <strong>{ticket_number}</strong>: {subject}</p>
  <p>Status: <span class="status">{status_display}</span></p>
  <div class="comment">{comment}</div>
</div>
</body>
</html>"""

    text = f"""Update on your ticket {ticket_number}: {subject}

Status: {status_display}

{comment}

— {business_name} Support"""

    return html, text
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_email_templates.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/email_templates.py tests/test_email_templates.py
git commit -m "feat: add LCARS-styled email templates for invoices and tickets"
```

---

## Task 4: Wire Invoice Send with PDF + Email

**Files:**
- Modify: `plugins/kbs_invoicing/routes.py`
- Create: `tests/test_invoicing_send.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_invoicing_send.py`:

```python
"""Tests for invoice send route — PDF generation + email delivery."""

import json
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture()
def mock_send_email():
    with patch("plugins.kbs_invoicing.routes.send_email") as mock:
        mock.return_value = True
        yield mock


@pytest.fixture()
def mock_db_invoice():
    """Return a mock invoice dict as the DB would."""
    return {
        "id": 1,
        "invoice_number": "INV-0001",
        "created_at": "2026-03-28T10:00:00",
        "due_date": "2026-04-28",
        "status": "sent",
        "customer_name": "Jane Smith",
        "customer_email": "jane@example.com",
        "notes": "Thanks",
        "subtotal": 500.00,
        "tax_rate": 13.0,
        "tax_amount": 65.00,
        "total": 565.00,
    }


def test_generate_invoice_pdf_from_db_data(mock_db_invoice):
    """Verify PDF generation works with DB-shaped invoice data."""
    from core.pdf_generator import generate_invoice_pdf

    invoice = mock_db_invoice
    invoice["items"] = [
        {"description": "Consulting", "quantity": 5, "unit_price": 100.00, "amount": 500.00},
    ]
    business = {"name": "Test Biz", "email": "test@test.com", "phone": "", "address": ""}

    pdf = generate_invoice_pdf(invoice, business)
    assert pdf[:5] == b"%PDF-"


def test_render_invoice_email_template(mock_db_invoice):
    """Verify email template renders with invoice data."""
    from core.email_templates import render_invoice_email

    html, text = render_invoice_email(
        invoice_number=mock_db_invoice["invoice_number"],
        customer_name=mock_db_invoice["customer_name"],
        total=mock_db_invoice["total"],
        due_date="April 28, 2026",
        business_name="Kytran Empowerment Inc.",
    )

    assert "INV-0001" in html
    assert "$565.00" in html
    assert "INV-0001" in text
```

- [ ] **Step 2: Run test to verify it fails (or passes — these test existing code)**

```bash
docker exec kbs_app python -m pytest tests/test_invoicing_send.py -v
```

Expected: 2 passed (these test the units we already built)

- [ ] **Step 3: Add imports and PDF download route to invoicing routes**

Add to the top of `plugins/kbs_invoicing/routes.py`:

```python
from flask import Response
from core.pdf_generator import generate_invoice_pdf
from core.email_templates import render_invoice_email
from core.mail_client import send_email
```

- [ ] **Step 4: Add PDF download endpoint**

Add inside `register_routes(bp)` in `plugins/kbs_invoicing/routes.py`, after the existing `send_invoice` route:

```python
    @bp.route("/api/invoices/<int:invoice_id>/pdf", methods=["GET"])
    @login_required
    @require_module("invoicing")
    def download_invoice_pdf(invoice_id):
        with get_db_cursor(dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute("SELECT * FROM invoices WHERE id = %s", (invoice_id,))
            invoice = cur.fetchone()
            if not invoice:
                return jsonify({"error": "invoice not found"}), 404

            # Get customer info
            cur.execute(
                "SELECT name, email FROM crm_customers WHERE id = %s",
                (invoice["customer_id"],),
            )
            customer = cur.fetchone() or {}
            invoice["customer_name"] = customer.get("name", "")
            invoice["customer_email"] = customer.get("email", "")

            # Get line items
            cur.execute(
                "SELECT description, quantity, unit_price, amount FROM invoice_items WHERE invoice_id = %s ORDER BY id",
                (invoice_id,),
            )
            invoice["items"] = cur.fetchall()

            # Get business settings
            cur.execute("SELECT * FROM invoice_settings LIMIT 1")
            settings = cur.fetchone() or {}

        business = {
            "name": settings.get("company_name", ""),
            "email": settings.get("company_email", ""),
            "phone": settings.get("company_phone", ""),
            "address": settings.get("company_address", ""),
        }

        pdf_bytes = generate_invoice_pdf(invoice, business)

        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={invoice['invoice_number']}.pdf",
            },
        )
```

- [ ] **Step 5: Update the existing send_invoice route to email the PDF**

Find the existing `send_invoice` route in `plugins/kbs_invoicing/routes.py` and replace it with:

```python
    @bp.route("/api/invoices/<int:invoice_id>/send", methods=["POST"])
    @login_required
    @require_module("invoicing")
    def send_invoice(invoice_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute("SELECT * FROM invoices WHERE id = %s", (invoice_id,))
            invoice = cur.fetchone()
            if not invoice:
                return jsonify({"error": "invoice not found"}), 404

            # Get customer
            cur.execute(
                "SELECT name, email FROM crm_customers WHERE id = %s",
                (invoice["customer_id"],),
            )
            customer = cur.fetchone()
            if not customer or not customer.get("email"):
                return jsonify({"error": "customer has no email address"}), 400

            invoice["customer_name"] = customer["name"]
            invoice["customer_email"] = customer["email"]

            # Get line items
            cur.execute(
                "SELECT description, quantity, unit_price, amount FROM invoice_items WHERE invoice_id = %s ORDER BY id",
                (invoice_id,),
            )
            invoice["items"] = cur.fetchall()

            # Get business settings
            cur.execute("SELECT * FROM invoice_settings LIMIT 1")
            settings = cur.fetchone() or {}

            # Update status to sent
            cur.execute(
                "UPDATE invoices SET status = 'sent', sent_at = NOW(), updated_at = NOW() WHERE id = %s RETURNING *",
                (invoice_id,),
            )
            updated = cur.fetchone()

        business = {
            "name": settings.get("company_name", ""),
            "email": settings.get("company_email", ""),
            "phone": settings.get("company_phone", ""),
            "address": settings.get("company_address", ""),
        }

        # Format due date for email
        due_date = ""
        if invoice.get("due_date"):
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(str(invoice["due_date"]))
                due_date = dt.strftime("%B %d, %Y")
            except (ValueError, TypeError):
                due_date = str(invoice["due_date"])

        # Render email
        html_body, text_body = render_invoice_email(
            invoice_number=invoice["invoice_number"],
            customer_name=customer["name"],
            total=float(invoice.get("total", 0)),
            due_date=due_date,
            business_name=business["name"] or "Kytran Empowerment Inc.",
        )

        # Send email
        try:
            send_email(
                to=customer["email"],
                subject=f"Invoice {invoice['invoice_number']} from {business.get('name', 'Kytran Empowerment')}",
                body=text_body,
                html_body=html_body,
            )
        except Exception as exc:
            logger.error("Failed to send invoice email: %s", exc)
            # Invoice is still marked as sent — email failure is non-blocking

        event_bus.emit(
            "invoice.sent",
            {"invoice_id": invoice_id, "customer_email": customer["email"], "total": float(invoice.get("total", 0))},
            tenant_id=g.tenant_id,
        )

        return jsonify(updated)
```

- [ ] **Step 6: Run all tests**

```bash
docker exec kbs_app python -m pytest tests/test_pdf_generator.py tests/test_email_templates.py tests/test_invoicing_send.py -v
```

Expected: All pass

- [ ] **Step 7: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_invoicing/routes.py tests/test_invoicing_send.py
git commit -m "feat(invoicing): wire PDF download + email send with LCARS template"
```

---

## Task 5: Inbound Email → Help Desk Ticket

**Files:**
- Create: `core/inbound_email.py`
- Modify: `plugins/kbs_help_desk/routes.py`
- Create: `tests/test_helpdesk_email_intake.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_helpdesk_email_intake.py`:

```python
"""Tests for inbound email parsing and ticket creation."""

import pytest


def test_parse_inbound_email_basic():
    from core.inbound_email import parse_inbound_email

    raw = {
        "from": "bob@example.com",
        "subject": "Login page broken",
        "body_plain": "I can't log in. The page shows a 500 error.",
        "body_html": "<p>I can't log in. The page shows a 500 error.</p>",
    }

    result = parse_inbound_email(raw)

    assert result["sender_email"] == "bob@example.com"
    assert result["subject"] == "Login page broken"
    assert "500 error" in result["body"]


def test_parse_inbound_email_with_name():
    from core.inbound_email import parse_inbound_email

    raw = {
        "from": "Bob Jones <bob@example.com>",
        "subject": "Help needed",
        "body_plain": "Please help me.",
    }

    result = parse_inbound_email(raw)

    assert result["sender_email"] == "bob@example.com"
    assert result["sender_name"] == "Bob Jones"


def test_parse_inbound_email_strips_reply_prefix():
    from core.inbound_email import parse_inbound_email

    raw = {
        "from": "bob@example.com",
        "subject": "Re: HD-0042: Login page broken",
        "body_plain": "Any update on this?",
    }

    result = parse_inbound_email(raw)
    assert result["is_reply"] is True
    assert result["ticket_number"] == "HD-0042"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec kbs_app python -m pytest tests/test_helpdesk_email_intake.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `core/inbound_email.py`:

```python
"""Parse inbound emails for Help Desk ticket creation."""

import re
import logging

logger = logging.getLogger(__name__)

# Match "HD-NNNN" in subject lines
_TICKET_RE = re.compile(r"HD-(\d{4,})")
# Match "Name <email>" format
_FROM_RE = re.compile(r"^(.+?)\s*<([^>]+)>$")


def parse_inbound_email(raw: dict) -> dict:
    """Parse a raw inbound email dict into structured ticket data.

    Args:
        raw: Dict with keys: from, subject, body_plain, body_html (optional).

    Returns:
        Dict with: sender_email, sender_name, subject, body, is_reply, ticket_number.
    """
    from_field = raw.get("from", "").strip()
    sender_email = from_field
    sender_name = ""

    match = _FROM_RE.match(from_field)
    if match:
        sender_name = match.group(1).strip().strip('"')
        sender_email = match.group(2).strip()

    subject = raw.get("subject", "").strip()
    body = raw.get("body_plain") or raw.get("body_html") or ""

    # Check if this is a reply to an existing ticket
    is_reply = False
    ticket_number = None
    ticket_match = _TICKET_RE.search(subject)
    if ticket_match:
        is_reply = True
        ticket_number = f"HD-{ticket_match.group(1)}"

    # Strip common reply prefixes for clean subject
    clean_subject = re.sub(r"^(Re:\s*|Fwd:\s*)+", "", subject, flags=re.IGNORECASE).strip()
    # Strip ticket number prefix if present
    clean_subject = re.sub(r"^HD-\d{4,}:\s*", "", clean_subject).strip()

    return {
        "sender_email": sender_email,
        "sender_name": sender_name,
        "subject": clean_subject or subject,
        "body": body.strip(),
        "is_reply": is_reply,
        "ticket_number": ticket_number,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_helpdesk_email_intake.py -v
```

Expected: 3 passed

- [ ] **Step 5: Add email intake endpoint to help desk routes**

Add to the top of `plugins/kbs_help_desk/routes.py`:

```python
from core.inbound_email import parse_inbound_email
from core.email_templates import render_ticket_created_email, render_ticket_updated_email
from core.mail_client import send_email
```

Add inside `register_routes(bp)`, after the existing routes:

```python
    @bp.route("/api/email-intake", methods=["POST"])
    def email_intake():
        """Receive inbound email webhook and create/update ticket.

        This endpoint is called by the mail server's webhook on incoming email.
        No login required — authenticated by webhook secret header.
        """
        secret = request.headers.get("X-Webhook-Secret", "")
        expected = os.environ.get("KBS_EMAIL_WEBHOOK_SECRET", "")
        if expected and secret != expected:
            return jsonify({"error": "unauthorized"}), 401

        data = request.get_json(force=True)
        tenant_id = data.get("tenant_id")
        if not tenant_id:
            return jsonify({"error": "tenant_id required"}), 400

        parsed = parse_inbound_email(data)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)

            if parsed["is_reply"] and parsed["ticket_number"]:
                # Add comment to existing ticket
                cur.execute(
                    "SELECT id, subject FROM support_tickets WHERE ticket_number = %s",
                    (parsed["ticket_number"],),
                )
                ticket = cur.fetchone()
                if ticket:
                    cur.execute(
                        """
                        INSERT INTO ticket_comments (ticket_id, author_name, author_email, content, source, created_at)
                        VALUES (%s, %s, %s, %s, 'email', NOW())
                        RETURNING id
                        """,
                        (ticket["id"], parsed["sender_name"] or parsed["sender_email"], parsed["sender_email"], parsed["body"]),
                    )
                    return jsonify({"action": "comment_added", "ticket_number": parsed["ticket_number"]}), 200

            # Create new ticket
            ticket_number = _next_ticket_number(cur, tenant_id)

            # Try to match sender to CRM contact
            customer_id = None
            cur.execute(
                "SELECT id FROM crm_customers WHERE email = %s LIMIT 1",
                (parsed["sender_email"],),
            )
            customer = cur.fetchone()
            if customer:
                customer_id = customer["id"]

            cur.execute(
                """
                INSERT INTO support_tickets
                    (ticket_number, subject, description, status, priority, source, customer_id, customer_email, customer_name, created_at, updated_at)
                VALUES (%s, %s, %s, 'open', 'medium', 'email', %s, %s, %s, NOW(), NOW())
                RETURNING id, ticket_number, subject
                """,
                (ticket_number, parsed["subject"], parsed["body"], customer_id, parsed["sender_email"], parsed["sender_name"]),
            )
            new_ticket = cur.fetchone()

        # Send confirmation email
        try:
            html_body, text_body = render_ticket_created_email(
                ticket_number=new_ticket["ticket_number"],
                subject=new_ticket["subject"],
                customer_name=parsed["sender_name"] or "there",
                business_name=os.environ.get("KBS_BUSINESS_NAME", "Kytran Empowerment Inc."),
            )
            send_email(
                to=parsed["sender_email"],
                subject=f"Ticket {new_ticket['ticket_number']}: {new_ticket['subject']}",
                body=text_body,
                html_body=html_body,
            )
        except Exception as exc:
            logger.error("Failed to send ticket confirmation: %s", exc)

        event_bus.emit(
            "ticket.created",
            {"ticket_id": new_ticket["id"], "ticket_number": new_ticket["ticket_number"], "source": "email"},
            tenant_id=tenant_id,
        )

        return jsonify({"action": "ticket_created", "ticket_number": new_ticket["ticket_number"]}), 201
```

Also add `import os` to the imports at the top of the file.

- [ ] **Step 6: Run all tests**

```bash
docker exec kbs_app python -m pytest tests/test_helpdesk_email_intake.py tests/test_email_templates.py -v
```

Expected: All pass

- [ ] **Step 7: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/inbound_email.py plugins/kbs_help_desk/routes.py tests/test_helpdesk_email_intake.py
git commit -m "feat(help-desk): add inbound email intake with CRM contact matching"
```

---

## Task 6: CRM Search + Segment Filtering

**Files:**
- Modify: `plugins/kbs_crm/routes.py`
- Create: `tests/test_crm_search.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_crm_search.py`:

```python
"""Tests for CRM search and segment filtering helpers."""

import pytest


def test_build_search_query_with_term():
    from plugins.kbs_crm.search import build_search_conditions

    conditions, params = build_search_conditions(search="jane")

    assert len(conditions) > 0
    assert "jane" in params or "%jane%" in params


def test_build_search_query_with_segment():
    from plugins.kbs_crm.search import build_search_conditions

    conditions, params = build_search_conditions(segment_id=5)

    assert len(conditions) > 0
    assert 5 in params


def test_build_search_query_with_both():
    from plugins.kbs_crm.search import build_search_conditions

    conditions, params = build_search_conditions(search="jane", segment_id=5)

    assert len(conditions) == 2


def test_build_search_query_empty():
    from plugins.kbs_crm.search import build_search_conditions

    conditions, params = build_search_conditions()

    assert len(conditions) == 0
    assert len(params) == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec kbs_app python -m pytest tests/test_crm_search.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create search helper module**

Create `plugins/kbs_crm/search.py`:

```python
"""CRM search and segment filtering query builders."""


def build_search_conditions(search: str = None, segment_id: int = None) -> tuple[list[str], list]:
    """Build WHERE conditions and params for customer search.

    Args:
        search: Free-text search term (matches name, email, company).
        segment_id: Filter to customers in this segment.

    Returns:
        Tuple of (list of SQL condition strings, list of params).
    """
    conditions = []
    params = []

    if search:
        search_term = f"%{search}%"
        conditions.append(
            "(c.name ILIKE %s OR c.email ILIKE %s OR c.company ILIKE %s)"
        )
        params.extend([search_term, search_term, search_term])

    if segment_id:
        conditions.append(
            "c.id IN (SELECT customer_id FROM crm_segment_members WHERE segment_id = %s)"
        )
        params.append(segment_id)

    return conditions, params
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_crm_search.py -v
```

Expected: 4 passed

- [ ] **Step 5: Wire search into CRM list_customers route**

In `plugins/kbs_crm/routes.py`, add to imports:

```python
from plugins.kbs_crm.search import build_search_conditions
```

Then update the `list_customers` route to use search params. Find the existing `list_customers` function and update the query section to accept search and segment_id from query params:

Add after `per_page = ...` line:

```python
        search = request.args.get("search", "").strip()
        segment_id = request.args.get("segment_id", type=int)

        conditions, search_params = build_search_conditions(search=search or None, segment_id=segment_id)
        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)
```

Update the count and select queries to include `where_clause` and `search_params`:

```python
            cur.execute(f"SELECT COUNT(*) AS total FROM crm_customers c {where_clause}", search_params)
            total = cur.fetchone()["total"]

            cur.execute(
                f"""
                SELECT * FROM crm_customers c {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                search_params + [per_page, offset],
            )
```

- [ ] **Step 6: Run all CRM tests**

```bash
docker exec kbs_app python -m pytest tests/test_crm_search.py -v
```

Expected: All pass

- [ ] **Step 7: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_crm/search.py plugins/kbs_crm/routes.py tests/test_crm_search.py
git commit -m "feat(crm): add search and segment filtering to customer list"
```

---

## Task 7: Store Plugin — Inventory Tracking

**Files:**
- Modify: `plugins/kbs_store/routes.py`

- [ ] **Step 1: Read the current store routes**

```bash
docker exec kbs_app cat plugins/kbs_store/routes.py
```

Review what CRUD exists. The store plugin should already have product and order CRUD. We need to add:
- Inventory quantity tracking on products
- Low stock alert event emission

- [ ] **Step 2: Add inventory update endpoint**

Add to `plugins/kbs_store/routes.py` inside `register_routes(bp)`:

```python
    @bp.route("/api/products/<int:product_id>/inventory", methods=["PUT"])
    @login_required
    @require_module("store")
    def update_inventory(product_id):
        data = request.get_json(force=True)
        quantity = data.get("quantity")
        if quantity is None:
            return jsonify({"error": "quantity is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE products SET stock_quantity = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING id, name, stock_quantity
                """,
                (int(quantity), product_id),
            )
            product = cur.fetchone()

        if not product:
            return jsonify({"error": "product not found"}), 404

        # Emit low stock alert if below threshold
        if product["stock_quantity"] <= 5:
            event_bus.emit(
                "product.low_stock",
                {"product_id": product["id"], "name": product["name"], "stock_quantity": product["stock_quantity"]},
                tenant_id=g.tenant_id,
            )

        return jsonify(product)
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_store/routes.py
git commit -m "feat(store): add inventory quantity tracking with low stock alerts"
```

---

## Task 8: Help Desk — SLA Deadline Tracking

**Files:**
- Modify: `plugins/kbs_help_desk/routes.py`

- [ ] **Step 1: Add SLA fields to ticket creation**

In `plugins/kbs_help_desk/routes.py`, update the `create_ticket` function. After the INSERT query, add SLA deadline calculation:

```python
    @bp.route("/api/tickets/<int:ticket_id>/sla", methods=["GET"])
    @login_required
    @require_module("help-desk")
    def get_ticket_sla(ticket_id):
        """Get SLA status for a ticket."""
        with get_db_cursor(dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, ticket_number, priority, status, created_at, resolved_at,
                    CASE priority
                        WHEN 'urgent' THEN created_at + INTERVAL '4 hours'
                        WHEN 'high' THEN created_at + INTERVAL '8 hours'
                        WHEN 'medium' THEN created_at + INTERVAL '24 hours'
                        WHEN 'low' THEN created_at + INTERVAL '72 hours'
                        ELSE created_at + INTERVAL '24 hours'
                    END AS sla_deadline,
                    CASE
                        WHEN resolved_at IS NOT NULL THEN 'met'
                        WHEN NOW() > CASE priority
                            WHEN 'urgent' THEN created_at + INTERVAL '4 hours'
                            WHEN 'high' THEN created_at + INTERVAL '8 hours'
                            WHEN 'medium' THEN created_at + INTERVAL '24 hours'
                            WHEN 'low' THEN created_at + INTERVAL '72 hours'
                            ELSE created_at + INTERVAL '24 hours'
                        END THEN 'breached'
                        ELSE 'on_track'
                    END AS sla_status
                FROM support_tickets WHERE id = %s
                """,
                (ticket_id,),
            )
            ticket = cur.fetchone()

        if not ticket:
            return jsonify({"error": "ticket not found"}), 404

        return jsonify(ticket)
```

- [ ] **Step 2: Add SLA summary endpoint**

```python
    @bp.route("/api/sla/summary", methods=["GET"])
    @login_required
    @require_module("help-desk")
    def sla_summary():
        """Get overall SLA compliance summary."""
        with get_db_cursor(dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE resolved_at IS NOT NULL AND resolved_at <=
                        CASE priority
                            WHEN 'urgent' THEN created_at + INTERVAL '4 hours'
                            WHEN 'high' THEN created_at + INTERVAL '8 hours'
                            WHEN 'medium' THEN created_at + INTERVAL '24 hours'
                            WHEN 'low' THEN created_at + INTERVAL '72 hours'
                            ELSE created_at + INTERVAL '24 hours'
                        END
                    ) AS met,
                    COUNT(*) FILTER (WHERE resolved_at IS NULL AND NOW() >
                        CASE priority
                            WHEN 'urgent' THEN created_at + INTERVAL '4 hours'
                            WHEN 'high' THEN created_at + INTERVAL '8 hours'
                            WHEN 'medium' THEN created_at + INTERVAL '24 hours'
                            WHEN 'low' THEN created_at + INTERVAL '72 hours'
                            ELSE created_at + INTERVAL '24 hours'
                        END
                    ) AS breached
                FROM support_tickets
                WHERE created_at >= NOW() - INTERVAL '30 days'
                """
            )
            row = cur.fetchone()

        total = row["total"] or 0
        met = row["met"] or 0
        breached = row["breached"] or 0

        return jsonify({
            "total_tickets_30d": total,
            "sla_met": met,
            "sla_breached": breached,
            "compliance_rate": round((met / total * 100), 1) if total > 0 else 100.0,
        })
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_help_desk/routes.py
git commit -m "feat(help-desk): add SLA deadline tracking with priority-based intervals"
```

---

## Task 9: Integration Test — Full Invoice Flow

**Files:**
- Create: `tests/test_invoice_flow_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_invoice_flow_integration.py`:

```python
"""Integration test: create customer → create invoice → generate PDF → send."""

import pytest
from unittest.mock import patch


def test_invoice_pdf_generation_with_real_data():
    """Test the full PDF pipeline with realistic data."""
    from core.pdf_generator import generate_invoice_pdf
    from core.email_templates import render_invoice_email

    invoice = {
        "invoice_number": "INV-0100",
        "created_at": "2026-03-28T14:30:00",
        "due_date": "2026-04-28",
        "status": "sent",
        "customer_name": "Acme Construction Ltd.",
        "customer_email": "billing@acme.ca",
        "notes": "Net 30 terms. Late fees of 1.5% per month apply.",
        "items": [
            {"description": "Foundation inspection — 123 Main St", "quantity": 1, "unit_price": 350.00, "amount": 350.00},
            {"description": "Electrical panel review", "quantity": 2, "unit_price": 175.00, "amount": 350.00},
            {"description": "HVAC commissioning report", "quantity": 1, "unit_price": 500.00, "amount": 500.00},
        ],
        "subtotal": 1200.00,
        "tax_rate": 13.0,
        "tax_amount": 156.00,
        "total": 1356.00,
    }

    business = {
        "name": "Kytran Empowerment Inc.",
        "email": "billing@kytranempowerment.com",
        "phone": "(613) 555-0199",
        "address": "Ottawa, ON, Canada",
    }

    # Generate PDF
    pdf_bytes = generate_invoice_pdf(invoice, business)
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 500  # Real PDF with content

    # Render email
    html, text = render_invoice_email(
        invoice_number="INV-0100",
        customer_name="Acme Construction Ltd.",
        total=1356.00,
        due_date="April 28, 2026",
        business_name="Kytran Empowerment Inc.",
    )
    assert "INV-0100" in html
    assert "$1,356.00" in html
    assert "Acme Construction" in text


def test_inbound_email_to_ticket_pipeline():
    """Test email parsing → ticket data extraction."""
    from core.inbound_email import parse_inbound_email

    # Simulate inbound email
    raw = {
        "from": "Sarah Chen <sarah@acme.ca>",
        "subject": "Urgent: Invoice discrepancy on INV-0100",
        "body_plain": "Hi, I noticed the HVAC commissioning was billed at $500 but our contract says $450. Can you please review?",
    }

    parsed = parse_inbound_email(raw)

    assert parsed["sender_email"] == "sarah@acme.ca"
    assert parsed["sender_name"] == "Sarah Chen"
    assert "Invoice discrepancy" in parsed["subject"]
    assert "HVAC commissioning" in parsed["body"]
    assert parsed["is_reply"] is False  # No HD-NNNN in subject

    # Simulate reply to existing ticket
    reply = {
        "from": "sarah@acme.ca",
        "subject": "Re: HD-0001: Urgent: Invoice discrepancy on INV-0100",
        "body_plain": "Thanks for looking into this!",
    }

    parsed_reply = parse_inbound_email(reply)
    assert parsed_reply["is_reply"] is True
    assert parsed_reply["ticket_number"] == "HD-0001"
```

- [ ] **Step 2: Run integration tests**

```bash
docker exec kbs_app python -m pytest tests/test_invoice_flow_integration.py -v
```

Expected: 2 passed

- [ ] **Step 3: Run ALL Plan A tests together**

```bash
docker exec kbs_app python -m pytest tests/test_pdf_generator.py tests/test_email_templates.py tests/test_invoicing_send.py tests/test_helpdesk_email_intake.py tests/test_crm_search.py tests/test_invoice_flow_integration.py -v
```

Expected: All pass (14+ tests)

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add tests/test_invoice_flow_integration.py
git commit -m "test: add integration tests for invoice and help desk email flows"
```

---

## Summary

After completing all 9 tasks, the core plugins are production-ready with:

- **Invoicing**: PDF generation (LCARS-styled), email delivery on send, PDF download endpoint
- **Help Desk**: Inbound email → ticket creation, CRM contact matching, ticket confirmation emails, SLA deadline tracking with priority-based intervals
- **CRM**: Full-text search across name/email/company, segment-based filtering
- **Store**: Inventory quantity tracking with low stock event alerts
- **Email**: Transactional templates (invoice, ticket created, ticket updated) wired to SMTP

**Next plan:** Plan B (Appointments + Booking) builds on this foundation — booking confirmations use the same email templates and mail_client.
