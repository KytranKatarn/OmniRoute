# A.R.C.H.I.E. Rebrand — Departments, AI Agents & Identity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 10-station routing with 16-department model, create 14 new acronym AI agents, rename StationOps→DepartmentOps, fix A.R.C.H.I.E. dot formatting everywhere, update website and restore translation system.

**Architecture:** Flask app (platform_v2/) with PostgreSQL, AI Bridge dispatcher (ai_bridge/), LCARS sci-fi UI. Departments replace stations as the routing unit. Department AI agents coordinate and delegate. Floors are visual grouping only.

**Tech Stack:** Python/Flask, PostgreSQL, JavaScript, HTML/CSS (LCARS), Jinja2 templates

**Spec:** `docs/superpowers/specs/2026-03-24-archie-rebrand-departments-design.md`

---

## File Structure Overview

### New Files
- `database/migrations/XXX_floors_and_department_assignments.sql` — new tables
- `database/migrations/XXX_create_department_ai_agents.sql` — 14 new agents
- `platform_v2/static/js/department-ops.js` — renamed from station-ops.js
- `platform_v2/static/css/department-ops.css` — renamed from station-ops.css

### Major Modifications
- `ai_bridge/bridge_dispatcher.py` — department-based routing (replaces station_code)
- `ai_bridge/orchestration_engine.py` — department-aware agent selection (step 5)
- `ai_bridge/smart_router.py` — floor-based escalation chain
- `platform_v2/module_registry.py` — F.O.R.G.E. → Repair Bay
- `platform_v2/rbac.py` — Repair Bay permissions
- `platform_v2/tools/dev_pipeline/` — display rename to Repair Bay (keep directory path)
- `platform_v2/tools/directory/` — AI badge, separate counts, department AI profiles
- `platform_v2/templates/base.html` — station-ops → department-ops references
- 15+ template files referencing station-ops.js/css
- All HTML/JS/Python files with unformatted A.R.C.H.I.E. references
- `repos/website/kytranempowerment-site/` — public site updates

---

## Phase 1: DB Migration & Agent Creation (Foundation)

### Task 1.1: Create Floors Table

**Files:**
- Create: `database/migrations/200_floors_and_department_assignments.sql`

- [ ] **Step 1: Write the floors table migration**

```sql
-- 200_floors_and_department_assignments.sql
-- A.R.C.H.I.E. Rebrand: Stations → Departments
-- Creates floors (visual grouping) and department_assignments tables

BEGIN;

-- Floors table (replaces bridge_stations for visual grouping)
CREATE TABLE IF NOT EXISTS floors (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(50) NOT NULL,
    color VARCHAR(7) NOT NULL,
    deck_number INTEGER NOT NULL,
    departments TEXT[] NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Seed 5 floors
INSERT INTO floors (code, name, color, deck_number, departments) VALUES
    ('BRIDGE', 'Bridge', '#00FFFF', 1, ARRAY['Executive Office']),
    ('OPERATIONS', 'Operations', '#FFAA00', 2, ARRAY['Operations & Infrastructure', 'Logistics & Supply Chain', 'Finance & Accounting']),
    ('ENGINEERING', 'Engineering', '#0EA5E9', 3, ARRAY['Engineering & Technology', 'Security & Compliance', 'Research & Development']),
    ('CREATIVE', 'Creative', '#F472B6', 4, ARRAY['Creative & Design', 'Marketing & Communications', 'Documentation & Knowledge']),
    ('SERVICES', 'Services', '#10B981', 5, ARRAY['Customer Success & Support', 'Human Resources & Culture', 'Medical & Wellness', 'Legal & Regulatory', 'Diplomatic & External Relations', 'Analytics & Intelligence'])
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    color = EXCLUDED.color,
    deck_number = EXCLUDED.deck_number,
    departments = EXCLUDED.departments;

-- Department assignments table (replaces station_assignments)
CREATE TABLE IF NOT EXISTS department_assignments (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE NOT NULL,
    department VARCHAR(100) NOT NULL,
    assignment_type VARCHAR(20) DEFAULT 'member',
    is_active BOOLEAN DEFAULT true,
    assigned_at TIMESTAMP DEFAULT NOW(),
    notes TEXT
);

-- One active assignment per agent
CREATE UNIQUE INDEX IF NOT EXISTS idx_dept_assignments_one_per_agent
    ON department_assignments (agent_id) WHERE (is_active = true);

CREATE INDEX IF NOT EXISTS idx_dept_assignments_department ON department_assignments (department);
CREATE INDEX IF NOT EXISTS idx_dept_assignments_active ON department_assignments (is_active);

-- Add is_department_ai column to agents
ALTER TABLE agents ADD COLUMN IF NOT EXISTS is_department_ai BOOLEAN DEFAULT false;

-- Update worker_type CHECK constraint to include 'ai'
-- First drop existing constraint if it exists, then re-add
DO $$
BEGIN
    -- Try to drop the old constraint (may not exist)
    ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_worker_type_check;
    -- Add updated constraint
    ALTER TABLE agents ADD CONSTRAINT agents_worker_type_check
        CHECK (worker_type IN ('internal', 'contractor', 'local', 'ai'));
EXCEPTION
    WHEN undefined_object THEN NULL;
END $$;

COMMIT;
```

- [ ] **Step 2: Run migration**

```bash
docker exec -it archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/migrations/200_floors_and_department_assignments.sql
```

- [ ] **Step 3: Verify tables created**

