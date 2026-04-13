# C.R.E.E.D. Governance Platform — Design Spec

**Date:** 2026-04-13
**Author:** Kytran + Claude
**Status:** Draft
**Project:** C.R.E.E.D. Consolidation + Standalone Extraction

---

## Problem

C.R.E.E.D. (Compliance, Rights & Ethical Enforcement Directive) logic is scattered across 4 locations inside A.R.C.H.I.E.:

1. `tools/creed/` — public transparency page (`/creed`, 5 routes, no auth)
2. `tools/team_management/creed_routes.py` — admin governance API (1,113 lines, auth-required)
3. `tools/department_hq/work_routes.py` — per-department C.R.E.E.D. scores
4. `department_hq/services/orchestration_engine.py` — governance checks in dispatch pipeline

There is no single module that owns governance. The admin API lives inside a deprecated module (Team Management, `enabled=False`). Meanwhile, C.R.E.E.D. is incorporated as a Canadian nonprofit with its own domain (creed-ai.org) and grant-readiness strategy — but the product doesn't exist as a standalone offering.

## Goal

1. **Consolidate** — single `tools/creed/` module owns all governance inside A.R.C.H.I.E.
2. **Extract** — standalone dockerized product (like KSO) with dashboard, compliance reports, and REST API
3. **Monetize** — open-source base + premium compliance tier; grant-ready demo using live A.R.C.H.I.E. data

## Target Users

- **AI companies** — self-govern with C.R.E.E.D., generate compliance reports, display trust badges
- **Government/regulators** — audit AI systems, request C.R.E.E.D. reports as compliance evidence
- **A.R.C.H.I.E.** — first client, live proof-of-concept ("we eat our own cooking")

---

## Phase 1: Internal Consolidation

**Scope:** Merge scattered C.R.E.E.D. code into one module. Delete Team Management.

### What Moves Where

| Source | Destination | Notes |
|--------|------------|-------|
| `team_management/creed_routes.py` (1,113 lines) | `tools/creed/admin_routes.py` | Admin governance API, re-prefixed to `/creed/api/admin/*` |
| `department_hq/work_routes.py` C.R.E.E.D. section | Stays in Dept HQ | Per-department scores are a Dept HQ concern, not standalone |
| `orchestration_engine.py` governance checks | Stays in orchestration | Pipeline integration, calls into creed service |
| `tools/creed/routes.py` (public) | Stays | Already in the right place |

### New File Structure

```
tools/creed/
  __init__.py              — Blueprint setup, route registration
  routes.py                — Public transparency (existing, unchanged)
  admin_routes.py          — Admin governance API (from team_management)
  services/
    governance_service.py  — Ethics constraints, audit logging, scoring
  templates/
    creed_transparency.html — Public page (existing)
```

### What Gets Deleted

| Item | Lines | Why |
|------|-------|-----|
| `tools/team_management/routes.py` | 10,498 | Fully superseded by Department HQ |
| `tools/team_management/creed_routes.py` | 1,113 | Relocated to `tools/creed/admin_routes.py` |
| `tools/team_management/__init__.py` | 23 | Module deleted |
| `templates/tools/team_management.html` | 1,169 | Module deleted |
| `static/css/team-management.css` | TBD | If exists |
| `static/js/team-management.js` | TBD | If exists |

### References to Update

| File | Change |
|------|--------|
| `app.py` | Change `from tools.team_management.creed_routes` to `from tools.creed.admin_routes` |
| `orchestration_engine.py` | String refs `"team_management"` — keep as intent type, just route to creed service |
| `consciousness/routes.py` | Remove `sys.path.insert` for team_management |
| `consciousness/services/api_documentation.py` | Update module reference |
| `module_registry.py` | Remove team_management entry |

### Phase 1 Tasks

1. Move `creed_routes.py` to `tools/creed/admin_routes.py`, update URL prefix
2. Register admin routes in `tools/creed/__init__.py`
3. Update `app.py` import path
4. Delete `tools/team_management/` entirely
5. Delete `templates/tools/team_management.html`
6. Clean all external references (orchestration engine, consciousness, api_docs)
7. Update `module_registry.py`
8. Deploy + verify `/creed` public page still works
9. Verify admin API works at new path
10. Log decision, update session handoff

---

## Phase 2: Standalone Extraction

**Scope:** New repo, dockerized, own DB, own auth, REST API.

### Repository

- **Repo:** `KytranKatarn/kytran-creed` (or `creed-governance`)
- **Port:** 8086 (next available after KSO 8085, KBS 8091)
- **Subdomain:** `creed.kytranempowerment.com`
- **Container:** `kytran_creed`

### Architecture

```
kytran-creed/
  docker-compose.yml
  Dockerfile
  kytran_creed/
    app.py                    — Flask app
    config.py                 — Environment config
    auth.py                   — Local auth + SSO ("Sign in with Kytran")
    db.py                     — SQLite default, Postgres option
    models/
      governance_event.py     — Event schema (agent actions, decisions, violations)
      compliance_score.py     — Per-agent/per-system scoring
      audit_trail.py          — Immutable audit log
    routes/
      dashboard_routes.py     — Live governance dashboard
      api_routes.py           — REST API for external platforms
      report_routes.py        — PDF compliance report generation
      badge_routes.py         — SVG compliance badges
      webhook_routes.py       — Inbound events from monitored platforms
    services/
      scoring_engine.py       — Calculate compliance scores from events
      report_generator.py     — PDF report with scores, remediations, badges
      badge_service.py        — Dynamic SVG badge generation
    templates/
      dashboard.html          — LCARS governance dashboard
      report.html             — Print-ready compliance report
    static/
      css/creed.css
      js/creed.js
```

