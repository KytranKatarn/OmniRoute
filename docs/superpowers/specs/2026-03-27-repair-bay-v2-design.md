# Repair Bay v2 — F.O.R.G.E. Full Auto-Remediation

**Date**: 2026-03-27
**Project**: #193 Kytran System Operations / Repair Bay Enhancement
**Status**: Approved
**Owner**: F.O.R.G.E. (Engineering AI Director)

---

## Problem

The Repair Bay (dev_pipeline module) has a working Scan → Proposal → Sandbox → Deploy pipeline and self-healing with circuit breakers, but:

1. **No Dependabot integration** — GitHub flags 73 vulnerabilities but F.O.R.G.E. doesn't know about them
2. **CodeRabbit dashboard orphaned** — `coderabbit.html` (217KB) exists but isn't wired into Repair Bay
3. **No recurring agent loop job** for vulnerability scanning/remediation
4. **No Bridge dispatch chain** for F.O.R.G.E. to delegate repair work to staff agents

## Solution

Extend Repair Bay with automated vulnerability ingestion, agent-delegated remediation, and compliance-gated merging.

---

## Architecture

### Core Loop

```
[Agent Loop Job - every 6h]
        |
        v
[GitHub Dependabot API] --> poll all open alerts
        |
        v
[F.O.R.G.E. Triage] --> create repair proposals per alert
        |
        v
[Bridge Dispatch] --> delegate to Engineering staff agent
        |
        v
[Staff Agent] --> bump version in manifest
              --> run sandbox tests
              --> open PR with fix
        |
        v
[S.H.I.E.L.D. Validation] --> compliance/security gate
        |
        +---> PASS --> auto-merge PR
        +---> FAIL --> Telegram escalation (Tier 2)
        +---> Circuit breaker (max 5 attempts) --> STOP + alert
```

### Agent Dispatch Chain

| Step | Agent | Role |
|------|-------|------|
| 1. Triage | F.O.R.G.E. | Receives alert, assesses severity, creates proposal, delegates |
| 2. Fix | Engineering staff agent | Bumps dependency, modifies manifest, runs local validation |
| 3. Test | Engineering staff agent | Sandbox execution, test suite verification |
| 4. Review | S.H.I.E.L.D. | Compliance gate — validates fix meets security standards |
| 5. Merge/Escalate | F.O.R.G.E. | Auto-merges on S.H.I.E.L.D. approval, escalates on failure |

### Integration Points

| System | Integration |
|--------|-------------|
| **Autonomy Module** | New agent loop job registered for Dependabot polling (every 6h) |
| **Bridge Dispatcher** | F.O.R.G.E. dispatches staff agents via `get_dispatcher().dispatch()` |
| **GitHub REST API** | Existing `github_service.py` extended with Dependabot alert endpoints |
| **Circuit Breaker** | Existing `forge_self_heal.py` constraints apply (max 5 attempts, 10/hr cap) |
| **Telegram** | Existing escalation for failures and Tier 2 approvals |

---

## Components

### 1. Dependabot Alert Poller

**Location**: `platform_v2/tools/dev_pipeline/services/dependabot_service.py`

**Responsibilities**:
- Poll GitHub Dependabot API: `GET /repos/{owner}/{repo}/dependabot/alerts`
- Filter for open alerts only
- Deduplicate against existing proposals (same package + manifest = skip)
- Create repair proposals for new alerts
- Track alert state (open, fixed, dismissed) in DB

**Manifest auto-discovery**:
- Scan repo for all `requirements.txt`, `pyproject.toml`, `go.mod`, `package.json`, `Gemfile`
- Map Dependabot alerts to discovered manifests
- No manual registration needed

### 2. Agent Loop Job Registration

**Location**: `ai_bridge/agent_loop.py` — new job entry

**Job spec**:
- **Name**: `dependabot_scan`
- **Interval**: every 6 hours
- **Function**: `_run_dependabot_scan()`
- **Pattern**: Same as existing `_run_proactive_scan()` and compliance scan jobs
- **Flow**: Poll → triage → create proposals → trigger auto-fix pipeline
- **Governance**: Logged via `_log_autonomy_action()` to `governance_audit_log`

### 3. GitHub Service Extension

**Location**: `platform_v2/tools/dev_pipeline/services/github_service.py` (extend existing)

**New functions**:
- `get_dependabot_alerts(state='open')` — fetch all open alerts
- `dismiss_dependabot_alert(alert_number, reason)` — dismiss after fix verified
- `get_alert_details(alert_number)` — full alert info with advisory
- `get_coderabbit_reviews(pr_number)` — fetch CR review comments from PR

**Auth**: Uses existing GitHub token from `/mnt/archie_brain/secrets/api/github_token.txt`

### 4. F.O.R.G.E. Triage Logic

**Location**: `platform_v2/tools/dev_pipeline/services/forge_triage.py` (new)

**Responsibilities**:
- Receive Dependabot alert
- Determine fix strategy:
  - **Version bump**: Simple `>=` constraint update in manifest
  - **Major upgrade**: Flag for human review if major version change
  - **No fix available**: Log, skip, notify via Telegram
- Create proposal with:
  - Source: `dependabot` (vs existing `scan` source)
  - Severity mapped from Dependabot (critical/high/medium/low)
  - Manifest path and package name
  - Proposed fix version
- Dispatch to Engineering staff agent via Bridge

### 5. S.H.I.E.L.D. Compliance Gate

**Location**: `platform_v2/tools/dev_pipeline/services/shield_gate.py` (new)