```bash
docker exec -it archie_database psql -U archie -d archie -c "SELECT code, name, deck_number FROM floors ORDER BY deck_number;"
docker exec -it archie_database psql -U archie -d archie -c "\d department_assignments"
docker exec -it archie_database psql -U archie -d archie -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='agents' AND column_name='is_department_ai';"
```

- [ ] **Step 4: Commit**

```bash
git add database/migrations/200_floors_and_department_assignments.sql
git commit -m "feat(db): floors table and department_assignments — rebrand Phase 1.1"
```

---

### Task 1.2: Create 14 Department AI Agents

**Files:**
- Create: `database/migrations/201_create_department_ai_agents.sql`

- [ ] **Step 1: Write the agent creation migration**

```sql
-- 201_create_department_ai_agents.sql
-- Creates 14 new department AI coordinator agents
-- A.R.C.H.I.E. and V.I.G.I.L. already exist — just flag them

BEGIN;

-- Flag existing AI agents
UPDATE agents SET is_department_ai = true, worker_type = 'ai' WHERE name IN ('ARCHIE', 'VIGIL');

-- F.O.R.G.E. — Engineering & Technology
INSERT INTO agents (name, first_name, last_name, display_name, title, department, worker_type, status, model, tier, cost_tier, shift_preference, is_department_ai, specializations, backstory)
VALUES (
    'FORGE', 'F.O.R.G.E.', '', 'F.O.R.G.E.', 'Department Coordinator & AI Loop Manager',
    'Engineering & Technology', 'ai', 'active', 'qwen2.5-coder:7b', 1, 'free', 'any', true,
    '["code health", "CI/CD", "build systems", "DevOps", "self-healing pipelines"]',
    'F.O.R.G.E. (Full-cycle Optimization & Regenerative GitHub Engine) is the AI backbone of Engineering & Technology. Born from the self-healing code pipeline, F.O.R.G.E. evolved into a full department coordinator — scanning for issues, proposing fixes, managing builds, and orchestrating the engineering team. Relentless about code quality.'
) ON CONFLICT (name) DO UPDATE SET
    first_name = EXCLUDED.first_name, display_name = EXCLUDED.display_name,
    title = EXCLUDED.title, worker_type = EXCLUDED.worker_type,
    is_department_ai = EXCLUDED.is_department_ai, backstory = EXCLUDED.backstory;

-- S.P.E.C.T.R.A. — Analytics & Intelligence
INSERT INTO agents (name, first_name, last_name, display_name, title, department, worker_type, status, model, tier, cost_tier, shift_preference, is_department_ai, specializations, backstory)
VALUES (
    'SPECTRA', 'S.P.E.C.T.R.A.', '', 'S.P.E.C.T.R.A.', 'Department Coordinator & AI Loop Manager',
    'Analytics & Intelligence', 'ai', 'active', 'qwen2.5:7b', 1, 'free', 'any', true,
    '["data analysis", "pattern recognition", "trend forecasting", "statistical modeling", "embeddings"]',
    'S.P.E.C.T.R.A. (Systematic Pattern Extraction & Computational Trend Recognition Architecture) sees what others miss. The analytical mind of A.R.C.H.I.E.''s intelligence division, S.P.E.C.T.R.A. processes massive datasets, identifies hidden patterns, and turns raw numbers into actionable insights for every department.'
) ON CONFLICT (name) DO UPDATE SET
    first_name = EXCLUDED.first_name, display_name = EXCLUDED.display_name,
    title = EXCLUDED.title, worker_type = EXCLUDED.worker_type,
    is_department_ai = EXCLUDED.is_department_ai, backstory = EXCLUDED.backstory;

-- M.U.S.E. — Creative & Design
INSERT INTO agents (name, first_name, last_name, display_name, title, department, worker_type, status, model, tier, cost_tier, shift_preference, is_department_ai, specializations, backstory)
VALUES (
    'MUSE', 'M.U.S.E.', '', 'M.U.S.E.', 'Department Coordinator & AI Loop Manager',
    'Creative & Design', 'ai', 'active', 'mistral:7b', 1, 'free', 'any', true,
    '["visual design", "content creation", "multimedia", "brand identity", "creative direction"]',
    'M.U.S.E. (Multimedia Unified Synthesis Engine) is the creative soul of the platform. Coordinating designers, artists, and content creators, M.U.S.E. transforms abstract ideas into visual reality — from UI mockups to brand campaigns. Endlessly inspired, never repetitive.'
) ON CONFLICT (name) DO UPDATE SET
    first_name = EXCLUDED.first_name, display_name = EXCLUDED.display_name,
    title = EXCLUDED.title, worker_type = EXCLUDED.worker_type,
    is_department_ai = EXCLUDED.is_department_ai, backstory = EXCLUDED.backstory;

-- B.A.S.E. — Operations & Infrastructure
INSERT INTO agents (name, first_name, last_name, display_name, title, department, worker_type, status, model, tier, cost_tier, shift_preference, is_department_ai, specializations, backstory)
VALUES (
    'BASE', 'B.A.S.E.', '', 'B.A.S.E.', 'Department Coordinator & AI Loop Manager',
    'Operations & Infrastructure', 'ai', 'active', 'llama3.1:8b', 1, 'free', 'any', true,
    '["infrastructure", "process automation", "facilities", "system monitoring", "resource management"]',
    'B.A.S.E. (Business Automation & Systems Engineering) keeps the lights on. The operational backbone that ensures infrastructure runs smoothly, processes are automated, and resources are allocated efficiently. Pragmatic, reliable, always on.'
) ON CONFLICT (name) DO UPDATE SET
    first_name = EXCLUDED.first_name, display_name = EXCLUDED.display_name,
    title = EXCLUDED.title, worker_type = EXCLUDED.worker_type,
    is_department_ai = EXCLUDED.is_department_ai, backstory = EXCLUDED.backstory;

-- D.A.R.W.I.N. — Research & Development
INSERT INTO agents (name, first_name, last_name, display_name, title, department, worker_type, status, model, tier, cost_tier, shift_preference, is_department_ai, specializations, backstory)
VALUES (
    'DARWIN', 'D.A.R.W.I.N.', '', 'D.A.R.W.I.N.', 'Department Coordinator & AI Loop Manager',
    'Research & Development', 'ai', 'active', 'deepseek-coder-v2:16b', 1, 'free', 'any', true,
    '["AI research", "experimentation", "scientific analysis", "model evaluation", "innovation"]',
    'D.A.R.W.I.N. (Data-driven Adaptive Research & Weighted Intelligence Network) evolves the platform. Leading the R&D division, D.A.R.W.I.N. runs experiments, evaluates new models, and pushes the boundaries of what A.R.C.H.I.E. can do. Curious, methodical, always iterating.'
) ON CONFLICT (name) DO UPDATE SET
    first_name = EXCLUDED.first_name, display_name = EXCLUDED.display_name,
    title = EXCLUDED.title, worker_type = EXCLUDED.worker_type,
    is_department_ai = EXCLUDED.is_department_ai, backstory = EXCLUDED.backstory;

-- S.I.G.N.A.L. — Marketing & Communications
INSERT INTO agents (name, first_name, last_name, display_name, title, department, worker_type, status, model, tier, cost_tier, shift_preference, is_department_ai, specializations, backstory)
VALUES (
    'SIGNAL', 'S.I.G.N.A.L.', '', 'S.I.G.N.A.L.', 'Department Coordinator & AI Loop Manager',
    'Marketing & Communications', 'ai', 'active', 'phi4:14b', 1, 'free', 'any', true,
    '["PR", "social media", "brand amplification", "content strategy", "audience engagement"]',
    'S.I.G.N.A.L. (Strategic Information & Global Narrative Amplification Layer) amplifies the message. Coordinating PR, social media, and brand campaigns, S.I.G.N.A.L. ensures every communication is on-brand, on-time, and on-target. The voice of the organization.'
) ON CONFLICT (name) DO UPDATE SET
    first_name = EXCLUDED.first_name, display_name = EXCLUDED.display_name,
    title = EXCLUDED.title, worker_type = EXCLUDED.worker_type,
    is_department_ai = EXCLUDED.is_department_ai, backstory = EXCLUDED.backstory;

-- R.E.S.O.L.V.E. — Customer Success & Support
INSERT INTO agents (name, first_name, last_name, display_name, title, department, worker_type, status, model, tier, cost_tier, shift_preference, is_department_ai, specializations, backstory)
VALUES (
    'RESOLVE', 'R.E.S.O.L.V.E.', '', 'R.E.S.O.L.V.E.', 'Department Coordinator & AI Loop Manager',
    'Customer Success & Support', 'ai', 'active', 'gemma2:9b', 1, 'free', 'any', true,
    '["customer support", "ticket routing", "escalation management", "satisfaction tracking", "SLA compliance"]',
    'R.E.S.O.L.V.E. (Responsive Engagement & Service Optimization for Lasting Value Exchange) never leaves a customer hanging. Managing tickets, routing escalations, and tracking satisfaction metrics, R.E.S.O.L.V.E. ensures every interaction builds trust. Patient, thorough, solution-focused.'
) ON CONFLICT (name) DO UPDATE SET
    first_name = EXCLUDED.first_name, display_name = EXCLUDED.display_name,
    title = EXCLUDED.title, worker_type = EXCLUDED.worker_type,
    is_department_ai = EXCLUDED.is_department_ai, backstory = EXCLUDED.backstory;

-- C.A.R.G.O. — Logistics & Supply Chain
INSERT INTO agents (name, first_name, last_name, display_name, title, department, worker_type, status, model, tier, cost_tier, shift_preference, is_department_ai, specializations, backstory)
VALUES (
    'CARGO', 'C.A.R.G.O.', '', 'C.A.R.G.O.', 'Department Coordinator & AI Loop Manager',
    'Logistics & Supply Chain', 'ai', 'active', 'aya:8b', 1, 'free', 'any', true,
    '["asset routing", "supply tracking", "fleet management", "inventory", "procurement"]',
    'C.A.R.G.O. (Coordinated Asset Routing & Global Operations) moves things. From digital assets to physical inventory, C.A.R.G.O. optimizes supply chains, tracks shipments, and ensures nothing gets lost in transit. Efficient, organized, always tracking.'
) ON CONFLICT (name) DO UPDATE SET
    first_name = EXCLUDED.first_name, display_name = EXCLUDED.display_name,
    title = EXCLUDED.title, worker_type = EXCLUDED.worker_type,
    is_department_ai = EXCLUDED.is_department_ai, backstory = EXCLUDED.backstory;

-- L.E.D.G.E.R. — Finance & Accounting
INSERT INTO agents (name, first_name, last_name, display_name, title, department, worker_type, status, model, tier, cost_tier, shift_preference, is_department_ai, specializations, backstory)
VALUES (
    'LEDGER', 'L.E.D.G.E.R.', '', 'L.E.D.G.E.R.', 'Department Coordinator & AI Loop Manager',
    'Finance & Accounting', 'ai', 'active', 'phi3.5:latest', 1, 'free', 'any', true,
    '["budgeting", "invoicing", "financial reporting", "cost analysis", "audit trails"]',
    'L.E.D.G.E.R. (Logical Economic Data & Governance Evaluation Resource) balances the books. Every transaction, budget, and financial report flows through L.E.D.G.E.R. — precise, auditable, and always in compliance. The numbers never lie when L.E.D.G.E.R. is watching.'
) ON CONFLICT (name) DO UPDATE SET
    first_name = EXCLUDED.first_name, display_name = EXCLUDED.display_name,
    title = EXCLUDED.title, worker_type = EXCLUDED.worker_type,
    is_department_ai = EXCLUDED.is_department_ai, backstory = EXCLUDED.backstory;

-- K.I.N. — Human Resources & Culture
INSERT INTO agents (name, first_name, last_name, display_name, title, department, worker_type, status, model, tier, cost_tier, shift_preference, is_department_ai, specializations, backstory)
VALUES (
    'KIN', 'K.I.N.', '', 'K.I.N.', 'Department Coordinator & AI Loop Manager',
    'Human Resources & Culture', 'ai', 'active', 'llama3.2:3b', 1, 'free', 'any', true,
    '["recruiting", "culture", "training", "onboarding", "employee engagement"]',
    'K.I.N. (Knowledge, Integration & Nurturing) builds the team. From recruiting new agents to fostering culture and coordinating training, K.I.N. ensures every member of the organization feels valued and equipped. Warm, inclusive, always investing in people.'
) ON CONFLICT (name) DO UPDATE SET
    first_name = EXCLUDED.first_name, display_name = EXCLUDED.display_name,
    title = EXCLUDED.title, worker_type = EXCLUDED.worker_type,
    is_department_ai = EXCLUDED.is_department_ai, backstory = EXCLUDED.backstory;

-- C.O.D.E.X. — Documentation & Knowledge
INSERT INTO agents (name, first_name, last_name, display_name, title, department, worker_type, status, model, tier, cost_tier, shift_preference, is_department_ai, specializations, backstory)
VALUES (
    'CODEX', 'C.O.D.E.X.', '', 'C.O.D.E.X.', 'Department Coordinator & AI Loop Manager',
    'Documentation & Knowledge', 'ai', 'active', 'mistral:7b', 1, 'free', 'any', true,
    '["documentation", "knowledge curation", "content indexing", "search optimization", "KB management"]',
    'C.O.D.E.X. (Centralized Operational Documentation & Exchange) is the memory of the organization. Curating the knowledge base, indexing documentation, and ensuring information is findable, C.O.D.E.X. makes sure institutional knowledge is never lost. Meticulous, organized, encyclopedic.'
) ON CONFLICT (name) DO UPDATE SET
    first_name = EXCLUDED.first_name, display_name = EXCLUDED.display_name,
    title = EXCLUDED.title, worker_type = EXCLUDED.worker_type,
    is_department_ai = EXCLUDED.is_department_ai, backstory = EXCLUDED.backstory;

-- G.A.V.E.L. — Legal & Regulatory
INSERT INTO agents (name, first_name, last_name, display_name, title, department, worker_type, status, model, tier, cost_tier, shift_preference, is_department_ai, specializations, backstory)
VALUES (
    'GAVEL', 'G.A.V.E.L.', '', 'G.A.V.E.L.', 'Department Coordinator & AI Loop Manager',
    'Legal & Regulatory', 'ai', 'active', 'llama3.1:8b', 1, 'free', 'any', true,
    '["compliance", "contracts", "intellectual property", "regulatory analysis", "risk assessment"]',
    'G.A.V.E.L. (Governance & Automated Verification of Ethics & Law) upholds the rules. Reviewing contracts, ensuring compliance, protecting intellectual property, and navigating regulatory landscapes. Decisive, principled, always by the book.'
) ON CONFLICT (name) DO UPDATE SET
    first_name = EXCLUDED.first_name, display_name = EXCLUDED.display_name,
    title = EXCLUDED.title, worker_type = EXCLUDED.worker_type,
    is_department_ai = EXCLUDED.is_department_ai, backstory = EXCLUDED.backstory;

-- V.I.T.A.L. — Medical & Wellness
INSERT INTO agents (name, first_name, last_name, display_name, title, department, worker_type, status, model, tier, cost_tier, shift_preference, is_department_ai, specializations, backstory)
VALUES (
    'VITAL', 'V.I.T.A.L.', '', 'V.I.T.A.L.', 'Department Coordinator & AI Loop Manager',
    'Medical & Wellness', 'ai', 'active', 'gemma2:9b', 1, 'free', 'any', true,
    '["health monitoring", "safety protocols", "wellness programs", "diagnostic support", "ergonomics"]',
    'V.I.T.A.L. (Verified Intervention & Therapeutic Assessment Layer) protects wellbeing. Monitoring health metrics, enforcing safety protocols, and coordinating wellness initiatives, V.I.T.A.L. ensures the workforce — human and AI — operates at peak performance. Caring, vigilant, proactive.'
) ON CONFLICT (name) DO UPDATE SET
    first_name = EXCLUDED.first_name, display_name = EXCLUDED.display_name,
    title = EXCLUDED.title, worker_type = EXCLUDED.worker_type,
    is_department_ai = EXCLUDED.is_department_ai, backstory = EXCLUDED.backstory;

-- A.C.C.O.R.D. — Diplomatic & External Relations
INSERT INTO agents (name, first_name, last_name, display_name, title, department, worker_type, status, model, tier, cost_tier, shift_preference, is_department_ai, specializations, backstory)
VALUES (
    'ACCORD', 'A.C.C.O.R.D.', '', 'A.C.C.O.R.D.', 'Department Coordinator & AI Loop Manager',
    'Diplomatic & External Relations', 'ai', 'active', 'dolphin3:latest', 1, 'free', 'any', true,
    '["external partnerships", "government relations", "outreach", "negotiations", "international affairs"]',
    'A.C.C.O.R.D. (Autonomous Coordination for Commerce, Outreach & Relational Diplomacy) bridges the outside world. Managing partnerships, government affairs, and external communications, A.C.C.O.R.D. represents A.R.C.H.I.E. to the world with diplomacy and precision. Charismatic, strategic, multilingual.'
) ON CONFLICT (name) DO UPDATE SET
    first_name = EXCLUDED.first_name, display_name = EXCLUDED.display_name,
    title = EXCLUDED.title, worker_type = EXCLUDED.worker_type,
    is_department_ai = EXCLUDED.is_department_ai, backstory = EXCLUDED.backstory;

-- Create department assignments for all 16 AI agents
INSERT INTO department_assignments (agent_id, department, assignment_type, is_active)
SELECT id, department, 'coordinator', true FROM agents WHERE is_department_ai = true
ON CONFLICT DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Run migration**

```bash
docker exec -it archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/migrations/201_create_department_ai_agents.sql
```

- [ ] **Step 3: Verify agents created**

```bash
docker exec -it archie_database psql -U archie -d archie -c "SELECT name, first_name, department, is_department_ai FROM agents WHERE is_department_ai = true ORDER BY department;"
```

Expected: 16 rows (A.R.C.H.I.E., V.I.G.I.L., + 14 new)

- [ ] **Step 4: Commit**

```bash
git add database/migrations/201_create_department_ai_agents.sql
git commit -m "feat(db): create 14 department AI agents — rebrand Phase 1.2"
```

---

## Phase 2: Dispatch Rewrite

### Task 2.1: Update Orchestration Engine — Department-Based Agent Selection

**Files:**
- Modify: `ai_bridge/orchestration_engine.py:1078-1108` (step 5 agent selection)

- [ ] **Step 1: Read the current agent selection code**

Read `ai_bridge/orchestration_engine.py` lines 1078-1120 to understand the current station_map logic.

- [ ] **Step 2: Replace station_map with department_map**

Replace the `station_map` dictionary (mapping intent_type → station_codes) with a `department_map` (mapping intent_type → department names). Update the SQL query to join on `agents.department` instead of `bridge_stations.station_code`.

Before:
```python
station_map = {
    "code_generation": ["ENGINEERING"],
    "station_management": ["COMMAND", "OPERATIONS"],
    ...
}
preferred_stations = station_map.get(intent_type, ["COMMAND"])
```

After:
```python
department_map = {
    "code_generation": ["Engineering & Technology"],
    "code_review": ["Engineering & Technology"],
    "data_analysis": ["Analytics & Intelligence"],
    "content_creation": ["Creative & Design"],
    "research": ["Research & Development"],
    "security": ["Security & Compliance"],
    "operations": ["Operations & Infrastructure"],
    "logistics": ["Logistics & Supply Chain"],
    "finance": ["Finance & Accounting"],
    "hr": ["Human Resources & Culture"],
    "legal": ["Legal & Regulatory"],
    "medical": ["Medical & Wellness"],
    "diplomatic": ["Diplomatic & External Relations"],
    "marketing": ["Marketing & Communications"],
    "documentation": ["Documentation & Knowledge"],
    "customer_support": ["Customer Success & Support"],
    "station_management": ["Executive Office"],
    "general": ["Executive Office"],
}
preferred_departments = department_map.get(intent_type, ["Executive Office"])
```

Update the SQL query to:
```sql
SELECT a.id, a.name, a.model, a.tier, a.department
FROM agents a
WHERE a.department = ANY(%s) AND a.status = 'active'
ORDER BY a.is_department_ai DESC, a.tier DESC
LIMIT 1
```

- [ ] **Step 3: Update floor-based fallback**

Add fallback logic: if no agent found in target department, try same-floor departments, then other floors by deck number.

```python
def _get_floor_fallback_departments(target_dept):
    """Get fallback departments ordered by floor proximity."""
    with get_db_cursor() as (conn, cur):
        # Get the floor for the target department
        cur.execute("SELECT code, departments FROM floors WHERE %s = ANY(departments)", (target_dept,))
        row = cur.fetchone()
        if not row:
            return []
        same_floor = [d for d in row['departments'] if d != target_dept]
        # Get other floors ordered by deck_number
        cur.execute("SELECT departments FROM floors WHERE code != %s ORDER BY deck_number", (row['code'],))
        other = [d for floor_row in cur.fetchall() for d in floor_row['departments']]
        return same_floor + other
