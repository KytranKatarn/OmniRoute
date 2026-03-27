# Workstream 1: Station → Department Hard Cutover

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the 10-station routing model entirely. All agent selection, dispatch, and tracking uses the 16-department model. No dual model.

**Architecture:** DB migration drops station infrastructure, adds floor column. Bridge dispatcher rewired to use CAPABILITY_DEPARTMENT_MAP as sole routing. Agent scoring by department. All station references in ai_bridge/ removed or replaced.

**Tech Stack:** PostgreSQL migrations, Python (bridge_dispatcher.py, smart_router.py, orchestration_engine.py, agent_loop.py)

---

## Current state (verified 2026-03-27)

- `agents` table already has `department` column with all 16 values populated
- `agents` table has `is_department_ai` flag for AI Directors
- `station_assignments` table exists with `station_id`, `agent_id`, `is_active`
- `bridge_stations` table exists with station definitions
- `CAPABILITY_DEPARTMENT_MAP` already exists in bridge_dispatcher.py as primary routing
- `CAPABILITY_STATION_MAP` still exists as fallback
- Smart router `_resolve_department()` already prefers department, falls back to station

## 16 Valid departments

```
Executive Office, Operations & Infrastructure, Logistics & Supply Chain,
Finance & Accounting, Engineering & Technology, Security & Compliance,
Research & Development, Creative & Design, Marketing & Communications,
Documentation & Knowledge, Customer Success & Support, Human Resources & Culture,
Medical & Wellness, Legal & Regulatory, Diplomatic & External Relations,
Analytics & Intelligence
```

## 5 Floors (department → floor mapping)

```python
DEPARTMENT_FLOOR_MAP = {
    "Executive Office": "BRIDGE",
    "Operations & Infrastructure": "OPERATIONS",
    "Logistics & Supply Chain": "OPERATIONS",
    "Finance & Accounting": "OPERATIONS",
    "Engineering & Technology": "ENGINEERING",
    "Security & Compliance": "ENGINEERING",
    "Research & Development": "ENGINEERING",
    "Creative & Design": "CREATIVE",
    "Marketing & Communications": "CREATIVE",
    "Documentation & Knowledge": "CREATIVE",
    "Customer Success & Support": "SERVICES",
    "Human Resources & Culture": "SERVICES",
    "Medical & Wellness": "SERVICES",
    "Legal & Regulatory": "SERVICES",
    "Diplomatic & External Relations": "SERVICES",
    "Analytics & Intelligence": "SERVICES",
}
```

---

### Task 1: Database migration — add floor, enforce department, drop station tables

**Files:**
- Create: `database/migrations/101_department_cutover.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- Migration 101: Station → Department Hard Cutover
-- Adds floor column, enforces department constraint, drops station infrastructure

BEGIN;

-- 1. Add floor column to agents (derived from department)
ALTER TABLE agents ADD COLUMN IF NOT EXISTS floor VARCHAR(20);

-- 2. Backfill floor from department
UPDATE agents SET floor = CASE
    WHEN department = 'Executive Office' THEN 'BRIDGE'
    WHEN department IN ('Operations & Infrastructure', 'Logistics & Supply Chain', 'Finance & Accounting') THEN 'OPERATIONS'
    WHEN department IN ('Engineering & Technology', 'Security & Compliance', 'Research & Development') THEN 'ENGINEERING'
    WHEN department IN ('Creative & Design', 'Marketing & Communications', 'Documentation & Knowledge') THEN 'CREATIVE'
    WHEN department IN ('Customer Success & Support', 'Human Resources & Culture', 'Medical & Wellness', 'Legal & Regulatory', 'Diplomatic & External Relations', 'Analytics & Intelligence') THEN 'SERVICES'
    ELSE 'SERVICES'
END
WHERE floor IS NULL;

-- 3. Add constraints
ALTER TABLE agents ALTER COLUMN department SET NOT NULL;
ALTER TABLE agents ALTER COLUMN floor SET NOT NULL;

ALTER TABLE agents ADD CONSTRAINT chk_agents_department CHECK (
    department IN (
        'Executive Office', 'Operations & Infrastructure', 'Logistics & Supply Chain',
        'Finance & Accounting', 'Engineering & Technology', 'Security & Compliance',
        'Research & Development', 'Creative & Design', 'Marketing & Communications',
        'Documentation & Knowledge', 'Customer Success & Support', 'Human Resources & Culture',
        'Medical & Wellness', 'Legal & Regulatory', 'Diplomatic & External Relations',
        'Analytics & Intelligence'
    )
);

ALTER TABLE agents ADD CONSTRAINT chk_agents_floor CHECK (
    floor IN ('BRIDGE', 'OPERATIONS', 'ENGINEERING', 'CREATIVE', 'SERVICES')
);

-- 4. Drop station infrastructure
-- First drop foreign keys pointing to station_assignments
ALTER TABLE agents DROP COLUMN IF EXISTS station_code;

-- Drop station_assignments table
DROP TABLE IF EXISTS station_assignments CASCADE;

-- Keep bridge_stations as reference/history but remove active use
-- (Don't drop — other tables may reference it. Mark deprecated.)
COMMENT ON TABLE bridge_stations IS 'DEPRECATED: replaced by agents.department + agents.floor. Kept for historical reference.';

COMMIT;
```

