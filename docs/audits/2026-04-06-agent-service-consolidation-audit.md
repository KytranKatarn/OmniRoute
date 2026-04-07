# Agent Service Consolidation Audit

**Date**: 2026-04-06
**Auditor**: Claude Opus 4.6 (automated)
**Scope**: All direct SQL on `agents` table outside `agent_service.py`
**Status**: FINDINGS REPORTED

---

## 1. Agent Service Public API (`platform_v2/services/agent_service.py`)

The service declares itself as "THE single authority for all agent operations" (line 1).

### CRUD

| Function | Signature | Description |
|----------|-----------|-------------|
| `get_agent` | `(agent_id)` | Get full agent profile by ID (joins emotional state). Returns dict or None. |
| `get_agent_by_name` | `(name)` | Get agent by code name. Returns dict or None. |
| `list_agents` | `(department, floor, shift_state, skill, search, is_department_ai, limit=200)` | List agents with optional filters. Returns list of dicts. |
| `create_agent` | `(name, display_name, department, model, **kwargs)` | Create agent + initial emotional state. Validates department/shift_state. Returns agent_id. |
| `update_agent` | `(agent_id, **fields)` | Generic field update. Auto-derives floor from department. Validates shift_state. Returns bool. |
| `delete_agent` | `(agent_id, hard=False)` | Soft-delete (default) sets status=inactive, shift_state=off_duty. Hard-delete removes row. |

### Shift Lifecycle

| Function | Signature | Description |
|----------|-----------|-------------|
| `activate` | `(agent_id)` | Set shift_state to 'active'. |
| `barracks` | `(agent_id)` | Set shift_state to 'barracked'. |
| `wind_down` | `(agent_id)` | Set shift_state to 'winding_down'. |
| `cooldown` | `(agent_id)` | Set shift_state to 'cooldown'. |
| `deploy_to_node` | `(agent_id, node_id)` | Set shift_state to 'deployed', create/reactivate node_agents row. |
| `return_from_node` | `(agent_id)` | Set shift_state to 'barracked', deactivate node_agents row. |

### Skills

| Function | Signature | Description |
|----------|-----------|-------------|
| `get_skills` | `(agent_id)` | Get agent skills with levels. Returns list of dicts. |
| `add_skill` | `(agent_id, skill_name, level=1, category="general")` | Add or upsert a skill. |
| `update_skill_from_benchmark` | `(agent_id, skill_name, score)` | Auto-level 1-5 from benchmark score (0.0-1.0). |
| `match_capability` | `(capability)` | Find agents with matching skill, ranked by level. |

### Welfare

| Function | Signature | Description |
|----------|-----------|-------------|
| `get_welfare` | `(agent_id)` | Get current emotional state (stress, energy, mood). |
| `update_welfare` | `(agent_id, stress, energy, mood, mood_intensity)` | Update welfare metrics (clamped 0.0-1.0). |
| `check_welfare_threshold` | `(agent_id)` | Returns (ok: bool, reason: str). Fails if stress >= 0.8 or energy <= 0.2. |
| `recover_idle` | `(agent_id, energy_boost=0.2, stress_reduction=0.15)` | Boost idle agent welfare. |

### Org Chart & Performance

| Function | Signature | Description |
|----------|-----------|-------------|
| `get_org_chart` | `()` | Full org chart: floors -> departments -> agents. |
| `get_department_summary` | `()` | Per-department counts and health stats. |
| `get_performance` | `(agent_id, period_days=7)` | Jobs completed/failed, avg response time, success rate. |

### Hardware & Deployment

| Function | Signature | Description |
|----------|-----------|-------------|
| `get_agents_for_hardware` | `(gpu_vram_gb, ram_gb)` | Filter active agents by hardware compatibility. |
| `recommend_node_deployment` | `(node_id)` | Recommend agents for a node based on its hardware. |

### Identity & Portraits

| Function | Signature | Description |
|----------|-----------|-------------|
| `get_identity` | `(agent_id)` | Get identity details (bio, gender, ethnicity, appearance, portrait_prompt). |
| `update_identity` | `(agent_id, **fields)` | Update identity fields (allowlisted: bio, gender, ethnicity, age_range, appearance_notes, portrait_prompt, email). |
| `get_portraits` | `(agent_id)` | Get all portraits for an agent. |
| `add_portrait` | `(agent_id, prompt, style, negative_prompt)` | Add portrait + trigger generation via Media Studio pipeline. |
| `set_primary_portrait` | `(agent_id, portrait_id)` | Set primary portrait (unsets existing). |

**Total public functions: 28**

---

## 2. Backdoor SQL Findings (Outside agent_service.py)

### HIGH Risk (shift_state, status, department, create, delete)