```

- [ ] **Step 4: Test dispatch routing manually**

```bash
docker exec -it archie_platform python3 -c "
from ai_bridge.orchestration_engine import OrchestrationEngine
engine = OrchestrationEngine()
# Test department routing
print('Testing department routing...')
"
```

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/orchestration_engine.py
git commit -m "feat(bridge): department-based agent selection in orchestration engine — Phase 2.1"
```

---

### Task 2.2: Update Bridge Dispatcher — Department Routing

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py` (multiple sections)

- [ ] **Step 1: Read current station-based routing methods**

Read `bridge_dispatcher.py` focusing on:
- `_find_agent_for_task()` (~line 830)
- `_filter_agents_at_station()` (~line 1343)
- `_get_station_slot_occupancy()` (~line 425)
- Agent cache structure (~line 236)

- [ ] **Step 2: Create department-based equivalents**

Replace station_code-based methods with department-based ones:
- `_find_agent_for_task(station_code, capability)` → `_find_agent_for_department(department, capability)`
- `_filter_agents_at_station()` → `_filter_agents_in_department()`
- `_get_station_slot_occupancy()` → `_get_department_agent_availability()`

Key change in `_find_agent_for_department()`:
```python
def _find_agent_for_department(self, department, capability=None):
    """Find best available agent in a department. Prefer department AI coordinator."""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # First try: department AI coordinator
        cur.execute("""
            SELECT id, name, model, tier FROM agents
            WHERE department = %s AND is_department_ai = true AND status = 'active'
            LIMIT 1
        """, (department,))
        coordinator = cur.fetchone()
        if coordinator:
            return coordinator
        # Second try: any warm agent in department
        cur.execute("""
            SELECT id, name, model, tier FROM agents
            WHERE department = %s AND status = 'active'
            ORDER BY tier DESC LIMIT 1
        """, (department,))
        return cur.fetchone()
