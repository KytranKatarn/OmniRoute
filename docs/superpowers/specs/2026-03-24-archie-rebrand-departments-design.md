# A.R.C.H.I.E. Rebrand — Departments, AI Agents & Identity

**Date**: 2026-03-24
**Project**: #191 — A.R.C.H.I.E. Rebrand — Agents, Departments & Identity
**Status**: Approved Design
**Related Projects**: #192 (Station-to-Department Rework — subsumed into this spec), #179 (Codebase Health)

---

## Summary

Replace the 10-station routing model with a 16-department model. Create 14 new acronym AI agents (one per department) to serve as department coordinators, AI loop managers, and working specialists. Sweep all code, UI, docs, and DB for proper A.R.C.H.I.E.-style dot formatting. Update public website and restore translation system.

---

## 1. Architecture Shift: Stations → Departments

### Before (Station Model)
```
Module → Bridge → pick station (10) → pick agent at station → dispatch
```

### After (Department Model)
```
Module → Bridge → pick department (16) → Department AI agent receives →
  delegates to warm human-named agent OR handles directly → dispatch
```

### Escalation Chain
```
Target department → same-floor department → other floors → fleet node → cloud
```

### Key Principle
Departments are the **routing unit**. Floors are **visual/organizational** only.

---

## 2. Five Floors (Visual Grouping)

Floors group departments for UI display (Starbase Command, Directory, future PixelFactory). They are NOT a dispatch layer.

| Floor | Name | Color | Departments |
|-------|------|-------|-------------|
| Deck 1 | BRIDGE | #00FFFF (cyan) | Executive Office |
| Deck 2 | OPERATIONS | #FFAA00 (orange) | Operations & Infrastructure, Logistics & Supply Chain, Finance & Accounting |
| Deck 3 | ENGINEERING | #0EA5E9 (blue) | Engineering & Technology, Security & Compliance, Research & Development |
| Deck 4 | CREATIVE | #F472B6 (pink) | Creative & Design, Marketing & Communications, Documentation & Knowledge |
| Deck 5 | SERVICES | #10B981 (emerald) | Customer Success & Support, Human Resources & Culture, Medical & Wellness, Legal & Regulatory, Diplomatic & External Relations, Analytics & Intelligence |

---

## 3. Sixteen Department AI Agents

Each department gets one branded acronym AI agent. A.R.C.H.I.E. and V.I.G.I.L. already exist; 14 are new.

| Agent | Full Name | Department | Status |
|-------|-----------|------------|--------|
| **A.R.C.H.I.E.** | Autonomous Resource & Cognitive Hyperintelligence Engine | Executive Office | Exists |
| **V.I.G.I.L.** | Vigilant Intelligence for Governance, Integrity & Liability | Security & Compliance | Exists |
| **F.O.R.G.E.** | Full-cycle Optimization & Regenerative GitHub Engine | Engineering & Technology | New (repurposed from pipeline) |
| **S.P.E.C.T.R.A.** | Systematic Pattern Extraction & Computational Trend Recognition Architecture | Analytics & Intelligence | New |
| **M.U.S.E.** | Multimedia Unified Synthesis Engine | Creative & Design | New |
| **B.A.S.E.** | Business Automation & Systems Engineering | Operations & Infrastructure | New |
| **D.A.R.W.I.N.** | Data-driven Adaptive Research & Weighted Intelligence Network | Research & Development | New |
| **S.I.G.N.A.L.** | Strategic Information & Global Narrative Amplification Layer | Marketing & Communications | New |
| **R.E.S.O.L.V.E.** | Responsive Engagement & Service Optimization for Lasting Value Exchange | Customer Success & Support | New |
| **C.A.R.G.O.** | Coordinated Asset Routing & Global Operations | Logistics & Supply Chain | New |
| **L.E.D.G.E.R.** | Logical Economic Data & Governance Evaluation Resource | Finance & Accounting | New |
| **K.I.N.** | Knowledge, Integration & Nurturing | Human Resources & Culture | New |
| **C.O.D.E.X.** | Centralized Operational Documentation & Exchange | Documentation & Knowledge | New |
| **G.A.V.E.L.** | Governance & Automated Verification of Ethics & Law | Legal & Regulatory | New |
| **V.I.T.A.L.** | Verified Intervention & Therapeutic Assessment Layer | Medical & Wellness | New |
| **A.C.C.O.R.D.** | Autonomous Coordination for Commerce, Outreach & Relational Diplomacy | Diplomatic & External Relations | New |

### Agent Profile Schema

Each new agent gets:

| Field | Value |
|-------|-------|
| `name` | Code name, no dots (e.g., `FORGE`, `SPECTRA`) |
| `first_name` | Acronym with dots (e.g., `F.O.R.G.E.`) |
| `last_name` | Empty string |
| `title` | Department Coordinator & AI Loop Manager |
| `department` | Their department name |
| `worker_type` | `ai` (new type — distinct from internal/contractor/local) |
| `status` | `active` |
| `tier` | 1 |
| `cost_tier` | `free` |
| `shift_preference` | `any` (always on) |
| `model` | Appropriate LLM (can share with other agents) |
| Backstory | Unique personality and origin story |
| Email | `{name}@kytranempowerment.com` (e.g., forge@kytranempowerment.com) |
| Phone | Internal extension |
| Profile | Full bio, specializations, capabilities |