| # | File | Line | Operation | What It Does | Risk |
|---|------|------|-----------|--------------|------|
| H1 | `ai_bridge/agent_management_api.py` | 180 | `INSERT INTO agents` | Full agent creation (name, type_id, tier, model, budget, etc.) | **HIGH** — Parallel create path, bypasses validation, no emotional state init |
| H2 | `ai_bridge/agent_management_api.py` | 302 | `UPDATE agents SET {dynamic}` | Generic field update with dynamic SET clauses | **HIGH** — Unrestricted field update, no department/shift_state validation |
| H3 | `ai_bridge/agent_management_api.py` | 345 | `UPDATE agents SET status = 'inactive'` | Soft-delete agent | **HIGH** — Bypasses agent_service.delete_agent soft-delete |
| H4 | `ai_bridge/agent_management_api.py` | 347 | `DELETE FROM agents` | Hard-delete agent | **HIGH** — Bypasses agent_service, no logging |
| H5 | `ai_bridge/orchestration_engine.py` | 1832 | `INSERT INTO agents` | Creates agent during orchestration | **HIGH** — No department validation, no emotional state init |
| H6 | `ai_bridge/orchestration_engine.py` | 1931 | `UPDATE agents SET status = 'inactive'` | Deactivates agent | **HIGH** — Bypasses agent_service soft-delete |
| H7 | `ai_bridge/orchestration_engine.py` | 2000 | `UPDATE agents SET department = %s` | Moves agent between departments | **HIGH** — No floor auto-derivation, no department validation |
| H8 | `ai_bridge/bridge_dispatcher.py` | 1128 | `UPDATE agents SET shift_state = %s` | Changes shift state during dispatch | **HIGH** — No shift_state validation against VALID_SHIFT_STATES |
| H9 | `ai_bridge/bridge_dispatcher.py` | 3575 | `INSERT INTO agents` | Creates agent (fleet contractor spawn) | **HIGH** — No department validation, no emotional state init |
| H10 | `ai_bridge/bridge_dispatcher.py` | 7078 | `UPDATE agents SET shift_state = 'barracked'` | Bulk return agents when node goes offline | **HIGH** — Bypasses return_from_node (does not deactivate node_agents) |
| H11 | `ai_bridge/bridge_dispatcher.py` | 7145 | `UPDATE agents SET shift_state = 'deployed'` | Deploy agent to node | **HIGH** — Bypasses deploy_to_node (no node_agents row creation) |
| H12 | `platform_v2/tools/starbase/provider_routes.py` | 500 | `UPDATE agents SET department = %s` | Reassign agent department | **HIGH** — No floor auto-derivation |
| H13 | `platform_v2/tools/team_management/routes.py` | 7704 | `UPDATE agents SET status = %s` | Change contract worker status | **HIGH** — Status mutation outside service |
| H14 | `platform_v2/tools/team_management/routes.py` | 8864 | `INSERT INTO agents` | Create agent (contract worker onboarding) | **HIGH** — Parallel create path, no emotional state init |
| H15 | `platform_v2/tools/consciousness/routes.py` | 5576 | `UPDATE agents SET name = %s` | Rename agent code name | **HIGH** — Name is used as FK key in bridge_jobs, could break references |
| H16 | `platform_v2/services/fleet_service.py` | 459 | `UPDATE agents SET shift_state = 'barracked'` | Return agents on node recall | **HIGH** — Bypasses return_from_node |
| H17 | `platform_v2/tools/starship/node_routes.py` | 963 | `UPDATE agents SET shift_state = 'barracked'` | Return agents on node disconnect | **HIGH** — Bypasses return_from_node |

### MEDIUM Risk (counters, metadata, computed fields)

| # | File | Line | Operation | What It Does | Risk |
|---|------|------|-----------|--------------|------|
| M1 | `ai_bridge/smart_router.py` | 695 | `UPDATE agents SET total_tasks_this_month, opus_usage` | Increment task/usage counters after routing | **MEDIUM** — Counter drift if service adds its own tracking |
| M2 | `ai_bridge/bridge_dispatcher.py` | 2498 | `UPDATE agents SET total_tasks_completed, success_rate` | Update performance stats after job completion | **MEDIUM** — Computed field update, could conflict with get_performance() |
| M3 | `platform_v2/services/agent_module_awareness.py` | 58 | `UPDATE agents SET metadata = ... \|\| %s` | Append module awareness metadata (JSONB merge) | **MEDIUM** — Metadata merge, low conflict risk but bypasses update_agent |

### LOW Risk (display fields)