- [ ] **Step 2: Run migration**

```bash
docker exec archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/migrations/101_department_cutover.sql
```

Expected: `ALTER TABLE`, `UPDATE`, `DROP TABLE` with no errors.

- [ ] **Step 3: Verify migration**

```bash
docker exec archie_database psql -U archie -d archie -c "
  SELECT department, floor, count(*) FROM agents GROUP BY department, floor ORDER BY floor, department;
"
```

Expected: 16 departments across 5 floors, all agents accounted for.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/101_department_cutover.sql
git commit -m "feat(db): migration 101 — department cutover, add floor, drop station_assignments"
```

---

### Task 2: Bridge dispatcher — remove station routing, department-only

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py`

This is the largest task. The dispatcher is 8000+ lines. Changes are surgical — remove station maps and replace station_code params with department.

- [ ] **Step 1: Add DEPARTMENT_FLOOR_MAP constant**

Near the top of bridge_dispatcher.py, after CAPABILITY_DEPARTMENT_MAP, add:

```python
DEPARTMENT_FLOOR_MAP = {
    "Executive Office": "BRIDGE",
    "Operations & Infrastructure": "OPERATIONS",
    "Logistics & Supply Chain": "OPERATIONS",
    "Finance & Accounting": "OPERATIONS",
    "Engineering & Technology": "ENGINEERING",
    "Security & Compliance": "ENGINEERING",
    "Research & Development": "ENGINEERING",
    "Creative & Design": "CREATIVE",
    "Marketing & Communications": "CREATIVE",
    "Documentation & Knowledge": "CREATIVE",
    "Customer Success & Support": "SERVICES",
    "Human Resources & Culture": "SERVICES",
    "Medical & Wellness": "SERVICES",
    "Legal & Regulatory": "SERVICES",
    "Diplomatic & External Relations": "SERVICES",
    "Analytics & Intelligence": "SERVICES",
}

FLOOR_DEPARTMENTS = {}
for dept, flr in DEPARTMENT_FLOOR_MAP.items():
    FLOOR_DEPARTMENTS.setdefault(flr, []).append(dept)
```

- [ ] **Step 2: Remove CAPABILITY_STATION_MAP**

Delete the entire `CAPABILITY_STATION_MAP` dict. Search for all references to it and replace with `CAPABILITY_DEPARTMENT_MAP`.

- [ ] **Step 3: Remove STATION_TO_DEPARTMENT and DEPARTMENT_TO_STATION**

Delete both dicts. Replace any usage:
- `STATION_TO_DEPARTMENT.get(station_code)` → use `agents.department` directly
- `DEPARTMENT_TO_STATION.get(department)` → use `DEPARTMENT_FLOOR_MAP.get(department)` if floor needed

- [ ] **Step 4: Rewrite `_select_agent()` to use department**

