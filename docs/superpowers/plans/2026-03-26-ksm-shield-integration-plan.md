# S.H.I.E.L.D. AI Compliance Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After each compliance report from a standalone product, S.H.I.E.L.D. generates AI-powered executive summaries, remediation plans, and trend analysis via Bridge dispatch. Standalone reports display the AI sections when available.

**Architecture:** Hub receives compliance report → triggers S.H.I.E.L.D. in background thread → Bridge dispatches to LLM → stores analysis in `compliance_ai_analysis` table → standalone fetches analysis when rendering reports.

**Tech Stack:** Python/Flask, Bridge Dispatcher (`dispatch()` from `ai_bridge.bridge_dispatcher`), PostgreSQL (ARCHIE), SQLite (standalone), S.H.I.E.L.D. agent #150

---

## File Map

### ARCHIE Platform
| Action | File | What |
|--------|------|------|
| Create | `database/migrations/203_compliance_ai_analysis.sql` | AI analysis table |
| Modify | `platform_v2/api_standalone.py` | Trigger S.H.I.E.L.D. + analysis fetch endpoint |

### Standalone
| Action | File | What |
|--------|------|------|
| Modify | `kytran-server-manager/.../services/hub_client.py` | Add fetch_ai_analysis() |
| Modify | `kytran-server-manager/.../services/report_service.py` | Include AI data in reports |
| Modify | `kytran-server-manager/.../templates/compliance_report.html` | AI sections with fallback |

---

### Task 1: AI Analysis Table Migration

**Files:**
- Create: `database/migrations/203_compliance_ai_analysis.sql`

- [ ] **Step 1: Create migration**

```sql
-- S.H.I.E.L.D. AI compliance analysis results
-- Run: docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/203_compliance_ai_analysis.sql

CREATE TABLE IF NOT EXISTS compliance_ai_analysis (
    id SERIAL PRIMARY KEY,
    scan_target VARCHAR(256) NOT NULL,
    scan_id INTEGER,
    executive_summary TEXT,
    remediation_plan TEXT,
    trend_analysis TEXT,
    model_used VARCHAR(64),
    tokens_used INTEGER,
    generated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_analysis_target ON compliance_ai_analysis(scan_target);
CREATE INDEX IF NOT EXISTS idx_ai_analysis_scan ON compliance_ai_analysis(scan_id);
```

- [ ] **Step 2: Run migration**

```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/203_compliance_ai_analysis.sql
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add database/migrations/203_compliance_ai_analysis.sql
git commit -m "feat(shield): add compliance_ai_analysis table for S.H.I.E.L.D. results"
```

---

### Task 2: S.H.I.E.L.D. Trigger + Analysis Endpoint on Hub

**Files:**
- Modify: `platform_v2/api_standalone.py`

- [ ] **Step 1: Read current api_standalone.py**

Read `/mnt/archie_brain/platform_v2/api_standalone.py` — understand the `receive_compliance_report()` function and where to add the S.H.I.E.L.D. trigger.

- [ ] **Step 2: Add S.H.I.E.L.D. background analysis function**

Add this function to `api_standalone.py`:

