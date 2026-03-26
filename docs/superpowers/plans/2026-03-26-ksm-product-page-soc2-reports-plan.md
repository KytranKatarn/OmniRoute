# KSM Product Page + SOC 2 Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a public product page for Kytran System Operations with pricing, a standalone splash page, SOC 2 evidence collection during compliance scans, HTML compliance reports, and branded PDF generation.

**Architecture:** Product page follows the existing standalone-HTML pattern (like `/competitors`). Standalone splash replaces the login redirect at `/`. Evidence collection hooks into the existing `run_scan()` flow. HTML reports render from scan data with print-friendly CSS. WeasyPrint generates PDFs from the same HTML.

**Tech Stack:** Python/Flask, Jinja2, WeasyPrint (PDF), SQLite, HTML/CSS (standalone pages — no template inheritance)

---

## File Map

### Phase 1: Product Pages
| Action | File | What |
|--------|------|------|
| Create | `platform_v2/templates/products/system_operations.html` | Public product page with pricing |
| Create | `platform_v2/static/css/products.css` | Product page styles |
| Modify | `platform_v2/app.py` | Add `/products/system-operations` route |
| Create | `kytran-server-manager/.../templates/splash.html` | Standalone splash/landing page |
| Modify | `kytran-server-manager/.../auth.py` | Serve splash at `/` for unauthenticated users |

### Phase 2: SOC 2 Evidence + Reports
| Action | File | What |
|--------|------|------|
| Modify | `kytran-server-manager/.../db.py` | Add `compliance_evidence` table |
| Modify | `kytran-server-manager/.../services/compliance_service.py` | Hook evidence collection into `run_scan()` |
| Create | `kytran-server-manager/.../services/report_service.py` | PDF generation with WeasyPrint |
| Create | `kytran-server-manager/.../templates/compliance_report.html` | HTML report template |
| Modify | `kytran-server-manager/.../routes/compliance_routes.py` | Report view + PDF download routes |
| Modify | `kytran-server-manager/.../templates/dashboard.html` | Report links in scan history |

---

## Phase 1: Product Pages

### Task 1: ARCHIE Product Page

**Files:**
- Create: `platform_v2/templates/products/system_operations.html`
- Create: `platform_v2/static/css/products.css`
- Modify: `platform_v2/app.py`

- [ ] **Step 1: Read the existing public page pattern**

Read `/mnt/archie_brain/platform_v2/templates/competitors.html` (first 60 lines) and find the `/competitors` route in `app.py` to understand how public (no-login) pages are structured. These are standalone HTML pages, NOT extending base.html.

- [ ] **Step 2: Create the products directory**

```bash
mkdir -p /mnt/archie_brain/platform_v2/templates/products
```

- [ ] **Step 3: Create products.css**

Create `/mnt/archie_brain/platform_v2/static/css/products.css` with styles for the product page. Dark theme matching `/competitors`:

- Background: `#020617`
- Text: `#F8FAFC`
- Purple accent: `#8b5cf6`
- Gold CTA: `#f59e0b`
- Card backgrounds: `rgba(15,23,42,0.6)` with `border: 1px solid rgba(139,92,246,0.15)`
- Hero section with gradient overlay
- Pricing table with 4 columns (Free/Pro/Business/Enterprise)
- Responsive grid at 480/768/1024px
- Feature matrix with checkmarks and dashes
- CTA buttons with hover glow

- [ ] **Step 4: Create the product page template**

Create `/mnt/archie_brain/platform_v2/templates/products/system_operations.html` — standalone DOCTYPE HTML (same pattern as competitors.html):

Sections:
1. **Nav bar**: Kytran logo + links to Trust Center (/iaae), Competitors (/competitors), Products
2. **Hero**: "Kytran System Operations" title, "Server Management + Compliance Scanning" subtitle, "Start Free" CTA button
3. **Live badges**: Embed SVG badges from standalone (`<img src="http://192.168.1.200:8085/dashboard/api/compliance/badge/overall.svg">` etc.), with "178 automated checks, 5 frameworks" text
4. **Pricing table**: 4 columns with feature matrix matching the spec. CTAs: "Start Free" / "Get Pro" / "Get Business" / "Contact Sales"
5. **How It Works**: 3 cards — Install (one command: `pip install kytran-server-manager`), Scan (automatic compliance), Report (PDF + badges)
6. **Trust section**: "Built on the same compliance engine that powers A.R.C.H.I.E." with links to /iaae and /competitors
7. **Footer**: Copyright, links