### REST API (for external platforms)

```
POST /api/v1/events          — Submit governance event (agent action, decision, violation)
GET  /api/v1/scores          — Get compliance scores (overall, per-agent, per-category)
GET  /api/v1/scores/{id}     — Get score for specific agent/system
GET  /api/v1/report           — Generate compliance report (JSON or PDF)
GET  /api/v1/badge/{type}     — Get SVG compliance badge
GET  /api/v1/audit            — Query audit trail
POST /api/v1/webhook/register — Register webhook for score changes
GET  /api/v1/frameworks       — List supported compliance frameworks
GET  /api/v1/health           — Health check
```

### Compliance Frameworks (Supported)

| Framework | Region | Status |
|-----------|--------|--------|
| EU AI Act | EU | Phase 2 |
| Canadian AIDA | Canada | Phase 2 |
| SOC 2 Trust Services | Global | Phase 2 (already in KSO) |
| NIST AI RMF | US | Phase 3 |
| ISO 42001 | Global | Phase 3 |

### Event Schema

```json
{
  "event_type": "agent_action|decision|violation|welfare_check|ethics_review",
  "source_platform": "archie",
  "agent_id": "agent-131",
  "agent_name": "Beacon-A",
  "category": "transparency|fairness|safety|privacy|accountability",
  "severity": "info|warning|violation|critical",
  "description": "Agent made autonomous decision without human review",
  "metadata": {},
  "timestamp": "2026-04-13T12:00:00Z"
}
```

### A.R.C.H.I.E. as First Client

A.R.C.H.I.E.'s orchestration engine already generates governance events (IAAE checks, welfare gates, ethics constraints). Phase 2 adds a reporter service that forwards these to the standalone C.R.E.E.D. instance:

```
Orchestration Engine → governance event → C.R.E.E.D. Reporter → POST /api/v1/events
                                                                  ↓
                                                         Scoring Engine
                                                                  ↓
                                                    Dashboard + Reports + Badges
```

### Phase 2 Tasks

1. Create repo with Dockerfile + docker-compose.yml (Tier 1 compliance)
2. Implement event ingestion API (`POST /api/v1/events`)
3. Implement scoring engine (calculate compliance from events)
4. Build dashboard (LCARS theme, live stats from DB)
5. Implement compliance report generator (PDF)
6. Implement badge service (SVG, same grading as KSO)
7. Add auth (local + SSO stub)
8. Add A.R.C.H.I.E. reporter service (forward governance events)
9. API documentation (OpenAPI/Swagger)
10. README + install instructions
11. Register in operational-state.md + Code Health

---

## Phase 3: Market + Grants

**Scope:** Public presence, grant applications, ecosystem partnerships.

### creed-ai.org Updates

- Product page with live demo link (points to A.R.C.H.I.E.'s `/creed`)
- API documentation page
- "For Companies" landing: self-governance, compliance badges, audit trail
- "For Regulators" landing: inspection API, report generation, framework mapping
- Case study: "How A.R.C.H.I.E. governs 131 AI agents in real-time"

### Grant Targets (from memory)

- CIFAR (Pan-Canadian AI Strategy)
- IVADO (Montreal AI institute)
- Mila (Quebec AI research)
- NRC IRAP (industrial research)
- SSHRC (social sciences — AI ethics)
- Scale AI (Canadian AI supercluster)

### Open Source Strategy

| Tier | What | Price |
|------|------|-------|
| **Open Source** | Event API, scoring engine, dashboard, basic reports | Free |
| **Pro** | PDF reports, badge service, multi-framework support | Paid |
| **Enterprise** | Custom frameworks, webhook alerts, API SLA, support | Paid |

### Phase 3 Tasks

1. Update creed-ai.org with product page + API docs
2. Write case study: A.R.C.H.I.E. as live demo
3. Prepare grant application materials (CIFAR, IVADO, Mila focus)
4. Open-source the base product on GitHub
5. Pricing page for Pro/Enterprise tiers
6. Montreal AI ecosystem outreach (advisory board recruitment)

---

## Success Criteria

| Phase | Metric |
|-------|--------|
| **1** | Single `tools/creed/` module, Team Management deleted, all governance routes working |
| **2** | `docker compose up` runs standalone, API accepts events, generates reports + badges |
| **3** | creed-ai.org has product page, first grant application submitted, GitHub repo public |

## Dependencies

- Phase 1 has no external dependencies (internal cleanup)
- Phase 2 depends on Phase 1 (clean governance engine to extract)
- Phase 3 depends on Phase 2 (working product to demo)
- KSO extraction playbook applies to Phase 2 (same Tier 1/2/3 checklist)

## Risks

| Risk | Mitigation |
|------|-----------|
| Admin API URL change breaks existing calls | No external consumers — only internal admin UI |
| Team Management deletion breaks orchestration | String refs only, not imports — safe to keep intent type |
| Standalone scope creep | Follow KSO playbook strictly, Tier 1 first |
| Grant timeline pressure | Phase 1 gives a working demo immediately via `/creed` |
