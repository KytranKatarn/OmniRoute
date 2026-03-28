"""Invoice PDF Generator with LCARS styling."""
from io import BytesIO
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER


# LCARS color palette
CYAN = colors.HexColor("#00e5ff")
DARK_BG = colors.HexColor("#1a1a2e")
ROW_DARK = colors.HexColor("#0d0d1a")
ROW_LIGHT = colors.HexColor("#141428")
WHITE = colors.white
GRAY = colors.HexColor("#aaaaaa")
BLACK = colors.black


def _format_date(date_str: str) -> str:
    """Convert ISO date string (YYYY-MM-DD) to 'March 28, 2026'."""
    if not date_str:
        return ""
    try:
        # Handle datetime strings with time component
        date_part = date_str.split("T")[0].split(" ")[0]
        dt = datetime.strptime(date_part, "%Y-%m-%d")
        return dt.strftime("%B %d, %Y")
    except (ValueError, AttributeError):
        return str(date_str)


def generate_invoice_pdf(invoice: dict, business: dict) -> bytes:
    """Generate a LCARS-styled invoice PDF.

    Args:
        invoice: Invoice data dict with keys: invoice_number, created_at,
                 due_date, status, customer_name, customer_email, notes,
                 items (list), subtotal, tax_rate, tax_amount, total
        business: Business info dict with keys: name, email, phone, address

    Returns:
        PDF bytes starting with %PDF-
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    style_business_name = ParagraphStyle(
        "BusinessName",
        parent=styles["Normal"],
        fontSize=20,
        textColor=CYAN,
        fontName="Helvetica-Bold",
        spaceAfter=4,
    )
    style_contact = ParagraphStyle(
        "Contact",
        parent=styles["Normal"],
        fontSize=9,
        textColor=GRAY,
        spaceAfter=2,
    )
    style_section_label = ParagraphStyle(
        "SectionLabel",
        parent=styles["Normal"],
        fontSize=8,
        textColor=CYAN,
        fontName="Helvetica-Bold",
        spaceAfter=2,
    )
    style_normal_white = ParagraphStyle(
        "NormalWhite",
        parent=styles["Normal"],
        fontSize=9,
        textColor=WHITE,
    )
    style_notes = ParagraphStyle(
        "Notes",
        parent=styles["Normal"],
        fontSize=9,
        textColor=GRAY,
        spaceAfter=4,
    )

    elements = []

    # ── Header: business name + contact info ──────────────────────────────────
    elements.append(Paragraph(business.get("name", ""), style_business_name))
    if business.get("email"):
        elements.append(Paragraph(business["email"], style_contact))
    if business.get("phone"):
        elements.append(Paragraph(business["phone"], style_contact))
    if business.get("address"):
        elements.append(Paragraph(business["address"], style_contact))

    elements.append(Spacer(1, 0.2 * inch))

    # ── Meta table: invoice details + bill-to ────────────────────────────────
    status_display = invoice.get("status", "").upper()
    meta_data = [
        [
            Paragraph("INVOICE", style_section_label),
            Paragraph("BILL TO", style_section_label),
        ],
        [
            Paragraph(invoice.get("invoice_number", ""), style_normal_white),
            Paragraph(invoice.get("customer_name", ""), style_normal_white),
        ],
        [
            Paragraph(
                f"Date: {_format_date(invoice.get('created_at', ''))}",
                style_normal_white,
            ),
            Paragraph(invoice.get("customer_email", ""), style_notes),
        ],
        [
            Paragraph(
                f"Due: {_format_date(invoice.get('due_date', ''))}",
                style_normal_white,
            ),
            Paragraph("", style_normal_white),
        ],
        [
            Paragraph(f"Status: {status_display}", style_normal_white),
            Paragraph("", style_normal_white),
        ],
    ]

    page_width = letter[0] - inch  # total usable width
    meta_table = Table(meta_data, colWidths=[page_width * 0.5, page_width * 0.5])
    meta_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), DARK_BG),
                ("TEXTCOLOR", (0, 0), (-1, -1), WHITE),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [DARK_BG]),
            ]
        )
    )
    elements.append(meta_table)
    elements.append(Spacer(1, 0.2 * inch))

    # ── Line items table ──────────────────────────────────────────────────────
    col_widths = [
        page_width * 0.45,
        page_width * 0.15,
        page_width * 0.20,
        page_width * 0.20,
    ]

    style_header_cell = ParagraphStyle(
        "HeaderCell",
        parent=styles["Normal"],
        fontSize=9,
        textColor=CYAN,
        fontName="Helvetica-Bold",
    )
    style_cell = ParagraphStyle(
        "Cell",
        parent=styles["Normal"],
        fontSize=9,
        textColor=WHITE,
    )
    style_cell_right = ParagraphStyle(
        "CellRight",
        parent=styles["Normal"],
        fontSize=9,
        textColor=WHITE,
        alignment=TA_RIGHT,
    )

    items_data = [
        [
            Paragraph("DESCRIPTION", style_header_cell),
            Paragraph("QTY", style_header_cell),
            Paragraph("UNIT PRICE", style_header_cell),
            Paragraph("AMOUNT", style_header_cell),
        ]
    ]

    for item in invoice.get("items", []):
        items_data.append(
            [
                Paragraph(str(item.get("description", "")), style_cell),
                Paragraph(str(item.get("quantity", "")), style_cell_right),
                Paragraph(f"${item.get('unit_price', 0):,.2f}", style_cell_right),
                Paragraph(f"${item.get('amount', 0):,.2f}", style_cell_right),
            ]
        )

    items_table = Table(items_data, colWidths=col_widths)

    row_count = len(items_data)
    row_styles = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), CYAN),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#2a2a4a")),
    ]

    # Alternating row backgrounds for data rows
    for i in range(1, row_count):
        bg = ROW_DARK if i % 2 == 1 else ROW_LIGHT
        row_styles.append(("BACKGROUND", (0, i), (-1, i), bg))

    items_table.setStyle(TableStyle(row_styles))
    elements.append(items_table)
    elements.append(Spacer(1, 0.15 * inch))

    # ── Totals ────────────────────────────────────────────────────────────────
    style_total_label = ParagraphStyle(
        "TotalLabel",
        parent=styles["Normal"],
        fontSize=9,
        textColor=GRAY,
        alignment=TA_RIGHT,
    )
    style_total_value = ParagraphStyle(
        "TotalValue",
        parent=styles["Normal"],
        fontSize=9,
        textColor=WHITE,
        alignment=TA_RIGHT,
    )
    style_total_grand_label = ParagraphStyle(
        "TotalGrandLabel",
        parent=styles["Normal"],
        fontSize=11,
        textColor=CYAN,
        fontName="Helvetica-Bold",
        alignment=TA_RIGHT,
    )
    style_total_grand_value = ParagraphStyle(
        "TotalGrandValue",
        parent=styles["Normal"],
        fontSize=11,
        textColor=CYAN,
        fontName="Helvetica-Bold",
        alignment=TA_RIGHT,
    )

    totals_data = [
        [
            Paragraph("Subtotal:", style_total_label),
            Paragraph(f"${invoice.get('subtotal', 0):,.2f}", style_total_value),
        ]
    ]

    tax_rate = invoice.get("tax_rate", 0)
    if tax_rate and float(tax_rate) > 0:
        totals_data.append(
            [
                Paragraph(f"Tax ({tax_rate}%):", style_total_label),
                Paragraph(
                    f"${invoice.get('tax_amount', 0):,.2f}", style_total_value
                ),
            ]
        )

    totals_data.append(
        [
            Paragraph("TOTAL:", style_total_grand_label),
            Paragraph(f"${invoice.get('total', 0):,.2f}", style_total_grand_value),
        ]
    )

    totals_table = Table(
        totals_data,
        colWidths=[page_width * 0.85, page_width * 0.15],
    )

    total_row_idx = len(totals_data) - 1
    totals_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0a0a1a")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                # Cyan line above TOTAL row
                (
                    "LINEABOVE",
                    (0, total_row_idx),
                    (-1, total_row_idx),
                    1.5,
                    CYAN,
                ),
            ]
        )
    )
    elements.append(totals_table)

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = invoice.get("notes", "")
    if notes:
        elements.append(Spacer(1, 0.2 * inch))
        elements.append(Paragraph("NOTES", style_section_label))
        elements.append(Paragraph(str(notes), style_notes))

    # Build PDF
    doc.build(elements)
    return buffer.getvalue()
