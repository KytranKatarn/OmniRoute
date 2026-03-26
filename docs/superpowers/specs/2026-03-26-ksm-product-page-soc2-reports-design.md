# KSM Product Page + SOC 2 Evidence & PDF Reports

**Date**: 2026-03-26
**Project**: #193 — Kytran System Operations — Standalone Product + Compliance Engine
**Status**: Design Approved
**Scope**: Public product page (ARCHIE + standalone splash), SOC 2 evidence collection, HTML compliance reports, PDF generation
**Depends on**: Tier 2 (SSO, badges, subdomain) + Feature Gating (tier enforcement)

---

## Problem Statement

KSM needs public visibility (product page with pricing) and audit-ready compliance documentation (SOC 2 evidence collection + branded PDF reports). The product page establishes the marketing presence; the reports provide the substance that backs it up.

---

## Deliverable 1: Product Page on ARCHIE Platform

**Route**: `/products/system-operations` (public, no login required)
**File**: `platform_v2/templates/products/system_operations.html`
**Route handler**: New route in `platform_v2/app.py` or a dedicated `product_routes.py`

### Content Sections

1. **Hero**: "Kytran System Operations" — Server Management + Compliance Scanning for Linux servers. Background gradient, subtle grid pattern.

2. **Live Compliance Badges**: Pulled from standalone's badge API (`http://192.168.1.200:8085/dashboard/api/compliance/badge/overall.svg` etc.). Shows "178 automated checks, 5 frameworks" tagline.

3. **Feature Matrix / Pricing Table**:

| Feature | Free | Pro ($29/mo) | Business ($49/mo) | Enterprise ($99/mo) |
|---------|:---:|:---:|:---:|:---:|
| System dashboard | Yes | Yes | Yes | Yes |
| Docker management | Yes | Yes | Yes | Yes |
| CIS Ubuntu pack | Yes | Yes | Yes | Yes |
| Compliance packs | 1 | 3 | All 5 | All 5 + custom |
| Live badges | — | Yes | Yes | Yes |
| Auto-remediation | — | — | Yes | Yes |
| PDF reports | — | — | Yes | Yes |
| SOC 2 evidence | — | — | Yes | Yes |
| Hub SSO | — | Yes | Yes | Yes |
| Themes | 2 | 3 | 5 | 5 |
| SLA | — | — | — | 99.9% |

CTA buttons: "Start Free" / "Get Pro" / "Get Business" / "Contact Sales"
- Free/Pro/Business link to standalone signup/login
- Enterprise links to contact form or email

4. **How It Works**: 3-step visual — Install (one command) → Scan (automatic) → Report (PDF + badges)

5. **Trust Indicators**: "Built on the same compliance engine that powers A.R.C.H.I.E." + link to `/iaae` trust center and `/competitors` comparison

6. **Footer**: Links to trust center, IAAE, competitors, documentation

