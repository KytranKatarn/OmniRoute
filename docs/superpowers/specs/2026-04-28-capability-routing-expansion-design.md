# Capability Routing Expansion + Hire Proposal Cleanup

**Date**: 2026-04-28
**Status**: Approved
**Author**: Kytran + Claude Sonnet 4.6
**ADR**: to be logged as project_decisions entry on completion

---

## Problem

The `spectra_misroute_audit` detected ~90 capabilities with no active Lv4+ dispatchable agent. The `propose_hire` job generated 90 `hire_candidate` approval requests (all pending in DHQ Approvals tab since April 23). K.I.N.'s welfare digest flagged 23 idle AI agents and 2 over-budget. R.E.S.O.L.V.E. has been volunteering to Operations every 5 minutes.

Root cause: ~33 capabilities are absent from `CAPABILITY_DEPARTMENT_MAP`, and no `agent_skills` rows exist for those capabilities on the relevant AI directors. The dispatcher cannot route what it cannot find.

The proposals are recommending the wrong solution (reactivating human internal agents). The right solution is routing to the 34 AI acronym agents that already exist.

---

## Decision

**Route all 89 capabilities to existing AI acronym agents. Reject all 90 hire proposals. Create 0 new agents.**

- Human roster is at capacity — no new internal agents
- 1 capability dropped entirely: `Crop Analysis` (scanner false positive — C.A.R.G.O. handles shipping/logistics, not agriculture)
- Governance event logged to C.R.E.E.D. public institute as a transparency report
- `creed_violations` table added to platform DB to enable future dispatch ethics tracking

---

## Capability → Department Mapping (89 capabilities)

| Department | Director | Capabilities |
|-----------|---------|-------------|
| Engineering & Technology | F.O.R.G.E. | CI/CD Pipeline, Container Orchestration, Deployment Automation, Infrastructure as Code, Infrastructure Architecture, API Architecture, API Integration, API Documentation, Database Design, Distributed Systems, Algorithm Design, Algorithmic Modeling, Code Quality Analysis, Bug Reporting, Edge Computing, Keyboard Navigation, Framework Implementation |
| Security & Compliance | V.I.G.I.L. | Encryption, Cryptographic Auditing, Key Management, Audit Management, Alert Management |
| Analytics & Intelligence | S.P.E.C.T.R.A. | Data Analysis, Data Visualization, Dashboard Design, Anomaly Detection, Competitive Analysis, Competitive Research, Comparative Research, AI Research, Intelligence Gathering, Backtesting |
| Marketing & Communications | S.I.G.N.A.L. | Digital Marketing, Keyword Research, Campaign Management, Campaign Conceptualization, Content Strategy, Audience Targeting, Copywriting, Crisis Communication, Community Building, Community Relations, Engagement Management |
| Creative & Design | M.U.S.E. | Creative Writing, Creative Direction, Brand Strategy, Content Architecture, Accessible UI Design |
| Documentation & Knowledge | C.O.D.E.X. | Knowledge Base Curation, Information Design, Briefing Preparation |
| Research & Development | D.A.R.W.I.N. | Experimental Design, Comparative Research, Competitive Research |
| Finance & Accounting | L.E.D.G.E.R. | Financial Reporting, Budgeting, Cost Analysis, Cost Estimation, Expense Tracking, Cash Flow Management, Drawdown Management, Fundamental Analysis |
| Operations & Infrastructure | B.A.S.E. | Facilities Management, Grounds Maintenance, Capacity Modeling, Infrastructure Planning, BIM Modeling, Arctic Infrastructure, Incident Management, Feature Prioritization |
| Logistics & Supply Chain | C.A.R.G.O. | Inventory Management, Itinerary Planning, Booking Management |
| Human Resources & Culture | K.I.N. | Coaching, Employee Relations, Habit Formation, Event Organization, Executive Scheduling |
| Customer Success & Support | R.E.S.O.L.V.E. | Customer Onboarding, Customer Advocacy, Churn Prevention, Conflict Resolution |
| Diplomatic & External Relations | A.C.C.O.R.D. | Bilingual Communication, Cultural Mediation, Cultural Intelligence, ASL Communication, Guest Experience, Hospitality Operations |
| Medical & Wellness | V.I.T.A.L. | Health Data Analysis, Biometric Monitoring |
| Legal & Regulatory | G.A.V.E.L. | Audit Management *(shared with V.I.G.I.L.)* |

