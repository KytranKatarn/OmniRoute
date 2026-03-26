# S.H.I.E.L.D. Integration + Node Deployment Design

**Date**: 2026-03-26
**Project**: #193 — Kytran System Operations — Standalone Product + Compliance Engine
**Status**: Design Approved
**Scope**: S.H.I.E.L.D. AI compliance analysis (implement now) + Node/Starship deployment architecture (spec only, defer implementation)
**Depends on**: Tier 2 (hub reporting), Feature Gating, SOC 2 Evidence + Reports

---

## Problem Statement

Compliance scan results are data — S.H.I.E.L.D. turns them into intelligence. AI-powered executive summaries, prioritized remediation plans, and trend analysis make compliance reports actionable. Separately, the standalone needs a deployment path for fleet nodes, following the same extraction playbook pattern.

---

## Deliverable 1: S.H.I.E.L.D. AI Compliance Analysis

### Flow

1. Standalone runs compliance scan → reports to hub via `POST /api/standalone/compliance-report` (already built)
2. Hub receives report → triggers S.H.I.E.L.D. analysis as background task
3. S.H.I.E.L.D. dispatches to Bridge (existing `get_dispatcher().dispatch()` pattern):
   - **Executive Summary**: 2-3 paragraph natural language summary of scan results, severity assessment, key findings
   - **Remediation Plan**: Prioritized list — what to fix first, why it matters, estimated effort, dependencies between fixes
   - **Trend Analysis**: Compare current scan to previous scans — score changes, new failures, resolved issues, trajectory
4. AI analysis stored in `compliance_ai_analysis` table
5. Standalone fetches analysis via hub API when rendering reports
6. HTML/PDF report includes AI sections when available, graceful fallback to static text when not

### Database (ARCHIE PostgreSQL)

```sql
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
```

### Hub-Side Implementation

**Modify `api_standalone.py`**: After storing the compliance report, trigger S.H.I.E.L.D. analysis in a background thread:

```python
# After successful report storage
import threading
thread = threading.Thread(
    target=_run_shield_analysis,
    args=(app._get_current_object(), product_name, scan_data),
    daemon=True,
)
thread.start()
```

**New function `_run_shield_analysis(app, product_name, scan_data)`**:
- Runs inside `with app.app_context():`
- Calls `get_dispatcher().dispatch()` with S.H.I.E.L.D. agent
- Prompt includes: overall score, per-pack scores, failed rules with severities, previous scan scores for trend
- Parses response into executive_summary, remediation_plan, trend_analysis sections
- Stores in `compliance_ai_analysis` table

**New endpoint `GET /api/standalone/compliance-analysis`**:
- Authenticated via client credentials (same as compliance report)
- Query params: `scan_target` (product name)
- Returns latest AI analysis for the product
- Response: `{executive_summary, remediation_plan, trend_analysis, generated_at}`

### Bridge Dispatch Prompt

```
You are S.H.I.E.L.D. (Security Hardening, Inspection, Enforcement & Liability Detection),
analyzing compliance scan results for {product_name}.

SCAN RESULTS:
- Overall Score: {score}%
- Frameworks: {pack_scores}
- Failed Rules ({fail_count}): {failed_rules_summary}
- Previous Score: {prev_score}% ({score_delta})

Generate three sections:

## EXECUTIVE SUMMARY
Write 2-3 paragraphs summarizing the compliance posture. Highlight critical findings,
overall assessment, and comparison to previous scan.

## REMEDIATION PLAN
Prioritized list of fixes. For each:
- Priority (1-N)
- Rule ID and description
- Why it matters (business impact)
- Fix command or steps
- Dependencies (must fix X before Y)
- Estimated effort (minutes)

## TREND ANALYSIS
Analyze how compliance changed since the last scan:
- Score trajectory (improving/declining/stable)
- Newly failed rules
- Resolved issues
- Frameworks trending up/down
```

### Standalone-Side Changes

**`hub_client.py`**: Add `fetch_ai_analysis()`:
```python
def fetch_ai_analysis():
    """Fetch latest AI compliance analysis from hub."""
    # GET {hub_url}/api/standalone/compliance-analysis?scan_target=Kytran+System+Operations
```

**`report_service.py`**: Include AI analysis in report data:
```python
# In get_scan_report_data():
ai_analysis = None
if is_hub_configured():
    ai_analysis = fetch_ai_analysis()
data["ai_analysis"] = ai_analysis
```

**`compliance_report.html`**: Conditional AI sections:
```html
{% if ai_analysis %}
<section class="ai-executive-summary">
    <h2>Executive Summary (AI-Generated)</h2>
    {{ ai_analysis.executive_summary|safe }}
</section>
{% else %}
<section class="executive-summary">
    <!-- Static fallback text -->
</section>
{% endif %}
```

### File Map (S.H.I.E.L.D. — Implement Now)

