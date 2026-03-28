# Agent Centralization — Master Design Spec

**Date:** 2026-03-28
**Status:** Approved
**Scope:** Centralize all agent management into a single authoritative service, consolidate UI, add training/benchmarking, identity system, and social presence
**Effort:** 5 sub-projects, ~10-13 sessions total

---

## Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Service scope | Full lifecycle — everything agent-related | One change = one place. Prevents scattered breakage |
| Service location | platform_v2/services/agent_service.py | Follows existing service pattern, importable by all consumers |
| UI home | Department HQ (consolidated) | Already built, absorbs Employee Directory + roster |
| Training/benchmarks | Own module — Agent Academy | Too complex for a tab, includes A/B testing + fine-tuning |
| Starbase role | Hardware only, calls agent service for workforce | Clean separation: hardware vs workforce |
| Portrait style | Near-human android (95% human, subtle AI tells) for Directors | Professional, slightly uncanny, B-style aesthetic |
| Portrait generation | ComfyUI auto-generate + manual override | Baseline generation with admin fine-tuning |
| Agent types | AI Directors (department generalists) + Human staff (specialists) | Two classes with different identity/social treatment |
| Social presence | Full digital persona (C) — voice, posting, engagement | Agents as brand ambassadors per department |
| Warmboot/models | Inside agent service, not Bridge | One service controls the full agent state |

---

## Architecture Overview

```
Agent Service (platform_v2/services/agent_service.py)
│   THE single authority for all agent data and operations
│
├── Consumers (read + write through service)
│   ├── Department HQ (/tools/department-hq) — UI for management
│   ├── Agent Academy (/tools/agent-academy) — training + benchmarks
│   ├── Bridge Dispatcher — dispatch, model loading, escalation
│   ├── Agent Loop — welfare, shifts, training ticks
│   ├── Starbase Command — hardware-aware agent recommendations
│   ├── MCP Tools — external API access
│   └── Nodes (remote) — fleet agent registry
│
├── Agent Types
│   ├── AI Directors (16) — acronym names, department generalists
│   │   └── Near-human android portraits, corporate identity
│   └── Human Staff (~106) — named specialists
│       └── Full portraits, photo gallery, social personas
│
└── Data (30+ tables, all accessed through service)
    ├── Core: agents, agent_skills, agent_identity
    ├── Welfare: agent_emotional_state, agent_rest_cycles
    ├── Performance: agent_performance_rankings, dept_work_sessions
    ├── Learning: agent_learning_records, benchmark_runs
    ├── Media: agent_portraits, agent_photo_gallery
    └── Social: agent_social_profiles, agent_content_posts
```

---

## Sub-Project 1: Agent Service — Centralized Authority

### Goal
One service that owns ALL agent operations. No other file writes directly to agent tables.

### File structure
```
platform_v2/services/agent_service.py  — Main service (split if >600 lines)
platform_v2/services/agent_models.py   — Model management (load/unload/warmboot/VRAM)
platform_v2/services/agent_dispatch.py — Candidate selection, scoring, escalation
```

### Core functions

**CRUD:**
- `create_agent(name, display_name, department, model, ...)` → agent_id
- `update_agent(agent_id, **fields)` → invalidates caches, notifies consumers
- `delete_agent(agent_id)` → soft-delete, archive
- `get_agent(agent_id)` → full profile dict
- `list_agents(department=, floor=, shift_state=, skill=, search=)` → filtered list
- `get_org_chart()` → floors → departments → director + staff

**Shift lifecycle:**
- `activate(agent_id)` → shift_state = active
- `barracks(agent_id)` → shift_state = barracked
- `deploy_to_node(agent_id, node_id)` → shift_state = deployed, create node_agent
- `return_from_node(agent_id)` → shift_state = barracked, deactivate node_agent
- `wind_down(agent_id)` → shift_state = winding_down
- `cooldown(agent_id)` → shift_state = cooldown

**Skills & capabilities:**
- `add_skill(agent_id, skill_name, level)` → insert/update agent_skills
- `get_skills(agent_id)` → list of skills with levels
- `match_capability(capability)` → agents who can handle this, ranked by skill level
- `update_skill_from_benchmark(agent_id, skill, score)` → auto-level from benchmark results

**Welfare:**
- `get_welfare(agent_id)` → stress, energy, mood
- `update_welfare(agent_id, stress=, energy=, mood=)` → update emotional state
- `check_welfare_threshold(agent_id)` → bool (can this agent work?)
- `recover_idle(agent_id)` → bump energy, reduce stress

**Model management:**
- `get_model_state(agent_id)` → GPU/CPU/cold, VRAM usage
- `load_model(agent_id)` → call Ollama to load agent's model
- `unload_model(agent_id)` → call Ollama to unload
- `warmboot(agent_id)` → ensure model ready for dispatch
- `get_agents_for_hardware(gpu_vram_gb, ram_gb)` → agents whose models fit

**Dispatch support:**
- `get_candidates(capability, department)` → scored agent list for Bridge
- `score_agent(agent_id, capability)` → composite score (skills + welfare + availability)
- `get_best_agent(capability, department)` → top-scored available agent
- `recommend_node_deployment(node_id)` → ranked agents for node hardware

