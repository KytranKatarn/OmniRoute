"""
P.R.O.B.E. QA Report Service — PDF report generator for QA test runs.

Converts QA test run results into styled HTML, then renders to PDF
via weasyprint. Reports are saved to static/qa_reports/ and the
path is persisted on the qa_test_runs row.
"""

import logging
import os
from datetime import datetime, timezone

import jinja2

logger = logging.getLogger(__name__)

try:
    from weasyprint import HTML as WeasyprintHTML
except ImportError:
    WeasyprintHTML = None
    logger.warning(
        "weasyprint not installed — PDF report generation will be unavailable. " "Install with: pip install weasyprint"
    )

TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "qa",
    "report_templates",
)

REPORT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static",
    "qa_reports",
)

# Ensure the output directory exists at import time
os.makedirs(REPORT_DIR, exist_ok=True)


def generate_report(run_id, branded=False):
    """Generate a PDF report for a QA test run.

    Args:
        run_id: The ID of the qa_test_runs row.
        branded: If True, use the client-facing branded template with
                 Kytran Empowerment header and C.R.E.E.D. badge.

    Returns:
        Absolute file path of the generated PDF, or None on failure.
    """
    try:
        # Late import to avoid circular dependency
        from services.qa_service import get_run_results

        run = get_run_results(run_id)
        if not run:
            logger.error("No run data found for run_id=%s", run_id)
            return None

        html_content = _build_template_html(run, branded=branded)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

        # Try PDF first, fall back to HTML if weasyprint unavailable
        if WeasyprintHTML is not None:
            filename = f"qa-report-{run_id}-{timestamp}.pdf"
            filepath = os.path.join(REPORT_DIR, filename)
            WeasyprintHTML(string=html_content).write_pdf(filepath)
        else:
            filename = f"qa-report-{run_id}-{timestamp}.html"
            filepath = os.path.join(REPORT_DIR, filename)
            with open(filepath, "w") as f:
                f.write(html_content)
            logger.info("weasyprint unavailable — generated HTML report instead")

        # Persist the report path on the test run row
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE qa_test_runs SET report_path = %s WHERE id = %s",
                    (filepath, run_id),
                )
        except Exception:
            logger.exception("Failed to update report_path for run_id=%s", run_id)

        logger.info("QA report generated: %s", filepath)
        return filepath

    except Exception:
        logger.exception("Failed to generate QA report for run_id=%s", run_id)
        return None


def _build_template_html(run, branded=False):
    """Build report HTML from Jinja2 templates.

    Falls back to the inline _build_report_html() if templates are missing.
    """
    template_name = "branded.html" if branded else "internal.html"
    template_path = os.path.join(TEMPLATE_DIR, template_name)

    if not os.path.exists(template_path):
        logger.warning("Template %s not found, falling back to inline HTML", template_name)
        return _build_report_html(run)

    total = run.get("total_tests", 0)
    passed = run.get("passed", 0)
    failed = run.get("failed", 0)
    errors = run.get("errors", 0)
    results = run.get("results", [])
    pass_rate = round(passed / total * 100, 1) if total > 0 else 0

    failures = [r for r in results if r.get("status") in ("fail", "error")]

    with open(template_path) as f:
        template_str = f.read()

    template = jinja2.Template(template_str)
    return template.render(
        suite_name=run.get("suite_name", "Unknown Suite"),
        run_date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        run_id=run.get("id", "?"),
        total=total,
        passed=passed,
        failed=failed,
        errors=errors,
        pass_rate=pass_rate,
        results=results,
        failures=failures,
    )