### Styling
- Matches existing public pages (`/iaae`, `/competitors`)
- Dark theme with purple (#8b5cf6) and gold (#f59e0b) accents
- Responsive at 480/768/1024px
- No login required — fully public

---

## Deliverable 2: Standalone Splash/Landing Page

**Route**: `/` on standalone (replaces direct login redirect)
**File**: `kytran-server-manager/kytran_server_manager/templates/splash.html`

### Content
- Branded header: "Kytran System Operations" with logo
- Tagline: "Server Management + Compliance Scanning"
- Two primary buttons: "Login" → `/login`, "Sign in with Kytran" → `/auth/sso` (only if hub configured)
- Brief feature bullets (4 items): System monitoring, Compliance scanning, Live badges, Automated remediation
- Compliance badge strip at bottom (overall badge from local API)
- "Start Free" secondary link for new account creation
- "Learn More" link to product page on ARCHIE platform

### Implementation
- New `splash.html` template (does NOT extend base.html — standalone page with own styling)
- Modify app route: `/` serves splash instead of redirecting to login
- If user is already logged in, redirect to dashboard (skip splash)
- LCARS themed but minimal — clean, fast-loading

---

## Deliverable 3: SOC 2 Evidence Collection

### Evidence Table

**New SQLite table** in standalone:

```sql
CREATE TABLE IF NOT EXISTS compliance_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL,
    rule_id TEXT NOT NULL,
    pack_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL CHECK(evidence_type IN ('command_output', 'file_content', 'config_snapshot', 'service_status', 'log_excerpt')),
    content TEXT NOT NULL,
    soc2_mapping TEXT,
    collected_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_evidence_scan ON compliance_evidence(scan_id);
CREATE INDEX IF NOT EXISTS idx_evidence_soc2 ON compliance_evidence(soc2_mapping);
```

### Collection Process
- During each compliance scan, after each rule check, capture the evidence artifact
- Evidence = the raw output that proves the check passed or failed
- Examples:
  - File content check: store the relevant file contents
  - Command output check: store the command's stdout
  - Service status check: store systemctl output
  - Config check: store the config value
- Each rule's `soc2_mapping` field (from rule pack JSON) links evidence to Trust Service Criteria

### SOC 2 Trust Service Criteria Mapping
Rules already have `soc2_mapping` fields in the JSON rule packs. Evidence is grouped by TSC:
- CC6.1 — Logical access controls
- CC6.6 — Security monitoring
- CC6.7 — System availability monitoring
- CC7.1 — Change management
- CC7.2 — System monitoring
- P1.1 — Privacy objectives
- C1.1 — Confidentiality

---

## Deliverable 4: HTML Compliance Report

**Route**: `GET /dashboard/compliance/report/<scan_id>` (login required, business+ tier)
**File**: `kytran-server-manager/kytran_server_manager/templates/compliance_report.html`
**Route handler**: New function in `compliance_routes.py`

### Report Sections

1. **Cover / Header**: Kytran System Operations logo, report title, scan date, server hostname, overall score badge

2. **Executive Summary**: Overall score, total rules checked, pass/fail/error counts, grade (A+/A/B/etc.), one-paragraph AI-generated summary (or static template)

3. **Framework Scores**: Per-pack breakdown table — pack name, rules, passed, failed, score, grade

4. **SOC 2 Trust Service Criteria**: Evidence grouped by TSC criteria — each TSC shows:
   - Criteria description
   - Related rules (pass/fail)
   - Evidence artifacts
   - Assessment: compliant / partially compliant / non-compliant

5. **Detailed Findings**: Per-rule results sorted by severity (high → medium → low):
   - Rule ID, title, severity, pack
   - Status: pass/fail/error/not_applicable
   - Evidence collected
   - Remediation recommendation (if failed)

6. **Remediation Summary**: List of all failed rules with fix commands and risk levels

### Styling
- LCARS themed for browser viewing
- Print-friendly with `@media print` overrides (white background, no nav, clean typography)
- Responsive

---

## Deliverable 5: PDF Report Generation

**Route**: `GET /dashboard/api/compliance/report/<scan_id>/pdf` (login required, business+ tier)
**File**: `kytran-server-manager/kytran_server_manager/services/report_service.py`

### Implementation
- Primary: WeasyPrint converts the HTML report template to PDF (`pip install weasyprint` — requires system deps: `libpango`, `libcairo`, `libgdk-pixbuf`)
- Fallback: If WeasyPrint not available, return HTML with "Print to PDF" instructions
- Install: `apt-get install -y libpango-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 && pip install weasyprint`
- Branded cover page: Kytran logo, report title, date, score
- Page numbers, headers/footers
- Clean print CSS (no LCARS chrome, professional look)

### Storage
- PDFs saved to `{data_dir}/reports/{scan_id}_{timestamp}.pdf`
- Linked from scan history in dashboard
- Auto-generated after each scan (background, non-blocking)

### Dashboard Integration
- Scan history table shows "Download PDF" link for each scan (business+ tier)
- Compliance summary bar shows "Latest Report" link
- Settings page shows report storage usage

---

## Deliverable 6: Report Routes + Dashboard Integration

**New/modified routes on standalone:**
- `GET /dashboard/compliance/report/<scan_id>` — HTML report (business+)
- `GET /dashboard/api/compliance/report/<scan_id>/pdf` — PDF download (business+)
- `GET /dashboard/api/compliance/reports` — list all reports with download links

**Dashboard changes:**
- Scan history shows "View Report" and "Download PDF" buttons per scan
- Compliance summary bar shows "Latest Report" link

---

## File Map

### ARCHIE Platform
| Action | File | What |
|--------|------|------|
| Create | `platform_v2/templates/products/system_operations.html` | Public product page |
| Modify | `platform_v2/app.py` | Add `/products/system-operations` route |

### Standalone
| Action | File | What |
|--------|------|------|
| Create | `templates/splash.html` | Public landing/splash page |
| Modify | `auth.py` or `routes/core_routes.py` | Serve splash at `/` |
| Modify | `db.py` | Add `compliance_evidence` table |
| Modify | `services/compliance_service.py` | Evidence collection during scans |
| Create | `services/report_service.py` | PDF generation with WeasyPrint |
| Create | `templates/compliance_report.html` | HTML report template |
| Modify | `routes/compliance_routes.py` | Report view + PDF download routes |
| Modify | `templates/dashboard.html` | Report links in scan history |
| Modify | `routes/__init__.py` | Register any new route modules |

---

## Out of Scope
- AI-generated executive summaries (S.H.I.E.L.D. integration — separate Tier 3 item)
- Custom rule pack creation (Enterprise feature — future)
- Report scheduling/email delivery
- Multi-server aggregated reports

---

## Success Criteria

1. `kytranempowerment.com/products/system-operations` loads publicly with pricing table and live badges
2. Standalone `/` shows splash page with login/SSO buttons (logged-in users skip to dashboard)
3. Evidence collected for every rule during compliance scans
4. HTML report renders with all 6 sections, print-friendly
5. PDF downloads with branded cover page
6. Reports stored on disk and linked from scan history
7. Report routes gated to business+ tier
8. Evidence grouped by SOC 2 TSC criteria in report