Change the method signature from:
```python
def _select_agent(self, capability, station_code, ...)
```
to:
```python
def _select_agent(self, capability, department, ...)
```

Update the agent query inside from:
```python
WHERE station_code = %s OR %s = ANY(station_codes)
```
to:
```python
WHERE department = %s
```

- [ ] **Step 5: Rewrite `_find_fleet_agent()` to use department**

Change the query from:
```python
WHERE station_code = ANY(na.station_codes)
```
to:
```python
WHERE na.department = %s
```

- [ ] **Step 6: Update `request_work()` internal routing**

Where `request_work()` resolves capability → station → agent, change to:
```python
department = CAPABILITY_DEPARTMENT_MAP.get(capability)
if not department:
    department = "Engineering & Technology"  # safe default
agent = self._select_agent(capability, department, ...)
```

- [ ] **Step 7: Update escalation chain**

Replace station-based escalation:
```
home station → capability → cross-station → fleet → cloud
```
with department-based:
```python
# 1. Home department
agent = self._select_agent(capability, department)
if not agent:
    # 2. Same-floor departments
    floor = DEPARTMENT_FLOOR_MAP.get(department)
    for sibling_dept in FLOOR_DEPARTMENTS.get(floor, []):
        if sibling_dept != department:
            agent = self._select_agent(capability, sibling_dept)
            if agent:
                break
if not agent:
    # 3. Cross-floor departments (all departments)
    for dept in CAPABILITY_DEPARTMENT_MAP.values():
        if dept != department and DEPARTMENT_FLOOR_MAP.get(dept) != floor:
            agent = self._select_agent(capability, dept)
            if agent:
                break
if not agent:
    # 4. Fleet nodes
    agent = self._find_fleet_agent(department, capability)
if not agent:
    # 5. Cloud escalation
    ...
```

- [ ] **Step 8: Remove all remaining station_code references**

Search bridge_dispatcher.py for `station_code`, `station_codes`, `CAPABILITY_STATION_MAP`, `STATION_TO_DEPARTMENT`. Remove or replace every occurrence.

- [ ] **Step 9: Verify file parses**

```bash
python3 -c "import ast; ast.parse(open('ai_bridge/bridge_dispatcher.py').read()); print('OK')"
```

- [ ] **Step 10: Commit**

```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat(dispatch): remove station routing, department-only dispatch with floor escalation"
```

---

### Task 3: Smart router — remove station fallback

**Files:**
- Modify: `ai_bridge/smart_router.py`

- [ ] **Step 1: Find and remove station fallback in `_resolve_department()`**

The method currently falls back to `CAPABILITY_STATION_MAP` when department lookup misses. Remove that fallback — if `CAPABILITY_DEPARTMENT_MAP` doesn't have the capability, default to "Engineering & Technology".

- [ ] **Step 2: Remove any station-based capacity logic**

Search for `station_code`, `station_capacity`, `station_limits` in smart_router.py. Remove or replace with department equivalents.

- [ ] **Step 3: Remove station imports**

Remove any imports of `CAPABILITY_STATION_MAP`, `STATION_TO_DEPARTMENT`, etc.

- [ ] **Step 4: Verify and commit**

```bash
python3 -c "import ast; ast.parse(open('ai_bridge/smart_router.py').read()); print('OK')"
git add ai_bridge/smart_router.py
git commit -m "feat(router): remove station fallback, department-only resolution"
```

---

### Task 4: Orchestration engine — station → department references

**Files:**
- Modify: `ai_bridge/orchestration_engine.py`

- [ ] **Step 1: Search for station references**

```bash
grep -n "station" ai_bridge/orchestration_engine.py
```

- [ ] **Step 2: Replace each station reference with department equivalent**

Typical replacements:
- `station_code` → `department`
- `station` in log messages → `department`
- Any station-based routing logic → department-based

- [ ] **Step 3: Verify and commit**

```bash
python3 -c "import ast; ast.parse(open('ai_bridge/orchestration_engine.py').read()); print('OK')"
git add ai_bridge/orchestration_engine.py
git commit -m "feat(orchestration): replace station references with department"
```

---