- [ ] **Step 5: Add route to app.py**

Read `/mnt/archie_brain/platform_v2/app.py` and find where the `/competitors` route is defined. Add nearby:

```python
@app.route("/products/system-operations")
def product_system_operations():
    """Public product page for Kytran System Operations."""
    return render_template("products/system_operations.html")
```

No `@login_required` — this is a public page.

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/templates/products/system_operations.html platform_v2/static/css/products.css platform_v2/app.py
git commit -m "feat(products): add public product page for Kytran System Operations"
```

---

### Task 2: Standalone Splash Page

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/templates/splash.html`
- Modify: `kytran-server-manager/kytran_server_manager/auth.py`

- [ ] **Step 1: Read current root route behavior**

Read `/mnt/archie_brain/kytran-server-manager/kytran_server_manager/auth.py` — find how `/` is handled (likely redirects to login). Also check `routes/core_routes.py` for any root route.

- [ ] **Step 2: Create splash.html**

Create `/mnt/archie_brain/kytran-server-manager/kytran_server_manager/templates/splash.html` — standalone HTML (does NOT extend base.html):

- Dark background (#0a0a0f), LCARS-inspired
- Centered content card with Kytran System Operations branding
- Tagline: "Server Management + Compliance Scanning"
- Two primary buttons: "Login" (→ /login) and "Sign in with Kytran" (→ /auth/sso, only if hub configured — use a Jinja2 conditional `{% if sso_enabled %}`)
- 4 brief feature bullets with icons (CSS-only, no emoji):
  - System Monitoring (CPU, RAM, disk, Docker)
  - Compliance Scanning (178 rules, 5 frameworks)
  - Live Badges (SVG compliance badges)
  - Automated Remediation (one-click fixes)
- Overall compliance badge at bottom: `<img src="/dashboard/api/compliance/badge/overall.svg">`
- "Learn More" link → product page URL
- Responsive, fast-loading, minimal dependencies

- [ ] **Step 3: Modify root route**

In `auth.py`, find the root `/` route or the login redirect. Change it so:
- If user is authenticated → redirect to dashboard (same as before)
- If not authenticated → render splash.html with `sso_enabled` context

```python
@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("sysops.dashboard_home"))
    sso_enabled = bool(app.config.get("ARCHIE_HUB_URL"))
    return render_template("splash.html", sso_enabled=sso_enabled)
```

IMPORTANT: Read the existing code first. The root route may be defined elsewhere. Adapt to the actual pattern.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/templates/splash.html kytran_server_manager/auth.py
git commit -m "feat(splash): add public landing page for standalone"
```

---

## Phase 2: SOC 2 Evidence + Reports

### Task 3: Evidence Table + Collection

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/db.py`
- Modify: `kytran-server-manager/kytran_server_manager/services/compliance_service.py`

- [ ] **Step 1: Read db.py and compliance_service.py**

- Read `db.py` — find `init_db()` to add the evidence table
- Read `compliance_service.py` — find `run_scan()` and understand:
  - Where individual rule checks happen
  - What data is available after each check (command output, file content, etc.)
  - The existing `collect_evidence()` function (line ~1418) — it may already do some of what we need

- [ ] **Step 2: Add compliance_evidence table to db.py**

In `init_db()`, add:

```python
    cur.execute("""
        CREATE TABLE IF NOT EXISTS compliance_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER NOT NULL,
            rule_id TEXT NOT NULL,
            pack_id TEXT NOT NULL,
            evidence_type TEXT NOT NULL CHECK(evidence_type IN ('command_output', 'file_content', 'config_snapshot', 'service_status', 'log_excerpt')),
            content TEXT NOT NULL,
            soc2_mapping TEXT,
            collected_at TEXT DEFAULT (datetime('now'))
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_evidence_scan ON compliance_evidence(scan_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_evidence_soc2 ON compliance_evidence(soc2_mapping)")
```

- [ ] **Step 3: Hook evidence collection into run_scan()**

In `compliance_service.py`, find where individual rule results are processed after each check. After recording the pass/fail result, add evidence collection:

```python
def _collect_rule_evidence(db, scan_id, rule, check_result):
    """Store evidence artifact for a compliance rule check."""
    evidence_type_map = {
        "command_output": "command_output",
        "file_content": "file_content",
        "file_contains": "file_content",
        "sysctl_value": "config_snapshot",
        "service_status": "service_status",
        "docker_config": "config_snapshot",
    }
    evidence_type = evidence_type_map.get(rule.get("check_type", ""), "command_output")
    content = check_result.get("output", check_result.get("value", str(check_result.get("actual", ""))))
    if not content:
        content = f"Status: {check_result.get('status', 'unknown')}"

    soc2 = rule.get("soc2_mapping", "")

    db.execute(
        """INSERT INTO compliance_evidence (scan_id, rule_id, pack_id, evidence_type, content, soc2_mapping)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (scan_id, rule.get("rule_id", ""), rule.get("pack_id", ""), evidence_type, content[:10000], soc2),
    )
```

Call this function after each rule check in the scan loop. Read the existing code to find the exact insertion point.

IMPORTANT: The existing `collect_evidence()` function may already handle some of this. Read it first and extend rather than duplicate.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/db.py kytran_server_manager/services/compliance_service.py
git commit -m "feat(evidence): SOC 2 evidence collection during compliance scans"
```

---

### Task 4: HTML Compliance Report Template

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/templates/compliance_report.html`

- [ ] **Step 1: Create the report template**

Create `/mnt/archie_brain/kytran-server-manager/kytran_server_manager/templates/compliance_report.html` — standalone HTML that works both in browser AND as print/PDF source.

Template receives these variables:
- `scan` — scan record (id, overall_score, scanned_at, pack_ids)
- `pack_scores` — dict of {pack_id: {score, passed, failed, total}}
- `findings` — list of rule results sorted by severity
- `evidence_by_tsc` — dict of {tsc_code: [evidence records]} grouped by SOC 2 criteria
- `server_info` — hostname, OS, IP
- `tier_prices` — for upgrade prompts if needed

Sections:
1. **Cover/Header**: Kytran logo, "Compliance Report", scan date, hostname, overall score badge
2. **Executive Summary**: Overall score, grade, total rules, pass/fail counts, 2-3 sentence summary
3. **Framework Scores**: Table — pack name, rules count, passed, failed, score, grade. Color-coded rows.
4. **SOC 2 TSC Evidence**: For each TSC (CC6.1, CC6.6, CC7.1, etc.):
   - Criteria name and description
   - Related rules with pass/fail status
   - Evidence artifacts (collapsible in browser, always shown in PDF)
   - Assessment: compliant / partially / non-compliant
5. **Detailed Findings**: Grouped by severity (high → medium → low). Each finding shows: rule ID, title, pack, status, evidence, remediation command
6. **Remediation Summary**: Failed rules only, with fix commands

Styling:
- Browser: LCARS dark theme (dark bg, purple/green/red accents)
- Print (`@media print`): White background, black text, no nav elements, clean serif font, page breaks between sections
- Both: Tables with borders, score badges color-coded

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/templates/compliance_report.html
git commit -m "feat(reports): add HTML compliance report template with print CSS"
```

---

### Task 5: Report Service (PDF Generation)

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/services/report_service.py`

- [ ] **Step 1: Install WeasyPrint dependencies**

```bash
sudo apt-get install -y libpango-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 2>/dev/null
pip3 install weasyprint
```

- [ ] **Step 2: Create report_service.py**

```python
"""Compliance report generation service — HTML rendering + PDF via WeasyPrint."""

import os
import logging
from datetime import datetime
from flask import render_template, current_app

logger = logging.getLogger(__name__)

WEASYPRINT_AVAILABLE = False
try:
    import weasyprint
    WEASYPRINT_AVAILABLE = True
except ImportError:
    logger.warning("WeasyPrint not installed — PDF generation unavailable. Install with: pip install weasyprint")


def get_reports_dir():
    """Get (and create if needed) the reports storage directory."""
    data_dir = current_app.config.get("DATA_DIR", "/var/lib/kytran-server-manager")
    reports_dir = os.path.join(data_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    return reports_dir


def get_scan_report_data(scan_id):
    """Fetch all data needed to render a compliance report."""
    from ..db import get_db
    import json
    import socket

    db = get_db()
    try:
        # Scan record
        cur = db.execute("SELECT * FROM compliance_scans WHERE id = ?", (scan_id,))
        scan = cur.fetchone()
        if not scan:
            return None

        # Convert Row to dict if needed
        scan = dict(scan) if scan else None

        # Pack scores
        pack_scores = {}
        cur = db.execute(
            """SELECT pack_id,
                      COUNT(*) as total,
                      SUM(CASE WHEN status = 'pass' THEN 1 ELSE 0 END) as passed,
                      SUM(CASE WHEN status = 'fail' THEN 1 ELSE 0 END) as failed
               FROM compliance_scan_results WHERE scan_id = ?
               GROUP BY pack_id""",
            (scan_id,),
        )
        for row in cur.fetchall():
            row = dict(row)
            total = row["total"] or 1
            passed = row["passed"] or 0
            pack_scores[row["pack_id"]] = {
                "total": total,
                "passed": passed,
                "failed": row["failed"] or 0,
                "score": round(passed / total * 100, 1),
            }

        # Findings sorted by severity
        cur = db.execute(
            """SELECT r.*, rp.pack_id FROM compliance_scan_results r
               LEFT JOIN compliance_rule_packs rp ON r.pack_id = rp.pack_id
               WHERE r.scan_id = ?
               ORDER BY CASE r.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, r.rule_id""",
            (scan_id,),
        )
        findings = [dict(row) for row in cur.fetchall()]

        # Evidence grouped by SOC 2 TSC
        evidence_by_tsc = {}
        cur = db.execute(
            "SELECT * FROM compliance_evidence WHERE scan_id = ? ORDER BY soc2_mapping, rule_id",
            (scan_id,),
        )
        for row in cur.fetchall():
            row = dict(row)
            tsc = row.get("soc2_mapping") or "unmapped"
            if tsc not in evidence_by_tsc:
                evidence_by_tsc[tsc] = []
            evidence_by_tsc[tsc].append(row)

        # Server info
        server_info = {
            "hostname": socket.gethostname(),
            "os": "Ubuntu 22.04",
            "generated_at": datetime.utcnow().isoformat(),
        }

        return {
            "scan": scan,
            "pack_scores": pack_scores,
            "findings": findings,
            "evidence_by_tsc": evidence_by_tsc,
            "server_info": server_info,
        }
    finally:
        db.close()


def render_html_report(scan_id):
    """Render HTML compliance report for a scan."""
    data = get_scan_report_data(scan_id)
    if not data:
        return None
    return render_template("compliance_report.html", **data)


def generate_pdf_report(scan_id):
    """Generate PDF compliance report. Returns (pdf_bytes, filename) or (None, None)."""
    if not WEASYPRINT_AVAILABLE:
        return None, None

    html_content = render_html_report(scan_id)
    if not html_content:
        return None, None

    try:
        pdf_bytes = weasyprint.HTML(string=html_content).write_pdf()
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"compliance_report_{scan_id}_{timestamp}.pdf"

        # Save to disk
        reports_dir = get_reports_dir()
        filepath = os.path.join(reports_dir, filename)
        with open(filepath, "wb") as f:
            f.write(pdf_bytes)

        logger.info(f"PDF report generated: {filepath} ({len(pdf_bytes)} bytes)")
        return pdf_bytes, filename
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return None, None


def list_reports():
    """List all saved PDF reports."""
    reports_dir = get_reports_dir()
    reports = []
    for f in sorted(os.listdir(reports_dir), reverse=True):
        if f.endswith(".pdf"):
            filepath = os.path.join(reports_dir, f)
            reports.append({
                "filename": f,
                "size_bytes": os.path.getsize(filepath),
                "created_at": datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat(),
            })
    return reports
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/services/report_service.py
git commit -m "feat(reports): add report service with WeasyPrint PDF generation"
```

---

### Task 6: Report Routes + Dashboard Integration

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/routes/compliance_routes.py`
- Modify: `kytran-server-manager/kytran_server_manager/templates/dashboard.html`

- [ ] **Step 1: Read compliance_routes.py**

Read the current file to find where to add report routes. They go inside `register_compliance_routes()`.

- [ ] **Step 2: Add report routes**

Add these routes inside `register_compliance_routes()`:

```python
    @bp.route("/compliance/report/<int:scan_id>", methods=["GET"])
    @login_required
    @require_tier("business")
    def compliance_report_view(scan_id):
        """Render HTML compliance report."""
        from ..services.report_service import render_html_report
        html = render_html_report(scan_id)
        if not html:
            return jsonify({"error": "Scan not found"}), 404
        return html

    @bp.route("/api/compliance/report/<int:scan_id>/pdf", methods=["GET"])
    @login_required
    @require_tier("business")
    def compliance_report_pdf(scan_id):
        """Download PDF compliance report."""
        from ..services.report_service import generate_pdf_report
        pdf_bytes, filename = generate_pdf_report(scan_id)
        if not pdf_bytes:
            return jsonify({"error": "PDF generation failed or unavailable"}), 500
        from flask import send_file
        import io
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )

    @bp.route("/api/compliance/reports", methods=["GET"])
    @login_required
    @require_tier("business")
    def compliance_report_list():
        """List all saved PDF reports."""
        from ..services.report_service import list_reports
        return jsonify({"success": True, "reports": list_reports()})