```python
def _run_shield_analysis(app, scan_target, scan_data, db_scan_id):
    """Background: dispatch S.H.I.E.L.D. to analyze compliance scan results."""
    import time
    with app.app_context():
        try:
            from ai_bridge.bridge_dispatcher import dispatch
            from database import get_db_cursor

            # Build context for S.H.I.E.L.D.
            score = scan_data.get("overall_score", scan_data.get("score", "N/A"))
            pack_scores = scan_data.get("pack_scores", {})
            total = scan_data.get("total_rules", 0)
            passed = scan_data.get("passed", 0)
            failed = scan_data.get("failed", 0)

            # Get previous scan for trend analysis
            prev_score = None
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT score, started_at FROM compliance_scans
                       WHERE scan_target = %s AND id != %s
                       ORDER BY started_at DESC LIMIT 1""",
                    (scan_target, db_scan_id),
                )
                prev = cur.fetchone()
                if prev:
                    prev_score = prev.get("score")

            # Build failed rules summary
            failed_summary = scan_data.get("findings_summary", [])
            if isinstance(failed_summary, list):
                failed_text = "\n".join(
                    f"- [{f.get('severity', 'medium').upper()}] {f.get('rule_id', '?')}: {f.get('title', f.get('description', 'No description'))}"
                    for f in failed_summary[:20]
                )
            else:
                failed_text = str(failed_summary)[:2000]

            # Pack scores text
            pack_text = "\n".join(
                f"- {pack}: {s}%" if isinstance(s, (int, float)) else f"- {pack}: {s}"
                for pack, s in pack_scores.items()
            )

            score_delta = ""
            if prev_score is not None:
                delta = float(score) - float(prev_score) if score != "N/A" else 0
                score_delta = f"Previous Score: {prev_score}% (change: {'+' if delta >= 0 else ''}{delta:.1f}%)"
            else:
                score_delta = "No previous scan available for comparison."

            prompt = f"""Analyze compliance scan results for {scan_target}.

SCAN RESULTS:
- Overall Score: {score}%
- Total Rules: {total} (Passed: {passed}, Failed: {failed})
- {score_delta}

FRAMEWORK SCORES:
{pack_text or 'No per-pack breakdown available.'}

FAILED RULES (top 20):
{failed_text or 'No failures — all rules passed.'}

Generate three clearly labeled sections:

## EXECUTIVE SUMMARY
Write 2-3 paragraphs summarizing the compliance posture. Highlight critical findings, overall assessment, and comparison to previous scan if available.

## REMEDIATION PLAN
Prioritized list of fixes. For each item:
- Priority number (1 = most urgent)
- Rule ID and what it checks
- Why it matters (business/security impact)
- Fix command or steps
- Estimated effort (minutes)

## TREND ANALYSIS
Analyze how compliance changed:
- Score trajectory (improving/declining/stable)
- Newly failed rules vs previously passing
- Frameworks trending up or down
- Recommendations for maintaining/improving score"""

            system_prompt = (
                "You are S.H.I.E.L.D. (Security Hardening, Inspection, Enforcement & Liability Detection), "
                "a compliance analysis agent. You provide clear, actionable security assessments. "
                "Be specific with rule IDs, fix commands, and impact statements. "
                "Use markdown formatting for readability."
            )

            result = dispatch(
                capability="compliance_analysis",
                prompt=prompt,
                module_id="security-network",
                system_prompt=system_prompt,
            )

            response_text = result.get("response", "") if isinstance(result, dict) else str(result)
            model = result.get("model", "unknown") if isinstance(result, dict) else "unknown"
            tokens = result.get("tokens_used", 0) if isinstance(result, dict) else 0

            # Parse sections from response
            executive = ""
            remediation = ""
            trend = ""

            sections = response_text.split("## ")
            for section in sections:
                lower = section.lower()
                if lower.startswith("executive summary"):
                    executive = section.split("\n", 1)[1].strip() if "\n" in section else ""
                elif lower.startswith("remediation plan"):
                    remediation = section.split("\n", 1)[1].strip() if "\n" in section else ""
                elif lower.startswith("trend analysis"):
                    trend = section.split("\n", 1)[1].strip() if "\n" in section else ""

            # Store analysis
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO compliance_ai_analysis
                       (scan_target, scan_id, executive_summary, remediation_plan, trend_analysis, model_used, tokens_used)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (scan_target, db_scan_id, executive, remediation, trend, model, tokens),
                )

            logger.info(f"[S.H.I.E.L.D.] Analysis complete for {scan_target} scan #{db_scan_id} ({len(response_text)} chars)")

        except Exception as e:
            logger.error(f"[S.H.I.E.L.D.] Analysis failed for {scan_target}: {e}")
```

- [ ] **Step 3: Trigger S.H.I.E.L.D. after report received**

In the `receive_compliance_report()` function, after the successful INSERT and before the return, add:

```python
            # Trigger S.H.I.E.L.D. AI analysis in background
            import threading
            from flask import current_app
            thread = threading.Thread(
                target=_run_shield_analysis,
                args=(current_app._get_current_object(), product_name, data, scan_id),
                daemon=True,
            )
            thread.start()
```

Add `import logging` at top if not already present, and `logger = logging.getLogger(__name__)`.

- [ ] **Step 4: Add analysis fetch endpoint**

Add a new route in the same file:

```python
@standalone_bp.route("/api/standalone/compliance-analysis")
def get_compliance_analysis():
    """Fetch latest AI analysis for a standalone product."""
    client_id = _validate_client_auth()
    if not client_id:
        return jsonify({"error": "unauthorized"}), 401

    scan_target = request.args.get("scan_target", "")
    if not scan_target:
        return jsonify({"error": "scan_target parameter required"}), 400

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT executive_summary, remediation_plan, trend_analysis, model_used, generated_at
                   FROM compliance_ai_analysis
                   WHERE scan_target = %s
                   ORDER BY generated_at DESC LIMIT 1""",
                (scan_target,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"success": True, "analysis": None})

            return jsonify({
                "success": True,
                "analysis": {
                    "executive_summary": row["executive_summary"],
                    "remediation_plan": row["remediation_plan"],
                    "trend_analysis": row["trend_analysis"],
                    "model_used": row["model_used"],
                    "generated_at": row["generated_at"].isoformat() if row["generated_at"] else None,
                },
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

Add `from flask import request` to imports if not already there.

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/api_standalone.py
git commit -m "feat(shield): trigger S.H.I.E.L.D. analysis after compliance report + fetch endpoint"
```