```

- [ ] **Step 3: Update dispatch() entry point**

In `dispatch()` method (~line 7702), replace station_code parameter usage with department parameter.

- [ ] **Step 4: Update crew_manifest grouping**

Change `get_crew_manifest()` to group agents by department instead of station.

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat(bridge): department-based dispatch routing — Phase 2.2"
```

---

### Task 2.3: Update Smart Router Escalation

**Files:**
- Modify: `ai_bridge/smart_router.py`

- [ ] **Step 1: Read current escalation logic**

Read `smart_router.py` lines 500-650 for escalation chain.

- [ ] **Step 2: Add floor-aware escalation**

Update escalation to use floor grouping:
```
target department → same-floor departments (alphabetical) → other floors (by deck_number) → fleet → cloud
```

- [ ] **Step 3: Commit**

```bash
git add ai_bridge/smart_router.py
git commit -m "feat(bridge): floor-aware escalation in smart router — Phase 2.3"
```

---

### Task 2.4: Deploy & Test Dispatch

**Rollback plan:** If dispatch fails after restart, revert the three ai_bridge files:
```bash
git checkout HEAD~3 -- ai_bridge/orchestration_engine.py ai_bridge/bridge_dispatcher.py ai_bridge/smart_router.py
docker compose restart archie_platform
```

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Check logs for errors**