```

- [ ] **Step 3: Add report links to dashboard**

Read `/mnt/archie_brain/kytran-server-manager/kytran_server_manager/templates/dashboard.html` — find the compliance summary bar or scan history section. Add "View Report" and "Download PDF" links for each scan.

In the `loadComplianceSummary()` JavaScript (or wherever scan results are displayed), add:

```javascript
// Add report links if scan exists
if (latest && latest.id) {
    var reportLink = document.createElement("a");
    reportLink.href = "/dashboard/compliance/report/" + latest.id;
    reportLink.target = "_blank";
    reportLink.textContent = "View Report";
    reportLink.style.cssText = "margin-left:8px;color:#8b5cf6;font-size:11px;text-decoration:none;";

    var pdfLink = document.createElement("a");
    pdfLink.href = "/dashboard/api/compliance/report/" + latest.id + "/pdf";
    pdfLink.textContent = "PDF";
    pdfLink.style.cssText = "margin-left:8px;color:#f59e0b;font-size:11px;text-decoration:none;";

    // Append to compliance summary bar
    var bar = document.getElementById("complianceSummaryBar");
    if (bar) { bar.appendChild(reportLink); bar.appendChild(pdfLink); }
}
```

IMPORTANT: Read the existing dashboard code first. The scan history/summary might use a different element structure. Adapt to what's actually there.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/routes/compliance_routes.py kytran_server_manager/templates/dashboard.html
git commit -m "feat(reports): add report view/download routes + dashboard links"
```