def _build_report_html(run):
    """Build a self-contained HTML document for the QA report.

    Uses LCARS-inspired dark theme with inline CSS so the PDF
    renderer needs no external resources.
    """
    run_id = run.get("id", "?")
    suite_name = run.get("suite_name", "Unknown Suite")
    status = run.get("status", "unknown")
    total = run.get("total_tests", 0)
    passed = run.get("passed", 0)
    run.get("failed", 0)
    run.get("errors", 0)
    duration_ms = run.get("duration_ms", 0)
    started_at = run.get("started_at", "N/A")
    results = run.get("results", [])

    pass_rate = (passed / total * 100) if total > 0 else 0
    status_color = "#10b981" if status == "completed" else "#ef4444"
    status_label = status.upper()

    # Build table rows
    rows_html = ""
    for r in results:
        t_name = r.get("test_name", "")
        t_type = r.get("test_type", "")
        t_status = r.get("status", "unknown")
        t_time = r.get("response_time_ms", 0)
        t_error = r.get("error_message") or ""

        color_map = {
            "pass": "#10b981",
            "fail": "#ef4444",
            "error": "#f59e0b",
            "skip": "#6b7280",
        }
        t_color = color_map.get(t_status, "#6b7280")

        rows_html += f"""
            <tr>
                <td>{t_name}</td>
                <td>{t_type}</td>
                <td style="color:{t_color};font-weight:bold;">{t_status.upper()}</td>
                <td style="text-align:right;">{t_time} ms</td>
                <td class="details">{t_error}</td>
            </tr>"""

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>P.R.O.B.E. QA Report — Run #{run_id}</title>
<style>
    @page {{
        size: A4 landscape;
        margin: 1.5cm;
    }}
    * {{
        box-sizing: border-box;
        margin: 0;
        padding: 0;
    }}
    body {{
        background: #0a0a1a;
        color: #e0e0e0;
        font-family: "Courier New", Courier, monospace;
        font-size: 11px;
        line-height: 1.5;
        padding: 20px;
    }}
    .header {{
        border-bottom: 2px solid #00e5ff;
        padding-bottom: 12px;
        margin-bottom: 20px;
    }}
    .header h1 {{
        color: #00e5ff;
        font-size: 22px;
        letter-spacing: 2px;
        margin-bottom: 4px;
    }}
    .header .subtitle {{
        color: #8b5cf6;
        font-size: 13px;
    }}
    .header .meta {{
        color: #9ca3af;
        font-size: 10px;
        margin-top: 4px;
    }}
    .summary {{
        display: flex;
        gap: 16px;
        margin-bottom: 24px;
    }}
    .card {{
        flex: 1;
        border: 1px solid #1e293b;
        border-radius: 6px;
        padding: 12px;
        background: #111827;
        text-align: center;
    }}
    .card .label {{
        color: #9ca3af;
        font-size: 9px;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 4px;
    }}
    .card .value {{
        font-size: 20px;
        font-weight: bold;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 20px;
    }}
    th {{
        background: #1e293b;
        color: #00e5ff;
        text-align: left;
        padding: 8px 10px;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 1px;
        border-bottom: 1px solid #00e5ff;
    }}
    td {{
        padding: 6px 10px;
        border-bottom: 1px solid #1e293b;
        font-size: 10px;
        vertical-align: top;
    }}
    tr:nth-child(even) {{
        background: #0f172a;
    }}
    td.details {{
        color: #9ca3af;
        max-width: 300px;
        word-wrap: break-word;
    }}
    .footer {{
        border-top: 1px solid #1e293b;
        padding-top: 10px;
        text-align: center;
        color: #6b7280;
        font-size: 9px;
    }}
    .footer span {{
        color: #8b5cf6;
    }}
</style>
</head>
<body>

<div class="header">
    <h1>P.R.O.B.E. QA Report</h1>
    <div class="subtitle">{suite_name}</div>
    <div class="meta">Run #{run_id} &mdash; Started {started_at}</div>
</div>

<div class="summary">
    <div class="card">
        <div class="label">Status</div>
        <div class="value" style="color:{status_color};">{status_label}</div>
    </div>
    <div class="card">
        <div class="label">Pass Rate</div>
        <div class="value" style="color:#00e5ff;">{pass_rate:.1f}%</div>
    </div>
    <div class="card">
        <div class="label">Tests</div>
        <div class="value" style="color:#e0e0e0;">{passed} / {total}</div>
    </div>
    <div class="card">
        <div class="label">Duration</div>
        <div class="value" style="color:#e0e0e0;">{duration_ms} ms</div>
    </div>
</div>

<table>
    <thead>
        <tr>
            <th>Test Name</th>
            <th>Type</th>
            <th>Status</th>
            <th style="text-align:right;">Time</th>
            <th>Details</th>
        </tr>
    </thead>
    <tbody>{rows_html}
    </tbody>
</table>

<div class="footer">
    Generated by <span>P.R.O.B.E.</span> &mdash; {generated_at}
</div>

</body>
</html>"""

    return html