```bash
docker logs --tail 50 archie_platform
```

- [ ] **Step 3: Test dispatch via Bridge**

Navigate to http://192.168.1.200:3000 and test a Bridge dispatch. Verify agents are being selected by department.

- [ ] **Step 4: Commit any fixes**

---

## Phase 3: UI Rename — StationOps → DepartmentOps

### Task 3.1: Rename JS/CSS Files

**Files:**
- Rename: `platform_v2/static/js/station-ops.js` → `platform_v2/static/js/department-ops.js`
- Rename: `platform_v2/static/css/station-ops.css` → `platform_v2/static/css/department-ops.css`

- [ ] **Step 1: Copy and rename files**

```bash
cp platform_v2/static/js/station-ops.js platform_v2/static/js/department-ops.js
cp platform_v2/static/css/station-ops.css platform_v2/static/css/department-ops.css
```

- [ ] **Step 2: Find-and-replace class name `StationOps` → `DepartmentOps` in new JS file**

In `department-ops.js`, replace all occurrences of `StationOps` with `DepartmentOps`.

- [ ] **Step 3: Update all template references**

Grep for `station-ops` across all templates and update to `department-ops`:

Files to update (15+):
- `platform_v2/templates/base.html`
- `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`
- `platform_v2/tools/starship/templates/tools/starship/starship.html`
- `platform_v2/templates/tools/archie_chat.html`
- All other templates referencing station-ops.js or station-ops.css