---

### Task 7: Deploy + Verify

**Files:** None (deployment + verification)

- [ ] **Step 1: Deploy ARCHIE platform**

```bash
cd /mnt/archie_brain
docker compose restart archie_platform
```

- [ ] **Step 2: Restart standalone**

```bash
sudo systemctl restart kytran-server-manager
```

- [ ] **Step 3: Verify product page**

```bash
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3000/products/system-operations
```

Expected: HTTP 200

- [ ] **Step 4: Verify standalone splash**

```bash
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:8085/
```

Expected: HTTP 200 (splash page, not 302 redirect)

- [ ] **Step 5: Trigger a compliance scan to generate evidence**

```bash
curl -s -X POST http://192.168.1.200:8085/dashboard/api/compliance/scan -H "Cookie: ..." | python3 -m json.tool
```

Or wait for the background scheduler to run one.

- [ ] **Step 6: Verify report renders**

After a scan has run:
```bash
# Get latest scan ID
# Then: http://192.168.1.200:8085/dashboard/compliance/report/{scan_id}
```

- [ ] **Step 7: Verify PDF download**

```bash
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:8085/dashboard/api/compliance/report/{scan_id}/pdf
```

Expected: HTTP 200 with `Content-Type: application/pdf`

- [ ] **Step 8: Log decision**

```python
mcp__archie__log_decision(
    title="KSM Product Page + SOC 2 Reports Complete",
    decision="Public product page at /products/system-operations with pricing. Standalone splash page. SOC 2 evidence collection during scans. HTML+PDF compliance reports with WeasyPrint. Reports gated to business+ tier.",
    project_id=193
)
```

---

## Task Summary

| Task | Phase | Description | Est. |
|------|-------|-------------|------|
| 1 | Pages | ARCHIE product page (pricing, badges, features) | 10 min |
| 2 | Pages | Standalone splash page | 5 min |
| 3 | Reports | Evidence table + collection in run_scan() | 8 min |
| 4 | Reports | HTML compliance report template | 10 min |
| 5 | Reports | Report service (PDF with WeasyPrint) | 5 min |
| 6 | Reports | Report routes + dashboard links | 5 min |
| 7 | Deploy | Deploy + verify all | 5 min |

**Total: 7 tasks, ~48 minutes**

**Phase 1** (T1-T2): Product pages — independent, can parallelize
**Phase 2** (T3-T6): Reports — sequential (T3 schema → T4 template → T5 service → T6 routes)
**Deploy** (T7): Verify everything