### Task 5: Agent loop — station → department in all jobs

**Files:**
- Modify: `ai_bridge/agent_loop.py`

- [ ] **Step 1: Search for all station references**

```bash
grep -n "station" ai_bridge/agent_loop.py | grep -v "^#" | head -40
```

- [ ] **Step 2: Update job functions that reference stations**

Key changes:
- Fleet health check: query `agents.department` not `station_assignments`
- Agent assignment logic: use department
- Any station-based grouping in job functions → department-based
- Log messages: "station" → "department"

- [ ] **Step 3: Add JOB_DEPARTMENT_MAP constant**

At the top of agent_loop.py or in a shared constants file:

```python
JOB_DEPARTMENT_MAP = {
    "fleet_health_check": "Operations & Infrastructure",
    "model_state_save": "Operations & Infrastructure",
    "heartbeat_monitor": "Operations & Infrastructure",
    "automated_module_audit": "Engineering & Technology",
    "pattern_compliance_check": "Engineering & Technology",
    "proactive_scan": "Engineering & Technology",
    "compliance_scan": "Security & Compliance",
    "dns_monitoring": "Security & Compliance",
    "ssl_check": "Security & Compliance",
    "knowledge_dedup": "Research & Development",
    "conversation_indexing": "Research & Development",
    "consciousness_analysis": "Research & Development",
    "embedding_batch": "Research & Development",
    "git_commit_tracking": "Research & Development",
    "github_skill_analysis": "Documentation & Knowledge",
    "skill_sync": "Documentation & Knowledge",
    "competitor_scanning": "Documentation & Knowledge",
    "repo_indexing": "Documentation & Knowledge",
    "telegram_notifications": "Marketing & Communications",
    "daily_digest": "Marketing & Communications",
    "welfare_recovery": "Human Resources & Culture",
    "training_tick": "Human Resources & Culture",
    "shift_management": "Human Resources & Culture",
    "approval_queue": "Executive Office",
    "escalation_management": "Executive Office",
    "metrics_snapshot": "Analytics & Intelligence",
    "ethics_monitoring": "Security & Compliance",
}
```

- [ ] **Step 4: Update `_log_cycle()` to include department**

If `agent_loop_cycles` table has a department column (from migration), populate it:

```python
def _log_cycle(self, job_name, ...):
    department = JOB_DEPARTMENT_MAP.get(job_name, "Operations & Infrastructure")
    # ... existing logic plus department in INSERT
```

Note: If `agent_loop_cycles` doesn't have a `department` column yet, add it in migration 101 or a follow-up migration:

```sql
ALTER TABLE agent_loop_cycles ADD COLUMN IF NOT EXISTS department VARCHAR(50);
```

- [ ] **Step 5: Verify and commit**

```bash
python3 -c "import ast; ast.parse(open('ai_bridge/agent_loop.py').read()); print('OK')"
git add ai_bridge/agent_loop.py
git commit -m "feat(agent-loop): department attribution for all jobs, remove station references"
```

---

### Task 6: Starbase command — remove station_code from queries

**Files:**
- Modify: `platform_v2/tools/starbase_command/station_routes.py` (will be removed in WS6, but must not break now)
- Modify: `platform_v2/tools/starbase_command/crew_routes.py`
- Modify: `platform_v2/tools/starbase_command/agent_routes.py`
- Modify: Any other starbase files querying station_assignments

- [ ] **Step 1: Search starbase for station_assignments queries**

```bash
grep -rn "station_assignments\|station_code\|station_codes" platform_v2/tools/starbase_command/
```

- [ ] **Step 2: Replace station_assignments JOINs with agents.department queries**

Anywhere Starbase JOINs `station_assignments` to get agent-station mapping, replace with direct `agents.department` and `agents.floor` queries. The table is gone.

- [ ] **Step 3: Update station_routes.py to use department data**

Station panels still render in WS1 (removed in WS6), but they now query by department groupings instead of station_assignments:

```python
# Old: SELECT * FROM station_assignments sa JOIN agents a ON sa.agent_id = a.id WHERE sa.station_id = %s
# New: SELECT * FROM agents WHERE department = %s
```