| # | File | Line | Operation | What It Does | Risk |
|---|------|------|-----------|--------------|------|
| L1 | `platform_v2/tools/team_management/routes.py` | 7379 | `UPDATE agents SET avatar_url` | Set avatar after portrait generation | **LOW** — Display field only |
| L2 | `platform_v2/tools/team_management/routes.py` | 7621 | `UPDATE agents SET api_key_configured = TRUE` | Mark API key as configured | **LOW** — Boolean flag |
| L3 | `platform_v2/tools/team_management/routes.py` | 7774 | `UPDATE agents SET api_key_configured = %s` | Update API key availability check | **LOW** — Boolean flag |
| L4 | `platform_v2/tools/media_studio/services/portrait_service.py` | 254 | `UPDATE agents SET avatar_url` | Set avatar after portrait generation | **LOW** — Display field, but duplicates agent_service.update_agent |
| L5 | `platform_v2/tools/media_studio/services/tts_service.py` | 233 | `UPDATE agents SET voice_sample` | Set voice sample path | **LOW** — Display/media field |

---

## 3. Summary

| Risk Level | Count | Description |
|------------|-------|-------------|
| **HIGH** | 17 | Shift state, status, department, create, delete, rename |
| **MEDIUM** | 3 | Counters, metadata |
| **LOW** | 5 | Display fields (avatar, api_key_configured, voice_sample) |
| **TOTAL** | **25** | Backdoor SQL statements bypassing agent_service.py |

### Worst Offenders (by file)

| File | HIGH | MED | LOW | Total |
|------|------|-----|-----|-------|
| `ai_bridge/bridge_dispatcher.py` | 4 | 1 | 0 | 5 |
| `ai_bridge/agent_management_api.py` | 4 | 0 | 0 | 4 |
| `platform_v2/tools/team_management/routes.py` | 2 | 0 | 3 | 5 |
| `ai_bridge/orchestration_engine.py` | 3 | 0 | 0 | 3 |
| `ai_bridge/smart_router.py` | 0 | 1 | 0 | 1 |
| `platform_v2/tools/starbase/provider_routes.py` | 1 | 0 | 0 | 1 |
| `platform_v2/tools/consciousness/routes.py` | 1 | 0 | 0 | 1 |
| `platform_v2/services/fleet_service.py` | 1 | 0 | 0 | 1 |
| `platform_v2/services/agent_module_awareness.py` | 0 | 1 | 0 | 1 |
| `platform_v2/tools/starship/node_routes.py` | 1 | 0 | 0 | 1 |
| `platform_v2/tools/media_studio/services/portrait_service.py` | 0 | 0 | 1 | 1 |
| `platform_v2/tools/media_studio/services/tts_service.py` | 0 | 0 | 1 | 1 |

### Key Risks

1. **3 parallel CREATE paths** (H1, H5, H9, H14) — None create `agent_emotional_state` rows, none validate department against `DEPARTMENT_FLOOR_MAP`. New agents created via these paths are born without welfare tracking.

2. **3 parallel DELETE paths** (H3, H4, H6) — `agent_management_api.py` has both soft and hard delete that bypass agent_service logging and cleanup.

3. **4 shift_state mutations without validation** (H8, H10, H11, H16, H17) — No check against `VALID_SHIFT_STATES`. Node deploy/return operations (H10, H11) skip `node_agents` table management, causing roster desync.

4. **2 department reassignments without floor derivation** (H7, H12) — Agent could end up with `department='Creative & Design'` but `floor='ENGINEERING'`, breaking org chart queries.

5. **1 name rename** (H15) — `bridge_jobs.agent_name` is varchar (not FK), so renaming an agent breaks historical job references.

### Recommended Consolidation Priority

1. **P0 (Immediate)**: Consolidate all CREATE paths to use `agent_service.create_agent()` — prevents agents without welfare state.
2. **P0 (Immediate)**: Consolidate all DELETE paths to use `agent_service.delete_agent()` — ensures consistent cleanup.
3. **P1 (This sprint)**: Route all shift_state + deploy/return operations through `agent_service` — prevents node_agents desync.
4. **P1 (This sprint)**: Route department reassignments through `agent_service.update_agent()` — ensures floor auto-derivation.
5. **P2 (Next sprint)**: Add `update_counters()` and `update_avatar()` to agent_service for MEDIUM/LOW items.
6. **P2 (Next sprint)**: Add `rename_agent()` to agent_service that also updates `bridge_jobs.agent_name`.

---

## 4. Test File Exclusions

The following files contain direct SQL but are test fixtures (acceptable):

- `platform_v2/services/tests/test_agent_lifecycle.py` (INSERT/DELETE for test setup/teardown)
- `platform_v2/services/tests/test_agent_service_budget.py` (INSERT/DELETE for test setup/teardown)