**Responsibilities**:
- Called after staff agent opens PR with fix
- Validates:
  - No new vulnerabilities introduced (re-scan)
  - Test suite passes in sandbox
  - Version bump doesn't break pinned compatibility
  - No secrets or unexpected files in diff
- Returns PASS/FAIL with reasoning
- On PASS: F.O.R.G.E. auto-merges
- On FAIL: Telegram escalation with S.H.I.E.L.D. report

### 6. CodeRabbit Absorption

**Source**: `platform_v2/templates/tools/coderabbit.html` (217KB orphaned template)

**Extract and integrate**:
- PR review summary cards (review status, comment counts, fix suggestions)
- Code health metrics (recurring issues, top fixers)
- Discard: standalone navigation, duplicate styling, disconnected JS

**Target**: New sections in `dev_pipeline.html` under Reviews tab

**Cleanup**: Delete `coderabbit.html` after absorption complete

---

## UI Changes (dev_pipeline.html)

### New Default Landing: Unified Repair Queue

A single prioritized view merging all repair sources:

| Column | Description |
|--------|-------------|
| Severity | Critical / High / Medium / Low (color-coded) |
| Source | Dependabot / Scan / CodeRabbit (icon badges) |
| Package/File | What needs fixing |
| Manifest | Which requirements file |
| Status | Pending / In Progress / Fixed / Failed / Escalated |
| Agent | Which agent is working on it |
| Actions | Fix / Dismiss / Escalate |

**Filters**: By severity, source, status, manifest
**Sort**: Severity (default), date, source

### New Tabs

| Tab | Content |
|-----|---------|
| **Repair Queue** (default) | Unified view described above |
| **Vulnerabilities** | Dependabot-specific: alert details, advisory info, affected versions, fix availability |
| **Reviews** | CodeRabbit PR feedback: review summaries, recurring issues, code health metrics |
| Scan | Existing — code scanning results |
| Proposals | Existing — improvement proposals |
| Sandbox | Existing — test execution |
| Deploy | Existing — deployment pipeline |

---

## Database Changes

### New table: `repair_queue`

```sql
CREATE TABLE IF NOT EXISTS repair_queue (
    id SERIAL PRIMARY KEY,
    source VARCHAR(20) NOT NULL CHECK (source IN ('dependabot', 'scan', 'coderabbit')),
    severity VARCHAR(10) NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    package_name VARCHAR(255),
    manifest_path VARCHAR(500),
    alert_number INTEGER,              -- GitHub Dependabot alert number
    advisory_id VARCHAR(50),           -- GHSA ID
    vulnerable_range VARCHAR(100),
    fix_version VARCHAR(50),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'fixed', 'failed', 'escalated', 'dismissed')),
    proposal_id INTEGER REFERENCES improvement_proposals(id),
    assigned_agent VARCHAR(100),       -- agent display_name
    pr_number INTEGER,                 -- GitHub PR number if fix opened
    attempts INTEGER DEFAULT 0,
    last_attempt_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(source, alert_number)       -- deduplicate Dependabot alerts
);

CREATE INDEX idx_repair_queue_status ON repair_queue(status);
CREATE INDEX idx_repair_queue_severity ON repair_queue(severity);
```

### New table: `manifest_registry`

```sql
CREATE TABLE IF NOT EXISTS manifest_registry (
    id SERIAL PRIMARY KEY,
    file_path VARCHAR(500) NOT NULL UNIQUE,
    manifest_type VARCHAR(20) NOT NULL
        CHECK (manifest_type IN ('pip', 'npm', 'go', 'ruby', 'cargo')),
    last_scanned_at TIMESTAMP,
    package_count INTEGER DEFAULT 0,
    alert_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## MCP Tool Extensions

Extend existing F.O.R.G.E. MCP tools in `forge_tools.py`:

| Tool | Function |
|------|----------|
| `forge_health` | Add: Dependabot alert count, repair queue depth |
| `forge_stats` | Add: alerts by severity, auto-fix success rate, S.H.I.E.L.D. pass rate |
| `forge_self_heal` | Extend: accept `repair_queue_id` as trigger source (not just proposal_id) |
| `forge_scan_vulns` (new) | Trigger on-demand Dependabot poll + manifest discovery |

---

## Error Handling

| Scenario | Response |
|----------|----------|
| GitHub API rate limit | Back off, retry next cycle (6h) |
| No fix version available | Log to repair_queue as `status='dismissed'`, reason='no_fix', Telegram notify |
| Major version bump required | Flag as `status='escalated'`, Telegram Tier 2 approval |
| Sandbox test failure | Retry up to 3x (existing circuit breaker), then escalate |
| S.H.I.E.L.D. rejects fix | Telegram alert with rejection reason, mark `status='failed'` |
| Circuit breaker tripped | Stop all auto-fix for 1h, Telegram alert to admin |

---

## Success Criteria

1. Dependabot alerts appear in Repair Bay within 6 hours of GitHub detection
2. Low/medium alerts auto-remediated without human intervention (version bump + test + PR + merge)
3. High/critical alerts auto-attempted, S.H.I.E.L.D. validated, merged or escalated
4. CodeRabbit review data visible in Reviews tab (no orphaned template)
5. Unified Repair Queue shows all sources in one view with severity sorting
6. Circuit breaker prevents runaway fix attempts
7. Full audit trail in `governance_audit_log` for every auto-remediation

---

## Out of Scope

- GitHub webhooks (polling only for v2)
- npm/Go/Ruby auto-fix logic (start with pip `requirements.txt` only, extend later)
- CodeRabbit auto-fix from review comments (surface only, manual action)
- Cross-repo scanning (single repo: archie-platform)