**Performance:**
- `get_performance(agent_id, period_days=7)` → jobs, success rate, avg response
- `get_department_performance(department)` → aggregate metrics
- `log_job_result(agent_id, capability, success, duration_ms)` → track outcome

### Refactor plan
Every file that currently does agent mutations gets refactored to call agent_service:
- `bridge_dispatcher.py` — replace ~15 agent mutation sites
- `orchestration_engine.py` — replace ~5 agent mutation sites
- `agent_loop.py` — replace ~10 agent mutation sites
- `agent_management_api.py` — absorbed into agent_service, then deprecated
- `starbase/agent_routes.py` — calls agent_service (already redirected)
- `department_hq/roster_routes.py` — calls agent_service
- `team_management/routes.py` — calls agent_service or deprecated

### The rule (enforced)
**No INSERT/UPDATE/DELETE on `agents`, `agent_skills`, `agent_emotional_state`, `agent_identity`, `node_agents` outside of agent_service.py.** Violations flagged by Code Health audit (new check).

---

## Sub-Project 2: Department HQ Consolidation

### Goal
Department HQ becomes THE single UI for all agent management. Absorbs Employee Directory.

### Changes
- Merge `team_management/` Employee Directory into Dept HQ Org Chart tab
- Enhanced agent detail panel: full profile, portrait, skills, welfare, model config, system prompt
- Roster tab: CRUD through agent_service, shift management, department transfers
- Operations tab: active dispatches, model states, warmboot queue, node deployments
- Deprecate `team_management/` module (redirect to Dept HQ)

---

## Sub-Project 3: Agent Academy

### Goal
Training, benchmarking, A/B model testing. Results feed into agent_service skill levels and dispatch scoring.

### Module: `/tools/agent_academy/`

### 5 tabs
- **Benchmarks** — Run tasks against agents, score results, rank by capability. Migrated from Starbase.
- **Training** — Skill progression Lv1-5, training programs, auto-level from benchmarks
- **Models** — Modelfile editor, system prompt designer, parameter tuning per agent
- **A/B Testing** — Compare 2 models on same task, measure quality/speed/cost. Assign winner.
- **Knowledge** — Inject domain docs into agent context, RAG per agent

### Data flow
Academy benchmark → agent_service.update_skill_from_benchmark() → Bridge dispatch scoring → best agent gets job → performance tracked → Academy suggests next training

---

## Sub-Project 4: Agent Identity & Portraits

### Goal
Complete agent profiles with AI-generated portraits matching identity.

### Two portrait styles
- **AI Directors**: Near-human android — 95% human, subtle AI tells (too-perfect skin, faint seam lines, digital iris). Professional corporate attire. Each has designed gender, ethnicity, age, build.
- **Human Staff**: Fully human — matching their name, ethnicity, gender, age in profile. Diverse, professional.

### Portrait pipeline
- Each agent has `portrait_prompt` field in profile (detailed appearance description)
- Generate via ComfyUI (RealVisXL or Juggernaut SDXL checkpoint)
- Store in `agent_portraits` table (multiple versions, admin picks primary)
- Manual override: admin can regenerate with tweaked prompt or upload custom image
- Photo gallery: human agents get lifestyle/work photos for social media use

### Data
- `agent_portraits` — id, agent_id, image_path, prompt, is_primary, generated_at
- `agent_photo_gallery` — id, agent_id, image_path, caption, category (headshot/work/casual/social), generated_at

---

## Sub-Project 5: Agent Social Presence

### Goal
Each human agent is a digital persona with writing voice, social accounts, and content posting.

### Components
- **Writing voice**: Each agent has a defined writing style (tone, vocabulary, emoji usage, topics). Stored in agent_identity.
- **Social accounts**: Connected via Social Media module. Each agent can have Twitter/LinkedIn/Instagram profiles.
- **Content generation**: Content Studio generates posts in each agent's voice. "Sofia Petrov (Security) just published a threat analysis..."
- **Auto-posting**: Social Media module schedules and posts on behalf of agents. Configurable frequency.
- **Engagement**: Agents can comment on company posts, respond to mentions. Managed through Content Studio.

### Data
- `agent_social_profiles` — id, agent_id, platform, handle, access_token, is_active
- `agent_content_posts` — id, agent_id, platform, content, media_urls, scheduled_at, posted_at, engagement_stats

### AI Director treatment
- Corporate profiles only (LinkedIn-style)
- Post department updates, achievement announcements
- No casual/lifestyle content

---

## Execution Order

| SP | Sub-project | Depends on | Priority |
|----|------------|-----------|----------|
| 1 | Agent Service | None | Do first |
| 2 | Department HQ Consolidation | SP1 | Do second |
| 3 | Agent Academy | SP1 | Do third |
| 4 | Agent Identity & Portraits | SP1 + SP2 | Do fourth |
| 5 | Agent Social Presence | SP4 | Do fifth |

## What's NOT in scope
- New agent creation (collaborative human review process, not automated)
- Adding departments beyond 16
- Cloud agent hosting
- Public-facing agent API (future)
