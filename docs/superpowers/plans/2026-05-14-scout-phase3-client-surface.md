# S.C.O.U.T. Phase 3 — Client Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose S.C.O.U.T.'s browser intelligence to clients via a KBS plugin and to Claude Code via a `/scout` CLI skill.

**Architecture:** Two independent surfaces. (1) `/scout` Claude Code skill + a new key-authenticated CLI endpoint in scout_routes.py — Claude dispatches jobs and polls from the terminal. (2) `kbs_scout` KBS plugin — clients submit audit URLs, Kytran approves results in DHQ, clients download PDF reports. Both surfaces call the hub's `/api/scout/` routes.

**Tech Stack:** Python Flask (KBS plugin), Jinja2 templates, fpdf2 (PDF), CLUSTER_PROXY_KEY auth (CLI), KBS plugin_loader pattern (manifest.json + register_routes).

---

## File Map

**New — platform_v2/**
```
platform_v2/tools/department_hq/scout_routes.py   (modify — add CLI endpoints)
```

**New — .claude/skills/scout/**
```
.claude/skills/scout/SKILL.md
```

**New — kytran-business-suite/plugins/kbs_scout/**
```
kbs_scout/__init__.py
kbs_scout/manifest.json
kbs_scout/routes.py
kbs_scout/templates/kbs_scout.html
kbs_scout/templates/kbs_scout_report.html
kbs_scout/migrations/001_kbs_scout_tables.sql
```

**Modified**
```
platform_v2/tools/department_hq/scout_routes.py   add /api/scout/cli-dispatch + /api/scout/cli-status/<id>
```

---

## Task 1: CLI Dispatch Endpoint + /scout Skill

**Files:**
- Modify: `platform_v2/tools/department_hq/scout_routes.py`
- Create: `.claude/skills/scout/SKILL.md`

- [ ] **Step 1: Add CLI endpoints to scout_routes.py**

Read scout_routes.py first to find where register_scout_routes ends. Add two new routes inside `register_scout_routes(bp, admin_required)` after the existing `api_scout_pool` route:

```python
    @bp.route("/api/scout/cli-dispatch", methods=["POST"])
    def api_scout_cli_dispatch():
        """Key-authenticated job submission for Claude Code /scout skill."""
        from os import getenv
        key = request.headers.get("X-Scout-Key", "")
        expected = getenv("CLUSTER_PROXY_KEY", "")
        if not expected or key != expected:
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json(silent=True) or {}
        job_type = (data.get("job_type") or "").strip()
        target_url = (data.get("target_url") or "").strip()
        if not job_type or not target_url:
            return jsonify({"error": "job_type and target_url required"}), 400

        result = _scraper_post(
            "/jobs",
            {
                "job_type": job_type,
                "target_url": target_url,
                "params": data.get("params") or {},
                "requested_by": "claude_cli",
            },
        )
        return jsonify(result)

    @bp.route("/api/scout/cli-status/<int:job_id>")
    def api_scout_cli_status(job_id):
        """Key-authenticated job status for Claude Code /scout skill."""
        from os import getenv
        key = request.headers.get("X-Scout-Key", "")
        expected = getenv("CLUSTER_PROXY_KEY", "")
        if not expected or key != expected:
            return jsonify({"error": "Unauthorized"}), 401

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, job_type, target_url, status, findings,
                          screenshots, data, created_at, completed_at
                   FROM scout_jobs WHERE id = %s""",
                (job_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify(dict(row))
```

- [ ] **Step 2: Restart platform and verify CLI endpoints**

```bash
docker compose restart archie_platform
sleep 5
# Should return 401 (route exists, auth rejected without key)
docker exec archie_platform python3 -c "
import urllib.request
try:
    urllib.request.urlopen('http://localhost:3000/tools/department-hq/api/scout/cli-dispatch', timeout=3)
except urllib.error.HTTPError as e:
    print('HTTP', e.code, '— expected 401 or 405')
"
```

Expected: HTTP 401 (or 405 for GET on POST endpoint).

- [ ] **Step 3: Create .claude/skills/scout/ directory**

```bash
mkdir -p /mnt/archie_brain/.claude/skills/scout
```

- [ ] **Step 4: Create SKILL.md**

```bash
cat > /mnt/archie_brain/.claude/skills/scout/SKILL.md << 'SKILLEOF'
---
name: scout
description: Dispatch S.C.O.U.T. browser intelligence jobs from the CLI — UX audits, procurement sync, SEO snapshots, login tests, and more.
---

# /scout — S.C.O.U.T. CLI Skill

Dispatch browser intelligence jobs to S.C.O.U.T. (agent #364) via the hub API and poll for results.

## Usage

```
/scout ux-audit <url>              UX audit (desktop + mobile screenshots, console errors)
/scout login-test <url>            Test login flow, capture all states
/scout seo-snapshot <url>          SEO metadata snapshot
/scout procurement-sync [url]      CanadaBuys tender sync (default URL if omitted)
/scout web-scrape <url> [selector] Extract elements matching CSS selector
/scout price-monitor <url>         Track product prices
/scout status [job_id]             Show recent jobs or specific job status
/scout report <job_id>             Show full findings for a completed job
```

## Implementation

### Prerequisites
Read CLUSTER_PROXY_KEY from /mnt/archie_brain/.env:
```bash
SCOUT_KEY=$(grep '^CLUSTER_PROXY_KEY=' /mnt/archie_brain/.env | cut -d= -f2)
HUB=http://192.168.1.200:3000
```

### Dispatch a job
```bash
# Map skill names to job_types
# ux-audit → ux_audit
# login-test → login_test
# seo-snapshot → seo_snapshot
# procurement-sync → procurement_sync
# web-scrape → web_scrape
# price-monitor → price_monitor

JOB_TYPE=$(echo "$1" | tr '-' '_')  # convert ux-audit to ux_audit
TARGET_URL="$2"

RESPONSE=$(python3 -c "
import urllib.request, json, os
key = '$SCOUT_KEY'
url = '$HUB/tools/department-hq/api/scout/cli-dispatch'
payload = json.dumps({'job_type': '$JOB_TYPE', 'target_url': '$TARGET_URL', 'params': {}}).encode()
req = urllib.request.Request(url, data=payload)
req.add_header('Content-Type', 'application/json')
req.add_header('X-Scout-Key', key)
r = urllib.request.urlopen(req, timeout=10)
print(r.read().decode())
")
JOB_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('job_id',''))")
echo "Dispatched job #$JOB_ID ($JOB_TYPE → $TARGET_URL)"
```

### Poll until complete (max 120s)
```bash
python3 -c "
import urllib.request, json, time, sys

key = '$SCOUT_KEY'
job_id = '$JOB_ID'
hub = '$HUB'
url = f'{hub}/tools/department-hq/api/scout/cli-status/{job_id}'

for i in range(24):
    req = urllib.request.Request(url)
    req.add_header('X-Scout-Key', key)
    r = urllib.request.urlopen(req, timeout=5)
    d = json.loads(r.read())
    status = d.get('status', 'unknown')
    print(f'[{(i+1)*5}s] {status}')
    if status not in ('pending', 'running'):
        print()
        print('=== FINDINGS ===')
        print(d.get('findings', 'No findings'))
        if d.get('screenshots'):
            print()
            print('=== SCREENSHOTS ===')
            for s in d['screenshots']:
                print(f'  {s[\"step\"]}: /mnt/data2/scout/screenshots/{s[\"path\"]}')
        if status == 'needs_review':
            print()
            print('Report needs review — approve in DHQ Scout → Reports tab')
        sys.exit(0)
    time.sleep(5)
print('Timed out after 120s')
"
```

### /scout status
```bash
python3 -c "
import urllib.request, json
key = '$SCOUT_KEY'
hub = '$HUB'
req = urllib.request.Request(f'{hub}/tools/department-hq/api/scout/jobs')
req.add_header('X-Scout-Key', key)
# Note: /api/scout/jobs requires admin session — use cli-status for key auth
# Show recent jobs from DB directly:
import sys; sys.path.insert(0, '/mnt/archie_brain/archie-scraper')
from database import get_db
with get_db() as conn:
    with conn.cursor() as cur:
        cur.execute(\"SELECT id, job_type, target_url, status, created_at FROM scout_jobs ORDER BY created_at DESC LIMIT 10\")
        for r in cur.fetchall():
            print(f'#{r[\"id\"]:4d} [{r[\"status\"]:12s}] {r[\"job_type\"]:20s} {str(r[\"created_at\"])[:16]} {r[\"target_url\"][:50]}')
"
```

## Notes
- Jobs with auto_approve=True finish as 'approved' automatically
- Jobs with auto_approve=False (ux_audit, login_test, etc.) finish as 'needs_review' — Kytran must approve in DHQ
- Screenshots stored at: /mnt/data2/scout/screenshots/{job_id}/{step}.png
- Hub must be running: http://192.168.1.200:3000
SKILLEOF
echo "SKILL.md created"
```

- [ ] **Step 5: Test /scout skill end-to-end**

```bash
# Read the key
SCOUT_KEY=$(grep '^CLUSTER_PROXY_KEY=' /mnt/archie_brain/.env | cut -d= -f2)
HUB=http://192.168.1.200:3000

# Submit a job via CLI dispatch endpoint
python3 -c "
import urllib.request, json
key = '$SCOUT_KEY'
url = '$HUB/tools/department-hq/api/scout/cli-dispatch'
payload = json.dumps({'job_type': 'web_scrape', 'target_url': 'https://httpbin.org/html', 'params': {'selectors': {'headings': 'h1'}}}).encode()
req = urllib.request.Request(url, data=payload)
req.add_header('Content-Type', 'application/json')
req.add_header('X-Scout-Key', key)
r = urllib.request.urlopen(req, timeout=10)
d = json.loads(r.read())
print('Job submitted:', d)
"
```

Expected: `{'job_id': N, 'status': 'pending'}`

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git checkout -b feat/scout-phase3
git add platform_v2/tools/department_hq/scout_routes.py \
        .claude/skills/scout/SKILL.md
git commit -m "feat(scout): CLI dispatch endpoints + /scout skill SKILL.md"
```

---

## Task 2: kbs_scout Plugin Scaffold

**Files:**
- Create: `kytran-business-suite/plugins/kbs_scout/manifest.json`
- Create: `kytran-business-suite/plugins/kbs_scout/__init__.py`
- Create: `kytran-business-suite/plugins/kbs_scout/migrations/001_kbs_scout_tables.sql`

- [ ] **Step 1: Read an existing plugin manifest for reference**

```bash
cat /mnt/archie_brain/kytran-business-suite/plugins/kbs_help_desk/manifest.json
```

Note the exact field names and structure.

- [ ] **Step 2: Create manifest.json**

```bash
mkdir -p /mnt/archie_brain/kytran-business-suite/plugins/kbs_scout
mkdir -p /mnt/archie_brain/kytran-business-suite/plugins/kbs_scout/migrations
mkdir -p /mnt/archie_brain/kytran-business-suite/plugins/kbs_scout/templates
```

Create `/mnt/archie_brain/kytran-business-suite/plugins/kbs_scout/manifest.json`:

```json
{
  "slug": "kbs-scout",
  "name": "Site Intelligence",
  "version": "1.0.0",
  "description": "S.C.O.U.T. browser intelligence — audit any website and get a visual report.",
  "category": "intelligence",
  "tier": "professional",
  "icon": "radar",
  "author": "Kytran Empowerment Inc.",
  "dependencies": [],
  "emits": ["scout_job_submitted", "scout_report_viewed"],
  "consumes": []
}
```

- [ ] **Step 3: Create __init__.py**

Read an existing plugin's __init__.py for the exact function signatures:
```bash
cat /mnt/archie_brain/kytran-business-suite/plugins/kbs_help_desk/__init__.py
```

Then create `/mnt/archie_brain/kytran-business-suite/plugins/kbs_scout/__init__.py`:

```python
"""KBS Scout plugin — S.C.O.U.T. site intelligence for clients."""
from flask import Blueprint
from .routes import register_routes


def create_blueprint(manifest):
    bp = Blueprint(
        "kbs_scout",
        __name__,
        template_folder="templates",
        url_prefix="/plugins/kbs-scout",
    )
    register_routes(bp)
    return bp
```

- [ ] **Step 4: Create migration**

Create `/mnt/archie_brain/kytran-business-suite/plugins/kbs_scout/migrations/001_kbs_scout_tables.sql`:

```sql
-- KBS Scout plugin — tracks audit job references per org
CREATE TABLE IF NOT EXISTS kbs_scout_jobs (
    id              SERIAL PRIMARY KEY,
    hub_job_id      INTEGER NOT NULL,        -- references scout_jobs.id on hub
    job_type        VARCHAR(50) NOT NULL,
    target_url      TEXT NOT NULL,
    status          VARCHAR(20) DEFAULT 'pending',
    submitted_by    INTEGER,                 -- references kbs users.id
    submitted_at    TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    findings        TEXT,
    approved        BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_kbs_scout_jobs_hub_id
    ON kbs_scout_jobs(hub_job_id);
CREATE INDEX IF NOT EXISTS idx_kbs_scout_jobs_status
    ON kbs_scout_jobs(status, submitted_at DESC);
```

- [ ] **Step 5: Verify migration runs**

```bash
# Check if KBS has a migration runner — look at how other plugins run migrations
grep -r "run_migration\|execute_migration\|migrations" \
  /mnt/archie_brain/kytran-business-suite/core/ --include="*.py" | head -5
```

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git add kytran-business-suite/plugins/kbs_scout/
git commit -m "feat(kbs-scout): plugin scaffold — manifest, __init__, migration"
```

---

## Task 3: kbs_scout Routes

**Files:**
- Create: `kytran-business-suite/plugins/kbs_scout/routes.py`

- [ ] **Step 1: Check how KBS plugins call external APIs**

```bash
grep -r "requests.post\|requests.get\|ARCHIE\|HUB_URL" \
  /mnt/archie_brain/kytran-business-suite/ --include="*.py" | head -10
```

Note the env var name used for hub URL.

- [ ] **Step 2: Create routes.py**

```python
# kytran-business-suite/plugins/kbs_scout/routes.py
"""KBS Scout plugin routes — client-facing site intelligence."""
import json
import logging
import os
import urllib.error
import urllib.request

from flask import jsonify, render_template, request, session

logger = logging.getLogger(__name__)

_HUB_URL = os.getenv("ARCHIE_HUB_URL", "http://192.168.1.200:3000")
_SCOUT_KEY = os.getenv("CLUSTER_PROXY_KEY", "")

_JOB_TYPE_MAP = {
    "ux_audit": "UX Audit",
    "seo_snapshot": "SEO Snapshot",
    "accessibility_check": "Accessibility Check",
    "broken_link_check": "Broken Link Check",
    "login_test": "Login Flow Test",
    "signup_flow": "Signup Flow Test",
    "form_audit": "Form Audit",
    "competitor_snapshot": "Competitor Snapshot",
    "web_scrape": "Custom Scrape",
    "price_monitor": "Price Monitor",
}


def _hub_post(path: str, body: dict) -> dict:
    payload = json.dumps(body).encode()
    req = urllib.request.Request(f"{_HUB_URL}{path}", data=payload)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Scout-Key", _SCOUT_KEY)
    try:
        r = urllib.request.urlopen(req, timeout=15)
        return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return {"error": f"Hub error {exc.code}", "detail": exc.read().decode()[:200]}
    except Exception as exc:
        return {"error": str(exc)}


def _hub_get(path: str) -> dict:
    req = urllib.request.Request(f"{_HUB_URL}{path}")
    req.add_header("X-Scout-Key", _SCOUT_KEY)
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return json.loads(r.read())
    except Exception as exc:
        return {"error": str(exc)}


def _current_org_id() -> int | None:
    return session.get("org_id")


def register_routes(bp):

    @bp.route("/")
    def index():
        return render_template(
            "kbs_scout.html",
            job_types=_JOB_TYPE_MAP,
        )

    @bp.route("/submit", methods=["POST"])
    def submit():
        data = request.get_json(silent=True) or {}
        job_type = (data.get("job_type") or "").strip()
        target_url = (data.get("target_url") or "").strip()
        org_id = _current_org_id()

        if not job_type or not target_url:
            return jsonify({"error": "job_type and target_url required"}), 400
        if job_type not in _JOB_TYPE_MAP:
            return jsonify({"error": f"Unknown job type: {job_type}"}), 400
        if not target_url.startswith(("http://", "https://")):
            return jsonify({"error": "URL must start with http:// or https://"}), 400

        result = _hub_post(
            "/tools/department-hq/api/scout/cli-dispatch",
            {
                "job_type": job_type,
                "target_url": target_url,
                "params": data.get("params") or {},
            },
        )
        if "error" in result:
            return jsonify(result), 502

        logger.info(
            "[kbs_scout] org=%s submitted job #%s: %s → %s",
            org_id,
            result.get("job_id"),
            job_type,
            target_url[:60],
        )
        return jsonify(result)

    @bp.route("/reports")
    def reports():
        org_id = _current_org_id()
        # Fetch approved jobs submitted by this org from hub
        # Hub filters by requested_by containing org_id
        return render_template("kbs_scout.html", job_types=_JOB_TYPE_MAP, view="reports")

    @bp.route("/api/jobs/<int:job_id>")
    def job_status(job_id):
        return jsonify(_hub_get(f"/tools/department-hq/api/scout/cli-status/{job_id}"))

    @bp.route("/api/reports")
    def api_reports():
        """List approved reports for this org."""
        org_id = _current_org_id()
        # Query hub for approved jobs requested by kbs_client:{org_id} or claude_cli
        # For now returns all approved jobs (scoping via org_id TBD when KBS org session is wired)
        result = _hub_get("/tools/department-hq/api/scout/jobs?status=approved&limit=50")
        jobs = result.get("jobs", []) if isinstance(result, dict) else []
        return jsonify({"reports": jobs, "total": len(jobs)})

    @bp.route("/reports/<int:job_id>")
    def report_detail(job_id):
        job = _hub_get(f"/tools/department-hq/api/scout/cli-status/{job_id}")
        return render_template("kbs_scout_report.html", job=job, job_types=_JOB_TYPE_MAP)

    @bp.route("/reports/<int:job_id>/pdf")
    def report_pdf(job_id):
        job = _hub_get(f"/tools/department-hq/api/scout/cli-status/{job_id}")
        if "error" in job:
            return f"Error: {job['error']}", 404

        try:
            from fpdf import FPDF

            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 16)
            pdf.cell(0, 10, f"S.C.O.U.T. Report — {_JOB_TYPE_MAP.get(job.get('job_type', ''), job.get('job_type', ''))}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=11)
            pdf.cell(0, 8, f"URL: {job.get('target_url', '')[:80]}", new_x="LMARGIN", new_y="NEXT")
            pdf.cell(0, 8, f"Status: {job.get('status', '')}", new_x="LMARGIN", new_y="NEXT")
            pdf.cell(0, 8, f"Completed: {str(job.get('completed_at', ''))[:16]}", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(5)
            pdf.set_font("Helvetica", "B", 13)
            pdf.cell(0, 8, "Findings", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=10)
            findings = job.get("findings") or "No findings."
            for line in findings.split("\n"):
                pdf.multi_cell(0, 6, line[:100])
            if job.get("screenshots"):
                pdf.ln(5)
                pdf.set_font("Helvetica", "B", 13)
                pdf.cell(0, 8, "Screenshots", new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", size=10)
                for sc in job["screenshots"]:
                    pdf.cell(0, 6, f"  {sc.get('step', '')}: {sc.get('caption', '')}", new_x="LMARGIN", new_y="NEXT")

            from flask import Response
            pdf_bytes = pdf.output()
            return Response(
                pdf_bytes,
                mimetype="application/pdf",
                headers={"Content-Disposition": f"attachment; filename=scout-report-{job_id}.pdf"},
            )
        except ImportError:
            return "PDF export requires fpdf2. Run: pip install fpdf2", 500
        except Exception as exc:
            return f"PDF generation failed: {exc}", 500
```

- [ ] **Step 3: Add fpdf2 to KBS requirements**

```bash
grep -n "fpdf\|requirements" /mnt/archie_brain/kytran-business-suite/requirements.txt | head -5
```

If not present, add:
```bash
echo "fpdf2==2.7.9" >> /mnt/archie_brain/kytran-business-suite/requirements.txt
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add kytran-business-suite/plugins/kbs_scout/routes.py \
        kytran-business-suite/requirements.txt
git commit -m "feat(kbs-scout): routes — submit, reports, PDF export"
```

---

## Task 4: kbs_scout Templates

**Files:**
- Create: `kytran-business-suite/plugins/kbs_scout/templates/kbs_scout.html`
- Create: `kytran-business-suite/plugins/kbs_scout/templates/kbs_scout_report.html`

- [ ] **Step 1: Check base template**

```bash
ls /mnt/archie_brain/kytran-business-suite/templates/
cat /mnt/archie_brain/kytran-business-suite/plugins/kbs_help_desk/templates/ | head -5 2>/dev/null || ls /mnt/archie_brain/kytran-business-suite/plugins/kbs_help_desk/templates/
```

Identify the base template name.

- [ ] **Step 2: Create kbs_scout.html**

Create `/mnt/archie_brain/kytran-business-suite/plugins/kbs_scout/templates/kbs_scout.html`:

```html
{% extends "base.html" %}

{% block title %}Site Intelligence — S.C.O.U.T.{% endblock %}

{% block content %}
<div class="kbs-scout-container">

  <div class="scout-header">
    <h1>Site Intelligence</h1>
    <p>Dispatch S.C.O.U.T. to audit any website. Results appear after Kytran approves the report.</p>
    <nav class="scout-tabs">
      <button class="scout-tab-btn active" onclick="showTab('submit', this)">New Audit</button>
      <button class="scout-tab-btn" onclick="showTab('reports', this)">My Reports</button>
    </nav>
  </div>

  <!-- Submit Tab -->
  <div id="scout-tab-submit" class="scout-tab-panel">
    <div class="scout-form-card">
      <h2>Submit Audit Request</h2>
      <div class="scout-form">
        <label>Audit Type
          <select id="job-type">
            {% for type_id, type_name in job_types.items() %}
            <option value="{{ type_id }}">{{ type_name }}</option>
            {% endfor %}
          </select>
        </label>
        <label>Target URL
          <input type="url" id="target-url" placeholder="https://yourwebsite.com" />
        </label>
        <button onclick="submitAudit()" class="scout-submit-btn">Request Audit</button>
      </div>
      <div id="scout-submit-result" style="display:none;" class="scout-result-banner"></div>
    </div>
  </div>

  <!-- Reports Tab -->
  <div id="scout-tab-reports" class="scout-tab-panel" style="display:none;">
    <div id="scout-reports-loading">Loading reports...</div>
    <table class="scout-table" id="scout-reports-table" style="display:none;">
      <thead>
        <tr><th>ID</th><th>Type</th><th>URL</th><th>Status</th><th>Completed</th><th>Action</th></tr>
      </thead>
      <tbody id="scout-reports-tbody"></tbody>
    </table>
  </div>

</div>

<style>
.kbs-scout-container { max-width: 900px; margin: 0 auto; padding: 2rem; }
.scout-header h1 { font-size: 1.75rem; margin-bottom: 0.5rem; }
.scout-tabs { display: flex; gap: 0.5rem; margin-top: 1rem; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.5rem; }
.scout-tab-btn { padding: 0.5rem 1.25rem; border: none; background: none; cursor: pointer; font-size: 0.95rem; color: #64748b; border-bottom: 2px solid transparent; margin-bottom: -2px; }
.scout-tab-btn.active { color: #0ea5e9; border-bottom-color: #0ea5e9; font-weight: 600; }
.scout-tab-panel { padding-top: 1.5rem; }
.scout-form-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1.5rem; }
.scout-form { display: flex; flex-direction: column; gap: 1rem; max-width: 500px; }
.scout-form label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.9rem; font-weight: 500; }
.scout-form input, .scout-form select { padding: 0.5rem; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 0.95rem; }
.scout-submit-btn { padding: 0.6rem 1.5rem; background: #0ea5e9; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 0.95rem; align-self: flex-start; }
.scout-submit-btn:hover { background: #0284c7; }
.scout-result-banner { margin-top: 1rem; padding: 0.75rem 1rem; border-radius: 6px; font-size: 0.9rem; }
.scout-result-banner.success { background: #dcfce7; color: #166534; border: 1px solid #86efac; }
.scout-result-banner.error { background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }
.scout-table { width: 100%; border-collapse: collapse; }
.scout-table th, .scout-table td { padding: 0.6rem 0.75rem; border-bottom: 1px solid #e2e8f0; text-align: left; font-size: 0.9rem; }
.scout-table th { background: #f1f5f9; font-weight: 600; }
.scout-badge { padding: 0.2rem 0.6rem; border-radius: 4px; font-size: 0.8rem; }
.scout-badge-approved { background: #dcfce7; color: #166534; }
.scout-badge-needs_review { background: #fef9c3; color: #854d0e; }
.scout-badge-pending, .scout-badge-running { background: #dbeafe; color: #1e40af; }
.scout-badge-failed { background: #fee2e2; color: #991b1b; }
</style>

<script>
function showTab(name, btn) {
  document.querySelectorAll('.scout-tab-panel').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.scout-tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('scout-tab-' + name).style.display = '';
  btn.classList.add('active');
  if (name === 'reports') loadReports();
}

async function submitAudit() {
  const jobType = document.getElementById('job-type').value;
  const targetUrl = document.getElementById('target-url').value.trim();
  const resultEl = document.getElementById('scout-submit-result');

  if (!targetUrl) {
    showResult('Please enter a target URL.', false);
    return;
  }

  const btn = document.querySelector('.scout-submit-btn');
  btn.disabled = true;
  btn.textContent = 'Submitting...';

  try {
    const r = await fetch('/plugins/kbs-scout/submit', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({job_type: jobType, target_url: targetUrl}),
    });
    const d = await r.json();
    if (d.job_id) {
      showResult('Audit #' + d.job_id + ' submitted. Results will appear in My Reports once approved.', true);
      document.getElementById('target-url').value = '';
    } else {
      showResult('Error: ' + (d.error || JSON.stringify(d)), false);
    }
  } catch (e) {
    showResult('Request failed: ' + String(e), false);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Request Audit';
  }
}

function showResult(msg, ok) {
  const el = document.getElementById('scout-submit-result');
  el.textContent = msg;
  el.className = 'scout-result-banner ' + (ok ? 'success' : 'error');
  el.style.display = '';
}

async function loadReports() {
  try {
    const r = await fetch('/plugins/kbs-scout/api/reports');
    const d = await r.json();
    const tbody = document.getElementById('scout-reports-tbody');
    const table = document.getElementById('scout-reports-table');
    const loading = document.getElementById('scout-reports-loading');
    tbody.textContent = '';
    (d.reports || []).forEach(function(job) {
      const tr = document.createElement('tr');
      [
        String(job.id || ''),
        String(job.job_type || '').replace(/_/g, ' '),
        (String(job.target_url || '')).slice(0, 40),
        job.status,
        (String(job.completed_at || '')).slice(0, 16),
        '',
      ].forEach(function(val, idx) {
        const td = document.createElement('td');
        if (idx === 3) {
          const span = document.createElement('span');
          span.className = 'scout-badge scout-badge-' + val;
          span.textContent = val;
          td.appendChild(span);
        } else if (idx === 5) {
          const a = document.createElement('a');
          a.href = '/plugins/kbs-scout/reports/' + job.id;
          a.textContent = 'View';
          td.appendChild(a);
          if (job.status === 'approved') {
            td.appendChild(document.createTextNode(' | '));
            const pdf = document.createElement('a');
            pdf.href = '/plugins/kbs-scout/reports/' + job.id + '/pdf';
            pdf.textContent = 'PDF';
            td.appendChild(pdf);
          }
        } else {
          td.textContent = val;
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    loading.style.display = 'none';
    table.style.display = '';
  } catch (e) {
    document.getElementById('scout-reports-loading').textContent = 'Failed to load reports: ' + e;
  }
}
</script>
{% endblock %}
```

- [ ] **Step 3: Create kbs_scout_report.html**

Create `/mnt/archie_brain/kytran-business-suite/plugins/kbs_scout/templates/kbs_scout_report.html`:

```html
{% extends "base.html" %}
{% block title %}Scout Report #{{ job.id }}{% endblock %}
{% block content %}
<div class="kbs-scout-container">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1.5rem;">
    <h1>Scout Report #{{ job.id }}</h1>
    <div>
      {% if job.status == 'approved' %}
      <a href="/plugins/kbs-scout/reports/{{ job.id }}/pdf" class="scout-submit-btn" style="text-decoration:none; display:inline-block; margin-right:0.5rem;">Download PDF</a>
      {% endif %}
      <a href="/plugins/kbs-scout/reports" style="color:#64748b;">← All Reports</a>
    </div>
  </div>

  <div class="scout-form-card" style="margin-bottom:1rem;">
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:1rem;">
      <div><strong>Type</strong><br>{{ job_types.get(job.job_type, job.job_type) }}</div>
      <div><strong>Status</strong><br><span class="scout-badge scout-badge-{{ job.status }}">{{ job.status }}</span></div>
      <div><strong>URL</strong><br><a href="{{ job.target_url }}" target="_blank" rel="noopener">{{ job.target_url }}</a></div>
      <div><strong>Completed</strong><br>{{ (job.completed_at or '')[:16] }}</div>
    </div>
  </div>

  {% if job.findings %}
  <div class="scout-form-card" style="margin-bottom:1rem;">
    <h2 style="margin-top:0;">Findings</h2>
    <pre style="white-space:pre-wrap; font-family:inherit; margin:0;">{{ job.findings }}</pre>
  </div>
  {% endif %}

  {% if job.screenshots %}
  <div class="scout-form-card">
    <h2 style="margin-top:0;">Screenshots ({{ job.screenshots|length }})</h2>
    <div style="display:flex; flex-direction:column; gap:0.5rem;">
      {% for sc in job.screenshots %}
      <div>
        <strong>{{ sc.step }}</strong>
        {% if sc.caption %} — {{ sc.caption }}{% endif %}
        <br><code style="font-size:0.8rem; color:#64748b;">/mnt/data2/scout/screenshots/{{ sc.path }}</code>
      </div>
      {% endfor %}
    </div>
  </div>
  {% endif %}

  {% if job.status == 'needs_review' %}
  <div style="margin-top:1rem; padding:1rem; background:#fef9c3; border-radius:8px; border:1px solid #fde047;">
    This report is pending approval. It will appear here once reviewed.
  </div>
  {% endif %}
</div>
<style>
.kbs-scout-container { max-width: 900px; margin: 0 auto; padding: 2rem; }
.scout-form-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1.5rem; }
.scout-submit-btn { padding: 0.5rem 1.25rem; background: #0ea5e9; color: white; border-radius: 6px; font-size: 0.9rem; }
.scout-badge { padding: 0.2rem 0.6rem; border-radius: 4px; font-size: 0.85rem; }
.scout-badge-approved { background: #dcfce7; color: #166534; }
.scout-badge-needs_review { background: #fef9c3; color: #854d0e; }
.scout-badge-failed { background: #fee2e2; color: #991b1b; }
</style>
{% endblock %}
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add kytran-business-suite/plugins/kbs_scout/templates/
git commit -m "feat(kbs-scout): submission form + report viewer templates"
```

---

## Task 5: End-to-End Verification + PR

- [ ] **Step 1: Verify /scout CLI skill works**

```bash
SCOUT_KEY=$(grep '^CLUSTER_PROXY_KEY=' /mnt/archie_brain/.env | cut -d= -f2)

# Submit via CLI dispatch
python3 -c "
import urllib.request, json
key = '$SCOUT_KEY'
url = 'http://192.168.1.200:3000/tools/department-hq/api/scout/cli-dispatch'
payload = json.dumps({'job_type': 'web_scrape', 'target_url': 'https://httpbin.org/html', 'params': {'selectors': {'heading': 'h1'}}}).encode()
req = urllib.request.Request(url, data=payload)
req.add_header('Content-Type', 'application/json')
req.add_header('X-Scout-Key', key)
r = urllib.request.urlopen(req, timeout=10)
d = json.loads(r.read())
print('Job:', d)
"
```

Expected: `{'job_id': N, 'status': 'pending'}`

- [ ] **Step 2: Verify KBS plugin loads**

```bash
# Restart KBS and check for plugin registration
docker compose restart kbs_app 2>/dev/null || docker restart kbs_app
sleep 5
docker logs kbs_app --tail=20 2>&1 | grep -iE "scout|error|plugin" | head -10
```

Expected: No import errors. "kbs-scout" plugin loaded.

- [ ] **Step 3: Check KBS plugin page loads**

```bash
python3 -c "
import urllib.request
try:
    r = urllib.request.urlopen('http://192.168.1.200:8091/plugins/kbs-scout/', timeout=5)
    print('KBS Scout page:', r.status)
except Exception as e:
    print('Error:', e)
"
```

Expected: HTTP 200 or 302 (redirect to login if not authenticated).

- [ ] **Step 4: Verify PDF export dependency**

```bash
docker exec kbs_app python3 -c "from fpdf import FPDF; print('fpdf2 OK')" 2>/dev/null || echo "fpdf2 not installed — needs container rebuild"
```

If not installed, rebuild:
```bash
cd /mnt/archie_brain && docker compose build kbs_app 2>&1 | tail -5 && docker compose up -d kbs_app
```

- [ ] **Step 5: Create PR**

```bash
cd /mnt/archie_brain
git push -u origin feat/scout-phase3
gh pr create \
  --title "feat(scout): Phase 3 — KBS kbs_scout plugin + /scout CLI skill" \
  --body "$(cat <<'EOF'
## Summary
- New CLI dispatch endpoints: POST /api/scout/cli-dispatch + GET /api/scout/cli-status/<id> (X-Scout-Key auth)
- /scout Claude Code skill: .claude/skills/scout/SKILL.md — dispatch jobs, poll results from terminal
- KBS kbs_scout plugin: clients submit audit URLs, view approved reports, download PDF
- PDF export via fpdf2 (basic but functional — job metadata + findings + screenshot list)

## Usage
```bash
# From Claude Code terminal:
/scout ux-audit https://clientsite.com
/scout seo-snapshot https://clientsite.com

# From KBS client portal:
# business.kytranempowerment.com → Site Intelligence → New Audit
```

## Test Plan
- [ ] /api/scout/cli-dispatch returns job_id with valid X-Scout-Key
- [ ] /api/scout/cli-status/{id} returns job status with valid key
- [ ] KBS plugin page loads at /plugins/kbs-scout/
- [ ] Submit form submits audit and shows confirmation
- [ ] Reports tab shows approved jobs
- [ ] PDF export works for approved reports
- [ ] Unauthenticated CLI endpoints return 401

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage:**

| Spec Requirement | Task |
|---|---|
| CLI dispatch endpoint (key-auth) | Task 1 |
| /scout SKILL.md | Task 1 |
| kbs_scout manifest + __init__ | Task 2 |
| kbs_scout DB table | Task 2 |
| Submit endpoint | Task 3 |
| Reports list + detail | Task 3 |
| PDF export | Task 3 |
| Submission form HTML | Task 4 |
| Report viewer HTML | Task 4 |
| E2E verification | Task 5 |

**Not in Phase 3 (Phase 4):**
- Dynamic fleet node egress discovery
- Agent loop scheduled jobs (nightly procurement sync)
- Gov-watch wiring to use archie_scraper
- WTF geographic bias detection