Map the 10 old stations to departments for backward compat until WS6 removes them:

```python
LEGACY_STATION_DEPARTMENT = {
    "COMMAND": ["Executive Office"],
    "ANALYTICS": ["Analytics & Intelligence", "Finance & Accounting"],
    "CREATIVE": ["Creative & Design", "Marketing & Communications", "Documentation & Knowledge"],
    "ENGINEERING": ["Engineering & Technology", "Security & Compliance", "Research & Development"],
    "COMMUNICATIONS": ["Marketing & Communications"],
    "RESEARCH": ["Research & Development"],
    "SECURITY": ["Security & Compliance"],
    "LOGISTICS": ["Logistics & Supply Chain"],
    "DIPLOMATIC": ["Diplomatic & External Relations"],
    "OPERATIONS": ["Operations & Infrastructure"],
}
```

- [ ] **Step 4: Verify platform starts**

```bash
docker compose restart archie_platform
docker logs archie_platform 2>&1 | tail -20
```

Expected: No import errors, no station_assignments query failures.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/starbase_command/
git commit -m "feat(starbase): replace station_assignments queries with agents.department"
```

---

### Task 7: Other consumers — grep and fix remaining station references

**Files:**
- Various across platform_v2/ and ai_bridge/

- [ ] **Step 1: Full codebase grep for remaining station references**

```bash
grep -rn "station_assignments\|station_code\|station_codes\|CAPABILITY_STATION_MAP" \
    platform_v2/ ai_bridge/ --include="*.py" | grep -v __pycache__ | grep -v migrations/
```

- [ ] **Step 2: Fix each remaining reference**

For each file found:
- If it queries `station_assignments`: replace with `agents.department` query
- If it uses `station_code`: replace with `department`
- If it uses `station_codes` (array): replace with single `department` value
- If it imports station maps: remove the import

- [ ] **Step 3: Verify full platform starts cleanly**

```bash
docker compose restart archie_platform
# Wait 10s for startup
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from ai_bridge.bridge_dispatcher import get_dispatcher
d = get_dispatcher()
print('Dispatcher OK, department routing active')
"
```

- [ ] **Step 4: Test a Bridge dispatch end-to-end**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from ai_bridge.bridge_dispatcher import get_dispatcher
d = get_dispatcher()
result = d.request_work(
    capability='code_review',
    prompt='Test dispatch — confirm department routing works. Reply with: DEPARTMENT_ROUTING_OK',
    module_id='test_cutover',
)
print(f'Agent: {result.agent_name}')
print(f'Response: {result.response[:100]}')
"
```

Expected: Agent from Engineering & Technology department responds.

- [ ] **Step 5: Commit**

```bash
git add -A  # careful — review staged files
git commit -m "feat(cutover): remove all remaining station references across platform"
```

---

### Task 8: Verify and deploy

- [ ] **Step 1: Run full platform health check**

```bash
docker compose restart archie_platform
# Check logs for errors
docker logs archie_platform 2>&1 | grep -i "error\|exception\|traceback" | head -20
```

- [ ] **Step 2: Verify agent routing via MCP**

```bash
# Call session_briefing to confirm MCP + dispatch works
```

Use `mcp__archie__get_quick_summary` and `mcp__archie__list_agents` to verify agents show department data.

- [ ] **Step 3: Browser test Starbase at http://192.168.1.200:3000/tools/starbase-command**

Verify station panels still render (using legacy mapping) without errors.

- [ ] **Step 4: Log decision and complete tasks**

```python
mcp__archie__log_decision(
    title="Station → Department hard cutover complete",
    decision="Removed station_assignments table, station_code columns, CAPABILITY_STATION_MAP. All routing uses CAPABILITY_DEPARTMENT_MAP + agents.department. Floor derived from department.",
    context="Dual station/department model caused routing bottlenecks and code confusion",
    consequences="All new code uses department only. Starbase station panels use legacy mapping until WS6.",
    project_id=199,
)
```

- [ ] **Step 5: Final commit and push**

```bash
git push origin main
```