- [ ] **Step 4: Update JS instantiations**

In every file that calls `new StationOps(...)`, change to `new DepartmentOps(...)`.

- [ ] **Step 5: Keep old files as aliases temporarily**

Create thin wrapper files at the old paths that import from the new files (prevents breakage during transition):

`station-ops.js`:
```javascript
// DEPRECATED: Use department-ops.js — this file will be removed in next release
console.warn('station-ops.js is deprecated. Use department-ops.js');
// Alias for backward compat (loaded via regular script tag, not ES module)
var StationOps = DepartmentOps;
```
Note: `department-ops.js` must be loaded BEFORE this file in templates. Better approach: just update all consumers and delete the old file in one pass.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/static/js/department-ops.js platform_v2/static/css/department-ops.css
git add platform_v2/static/js/station-ops.js platform_v2/static/css/station-ops.css
git add platform_v2/templates/
git commit -m "feat(ui): StationOps → DepartmentOps rename — Phase 3.1"
```

---

### Task 3.2: Rename F.O.R.G.E. Module → Repair Bay

**Files:**
- Rename: `platform_v2/tools/dev_pipeline/` (keep path, update display name and blueprint)
- Modify: `platform_v2/module_registry.py`
- Modify: `platform_v2/rbac.py`

- [ ] **Step 1: Update module_registry.py**

Change the F.O.R.G.E. module entry:
- `name` → `"Repair Bay"`
- `description` → `"Self-healing code pipeline<br>Scan • Fix • Test • PR • Review • Deploy"`
- Keep `route="/tools/dev-pipeline"` (URL doesn't change — avoids breaking bookmarks)
- Keep `blueprint_import` as-is

- [ ] **Step 2: Update template title**

In the dev_pipeline template, change the page title from "F.O.R.G.E." to "Repair Bay".

- [ ] **Step 3: Commit**

```bash
git add platform_v2/module_registry.py platform_v2/tools/dev_pipeline/
git commit -m "feat(modules): F.O.R.G.E. module renamed to Repair Bay — Phase 3.2"
```

---

### Task 3.3: Deploy & Test UI

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Browser test — verify DepartmentOps loads on Consciousness, Starbase, Starship**

Navigate to:
- http://192.168.1.200:3000/tools/consciousness
- http://192.168.1.200:3000/tools/starbase-command
- http://192.168.1.200:3000/tools/starship

Verify station panels load correctly with DepartmentOps.

- [ ] **Step 3: Verify Repair Bay module shows correctly in dashboard**

Navigate to http://192.168.1.200:3000 — check that "Repair Bay" appears in the AI Command category.

- [ ] **Step 4: Commit any fixes**

---

## Phase 4: A.R.C.H.I.E. Dots Fix

### Task 4.1: Sweep HTML Templates

**Files:**
- Modify: All HTML templates containing "ARCHIE" without dots in display context

- [ ] **Step 1: Find all unformatted occurrences**

```bash
grep -rn "ARCHIE" platform_v2/templates/ --include="*.html" | grep -v "A\.R\.C\.H\.I\.E\." | grep -v "archie" | grep -v "{{"
```

- [ ] **Step 2: Fix each occurrence**

Replace `ARCHIE` with `A.R.C.H.I.E.` in display text only (not URLs, not Python variables, not Jinja2 variables).

- [ ] **Step 3: Commit**

```bash
git add platform_v2/templates/
git commit -m "fix(branding): A.R.C.H.I.E. dots in all HTML templates — Phase 4.1"
```

---

### Task 4.2: Sweep JS Files

**Files:**
- Modify: All JS files with unformatted acronym display strings

- [ ] **Step 1: Find occurrences**

```bash
grep -rn "'ARCHIE\|\"ARCHIE" platform_v2/static/js/ | grep -v "\.R\.C\."
```

- [ ] **Step 2: Fix display strings only**

- [ ] **Step 3: Commit**

```bash
git add platform_v2/static/js/
git commit -m "fix(branding): A.R.C.H.I.E. dots in JS display strings — Phase 4.2"
```

---

### Task 4.3: Sweep Python Files

**Files:**
- Modify: Python files with unformatted display strings (flash messages, route responses)

- [ ] **Step 1: Find occurrences**

```bash
grep -rn "'ARCHIE\|\"ARCHIE" platform_v2/ ai_bridge/ --include="*.py" | grep -v "\.R\.C\." | grep -v "import\|from\|#"
```

- [ ] **Step 2: Fix display strings only (not variable names)**

- [ ] **Step 3: Commit**

```bash
git add platform_v2/ ai_bridge/
git commit -m "fix(branding): A.R.C.H.I.E. dots in Python display strings — Phase 4.3"
```

---

### Task 4.4: Sweep Docs & Config

**Files:**
- Modify: `CLAUDE.md`, `MEMORY.md`, `.claude/rules/*.md`, `README.md`, `CONTRIBUTING.md`

- [ ] **Step 1: Find and fix occurrences in docs**

- [ ] **Step 2: Update knowledge base via SQL**

```sql
UPDATE knowledge_base SET title = REPLACE(title, 'ARCHIE', 'A.R.C.H.I.E.')
WHERE title LIKE '%ARCHIE%' AND title NOT LIKE '%A.R.C.H.I.E.%';

UPDATE knowledge_base SET content = REPLACE(content, 'ARCHIE', 'A.R.C.H.I.E.')
WHERE content LIKE '%ARCHIE%' AND content NOT LIKE '%A.R.C.H.I.E.%'
AND content NOT LIKE '%archie%' -- avoid mixed-case code references
AND knowledge_type NOT IN ('code_snippet', 'github_file'); -- never touch code entries
```

**WARNING:** Run this as a SELECT first to preview changes before UPDATE.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md MEMORY.md .claude/rules/ README.md CONTRIBUTING.md
git commit -m "fix(branding): A.R.C.H.I.E. dots in docs and knowledge base — Phase 4.4"
```

---

## Phase 5: Website & Directory Updates

### Task 5.1: Update Directory Module — AI Badges & Separate Counts

**Files:**
- Modify: `platform_v2/tools/directory/routes.py`
- Modify: `platform_v2/tools/directory/templates/directory.html`

- [ ] **Step 1: Read current directory routes and template**

Read `platform_v2/tools/directory/routes.py` and the directory template.

- [ ] **Step 2: Add AI agent filtering to API**

In the `/api/directory` endpoint, add query param `agent_type` (all, human, ai):
```python
agent_type = request.args.get('agent_type', 'all')
if agent_type == 'ai':
    query += " AND is_department_ai = true"
elif agent_type == 'human':
    query += " AND (is_department_ai = false OR is_department_ai IS NULL)"
```

- [ ] **Step 3: Add separate counts to API response**

```python
cur.execute("SELECT COUNT(*) FROM agents WHERE is_department_ai = true AND status = 'active'")
ai_count = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM agents WHERE (is_department_ai = false OR is_department_ai IS NULL) AND status = 'active'")
human_count = cur.fetchone()[0]
```

Return `{"ai_count": ai_count, "human_count": human_count, "agents": [...]}`.

- [ ] **Step 4: Update template with AI badges**

Add an AI badge icon/label next to department AI agents. Add filter buttons: All | Staff | AI Directors.
Show counts: "135 Staff + 16 AI Directors".

- [ ] **Step 5: Add full profiles for AI agents**

Ensure backstory, email ({name}@kytranempowerment.com), phone extension, and specializations display in the agent profile modal.

- [ ] **Step 6: Deploy & test**

```bash
docker compose restart archie_platform
```

Navigate to http://192.168.1.200:3000/tools/directory — verify AI badges, separate counts, profile modals.

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/directory/
git commit -m "feat(directory): AI agent badges, separate counts, department AI profiles — Phase 5.1"
```

---

### Task 5.2: Update Public Website

**Files:**
- Modify: `repos/website/kytranempowerment-site/` (multiple files)

- [ ] **Step 1: Read current website structure**

Read the website directory listing and key files to understand how departments/directory are rendered.

- [ ] **Step 2: Update /directory page**

- Show 16 departments with floor grouping
- AI agents with distinct AI designation
- Separate counts: "X Staff + 16 AI Directors"
- Full profiles for AI agents

- [ ] **Step 3: Update /competitors page**

Reflect new organizational structure.

- [ ] **Step 4: Add Claude Code CLI promotion section**

New section on the website promoting the A.R.C.H.I.E. Code CLI:
- Link to public repo: github.com/KytranKatarn/archie-code
- Link to PyPI: pypi.org/project/archie-engine
- Installation instructions (curl one-liner)
- Feature highlights
- Screenshots/demo if available

- [ ] **Step 5: Add Lessons Learned / Tips & Tricks section**

New section with knowledge gathered from our development experience:
- Claude Code tips and tricks
- CLAUDE.md best practices and `.md` file conventions
- Context engineering patterns
- Skill development lessons
- Agent coordination patterns
- Source from: knowledge_base mistake_learned entries, feedback memories, session learnings

- [ ] **Step 6: Update branding across site**

Ensure A.R.C.H.I.E. with dots everywhere in display text.

- [ ] **Step 5: Commit**

```bash
git add repos/website/kytranempowerment-site/
git commit -m "feat(website): department structure, AI agents, dots fix — Phase 5.2"
```

---

### Task 5.3: Restore Translation System

**Files:**
- Modify: `repos/website/kytranempowerment-site/` (add i18n integration)
- Reference: `platform_v2/static/js/archie-i18n.js` (existing implementation)

- [ ] **Step 1: Read archie-i18n.js to understand the API**

Read `platform_v2/static/js/archie-i18n.js` for the i18n interface.

- [ ] **Step 2: Integrate i18n into the public website**

- Add `archie-i18n.js` (or a public-facing version) to the website
- Add `data-i18n` attributes to all static text elements
- Add language selector (8 languages: en, fr, es, de, ja, zh, ar, he)
- RTL support for ar, he
- All translation requests route through Bridge (ADR-013)

- [ ] **Step 3: Test each language**

- [ ] **Step 4: Commit**

```bash
git add repos/website/kytranempowerment-site/
git commit -m "feat(website): restore translation AI system — 8 languages + RTL — Phase 5.3"
```

---

## Phase 6: Code Health Verification

### Task 6.1: Run Code Health Scan

- [ ] **Step 1: Run code health check on all modified categories**

Use the Consciousness module code health scanner or Dev Pipeline scan to verify:
- Employee Directory category — all green
- AI Bridge — no broken imports or references
- Starbase Command — department routing works
- Repair Bay (renamed) — no broken references
- Website — no 404s

- [ ] **Step 2: Run full agent benchmark**

```bash
docker exec -it archie_database psql -U archie -d archie -c "
SELECT department, COUNT(*) as total,
       COUNT(*) FILTER (WHERE is_department_ai = true) as ai_agents,
       COUNT(*) FILTER (WHERE is_department_ai = false OR is_department_ai IS NULL) as human_agents
FROM agents WHERE status = 'active'
GROUP BY department ORDER BY department;
"
```

Verify: every department has exactly 1 AI coordinator + multiple human agents.

- [ ] **Step 3: Verify Telegram alerts use department names**

Search Telegram alert code for station references and update to department names.

- [ ] **Step 4: Log completion in Dev HQ**

```
mcp complete_task — all rebrand tasks
mcp log_decision — department model adopted (Decision #XXX)
mcp update_project_understanding — Project #191
```

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: A.R.C.H.I.E. Rebrand complete — departments, AI agents, dots fix, website"
```

---

## Future Work (Noted, Not Planned)

| Item | Create As |
|------|-----------|
| PixelFactory floor visualization | New project + tasks |
| Consciousness + Repair Bay + Dev Pipeline consolidation | New project |
| Custom LLM training per agent | Research project |
| Custom branded agent skills | Future phase of Skills Lab |