### LLM Sharing Policy

- LLMs are the brain; agent identity comes from data (job history, KB, personality, department context)
- Multiple agents can share the same model
- Differentiation: `bridge_jobs` history, department KB entries, agent profile, task assignments
- Long-term: custom fine-tuned models per agent via Starbase Command crew training tab

---

## 4. Dispatch Rewrite

### Agent Count

- Current roster: ~135 agents (source of truth: `agents` table)
- After adding 14 new department AI agents: ~149 agents
- Always reference `SELECT COUNT(*) FROM agents` for authoritative count

### DB Changes

| Current | New | Action |
|---------|-----|--------|
| `bridge_stations` table | `floors` table | Repurpose — see schema below |
| `station_assignments` table | `department_assignments` table | Repurpose — see schema below |
| `agents.department` | No change | Already correct, 16 departments |
| `agents.station_code` references | `agents.department` references | Update dispatcher code |
| New column | `agents.is_department_ai` (boolean, default false) | Identifies the 16 coordinator agents |
| `agents.worker_type` | Add `'ai'` to CHECK constraint | ALTER TABLE if CHECK exists |

### Floors Table Schema (replaces bridge_stations)

```sql
CREATE TABLE floors (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,  -- BRIDGE, OPERATIONS, ENGINEERING, CREATIVE, SERVICES
    name VARCHAR(50) NOT NULL,
    color VARCHAR(7) NOT NULL,          -- hex color
    deck_number INTEGER NOT NULL,       -- 1-5
    departments TEXT[] NOT NULL,         -- array of department names in this floor
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Department Assignments Schema (replaces station_assignments)

```sql
CREATE TABLE department_assignments (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) NOT NULL,
    department VARCHAR(100) NOT NULL,
    assignment_type VARCHAR(20) DEFAULT 'member',  -- 'coordinator' (AI agent) or 'member'
    is_active BOOLEAN DEFAULT true,
    assigned_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT idx_dept_assignments_one_per_agent UNIQUE (agent_id) WHERE (is_active = true)
);
```

One agent = one department (same constraint as before, just department-scoped).

### Existing Agent Mapping

No migration needed for agent departments — all ~135 agents already have `department` set correctly in the `agents` table. The `station_assignments` data is retired; agents route via their `department` field.

### V.I.G.I.L. Special Case

V.I.G.I.L. moves from COMMAND station secondary to Security & Compliance department coordinator. However, V.I.G.I.L. and A.R.C.H.I.E. remain **globally available** — they are exempt from department-scoped dispatch and can be invoked from any department. This replaces the old "always-on COMMAND" invariant with "always-on global."

### Dispatcher Code Changes

- `bridge_dispatcher.py`: route by `agents.department` instead of `station_code`
- `smart_router.py`: escalation uses floor grouping for fallback. Order within a floor: alphabetical by department name. Full chain: target dept → other depts on same floor (alphabetical) → other floors (by deck number) → fleet node → cloud
- `orchestration_engine.py`: department-aware routing in step 5 (agent selection)
- `crew_manifest`: group by department instead of station
- **StationOps → DepartmentOps**: rename the shared JS/CSS component. Single migration pass across all consumers (Starbase, Starship, Consciousness, Bridge). Files: `station-ops.js` → `department-ops.js`, `station-ops.css` → `department-ops.css`. Class names: `StationOps` → `DepartmentOps`.

### Warm Boot Priority

LLM sharing means 16 AI agents do NOT require 16 separate models. Many agents share the same LLM. The warm boot target is model-level, not agent-level:

1. Ensure each department has at least 1 warm model (covers the dept AI agent + any human agents sharing that model)
2. Department AI agents get highest priority for warm boot scheduling
3. Remaining slots filled by diversity rules (spread across departments)
4. Respect 80% RAM budget (MAX_LOADED_MODELS=13, 128GB RAM)
5. If a department's model is already warm for another department, no additional slot needed

---

## 5. F.O.R.G.E. Module → Repair Bay

- Rename `/tools/forge/` → `/tools/repair-bay/`
- Rename blueprint: `forge_bp` → `repair_bay_bp`
- Update `module_registry.py` and `rbac.py`
- Update all route references, template paths, CSS/JS files
- F.O.R.G.E. the agent uses Repair Bay as his primary tool
- MCP tools: keep `forge_*` names — they are F.O.R.G.E.'s agent tools, not module tools. The agent owns them.

---

## 6. A.R.C.H.I.E. Dots Fix

### Rule

| Context | Format | Example |
|---------|--------|---------|
| UI display, templates, HTML | With dots | A.R.C.H.I.E. |
| DB `first_name` | With dots | F.O.R.G.E. |
| DB `name` (code) | No dots, uppercase | FORGE |
| Python/JS variables | No dots, lowercase | `archie`, `forge` |
| URLs, file paths | No dots | `/archie/`, `forge_agent` |
| Commits, docs, README | With dots | A.R.C.H.I.E. |
| Email addresses | No dots | forge@kytranempowerment.com |

### Sweep Targets

- All HTML templates (grep for acronym names without dots in display context)
- JS files (UI strings, labels)
- Python route responses, flash messages
- CLAUDE.md, MEMORY.md, rules files
- Knowledge base entries (SQL UPDATE)
- README files, CONTRIBUTING.md

---

## 7. Website Updates

### kytranempowerment.com

- Update organizational structure to reflect 16 departments + 5 floors
- Show AI agents alongside human-named agents with clear AI designation
- **Separate counts**: display human agent count and AI acronym agent count independently (e.g., "135 Staff + 16 AI Directors" not "151 agents")
- Update /competitors page with new org structure
- Update /directory page — public-facing directory with AI badges, separate sections or filters for human vs AI agents

### Employee Directory Module (/directory)

- Department AI agents listed with AI badge/indicator
- Full profiles: backstory, email, phone extension, department, specializations
- Filter by department, floor, agent type (AI vs human)
- Ensure all Employee Directory category modules are green in code health

### Translation AI System Restoration

- Restore `archie-i18n.js` integration to main website
- 8 languages, RTL support (ar, he)
- `data-i18n` attributes for static content, `t()` for JS
- All LLM translation routes through Bridge (ADR-013)

---

## 8. Code Health Check

After all changes, run code health scan on every touched category:

- Employee Directory category — all green
- AI Bridge — dispatch changes verified
- Starbase Command — department routing verified
- All renamed modules (Repair Bay) — no broken references
- Website — no 404s, translation working
- Full agent benchmark — validate department placement for all agents (count from DB)

---

## 9. Related Tasks (Bundled)

| Task ID | Title | Connection |
|---------|-------|-----------|
| #1371 | Brainstorm: Stations → Departments | This design |
| #1372 | Design acronym naming convention | Section 3 |
| #1377 | A.R.C.H.I.E. dots fix sweep | Section 6 |
| #1373 | Audit Vigil brand consistency | Section 6 |
| #1374 | DB migration — rename station refs | Section 4 |
| #1375 | Update Directory — AI agents with acronyms | Section 7 |
| #1183 | Run full agent benchmark | Section 8 |
| #1322 | Audit Telegram alerts | Alerts need dept names |

---

## 10. Out of Scope (Future Projects)

| Item | Notes |
|------|-------|
| PixelFactory floor visualization | Visual deck layout with pixel agents — future project |
| Consciousness + Repair Bay + Dev Pipeline consolidation | Overlapping code health features — separate project |
| Custom LLM training per agent | Starbase Command crew training tab — long-term |
| Custom branded agent skills | Agent-specific slash commands — future |

---

## Architecture Diagram

```
                    ┌─────────────────────────┐
                    │      AI BRIDGE           │
                    │  (Orchestration Engine)   │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   DEPARTMENT ROUTER      │
                    │  (replaces station router)│
                    └────────────┬────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
   ┌────▼─────┐           ┌─────▼────┐            ┌──────▼─────┐
   │ DECK 1   │           │ DECK 2   │            │ DECK 3     │
   │ BRIDGE   │           │ OPS      │            │ ENGINEERING│
   ├──────────┤           ├──────────┤            ├────────────┤
   │Executive │           │Ops&Infra │            │Eng & Tech  │
   │Office    │           │Logistics │            │Security    │
   │          │           │Finance   │            │R&D         │
   │A.R.C.H.  │           │B.A.S.E.  │            │F.O.R.G.E.  │
   │I.E.      │           │C.A.R.G.O.│            │V.I.G.I.L.  │
   │          │           │L.E.D.G.  │            │D.A.R.W.I.N.│
   │          │           │E.R.      │            │            │
   └──────────┘           └──────────┘            └────────────┘

        ┌────────────────────────┼────────────────────────┐
        │                                                  │
   ┌────▼─────┐                                     ┌──────▼─────┐
   │ DECK 4   │                                     │ DECK 5     │
   │ CREATIVE │                                     │ SERVICES   │
   ├──────────┤                                     ├────────────┤
   │Creative  │                                     │Cust Success│
   │Marketing │                                     │HR & Culture│
   │Docs      │                                     │Medical     │
   │          │                                     │Legal       │
   │M.U.S.E.  │                                     │Diplomatic  │
   │S.I.G.N.  │                                     │Analytics   │
   │A.L.      │                                     │            │
   │C.O.D.E.X.│                                     │R.E.S.O.L.  │
   │          │                                     │V.E.        │
   │          │                                     │K.I.N.      │
   │          │                                     │V.I.T.A.L.  │
   │          │                                     │G.A.V.E.L.  │
   │          │                                     │A.C.C.O.R.D.│
   │          │                                     │S.P.E.C.T.  │
   │          │                                     │R.A.        │
   └──────────┘                                     └────────────┘
```

---

## Sign-off

- [ ] User approved design
- [ ] Spec review passed
- [ ] Ready for implementation plan