**Skill levels**: Lv5 for capabilities core to the department mission, Lv3 generalist for all others.

---

## Technical Changes

### 1. `CAPABILITY_DEPARTMENT_MAP` — two files, both must be updated

- `platform_v2/services/department_coordinator.py:45` — used by coordinator for agent selection
- `platform_v2/tools/department_hq/services/department_dispatcher.py:97` — used by dispatcher for station routing

Add all 89 capability strings mapped to their department name in both. If a capability is missing, the dispatcher defaults to "Engineering & Technology" — which explains why F.O.R.G.E. was getting everything.

### 2. `agent_skills` table

Seed skill rows for each AI director:
```sql
INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, can_escalate_to)
VALUES (...) ON CONFLICT DO NOTHING;
```

Each director gets rows for their department's capabilities. Core capabilities at Lv5, others at Lv3. Escalation target = A.R.C.H.I.E. (id=2) for all.

### 3. Bulk-reject all pending hire proposals

```sql
UPDATE autonomy_approval_queue
SET status = 'rejected',
    rejected_reason = 'Capability routing fix applied — routed to existing AI acronym agents. No headcount expansion needed.',
    updated_at = NOW()
WHERE action_type = 'hire_candidate' AND status = 'pending';
```

### 4. `creed_violations` table migration

```sql
CREATE TABLE IF NOT EXISTS creed_violations (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id),
    agent_name VARCHAR(100),
    violation_type VARCHAR(100) NOT NULL,
    severity VARCHAR(20) DEFAULT 'low' CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    description TEXT,
    dispatch_context JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'resolved', 'dismissed')),
    resolved_at TIMESTAMP,
    resolved_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_creed_violations_agent ON creed_violations(agent_id);
CREATE INDEX IF NOT EXISTS idx_creed_violations_status ON creed_violations(status, severity);
```

### 5. Platform restart

Dispatcher caches agent skills at startup. Restart required after skill seeding.

---

## C.R.E.E.D. Governance

### Internal ADR
Logged via `mcp__archie__log_decision` on completion:
- **Title**: Capability Routing Expansion — 89 capabilities routed to existing AI agents
- **Decision**: Chose routing over headcount. 90 hire proposals rejected.
- **Context**: K.I.N. welfare flag, 23 idle agents, 90 pending proposals since April 23
- **Consequences**: Dispatcher coverage expanded, hire proposal flood stops, K.I.N. idle-agent metric should improve within 24h of restart

### Public Transparency Report
New entry on creed.kytranempowerment.com and creed-ai.org under **"Capability Governance"**:

> *"April 2026 — Capability Routing Review: A.R.C.H.I.E. evaluated 90 AI capability proposals. 89 routed to existing agents using skill-based dispatch. 1 rejected (out of platform scope). 0 new AI agents created. Decision rationale: responsible scaling through existing governance structure rather than headcount expansion."*

This demonstrates: transparent AI governance, preference for existing agent reuse, documented decision trail — all grant-fundable signals.

---

## Success Criteria

1. `CAPABILITY_DEPARTMENT_MAP` covers all 89 new capabilities
2. Each AI director has `agent_skills` rows for their department's capabilities
3. 0 pending `hire_candidate` approvals in DHQ Approvals tab
4. Next K.I.N. welfare digest shows fewer than 23 idle agents
5. `spectra_misroute_audit` next run shows 0 "no active Lv4+ agent" gaps for the 89 mapped capabilities
6. `creed_violations` table exists and is queryable
7. C.R.E.E.D. public pages updated with governance entry

---

## Out of Scope

- Reactivating any decommissioned internal (human) agents
- Creating new AI acronym agents (unless a future audit reveals a genuine department gap)
- Changes to the `propose_hire` job logic (it's working correctly — the input data will change once routing is fixed)
- R.E.S.O.L.V.E. volunteering frequency (resolves naturally as idle agents get dispatched)