| Action | File | What |
|--------|------|------|
| Create | `database/migrations/203_compliance_ai_analysis.sql` | AI analysis table |
| Modify | `platform_v2/api_standalone.py` | Trigger S.H.I.E.L.D. after report received |
| Modify | `platform_v2/api_standalone.py` | Add /api/standalone/compliance-analysis endpoint |
| Modify | `kytran-server-manager/.../services/hub_client.py` | Add fetch_ai_analysis() |
| Modify | `kytran-server-manager/.../services/report_service.py` | Include AI data in reports |
| Modify | `kytran-server-manager/.../templates/compliance_report.html` | AI sections with fallback |

---

## Deliverable 2: Node/Starship Deployment Architecture (Spec Only)

### Key Architecture Principle

Nodes follow the **same standalone extraction playbook** as KSM:
- Own authentication (local + SSO via hub)
- Own health endpoint (`/api/health`)
- Hub reporting (health + metrics)
- Feature gating by tier
- Docker-deployable

### What "KSM on a Node" Means

```
┌─────────────────────────────────────┐
│ ARCHIE Hub (192.168.1.200)          │
│  - OAuth Provider                    │
│  - Compliance Report Receiver        │
│  - S.H.I.E.L.D. AI Analysis         │
│  - Code Health + Launch Pages        │
│  - Agent Loop Health Monitor         │
└──────────┬──────────────────────────┘
           │ Hub API (SSO, reports, analysis)
           │
┌──────────▼──────────────────────────┐
│ Fleet Node (.246 / .245)             │
│  ┌─────────────────────────────────┐ │
│  │ ARCHIE Node (standalone)        │ │
│  │  - Agent dispatch               │ │
│  │  - Model management             │ │
│  │  - Health: /api/health          │ │
│  └─────────────────────────────────┘ │
│  ┌─────────────────────────────────┐ │
│  │ KSM (Docker container)          │ │
│  │  - System monitoring            │ │
│  │  - Compliance scanning          │ │
│  │  - Health: /api/health          │ │
│  │  - Reports to hub independently │ │
│  └─────────────────────────────────┘ │
└─────────────────────────────────────┘
```

- **Node** is its own standalone product (ARCHIE Node)
- **KSM** runs as an optional Docker container ON the node
- Both report independently to hub — separate health checks, separate compliance reports
- Hub shows both in Code Health and launch pages

### Docker Image for KSM

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8085
CMD ["python", "-m", "kytran_server_manager.app"]
```

Published to: `ghcr.io/kytrankatarn/kytran-server-manager:latest`

### Node docker-compose.yml (KSM as a service)

```yaml
services:
  kytran-sysops:
    image: ghcr.io/kytrankatarn/kytran-server-manager:latest
    container_name: kytran_sysops
    restart: unless-stopped
    read_only: true
    tmpfs:
      - /tmp:size=64m
    environment:
      - KSM_PORT=8085
      - KSM_ARCHIE_HUB_URL=http://192.168.1.200:3000
      - KSM_ARCHIE_CLIENT_ID=kytran-sysops
      - KSM_ARCHIE_CLIENT_SECRET=${KSM_CLIENT_SECRET}
      - KSM_TIER_OVERRIDE=enterprise
    ports:
      - "8085:8085"
    volumes:
      - kytran-sysops-data:/var/lib/kytran-server-manager
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 256M

volumes:
  kytran-sysops-data:
```

### Mesh Integration (Future)

- Node mesh sync discovers KSM container on each node
- Hub `STANDALONE_PRODUCTS` registry extended to track per-node instances
- Code Health shows: "KSM @ Node .246: 42 files, 29K lines, Tier 2: 8/8"
- Each node's KSM has its own compliance scan results (different server = different results)

### Implementation Deferred Until

- Node .246 Docker environment is clean and operational
- Node .245 is set up
- ARCHIE Node standalone product is built (separate project)
- Mesh sync is reliable

---

## Out of Scope

- ARCHIE Node standalone product (separate project)
- Mesh sync protocol changes
- Multi-node compliance aggregation (aggregated reports across fleet)
- Real-time compliance monitoring (config change detection)
- Custom rule pack authoring (Enterprise feature)

---

## Success Criteria

### S.H.I.E.L.D. (Implement Now)
1. After compliance report received, S.H.I.E.L.D. generates AI analysis within 60 seconds
2. Executive summary is 2-3 coherent paragraphs assessing compliance posture
3. Remediation plan is prioritized with fix commands and effort estimates
4. Trend analysis compares to previous scan with specific score changes
5. Standalone report shows AI sections when connected to hub
6. Report gracefully falls back to static text when hub unavailable

### Node Deployment (Deferred — Spec Only)
1. Docker image builds and runs from `docker compose up`
2. KSM container reports compliance to hub independently
3. Hub shows per-node KSM instances in Code Health
4. SSO works from node-deployed KSM to hub