---

### Task 3: Standalone Hub Client — Fetch AI Analysis

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/services/hub_client.py`

- [ ] **Step 1: Read current hub_client.py**

Read `/mnt/archie_brain/kytran-server-manager/kytran_server_manager/services/hub_client.py` to understand existing functions and auth pattern.

- [ ] **Step 2: Add fetch_ai_analysis function**

Add to `hub_client.py`:

```python
def fetch_ai_analysis():
    """Fetch latest AI compliance analysis from ARCHIE hub."""
    cfg = _get_hub_config()
    if not cfg["hub_url"] or not cfg["client_secret"]:
        return None

    url = f"{cfg['hub_url']}/api/standalone/compliance-analysis"
    params = {"scan_target": "Kytran System Operations"}

    try:
        resp = requests.get(url, params=params, headers=_hub_auth_header(), timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("analysis")
        else:
            logger.warning(f"AI analysis fetch returned {resp.status_code}")
            return None
    except Exception as e:
        logger.warning(f"Failed to fetch AI analysis: {e}")
        return None
```

IMPORTANT: Read the file first. Match the existing import pattern, auth header function name, and config access pattern. The function names might be `_get_hub_config()` and `_hub_auth_header()` or something different.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/services/hub_client.py
git commit -m "feat(shield): add fetch_ai_analysis() to hub client"
```

---

### Task 4: Report Service — Include AI Analysis

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/services/report_service.py`

- [ ] **Step 1: Read current report_service.py**

Read `/mnt/archie_brain/kytran-server-manager/kytran_server_manager/services/report_service.py` — find `get_scan_report_data()` to add AI analysis to the data dict.

- [ ] **Step 2: Add AI analysis to report data**

In `get_scan_report_data()`, after gathering all other data and before the return, add:

```python
        # Fetch AI analysis from hub (if connected)
        ai_analysis = None
        try:
            from .hub_client import is_hub_configured, fetch_ai_analysis
            if is_hub_configured():
                ai_analysis = fetch_ai_analysis()
        except Exception:
            pass

        data["ai_analysis"] = ai_analysis
```

Where `data` is the dict being returned. Read the code to find the exact variable name and insertion point.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/services/report_service.py
git commit -m "feat(shield): include AI analysis in compliance report data"
```

---

### Task 5: Report Template — AI Sections

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/templates/compliance_report.html`

- [ ] **Step 1: Read current report template**

Read `/mnt/archie_brain/kytran-server-manager/kytran_server_manager/templates/compliance_report.html` — find the Executive Summary section and Remediation Summary section. These will be enhanced with AI content.

- [ ] **Step 2: Add conditional AI executive summary**

Find the existing Executive Summary section. Wrap it in a conditional that shows AI content when available, static content as fallback:

```html
{% if ai_analysis and ai_analysis.executive_summary %}
<section class="report-section" id="executive-summary">
    <h2>Executive Summary</h2>
    <div class="ai-badge" style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;background:rgba(139,92,246,0.1);border:1px solid rgba(139,92,246,0.3);border-radius:6px;margin-bottom:12px;font-size:11px;color:#8b5cf6;">
        <span style="width:6px;height:6px;border-radius:50%;background:#8b5cf6;display:inline-block;"></span>
        AI-Generated by S.H.I.E.L.D. &mdash; {{ ai_analysis.model_used|default('AI') }}
    </div>
    <div class="ai-content" style="line-height:1.7;">{{ ai_analysis.executive_summary|safe }}</div>
</section>
{% else %}
<!-- Existing static executive summary section stays here unchanged -->
{% endif %}
```

- [ ] **Step 3: Add AI remediation plan section**

After the existing remediation summary section, add an enhanced AI version:

```html
{% if ai_analysis and ai_analysis.remediation_plan %}
<section class="report-section" id="ai-remediation">
    <h2>Prioritized Remediation Plan</h2>
    <div class="ai-badge" style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;background:rgba(139,92,246,0.1);border:1px solid rgba(139,92,246,0.3);border-radius:6px;margin-bottom:12px;font-size:11px;color:#8b5cf6;">
        <span style="width:6px;height:6px;border-radius:50%;background:#8b5cf6;display:inline-block;"></span>
        AI-Generated by S.H.I.E.L.D.
    </div>
    <div class="ai-content" style="line-height:1.7;">{{ ai_analysis.remediation_plan|safe }}</div>
</section>
{% endif %}
```

- [ ] **Step 4: Add AI trend analysis section**

After the remediation section:

```html
{% if ai_analysis and ai_analysis.trend_analysis %}
<section class="report-section" id="ai-trends">
    <h2>Trend Analysis</h2>
    <div class="ai-badge" style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;background:rgba(139,92,246,0.1);border:1px solid rgba(139,92,246,0.3);border-radius:6px;margin-bottom:12px;font-size:11px;color:#8b5cf6;">
        <span style="width:6px;height:6px;border-radius:50%;background:#8b5cf6;display:inline-block;"></span>
        AI-Generated by S.H.I.E.L.D.
    </div>
    <div class="ai-content" style="line-height:1.7;">{{ ai_analysis.trend_analysis|safe }}</div>
</section>
{% endif %}
```

IMPORTANT: Read the existing template first. The section structure, class names, and styling patterns must match. Don't break existing static sections — the AI sections are ADDITIONS that conditionally replace or augment the static versions.

- [ ] **Step 5: Add print CSS for AI sections**

In the `@media print` block, add:

```css
.ai-badge { border: 1px solid #8b5cf6 !important; background: #f3f0ff !important; color: #5b21b6 !important; }
.ai-content { color: #1e293b !important; }
#ai-remediation, #ai-trends { page-break-before: always; }
```

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/templates/compliance_report.html
git commit -m "feat(shield): add AI-powered executive summary, remediation, and trend sections to report"
```

---

### Task 6: Deploy + Verify

**Files:** None (deployment + testing)

- [ ] **Step 1: Deploy ARCHIE**

```bash
cd /mnt/archie_brain
docker compose restart archie_platform
```

- [ ] **Step 2: Restart standalone**

```bash
sudo systemctl restart kytran-server-manager
```

- [ ] **Step 3: Verify AI analysis table exists**

```bash
docker exec archie_database psql -U archie -d archie -c "\d compliance_ai_analysis"
```

- [ ] **Step 4: Verify analysis fetch endpoint**

```bash
# Should return null analysis (none generated yet)
curl -s -H "Authorization: Bearer $(echo -n 'kytran-sysops:74def30d04efe720ddcf4bd0f6e44d8c645719f4290f45c1ed0aacf74ed8acba' | base64)" \
  "http://192.168.1.200:3000/api/standalone/compliance-analysis?scan_target=Kytran+System+Operations" | python3 -m json.tool
```

Expected: `{"success": true, "analysis": null}`

- [ ] **Step 5: Trigger a compliance scan to generate AI analysis**

The standalone's background scheduler will trigger a scan within its interval. Or trigger manually if the standalone is accessible with auth cookies. After the scan, the hub should receive the report and S.H.I.E.L.D. should generate analysis within ~60 seconds.

Check ARCHIE logs for the S.H.I.E.L.D. analysis:
```bash
docker logs archie_platform 2>&1 | grep "S.H.I.E.L.D" | tail -5
```

- [ ] **Step 6: Verify analysis was stored**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT scan_target, LENGTH(executive_summary) as summary_len, model_used, generated_at FROM compliance_ai_analysis ORDER BY generated_at DESC LIMIT 3"
```

- [ ] **Step 7: Log decision**

```python
mcp__archie__log_decision(
    title="S.H.I.E.L.D. AI Compliance Analysis Complete",
    decision="S.H.I.E.L.D. agent generates executive summaries, remediation plans, and trend analysis after each compliance report. Analysis stored in compliance_ai_analysis table, fetched by standalone for reports.",
    project_id=193
)
```

---

## Task Summary

| Task | Description | Codebase | Est. |
|------|-------------|----------|------|
| 1 | AI analysis table migration | ARCHIE DB | 2 min |
| 2 | S.H.I.E.L.D. trigger + fetch endpoint | ARCHIE | 8 min |
| 3 | Hub client fetch_ai_analysis() | Standalone | 3 min |
| 4 | Report service include AI data | Standalone | 3 min |
| 5 | Report template AI sections | Standalone | 5 min |
| 6 | Deploy + verify | Both | 5 min |

**Total: 6 tasks, ~26 minutes**

**Note for future**: When ARCHIE Node becomes a standalone product, register it in `STANDALONE_PRODUCTS` in `code_metrics_service.py` and add to Code Health (same pattern as KSM). Track in Dev HQ projects and tasks.
